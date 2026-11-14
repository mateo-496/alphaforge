"""Deterministic scoring. The LLM explains these numbers; it never invents them."""


def ticker_risk(country_exposure: dict[str, float], country_scores: dict[str, float]) -> float:
    """Exposure-weighted average of country risk scores (0-100). Exposure weights sum to <= 1."""
    return sum(w * country_scores.get(c, 0.0) for c, w in country_exposure.items())


def portfolio_risk(weights: dict[str, float], ticker_scores: dict[str, float]) -> float:
    return sum(w * ticker_scores.get(t, 0.0) for t, w in weights.items())
