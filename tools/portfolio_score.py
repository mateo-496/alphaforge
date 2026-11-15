"""Deterministic portfolio risk scoring.

Combines four agent outputs into an objective risk score and a
personalized concern score. The user's risk tolerance affects ONLY
the personalized score; the objective score is independent of it.

Agents
------
A₁  National risk        (0–1)
A₂  Geopolitical risk    (0–1)
A₃  Country-index risk   (0–1)
A₄  User risk tolerance  (0–1, higher = more tolerant)

Each risk input has a confidence cᵢ ∈ [0, 1].

Two-stage formula
-----------------
Stage 0 — Agent inputs (extract_agent_inputs), each mapped to [0, 1]:
  A₁ = g(M₂(R_c ; X_c), m₁)          exposure-weighted power mean of country risk, calibrated
  A₂ = 1 − exp(−EL / EL_ref)         EL = Σ_s likelihood_s · impact_s/5 · exposure_s
  A₃ = g(M₂(firm_i/5 ; w_i), m₃)     holding-weighted power mean of firm risk, calibrated
  (k₁ = 2, k₃ = 1.5)
  where M_p(x; w) = (Σ w·x^p / Σ w)^{1/p}   (p > 1 leans toward the worst exposures)
  and   g(x, m) = r^k / (1 + r^k),  r = [x/(1−x)] / [m/(1−m)]
        (odds-ratio S-curve: g(0)=0, g(m)=0.5, g(1)=1; m = "typical" level).

Stage 1 — Objective risk R ∈ [0, 1]:
  (1) Shrinkage:        Ãᵢ  = cᵢ·Aᵢ + (1−cᵢ)·μ
  (2) Transform:        f(x) = (e^{λx} − 1) / (e^λ − 1)   (λ = 0 → identity, the default)
  (3) Structural block: F_S = α·f(Ã₁) + (1−α)·f(Ã₃)
      Geopolitical:     F_G = f(Ã₂)
  (4) Base risk:        B   = (w_S·F_S^q + w_G·F_G^q)^{1/q}
  (5) Interaction:      R₀  = B + η·F_S·F_G·(1 − B)
  (6) Red-flag penalty: h   = (max(0, max(Ãᵢ) − τ) / (1 − τ))²
      Objective risk:   R   = R₀ + κ·h·(1 − R₀)
  Uniform inputs map close to themselves (A=x → R≈x), so the score spans 0-100.

Stage 2 — Personalized concern C ∈ [0, 100]:
  (7) Comfort level:    ρ(t)= a + b·t
      Normalized logistic gap mapping R → C:
      C = 100 · [σ(k(R−ρ)) − σ(−kρ)] / [σ(k(1−ρ)) − σ(−kρ)]

Reference worked example
-------------------------
  portfolio_scores(0.45, 0.70, 0.55, 0.4, conf=(0.9, 0.6, 1.0))
  → {'objective': 58.74, 'personalized': 78.01, 'confidence': 0.81}
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Params:
    """All tunable parameters, frozen for determinism."""

    lam: float = 0.0         # λ  – convexity of f (0 = identity; >0 compresses low/mid risk)
    w_S: float = 0.60        # structural block weight
    w_G: float = 0.40        # geopolitical block weight  (w_S + w_G = 1)
    alpha: float = 0.50      # split inside the structural block (A₁ vs A₃)
    q: float = 2.0           # power-mean exponent combining blocks (>1: worst block dominates)
    eta: float = 0.25        # η  – interaction (reinforcement) coefficient
    tau: float = 0.70        # τ  – red-flag threshold
    kappa: float = 0.35      # κ  – red-flag penalty strength
    k: float = 8.0           # logistic steepness for personalized score
    a: float = 0.15          # comfort-level intercept
    b: float = 0.70          # comfort-level slope
    mu: float = 0.50         # prior for shrinkage (neutral risk)
    # Stage 0 – input calibration (extract_agent_inputs)
    agg_p: float = 2.0       # power-mean exponent across countries / holdings
    m1: float = 0.40         # typical country risk (R_c = 40/100) → A₁ = 0.5
    m3: float = 0.50         # typical firm risk (firm_score = 2.5/5) → A₃ = 0.5
    k1: float = 2.0          # S-curve steepness for A₁ (1 = no stretch)
    k3: float = 1.5          # S-curve steepness for A₃
    el_ref: float = 0.15     # expected scenario shock that maps to A₂ = 1 − 1/e ≈ 0.63
    default_exposure: float = 0.5  # scenario exposure when it cannot be computed
    # Stage 1 (8) – final calibration of R: R* = g(R, r_mid, r_k)  (r_mid = 0.5, r_k = 1 is the identity)
    r_mid: float = 0.5       # raw R that maps to 50
    r_k: float = 1.0         # spread around r_mid


# ── Tolerance mappings ────────────────────────────────────────────────

TOLERANCE_MAP: dict[str, float] = {
    "low": 0.20,
    "low_moderate": 0.40,
    "low-moderate": 0.40,
    "moderate": 0.60,
    "moderate_high": 0.75,
    "moderate-high": 0.75,
    "high": 0.85,
}


def parse_tolerance(val: float | str | None, default: float = 0.50) -> float:
    """Safely map any tolerance input (string, numeric, None, NaN) to [0, 1].

    Deterministic: identical inputs always yield identical outputs.
    """
    if val is None:
        return default
    if isinstance(val, str):
        key = val.strip().lower().replace(" ", "_")
        return TOLERANCE_MAP.get(key, default)
    try:
        f = float(val)
        if math.isnan(f):
            return default
        # Auto-scale if provided as 0..100 percentage
        if 1.0 < f <= 100.0:
            f = f / 100.0
        return max(0.0, min(1.0, f))
    except (ValueError, TypeError):
        return default


# ── helpers ──────────────────────────────────────────────────────────

def _f(x: float, lam: float) -> float:
    """Normalized exponential transform f: [0,1] → [0,1].

    f(x) = (e^{λx} − 1) / (e^λ − 1).

    Strictly convex for λ > 0. As λ → 0 the function approaches the
    identity, so the linear model is a special case.
    """
    if lam == 0:
        return x
    return (math.exp(lam * x) - 1.0) / (math.exp(lam) - 1.0)


def _sig(z: float) -> float:
    """Logistic (sigmoid) function σ(z) = 1 / (1 + e^{−z}).

    Numerically stable for large |z|.
    """
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    ez = math.exp(z)
    return ez / (1.0 + ez)


def _clamp(x: float | None, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp *x* to [lo, hi]; treat None / NaN as the prior μ = 0.5."""
    if x is None or math.isnan(x):
        return 0.5  # will be overridden by shrinkage anyway
    return max(lo, min(hi, float(x)))


