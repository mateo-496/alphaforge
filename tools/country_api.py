from config import COUNTRY_API_URL, COUNTRY_API_KEY, USE_DEMO_DATA
import os

from tools import worldbank
from tools.http_utils import get_json

COUNTRY_DEMO_PROFILES = {
    "canada": {
        "gdp_growth_pct": 1.5,
        "inflation_pct": 2.7,
        "unemployment_pct": 6.4,
        "public_debt_pct_gdp": 69.2,
    },
    "united states": {
        "gdp_growth_pct": 2.8,
        "inflation_pct": 2.9,
        "unemployment_pct": 4.1,
        "public_debt_pct_gdp": 122.3,
    },
    "us": {
        "gdp_growth_pct": 2.8,
        "inflation_pct": 2.9,
        "unemployment_pct": 4.1,
        "public_debt_pct_gdp": 122.3,
    },
    "germany": {
        "gdp_growth_pct": 0.2,
        "inflation_pct": 2.4,
        "unemployment_pct": 5.8,
        "public_debt_pct_gdp": 63.6,
    },
    "china": {
        "gdp_growth_pct": 4.8,
        "inflation_pct": 0.5,
        "unemployment_pct": 5.1,
        "public_debt_pct_gdp": 83.6,
    },
    "brazil": {
        "gdp_growth_pct": 2.9,
        "inflation_pct": 4.2,
        "unemployment_pct": 7.5,
        "public_debt_pct_gdp": 77.8,
    },
    "japan": {
        "gdp_growth_pct": 0.7,
        "inflation_pct": 2.8,
        "unemployment_pct": 2.6,
        "public_debt_pct_gdp": 255.2,
    },
    "united kingdom": {
        "gdp_growth_pct": 1.1,
        "inflation_pct": 3.2,
        "unemployment_pct": 4.3,
        "public_debt_pct_gdp": 98.5,
    },
    "uk": {
        "gdp_growth_pct": 1.1,
        "inflation_pct": 3.2,
        "unemployment_pct": 4.3,
        "public_debt_pct_gdp": 98.5,
    }
}

def get_country_data(country: str) -> dict:
    if COUNTRY_API_URL:
        raw = get_json(COUNTRY_API_URL, COUNTRY_API_KEY, params={"country": country})
        if isinstance(raw, list):
            raw = raw[0] if raw else {}
        return normalize_country_data(raw, country)

    if os.environ.get("USE_WORLD_BANK", "1") == "1":
        try:
            data = worldbank.country_data(country)
        except Exception:
            data = None
        if data and any(k in data for k in worldbank.COUNTRY_INDICATORS):
            return data

    if not USE_DEMO_DATA:
        raise RuntimeError("No country data source is available and demo mode is disabled.")

    profile = COUNTRY_DEMO_PROFILES.get(country.strip().lower(), {
        "gdp_growth_pct": 2.0,
        "inflation_pct": 3.0,
        "unemployment_pct": 6.0,
        "public_debt_pct_gdp": 65.0,
    })

    return {
        "country": country,
        **profile,
        "data_source": "SYNTHETIC_DEMO_DATA",
        "is_demo": True
    }

def normalize_country_data(raw: dict, country: str) -> dict:
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
