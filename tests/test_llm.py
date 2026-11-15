"""core.llm against a fake Bedrock: structured output, tool loop, one trace per call, CloudTrail Lake event."""
import json

import pytest
from pydantic import BaseModel

from core import config, llm


class Out(BaseModel):
    answer: str
    n: int


class FakeBedrock:
    def __init__(self, replies):
        self.replies, self.requests = list(replies), []

    def converse(self, **req):
        self.requests.append(json.loads(json.dumps(req)))   # snapshot: the caller keeps appending to messages
        content = self.replies.pop(0)
        return {"output": {"message": {"role": "assistant", "content": content}}, "stopReason": "tool_use",
                "usage": {"inputTokens": 100, "outputTokens": 20, "totalTokens": 120},
                "ResponseMetadata": {"RequestId": f"req-{len(self.requests)}"}}


class FakeLake:
    def __init__(self):
        self.calls = []

    def put_audit_events(self, **kw):
        self.calls.append(kw)
        return {"successful": [{"id": e["id"]} for e in kw["auditEvents"]], "failed": []}


def use(name, inp, uid="t1"):
    return [{"toolUse": {"toolUseId": uid, "name": name, "input": inp}}]


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(llm, "_NO_FORCED", set())
    def install(replies):
        bed, lake = FakeBedrock(replies), FakeLake()
        monkeypatch.setattr(llm, "_client", lambda service, region=None: bed if service == "bedrock-runtime" else lake)
        return bed, lake
    return install


def traces():
    return [json.loads(line) for p in sorted(llm.TRACE_DIR.glob("*.jsonl")) for line in p.read_text().splitlines()]


def test_ask_returns_validated_object_and_traces(fake):
    bed, _ = fake([use("answer", {"answer": "ok", "n": 3})])
    assert llm.ask("unit", "sys", "hello", Out) == Out(answer="ok", n=3)
    req = bed.requests[0]
    assert req["toolConfig"]["toolChoice"] == {"tool": {"name": "answer"}} and "temperature" not in req["inferenceConfig"]
    [t] = traces()
    assert (t["token_in"], t["token_out"], t["agent"], t["request_id"]) == (100, 20, "unit", "req-1")
    assert t["input"]["system"].startswith("sys") and t["output"][0]["toolUse"]["input"] == {"answer": "ok", "n": 3}


def test_invalid_answer_gets_one_retry(fake):
    bed, _ = fake([use("answer", {"answer": "x"}), use("answer", {"answer": "x", "n": 1}, "t2")])
    assert llm.ask("unit", "sys", "p", Out).n == 1
    last = bed.requests[1]["messages"][-1]["content"][0]["toolResult"]
    assert last["toolUseId"] == "t1" and last["status"] == "error" and len(traces()) == 2


def test_tool_loop_calls_tools_then_answers(fake):
    seen = []
    tools = [llm.Tool("search", "s", {"type": "object", "properties": {"q": {"type": "string"}}},
                      lambda q: seen.append(q) or {"hits": 2}),
             llm.Tool("boom", "b", {"type": "object", "properties": {}}, lambda: 1 / 0)]
    bed, _ = fake([use("search", {"q": "China"}), use("boom", {}, "t2"), use("answer", {"answer": "done", "n": 2}, "t3")])
    assert llm.run_tools("unit", "sys", "go", tools, Out).answer == "done"
    assert seen == ["China"]
    r1 = bed.requests[1]["messages"][-1]["content"][0]["toolResult"]
    r2 = bed.requests[2]["messages"][-1]["content"][0]["toolResult"]
    assert r1["content"] == [{"json": {"hits": 2}}] and r2["status"] == "error"
    assert bed.requests[0]["toolConfig"]["toolChoice"] == {"any": {}} and len(traces()) == 3


def test_last_turn_forces_answer(fake):
    tools = [llm.Tool("search", "s", {"type": "object", "properties": {}}, lambda: {})]
    bed, _ = fake([use("search", {}), use("answer", {"answer": "a", "n": 0}, "t2")])
    llm.run_tools("unit", "sys", "go", tools, Out, max_turns=2)
    assert bed.requests[1]["toolConfig"]["toolChoice"] == {"tool": {"name": "answer"}}


def test_cloudtrail_lake_event(fake, monkeypatch):
    monkeypatch.setattr(config, "CLOUDTRAIL_CHANNEL_ARN", "arn:aws:cloudtrail:us-east-1:123456789012:channel/abc")
    _, lake = fake([use("answer", {"answer": "ok", "n": 1})])
    llm.ask("geopolitical", "sys", "x" * 20_000, Out)
    [call] = lake.calls
    assert call["channelArn"].endswith("channel/abc")
    ev = json.loads(call["auditEvents"][0]["eventData"])
    assert ev["recipientAccountId"] == "123456789012" and ev["eventSource"] == "alphaforge.llm"
    assert ev["userIdentity"]["principalId"] == "geopolitical" and ev["eventTime"].endswith("Z")
    assert ev["additionalEventData"]["tokenIn"] == 100 and ev["additionalEventData"]["bedrockRequestId"] == "req-1"
    assert len(ev["requestParameters"]["input"]) <= llm.LAKE_TEXT_MAX


