from agents.base import run_agent
from core import config
from core.schemas import ExposureReport, GeopoliticalReport, Portfolio, PortfolioRisk
from tools import risk_math


def _compute(portfolio: Portfolio, exposures: ExposureReport, geo: GeopoliticalReport):
    cscore = {c.country: c.score for c in geo.countries}
    by_ticker = {
        t.ticker: risk_math.ticker_risk({e.country: e.revenue_share or 0.0 for e in t.exposures}, cscore)
        for t in exposures.tickers}
    total = risk_math.portfolio_risk({h.ticker: h.weight for h in portfolio.holdings}, by_ticker)
    return total, by_ticker


def run(portfolio: Portfolio, exposures: ExposureReport, geo: GeopoliticalReport) -> PortfolioRisk:
    total, by_ticker = _compute(portfolio, exposures, geo)  # numbers are deterministic
    if config.USE_MOCK:
        return PortfolioRisk(score=total, top_drivers=["mock"], by_ticker=by_ticker, explanation="mock")
    # LLM only explains; overwrite its numbers with the computed ones.
    out = run_agent("Explain these computed risk numbers and name top drivers.",
                    f"score={total} by_ticker={by_ticker}\n{geo.model_dump_json()}", PortfolioRisk)
    return out.model_copy(update={"score": total, "by_ticker": by_ticker})
