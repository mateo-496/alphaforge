"""Deterministic scoring. The LLM explains these numbers; it never invents them."""
from tools.portfolio_score import (
    Params,
    calculate_portfolio_risk,
    portfolio_scores,
)


# ── Per-domain channel-severity amplifiers ───────────────────────────────────
# Weights capture how much each geopolitical channel matters in each domain.
# They are fixed constants; identical inputs always produce identical scores.

#: Amplifiers for the filings agent (firm-level geopolitical exposure from SEC filings).
#: Export controls and sanctions are the most material for companies.
FILINGS_CHANNEL_WEIGHTS: dict[str, float] = {
    "export_controls":    1.4,
    "sanctions":          1.4,
    "trade_tariffs":      1.2,
    "conflict_exposure":  1.2,
    "supply_chain":       1.1,
    "regulatory":         1.0,
    "fx_capital_controls": 1.0,
    "financial_stress":   0.9,
}

#: Amplifiers for the geopolitical agent (country-level GPR risk).
#: Conflict and sanctions drive the highest sovereign-risk premium.
GEO_CHANNEL_WEIGHTS: dict[str, float] = {
    "conflict_exposure":  1.5,
    "sanctions":          1.3,
    "trade_tariffs":      1.1,
    "export_controls":    1.1,
    "fx_capital_controls": 1.0,
    "financial_stress":   1.0,
    "supply_chain":       0.9,
    "regulatory":         0.8,
}



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


# ── Agent-output scoring functions ───────────────────────────────────────────
# Each function takes an AgentOutput (the agent's JSON contract) and returns a
# plain dict with a deterministic numeric score.  Identical inputs → identical
# outputs.  The LLM never touches these numbers.

from core.schemas import AgentOutput  # noqa: E402  (import after other local defs)


def q_bar_weighted(claims: list[Claim], channel_weights: dict[str, float] | None = None) -> float:
    """Channel-weighted, confidence-weighted mean claim score ∈ [0, 5].

    Equation
    --------
    q = Σ_i (w_ch_i · c_i · s_i) / Σ_i (w_ch_i · c_i)

    where
      w_ch_i  = channel_weights[channel_i] (1.0 if channel_weights is None)
      c_i     ∈ [0, 1]  confidence of claim i
      s_i     ∈ [0, 5]  severity score of claim i

    Returns 0.0 for empty claim lists (no score possible without evidence).
    """
    if not claims:
        return 0.0
    total_w = 0.0
    total_ws = 0.0
    for c in claims:
        ch_w = channel_weights.get(c.channel, 1.0) if channel_weights else 1.0
        w = ch_w * c.confidence
        total_w += w
        total_ws += w * c.score
    return total_ws / total_w if total_w > 0 else 0.0


def score_filings(output: AgentOutput) -> dict[str, float]:
    """Deterministic firm-exposure score from a filings AgentOutput (A3 input).

    Scoring equation
    ----------------
    firm_score = q_bar_weighted(claims, FILINGS_CHANNEL_WEIGHTS)   ∈ [0, 5]
    confidence = (mean_claim_confidence) × min(1, n_claims / 5)    ∈ [0, 1]

    The coverage term (min(1, n/5)) shrinks confidence when fewer than 5
    claims are available; it reaches 1 at 5+ claims.

    Returns
    -------
    {"firm_score": float, "confidence": float, "num_claims": int}
    """
    claims = output.claims
    if not claims:
        return {"firm_score": 0.0, "confidence": 0.0, "num_claims": 0}
    fs = q_bar_weighted(claims, FILINGS_CHANNEL_WEIGHTS)
    mean_conf = sum(c.confidence for c in claims) / len(claims)
    coverage = min(1.0, len(claims) / 5.0)
    return {
        "firm_score": round(fs, 4),
        "confidence": round(mean_conf * coverage, 4),
        "num_claims": len(claims),
    }


def score_geopolitical(output: AgentOutput) -> dict[str, float]:
    """Deterministic country risk score R from a geopolitical AgentOutput (A1/A2 input).

    Scoring equation
    ----------------
    R = q_bar_weighted(claims, GEO_CHANNEL_WEIGHTS) / 5 × 100   ∈ [0, 100]
    confidence = (mean_claim_confidence) × min(1, n_claims / 4)  ∈ [0, 1]

    The coverage term reaches 1 at 4+ claims (GPR analysis typically yields
    fewer but higher-quality claims than filings analysis).

    Returns
    -------
    {"R": float, "confidence": float, "num_claims": int}
    """
    claims = output.claims
    if not claims:
        return {"R": 0.0, "confidence": 0.0, "num_claims": 0}
    q = q_bar_weighted(claims, GEO_CHANNEL_WEIGHTS)
    r = q / 5.0 * 100.0
    mean_conf = sum(c.confidence for c in claims) / len(claims)
    coverage = min(1.0, len(claims) / 4.0)
    return {
        "R": round(r, 2),
        "confidence": round(mean_conf * coverage, 4),
        "num_claims": len(claims),
    }