def calibrate(x: float, mid: float, k: float) -> float:
    """Odds-ratio S-curve g: [0,1] → [0,1] that sends the typical level *mid* to 0.5.

    g(x) = r^k / (1 + r^k),   r = [x / (1−x)] / [mid / (1−mid)]

    g(0)=0, g(mid)=0.5, g(1)=1, strictly increasing. k > 1 spreads values
    around *mid* apart; (mid=0.5, k=1) is the identity.
    """
    x = _clamp(x)
    if x <= 0.0 or x >= 1.0:
        return x
    mid = min(max(mid, 1e-6), 1.0 - 1e-6)
    r = (x / (1.0 - x)) / (mid / (1.0 - mid))
    rk = r ** k
    return rk / (1.0 + rk)


def power_mean(pairs: list[tuple[float, float]], p: float) -> float | None:
    """Weighted power mean M_p = (Σ w·x^p / Σ w)^{1/p} over (x, w) pairs with x ≥ 0.

    p = 1 is the weighted average; p > 1 leans toward the largest values so a
    concentrated hotspot is not averaged away. Returns None if Σw = 0.
    """
    tw = sum(w for _, w in pairs)
    if tw <= 0:
        return None
    m = sum(w * max(0.0, x) ** p for x, w in pairs) / tw
    return m ** (1.0 / p)


