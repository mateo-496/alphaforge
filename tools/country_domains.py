"""Country-code top-level domain (ccTLD) mappings and domain prioritization for AlphaForge."""
import re
from urllib.parse import urlparse

# Predefined comprehensive mapping of country names, aliases, and ISO codes to their official ccTLD
COUNTRY_TO_CCTLD: dict[str, str] = {
    # Americas
    "united states": "us",
    "usa": "us",
    "us": "us",
    "canada": "ca",
    "ca": "ca",
    "mexico": "mx",
    "mx": "mx",
    "brazil": "br",
    "brasil": "br",
    "br": "br",
    "argentina": "ar",
    "ar": "ar",
    "chile": "cl",
    "cl": "cl",
    "colombia": "co",
    "co": "co",
    "peru": "pe",
    "pe": "pe",
    "venezuela": "ve",
    "ve": "ve",
    "ecuador": "ec",
    "ec": "ec",
    "uruguay": "uy",
    "uy": "uy",
    "paraguay": "py",
    "py": "py",
    "panama": "pa",
    "pa": "pa",
    "costa rica": "cr",
    "cr": "cr",

    # Europe & Eurozone
    "europe": "eu",
    "european union": "eu",
    "eurozone": "eu",
    "eu": "eu",
    "united kingdom": "uk",
    "uk": "uk",
    "great britain": "uk",
    "gb": "uk",
    "germany": "de",
    "deutschland": "de",
    "de": "de",
    "france": "fr",
    "fr": "fr",
    "italy": "it",
    "italia": "it",
    "it": "it",
    "spain": "es",
    "espana": "es",
    "es": "es",
    "netherlands": "nl",
    "holland": "nl",
    "nl": "nl",
    "switzerland": "ch",
    "ch": "ch",
    "sweden": "se",
    "se": "se",
    "norway": "no",
    "no": "no",
    "denmark": "dk",
    "dk": "dk",
    "finland": "fi",
    "fi": "fi",
    "poland": "pl",
    "pl": "pl",
    "belgium": "be",
    "be": "be",
    "austria": "at",
    "at": "at",
    "ireland": "ie",
    "ie": "ie",
    "portugal": "pt",
    "pt": "pt",
    "greece": "gr",
    "gr": "gr",
    "czech republic": "cz",
    "czechia": "cz",
    "cz": "cz",
    "hungary": "hu",
    "hu": "hu",
    "romania": "ro",
    "ro": "ro",
    "ukraine": "ua",
    "ua": "ua",
    "russia": "ru",
    "russian federation": "ru",
    "ru": "ru",
    "turkey": "tr",
    "turkiye": "tr",
    "tr": "tr",

    # Asia & Pacific
    "china": "cn",
    "prc": "cn",
    "cn": "cn",
    "japan": "jp",
    "nippon": "jp",
    "jp": "jp",
    "india": "in",
    "in": "in",
    "south korea": "kr",
    "korea": "kr",
    "kr": "kr",
    "australia": "au",
    "au": "au",
    "new zealand": "nz",
    "nz": "nz",
    "singapore": "sg",
    "sg": "sg",
    "hong kong": "hk",
    "hk": "hk",
    "taiwan": "tw",
    "tw": "tw",
    "indonesia": "id",
    "id": "id",
    "malaysia": "my",
    "my": "my",
    "thailand": "th",
    "th": "th",
    "vietnam": "vn",
    "vn": "vn",
    "philippines": "ph",
    "ph": "ph",
    "pakistan": "pk",
    "pk": "pk",
    "bangladesh": "bd",
    "bd": "bd",
    "saudi arabia": "sa",
    "sa": "sa",
    "united arab emirates": "ae",
    "uae": "ae",
    "ae": "ae",
    "israel": "il",
    "il": "il",
    "qatar": "qa",
    "qa": "qa",

    # Africa
    "south africa": "za",
    "za": "za",
    "nigeria": "ng",
    "ng": "ng",
    "egypt": "eg",
    "eg": "eg",
    "kenya": "ke",
    "ke": "ke",
    "morocco": "ma",
    "ma": "ma",
    "ghana": "gh",
    "gh": "gh"
}

