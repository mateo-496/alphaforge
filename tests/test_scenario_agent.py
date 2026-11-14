"""Real (non-mock) scenario path with the network and Bedrock stubbed."""
import types

import httpx
import pytest

from agents import scenario_agent
from core import config, storage
from core.schemas import DraftScenario, DraftScenarioSet, ScenarioEvidence
from tools import scenario_sources as src

PAGE = """<html><body><nav>Menu Home About</nav><main>
<h2>Top risk: a Taiwan crisis</h2>
<p>China is likely to step up military pressure on Taiwan, raising the risk of a blockade in 2026.</p>
<p>Our newsletter is great and you should subscribe today to receive more of it.</p>
<p>US tariffs on Canada and Mexico could escalate into a broader trade war across North America.</p>
<p>Russia may test NATO resolve in the Baltics, and sanctions on Iran keep oil markets on edge this year.</p>
<p>Elections across Latin America raise the risk of fiscal crises and capital controls in several economies.</p>
</main></body></html>"""


@pytest.fixture
def offline(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "LOCAL_ROOT", tmp_path)
    monkeypatch.setattr(config, "SCENARIO_USE_MOCK", False)
    calls = {"n": 0}

    def fake_get(url, **kw):
        calls["n"] += 1
        if "iacoviello" in url:
            raise httpx.ConnectError("offline")
        return types.SimpleNamespace(text=PAGE, url=url, raise_for_status=lambda: None)
    monkeypatch.setattr(src.httpx, "get", fake_get)

    def ev(sid, q):
        return [ScenarioEvidence(source_id=sid, quote=q)]
    draft = DraftScenarioSet(scenarios=[
        DraftScenario(id="taiwan-blockade", name="Taiwan blockade", summary="s", countries={"twn": 1.2, "CHN": .8},
                      channels=["conflict_exposure"], likelihood=.08, impact=5, signposts=["a"],
                      evidence=ev("eurasia_top_risks", "raising the risk of a blockade in 2026")),
        DraftScenario(id="invented", name="Invented risk", summary="s", countries={"FRA": 1},
                      channels=["regulatory"], likelihood=.2, impact=2, signposts=["a"],
                      evidence=ev("cfr_pps", "a sentence that is not in the source text at all")),
    ])
    seen = {}

    class FakeAgent:
        def __call__(self, prompt, structured_output_model=None):
            seen["prompt"] = prompt
            return types.SimpleNamespace(structured_output=draft)
    monkeypatch.setattr(scenario_agent, "build_agent", lambda: FakeAgent())
    return calls, seen


def test_single_call_verifies_quotes_and_caches_inputs(offline):
    calls, seen = offline
    events = []
    d, rec = scenario_agent.run(n=12, week="2026-W46", on_event=lambda *e: events.append(e))
    assert [s.id for s in d.scenarios] == ["taiwan-blockade"] and rec["dropped_unverified"] == ["invented"]
    t = d.scenarios[0]
    assert t.countries == {"TWN": 1.0, "CHN": .8} and t.evidence[0].quote_verified and t.evidence[0].url
    assert "newsletter" not in seen["prompt"] and "Menu Home" not in seen["prompt"]   # only risk paragraphs
    assert len(seen["prompt"]) < 40_000
    assert ("llm", "start") in [e[:2] for e in events]
    first = calls["n"]
    scenario_agent.run(n=12, week="2026-W46")          # same week: sources from cache, only GPR retried
    assert calls["n"] == first + 1


def test_pipeline_saves_query_and_week(offline):
    from pipelines.scenarios import run as sc
    s = sc.generate(force=True)
    keys = storage.list_keys("scenarios/")
    assert any("/queries/" in k for k in keys) and any(k.endswith("latest.json") for k in keys)
    assert not s.mock and s.scenarios[0].id == "taiwan-blockade"


def test_summary_hard_limit():
    long = "China blockades Taiwan and halts chip exports. " * 12
    out = scenario_agent.clip(long)
    assert len(out) <= 350 and out.endswith(".")
    assert scenario_agent.clip("word " * 100).endswith("…") and len(scenario_agent.clip("word " * 100)) <= 351