# ── main scoring function ───────────────────────────────────────────

def portfolio_scores(
    a1: float | None,
    a2: float | None,
    a3: float | None,
    tolerance: float | str | None,
    *,
    conf: tuple[float, float, float] = (1.0, 1.0, 1.0),
    firm_share: float = 1.0,
    p: Params = Params(),
) -> dict[str, float]:
    """Compute objective and personalized portfolio risk scores.

    Parameters
    ----------
    a1 : float | None
        National risk score ∈ [0, 1].
    a2 : float | None
        Geopolitical risk score ∈ [0, 1].
    a3 : float | None
        Country-index risk score ∈ [0, 1].
    tolerance : float | str | None
        User risk tolerance ∈ [0, 1] or string ("low", "moderate", "high").
        Does NOT affect the objective score.
    conf : tuple[float, float, float]
        Confidence for (a1, a2, a3), each ∈ [0, 1].
    firm_share : float
        Share s ∈ [0, 1] of the portfolio held in single companies. The
        company term applies to that sleeve only: funds, bonds, gold and
        crypto have no filing, which is "not applicable", not "unknown".
        s = 1 reproduces the original formula.
    p : Params
        All tunable parameters (frozen dataclass).

    Returns
    -------
    dict with keys:
        objective     – 0–100, independent of user tolerance
        personalized  – 0–100, user-adjusted concern
        confidence    – 0–1,   weighted average confidence
    """
    # ── 0. Clamp & default ──────────────────────────────────────────
    A1 = _clamp(a1)
    A2 = _clamp(a2)
    A3 = _clamp(a3)
    t = parse_tolerance(tolerance, default=p.mu)

    c1 = _clamp(conf[0] if len(conf) > 0 else 1.0)
    c2 = _clamp(conf[1] if len(conf) > 1 else 1.0)
    c3 = _clamp(conf[2] if len(conf) > 2 else 1.0)

    # ── STAGE 1: Objective risk ─────────────────────────────────────

    # (1) Shrinkage toward prior μ  (low-confidence → neutral)
    A1t = c1 * A1 + (1.0 - c1) * p.mu
    A2t = c2 * A2 + (1.0 - c2) * p.mu
    A3t = c3 * A3 + (1.0 - c3) * p.mu

    # (2) Convex transform
    fA1 = _f(A1t, p.lam)
    fA2 = _f(A2t, p.lam)
    fA3 = _f(A3t, p.lam)

    # (3) Structural and geopolitical blocks
    #     A₁ and A₃ share one block (they overlap on country fundamentals).
    #     The company term only covers the company sleeve s:
    #     F_S = (1 − (1−α)s)·f(Ã₁) + (1−α)s·f(Ã₃)
    s = _clamp(firm_share)
    w3 = (1.0 - p.alpha) * s
    F_S = (1.0 - w3) * fA1 + w3 * fA3
    F_G = fA2

    # (4) Base risk: weighted power mean of the blocks (q > 1 → the worse
    #     block dominates; a portfolio is as risky as its weakest dimension).
    B = (p.w_S * F_S ** p.q + p.w_G * F_G ** p.q) / (p.w_S + p.w_G)
    B = B ** (1.0 / p.q)

    # (5) Interaction term (super-additive reinforcement)
    #     Both structural AND geopolitical risk present → worse than sum.
    R0 = B + p.eta * F_S * F_G * (1.0 - B)

    # (6) Red-flag penalty (weakest-link rule)
    #     Squared hinge: zero below τ, smooth ramp above.
    peak = max(A1t, A2t, A3t) if s > 0 else max(A1t, A2t)
    h = (max(0.0, peak - p.tau) / (1.0 - p.tau)) ** 2 if p.tau < 1.0 else 0.0
    R = R0 + p.kappa * h * (1.0 - R0)

    # (8) Calibration: the raw R of a reference portfolio (r_mid) maps to 50 and
    #     the S-curve spreads scores around it over the full 0-100 range.
    R = calibrate(R, p.r_mid, p.r_k)

    # ── STAGE 2: Personalized concern ───────────────────────────────

    # (7) Comfort level ρ(t) = a + b·t
    rho = p.a + p.b * t

    # Normalized logistic gap  C ∈ [0, 100]
    sig_num = _sig(p.k * (R - rho))
    sig_denom_lo = _sig(-p.k * rho)
    sig_denom_hi = _sig(p.k * (1.0 - rho))
    denom = sig_denom_hi - sig_denom_lo
    C = 100.0 * (sig_num - sig_denom_lo) / denom if denom != 0 else 50.0

    # ── Aggregate confidence ────────────────────────────────────────
    w_total = p.w_S + p.w_G
    agg_conf = (p.w_S * (1.0 - w3) * c1 + p.w_S * w3 * c3 + p.w_G * c2) / w_total

    return {
        "objective": round(100.0 * R, 2),
        "personalized": round(C, 2),
        "confidence": round(agg_conf, 2),
    }


