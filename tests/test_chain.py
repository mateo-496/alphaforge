"""Integration test for orchestrator/chain.py (mock mode).

Verifies:
- The chain runs end-to-end with USE_MOCK=1 (default)
- Exactly 4 steps are recorded (filings, geopolitical, risk, remediation)
- Each step has the expected agent name
- The final score is in [0, 100]
- The chain is deterministic: identical inputs produce identical results
"""
import os

import pytest

from core.schemas import ChainResult, InvestorProfile, Portfolio
from orchestrator import chain


@pytest.fixture(autouse=True)
def mock_mode(monkeypatch):
    """Ensure USE_MOCK=1 for all tests in this module."""
    monkeypatch.setenv("USE_MOCK", "1")
    # Also patch the in-process config flag
    import core.config as _cfg
    monkeypatch.setattr(_cfg, "USE_MOCK", True)
    import agents.risk_agent  # noqa: F401 — re-import picks up monkeypatched config


def _make_portfolio():
    return Portfolio(holdings=[{"ticker": "NVDA", "weight": 1.0}])


def test_mock_chain_runs():
    """Chain completes without error and returns a ChainResult."""
    p = _make_portfolio()
    r = chain.run(p, InvestorProfile())
    assert isinstance(r, ChainResult)


def test_mock_chain_has_four_steps():
    """Chain always produces exactly 4 recorded steps."""
    p = _make_portfolio()
    r = chain.run(p, InvestorProfile())
    assert len(r.steps) == 4


def test_mock_chain_step_names():
    """Steps are named in the expected order."""
    p = _make_portfolio()
    r = chain.run(p, InvestorProfile())
    names = [s.agent for s in r.steps]
    assert names == ["filings", "geopolitical", "risk", "remediation"]


def test_mock_chain_risk_score_in_range():
    """Final risk score is a number in [0, 100]."""
    p = _make_portfolio()
    r = chain.run(p, InvestorProfile())
    # Find the risk step
    risk_step = next(s for s in r.steps if s.agent == "risk")
    score = risk_step.output.get("score", -1)
    assert 0 <= score <= 100


def test_mock_chain_deterministic():
    """Running the chain twice with the same inputs gives the same score."""
    p = _make_portfolio()
    r1 = chain.run(p, InvestorProfile())
    r2 = chain.run(p, InvestorProfile())
    risk1 = next(s for s in r1.steps if s.agent == "risk").output["score"]
    risk2 = next(s for s in r2.steps if s.agent == "risk").output["score"]
    assert risk1 == risk2


def test_mock_chain_remediation_plan():
    """The remediation plan contains at least one trade."""
    p = _make_portfolio()
    r = chain.run(p, InvestorProfile())
    assert len(r.final.trades) >= 1
    trade = r.final.trades[0]
    assert trade.ticker == "NVDA"
    assert trade.action in ("buy", "sell", "hold")
    assert trade.delta_weight < 0  # selling


def test_mock_chain_multi_holding():
    """Chain works with multiple holdings."""
    p = Portfolio(holdings=[
        {"ticker": "NVDA", "weight": 0.6},
        {"ticker": "AAPL", "weight": 0.4},
    ])
    r = chain.run(p, InvestorProfile())
    assert isinstance(r, ChainResult)
    assert len(r.steps) == 4
