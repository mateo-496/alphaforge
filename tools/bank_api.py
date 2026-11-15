from config import BANK_API_URL, BANK_API_KEY, USE_DEMO_DATA
import os

from tools import worldbank
from tools.http_utils import get_json

def get_bank_data(country: str, bank: str | None = None) -> dict:
    if BANK_API_URL:
        raw = get_json(BANK_API_URL, BANK_API_KEY, params={"country": country, "bank": bank or ""})
        if isinstance(raw, list):
            raw = raw[0] if raw else {}
        return normalize_bank_data(raw, country, bank)

    if os.environ.get("USE_WORLD_BANK", "1") == "1":
        try:
            data = worldbank.bank_data(country, bank)
        except Exception:
            data = None
        if data and any(k in data for k in worldbank.BANK_INDICATORS):
            return data

    if not USE_DEMO_DATA:
        raise RuntimeError("No banking data source is available and demo mode is disabled.")

    return {
        "country": country,
        "bank": bank or "Domestic Banking Sector",
        "capital_adequacy_pct": 14.2,
        "nonperforming_loans_pct": 3.8,
        "liquidity_coverage_pct": 125.0,
        "data_source": "SYNTHETIC_DEMO_DATA",
        "is_demo": True
    }

def normalize_bank_data(raw: dict, country: str, bank: str | None) -> dict:
    aliases = {
        "capital_adequacy_pct": ["capital_adequacy_pct", "capital_adequacy_ratio"],
        "nonperforming_loans_pct": ["nonperforming_loans_pct", "npl_ratio"],
        "liquidity_coverage_pct": ["liquidity_coverage_pct", "liquidity_coverage_ratio"]
    }
    normalized = {
        "country": country,
        "bank": bank or raw.get("bank", "Domestic Banking Sector"),
        "data_source": "BANK_API",
        "is_demo": False
    }
    for target, keys in aliases.items():
        for key in keys:
            if raw.get(key) is not None:
                try:
                    normalized[target] = float(raw[key])
                except (TypeError, ValueError):
                    pass
                break
    return normalized
