"""Deterministic scoring. The LLM explains these numbers; it never invents them."""
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
#   Country hazard  g_c  = percentile of GPR_c among its own past months     (Caldara-Iacoviello GPR, 0-1)
#                          countries without GPR coverage use the global GPR, labelled
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
