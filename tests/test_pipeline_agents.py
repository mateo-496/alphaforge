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
    again = portfolio_scores(*(r["inputs"][k] for k in ("A1", "A2", "A3")), "low_moderate", conf=tuple(r["conf"]),
                             firm_share=r["firm_share"])
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
    assert r["agent_status"] == "unavailable"
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


def test_form_trade_preferences():
    from starlette.datastructures import FormData
    from web.app import build_request

    form = FormData([("ticker", "NVDA"), ("amount", "100"), ("protected_holdings", "NVDA"),
                     ("max_turnover", "10"), ("replacement_types", "etf_bond")])
    request, errors, _ = build_request(form)
    assert not errors
    assert request.profile.protected_holdings == ["NVDA"]
    assert request.profile.max_turnover == .1
    assert request.profile.replacement_types == ["etf_bond"]

    invalid = FormData([("ticker", "NVDA"), ("amount", "100"), ("protected_holdings", "SPY")])
    request, errors, _ = build_request(invalid)
    assert request is None and "Holdings to keep must be in the portfolio." in errors


def test_pipeline_respects_trade_preferences(env):
    rec = _run([{"ticker": "NVDA", "weight": .6}, {"ticker": "RY.TO", "weight": .4}],
               protected_holdings=["NVDA"], max_turnover=.1, replacement_types=["etf_bond"])
    assert rec["status"] == "done", rec["error"]
    result = rec["result"]
    assert result["style"]["prefer"] == ["etf_bond"]
    assert sum(swap["move"] for swap in result["remediation"]) <= .1 + 1e-9
    for swap in result["remediation"] + (result["agent_swaps"] or []):
        assert swap["from"] != "NVDA"
        assert swap["to"] in ("XBB.TO", "ZST.TO", "AGG", "BND", "TLT")
        assert swap["move"] <= .1 + 1e-9


def test_pipeline_sends_verified_reports_to_remediation(env, monkeypatch):
    import json
    from core import llm

    captured = {}
    original = llm.ask

    def capture(agent, system, prompt, schema, **kwargs):
        if agent == "remediation":
            captured.update(json.loads(prompt))
        return original(agent, system, prompt, schema, **kwargs)

    monkeypatch.setattr(llm, "ask", capture)
    rec = _run([{"ticker": "NVDA", "weight": .8}, {"ticker": "RY.TO", "weight": .2}],
               protected_holdings=["RY.TO"], max_turnover=.2)
    assert rec["status"] == "done" and rec["result"]["agent_status"] == "completed"
    assert captured["profile"]["protected_holdings"] == ["RY.TO"]
    assert captured["profile"]["max_turnover"] == .2
    assert captured["score"] == pytest.approx(rec["result"]["objective"], abs=.1)
    assert captured["countries"] and captured["holdings"][0]["exposure"]
    assert all(candidate["exposure"] is not None for candidate in captured["candidates"])
    assert all(candidate["exposure"].get("TWN", 0) < .05 for candidate in captured["candidates"])
    assert any(item["kind"] == "Company filing" and item["ticker"] == "NVDA" for item in captured["evidence"])

    from fastapi.testclient import TestClient
    from web.app import app
    source = next(item for item in captured["evidence"] if item["kind"] == "Company filing")
    rec["result"]["agent_swaps"] = [{"from": "NVDA", "to": "AGG", "fraction": .25, "move": .2,
                                      "score_before": 80, "score_after": 70, "rationale": "Illustrative trade.",
                                      "evidence": [source]}]
    response = TestClient(app).get(f"/runs/{rec['id']}/result")
    assert response.status_code == 200
    assert source["quote"] in response.text and source["url"] in response.text