# ── Application Integration ─────────────────────────────────────────

def _is_agent_output(obj: Any) -> bool:
    return hasattr(obj, "claims") and hasattr(obj, "agent")


def _country_r(c_info: Any) -> float | None:
    """Country risk from any supported shape, normalized to [0, 1] (0-100 inputs are rescaled)."""
    r_val = None
    if _is_agent_output(c_info):
        from tools import risk_math as _rm  # lazy â€“ avoids circular import
        r_val = _rm.score_geopolitical(c_info)["R"]
    elif isinstance(c_info, (int, float)):
        r_val = float(c_info)
    elif isinstance(c_info, dict):
        for key in ("R", "R_c", "score"):
            if c_info.get(key) is not None:
                r_val = c_info[key]
                break
    elif hasattr(c_info, "R_c"):
        r_val = getattr(c_info, "R_c")
    if r_val is None:
        return None
    r_val = float(r_val)
    if math.isnan(r_val):
        return None
    return _clamp(r_val / 100.0 if r_val > 1.0 else r_val)


def _firm_score(rep: Any) -> float | None:
    """Firm score on the 0-5 scale from any supported shape."""
    f = None
    if _is_agent_output(rep):
        from tools import risk_math as _rm
        f = _rm.score_filings(rep)["firm_score"]
    elif isinstance(rep, dict):
        f = rep.get("firm_score")
    elif hasattr(rep, "firm_score"):
        f = getattr(rep, "firm_score")
    if f is None or math.isnan(float(f)):
        return None
    return float(f)


