"""World Bank open data (no key): annual macro and banking indicators per country, point in time, cached 7 days.

A value for year Y is only used for analysis dates in Y+1 or later (annual data is published after the year ends)."""
from typing import Optional

import httpx

from core.storage import cached

BASE = "https://api.worldbank.org/v2"
INDICATORS = {   # field -> (World Bank code, label)
    "gdp_growth_pct": ("NY.GDP.MKTP.KD.ZG", "GDP growth, %"),
    "inflation_pct": ("FP.CPI.TOTL.ZG", "Inflation, consumer prices, %"),
    "unemployment_pct": ("SL.UEM.TOTL.ZS", "Unemployment, % of labour force"),
    "public_debt_pct_gdp": ("GC.DOD.TOTL.GD.ZS", "Central government debt, % of GDP"),
    "nonperforming_loans_pct": ("FB.AST.NPER.ZS", "Bank non-performing loans, % of gross loans"),
    "capital_adequacy_pct": ("FB.BNK.CAPA.ZS", "Bank capital to assets, %"),
}
COUNTRY_FIELDS = ("gdp_growth_pct", "inflation_pct", "unemployment_pct", "public_debt_pct_gdp")
BANK_FIELDS = ("nonperforming_loans_pct", "capital_adequacy_pct")
PAGE = "https://data.worldbank.org/indicator/{code}"
WEEK_H = 24 * 7


def _get(path: str, **params) -> list:
    """GET with a few retries: the API throttles bursts (HTTP 429/5xx) and times out under load."""
    import time
    for attempt in range(4):
        try:
            r = httpx.get(f"{BASE}/{path}", params={"format": "json", **params}, timeout=60, follow_redirects=True)
            if r.status_code in (429, 500, 502, 503, 504) and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            return r.json()
        except (httpx.TimeoutException, httpx.TransportError):
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("unreachable")


def _all(code: str) -> dict[str, list[tuple[int, float]]]:
    """One indicator for every country in a single request: {iso3: [(year, value), ...] newest first}."""
    def fetch():
        payload = _get(f"country/all/indicator/{code}", date="2000:2030", per_page=20000)
        out: dict[str, list] = {}
        for r in (payload[1] if len(payload) > 1 and payload[1] else []):
            if r.get("value") is not None and r.get("countryiso3code"):
                out.setdefault(r["countryiso3code"], []).append((int(r["date"]), float(r["value"])))
        return {k: sorted(v, reverse=True) for k, v in out.items()}
    return cached("worldbank-all", {"code": code}, fetch, hours=WEEK_H)


def _countries() -> dict[str, dict]:
    """ISO3 -> {"name", "iso2"} for real countries (aggregates such as 'World' left out)."""
    def fetch():
        rows = _get("country", per_page=400)[1]
        return {c["id"]: {"name": c["name"], "iso2": c["iso2Code"]} for c in rows if c["region"]["id"] != "NA"}
    return cached("worldbank-countries", {}, fetch, hours=WEEK_H)


def resolve_country(country: str) -> Optional[str]:
    """Name, ISO2 or ISO3 -> ISO3 (None if the World Bank does not list it, e.g. Taiwan)."""
    key = country.strip().lower()
    for iso3, c in _countries().items():
        if key in (iso3.lower(), c["iso2"].lower(), c["name"].lower()):
            return iso3
    return None


def indicators(iso3: str, as_of: str) -> dict[str, dict]:
    """{field: {"value", "year", "code", "label", "url"}} — latest value published by `as_of`. {} if not covered."""
    c = _countries().get(iso3)
    if not c:
        return {}
    last_year = int(as_of[:4]) - 1
    out = {}
    for field, (code, label) in INDICATORS.items():   # 6 requests in all, shared by every country (cached)
        row = next(((y, v) for y, v in _all(code).get(iso3, []) if y <= last_year), None)
        if row:
            out[field] = {"value": round(row[1], 2), "year": row[0], "code": code, "label": label,
                          "url": PAGE.format(code=code)}
    return out


def gdp_weights(as_of: str, top: int = 60) -> dict[str, float]:
    """Share of world GDP (current USD) of the `top` largest economies, last year published before as_of."""
    year = int(as_of[:4]) - 1

    def fetch():
        rows = _get("country/all/indicator/NY.GDP.MKTP.CD", date=f"{year - 2}:{year}", per_page=2000)
        return rows[1] if len(rows) > 1 and rows[1] else []
    rows = cached("worldbank-gdp", {"year": year}, fetch, hours=WEEK_H)
    real, best = _countries(), {}
    for r in rows:   # newest non-null value per country within the window
        iso3 = r.get("countryiso3code")
        if iso3 in real and r.get("value") is not None and int(r["date"]) <= year and iso3 not in best:
            best[iso3] = float(r["value"])
    big = dict(sorted(best.items(), key=lambda kv: -kv[1])[:top])
    total = sum(big.values())
    return {c: v / total for c, v in big.items()} if total else {}