def test_pipeline_reports_remaining_conflicts_and_profile_preferences(env, monkeypatch):
    from fastapi.testclient import TestClient
    from agents import remediation_agent
    from core.schemas import AnalysisRequest
    from web.app import app, profile_checks
    from web import recommend

    req = AnalysisRequest(portfolio={"holdings": [{"ticker": "NVDA", "weight": .8},
                                                   {"ticker": "SPY", "weight": .2}]},
                          profile={"risk_level": 5, "max_single_weight": .4, "max_turnover": .2,
                                   "protected_holdings": ["SPY"], "replacement_types": ["etf_bond"],
                                   "avoid_countries": ["TWN"]}, as_of="2026-11-12")
    rid = store.runs.create(req.model_dump() | {"checks": profile_checks(req)})
    trade = {"from": "NVDA", "to": "AGG", "fraction": .25, "move": .2, "kind": "profile",
             "score_before": 80, "score_after": 70, "why_sell": "Reduce the holding.", "why_buy": "Bond fund."}
    alternative = {"from": "NVDA", "to": "AGG", "fraction": .125, "move": .1, "evidence": [],
                   "score_before": 80, "score_after": 75, "rationale": "Alternative trade."}
    monkeypatch.setattr(recommend, "propose", lambda *args, **kwargs: [dict(trade)])
    monkeypatch.setattr(remediation_agent, "propose", lambda *args, **kwargs: [dict(alternative)])
    asyncio.run(pipeline.run(rid))
    rec = store.runs.get(rid)
    assert rec["status"] == "done", rec["error"]
    result = rec["result"]
    assert {item["id"] for item in result["profile_outcome"]["remaining"]} >= {"single:NVDA", "country:TWN"}
    assert "20.0% of the 20.0% limit" in result["remediation"][0]["profile_notes"][0]
    assert "10.0% of the 20.0% limit" in result["agent_swaps"][0]["profile_notes"][0]
    assert any("70%" in item["text"] for item in result["agent_swaps"][0]["conflict_changes"])
    response = TestClient(app).get(f"/runs/{rid}/result")
    assert response.status_code == 200
    assert "Still unresolved after proposed changes" in response.text
    assert "Holdings kept: SPY" in response.text
    assert "selected replacement types" in response.text
    result["checks"] = []
    result["profile_outcome"]["new"] = [{"id": "volatility:AGG", "ticker": "AGG", "text": "AGG exceeds volatility limit."}]
    response = TestClient(app).get(f"/runs/{rid}/result")
    assert "New conflicts after the proposed changes" in response.text
    assert "AGG exceeds volatility limit." in response.text


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


def test_country_notes_and_drivers_are_saved_per_country(env, monkeypatch):
    """Second portfolio sharing countries with the first: saved notes / drivers are reused, only new countries are
    asked for, and the reused text is the same."""
    from core import llm
    asked = []

    def counting(agent, system, prompt, schema, **kw):
        if schema.__name__ in ("CountryNotes", "CountryDrivers"):
            asked.append((schema.__name__, sorted(f["country"] for f in fakes.json.loads(prompt))))
        return fakes.fake_ask(agent, system, prompt, schema, **kw)
    monkeypatch.setattr(llm, "ask", counting)
    holdings = [{"ticker": "NVDA", "weight": .5}, {"ticker": "RY.TO", "weight": .3}, {"ticker": "SPY", "weight": .2}]
    first = _run(holdings)["result"]
    n_first = len(asked)
    assert n_first == 2
    again = _run(holdings)["result"]
    assert len(asked) == n_first                                  # same countries: no call at all
    drv = lambda r: {c["iso3"]: c["driver"] for c in r["by_country"]}
    assert drv(again) == drv(first)
    assert {c: v["note"] for c, v in again["macro"]["countries"].items()} == \
           {c: v["note"] for c, v in first["macro"]["countries"].items()}


def _post(client, holdings: dict, **extra):
    form = {"mode": "weight", "as_of": "2026-11-12", "risk_level": "3", "horizon_years": "10", "objective_level": "3",
            "max_single_weight": "100", "ticker": list(holdings), "amount": [str(v) for v in holdings.values()], **extra}
    r = client.post("/runs", data=form, follow_redirects=False)
    assert r.status_code == 303, r.text[:300]
    return r.headers["location"].rsplit("/", 1)[-1].split("?")[0]


def _wait(client, rid):
    import time
    for _ in range(300):
        if client.get(f"/runs/{rid}/events").json()["status"] in ("done", "error"):
            return store.runs.get(rid)
        time.sleep(0.05)
    raise AssertionError("run did not finish")


def test_same_analysis_reuses_the_finished_run(env, monkeypatch):
    """Same holdings (any order), profile and date: redirected to the finished run, no new run. A different weight,
    'run again', an expired entry or RUN_CACHE_DAYS=0 start a fresh one."""
    from fastapi.testclient import TestClient
    from web import app as A
    with TestClient(A.app) as c:
        first = _post(c, {"NVDA": 50, "RY.TO": 30, "SPY": 20})
        rec = _wait(c, first)
        assert rec["status"] == "done" and A._complete(rec)
        n = len(list((store.runs.root).glob("*/run.json")))
        assert _post(c, {"SPY": 20, "NVDA": 50, "RY.TO": 30}) == first          # order-free, nothing recomputed
        assert len(list((store.runs.root).glob("*/run.json"))) == n
        loc = c.post("/runs", data={"mode": "weight", "as_of": "2026-11-12", "risk_level": "3", "horizon_years": "10",
                                    "objective_level": "3", "max_single_weight": "100", "ticker": ["NVDA", "RY.TO", "SPY"],
                                    "amount": ["50", "30", "20"]}, follow_redirects=False).headers["location"]
        assert loc == f"/runs/{first}?replay=1"
        page = c.get(loc).text                                   # replay: progress shown, report filled in by run.js
        assert 'data-status="replay"' in page and 'id="progress" >' in page and "Geopolitical risk report" not in page
        page = c.get(f"/runs/{first}").text                      # plain link: the report at once
        assert 'data-status="done"' in page and "Run this analysis again" in page
        other = _post(c, {"NVDA": 40, "RY.TO": 40, "SPY": 20})
        assert other != first
        _wait(c, other)
        r = c.post(f"/runs/{first}/rerun", follow_redirects=False)
        fresh = r.headers["location"].rsplit("/", 1)[-1]
        assert fresh != first and _wait(c, fresh)["request"]["portfolio"] == rec["request"]["portfolio"]
        assert _post(c, {"NVDA": 50, "RY.TO": 30, "SPY": 20}) == fresh           # the newest complete run is reused
        store.runs.get(fresh)["created"] -= 8 * 86400                            # older than RUN_CACHE_DAYS (7)
        newer = _post(c, {"NVDA": 50, "RY.TO": 30, "SPY": 20})
        assert newer != fresh
        _wait(c, newer)
        monkeypatch.setattr(config, "RUN_CACHE_DAYS", 0)
        assert _post(c, {"NVDA": 50, "RY.TO": 30, "SPY": 20}) != newer


