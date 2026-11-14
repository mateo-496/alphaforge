def _risk_from_range(value, low, high, reverse=False):
    """Map a numeric indicator to 0..100 risk using a simple linear range."""
    if value is None:
        return None
    value = float(value)
    score = max(0.0, min(100.0, (value - low) / (high - low) * 100.0))
    return 100.0 - score if reverse else score

def calculate_risk(country: dict, bank: dict) -> dict:
    # Illustrative thresholds only. Replace with a defensible methodology and
    # authoritative, comparable data before using this for real decisions.
    components = {
        "inflation": _risk_from_range(country.get("inflation_pct"), 2, 20),
        "unemployment": _risk_from_range(country.get("unemployment_pct"), 3, 25),
        "public_debt": _risk_from_range(country.get("public_debt_pct_gdp"), 30, 150),
        "low_gdp_growth": _risk_from_range(country.get("gdp_growth_pct"), -5, 5, reverse=True),
        "bank_npl": _risk_from_range(bank.get("nonperforming_loans_pct"), 1, 15),
        "weak_capital": _risk_from_range(bank.get("capital_adequacy_pct"), 8, 20, reverse=True),
        "weak_liquidity": _risk_from_range(bank.get("liquidity_coverage_pct"), 80, 160, reverse=True)
    }

    weights = {
        "inflation": 0.15, "unemployment": 0.10, "public_debt": 0.15,
        "low_gdp_growth": 0.10, "bank_npl": 0.20,
        "weak_capital": 0.15, "weak_liquidity": 0.15
    }
    available = [(name, value, weights[name]) for name, value in components.items() if value is not None]
    if not available:
        return {
            "score": None, "label": "Insufficient data", "components": components,
            "coverage_pct": 0, "methodology": "No usable numeric indicators."
        }

    weight_sum = sum(weight for _, _, weight in available)
    score = sum(value * weight for _, value, weight in available) / weight_sum
    coverage = sum(weight for _, _, weight in available) * 100

    if coverage < 50:
        label = "Insufficient data"
    elif score < 25:
        label = "Lower risk"
    elif score < 50:
        label = "Moderate risk"
    elif score < 75:
        label = "Elevated risk"
    else:
        label = "High risk"

    return {
        "score": round(score, 1),
        "label": label,
        "scale": "0 = lower risk; 100 = higher risk",
        "coverage_pct": round(coverage, 1),
        "components": {k: None if v is None else round(v, 1) for k, v in components.items()},
        "weights": weights,
        "methodology": (
            "Illustrative weighted heuristic. Missing indicators are excluded and "
            "remaining weights are renormalized. Thresholds and weights are not validated."
        )
    }
