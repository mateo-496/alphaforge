"""Prices (Yahoo Finance) and country revenue shares (latest SEC 10-K / 20-F), cached 24 h in core.storage."""
import math
import os
import re
import threading
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import edgar_geo_revenue as geo
from edgar_geo_revenue import _parser as _geo_parser
import httpx
import yfinance as yf

from core.schemas import MarketSeries, Observation, Source
from core.storage import cached

_SEC_LOCK = threading.Lock()
_last_sec_request = 0.0
_TICKER = re.compile(r"^[A-Z0-9][A-Z0-9.\-]*$")


def _validate_ticker(ticker: str) -> None:
    if not _TICKER.fullmatch(ticker):
        raise ValueError("Invalid ticker")


def _source(title: str, url: str, locator: str) -> Source:
    return Source(title=title, url=url, locator=locator,
                  retrieved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))


def _sec_get(url: str) -> httpx.Response:
    global _last_sec_request
    identity = os.environ.get("SEC_IDENTITY", "")
    if not identity or "example.com" in identity.lower() or "@" not in identity:
        raise ValueError("SEC_IDENTITY must contain a real contact email for SEC access")
    with _SEC_LOCK:   # the lock only spaces request starts (SEC asks for <= 10/s); downloads run in parallel
        wait = 0.125 - (time.monotonic() - _last_sec_request)
        if wait > 0:
            time.sleep(wait)
        _last_sec_request = time.monotonic()
    response = httpx.get(url, headers={"User-Agent": identity}, follow_redirects=True,
                         timeout=httpx.Timeout(30, connect=10))
    if response.status_code in (403, 429):
        raise SecBlocked(response.status_code, url)
    response.raise_for_status()
    return response


def get_price_history(ticker: str, as_of: str, lookback_days: int = 90) -> dict[str, Any]:
    """Fetch adjusted daily Yahoo Finance prices, cached (a month for a past window, else 24 hours)."""
    _validate_ticker(ticker)
    end = date.fromisoformat(as_of)
    if end > date.today() or not 1 <= lookback_days <= 3660:
        raise ValueError("Invalid as_of or lookback_days")

    def fetch() -> dict:
        instrument = yf.Ticker(ticker)
        frame = instrument.history(start=(end - timedelta(days=lookback_days)).isoformat(),
                                   end=(end + timedelta(days=1)).isoformat(),
                                   interval="1d", auto_adjust=True, raise_errors=True, timeout=20)
        currency = instrument.history_metadata.get("currency")
        if not currency:
            raise ValueError(f"No price currency returned for {ticker}")
        if "Close" not in frame:
            raise ValueError(f"No closing prices returned for {ticker}")
        observations = [
            Observation(date=index.date(), value=float(value))
            for index, value in frame["Close"].items()
            if not math.isnan(float(value)) and index.date() <= end
        ]
        if any(item.value <= 0 for item in observations):
            raise ValueError(f"Non-positive price returned for {ticker}")
        source = _source("Yahoo Finance adjusted daily close",
                         f"https://finance.yahoo.com/quote/{quote(ticker, safe='.-')}/history/",
                         f"{ticker}, through {end}; adjusted close")
        return MarketSeries(name=ticker, unit=currency, observations=observations,
                            source=source).model_dump(mode="json")

    # A window ending more than a week ago is history: kept a month (adjusted closes only move with later
    # dividends/splits). A recent window is refreshed daily.
    hours = 24 * 30 if end < date.today() - timedelta(days=7) else 24
    return cached("prices", {"ticker": ticker, "as_of": as_of, "days": lookback_days}, fetch, hours=hours)


def _ticker_map() -> dict[str, Any]:
    return cached("sec-tickers", {}, lambda: _sec_get("https://www.sec.gov/files/company_tickers.json").json())


def _oldest_year_first(table, fiscal_year: int) -> bool:
    for row in table.find_all("tr")[:4]:
        years = list(dict.fromkeys(
            int(year) for year in re.findall(r"\b(?:19|20)\d{2}\b", row.get_text(" ", strip=True))
            if 2015 <= int(year) <= fiscal_year
        ))
        if len(years) > 1:
            return years[0] != max(years)
    return False


MAX_R_PAGES = 12
_TITLE_RANK = [re.compile(r"geograph|countr|by\s+region|regional|area", re.I),
               re.compile(r"disaggregat|revenue|net\s+sales|turnover", re.I),
               re.compile(r"segment", re.I)]
_ASSET_TITLE = re.compile(r"long[- ]lived|property|plant|non-?current\s+assets|goodwill|intangible|income\s+tax|deferred", re.I)
_REVENUE_WORD = re.compile(r"revenue|net\s+sales|sales|turnover|income\s+from\s+operations", re.I)


# Filers such as NVIDIA report one "China (including Hong Kong)" line. The parser skips any label naming two
# places, which silently drops the whole China exposure. Hong Kong is a SAR of China: attribute these to CN.
_CHINA_INCLUDING_HK = ("china (including hong kong)", "china (including hong kong and macau)",
                       "china including hong kong", "china, including hong kong", "china and hong kong",
                       "china & hong kong", "mainland china and hong kong", "china (including hong kong sar)",
                       "china, hong kong and macau")
for _label in _CHINA_INCLUDING_HK:
    geo.SEG_MAP.setdefault(_label, "CN")
_geo_parser._SEG_MAP_BY_LEN = sorted(geo.SEG_MAP.items(), key=lambda kv: -len(kv[0]))


class SecBlocked(RuntimeError):
    """EDGAR refused the request (403: missing or generic User-Agent; 429: over 10 requests/s). Not "no filing"."""
    def __init__(self, status: int, url: str):
        super().__init__(f"SEC returned HTTP {status} for {url}")
        self.status = status


