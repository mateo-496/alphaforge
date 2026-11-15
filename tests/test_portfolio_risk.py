import pytest

from core.schemas import Claim
from tools import market_inputs
from tools import risk_math as rm
from tools.portfolio_risk import compute_portfolio_risk


def claim(score, confidence=1.0):
    return Claim(id="filing_risk:T:001", channel="filing_risk", statement="s", score=score, confidence=confidence)


def test_filing_risk_is_not_diluted_by_many_minor_claims():
    grave = [claim(5)] + [claim(0)] * 9
    minor = [claim(1)] * 10
    assert rm.filing_risk(grave) > rm.filing_risk(minor)
    assert rm.filing_risk([]) is None
    assert rm.filing_risk([claim(5)]) == pytest.approx(1.0)


def test_market_risk_uses_fixed_bounds_and_clips():
    assert rm.market_risk(0.10, 0.5) == 0.0
    assert rm.market_risk(0.60, 2.0) == 1.0
    assert rm.market_risk(2.0, None) == 1.0
    assert rm.market_risk(0.35, 1.25) == pytest.approx(0.5)
    assert rm.market_risk(None, None) is None


def test_asset_risk_without_known_revenue_split_omits_exposure():
    score, contrib, per_country = rm.asset_risk({}, {"US": 0.5}, filing=0.4)
    assert score == pytest.approx(0.4) and "exposure" not in contrib and per_country == {}


def test_compute_portfolio_risk_end_to_end():
    report = compute_portfolio_risk(
        "2026-11-14", {"A": 0.6, "B": 0.4},
        {"A": {"CN": 0.5, "US": 0.5}, "B": {"US": 1.0}},
        {"CN": {"score": 0.8, "missing_inputs": ["epu"]}, "US": {"score": 0.4, "missing_inputs": []}},
        {"A": [claim(5)], "B": [claim(0)]},
        {"A": {"vol_1y": 0.60, "beta": 2.0}, "B": {"vol_1y": 0.10, "beta": 0.5}})
    a, b = report.tickers
    assert a.score == pytest.approx((0.6 + 1.0 + 1.0) / 3) and b.score == pytest.approx((0.4 + 0.0 + 0.0) / 3)
    assert report.score == pytest.approx(0.6 * a.score + 0.4 * b.score)
    assert sum(report.contributions.values()) == pytest.approx(report.score)
    assert all(sum(t.contributions.values()) == pytest.approx(t.score) for t in report.tickers)
    assert report.ranking_stability == 1.0 and report.stressed_score is None and report.notes == []


def test_missing_inputs_are_reported_and_scenario_stresses_the_score():
    report = compute_portfolio_risk(
        "2026-11-14", {"A": 1.0}, {"A": {"CN": 1.0}}, {"CN": {"score": 0.5, "missing_inputs": []}}, {}, {},
        scenario=({"CN": 1.0}, 0.2))
    assert report.tickers[0].missing_inputs == ["filing", "market"]
    assert report.score == pytest.approx(0.5) and report.scenario_shock == pytest.approx(0.2)
    assert report.stressed_score == pytest.approx(0.7) and report.notes


def test_vol_and_beta_from_aligned_prices(monkeypatch):
    import math
    n = 200
    bench = [100 * math.exp(0.001 * i + (0.01 if i % 2 else -0.01)) for i in range(n)]
    own = [100 * math.exp(2 * (math.log(b / 100))) for b in bench]  # exactly twice the benchmark's log returns

    def series(values):
        return {"observations": [{"date": f"d{i:03d}", "value": v} for i, v in enumerate(values)]}
    monkeypatch.setattr(market_inputs.market_data, "get_price_history",
                        lambda t, as_of, days: series(bench if t == "SPY" else own))
    result = market_inputs.vol_and_beta("XYZ", "2026-11-14")
    assert result["beta"] == pytest.approx(2.0) and result["vol_1y"] > 0.3
    monkeypatch.setattr(market_inputs.market_data, "get_price_history",
                        lambda t, as_of, days: series(bench[:50]))
    assert market_inputs.vol_and_beta("XYZ", "2026-11-14")["beta"] is None
