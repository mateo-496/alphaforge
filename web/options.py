"""Option lists for the preference dropdowns. Every list also accepts free text in the form."""
import json
from pathlib import Path

GICS_SECTORS = ["Communication Services", "Consumer Discretionary", "Consumer Staples", "Energy", "Financials",
                "Health Care", "Industrials", "Information Technology", "Materials", "Real Estate", "Utilities"]

EXCLUSION_THEMES = ["Fossil fuels", "Coal", "Oil sands", "Weapons and defence", "Controversial weapons",
                    "Nuclear power", "Tobacco", "Alcohol", "Gambling", "Adult entertainment", "Private prisons",
                    "Animal testing", "Crypto assets", "Sanctioned jurisdictions", "State-owned enterprises",
                    "Companies with labour-rights controversies", "Deforestation-linked commodities"]

INTERESTS = ["Artificial intelligence", "Semiconductors", "Cloud and software", "Cybersecurity", "Fintech and payments",
             "E-commerce", "Energy transition", "Electric vehicles and batteries", "Critical minerals", "Gold and precious metals",
             "Oil and gas", "Infrastructure", "Defence and aerospace", "Healthcare and biotech", "Consumer brands",
             "Real estate", "Dividend income", "Bonds and fixed income", "Emerging markets", "Canadian companies",
             "US large caps", "European companies", "Asia-Pacific", "Latin America", "Africa", "Crypto assets",
             "Water and agriculture", "ESG leaders"]

_C = json.loads((Path(__file__).parent / "countries.json").read_text())
NAMES = {k: v["name"] for k, v in _C.items()}
COUNTRIES = sorted(((k, v["name"]) for k, v in _C.items() if k != "Other"), key=lambda c: c[1])


def exclusion_options(universe: dict) -> list[dict]:
    """Grouped options for the exclusions box: value carries its type, e.g. 'sector:Energy'."""
    return ([{"v": f"sector:{s}", "l": s, "g": "Sector"} for s in GICS_SECTORS]
            + [{"v": f"theme:{t}", "l": t, "g": "Theme"} for t in EXCLUSION_THEMES]
            + [{"v": f"ticker:{t}", "l": f"{t} · {a['name']}", "g": "Company"} for t, a in sorted(universe.items())])


def country_options() -> list[dict]:
    return [{"v": k, "l": n, "g": ""} for k, n in COUNTRIES]


def interest_options() -> list[dict]:
    return [{"v": i, "l": i, "g": ""} for i in INTERESTS]