def extract_agent_inputs(

    weights: dict[str, float] | None = None,
    profile: Any = None,
    assets: dict[str, Any] | None = None,
    countries: dict[str, Any] | None = None,
    scenarios: list[Any] | None = None,
    p: Params = Params(),
) -> tuple[float, float, float, float, tuple[float, float, float]]:
    """Extract (A1, A2, A3, A4) and confidences from application data structures.

    A1: National Risk (from country sovereign/macroeconomic reports)
    A2: Geopolitical Risk (from scenario impacts and geopolitical indicators)
    A3: Country Index Risk (from asset disclosures and firm scores)
    A4: User Risk Tolerance (from investor profile)

    Returns
    -------
    (a1, a2, a3, tolerance, (c1, c2, c3)) all in [0, 1].
    """
    weights = weights or {}
    assets = assets or {}
    countries = countries or {}
    scenarios = scenarios or []

    # 0. Clean and normalize portfolio weights
    norm_weights: dict[str, float] = {}
    total_w = 0.0
    for t, w in sorted(weights.items()):
        if w is not None and not math.isnan(w) and w > 0:
            norm_weights[t] = float(w)
            total_w += float(w)

    if total_w > 0:
        norm_weights = {t: w / total_w for t, w in norm_weights.items()}

    # Compute portfolio country exposure: X_c = sum_i w_i * w_ic
    X: dict[str, float] = {}
    for t, w in norm_weights.items():
        asset_data = assets.get(t, {})
        # AgentOutput objects don't have .get(); extract country_weights safely
        if hasattr(asset_data, "claims") and hasattr(asset_data, "agent"):
            # AgentOutput: no country_weights field; skip exposure calculation here
            # (the firm score is still used for A3)
            cw: dict = {}
        elif isinstance(asset_data, dict):
            cw = asset_data.get("country_weights", {})
        elif hasattr(asset_data, "country_weights"):
            cw = asset_data.country_weights or {}
        else:
            cw = {}
        for c, share in cw.items():
            if share is not None and not math.isnan(share):
                X[c] = X.get(c, 0.0) + w * float(share)

    # 1. A1: National Risk â€” exposure-weighted power mean of country R, calibrated
    #    A1 = g(M_p(R_c ; X_c), m1)
    a1 = p.mu
    c1 = 0.0
    if countries:
        pairs: list[tuple[float, float]] = []
        covered_x = 0.0
        for c, c_info in sorted(countries.items()):
            r_val = _country_r(c_info)
            if r_val is None:
                continue
            # With exposure: weight by X_c (countries the portfolio doesn't touch are ignored).
            # Without exposure data: every reported country counts equally.
            x = X.get(c, 0.0) if X else 1.0
            if x > 0:
                pairs.append((r_val, x))
                covered_x += x
        m = power_mean(pairs, p.agg_p)
        if m is not None:
            a1 = calibrate(m, p.m1, p.k1)
            c1 = min(1.0, covered_x) if X else 0.90
        elif X:
            c1 = 0.5

    # 2. A2: Geopolitical scenario risk â€” saturating expected shock
    #    EL = Î£_s likelihood_s Â· (impact_s / 5) Â· exposure_s ,  A2 = 1 âˆ’ exp(âˆ’EL / EL_ref)
    #    Scenarios are distinct risks, so their shocks add up (a mean would let
    #    benign scenarios dilute dangerous ones).
    a2 = p.mu
    c2 = 0.0
    all_scenarios = []
    for item in scenarios:
        if isinstance(item, dict) and "scenarios" in item:
            all_scenarios.extend(item["scenarios"])
        elif isinstance(item, dict):
            all_scenarios.append(item)
        elif hasattr(item, "scenarios"):
            all_scenarios.extend(getattr(item, "scenarios"))

    if all_scenarios:
        el = 0.0
        for s in all_scenarios:
            if not isinstance(s, dict):
                s = getattr(s, "model_dump", lambda: vars(s))()
            imp = _clamp(float(s.get("impact", 3.0)) / 5.0)
            lik = _clamp(float(s.get("likelihood", 0.5)))
            # Prefer exposure computed from THIS portfolio's country mix
            # (Σ_c X_c · intensity_c); a precomputed "exposure" field may
            # belong to other weights (e.g. a what-if trade), so it is a fallback.
            s_countries = s.get("countries") or {}
            exp = None
            if X and s_countries:
                exp = sum(X.get(c, 0.0) * float(intensity) for c, intensity in s_countries.items())
            if exp is None:
                exp = s.get("exposure")
            exp = _clamp(float(exp)) if exp is not None else p.default_exposure
            el += lik * imp * exp
        a2 = 1.0 - math.exp(-el / p.el_ref) if p.el_ref > 0 else 0.0
        c2 = 0.85
    elif countries and c1 > 0:
        # No scenarios: country risk is the best available geopolitical proxy.
        a2 = a1
        c2 = 0.6 * c1

    # 3. A3: Firm exposure risk â€” holding-weighted power mean of firm_score/5, calibrated
    #    A3 = g(M_p(firm_i / 5 ; w_i), m3)
    a3 = p.mu
    c3 = 0.0
    if assets:
        pairs = []
        covered_firm_w = 0.0
        use_weights = bool(norm_weights)
        tickers = sorted(norm_weights) if use_weights else sorted(assets)
        for t in tickers:
            f_score = _firm_score(assets.get(t, {}))
            if f_score is None:
                continue
            w = norm_weights[t] if use_weights else 1.0
            pairs.append((_clamp(f_score / 5.0), w))
            covered_firm_w += w
        m = power_mean(pairs, p.agg_p)
        if m is not None:
            a3 = calibrate(m, p.m3, p.k3)
            c3 = min(1.0, covered_firm_w) if use_weights else 0.80
        elif use_weights:
            c3 = 0.5

    # 4. A4: User Risk Tolerance
    tol_raw = None
    if isinstance(profile, dict):
        tol_raw = profile.get("risk_tolerance")
    elif profile is not None:
        tol_raw = getattr(profile, "risk_tolerance", profile)
    tolerance = parse_tolerance(tol_raw, default=0.50)

    # Final safe clamping
    return (
        _clamp(a1),
        _clamp(a2),
        _clamp(a3),
        _clamp(tolerance),
        (_clamp(c1), _clamp(c2), _clamp(c3)),
    )


