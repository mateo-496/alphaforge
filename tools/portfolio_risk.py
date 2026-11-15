"""Final portfolio risk from country exposure, filing risk and market risk (deterministic, see tools.risk_math)."""
from typing import Optional

from core.portfolio_risk import CountryRiskSummary, PortfolioRiskReport, TickerRisk
from core.schemas import Claim
from tools import risk_math as rm


def compute_portfolio_risk(
    as_of: str,
    weights: dict[str, float],
    exposures: dict[str, dict[str, float]],
    country_scores: dict[str, dict],
    filing_claims: dict[str, list[Claim]],
    market: dict[str, dict],
    asset_weights: dict[str, float] = rm.EQUAL_ASSET_WEIGHTS,
    scenario: Optional[tuple[dict[str, float], float]] = None,
) -> PortfolioRiskReport:
    """exposures: ticker -> {ISO2: revenue share}; country_scores: ISO2 -> {"score", "missing_inputs"};
    market: ticker -> {"vol_1y", "beta"}; scenario: (intensity per ISO2 on [0, 1], likelihood)."""
    R = {c: v["score"] for c, v in country_scores.items()}

    def asset_scores(w: dict[str, float]) -> dict[str, tuple]:
        out = {}
        for ticker in weights:
            m = market.get(ticker, {})
            out[ticker] = rm.asset_risk(exposures.get(ticker, {}), R, rm.filing_risk(filing_claims.get(ticker, [])),
                                        rm.market_risk(m.get("vol_1y"), m.get("beta")), w)
        return out

    scored = asset_scores(asset_weights)
    G = {t: s[0] for t, s in scored.items()}
    total, by_ticker = rm.portfolio_scores(weights, G)
    tickers = []
    for t, (g, contrib, per_country) in scored.items():
        missing = [k for k in ("exposure", "filing", "market") if k not in contrib]
        tickers.append(TickerRisk(
            ticker=t, weight=weights[t], score=g, contributions=contrib, country_contributions=per_country,
            unknown_revenue_share=max(0.0, 1.0 - sum(exposures.get(t, {}).values())), missing_inputs=missing))
    notes = [f"{t.ticker}: missing {', '.join(t.missing_inputs)}; weights renormalised over the rest"
             for t in tickers if t.missing_inputs]
    stressed = shock = None
    if scenario:
        intensity, likelihood = scenario
        shock = rm.scenario_shock(weights, exposures, intensity, likelihood)
        stressed = min(1.0, total + shock)
    stability = rm.ranking_stability(lambda w: {t: s[0] for t, s in asset_scores(w).items()}, asset_weights)
    return PortfolioRiskReport(
        as_of=as_of, score=total, asset_weights=asset_weights, tickers=tickers, contributions=by_ticker,
        countries=[CountryRiskSummary(country=c, score=v["score"], missing_inputs=v.get("missing_inputs", []))
                   for c, v in sorted(country_scores.items())],
        stressed_score=stressed, scenario_shock=shock, ranking_stability=stability, notes=notes)
