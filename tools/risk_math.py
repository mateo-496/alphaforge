"""Deterministic scoring. The LLM explains these numbers; it never invents them."""
import math
from statistics import fmean, pstdev


def ticker_risk(country_exposure: dict[str, float], country_scores: dict[str, float]) -> float:
    """Exposure-weighted average of country risk scores (0-100). Exposure weights sum to <= 1."""
    return sum(w * country_scores.get(c, 0.0) for c, w in country_exposure.items())


def portfolio_risk(weights: dict[str, float], ticker_scores: dict[str, float]) -> float:
    return sum(w * ticker_scores.get(t, 0.0) for t, w in weights.items())


# ---------- Risk formula v2: mechanical, every input measured ----------
# No LLM-made number enters the score. LLMs only extract facts (verbatim quotes, country lists) that code verifies.
#
#   Exposure        X_c  = sum_i w_i w_ic                                  (SEC revenue tables, parsed by code)
#   Country hazard  g_c  = L_c (1/2 + heat_c/2), see hazard() below          (WGI + Caldara-Iacoviello GPR, 0-1)
#   Market stress   m    = mean z of OFR FSI, STLFSI4, VIX (3-year window);  A = 1 + 0.15 clip(m, 0, 3)
#   Firm flags      f_i  = share of the 8 risk channels with a verified quote in the filing (code-checked)
#   Holding         G_i  = 100 [ a_i A sum_c w_ic g_c + (1 - a_i) f_i ],  a_i = 0.8 if the filing was read, else 1
#   Portfolio       P    = sum_i w_i G_i            -> additive: every point is traced to a country or a filing
#
# 50 = a typical month for the countries the portfolio earns in, in calm markets.
# Scenarios are NOT in P: they are a what-if table, E_s = sum_c X_c 1[country directly involved in s].
GAMMA = 0.15
LAMBDA_FIRM = 0.2
N_CHANNELS = 8
INVOLVED = 0.5      # scenario intensity at or above which a country counts as directly involved
Z_WINDOW_DAYS = 3 * 365
MOVE_LAG = 20


def _clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return min(hi, max(lo, x))


def percentile(x: float, history: list[float]) -> float:
    """Share of the history at or below x (0-1). 'Higher than 72% of past months' reads directly."""
    return sum(v <= x for v in history) / len(history) if history else 0.5


def level_z(values: list[float]) -> float | None:
    """z-score of the last value against the whole window (None if too short or flat)."""
    if len(values) < 30:
        return None
    sd = pstdev(values)
    return (values[-1] - fmean(values)) / sd if sd else None


def move_z(values: list[float], lag: int = MOVE_LAG) -> float | None:
    """z-score of the latest `lag`-observation change against all such changes in the window."""
    d = [b - a for a, b in zip(values, values[lag:])]
    if len(d) < 30:
        return None
    sd = pstdev(d)
    return (d[-1] - fmean(d)) / sd if sd else None


def market_stress_level(global_z: dict[str, float | None]) -> float | None:
    zs = [v for v in global_z.values() if v is not None]
    return fmean(zs) if zs else None


def amplifier(m: float | None, gamma: float = GAMMA) -> float:
    return 1 + gamma * _clip(m, 0, 3) if m is not None else 1.0


# ---------- Country hazard g_c (A2 input): level across countries x heat vs. own history ----------
#   S_c    = clip((1.5 - PV_c) / 3.5)        internal instability, WGI political stability PV (about -2.5..2.5)
#   E_c    = clip((ln GPR12_c - lo) / (hi - lo))   external tension: 12-month mean GPR level on a log scale,
#            lo = 10th percentile, hi = max over the covered countries (tools/gpr.tension_anchors).
#            Not used for PRESS_COUNTRIES: GPR counts articles in US, UK and Canadian newspapers, so home
#            coverage inflates their level.
#   L_c    = mean of the available parts of (S_c, E_c)        (None if neither is available)
#   heat_c = percentile of GPR_c among its own past months (global GPR when the country is not covered)
#   g_c    = L_c * (1/2 + heat_c / 2)         a calm country stays calm when its news coverage spikes
PV_SAFE, PV_DANGER = 1.5, -2.0
PRESS_COUNTRIES = frozenset({"USA", "GBR", "CAN"})


def instability(pv: float | None) -> float | None:
    """S_c from the WGI political-stability estimate."""
    return None if pv is None else _clip((PV_SAFE - pv) / (PV_SAFE - PV_DANGER))


def tension(mean_12m: float | None, anchors: tuple[float, float] | None, iso3: str = "") -> float | None:
    """E_c from the 12-month mean GPR level; None for press countries or without data."""
    if mean_12m is None or mean_12m <= 0 or not anchors or iso3 in PRESS_COUNTRIES:
        return None
    lo, hi = anchors
    return _clip((math.log(mean_12m) - lo) / (hi - lo)) if hi > lo else None


def hazard(S: float | None, E: float | None, heat: float | None) -> float | None:
    """g_c = L_c (1/2 + heat/2). Heat alone (no level) is not a hazard: returns None, so A2 is shrunk."""
    parts = [x for x in (S, E) if x is not None]
    if not parts:
        return None
    L = sum(parts) / len(parts)
    return L * (0.5 + 0.5 * (heat if heat is not None else 0.5))


def firm_flags(channels_verified: list[str] | None) -> float | None:
    """f_i: share of risk channels for which the filing has a verified quote. None = filing not read."""
    return None if channels_verified is None else len(set(channels_verified)) / N_CHANNELS


