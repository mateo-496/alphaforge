from urllib.parse import urlparse
from config import SEARCH_API_URL, SEARCH_API_KEY, USE_DEMO_DATA
from tools.http_utils import get_json

def find_candidate_sources(country: str, limit: int = 10) -> list[dict]:
    """Find candidate sources from search API or trusted demo providers."""
    if SEARCH_API_URL:
        raw = get_json(
            SEARCH_API_URL, SEARCH_API_KEY,
            params={"q": f"official economic financial stability reports {country}", "limit": limit}
        )
        if isinstance(raw, dict):
            raw = raw.get("results", raw.get("items", []))
        return raw[:limit]

    if not USE_DEMO_DATA:
        raise RuntimeError("SEARCH_API_URL is not configured and demo mode is disabled.")

    country_clean = country.strip().lower().replace(" ", "")
    return [
        {
            "title": f"Central Bank & Monetary Authority of {country}",
            "url": f"https://www.bankof{country_clean}.org/en/financial-stability",
            "snippet": f"Financial stability reports and monetary policy data for {country}."
        },
        {
            "title": f"Ministry of Finance & Treasury of {country}",
            "url": f"https://www.treasury.{country_clean}.gov/reports",
            "snippet": f"Official fiscal accounts, sovereign debt, and public budget reports for {country}."
        },
        {
            "title": f"National Statistics Office for {country}",
            "url": f"https://data.{country_clean}.gov/macroeconomics",
            "snippet": f"National accounts, inflation, unemployment, and gross domestic product data for {country}."
        },
        {
            "title": f"Central bank publications for {country}",
            "url": "https://www.bis.org/",
            "snippet": f"Bank for International Settlements publications and statistics for {country}."
        },
        {
            "title": f"Country economic data for {country}",
            "url": "https://data.worldbank.org/",
            "snippet": f"World Bank open data and country indicators for {country}."
        },
        {
            "title": f"Country reports for {country}",
            "url": "https://www.imf.org/en/Countries",
            "snippet": f"IMF country information and Article IV surveillance reports for {country}."
        }
    ][:limit]

def assess_source(candidate: dict, country: str) -> dict:
    """Assess a candidate source using domain heuristics."""
    url = candidate.get("url", "")
    host = urlparse(url).hostname or ""
    official_domains = (
        ".gov", ".gov.uk", ".gc.ca", ".europa.eu", ".int",
        ".gov.cn", ".go.jp", ".gov.ru", ".statcan.gc.ca", ".bankofcanada.ca"
    )
    known_institutions = (
        "worldbank.org", "imf.org", "bis.org", "oecd.org", "un.org",
        "ecb.europa.eu", "treasury.gov", "federalregister.gov",
        "pbc.gov.cn", "mof.gov.cn", "boj.or.jp", "mof.go.jp",
        "minfin.gov.ru", "cbr.ru", "pboc.io"
    )
    is_known = host.endswith(official_domains) or any(
        host == domain or host.endswith("." + domain) for domain in known_institutions
    )
    return {
        "country": country,
        "title": candidate.get("title", ""),
        "url": url,
        "domain": host,
        "snippet": candidate.get("snippet", ""),
        "preliminary_domain_signal": "stronger" if is_known else "unverified",
        "review_required": True
    }
