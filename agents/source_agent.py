import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import TRUSTED_SOURCES_PATH
from output_example import Source
from storage.s3_service import load_json, save_json
from tools.source_discovery import assess_source, find_candidate_sources

DEFAULT_TRUSTED: dict[str, list[dict]] = {
    "general": [
        {
            "name": "World Bank Data",
            "url": "https://data.worldbank.org/",
            "type": "multilateral_development_data",
            "notes": "Official World Bank open data and indicators."
        },
        {
            "name": "World Bank Documents & Reports API",
            "url": "https://documents.worldbank.org/en/publication/documents-reports/api",
            "type": "multilateral_development_data",
            "notes": "Official API for World Bank publications, economic analysis, and country reports."
        },
        {
            "name": "International Monetary Fund",
            "url": "https://www.imf.org/en/Countries",
            "type": "multilateral_financial_institution",
            "notes": "IMF country information and Article IV surveillance reports."
        },
        {
            "name": "IMF Data Support & Knowledge Base",
            "url": "https://datasupport.imf.org/knowledge?id=knowledge_category&sys_kb_id=5ca208d697bc4390d4f0b437f053af9e&category_id=9959b2bc1b6391903dba646fbd4bcb6a",
            "type": "multilateral_financial_institution",
            "notes": "IMF Data Services, API guidelines, and knowledge portal."
        },
        {
            "name": "Bank for International Settlements",
            "url": "https://www.bis.org/",
            "type": "international_financial_institution",
            "notes": "Central bank and international financial system statistics."
        }
    ],
    "united_states": [
        {
            "name": "U.S. Treasury Fiscal Data API",
            "url": "https://fiscaldata.treasury.gov/api-documentation/",
            "type": "sovereign_fiscal_authority",
            "notes": "U.S. Department of the Treasury official fiscal data API documentation."
        },
        {
            "name": "Federal Register API",
            "url": "https://www.federalregister.gov/developers/documentation/api/v1",
            "type": "regulatory_authority",
            "notes": "Official daily journal of the United States Government regulations and notices API."
        }
    ],
    "china": [
        {
            "name": "People's Bank of China API Documentation",
            "url": "https://pboc.io/api.html",
            "type": "central_bank",
            "notes": "PBOC data interface and monetary statistics."
        },
        {
            "name": "People's Bank of China Official Portal",
            "url": "https://www.pbc.gov.cn/english/130437/index.html",
            "type": "central_bank",
            "notes": "Central Bank of China official announcements and financial reports."
        },
        {
            "name": "Ministry of Finance of the People's Republic of China",
            "url": "https://www.mof.gov.cn/en/abus/os/rd/",
            "type": "sovereign_fiscal_authority",
            "notes": "Official fiscal policies, budgets, and research bulletins."
        }
    ],
    "europe": [
        {
            "name": "European Central Bank",
            "url": "https://www.ecb.europa.eu/home/html/index.en.html",
            "type": "central_bank",
            "notes": "Eurozone monetary policy, statistical data warehouse, and financial stability reviews."
        }
    ],
    "japan": [
        {
            "name": "Bank of Japan Statistics & Notices",
            "url": "https://www.boj.or.jp/en/statistics/outline/notice_2026/not260218a.htm",
            "type": "central_bank",
            "notes": "Bank of Japan statistical updates, balance sheets, and monetary notices."
        },
        {
            "name": "Ministry of Finance Japan",
            "url": "https://www.mof.go.jp/english/index.htm",
            "type": "sovereign_fiscal_authority",
            "notes": "Japanese government bonds, fiscal policy, and currency statistics."
        }
    ],
    "canada": [
        {
            "name": "Bank of Canada Valet API",
            "url": "https://www.bankofcanada.ca/valet/docs",
            "type": "central_bank",
            "notes": "Bank of Canada official programmatic data API for exchange rates, interest rates, and financial metrics."
        },
        {
            "name": "Statistics Canada Microdata API",
            "url": "https://www.statcan.gc.ca/en/microdata/api",
            "type": "national_statistical_office",
            "notes": "National accounts, GDP, labor market, and CPI statistical API."
        }
    ],
    "russia": [
        {
            "name": "Ministry of Finance of the Russian Federation",
            "url": "https://minfin.gov.ru/ru/document/",
            "type": "sovereign_fiscal_authority",
            "notes": "State budget documents, sovereign debt reports, and public finance bulletins."
        },
        {
            "name": "Central Bank of the Russian Federation (Bank of Russia)",
            "url": "https://cbr.ru/",
            "type": "central_bank",
            "notes": "Key policy rate, banking sector reviews, and monetary statistics."
        }
    ]
}