def holding_score(w_ic: dict[str, float], g: dict[str, float], A: float, f: float | None,
                  lam: float = LAMBDA_FIRM) -> dict:
    """G_i with its parts: points per country and points from the filing."""
    a = 1 - lam if f is not None else 1.0
    per_country = {c: 100 * a * A * w * g.get(c, g.get("Other", 0.5)) for c, w in w_ic.items()}
    firm = 100 * (1 - a) * f if f is not None else 0.0
    return {"G": sum(per_country.values()) + firm, "countries": per_country, "firm": firm}


def portfolio_score(weights: dict[str, float], holdings: dict[str, dict]) -> dict:
    """P = sum_i w_i G_i, with exact additive contributions by holding, by country and from filings."""
    by_holding = {t: w * holdings[t]["G"] for t, w in weights.items()}
    by_country: dict[str, float] = {}
    for t, w in weights.items():
        for c, pts in holdings[t]["countries"].items():
            by_country[c] = by_country.get(c, 0.0) + w * pts
    firm = sum(w * holdings[t]["firm"] for t, w in weights.items())
    return {"P": sum(by_holding.values()), "by_holding": by_holding, "by_country": by_country, "firm": firm}


def scenario_exposure(scenario: dict, X: dict[str, float]) -> float:
    """E_s: share of portfolio revenue in countries directly involved in the scenario (no probability)."""
    return sum(x for c, x in X.items() if scenario["countries"].get(c, 0) >= INVOLVED)


# ---------- verdict, from the investor's profile ----------
# Risk tolerance (profile risk_level 1-5) sets how far above a typical month (50) the score may go.
TOLERANCE = {1: 50, 2: 55, 3: 60, 4: 65, 5: 70}


def level(P: float) -> str:
    return "below normal" if P < 40 else "normal" if P < 60 else "elevated" if P < 75 else "high"


def verdict(P: float, risk_level: int, A: float, conflicts: int) -> dict:
    """Mechanical verdict: every test is shown to the user. 'clear' = no immediate danger for this profile."""
    T = TOLERANCE.get(risk_level, 60)
    tests = [{"name": f"Score within the profile's tolerance ({T})", "ok": P <= T, "value": f"{P:.0f}"},
             {"name": "Markets not under acute stress (amplifier ≤ ×1.15)", "ok": A <= 1.15, "value": f"×{A:.2f}"},
             {"name": "No conflict with the profile's stated limits", "ok": conflicts == 0, "value": str(conflicts)}]
    return {"clear": all(t["ok"] for t in tests), "tolerance": T, "tests": tests}


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


# ── Agent-output scoring functions ───────────────────────────────────────────
# Each function takes an AgentOutput (the agent's JSON contract) and returns a
# plain dict with a deterministic numeric score.  Identical inputs → identical
# outputs.  The LLM never touches these numbers.

from core.schemas import AgentOutput  # noqa: E402  (import after other local defs)



# ── Per-domain channel-severity amplifiers (restored from origin/equation) ──
FILINGS_CHANNEL_WEIGHTS: dict[str, float] = {
    "export_controls": 1.4, "sanctions": 1.4, "trade_tariffs": 1.2, "conflict_exposure": 1.2,
    "supply_chain": 1.1, "regulatory": 1.0, "fx_capital_controls": 1.0, "financial_stress": 0.9,
}
GEO_CHANNEL_WEIGHTS: dict[str, float] = {
    "conflict_exposure": 1.5, "sanctions": 1.3, "trade_tariffs": 1.1, "export_controls": 1.1,
    "fx_capital_controls": 1.0, "financial_stress": 1.0, "supply_chain": 0.9, "regulatory": 0.8,
}

#: Power-mean exponent used when turning claims into one score. p = 1 is the
#: plain weighted mean; p = 3 lets one severe, well-sourced claim dominate a
#: handful of minor ones (a firm with one 5/5 sanctions exposure is not "fine
#: on average"), while all-equal claims still return that same score.
CLAIM_POWER: float = 3.0


def q_bar_weighted(claims: list[Claim], channel_weights: dict[str, float] | None = None,
                   p: float = 1.0) -> float:
    """Channel-weighted, confidence-weighted power mean of claim scores ∈ [0, 5].

    Equation
    --------
    q = ( Σ_i (w_ch_i · c_i · s_i^p) / Σ_i (w_ch_i · c_i) )^{1/p}

    where
      w_ch_i  = channel_weights[channel_i] (1.0 if channel_weights is None)
      c_i     ∈ [0, 1]  confidence of claim i
      s_i     ∈ [0, 5]  severity score of claim i
      p       ≥ 1       power (1 = weighted mean, the default)

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
        total_ws += w * float(c.score) ** p
    return (total_ws / total_w) ** (1.0 / p) if total_w > 0 else 0.0


def score_filings(output: AgentOutput) -> dict[str, float]:
    """Deterministic firm-exposure score from a filings AgentOutput (A3 input).

    Scoring equation
    ----------------
    firm_score = q_bar_weighted(claims, FILINGS_CHANNEL_WEIGHTS, p=CLAIM_POWER)   ∈ [0, 5]
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
    fs = q_bar_weighted(claims, FILINGS_CHANNEL_WEIGHTS, p=CLAIM_POWER)
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
    R = q_bar_weighted(claims, GEO_CHANNEL_WEIGHTS, p=CLAIM_POWER) / 5 × 100   ∈ [0, 100]
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
    q = q_bar_weighted(claims, GEO_CHANNEL_WEIGHTS, p=CLAIM_POWER)
    r = q / 5.0 * 100.0
    mean_conf = sum(c.confidence for c in claims) / len(claims)
    coverage = min(1.0, len(claims) / 4.0)
    return {
        "R": round(r, 2),
        "confidence": round(mean_conf * coverage, 4),
        "num_claims": len(claims),
    }
