"""Deterministic scoring. The LLM explains these numbers; it never invents them."""


def ticker_risk(country_exposure: dict[str, float], country_scores: dict[str, float]) -> float:
    """Exposure-weighted average of country risk scores (0-100). Exposure weights sum to <= 1."""
    return sum(w * country_scores.get(c, 0.0) for c, w in country_exposure.items())


def portfolio_risk(weights: dict[str, float], ticker_scores: dict[str, float]) -> float:
    return sum(w * ticker_scores.get(t, 0.0) for t, w in weights.items())


# ---------- Country / asset / portfolio risk, watchlist ----------
from datetime import date as _date
from itertools import product
from typing import Callable, Optional

from core.schemas import AssetReport, Claim, Event

# All scores below are on [0, 1] (multiply by 100 to display). Each is a weighted mean of
# components that are themselves on [0, 1], so the result is bounded and decomposable.
COUNTRY_COMPONENTS = ("gpr", "epu", "vol", "claims")
EQUAL_COUNTRY_WEIGHTS = {k: 1 / len(COUNTRY_COMPONENTS) for k in COUNTRY_COMPONENTS}
EQUAL_ASSET_WEIGHTS = {"exposure": 1 / 3, "filing": 1 / 3, "market": 1 / 3}


def percentile_rank(x: float, history: list[float]) -> Optional[float]:
    """Share of the reference sample that is <= x, in [0, 1]. None when there is no history."""
    return sum(h <= x for h in history) / len(history) if history else None


def claim_quality(claims: list[Claim]) -> Optional[float]:
    """Confidence-weighted mean claim severity, scaled from 0-5 to [0, 1]. None without claims."""
    w = sum(c.confidence for c in claims)
    return sum(c.confidence * c.score for c in claims) / (5 * w) if w else None


def filing_risk(claims: list[Claim], top: int = 3) -> Optional[float]:
    """F_i on [0, 1]: half the confidence-weighted mean severity of all filing claims, half that of the `top`
    most severe ones (severity x confidence). The mean alone would let many minor risks dilute one grave risk."""
    if not claims:
        return None
    worst = sorted(claims, key=lambda c: c.score * c.confidence, reverse=True)[:top]
    return 0.5 * claim_quality(claims) + 0.5 * claim_quality(worst)


# Fixed, documented bounds (not fitted to the portfolio): annualised volatility 10%-60%, beta 0.5-2.0.
VOL_BOUNDS = (0.10, 0.60)
BETA_BOUNDS = (0.5, 2.0)


def _scale(x: float, bounds: tuple[float, float]) -> float:
    low, high = bounds
    return min(1.0, max(0.0, (x - low) / (high - low)))


def market_risk(vol_1y: Optional[float], beta: Optional[float]) -> Optional[float]:
    """M_i on [0, 1]: mean of the volatility and beta scores, each linear between fixed bounds. None if both unknown."""
    parts = [_scale(v, b) for v, b in ((vol_1y, VOL_BOUNDS), (beta, BETA_BOUNDS)) if v is not None]
    return sum(parts) / len(parts) if parts else None


def _blend(values: dict[str, Optional[float]], weights: dict[str, float]) -> tuple[float, dict[str, float]]:
    """Weighted mean over the available values; weights are renormalised, a missing value never counts as 0.
    Returns (score, contribution of each used component, summing to score)."""
    if any(w < 0 for w in weights.values()) or not any(w > 0 for w in weights.values()):
        raise ValueError("weights must be non-negative with a positive sum")
    for k, v in values.items():
        if v is not None and not 0.0 <= v <= 1.0:
            raise ValueError(f"{k} must be in [0, 1]")
    used = {k: v for k, v in values.items() if v is not None and weights.get(k, 0) > 0}
    if not used:
        raise ValueError("no component available")
    total = sum(weights[k] for k in used)
    contrib = {k: weights[k] / total * v for k, v in used.items()}
    return sum(contrib.values()), contrib


def country_risk(gpr: Optional[float], epu: Optional[float], vol: Optional[float], claims: list[Claim],
                 weights: dict[str, float] = EQUAL_COUNTRY_WEIGHTS) -> tuple[float, dict[str, float]]:
    """R_c = sum_k a_k * p_k over GPR, EPU and volatility percentile ranks and claim quality Q_c.
    Inputs gpr/epu/vol are percentile ranks in [0, 1] (see percentile_rank)."""
    return _blend({"gpr": gpr, "epu": epu, "vol": vol, "claims": claim_quality(claims)}, weights)


