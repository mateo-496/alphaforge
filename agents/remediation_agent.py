from agents.base import run_agent
from core import config
from core.schemas import InvestorProfile, Portfolio, PortfolioRisk, RemediationPlan, Trade

PROMPT = "Propose trades that reduce portfolio geopolitical risk within the investor's constraints."


def run(portfolio: Portfolio, risk: PortfolioRisk, profile: InvestorProfile) -> RemediationPlan:
    if config.USE_MOCK:
        worst = max(risk.by_ticker, key=risk.by_ticker.get)
        return RemediationPlan(
            trades=[Trade(ticker=worst, action="sell", delta_weight=-0.05, rationale="mock")],
            expected_risk_after=risk.score * 0.9, summary="mock plan")
    prompt = f"{portfolio.model_dump_json()}\n{risk.model_dump_json()}\n{profile.model_dump_json()}"
    return run_agent(PROMPT, prompt, RemediationPlan)
