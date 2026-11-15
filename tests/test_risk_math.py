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


# ── score_filings ─────────────────────────────────────────────────────────

class TestScoreFilings:
    def test_empty_output(self):
        out = _make_output("filings", "NVDA", [])
        result = score_filings(out)
        assert result["firm_score"] == 0.0
        assert result["confidence"] == 0.0
        assert result["num_claims"] == 0

    def test_single_max_severity(self):
        c = _make_claim("export_controls", score=5, confidence=1.0)
        out = _make_output("filings", "NVDA", [c])
        result = score_filings(out)
        assert result["firm_score"] == 5.0
        # coverage = min(1, 1/5) = 0.2 → confidence = 1.0 * 0.2 = 0.2
        assert math.isclose(result["confidence"], 0.2, rel_tol=1e-6)
        assert result["num_claims"] == 1

    def test_five_claims_full_coverage(self):
        claims = [_make_claim("trade_tariffs", score=3, confidence=1.0) for _ in range(5)]
        out = _make_output("filings", "NVDA", claims)
        result = score_filings(out)
        # coverage = min(1, 5/5) = 1.0 → confidence = 1.0
        assert math.isclose(result["confidence"], 1.0, rel_tol=1e-6)

    def test_score_in_range(self):
        import random
        random.seed(1)
        channels = list(FILINGS_CHANNEL_WEIGHTS)
        for _ in range(200):
            n = random.randint(1, 12)
            claims = [
                _make_claim(random.choice(channels), random.randint(0, 5), random.random())
                for _ in range(n)
            ]
            out = _make_output("filings", "TEST", claims)
            r = score_filings(out)
            assert 0.0 <= r["firm_score"] <= 5.0
            assert 0.0 <= r["confidence"] <= 1.0

    def test_deterministic(self):
        claims = [
            _make_claim("export_controls", 4, 0.9),
            _make_claim("sanctions", 3, 0.7),
            _make_claim("trade_tariffs", 2, 0.8),
        ]
        out = _make_output("filings", "NVDA", claims)
        r1 = score_filings(out)
        for _ in range(50):
            r2 = score_filings(out)
            assert r1 == r2, "score_filings is not deterministic"

    def test_high_risk_channels_raise_firm_score(self):
        """export_controls (w=1.4) > financial_stress (w=0.9) with same score/confidence."""
        c_high = _make_claim("export_controls", score=5, confidence=1.0)
        c_low  = _make_claim("financial_stress", score=1, confidence=1.0)
        out = _make_output("filings", "X", [c_high, c_low])
        result = score_filings(out)
        # Channel-weighted cubic power mean: ((1.4·5³ + 0.9·1³)/(1.4 + 0.9))^(1/3) ≈ 4.24
        expected = ((1.4 * 5**3 + 0.9 * 1**3) / (1.4 + 0.9)) ** (1 / 3)
        assert expected > (1.4 * 5 + 0.9 * 1) / (1.4 + 0.9)  # severe claim is not averaged away
        assert math.isclose(result["firm_score"], expected, rel_tol=1e-4)


# ── score_geopolitical ────────────────────────────────────────────────────

class TestScoreGeopolitical:
    def test_empty_output(self):
        out = _make_output("geopolitical", "TWN", [])
        result = score_geopolitical(out)
        assert result["R"] == 0.0
        assert result["confidence"] == 0.0
        assert result["num_claims"] == 0

    def test_max_severity_gives_100(self):
        c = _make_claim("conflict_exposure", score=5, confidence=1.0)
        out = _make_output("geopolitical", "TWN", [c])
        result = score_geopolitical(out)
        assert result["R"] == 100.0

    def test_zero_severity_gives_zero_R(self):
        c = _make_claim("conflict_exposure", score=0, confidence=1.0)
        out = _make_output("geopolitical", "TWN", [c])
        result = score_geopolitical(out)
        assert result["R"] == 0.0

    def test_coverage_reaches_one_at_four_claims(self):
        claims = [_make_claim("conflict_exposure", score=3, confidence=1.0) for _ in range(4)]
        out = _make_output("geopolitical", "CHN", claims)
        result = score_geopolitical(out)
        assert math.isclose(result["confidence"], 1.0, rel_tol=1e-6)

    def test_R_in_range(self):
        import random
        random.seed(2)
        channels = list(GEO_CHANNEL_WEIGHTS)
        for _ in range(200):
            n = random.randint(1, 8)
            claims = [
                _make_claim(random.choice(channels), random.randint(0, 5), random.random())
                for _ in range(n)
            ]
            out = _make_output("geopolitical", "X", claims)
            r = score_geopolitical(out)
            assert 0.0 <= r["R"] <= 100.0
            assert 0.0 <= r["confidence"] <= 1.0

    def test_deterministic(self):
        claims = [
            _make_claim("conflict_exposure", 5, 0.9),
            _make_claim("sanctions", 4, 0.8),
        ]
        out = _make_output("geopolitical", "IRN", claims)
        r1 = score_geopolitical(out)
        for _ in range(50):
            r2 = score_geopolitical(out)
            assert r1 == r2, "score_geopolitical is not deterministic"

    def test_conflict_channel_amplification(self):
        """conflict_exposure (w=1.5) should raise R vs regulatory (w=0.8) with same severity."""
        c_conflict = _make_claim("conflict_exposure", score=5, confidence=1.0)
        c_reg      = _make_claim("regulatory",        score=1, confidence=1.0)
        out = _make_output("geopolitical", "X", [c_conflict, c_reg])
        result = score_geopolitical(out)
        # channel-weighted cubic power mean: ((1.5·5³ + 0.8·1³)/(1.5+0.8))^(1/3) ≈ 4.34
        expected_q = ((1.5 * 5**3 + 0.8 * 1**3) / (1.5 + 0.8)) ** (1 / 3)
        expected_R = expected_q / 5.0 * 100.0
        assert math.isclose(result["R"], expected_R, rel_tol=1e-4)