def normalize_country_key(country: str) -> str:
    """Normalize input country names/aliases to registry keys."""
    c = country.strip().lower().replace(" ", "_").replace("-", "_")
    mapping = {
        "us": "united_states",
        "usa": "united_states",
        "u.s.": "united_states",
        "u.s.a.": "united_states",
        "united_states_of_america": "united_states",
        "cn": "china",
        "prc": "china",
        "jp": "japan",
        "ca": "canada",
        "ru": "russia",
        "eu": "europe",
        "european_union": "europe",
        "eurozone": "europe",
        "germany": "europe",
        "france": "europe",
        "italy": "europe"
    }
    return mapping.get(c, c)

def load_trusted_registry() -> dict[str, list[dict]]:
    """Load trusted sources registry organized by country and general category."""
    remote = load_json("trusted_sources.json", default=None)
    if remote:
        if isinstance(remote, dict):
            return remote
        elif isinstance(remote, list):
            return {"general": remote}

    if Path(TRUSTED_SOURCES_PATH).exists():
        try:
            with open(TRUSTED_SOURCES_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
                elif isinstance(data, list):
                    return {"general": data}
        except Exception:
            pass
    return DEFAULT_TRUSTED

def get_trusted_sources_for_country(country: str | None = None) -> list[dict]:
    """Retrieve trusted sources prioritizing country-specific sources and general sources."""
    registry = load_trusted_registry()
    if not country:
        # Flatten all
        combined: list[dict] = []
        for cat in registry.values():
            if isinstance(cat, list):
                combined.extend(cat)
        return combined

    country_key = normalize_country_key(country)
    country_sources = registry.get(country_key, [])
    general_sources = registry.get("general", [])

    return list(country_sources) + list(general_sources)

def get_all_trusted_urls() -> set[str]:
    """Return normalized set of all known URLs in the trusted registry."""
    registry = load_trusted_registry()
    urls = set()
    for cat in registry.values():
        if isinstance(cat, list):
            for item in cat:
                url = item.get("url", "").rstrip("/").lower()
                if url:
                    urls.add(url)
    return urls

def discover_sources(country: str, limit: int = 10) -> dict[str, Any]:
    """Discover candidate sources for a country, deduplicated against trusted registry."""
    relevant_trusted = get_trusted_sources_for_country(country)
    all_known_urls = get_all_trusted_urls()

    candidates = find_candidate_sources(country, limit=limit)
    results = []
    for candidate in candidates:
        url = candidate.get("url", "").rstrip("/")
        if not url or url.lower() in all_known_urls:
            continue
        evaluated = assess_source(candidate, country)
        results.append(evaluated)

    output = {
        "country": country,
        "country_key": normalize_country_key(country),
        "existing_source_count": len(relevant_trusted),
        "candidates": results,
        "note": (
            "These are candidate sources, not verified endorsements. "
            "Check publisher identity, domain ownership, publication date, "
            "methodology, and whether the page is actually relevant before approval."
        )
    }
    country_slug = country.lower().replace(" ", "-")
    save_json(f"source-discovery/{country_slug}.json", output)
    return output

def get_country_sources(country: str, limit: int = 5) -> list[Source]:
    """Return validated Source contract instances prioritizing country-specific and general authorities."""
    now_iso = datetime.now(timezone.utc).isoformat()
    relevant_trusted = get_trusted_sources_for_country(country)
    discovery = discover_sources(country, limit=limit)

    sources: list[Source] = []

    # 1. Add authoritative trusted sources (country-specific first, then general)
    for item in relevant_trusted[:4]:
        name = item.get("name", "Institutional Database")
        url = item.get("url", "https://data.worldbank.org/")
        locator = item.get("notes") or "Macroeconomic Indicators & Sovereign Surveillance"
        sources.append(
            Source(
                title=f"{name} ({country})",
                url=url,
                locator=locator[:120],
                retrieved_at=now_iso
            )
        )

    # 2. Add evaluated candidate sources
    for cand in discovery.get("candidates", [])[:limit]:
        title = cand.get("title") or f"{country} Financial Report"
        url = cand.get("url") or "https://www.bis.org/"
        sources.append(
            Source(
                title=title,
                url=url,
                locator="Section: National Risk & Banking Assessment",
                retrieved_at=now_iso
            )
        )

    return sources

class SourceAgent:
    """Agent responsible for source discovery, validation, and attribution."""

    def __init__(self, country: str):
        self.country = country

    def discover(self, limit: int = 10) -> dict[str, Any]:
        return discover_sources(self.country, limit=limit)

    def get_sources(self, limit: int = 5) -> list[Source]:
        return get_country_sources(self.country, limit=limit)

    def get_trusted(self) -> list[dict]:
        return get_trusted_sources_for_country(self.country)
