"""Risk agent: aggregate filings and geopolitical agent outputs into a portfolio risk score.

Score pipeline
--------------
A3 (firm exposure risk):
    score_filings(output)   →  firm_score ∈ [0, 5]
    q = Σ(w_ch · c · s) / Σ(w_ch · c)   where w_ch = FILINGS_CHANNEL_WEIGHTS
    A3 = firm_score / 5                   ∈ [0, 1]

A1 (national / country risk):
    score_geopolitical(output)  →  R ∈ [0, 100]
    q = Σ(w_ch · c · s) / Σ(w_ch · c)   where w_ch = GEO_CHANNEL_WEIGHTS
    R = q / 5 × 100,  A1 = portfolio-exposure-weighted mean(R) / 100

A2 (geopolitical scenario risk):
    From scenario sets: Σ(exp · likelihood · impact/5) / n_scenarios
    Falls back to A1 when no scenarios are available.

Final score via tools.portfolio_score.calculate_portfolio_risk (deterministic 2-stage formula).
Identical inputs always produce identical scores.
"""
from core import config
from core.schemas import AgentOutput, InvestorProfile, Portfolio, PortfolioRisk
from tools import risk_math
from tools.portfolio_score import calculate_portfolio_risk


def run(
    portfolio: Portfolio,
    filings_outputs: list[AgentOutput] | None = None,
    geo_outputs: list[AgentOutput] | None = None,
    profile: InvestorProfile | None = None,
    scenarios: list[dict] | None = None,
) -> PortfolioRisk:
    """Compute deterministic portfolio risk from agent outputs.

    Parameters
    ----------
    portfolio       Portfolio with holdings and weights.
    filings_outputs One AgentOutput per ticker from filings_agent.run().
    geo_outputs     One AgentOutput per country from geopolitical_agent.run().
    profile         Investor profile (drives personalized score only).
    scenarios       Scenario sets from the scenario agent (list of group dicts).

    Returns
    -------
    PortfolioRisk with score, objective_score, personalized_score, by_ticker, components.
    """
    weights = {h.ticker: h.weight for h in portfolio.holdings}

    # ── Build assets dict for extract_agent_inputs ───────────────────────────
    # Passing AgentOutput objects directly; extract_agent_inputs handles them.
    assets: dict = {}
    for out in (filings_outputs or []):
        ticker = out.entity.ticker
        scored = risk_math.score_filings(out)
        # Country weights: extract claims where unit="revenue_share" and value is set.
        # If none are present the dict is empty; extract_agent_inputs still works.
        country_weights: dict[str, float] = {}
        for cl in out.claims:
            if cl.value is not None and cl.unit == "revenue_share":
                parts = cl.id.split(":")
                if len(parts) >= 2:
                    country_weights[parts[1]] = float(cl.value)
        assets[ticker] = {
            "firm_score": scored["firm_score"],
            "confidence": scored["confidence"],
            "country_weights": country_weights,
        }

    # ── Build countries dict for extract_agent_inputs ────────────────────────
    countries: dict = {}
    for out in (geo_outputs or []):
        iso3 = out.entity.ticker   # geopolitical_agent stores the ISO3 as the ticker
        scored = risk_math.score_geopolitical(out)
        countries[iso3] = {"R": scored["R"], "confidence": scored["confidence"]}

    # ── Compute final scores via the deterministic 2-stage formula ───────────
    risk_calc = calculate_portfolio_risk(
        weights=weights,
        profile=profile.model_dump() if profile else None,
        assets=assets if assets else None,
        countries=countries if countries else None,
        scenarios=scenarios or [],
    )

    # ── Per-ticker firm risk (0-100) for the remediation agent ───────────────
    by_ticker: dict[str, float] = {
        t: round(assets.get(t, {}).get("firm_score", 0.0) / 5.0 * 100.0, 2)
        for t in weights
    }
    top_drivers = sorted(by_ticker, key=by_ticker.__getitem__, reverse=True)[:3]

    return PortfolioRisk(
        score=risk_calc["score"],
        objective_score=risk_calc["objective"],
        personalized_score=risk_calc["personalized"],
        confidence=risk_calc["confidence"],
        by_ticker=by_ticker,
        top_drivers=top_drivers,
        explanation=(
            f"2-stage formula — objective: {risk_calc['objective']:.1f}/100, "
            f"personalized: {risk_calc['personalized']:.1f}/100, "
            f"confidence: {risk_calc['confidence']:.2f}"
        ),
        components=risk_calc.get("components", {}),
    )
