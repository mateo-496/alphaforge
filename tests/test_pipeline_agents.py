"""Full pipeline with every external call faked (tests/fakes.py): every agent's real code path runs."""
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
    monkeypatch.setattr(config, "STORAGE", "local")


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
    assert set(phases) >= {"assets", "firms", "scenarios", "macro", "countries", "risk", "remediation"}
    nv = next(h for h in r["by_holding"] if h["ticker"] == "NVDA")
    assert not nv["estimated"] and nv["f"] == 1 / 8          # one channel with a VERIFIED quote; severity unused
    assert next(h for h in r["by_holding"] if h["ticker"] == "RY.TO")["estimated"]
    twn = next(c for c in r["by_country"] if c["iso3"] == "TWN")
    assert 0 <= twn["g"] <= 1 and twn["gpr"] and "GPR" in twn["method"] and twn["driver"]
    # Cedric's formula, recomputed from the reported inputs: same objective and concern
    from tools.portfolio_score import portfolio_scores
    again = portfolio_scores(*(r["inputs"][k] for k in ("A1", "A2", "A3")), "low_moderate", conf=tuple(r["conf"]))
    assert (again["objective"], again["personalized"]) == (r["objective"], r["score"])
    assert r["inputs"]["A1"] is not None and r["inputs"]["A3"] == 1 / 8   # World Bank macro feeds A1; NVDA's flags A3
    assert all(0 <= h["R"] <= 100 for h in r["by_holding"]) and all(0 <= c["R"] <= 100 for c in r["by_country"])
    assert abs(sum(h["share"] for h in r["by_holding"]) - 1) < 1e-9
    assert r["summary_by"] == "risk agent" and not any("73%" in s["text"] for s in r["summary"]) and len(r["summary"]) == 3   # invented number dropped
    assert r["verdict"]["status"] == "act" and r["verdict"]["tolerance"] == 43 and any("Taiwan" in c["text"] for c in r["checks"])
    for w in r["remediation"]:                                 # bond funds for a 4-year, capital-preservation profile
        assert w["to"] in ("XBB.TO", "ZST.TO", "AGG", "BND", "TLT") and w["score_after"] <= w["score_before"] + 1e-9
    assert r["signposts"] and r["firms"]["NVDA"]["claims"][0]["verified"]
    # scenario agent: the scenario whose quote is in no source is dropped
    assert {s["id"] for s in r["scenarios"]} == {"taiwan-blockade", "us-canada-tariffs"}
    # filing-risk agent: every kept quote is the filing's text (the bad one was repaired from a segment)
    rf = r["firms"]["NVDA"]["risk_factors"]
    assert rf["status"] == "ok" and len(rf["risks"]) == 2 and all(x["quote"] in fakes.RISK_TEXT for x in rf["risks"])
    assert "market" not in r
    # country risk + source agents: World Bank facts, computed macro score, reachable sources only, no invented number
    m = r["macro"]["countries"]
    assert m["USA"]["macro"]["score"] > 0 and [x["name"] for x in m["USA"]["sources"]] == ["IMF country page"]
    assert m["TWN"]["macro"] is None and "300%" not in " ".join(v["note"] for v in m.values())
    # geopolitical claims agent: only the claim whose quote is in the data survives
    assert r["gpr_claims"] and all(len(g["claims"]) == 1 and g["summary"] == "" for g in r["gpr_claims"].values())
    # remediation agent: invalid ticker dropped, every kept swap lowers the score
    assert all(w["from"] in ("NVDA", "RY.TO", "SPY") and w["score_after"] < w["score_before"] for w in r["agent_swaps"])


def test_agent_failures_never_break_the_report(env, monkeypatch):
    from core import llm

    def down(*a, **k):
        raise RuntimeError("Bedrock down")
    monkeypatch.setattr(llm, "ask", down)
    rec = _run([{"ticker": "NVDA", "weight": 1.0}])
    r = rec["result"]
    assert rec["status"] == "done" and r["summary_by"] == "code"
    assert all(c["driver"] for c in r["by_country"])   # factual fallback drivers
    assert r["agent_swaps"] is None
    assert r["macro"]["meta"]["error"] and "Central government debt" in r["macro"]["countries"]["USA"]["note"]
    assert all(g["error"] for g in r["gpr_claims"].values())
    assert r["firms"]["NVDA"]["risk_factors"]["status"] == "error"


def test_no_immediate_danger(env):
    """A portfolio within tolerance, with no broken limit, gets an explicit all-clear and no trade."""
    rec = _run([{"ticker": "XBB.TO", "weight": 1.0}], risk_level=5, objective_level=4, horizon_years=15, avoid_countries=[])
    r = rec["result"]
    assert r["verdict"]["tests"][0]["ok"], r["score"]
    if r["verdict"]["clear"]:
        assert r["verdict"]["status"] == "clear" and r["remediation"] == []
    else:   # only the market test can fail here
        assert r["verdict"]["status"] == "watch" and r["remediation"] == []


def test_every_split_is_tagged_with_its_tier(env):
    """XBRL with a region line split by the prior, filing text blended at 0.8, funds and gold handled, no REGION rows."""
    rec = _run([{"ticker": "AAPL", "weight": .4}, {"ticker": "JPM", "weight": .3}, {"ticker": "SPY", "weight": .2},
                {"ticker": "GLD", "weight": .1}], avoid_countries=[])
    assert rec["status"] == "done", rec["error"]
    r = rec["result"]
    tier = {h["ticker"]: h["tier"] for h in r["by_holding"]}
    assert tier["AAPL"]["code"] == "xbrl" and tier["AAPL"]["lambda"] == 1
    assert tier["JPM"]["code"] == "text" and tier["JPM"]["lambda"] == .8
    assert tier["SPY"]["code"] == "returns" and tier["GLD"]["code"] == "none"
    cw = r["assets"]
    assert all(abs(sum(a["country_weights"].values()) - 1) < 1e-6 for a in cw.values())
    assert not any(c.startswith("REGION:") for a in cw.values() for c in a["country_weights"])
    assert cw["AAPL"]["country_weights"]["DEU"] > 0                    # Europe split by the prior, not dropped
    jpm = cw["JPM"]["country_weights"]                                  # 78% at home, said by the verified quote
    assert .78 * .8 < jpm["USA"] < .78 * .8 + .2 and cw["GLD"]["country_weights"] == {"Other": 1.0}
