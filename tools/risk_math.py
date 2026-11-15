"""Deterministic scoring. The LLM explains these numbers; it never invents them."""


def ticker_risk(country_exposure: dict[str, float], country_scores: dict[str, float]) -> float:
    """Exposure-weighted average of country risk scores (0-100). Exposure weights sum to <= 1."""
    return sum(w * country_scores.get(c, 0.0) for c, w in country_exposure.items())


def portfolio_risk(weights: dict[str, float], ticker_scores: dict[str, float]) -> float:
    return sum(w * ticker_scores.get(t, 0.0) for t, w in weights.items())


# ---------- Country / asset / portfolio risk, watchlist ----------
from datetime import date as _date
from statistics import fmean, pstdev

from core.schemas import AssetReport, Claim, Event


def z(x: float, history: list[float]) -> float:
    """z-score of x against a reference sample (0 if the sample is degenerate)."""
    sd = pstdev(history) if len(history) > 1 else 0.0
    return (x - fmean(history)) / sd if sd else 0.0


def q_bar(claims: list[Claim]) -> float:
    """Confidence-weighted average claim score (0-5)."""
    w = sum(c.confidence for c in claims)
    return sum(c.confidence * c.score for c in claims) / w if w else 0.0


def country_risk(gpr_z: float, epu_z: float, vol_z: float, claims: list[Claim]) -> float:
    """R_c = mean(z(GPR), z(EPU), z(Vol), Q_c). NOTE: Q_c is on a 0-5 scale, z-scores are not."""
    return fmean([gpr_z, epu_z, vol_z, q_bar(claims)])


def asset_risk(w_ic: dict[str, float], R: dict[str, float], beta_gpr_z: float, claims: list[Claim],
               lambdas: tuple[float, float, float] = (0.6, 0.2, 0.2)) -> float:
    """G_i = l1 * sum_c w_ic R_c + l2 * z(beta_gpr) + l3 * Q_i. Unknown countries (incl. 'Other') use R['Other']."""
    l1, l2, l3 = lambdas
    exposure = sum(w * R.get(c, R.get("Other", 0.0)) for c, w in w_ic.items())
    return l1 * exposure + l2 * beta_gpr_z + l3 * q_bar(claims)


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
