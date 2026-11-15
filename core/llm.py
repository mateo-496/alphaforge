"""Every LLM call goes through this module: Amazon Bedrock Converse, one `Tracer` per call.

    ask(agent, system, prompt, Schema)               one call, structured output (forced `answer` tool)
    run_tools(agent, system, prompt, tools, Schema)  tool loop: the model calls `tools`, then `answer`

Audit trail of each call:
  * CloudTrail logs every Bedrock `Converse` call by default (management event, no prompt text). The tracer keeps
    Bedrock's RequestId, which is that event's `requestID`, so each trace joins its CloudTrail record.
  * The trace itself (tokens, input, output) goes to data/traces/<day>.jsonl and, when CLOUDTRAIL_CHANNEL_ARN is
    set, to CloudTrail Lake as a custom event (PutAuditEvents), queryable with SQL next to the Converse events.
"""
import json
import logging
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TypeVar

from pydantic import BaseModel, ValidationError

from core import config, storage

log = logging.getLogger("alphaforge.llm")
T = TypeVar("T", bound=BaseModel)
TRACE_DIR = config.DATA_DIR / "traces"
LAKE_TEXT_MAX = 8_000   # chars of input / output copied into each CloudTrail Lake event (full text stays local)
_lock = threading.Lock()
_clients: dict[str, Any] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Tracer:
    """One LLM call: tokens in and out, what was sent, what came back."""
    token_in: int
    token_out: int
    input: Any
    output: Any
    agent: str = ""
    model: str = ""
    request_id: str = ""        # Bedrock RequestId = requestID of the CloudTrail `Converse` event
    ms: int = 0
    error: str | None = None
    cached: bool = False        # answer reused from agent-cache/ (same input): no Bedrock call was made
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    at: str = field(default_factory=_now)

    def emit(self) -> "Tracer":
        """Record the call. Never raises: tracing must not break an analysis."""
        try:
            TRACE_DIR.mkdir(parents=True, exist_ok=True)
            line = json.dumps(asdict(self), default=str, ensure_ascii=False)
            with _lock, open(TRACE_DIR / f"{self.at[:10]}.jsonl", "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception as e:
            log.warning("trace not written locally: %s", e)
        if config.CLOUDTRAIL_CHANNEL_ARN:
            try:
                res = _client("cloudtrail-data", config.CLOUDTRAIL_CHANNEL_ARN.split(":")[3]).put_audit_events(
                    channelArn=config.CLOUDTRAIL_CHANNEL_ARN,
                    auditEvents=[{"id": self.id, "eventData": json.dumps(self.lake_event(), default=str)}])
                for f in res.get("failed", []):
                    log.warning("CloudTrail Lake rejected trace %s: %s %s", f.get("id"), f.get("errorCode"), f.get("errorMessage"))
            except Exception as e:
                log.warning("trace not sent to CloudTrail Lake: %s", e)
        return self

    def lake_event(self) -> dict:
        """CloudTrail Lake integration event schema (eventData of PutAuditEvents)."""
        clip = lambda x: (x if isinstance(x, str) else json.dumps(x, default=str, ensure_ascii=False))[:LAKE_TEXT_MAX]
        ev = {"version": "1.0",
              "userIdentity": {"type": "AlphaForgeAgent", "principalId": self.agent or "alphaforge"},
              "userAgent": "alphaforge/core.llm",
              "eventSource": "alphaforge.llm",
              "eventName": "Converse",
              "eventTime": datetime.fromisoformat(self.at).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "UID": self.id,
              "requestParameters": {"modelId": self.model, "input": clip(self.input)},
              "responseElements": {"output": clip(self.output)},
              "recipientAccountId": config.CLOUDTRAIL_CHANNEL_ARN.split(":")[4],
              "additionalEventData": {"tokenIn": self.token_in, "tokenOut": self.token_out, "latencyMs": self.ms,
                                      "bedrockRequestId": self.request_id, "cached": self.cached}}
        if self.error:
            ev["errorMessage"] = self.error[:1000]
        return ev


def _client(service: str, region: str | None = None):
    key = f"{service}:{region or config.REGION}"
    if key not in _clients:
        import boto3
        from botocore.config import Config
        _clients[key] = boto3.client(service, region_name=region or config.REGION,
                                     config=Config(read_timeout=300, retries={"max_attempts": 4, "mode": "adaptive"}))
    return _clients[key]


_CREDENTIAL_ERRORS = ("UnrecognizedClientException", "ExpiredTokenException", "ExpiredToken", "InvalidClientTokenId")
_bad_credentials: str | None = None


class AWSCredentialsError(RuntimeError):
    pass


def converse(agent: str, system: str, messages: list[dict], *, model_id: str | None = None, max_tokens: int = 4096,
             tools: list[dict] | None = None, tool_choice: dict | None = None) -> dict:
    """One Bedrock Converse call, traced. Returns the raw response. Once AWS rejects the credentials, later calls
    fail at once with the same clear message instead of each making a doomed request (restart after fixing .env)."""
    global _bad_credentials
    if _bad_credentials:
        raise AWSCredentialsError(_bad_credentials)
    model = model_id or config.BEDROCK_MODEL_ID
    req = {"modelId": model, "system": [{"text": system}], "messages": messages,
           "inferenceConfig": {"maxTokens": max_tokens}}   # no temperature: newer Claude models reject it
    if tools:
        req["toolConfig"] = {"tools": tools, **({"toolChoice": tool_choice} if tool_choice else {})}
    sent = {"system": system, "message": messages[-1]} if len(messages) == 1 else {"message": messages[-1]}
    t0 = time.perf_counter()
    try:
        r = _client("bedrock-runtime").converse(**req)
    except Exception as e:
        Tracer(0, 0, sent, None, agent, model, ms=int((time.perf_counter() - t0) * 1000),
               error=f"{type(e).__name__}: {e}").emit()
        code = getattr(e, "response", {}).get("Error", {}).get("Code", "") if hasattr(e, "response") else ""
        if code in _CREDENTIAL_ERRORS:
            _bad_credentials = (f"AWS credentials rejected ({code}): the session token in .env has probably expired. "
                                "Refresh AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_SESSION_TOKEN and restart.")
            raise AWSCredentialsError(_bad_credentials) from e
        raise
    usage = r.get("usage", {})
    Tracer(usage.get("inputTokens", 0), usage.get("outputTokens", 0), sent, r["output"]["message"]["content"],
           agent, model, r.get("ResponseMetadata", {}).get("RequestId", ""),
           int((time.perf_counter() - t0) * 1000)).emit()
    return r


# ---------- structured output ----------
def _inline(schema: dict) -> dict:
    """Pydantic JSON schema with every $ref replaced by its definition (tool input schemas must be self-contained)."""
    defs = schema.get("$defs", {})

    def walk(x):
        if isinstance(x, dict):
            if "$ref" in x:
                return walk(defs[x["$ref"].rsplit("/", 1)[1]])
            return {k: walk(v) for k, v in x.items() if k != "$defs"}
        return [walk(v) for v in x] if isinstance(x, list) else x
    return walk(schema)


def _answer_tool(schema: type[BaseModel]) -> dict:
    return {"toolSpec": {"name": "answer", "description": "Return the final answer in this exact structure.",
                         "inputSchema": {"json": _inline(schema.model_json_schema())}}}


def _uses(msg: dict) -> list[dict]:
    return [c["toolUse"] for c in msg.get("content", []) if "toolUse" in c]


def _result(use_id: str, out: Any, ok: bool = True) -> dict:
    content = [{"json": out if isinstance(out, dict) else {"result": out}}] if ok else [{"text": str(out)}]
    return {"toolResult": {"toolUseId": use_id, "content": content, "status": "success" if ok else "error"}}


# Newer Claude models on Bedrock think by default and reject a forced tool choice ("tool" / "any") with a
# ValidationException. Such models are remembered here and called with "auto"; the prompt then asks for the tool.
_NO_FORCED: set[str] = set()
HINT = "\n\nAlways reply by calling a tool. Give your final result by calling the `answer` tool."


def _forcing_rejected(e: Exception) -> bool:
    err = getattr(e, "response", {}).get("Error", {}) if hasattr(e, "response") else {}
    msg = (err.get("Message") or "").lower()
    return err.get("Code") == "ValidationException" and ("tool_choice" in msg or "toolchoice" in msg)


def _call(agent: str, system: str, messages: list[dict], model_id: str | None, max_tokens: int, tools: list[dict],
          forced: dict) -> dict:
    """Converse with a forced tool choice, or with "auto" when the model rejects forcing."""
    model = model_id or config.BEDROCK_MODEL_ID
    if model not in _NO_FORCED:
        try:
            return converse(agent, system, messages, model_id=model, max_tokens=max_tokens, tools=tools,
                            tool_choice=forced)
        except Exception as e:
            if not _forcing_rejected(e):
                raise
            _NO_FORCED.add(model)
            log.info("%s rejects forced tool choice; using auto", model)
    return converse(agent, system, messages, model_id=model, max_tokens=max_tokens, tools=tools,
                    tool_choice={"auto": {}})


def _nudge(text: str) -> dict:
    return {"role": "user", "content": [{"text": text}]}


def ask(agent: str, system: str, prompt: str, schema: type[T], *, model_id: str | None = None,
        max_tokens: int = 4096, cache: bool = True) -> T:
    """One structured answer. A missing or invalid answer gets up to two retries with the problem shown to the model.
    The validated answer is saved under its exact input (model, system, prompt, schema) and reused next time;
    cache=False always calls the model (and does not save)."""
    if not cache:
        return _ask(agent, system, prompt, schema, model_id, max_tokens)
    model = model_id or config.BEDROCK_MODEL_ID
    ident = {"v": 1, "model": model, "system": system, "prompt": prompt, "max_tokens": max_tokens,
             "schema": schema.model_json_schema()}
    hit = storage.memo_get(f"llm/{agent}", ident)
    if hit is not None:
        try:
            out = schema.model_validate(hit)
            Tracer(0, 0, {"system": system, "message": prompt}, hit, agent, model, "cache", cached=True).emit()
            return out
        except ValidationError:
            pass
    out = _ask(agent, system, prompt, schema, model_id, max_tokens)
    storage.memo_put(f"llm/{agent}", ident, out.model_dump(mode="json"))
    return out


def _ask(agent: str, system: str, prompt: str, schema: type[T], model_id: str | None, max_tokens: int) -> T:
    messages = [{"role": "user", "content": [{"text": prompt}]}]
    for attempt in range(3):
        r = _call(agent, system + HINT, messages, model_id, max_tokens, [_answer_tool(schema)],
                  {"tool": {"name": "answer"}})
        msg = r["output"]["message"]
        use = next((u for u in _uses(msg) if u["name"] == "answer"), None)
        try:
            if use is None:
                raise ValueError("no answer tool call")
            return schema.model_validate(use["input"])
        except (ValueError, ValidationError) as e:
            if attempt == 2:
                raise ValueError(f"{agent}: no valid answer after 3 attempts ({e})") from e
            messages.append(msg)
            messages.append({"role": "user", "content": [_result(use["toolUseId"], f"Invalid answer: {e}. Call answer again.", False)]}
                            if use else _nudge("Call the `answer` tool now with your result."))
    raise AssertionError("unreachable")


@dataclass
class Tool:
    name: str
    description: str
    params: dict                     # JSON schema of the arguments
    fn: Callable[..., Any]


def run_tools(agent: str, system: str, prompt: str, tools: list[Tool], schema: type[T], *, max_turns: int = 10,
              model_id: str | None = None, max_tokens: int = 4096) -> T:
    """Tool loop. Every turn the model must call a tool; on the last turn it must call `answer`
    (asked for in the prompt when the model rejects a forced tool choice)."""
    specs = [{"toolSpec": {"name": t.name, "description": t.description, "inputSchema": {"json": t.params}}}
             for t in tools] + [_answer_tool(schema)]
    by_name = {t.name: t for t in tools}
    messages = [{"role": "user", "content": [{"text": prompt}]}]
    for turn in range(max_turns):
        last = turn == max_turns - 1
        r = _call(agent, system + HINT, messages, model_id, max_tokens, specs,
                  {"tool": {"name": "answer"}} if last else {"any": {}})
        msg = r["output"]["message"]
        messages.append(msg)
        results = []
        for u in _uses(msg):
            if u["name"] == "answer":
                try:
                    return schema.model_validate(u["input"])
                except ValidationError as e:
                    if last:
                        raise
                    results.append(_result(u["toolUseId"], f"Invalid answer: {e}. Call answer again.", False))
            elif u["name"] in by_name:
                try:
                    results.append(_result(u["toolUseId"], by_name[u["name"]].fn(**u["input"])))
                except Exception as e:
                    results.append(_result(u["toolUseId"], f"{type(e).__name__}: {e}", False))
            else:
                results.append(_result(u["toolUseId"], f"Unknown tool {u['name']}", False))
        messages.append({"role": "user", "content": results} if results else
                        _nudge("Call one of the tools, or the `answer` tool now if you are done." if turn < max_turns - 2
                               else "Call the `answer` tool now with your result."))
    raise RuntimeError(f"{agent}: no answer after {max_turns} turns")
