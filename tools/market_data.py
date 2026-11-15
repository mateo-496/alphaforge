"""Shared price and geographic revenue retrieval."""
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
import httpx
import yfinance as yf

from core.market_stress import MarketSeries, Observation
from core.schemas import Source
from tools.market_cache import cached

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
    from core.config import _sec_identity
    identity = _sec_identity(os.environ.get("SEC_IDENTITY", ""))
    if not identity or "example.com" in identity.lower() or "@" not in identity:
        raise ValueError("SEC_IDENTITY must contain a real contact email for SEC access")
    with _SEC_LOCK:
        wait = 0.125 - (time.monotonic() - _last_sec_request)
        if wait > 0:
            time.sleep(wait)
        response = httpx.get(url, headers={"User-Agent": identity}, timeout=30, follow_redirects=True)
        _last_sec_request = time.monotonic()
    response.raise_for_status()
    return response


def get_price_history(ticker: str, as_of: str, lookback_days: int = 90) -> dict[str, Any]:
    """Fetch adjusted daily Yahoo Finance prices, cached in S3 for 24 hours."""
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

    return cached("prices", {"ticker": ticker, "as_of": as_of, "days": lookback_days}, fetch)


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


def get_country_exposures(ticker: str) -> dict[str, Any]:
    """Read country (and, when that is all the filing gives, region) revenue shares from the latest SEC 10-K or
    20-F. Region rows come back as "REGION:<code>" (e.g. REGION:EUROPE): real disclosed shares, never split
    into invented country numbers."""
    _validate_ticker(ticker)

    def fetch() -> dict:
        entries = _ticker_map()
        entry = next((e for e in entries.values() if e["ticker"].upper() == ticker), None)
        if entry is None:
            return {"ticker": ticker, "status": "no_sec_ticker", "exposures": []}
        cik = str(entry["cik_str"]).zfill(10)
        submission = _sec_get(f"https://data.sec.gov/submissions/CIK{cik}.json").json()
        recent = submission["filings"]["recent"]
        filing = next((i for i, form in enumerate(recent["form"]) if form in ("10-K", "20-F")), None)
        if filing is None:
            return {"ticker": ticker, "status": "no_annual_filing", "exposures": []}
        accession = recent["accessionNumber"][filing].replace("-", "")
        fiscal_date = recent["reportDate"][filing]
        fiscal_year = date.fromisoformat(fiscal_date).year
        base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession}"
        root = ET.fromstring(_sec_get(f"{base}/FilingSummary.xml").content)
        # Which XBRL report pages may hold the geographic revenue table, best first. The old filter only looked
        # at titles containing "geograph|segment" and then required the words "net sales / net revenue / total
        # revenue", which rejected most tables headed "Revenues" and every "Disaggregation of revenue" page.
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
            status = "unsupported_fiscal_year_order" if skipped_year_order else "no_country_revenue_found"
            return {"ticker": ticker, "status": status, "exposures": [], "filing_url": base, "fiscal_year": fiscal_year,
                    "pages_checked": [t for _, t, _ in pages[:MAX_R_PAGES]]}
        # Several tables can match (revenue by country and by region, segment sub-tables): keep the one closest
        # to a full company-wide breakdown instead of failing the whole holding.
        best = sorted(candidates, key=lambda c: (not c["clean"], c["rank"], -c["n"]))[0]
        source = _source(f"{ticker} SEC annual filing", best["url"], f"{best['title']}; fiscal year {best['fy']}")
        return {"ticker": ticker, "status": "available", "fiscal_year": best["fy"],
                "exposures": [{"country": country, "revenue_share": share, "source": source.model_dump(mode="json")}
                              for country, share in best["shares"]]}

    return cached("sec-exposures-v2", {"ticker": ticker}, fetch)   # v2: old cached "not found" results ignored
