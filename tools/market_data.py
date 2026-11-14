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
    identity = os.environ.get("SEC_IDENTITY", "")
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


def get_country_exposures(ticker: str) -> dict[str, Any]:
    """Read country revenue shares from the latest SEC 10-K or 20-F, where available."""
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
        candidates = []
        skipped_year_order = False
        for report in root.findall(".//Report"):
            title = report.findtext("ShortName", "")
            filename = report.findtext("HtmlFileName", "")
            if not re.search(r"geograph|segment", title, re.I):
                continue
            if not re.fullmatch(r"R\d+\.htm", filename, re.I):
                continue
            url = f"{base}/{filename}"
            html = _sec_get(url).text
            table = geo.find_geo_table(html)
            if table is None:
                continue
            text = table.get_text(" ", strip=True)
            if not re.search(r"\b(?:net\s+sales|net\s+revenue|total\s+revenues?)\b", text, re.I):
                continue
            if not any(re.fullmatch(r"(?:total|total\s+revenues?|total\s+net\s+sales|worldwide)",
                                    row.find(["td", "th"]).get_text(" ", strip=True), re.I)
                       for row in table.find_all("tr") if row.find(["td", "th"])):
                continue
            # The upstream parser uses the first numeric column for each country.
            if _oldest_year_first(table, fiscal_year):
                skipped_year_order = True
                continue
            result = geo.parse_geo_table(table, html, fiscal_year)
            if not result or not result.get("segments"):
                continue
            shares = sorted((country, float(percent) / 100) for country, percent in result["segments"])
            if any(not re.fullmatch(r"[A-Z]{2}", c) or not 0 <= v <= 1 for c, v in shares):
                raise ValueError(f"Invalid SEC geographic revenue values for {ticker}")
            if sum(v for _, v in shares) > 1 + 1e-9:
                raise ValueError(f"Overlapping SEC geographic revenue values for {ticker}")
            candidates.append((shares, title, url, result["fiscal_year"]))
        if not candidates:
            status = "unsupported_fiscal_year_order" if skipped_year_order else "no_country_revenue_found"
            return {"ticker": ticker, "status": status, "exposures": [],
                    "filing_url": base, "fiscal_year": fiscal_year}
        shares, title, url, reported_year = candidates[0]
        if any(candidate[0] != shares for candidate in candidates[1:]):
            raise ValueError(f"Conflicting geographic revenue tables for {ticker}; manual review required")
        source = _source(f"{ticker} SEC annual filing", url, f"{title}; fiscal year {reported_year}")
        return {"ticker": ticker, "status": "available", "fiscal_year": reported_year,
                "exposures": [{"country": country, "revenue_share": share,
                               "source": source.model_dump(mode="json")}
                              for country, share in shares]}

    return cached("sec-exposures", {"ticker": ticker}, fetch)