def calculate_portfolio_risk(
    weights: dict[str, float] | None = None,
    profile: Any = None,
    assets: dict[str, Any] | None = None,
    countries: dict[str, Any] | None = None,
    scenarios: list[Any] | None = None,
    *,
    a1: float | None = None,
    a2: float | None = None,
    a3: float | None = None,
    tolerance: float | str | None = None,
    conf: tuple[float, float, float] | None = None,
    p: Params = Params(),
) -> dict[str, Any]:
    """Calculate the final portfolio risk scores using the deterministic 2-stage formula.

    Either extracts scores automatically from agent outputs / portfolio data
    or uses directly provided agent scores.

    Returns
    -------
    dict:
        score         – Final personalized portfolio risk score (0-100)
        objective     – Objective portfolio risk score (0-100)
        personalized  – Personalized concern score (0-100)
        confidence    – Aggregate confidence (0-1)
        components    – Breakdown of inputs (0-100 scale)
        confidences   – Confidence per agent
    """
    # 1. Extract inputs if not explicitly supplied
    if a1 is None or a2 is None or a3 is None or tolerance is None or conf is None:
        ea1, ea2, ea3, etol, econf = extract_agent_inputs(
            weights=weights,
            profile=profile,
            assets=assets,
            countries=countries,
            scenarios=scenarios,
            p=p,
        )
        a1 = ea1 if a1 is None else _clamp(a1)
        a2 = ea2 if a2 is None else _clamp(a2)
        a3 = ea3 if a3 is None else _clamp(a3)
        tolerance = etol if tolerance is None else tolerance
        conf = econf if conf is None else conf

    # 2. Evaluate deterministic scoring formula
    scores = portfolio_scores(
        a1=a1,
        a2=a2,
        a3=a3,
        tolerance=tolerance,
        conf=conf,
        p=p,
    )

    t_numeric = parse_tolerance(tolerance, default=p.mu)

    return {
        "score": scores["personalized"],
        "objective": scores["objective"],
        "personalized": scores["personalized"],
        "confidence": scores["confidence"],
        "components": {
            "a1_national_risk": round(a1 * 100.0, 2),
            "a2_geopolitical_risk": round(a2 * 100.0, 2),
            "a3_country_index_risk": round(a3 * 100.0, 2),
            "a4_tolerance": round(t_numeric * 100.0, 2),
        },
        "confidences": {
            "c1": round(conf[0], 2),
            "c2": round(conf[1], 2),
            "c3": round(conf[2], 2),
        },
    }