def asset_risk(w_ic: dict[str, float], R: dict[str, float], filing: Optional[float] = None,
               market: Optional[float] = None, weights: dict[str, float] = EQUAL_ASSET_WEIGHTS
               ) -> tuple[float, dict[str, float], dict[str, float]]:
    """G_i = a * sum_c w_ic R_c + b * F_i + c * M_i, with F_i the filing-risk score and M_i the market-risk score.
    Revenue shares that are unknown or in unscored countries (incl. 'Other', and any share missing from w_ic)
    take the mean R of the scored countries, never 0; with no known split the exposure term is omitted. Returns (G_i, component contributions, per-country contributions)."""
    if any(w < 0 for w in w_ic.values()) or sum(w_ic.values()) > 1 + 1e-9:
        raise ValueError("revenue shares must be non-negative and sum to at most 1")
    per_country: dict[str, float] = {}
    exposure: Optional[float] = None
    if R and sum(w_ic.values()) > 0:  # with no known revenue split at all, the exposure term is missing, not guessed
        default = sum(R.values()) / len(R)
        shares = {**w_ic, "Other": w_ic.get("Other", 0.0) + max(0.0, 1.0 - sum(w_ic.values()))}
        per_country = {c: w * R.get(c, default) for c, w in shares.items() if w > 0}
        exposure = sum(per_country.values())
    score, contrib = _blend({"exposure": exposure, "filing": filing, "market": market}, weights)
    return score, contrib, per_country


def portfolio_scores(weights: dict[str, float], G: dict[str, float]) -> tuple[float, dict[str, float]]:
    """P = sum_i w_i G_i. Returns (P, contribution of each holding)."""
    if abs(sum(weights.values()) - 1.0) > 1e-9 or any(w < 0 for w in weights.values()):
        raise ValueError("portfolio weights must be non-negative and sum to 1")
    contrib = {t: w * G[t] for t, w in weights.items()}
    return sum(contrib.values()), contrib


def scenario_shock(weights: dict[str, float], assets: dict[str, dict[str, float]],
                   intensity: dict[str, float], likelihood: float) -> float:
    """Shock = L * sum_i w_i sum_c w_ic I_c, with I_c the scenario intensity per country (0-1) and L its
    probability. It lies in [0, L]; the stressed score is min(1, P + shock)."""
    if not 0.0 <= likelihood <= 1.0 or any(not 0.0 <= v <= 1.0 for v in intensity.values()):
        raise ValueError("likelihood and intensities must be in [0, 1]")
    exposed = sum(w * sum(share * intensity.get(c, 0.0) for c, share in assets[t].items())
                  for t, w in weights.items())
    return likelihood * exposed


def ranking_stability(score_fn: Callable[[dict[str, float]], dict[str, float]], base: dict[str, float],
                      delta: float = 0.2) -> float:
    """Share of weight perturbations (each weight scaled by 1-delta or 1+delta, then renormalised) that keep
    the base ranking of the scored items. 1.0 means the ranking does not depend on the exact weights."""
    def order(weights: dict[str, float]) -> list[str]:
        scores = score_fn(weights)
        return sorted(scores, key=lambda k: (-scores[k], k))
    keys = list(base)
    reference = order(base)
    same = total = 0
    for factors in product((1 - delta, 1 + delta), repeat=len(keys)):
        perturbed = {k: base[k] * f for k, f in zip(keys, factors)}
        norm = sum(perturbed.values())
        same += order({k: v / norm for k, v in perturbed.items()}) == reference
        total += 1
    return same / total


def country_exposure(weights: dict[str, float], assets: dict[str, AssetReport]) -> dict[str, float]:
    """X_c = sum_i w_i * w_ic."""
    X: dict[str, float] = {}
    for t, w_i in weights.items():
        for c, w_ic in assets[t].country_weights.items():
            X[c] = X.get(c, 0.0) + w_i * w_ic
    return X


def watchlist(events: list[Event], weights: dict[str, float], assets: dict[str, AssetReport],
              as_of: str, top: int = 5) -> list[dict]:
    """Rank events by I_e = X * severity * likelihood / (1 + days_until/90). Past events are skipped.
    X is X_c for country events and w_i for firm-specific ones."""
    X = country_exposure(weights, assets)
    today = _date.fromisoformat(as_of)
    ranked = []
    for e in events:
        days = (_date.fromisoformat(e.date) - today).days
        if days < 0:
            continue
        if e.ticker:
            x, holdings = weights.get(e.ticker, 0.0), [e.ticker]
        else:
            x = X.get(e.country or "", 0.0)
            holdings = [t for t, a in assets.items() if weights.get(t, 0) > 0 and a.country_weights.get(e.country or "", 0) > 0]
        ranked.append({"event": e, "impact": x * e.severity * e.likelihood / (1 + days / 90),
                       "affected_holdings": holdings})
    return sorted(ranked, key=lambda r: -r["impact"])[:top]
