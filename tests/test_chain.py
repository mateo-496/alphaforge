import pytest

try:
    from core.schemas import ChainResult, InvestorProfile, Portfolio, Scenario
    from orchestrator import chain
except ImportError:
    pytest.skip("legacy chain: schemas and agents not yet migrated (see agents/risk_agent.md)",
                allow_module_level=True)


def test_mock_chain():
    p = Portfolio(holdings=[{"ticker": "NVDA", "weight": 1.0}])
    s = Scenario(name="x", description="x", countries=["TWN"])
    r = chain.run(p, InvestorProfile(), s)
    assert isinstance(r, ChainResult) and len(r.steps) == 4