def test_partial_run_is_not_reused(env, monkeypatch):
    """A run with a filing still reading in the background is shown, not reused: the next request reruns."""
    from fastapi.testclient import TestClient
    from web import app as A, firms
    real = firms.analyse
    monkeypatch.setattr(firms, "analyse", lambda *a, **k: {t: {**v, "status": "pending"} for t, v in real(*a, **k).items()})
    with TestClient(A.app) as c:
        first = _post(c, {"NVDA": 50, "RY.TO": 30, "SPY": 20})
        assert not A._complete(_wait(c, first))
        monkeypatch.setattr(firms, "analyse", real)
        second = _post(c, {"NVDA": 50, "RY.TO": 30, "SPY": 20})
        assert second != first and A._complete(_wait(c, second))
        assert _post(c, {"NVDA": 50, "RY.TO": 30, "SPY": 20}) == second


def test_streamed_run_needs_no_second_request(env, monkeypatch):
    """Serverless mode: /runs answers with the page (request embedded), /runs/stream runs the analysis in that one
    request and streams its id, every event, then the report HTML and the map data. Then it is reused like any run."""
    import json as J
    import re
    from fastapi.testclient import TestClient
    from web import app as A
    monkeypatch.setattr(config, "STREAM_RUNS", True)
    form = {"mode": "weight", "as_of": "2026-11-12", "risk_level": "3", "horizon_years": "10", "objective_level": "3",
            "max_single_weight": "100", "ticker": ["NVDA", "RY.TO", "SPY"], "amount": ["50", "30", "20"]}
    with TestClient(A.app) as c:
        page = c.post("/runs", data=form, follow_redirects=False)
        assert page.status_code == 200 and 'data-status="stream"' in page.text
        body = re.search(r'<script id="run-payload" type="application/json">(.*?)</script>', page.text, re.S).group(1)
        lines = [J.loads(x) for x in c.post("/runs/stream", content=body.replace("<\\/", "</"),
                                             headers={"Content-Type": "application/json"}).text.splitlines()]
        assert lines[0]["kind"] == "run" and lines[0]["status"] == "start"
        rid = lines[0]["id"]
        phases = {e["phase"] for e in lines if e.get("kind") == "phase" and e["status"] == "done"}
        assert phases >= {"assets", "firms", "scenarios", "macro", "countries", "risk", "remediation"}
        report = lines[-1]
        assert report["kind"] == "report" and report["status"] == "done" and report["id"] == rid
        assert "/100" in report["html"] and report["scenarios"]["scenarios"] and "num" in report["scenarios"]
        again = c.post("/runs", data=form, follow_redirects=False)                     # complete: replayed from now on
        assert again.status_code == 303 and again.headers["location"] == f"/runs/{rid}?replay=1"
        bad = c.post("/runs/stream", json={"portfolio": {"holdings": []}, "profile": {}, "as_of": "x"})
        assert bad.status_code == 422


def test_vercel_copies_the_shipped_data_once(tmp_path):
    """On Vercel, data/ shipped with the deployment is copied to the writable DATA_DIR at import, traces excluded."""
    import os
    import subprocess
    import sys
    env = {**os.environ, "VERCEL": "1", "DATA_DIR": str(tmp_path / "d")}
    code = ("from core import config;import sys;"
            "print(config.ON_VERCEL, config.STREAM_RUNS, config.FILINGS_WAIT_S, config.DATA_DIR)")
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True).stdout.split()
    assert out[:3] == ["True", "True", "45.0"] and out[3] == str(tmp_path / "d")
    assert (tmp_path / "d" / ".seeded").exists() and not (tmp_path / "d" / "traces").exists()