# ── Integration: scores flow into portfolio_score ────────────────────────────

class TestAgentOutputIntegration:
    """AgentOutput objects passed directly to extract_agent_inputs must yield the same
    scores as manually-computed firm_score/R dicts."""

    def test_filings_output_in_extract_agent_inputs(self):
        """extract_agent_inputs accepts AgentOutput for assets and returns a valid a3."""
        from tools.portfolio_score import extract_agent_inputs

        claims = [
            _make_claim("export_controls", 4, 0.9),
            _make_claim("trade_tariffs", 3, 0.8),
            _make_claim("sanctions", 2, 0.7),
            _make_claim("supply_chain", 1, 0.6),
            _make_claim("regulatory", 2, 0.75),
        ]
        out = _make_output("filings", "NVDA", claims)
        expected = score_filings(out)

        a1, a2, a3, tol, conf = extract_agent_inputs(
            weights={"NVDA": 1.0},
            profile={"risk_tolerance": "moderate"},
            assets={"NVDA": out},   # AgentOutput directly
            countries={},
            scenarios=[],
        )
        # a3 = calibrated firm_score/5 (single holding → power mean is the value itself)
        from tools.portfolio_score import Params, calibrate
        want = calibrate(expected["firm_score"] / 5.0, Params().m3, Params().k3)
        assert math.isclose(a3, want, rel_tol=1e-4), (
            f"a3={a3}, expected={want}"
        )
        assert 0.0 <= a3 <= 1.0

    def test_geo_output_in_extract_agent_inputs(self):
        """extract_agent_inputs accepts AgentOutput for countries and returns a valid a1."""
        from tools.portfolio_score import extract_agent_inputs

        claims = [
            _make_claim("conflict_exposure", 5, 0.9),
            _make_claim("sanctions", 4, 0.8),
            _make_claim("trade_tariffs", 3, 0.7),
            _make_claim("financial_stress", 2, 0.6),
        ]
        out = _make_output("geopolitical", "TWN", claims)
        expected_R = score_geopolitical(out)["R"]

        a1, a2, a3, tol, conf = extract_agent_inputs(
            weights={"NVDA": 1.0},
            profile={"risk_tolerance": "moderate"},
            assets={"NVDA": {"country_weights": {"TWN": 1.0}, "firm_score": 2.0}},
            countries={"TWN": out},   # AgentOutput directly
            scenarios=[],
        )
        # a1 = calibrated R/100 since NVDA has 100% TWN exposure
        from tools.portfolio_score import Params, calibrate
        want = calibrate(expected_R / 100.0, Params().m1, Params().k1)
        assert math.isclose(a1, want, rel_tol=1e-4), (
            f"a1={a1}, expected={want}"
        )
        assert 0.0 <= a1 <= 1.0

    def test_mixed_dict_and_agent_output(self):
        """Dict assets and AgentOutput assets can coexist in the same call."""
        from tools.portfolio_score import extract_agent_inputs

        filings_out = _make_output("filings", "AAPL", [_make_claim("trade_tariffs", 3, 0.8)])
        a1, a2, a3, tol, conf = extract_agent_inputs(
            weights={"NVDA": 0.5, "AAPL": 0.5},
            profile={"risk_tolerance": "low"},
            assets={
                "NVDA": {"country_weights": {"USA": 1.0}, "firm_score": 4.0},
                "AAPL": filings_out,  # AgentOutput
            },
            countries={"USA": {"R": 38.0}},
            scenarios=[],
        )
        assert 0.0 <= a3 <= 1.0
        assert tol == 0.20  # "low" tolerance
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
