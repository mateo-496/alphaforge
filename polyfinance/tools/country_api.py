from config import COUNTRY_API_URL, COUNTRY_API_KEY, USE_DEMO_DATA
from tools.http_utils import get_json

def get_country_data(country: str) -> dict:
    if COUNTRY_API_URL:
        # Adapt params/response parsing to the API documentation you receive.
        raw = get_json(COUNTRY_API_URL, COUNTRY_API_KEY, params={"country": country})
        if isinstance(raw, list):
            raw = raw[0] if raw else {}
        return normalize_country_data(raw, country)

    if not USE_DEMO_DATA:
        raise RuntimeError("COUNTRY_API_URL is not configured and demo mode is disabled.")

    # Clearly labelled synthetic demo values; replace with real API data.
    return {
        "country": country,
        "gdp_growth_pct": 2.0,
        "inflation_pct": 3.0,
        "unemployment_pct": 6.0,
        "public_debt_pct_gdp": 65.0,
        "data_source": "SYNTHETIC_DEMO_DATA",
        "is_demo": True
    }

def normalize_country_data(raw: dict, country: str) -> dict:
    # Update these aliases to match the actual country API response.
    aliases = {
        "gdp_growth_pct": ["gdp_growth_pct", "gdp_growth", "growth"],
        "inflation_pct": ["inflation_pct", "inflation"],
        "unemployment_pct": ["unemployment_pct", "unemployment"],
        "public_debt_pct_gdp": ["public_debt_pct_gdp", "debt_to_gdp", "public_debt"]
    }
    normalized = {"country": country, "data_source": "COUNTRY_API", "is_demo": False}
    for target, keys in aliases.items():
        for key in keys:
            if raw.get(key) is not None:
                try:
                    normalized[target] = float(raw[key])
                except (TypeError, ValueError):
                    pass
                break
    return normalized
