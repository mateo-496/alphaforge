"""Risk score with Cedric's two-stage formula (tools/portfolio_score.portfolio_scores, unchanged).

Its three risk inputs are fed with measured values only (no number written by a language model):
  A1 national risk        exposure-weighted macro fragility M_c   World Bank -> tools/risk_calculator (country risk agent)
  A2 geopolitical risk    exposure-weighted hazard g_c            GPR percentile vs. the country's own history
  A3 company disclosures  weight-weighted filing flags f_i        verified risk channels / 8 (filings agent)
  t  tolerance            profile risk level 1-5 -> portfolio_score.TOLERANCE_MAP
Each input's confidence c_k is the share of revenue (or weight) it actually covers; the formula shrinks a partly
covered input toward the neutral prior 0.5. Unattributed revenue ("Other") counts as not covered.

The same function scores the portfolio (headline), each holding and each country, so every table uses one formula.
"""
from tools import portfolio_score as cedric

RISK_LEVEL_TOLERANCE = {1: "low", 2: "low_moderate", 3: "moderate", 4: "moderate_high", 5: "high"}
P = cedric.Params()


def tolerance(profile: dict) -> float:
    return cedric.parse_tolerance(RISK_LEVEL_TOLERANCE.get(profile.get("risk_level", 3), "moderate"))


def comfort(t: float) -> float:
    """rho(t) = a + b t: the objective risk (0-1) at which the profile's concern starts to rise."""
    return P.a + P.b * t


def _mean(pairs) -> tuple[float | None, float]:
    """(weighted mean over known values, weight covered)."""
    known = [(w, v) for w, v in pairs if v is not None and w > 0]
    cov = sum(w for w, _ in known)
    return (sum(w * v for w, v in known) / cov if cov else None), cov


def score(exposure: dict[str, float], M: dict, g: dict, firms: list[tuple[float, float | None]], t: float,
          firm_share: float = 1.0) -> dict:
    """Cedric's formula for one exposure vector (a holding's w_ic, or the portfolio's X_c) and its firm terms.
    `firms` lists the company holdings only; `firm_share` is their share of the portfolio (funds, bonds, gold and
    crypto have no filing: their company term is not applicable rather than unknown)."""
    total = sum(exposure.values()) or 1.0
    a1, cov1 = _mean((w, M.get(c)) for c, w in exposure.items() if c != "Other")
    a2, cov2 = _mean((w, g.get(c)) for c, w in exposure.items() if c != "Other")
    a3, cov3 = _mean(firms)
    weight = sum(w for w, _ in firms) or 1.0
    conf = (cov1 / total, cov2 / total, cov3 / weight)
    out = cedric.portfolio_scores(a1, a2, a3, t, conf=conf, firm_share=firm_share, p=P)
    return {**out, "A1": a1, "A2": a2, "A3": a3, "conf": [round(c, 3) for c in conf],
            "firm_share": round(firm_share, 3)}


def exposure(weights: dict[str, float], country_weights: dict[str, dict]) -> dict[str, float]:
    """X_c = sum_i w_i w_ic."""
    X: dict[str, float] = {}
    for t, w in weights.items():
        for c, s in country_weights[t].items():
            X[c] = X.get(c, 0.0) + w * s
    return X


def portfolio(weights: dict[str, float], country_weights: dict[str, dict], M: dict, g: dict, f: dict, t: float,
              companies: set[str] | None = None) -> dict:
    """`companies`: tickers that are single companies (None = every holding, the original formula)."""
    w = {k: v for k, v in weights.items() if v > 1e-9}
    co = {k: v for k, v in w.items() if companies is None or k in companies}
    share = sum(co.values()) / (sum(w.values()) or 1.0)
    return score(exposure(w, country_weights), M, g, [(v, f.get(k)) for k, v in co.items()], t, share)


def holding(cw: dict, M: dict, g: dict, f: float | None, t: float, company: bool = True) -> dict:
    return score(cw, M, g, [(1.0, f)] if company else [], t, 1.0 if company else 0.0)


def country(c: str, M: dict, g: dict, t: float) -> dict:
    """A country on its own: no company term."""
    return score({c: 1.0}, M, g, [], t, 0.0)


def companies(tickers, uni: dict) -> set[str]:
    """Single companies (equities). Funds, bonds, gold and crypto have no filing to read."""
    return {t for t in tickers if (uni.get(t) or {}).get("asset_class") == "equity"}


def level(personalized: float) -> str:
    return "low" if personalized < 25 else "moderate" if personalized < 50 else "elevated" if personalized < 75 else "high"


def verdict(objective: float, t: float, conflicts: int) -> dict:
    """clear = objective risk within the profile's comfort level and no broken stated limit."""
    T = round(100 * comfort(t), 1)
    tests = [{"name": f"Objective risk within the profile's comfort level ({T:g})", "ok": objective <= T,
              "value": f"{objective:.1f}"},
             {"name": "No conflict with the profile's stated limits", "ok": conflicts == 0, "value": str(conflicts)}]
    clear = all(x["ok"] for x in tests)
    return {"clear": clear, "status": "clear" if clear else "act", "tolerance": T, "tests": tests}
