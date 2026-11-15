"""Full pipeline with every external call faked (tests/fakes.py): real agent code paths, no synthetic data module."""
import asyncio

import pytest

from core import config, storage
from tests import fakes
from web import pipeline, store


@pytest.fixture
def env(tmp_path, monkeypatch):
    fakes.install(monkeypatch)
    monkeypatch.setattr(storage, "LOCAL_ROOT", tmp_path)
    monkeypatch.setattr(store, "ROOT", tmp_path)
    monkeypatch.setattr(store.runs, "root", tmp_path / "runs")
    monkeypatch.setattr(store.runs, "_runs", {})
    monkeypatch.setattr(config, "SCENARIO_USE_MOCK", True)   # scenario agent covered by its own tests
    import tools.market_cache as mc
    monkeypatch.setattr(mc, "LOCAL_ROOT", tmp_path)
    monkeypatch.delenv("S3_BUCKET", raising=False)


def _run(holdings, **profile):
    prof = {"horizon_years": 4, "risk_level": 2, "objective_level": 1, "max_single_weight": .3,
            "excluded_themes": [], "avoid_countries": ["TWN"], **profile}
    from core.schemas import AnalysisRequest
    req = AnalysisRequest(portfolio={"holdings": holdings}, profile=prof, as_of="2026-11-12")
    rid = store.runs.create(req.model_dump() | {"checks": []})
    asyncio.run(pipeline.run(rid))
    return store.runs.get(rid)


def test_full_chain(env):
    rec = _run([{"ticker": "NVDA", "weight": .5}, {"ticker": "RY.TO", "weight": .3}, {"ticker": "SPY", "weight": .2}])
    assert rec["status"] == "done", rec["error"]
    r = rec["result"]
    phases = [e["phase"] for e in rec["events"] if e["kind"] == "phase" and e["status"] == "done"]
    assert set(phases) >= {"assets", "firms", "market", "scenarios", "countries", "risk", "remediation"}
    nv = next(h for h in r["by_holding"] if h["ticker"] == "NVDA")
    assert not nv["estimated"] and nv["f"] == 1 / 8          # one channel with a VERIFIED quote; severity unused
    assert next(h for h in r["by_holding"] if h["ticker"] == "RY.TO")["estimated"]
    twn = next(c for c in r["by_country"] if c["iso3"] == "TWN")
    assert 0 <= twn["g"] <= 1 and twn["gpr"] and "GPR" in twn["method"] and twn["driver"]
    # additive: holding points and country + filing points both sum to the score
    assert abs(sum(h["points"] for h in r["by_holding"]) - r["score"]) < 0.1
    assert abs(sum(c["points"] for c in r["by_country"]) + r["firm_points"] - r["score"]) < 0.1
    assert r["summary_by"] == "risk agent" and not any("73%" in s for s in r["summary"])   # invented number dropped
    assert r["verdict"]["status"] == "act" and any("Taiwan" in c["text"] for c in r["checks"])
    for w in r["remediation"]:                                 # bond funds for a 4-year, capital-preservation profile
        assert w["to"] in ("XBB.TO", "ZST.TO", "AGG", "BND", "TLT") and w["score_after"] <= w["score_before"] + 1e-9
    assert r["signposts"] and r["firms"]["NVDA"]["claims"][0]["verified"]


def test_agent_failures_never_break_the_report(env, monkeypatch):
    from agents import geopolitical_agent, risk_agent

    class Down:
        def __init__(self, *a, **k): pass
        def __call__(self, *a, **k): raise RuntimeError("Bedrock down")
    for m in (geopolitical_agent, risk_agent):
        monkeypatch.setattr(m, "Agent", Down)
    rec = _run([{"ticker": "NVDA", "weight": 1.0}])
    r = rec["result"]
    assert rec["status"] == "done" and r["summary_by"] == "code"
    assert all(c["driver"] for c in r["by_country"])   # factual fallback drivers


def test_no_immediate_danger(env):
    """A portfolio within tolerance, with no broken limit, gets an explicit all-clear and no trade."""
    rec = _run([{"ticker": "XBB.TO", "weight": 1.0}], risk_level=5, objective_level=4, horizon_years=15, avoid_countries=[])
    r = rec["result"]
    assert r["verdict"]["tests"][0]["ok"], r["score"]
    if r["verdict"]["clear"]:
        assert r["verdict"]["status"] == "clear" and r["remediation"] == []
        assert any("No immediate danger" in s for s in r["summary"])
    else:   # only the market test can fail here
        assert r["verdict"]["status"] == "watch" and r["remediation"] == []


def test_region_rows_are_scored_and_labelled(env):
    """A filing that reports 'Europe' as one line keeps that line; its hazard is the mean of Europe's main countries."""
    rec = _run([{"ticker": "AAPL", "weight": 1.0}], avoid_countries=[])
    r = rec["result"]
    eu = next(c for c in r["by_country"] if c["iso3"] == "REGION:EUROPE")
    assert eu["name"] == "Europe (region)" and 0 <= eu["g"] <= 1 and eu["points"] > 0
    assert abs(sum(c["points"] for c in r["by_country"]) + r["firm_points"] - r["score"]) < 0.1
