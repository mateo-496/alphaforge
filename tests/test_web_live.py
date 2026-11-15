import asyncio

import pytest

from web import live, pipeline


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def real(monkeypatch):
    monkeypatch.setenv("USE_REAL_AGENTS", "1")
    monkeypatch.setenv("USE_FILING_RISK_AGENT", "0")
    monkeypatch.setattr(live.worldbank, "country_info", lambda c: {
        "US": {"iso3": "USA", "iso2": "US", "name": "United States"},
        "CN": {"iso3": "CHN", "iso2": "CN", "name": "China"}}.get(c))


def test_equity_exposures_become_iso3_weights_with_explicit_other(real, monkeypatch):
    monkeypatch.setattr(live.market_data, "get_country_exposures", lambda t: {
        "status": "available", "exposures": [
            {"country": "US", "revenue_share": 0.6, "source": {"title": "s"}},
            {"country": "TW", "revenue_share": 0.2, "source": {"title": "s"}}]})
    monkeypatch.setattr(live.market_inputs, "vol_and_beta", lambda t, d: {"vol_1y": 0.35, "beta": 1.25})
    report = run(live.asset_report("NVDA", {"asset_class": "equity"}, "2026-11-14"))
    assert report["country_weights"]["USA"] == 0.6 and report["country_weights"]["TWN"] == 0.2  # Taiwan: GPR table
    assert report["country_weights"]["Other"] == pytest.approx(0.2)
    assert report["market"] == pytest.approx(0.5) and report["filing"] is None and report["mock"] is False


def test_funds_unknown_issuers_and_disabled_flag_return_none(real, monkeypatch):
    assert run(live.asset_report("SPY", {"asset_class": "etf_equity"}, "2026-11-14")) is None
    monkeypatch.setattr(live.market_data, "get_country_exposures", lambda t: {"status": "no_sec_ticker", "exposures": []})
    assert run(live.asset_report("RY.TO", {"asset_class": "equity"}, "2026-11-14")) is None
    monkeypatch.setenv("USE_REAL_AGENTS", "0")
    assert run(live.asset_report("NVDA", {"asset_class": "equity"}, "2026-11-14")) is None
    assert run(live.country_report("CHN", "2026-11-14")) is None


def test_agent_failure_falls_back_to_none(real, monkeypatch):
    def boom(t):
        raise RuntimeError("SEC down")
    monkeypatch.setattr(live.market_data, "get_country_exposures", boom)
    assert run(live.asset_report("NVDA", {"asset_class": "equity"}, "2026-11-14")) is None


def test_country_report_uses_measured_score_when_agent_unavailable(real, monkeypatch):
    def no_agent(name):
        raise RuntimeError("Bedrock unavailable")
    monkeypatch.setattr("agents.country_risk_agent.analyze_country_scored", no_agent)
    monkeypatch.setattr(live, "country_risk_score", lambda iso2, as_of: {
        "score": 0.75, "gpr": {"percentile": 0.99, "month": "2026-10"}, "stress": {"percentile": 0.5}})
    report = run(live.country_report("CHN", "2026-11-14"))
    assert report["R"] == 75.0 and report["mock"] is False and "99%" in report["driver"]
    assert report["sources"][0]["locator"] == "gprc_chn, 2026-10"


def test_pipeline_asset_risk_uses_the_shared_formula_and_mean_for_unknown_countries():
    rep = {"country_weights": {"CHN": 0.5, "Other": 0.5}, "firm_score": 0.0, "filing": 0.2, "market": 0.6,
           "mock": False}
    # exposure = 0.5 * 0.8 + 0.5 * 0.8 (Other takes the mean of scored countries); equal weights over 3 terms
    assert pipeline._asset_risk(rep, {"CHN": 80, "Other": 10}) == pytest.approx(100 * (0.8 + 0.2 + 0.6) / 3)
    mock = {"country_weights": {"CHN": 1.0}, "firm_score": 5.0, "mock": True}
    assert pipeline._asset_risk(mock, {"CHN": 40}) == pytest.approx(100 * (0.4 + 1.0) / 2)


def test_levels_are_equal_bands():
    assert [pipeline._level(x) for x in (10, 30, 60, 90)] == ["low", "moderate", "elevated", "high"]
