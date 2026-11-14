from config import BANK_API_URL, BANK_API_KEY, USE_DEMO_DATA
from tools.http_utils import get_json

def get_bank_data(country: str, bank: str | None = None) -> dict:
    if BANK_API_URL:
        # Adapt query parameters and normalization to your bank API's schema.
        raw = get_json(BANK_API_URL, BANK_API_KEY, params={"country": country, "bank": bank or ""})
        if isinstance(raw, list):
            raw = raw[0] if raw else {}
        return normalize_bank_data(raw, country, bank)

    if not USE_DEMO_DATA:
        raise RuntimeError("BANK_API_URL is not configured and demo mode is disabled.")

    return {
        "country": country,
        "bank": bank or "Demo bank",
        "capital_adequacy_pct": 14.0,
        "nonperforming_loans_pct": 4.0,
        "liquidity_coverage_pct": 120.0,
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
        "country": country, "bank": bank or raw.get("bank", "Unknown bank"),
        "data_source": "BANK_API", "is_demo": False
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
