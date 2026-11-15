from urllib.parse import urlparse
from config import SEARCH_API_URL, SEARCH_API_KEY, USE_DEMO_DATA
from tools.country_domains import (
    get_country_domain,
    get_country_official_patterns,
    is_country_domain_match,
    score_source_priority,
)
from tools.http_utils import get_json

def find_candidate_sources(country: str, limit: int = 10) -> list[dict]:
    """Find candidate sources from search API or trusted country-prioritized providers."""
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
    cc = get_country_domain(country)

    candidates = [
        {
            "title": f"Central Bank & Monetary Authority of {country}",
            "url": f"https://www.bankof{country_clean}.{cc}/en/financial-stability" if cc != "us" else "https://www.federalreserve.gov/data.htm",
            "snippet": f"Financial stability reports and monetary policy data for {country} on national domain .{cc}."
        },
        {
            "title": f"Ministry of Finance & Treasury of {country}",
            "url": f"https://www.treasury.gov.{cc}/reports" if cc not in {"us", "ca"} else (
                "https://www.treasury.gov/reports" if cc == "us" else "https://www.fin.gc.ca/reports"
            ),
            "snippet": f"Official fiscal accounts, sovereign debt, and public budget reports for {country}."
        },
        {
            "title": f"National Statistics Office for {country}",
            "url": f"https://data.gov.{cc}/macroeconomics" if cc not in {"us", "ca"} else (
                "https://data.gov/macroeconomics" if cc == "us" else "https://www.statcan.gc.ca/macroeconomics"
            ),
            "snippet": f"National accounts, inflation, unemployment, and gross domestic product data for {country} on .{cc}."
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
    ]

    return candidates[:limit]

def assess_source(candidate: dict, country: str) -> dict:
    """Assess a candidate source using domain heuristics and country-domain prioritization.
    
    Country-specific domain match boosts prioritization, while maintaining strict trust
    validation for official/institutional credentials.
    """
    url = candidate.get("url", "")
    host = (urlparse(url).hostname or "").lower()

    # Base official domains + country-specific official patterns
    standard_official = (
        ".gov", ".gov.uk", ".gc.ca", ".europa.eu", ".int",
        ".gov.cn", ".go.jp", ".gov.ru", ".statcan.gc.ca", ".bankofcanada.ca"
    )
    country_official_patterns = tuple(get_country_official_patterns(country))
    official_domains = standard_official + country_official_patterns

    known_institutions = (
        "worldbank.org", "imf.org", "bis.org", "oecd.org", "un.org",
        "ecb.europa.eu", "treasury.gov", "federalregister.gov",
        "federalreserve.gov", "pbc.gov.cn", "mof.gov.cn", "boj.or.jp",
        "mof.go.jp", "minfin.gov.ru", "cbr.ru", "pboc.io", "statcan.gc.ca",
        "bankofcanada.ca"
    )

    # 1. Quality & Trust validation: Check if host qualifies as an official/institutional domain
    # Note: Only official government subdomains (e.g. .gov.br, .gc.ca, .gov.cn) qualify as is_known,
    # NOT general commercial domains on the ccTLD.
    is_known = any(
        host == domain or host.endswith("." + domain) or host.endswith(domain)
        for domain in known_institutions
    ) or any(
        host.endswith(dom) for dom in official_domains
        if dom.startswith(".gov") or dom.startswith(".gob") or dom.startswith(".gouv") or
           dom.startswith(".go.") or dom.startswith(".govt.") or dom in {".gc.ca", ".europa.eu", ".int"}
    )

    # 2. Country domain match (prioritization factor)
    has_country_match = is_country_domain_match(url, country)

    # 3. Compute combined priority score
    candidate_with_signal = dict(candidate)
    candidate_with_signal["preliminary_domain_signal"] = "stronger" if is_known else "unverified"
    priority = score_source_priority(candidate_with_signal, country, is_trusted_authority=is_known)

    return {
        "country": country,
        "title": candidate.get("title", ""),
        "url": url,
        "domain": host,
        "snippet": candidate.get("snippet", ""),
        "preliminary_domain_signal": "stronger" if is_known else "unverified",
        "country_domain_match": has_country_match,
        "priority_score": priority,
        "review_required": True
    }