# Country specific official domain prefixes and patterns
SPECIFIC_OFFICIAL_PATTERNS: dict[str, list[str]] = {
    "ca": [".gc.ca", ".statcan.gc.ca", ".bankofcanada.ca", ".gov.ca", ".ca"],
    "us": [".gov", ".treasury.gov", ".federalregister.gov", ".fed.us", ".us"],
    "cn": [".gov.cn", ".pbc.gov.cn", ".mof.gov.cn", ".pboc.io", ".cn"],
    "jp": [".go.jp", ".boj.or.jp", ".mof.go.jp", ".jp"],
    "uk": [".gov.uk", ".bankofengland.co.uk", ".co.uk", ".uk"],
    "de": [".bund.de", ".bundesbank.de", ".de"],
    "fr": [".gouv.fr", ".banque-france.fr", ".fr"],
    "it": [".gov.it", ".bancaditalia.it", ".it"],
    "es": [".gob.es", ".bde.es", ".es"],
    "ru": [".gov.ru", ".minfin.gov.ru", ".cbr.ru", ".ru"],
    "br": [".gov.br", ".bcb.gov.br", ".br"],
    "au": [".gov.au", ".rba.gov.au", ".au"],
    "in": [".gov.in", ".rbi.org.in", ".in"],
    "mx": [".gob.mx", ".banxico.org.mx", ".mx"],
    "za": [".gov.za", ".resbank.co.za", ".za"],
    "eu": [".europa.eu", ".ecb.europa.eu", ".eu"]
}

def get_country_domain(country: str) -> str:
    """Determine the official country-code domain (ccTLD) for any country.
    
    Uses comprehensive mapping, handles abbreviations, and provides automatic
    heuristic determination for new/arbitrary country inputs.
    """
    if not country:
        return ""
    
    clean = country.strip().lower()

    # 1. Direct lookup in comprehensive dictionary
    if clean in COUNTRY_TO_CCTLD:
        return COUNTRY_TO_CCTLD[clean]

    # Clean punctuation and multiple spaces
    normalized = re.sub(r"[^a-z0-9 ]+", "", clean)
    if normalized in COUNTRY_TO_CCTLD:
        return COUNTRY_TO_CCTLD[normalized]

    # 2. Check if clean string itself is a 2-letter ISO ccTLD format
    if len(clean) == 2 and clean.isalpha():
        return clean

    # 3. Match known country substrings (e.g. "Republic of Singapore" -> "sg")
    for key, cc in COUNTRY_TO_CCTLD.items():
        if len(key) > 3 and key in clean:
            return cc

    # 4. Fallback heuristic: 2-letter prefix if alphabet characters
    words = clean.split()
    if words:
        first_word = re.sub(r"[^a-z]", "", words[0])
        if len(first_word) >= 2:
            return first_word[:2]

    return "int"

def get_country_official_patterns(country: str) -> list[str]:
    """Return recognized official domain patterns for the target country."""
    cc = get_country_domain(country)
    if not cc:
        return [".gov", ".int"]

    if cc in SPECIFIC_OFFICIAL_PATTERNS:
        return SPECIFIC_OFFICIAL_PATTERNS[cc]

    # Generic institutional patterns for any international country
    return [
        f".gov.{cc}",
        f".gob.{cc}",
        f".gouv.{cc}",
        f".go.{cc}",
        f".govt.{cc}",
        f".org.{cc}",
        f".{cc}"
    ]

def is_country_domain_match(url_or_host: str, country: str) -> bool:
    """Check whether a URL or hostname belongs to the country's official domain or ccTLD."""
    if not url_or_host or not country:
        return False

    host = urlparse(url_or_host).hostname or url_or_host
    host = host.lower().strip()
    cc = get_country_domain(country)

    if not cc:
        return False

    patterns = get_country_official_patterns(country)
    for pat in patterns:
        if host == pat.lstrip(".") or host.endswith(pat):
            return True

    # Check bare ccTLD ending (e.g. host.endswith('.ca'))
    if host.endswith(f".{cc}"):
        return True

    return False

def score_source_priority(
    candidate: dict,
    country: str,
    is_trusted_authority: bool = False
) -> float:
    """Calculate a priority score for candidate source sorting.
    
    Country-specific domain match is a prioritization boost, not an automatic guarantee
    of trust. High score = prioritized higher in discovery and report source lists.
    """
    url = candidate.get("url", "")
    has_country_domain = is_country_domain_match(url, country)
    is_strong_domain = candidate.get("preliminary_domain_signal") == "stronger" or is_trusted_authority

    score = 0.0

    # 1. Base trust quality (dominant factor)
    if is_strong_domain:
        score += 50.0

    # 2. Country-specific domain prioritization (boost)
    if has_country_domain:
        score += 30.0

    # 3. Country mention in title/snippet (relevance boost)
    title = (candidate.get("title") or "").lower()
    snippet = (candidate.get("snippet") or "").lower()
    c_lower = country.lower()
    if c_lower in title:
        score += 15.0
    elif c_lower in snippet:
        score += 8.0

    return score
