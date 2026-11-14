from tools.source_discovery import find_candidate_sources, assess_source
from storage.s3_service import load_json, save_json

def discover_sources(country: str, limit: int = 10) -> dict:
    existing = load_json("trusted_sources.json", default=[])
    candidates = find_candidate_sources(country, limit=limit)

    known_urls = {item.get("url", "").rstrip("/").lower() for item in existing}
    results = []
    for candidate in candidates:
        url = candidate.get("url", "").rstrip("/")
        if not url or url.lower() in known_urls:
            continue
        evaluated = assess_source(candidate, country)
        results.append(evaluated)

    # Do not automatically mark discovered links as trusted.
    output = {
        "country": country,
        "existing_source_count": len(existing),
        "candidates": results,
        "note": (
            "These are candidate sources, not verified endorsements. "
            "Check publisher identity, domain ownership, publication date, "
            "methodology, and whether the page is actually relevant before approval."
        )
    }
    save_json(f"source-discovery/{country.lower().replace(' ', '-')}.json", output)
    return output
