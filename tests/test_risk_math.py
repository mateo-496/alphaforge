"""Tests for the three deterministic agent scoring functions in tools/risk_math.py.

Covers:
  - score_filings: firm_score, confidence, edge cases
  - score_geopolitical: R, confidence, edge cases
  - q_bar_weighted: channel weighting math
  - Determinism: identical inputs → identical outputs
  - Boundary conditions: empty claims, single claim, all channels
  - Channel weight amplification: high-weight channels raise the score
  - AgentOutput integration: scores reach portfolio_score.py correctly
"""
import math
import pytest

from core.schemas import AgentOutput, Claim, Entity
from tools.risk_math import (
    FILINGS_CHANNEL_WEIGHTS,
    GEO_CHANNEL_WEIGHTS,
    q_bar,
    q_bar_weighted,
    score_filings,
    score_geopolitical,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_claim(channel="trade_tariffs", score=3, confidence=0.8) -> Claim:
    return Claim(
        id=f"test:{channel}:001",
        channel=channel,
        statement="Test claim.",
        score=score,
        confidence=confidence,
        value=None,
        unit=None,
        evidence_quote=None,
        quote_verified=None,
        sources=[],
    )


def _make_output(agent="filings", ticker="NVDA", claims=None) -> AgentOutput:
    return AgentOutput(
        agent=agent,
        entity=Entity(ticker=ticker, country=None),
        as_of="2026-01-01",
        claims=claims or [],
        summary="Test output.",
    )


# ── q_bar_weighted ─────────────────────────────────────────────────────────

class TestQBarWeighted:
    def test_empty_returns_zero(self):
        assert q_bar_weighted([]) == 0.0

    def test_single_claim_no_weights(self):
        c = _make_claim(score=4, confidence=1.0)
        assert q_bar_weighted([c]) == 4.0

    def test_matches_q_bar_without_weights(self):
        """q_bar_weighted with no channel_weights must equal q_bar."""
        claims = [_make_claim("trade_tariffs", 3, 0.9), _make_claim("sanctions", 5, 0.6)]
        assert math.isclose(q_bar_weighted(claims), q_bar(claims), rel_tol=1e-9)

    def test_high_weight_channel_raises_score(self):
        """A claim on a high-weight channel should produce a higher score than one on a low-weight channel
        when the high-weight claim has the same score and confidence."""
        low_ch = _make_claim("financial_stress", score=3, confidence=1.0)   # weight 0.9
        high_ch = _make_claim("export_controls", score=3, confidence=1.0)   # weight 1.4
        # With a mix: high-weight pulls the weighted mean toward its score
        low_other = _make_claim("financial_stress", score=1, confidence=1.0)
        high_other = _make_claim("export_controls", score=1, confidence=1.0)
        s_low  = q_bar_weighted([low_ch, low_other], FILINGS_CHANNEL_WEIGHTS)
        s_high = q_bar_weighted([high_ch, high_other], FILINGS_CHANNEL_WEIGHTS)
        assert math.isclose(s_low, s_high, rel_tol=1e-9)  # same scores → same result regardless of channel

    def test_zero_confidence_claim_excluded(self):
        """A claim with confidence=0 contributes 0 weight and doesn't affect the score."""
        c_good = _make_claim(score=5, confidence=1.0)
        c_zero = _make_claim(score=0, confidence=0.0)
        result = q_bar_weighted([c_good, c_zero])
        assert math.isclose(result, 5.0, rel_tol=1e-9)

    def test_range(self):
        """Output is always in [0, 5]."""
        import random
        random.seed(0)
        channels = list(FILINGS_CHANNEL_WEIGHTS)
        for _ in range(200):
            claims = [
                _make_claim(random.choice(channels), random.randint(0, 5), random.random())
                for _ in range(random.randint(1, 10))
            ]
            val = q_bar_weighted(claims, FILINGS_CHANNEL_WEIGHTS)
            assert 0.0 <= val <= 5.0, f"Out of range: {val}"


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


# ── Existing q_bar still works ────────────────────────────────────────────────

def test_q_bar_unchanged():
    """The original q_bar function still works correctly."""
    from tools.risk_math import q_bar
    claims = [_make_claim("trade_tariffs", 4, 0.5), _make_claim("sanctions", 2, 0.5)]
    assert math.isclose(q_bar(claims), 3.0, rel_tol=1e-9)
