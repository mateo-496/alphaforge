"""Sample and showcase portfolios mapped onto the form's fields."""
from functools import lru_cache

from web import universe as U

RISK = {"low": 1, "low-moderate": 2, "moderate": 3, "moderate-high": 4, "high": 5}
OBJECTIVE = {"capital preservation": 1, "preserve real value": 1, "income": 2, "inflation hedge": 3,
             "balanced": 3, "growth": 4}
THEMES = {"fossil_fuels": "theme:Fossil fuels", "weapons": "theme:Weapons and defence",
          "sanctioned_jurisdictions": "theme:Sanctioned jurisdictions"}
SAMPLE_IDS = {"qc-retiree-income", "global-tech-growth", "esg-endowment"}


def _profile(p: dict) -> dict:
    pr = p["profile"]
    excl = pr.get("exclusions", [])
    return {"age": None, "horizon_years": min(pr.get("horizon_years", 10), 30),
            "risk_level": RISK.get(pr.get("risk_tolerance"), 3),
            "objective_level": OBJECTIVE.get(pr.get("objective"), 3),
            "experience": "advanced" if "institutional" in pr.get("persona", "") or "manager" in pr.get("persona", "").lower() else "intermediate",
            "esg_importance": "high" if excl else "none",
            "crypto_max": 0.05 if any(h["ticker"] == "BTC" for h in p["holdings"]) else 0.0,
            "max_single_weight": pr.get("max_single_holding", 0.25),
            "exclusions": [THEMES.get(e, f"text:{e}") for e in excl],
            "avoid_countries": [c for c, cap in pr.get("max_country", {}).items() if cap == 0],
            "interests": ["Dividend income"] if pr.get("objective") == "income" else [],
            "notes": f"{pr.get('persona', '')}. {p.get('geo_angle', '')}".strip(),
            "base_currency": pr.get("base_currency", "CAD")}


@lru_cache
def samples() -> dict[str, dict]:
    out = {}
    for group, key in (("showcase", "showcase_portfolios"), ("sample", "portfolios")):
        for p in U.load()[key]:
            if group == "sample" and p["id"] not in SAMPLE_IDS:
                continue
            rows = []
            for h in p["holdings"]:
                t = U.normalise_ticker(h["ticker"]) or h["ticker"]
                rows.append((t, round(h["weight"] * 100, 2)))
            out[p["id"]] = {"label": p["label"], "persona": p["profile"].get("persona", ""),
                            "profile": _profile(p), "portfolio": rows, "group": group}
    return out