ANNUAL = ("10-K", "20-F", "40-F")
STALE_AFTER_DAYS = 550   # a fiscal year ending more than ~18 months before as_of is last year's mix


def annual_filings(ticker: str, as_of: str) -> dict[str, Any]:
    """Annual filings (10-K, 20-F, 40-F) filed on or before as_of, newest first: {status, cik, filings[...]}."""
    _validate_ticker(ticker)
    entry = next((e for e in _ticker_map().values() if e["ticker"].upper() == ticker), None)
    if entry is None:
        return {"status": "no_sec_ticker", "filings": []}
    cik = str(entry["cik_str"]).zfill(10)
    recent = cached("sec-submissions", {"cik": cik},
                    lambda: _sec_get(f"https://data.sec.gov/submissions/CIK{cik}.json").json())["filings"]["recent"]
    rows = [{"form": f, "accession": recent["accessionNumber"][i].replace("-", ""), "filing_date": recent["filingDate"][i],
             "report_date": recent["reportDate"][i] or recent["filingDate"][i]}
            for i, f in enumerate(recent["form"]) if f in ANNUAL and recent["filingDate"][i] <= as_of]
    for r in rows:
        r["base"] = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{r['accession']}"
    return {"status": "ok" if rows else "no_annual_filing", "cik": cik, "filings": rows}


def _xbrl_split(ticker: str, filing: dict) -> dict[str, Any]:
    """Country / region revenue shares from one filing's XBRL report pages (cached for good: a filing never changes)."""
    def fetch() -> dict:
        base, fiscal_year = filing["base"], date.fromisoformat(filing["report_date"]).year
        root = ET.fromstring(_sec_get(f"{base}/FilingSummary.xml").content)
        # Which XBRL report pages may hold the geographic revenue table, best first.
        pages = []
        for report in root.findall(".//Report"):
            title = report.findtext("ShortName", "")
            filename = report.findtext("HtmlFileName", "")
            if not re.fullmatch(r"R\d+\.htm", filename, re.I) or _ASSET_TITLE.search(title):
                continue
            rank = next((i for i, rx in enumerate(_TITLE_RANK) if rx.search(title)), None)
            if rank is not None:
                pages.append((rank, title, filename))
        pages.sort(key=lambda p: p[0])
        candidates, skipped_year_order = [], False
        for rank, title, filename in pages[:MAX_R_PAGES]:
            url = f"{base}/{filename}"
            html = _sec_get(url).text
            table = geo.find_geo_table(html)
            if table is None:
                continue
            if not _REVENUE_WORD.search(table.get_text(" ", strip=True) + " " + title):
                continue
            if _oldest_year_first(table, fiscal_year):   # the parser reads the first numeric column
                skipped_year_order = True
                continue
            result = geo.parse_geo_table(table, html, fiscal_year)
            if not result or not (result.get("segments") or result.get("region_segments")):
                continue
            countries = [(c, float(v) / 100) for c, v in result.get("segments") or [] if re.fullmatch(r"[A-Z]{2}", c)]
            regions = [(f"REGION:{c}", float(v) / 100) for c, v in result.get("region_segments") or []]
            shares = sorted(countries + regions)
            total = sum(v for _, v in shares)
            if not shares or any(not 0 <= v <= 1 for _, v in shares) or total > 1.05:
                continue
            clean = 0.9 <= total <= 1.05
            candidates.append({"clean": clean, "rank": rank, "n": len(shares), "shares": shares, "title": title,
                               "url": url, "fy": result.get("fiscal_year") or fiscal_year})
            if clean and len(countries) >= 2:
                break   # a full company-wide country table: good enough, save requests
        if not candidates:
            return {"status": "unsupported_fiscal_year_order" if skipped_year_order else "no_country_revenue_found",
                    "exposures": [], "fiscal_year": fiscal_year}
        # Several tables can match (by country and by region, segment sub-tables): keep the closest to a full breakdown.
        best = sorted(candidates, key=lambda c: (not c["clean"], c["rank"], -c["n"]))[0]
        source = _source(f"{ticker} SEC {filing['form']} filed {filing['filing_date']}", best["url"],
                         f"{best['title']}; fiscal year {best['fy']}")
        return {"status": "available", "fiscal_year": best["fy"],
                "exposures": [{"country": c, "revenue_share": v, "source": source.model_dump(mode="json")}
                              for c, v in best["shares"]]}
    return cached("sec-xbrl-split", {"accession": filing["accession"], "parser": 5}, fetch, hours=24 * 365)


def get_country_exposures(ticker: str, as_of: str | None = None) -> dict[str, Any]:
    """XBRL tiers of the exposure chain, point in time: the latest annual filing on or before as_of; if it has no
    geographic split, the previous one (stale: True). A refused request raises SecBlocked instead of "no filing".
    Countries come back as ISO2, regions as "REGION:<code>"."""
    as_of = as_of or date.today().isoformat()
    found = annual_filings(ticker, as_of)
    out = {"ticker": ticker, "status": found["status"], "exposures": [], "stale": False, "filing": None}
    for n, filing in enumerate(found["filings"][:2]):
        split = _xbrl_split(ticker, filing)
        out["filing"] = out["filing"] or {k: filing[k] for k in ("form", "accession", "filing_date", "report_date", "base")}
        if split["status"] == "available":
            old = (date.fromisoformat(as_of) - date.fromisoformat(filing["report_date"])).days > STALE_AFTER_DAYS
            return {**out, **split, "status": "available", "stale": n > 0 or old,
                    "used_filing": {k: filing[k] for k in ("form", "accession", "filing_date", "report_date")}}
        if n == 0:
            out.update(status=split["status"], fiscal_year=split["fiscal_year"])
    return out


