"""The 10 sample portfolios (examples/portfolios.json), mapped onto the form's fields."""
from functools import lru_cache

from core.sample_portfolios import load
from web import universe as U

RISK = {"low": "low", "low-moderate": "low_moderate", "moderate": "moderate", "moderate-high": "high", "high": "high"}
OBJECTIVE = {"growth": "growth", "balanced": "balanced", "income": "balanced", "inflation hedge": "balanced",
             "preserve real value": "preserve", "capital preservation": "preserve"}


def _profile(p: dict) -> dict:
    pr = p["profile"]
    excl = pr.get("exclusions", [])
    return {"age": None, "horizon_years": pr.get("horizon_years", 10),
            "risk_tolerance": RISK.get(pr.get("risk_tolerance"), "moderate"),
            "objective": OBJECTIVE.get(pr.get("objective"), "balanced"),
            "experience": "advanced" if "institutional" in pr.get("persona", "") or "manager" in pr.get("persona", "").lower() else "intermediate",
            "esg_importance": "high" if excl else "none", "avoid_controversies": bool(excl),
            "crypto_max": 0.05 if any(h["ticker"] == "BTC" for h in p["holdings"]) else 0.0,
            "max_single_weight": pr.get("max_single_holding", 0.25),
            "excluded_sectors": ["Energy"] if "fossil_fuels" in excl else [],
            "excluded_tickers": [], "avoid_countries": [c for c, cap in pr.get("max_country", {}).items() if cap == 0],
            "interests": ["dividends"] if pr.get("objective") == "income" else [],
            "notes": f"{pr.get('persona', '')}. {p.get('geo_angle', '')}".strip(),
            "base_currency": pr.get("base_currency", "CAD")}


@lru_cache
def samples() -> dict[str, dict]:
    out = {}
    for p in load()["portfolios"]:
        rows = []
        for h in p["holdings"]:
            t = U.normalise_ticker(h["ticker"]) or h["ticker"]
            rows.append((t, round(h["weight"] * 100, 2)))
        out[p["id"]] = {"label": p["label"], "persona": p["profile"].get("persona", ""),
                        "profile": _profile(p), "portfolio": rows}
    return out
