from tools.risk_math import portfolio_risk, ticker_risk


def test_ticker_risk():
    assert ticker_risk({"CHN": 0.5}, {"CHN": 80}) == 40


def test_portfolio_risk():
    assert portfolio_risk({"A": 0.5, "B": 0.5}, {"A": 80, "B": 20}) == 50


import pytest

from core.schemas import Claim
from tools import risk_math as rm


def claim(score, confidence):
    return Claim(id="a:T:001", channel="filing_risk", statement="s", score=score, confidence=confidence)


def test_percentile_rank_is_bounded_and_none_without_history():
    assert rm.percentile_rank(5, [1, 2, 3, 4]) == 1.0
    assert rm.percentile_rank(0, [1, 2, 3, 4]) == 0.0
    assert rm.percentile_rank(2, [1, 2, 3, 4]) == 0.5
    assert rm.percentile_rank(1, []) is None


def test_claim_quality_is_confidence_weighted():
    assert rm.claim_quality([claim(5, 1.0), claim(0, 1.0)]) == 0.5
    assert rm.claim_quality([claim(5, 0.9), claim(0, 0.1)]) == pytest.approx(0.9)
    assert rm.claim_quality([]) is None


def test_country_risk_renormalises_missing_components_instead_of_counting_zero():
    score, contrib = rm.country_risk(0.8, None, 0.4, [])
    assert score == pytest.approx(0.6)
    assert set(contrib) == {"gpr", "vol"} and sum(contrib.values()) == pytest.approx(score)
    with pytest.raises(ValueError):
        rm.country_risk(None, None, None, [])
    with pytest.raises(ValueError):
        rm.country_risk(1.2, 0.5, 0.5, [])


def test_asset_risk_unknown_share_uses_mean_country_risk_not_zero():
    score, contrib, per_country = rm.asset_risk({"CN": 0.5}, {"CN": 0.8, "US": 0.2},
                                                weights={"exposure": 1, "filing": 0, "market": 0})
    assert per_country == {"CN": pytest.approx(0.4), "Other": pytest.approx(0.25)}  # mean R = 0.5
    assert score == pytest.approx(0.65)


def test_asset_risk_blends_filing_and_market_and_contributions_sum_to_score():
    score, contrib, _ = rm.asset_risk({"CN": 1.0}, {"CN": 0.6}, filing=0.3, market=0.9)
    assert score == pytest.approx((0.6 + 0.3 + 0.9) / 3)
    assert sum(contrib.values()) == pytest.approx(score)
    score, contrib, _ = rm.asset_risk({"CN": 1.0}, {"CN": 0.6}, filing=0.3)
    assert score == pytest.approx(0.45) and set(contrib) == {"exposure", "filing"}


def test_portfolio_scores_and_validation():
    total, contrib = rm.portfolio_scores({"A": 0.5, "B": 0.5}, {"A": 0.8, "B": 0.2})
    assert total == pytest.approx(0.5) and contrib == {"A": pytest.approx(0.4), "B": pytest.approx(0.1)}
    with pytest.raises(ValueError):
        rm.portfolio_scores({"A": 0.5}, {"A": 0.5})


def test_scenario_shock_is_bounded_by_likelihood():
    shock = rm.scenario_shock({"A": 0.5, "B": 0.5}, {"A": {"TW": 1.0}, "B": {"US": 1.0}}, {"TW": 1.0}, 0.2)
    assert shock == pytest.approx(0.1)
    assert rm.scenario_shock({"A": 1.0}, {"A": {"TW": 1.0}}, {"TW": 1.0}, 0.2) == pytest.approx(0.2)
    with pytest.raises(ValueError):
        rm.scenario_shock({"A": 1.0}, {"A": {"TW": 1.0}}, {"TW": 2.0}, 0.2)


def test_ranking_stability_detects_weight_dependence():
    values = {"A": {"x": 0.9, "y": 0.1}, "B": {"x": 0.1, "y": 0.9}}

    def score(weights):
        return {k: sum(weights[c] * v for c, v in comps.items()) for k, comps in values.items()}
    assert rm.ranking_stability(score, {"x": 0.5, "y": 0.5}) < 1.0
    values = {"A": {"x": 0.9, "y": 0.8}, "B": {"x": 0.1, "y": 0.2}}
    assert rm.ranking_stability(score, {"x": 0.5, "y": 0.5}) == 1.0
