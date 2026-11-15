"""Country macro and banking indicators from the World Bank API (free, no key, annual, latest available year)."""
from functools import lru_cache
from typing import Optional

from tools.http_utils import get_json

BASE = "https://api.worldbank.org/v2"
COUNTRY_INDICATORS = {
    "gdp_growth_pct": "NY.GDP.MKTP.KD.ZG",
    "inflation_pct": "FP.CPI.TOTL.ZG",
    "unemployment_pct": "SL.UEM.TOTL.ZS",
    "public_debt_pct_gdp": "GC.DOD.TOTL.GD.ZS",
}
BANK_INDICATORS = {
    "nonperforming_loans_pct": "FB.AST.NPER.ZS",
    "capital_adequacy_pct": "FB.BNK.CAPA.ZS",
}
SOURCE_URL = "https://data.worldbank.org/indicator/"


@lru_cache(maxsize=1)
def _countries() -> dict[str, str]:
    """Lower-cased name / ISO2 / ISO3 -> ISO3, for real countries only (aggregates are excluded)."""
    payload = get_json(f"{BASE}/country", params={"format": "json", "per_page": 400})
    names: dict[str, str] = {}
    for item in payload[1]:
        if item["region"]["id"] == "NA":  # aggregates such as "World" or "Euro area"
            continue
        iso3 = item["id"]
        for key in (item["name"], item["iso2Code"], iso3):
            names[key.lower()] = iso3
    return names


def resolve_country(country: str) -> Optional[str]:
    return _countries().get(country.strip().lower())


@lru_cache(maxsize=256)
def fetch_indicators(iso3: str, indicators: tuple[tuple[str, str], ...]) -> dict[str, dict]:
    """{field: {"value", "year", "indicator", "url"}} for indicators with at least one observation."""
    out: dict[str, dict] = {}
    for field, code in indicators:
        payload = get_json(f"{BASE}/country/{iso3}/indicator/{code}", params={"format": "json", "mrnev": 1})
        rows = payload[1] if len(payload) > 1 and payload[1] else []
        row = next((r for r in rows if r.get("value") is not None), None)
        if row:
            out[field] = {"value": float(row["value"]), "year": int(row["date"]), "indicator": code,
                          "url": SOURCE_URL + code}
    return out


def country_data(country: str) -> Optional[dict]:
    """Macro indicators in the shape expected by tools.risk_calculator; None if the country is unknown."""
    iso3 = resolve_country(country)
    if iso3 is None:
        return None
    found = fetch_indicators(iso3, tuple(COUNTRY_INDICATORS.items()))
    return {"country": country, "iso3": iso3, **{k: v["value"] for k, v in found.items()},
            "data_years": {k: v["year"] for k, v in found.items()},
            "data_source": "WORLD_BANK", "is_demo": False}


def bank_data(country: str, bank: Optional[str] = None) -> Optional[dict]:
    """Banking-sector indicators (liquidity coverage has no World Bank series and stays absent)."""
    iso3 = resolve_country(country)
    if iso3 is None:
        return None
    found = fetch_indicators(iso3, tuple(BANK_INDICATORS.items()))
    return {"country": country, "bank": bank or "Domestic Banking Sector", "iso3": iso3,
            **{k: v["value"] for k, v in found.items()},
            "data_years": {k: v["year"] for k, v in found.items()},
            "data_source": "WORLD_BANK", "is_demo": False}
