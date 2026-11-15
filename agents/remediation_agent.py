"""Remediation agent: propose trades to reduce portfolio geopolitical risk.

In USE_MOCK=1 mode (default) the agent returns a deterministic mock plan based
on the computed risk scores.  The LLM path is a stub for future implementation.
"""
from core import config
from core.schemas import InvestorProfile, Portfolio, PortfolioRisk, RemediationPlan, Trade

PROMPT = "Propose trades that reduce portfolio geopolitical risk within the investor's constraints."


def run(portfolio: Portfolio, risk: PortfolioRisk, profile: InvestorProfile) -> RemediationPlan:
    """Suggest trades that reduce the portfolio's geopolitical risk score.

    The mock path is deterministic: it always targets the highest-risk ticker.
    The LLM path is not yet implemented.
    """
    if config.USE_MOCK:
        return _mock_plan(portfolio, risk)
    # LLM path: not yet implemented
    return _mock_plan(portfolio, risk)


def _mock_plan(portfolio: Portfolio, risk: PortfolioRisk) -> RemediationPlan:
    """Deterministic mock plan: trim the worst ticker by half a standard allocation."""
    if not risk.by_ticker:
        return RemediationPlan(
            trades=[],
            expected_risk_after=risk.score,
            summary="No holdings to remediate.",
        )
    worst = max(risk.by_ticker, key=risk.by_ticker.__getitem__)
    worst_score = risk.by_ticker[worst]
    delta = -min(0.10, next((h.weight for h in portfolio.holdings if h.ticker == worst), 0.05) / 2)
    trades = [
        Trade(
            ticker=worst,
            action="sell",
            delta_weight=round(delta, 4),
            rationale=(
                f"{worst} is the highest-risk holding at {worst_score:.1f}/100 — "
                f"reduce weight by {abs(delta):.0%} to lower portfolio risk."
            ),
        )
    ]
    return RemediationPlan(
        trades=trades,
        expected_risk_after=round(risk.score * 0.9, 2),
        summary=(
            f"Reduce {worst} to lower geopolitical risk from "
            f"{risk.score:.1f}/100 to an estimated "
            f"{risk.score * 0.9:.1f}/100."
        ),
    )
