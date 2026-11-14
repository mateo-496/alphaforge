from urllib.parse import urlparse
from config import SEARCH_API_URL, SEARCH_API_KEY, USE_DEMO_DATA
from tools.http_utils import get_json

def find_candidate_sources(country: str, limit: int = 10) -> list[dict]:
    if SEARCH_API_URL:
        raw = get_json(
            SEARCH_API_URL, SEARCH_API_KEY,
            params={"q": f"official economic financial stability reports {country}", "limit": limit}
        )
        if isinstance(raw, dict):
            # Adjust this key to match your search provider's response.
            raw = raw.get("results", raw.get("items", []))
        return raw[:limit]

    if not USE_DEMO_DATA:
        raise RuntimeError("SEARCH_API_URL is not configured and demo mode is disabled.")

    return [
        {
            "title": f"Central bank publications for {country}",
            "url": "https://www.bis.org/",
            "snippet": "Bank for International Settlements publications and statistics."
        },
        {
            "title": f"Country economic data for {country}",
            "url": "https://data.worldbank.org/",
            "snippet": "World Bank open data and country indicators."
        },
        {
            "title": f"Country reports for {country}",
            "url": "https://www.imf.org/en/Countries",
            "snippet": "IMF country information and reports."
        }
    ][:limit]

def assess_source(candidate: dict, country: str) -> dict:
    url = candidate.get("url", "")
    host = urlparse(url).hostname or ""
    # This is a transparent preliminary domain heuristic, NOT proof of trust.
    official_domains = (".gov", ".gov.uk", ".gc.ca", ".europa.eu", ".int")
    known_institutions = ("worldbank.org", "imf.org", "bis.org", "oecd.org", "un.org")
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