def test_failed_call_is_traced_and_raised(fake, monkeypatch):
    class Down:
        def converse(self, **kw):
            raise RuntimeError("throttled")
    monkeypatch.setattr(llm, "_client", lambda service, region=None: Down())
    with pytest.raises(RuntimeError):
        llm.ask("unit", "sys", "p", Out)
    assert traces()[0]["error"] == "RuntimeError: throttled"


def test_schema_refs_are_inlined():
    from core.schemas import DraftScenarioSet
    s = json.dumps(llm._answer_tool(DraftScenarioSet))
    assert "$ref" not in s and "$defs" not in s


def test_models_that_reject_forced_tool_choice_fall_back_to_auto(fake, monkeypatch):
    """Newer Claude models on Bedrock reject toolChoice tool/any: retry with auto, remember it, nudge if no tool call."""
    from botocore.exceptions import ClientError
    monkeypatch.setattr(llm, "_NO_FORCED", set())
    bed, _ = fake([[{"text": "Here is my answer: ok"}], use("answer", {"answer": "ok", "n": 1}, "t2"),
                   use("answer", {"answer": "again", "n": 2}, "t3")])
    real = bed.converse

    def converse(**req):
        if "auto" not in req["toolConfig"]["toolChoice"]:
            raise ClientError({"Error": {"Code": "ValidationException",
                                         "Message": 'tool_choice: type "tool" and "any" are not supported'}}, "Converse")
        return real(**req)
    bed.converse = converse
    assert llm.ask("unit", "sys", "p", Out, cache=False).answer == "ok"   # text-only reply -> nudged -> answer
    assert bed.requests[1]["messages"][-1]["content"][0]["text"].startswith("Call the `answer` tool")
    assert llm.ask("unit", "sys", "p", Out, cache=False).answer == "again"   # remembered: auto straight away
    assert all(r["toolConfig"]["toolChoice"] == {"auto": {}} for r in bed.requests)
    assert "answer` tool" in bed.requests[0]["system"][0]["text"]


def test_other_validation_errors_are_not_swallowed(fake, monkeypatch):
    from botocore.exceptions import ClientError
    monkeypatch.setattr(llm, "_NO_FORCED", set())

    class Bad:
        def converse(self, **kw):
            raise ClientError({"Error": {"Code": "ValidationException", "Message": "Input is too long"}}, "Converse")
    monkeypatch.setattr(llm, "_client", lambda service, region=None: Bad())
    with pytest.raises(ClientError):
        llm.ask("unit", "sys", "p", Out)


def test_expired_credentials_fail_fast_with_a_clear_message(monkeypatch):
    from botocore.exceptions import ClientError
    monkeypatch.setattr(llm, "_bad_credentials", None)
    calls = []

    class Expired:
        def converse(self, **kw):
            calls.append(1)
            raise ClientError({"Error": {"Code": "UnrecognizedClientException", "Message": "invalid token"}}, "Converse")
    monkeypatch.setattr(llm, "_client", lambda service, region=None: Expired())
    for _ in range(3):
        with pytest.raises(llm.AWSCredentialsError, match="AWS_SESSION_TOKEN"):
            llm.ask("unit", "sys", "p", Out)
    assert len(calls) == 1


def test_same_input_is_answered_from_the_saved_answer(fake):
    """Second identical ask: no Bedrock call, same answer, traced as cached (token 0)."""
    bed, _ = fake([use("answer", {"answer": "ok", "n": 1})])
    first = llm.ask("unit", "sys", "same", Out)
    assert llm.ask("unit", "sys", "same", Out) == first
    assert len(bed.requests) == 1
    t = traces()
    assert [x["cached"] for x in t] == [False, True] and t[1]["token_in"] == 0


def test_any_change_in_the_input_asks_again(fake, monkeypatch):
    """Prompt, system prompt and model are all part of the key; LLM_CACHE=0 and cache=False always ask."""
    bed, _ = fake([use("answer", {"answer": str(i), "n": i}, f"t{i}") for i in range(6)])
    llm.ask("unit", "sys", "p", Out)
    llm.ask("unit", "sys", "p2", Out)
    llm.ask("unit", "sys2", "p", Out)
    llm.ask("unit", "sys", "p", Out, model_id="other-model")
    llm.ask("unit", "sys", "p", Out, cache=False)
    monkeypatch.setattr(config, "LLM_CACHE", False)
    llm.ask("unit", "sys", "p", Out)
    assert len(bed.requests) == 6


def test_failed_answers_are_not_saved(fake):
    """No valid answer after 3 attempts raises and saves nothing: the next run asks again."""
    bed, _ = fake([use("answer", {"answer": "x"}, f"t{i}") for i in range(3)] + [use("answer", {"answer": "ok", "n": 1})])
    with pytest.raises(ValueError):
        llm.ask("unit", "sys", "p", Out)
    assert llm.ask("unit", "sys", "p", Out).answer == "ok" and len(bed.requests) == 4
