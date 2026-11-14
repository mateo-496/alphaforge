"""Deterministic market data and portfolio calculations shared through MCP."""
import csv
import io
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from core.market_stress import EnrichedPortfolio, MarketSeries, Observation
from core.schemas import Source

OFR_URL = "https://www.financialresearch.gov/financial-stress-index/data/fsi.csv"
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
FRED_SERIES = {
    "STLFSI4": ("St. Louis Fed Financial Stress Index", "index"),
    "VIXCLS": ("Cboe Volatility Index via FRED", "percent"),
    "DGS10": ("US 10-year Treasury yield via FRED", "percent"),
    "DEXCHUS": ("Chinese yuan per US dollar via FRED", "CNY_per_USD"),
    "DEXJPUS": ("Japanese yen per US dollar via FRED", "JPY_per_USD"),
    "DEXCAUS": ("Canadian dollars per US dollar via FRED", "CAD_per_USD"),
    "DEXUSUK": ("US dollars per British pound via FRED", "USD_per_GBP"),
    "DEXUSEU": ("US dollars per euro via FRED", "USD_per_EUR"),
}


def _download(url: str) -> str:
    response = httpx.get(url, timeout=20, follow_redirects=True)
    response.raise_for_status()
    return response.content.decode("utf-8-sig")


def _source(title: str, url: str, locator: str) -> Source:
    return Source(title=title, url=url, locator=locator,
                  retrieved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))


def get_market_series(series_id: str, as_of: str, lookback_days: int = 90) -> dict[str, Any]:
    """Fetch OFR FSI or a supported FRED series, filtering by observation date.

    These are the latest revised data, not historical publication vintages.
    """
    end = date.fromisoformat(as_of)
    if not 1 <= lookback_days <= 3660:
        raise ValueError("lookback_days must be between 1 and 3660")
    start = end - timedelta(days=lookback_days)
    if series_id == "OFR_FSI":
        url, column, title, unit = OFR_URL, "OFR FSI", "OFR Financial Stress Index", "index"
    elif series_id in FRED_SERIES:
        title, unit = FRED_SERIES[series_id]
        url = FRED_URL + "?" + urlencode({"id": series_id, "cosd": start.isoformat(), "coed": end.isoformat()})
        column = series_id
    else:
        raise ValueError(f"Unsupported market series: {series_id}")
    rows = csv.DictReader(io.StringIO(_download(url)))
    if not rows.fieldnames or column not in rows.fieldnames:
        raise ValueError(f"Unexpected CSV format for {series_id}")
    date_column = rows.fieldnames[0]
    observations = []
    for row in rows:
        if not row.get(column) or row[column] == ".":
            continue
        observed = date.fromisoformat(row[date_column])
        if start <= observed <= end:
            observations.append(Observation(date=observed, value=float(row[column])))
    observations.sort(key=lambda item: item.date)
    series = MarketSeries(name=series_id, unit=unit, observations=observations,
                          source=_source(title, url, f"{column}; observation dates {start} through {end}"))
    return series.model_dump(mode="json")


def calculate_variation(series: dict) -> dict[str, Any]:
    """Calculate last-observation change against the previous available observation."""
    data = MarketSeries.model_validate(series)
    previous, current = data.observations[-2:]
    difference = current.value - previous.value
    return {
        "name": data.name,
        "unit": data.unit,
        "previous": previous.model_dump(mode="json"),
        "current": current.model_dump(mode="json"),
        "absolute_change": difference,
        "relative_change": difference / previous.value if previous.value != 0 else None,
        "source": data.source.model_dump(mode="json"),
    }


def decompose_portfolio(request: dict) -> dict[str, Any]:
    """Compute weighted revenue-country exposures, leaving unknown shares explicit."""
    portfolio = EnrichedPortfolio.model_validate(request)
    countries: dict[str, float] = {}
    holdings = []
    for holding in portfolio.holdings:
        exposures = []
        for exposure in holding.exposures:
            weighted = holding.weight * exposure.revenue_share
            countries[exposure.country] = countries.get(exposure.country, 0.0) + weighted
            exposures.append({**exposure.model_dump(), "portfolio_weight": weighted})
        unknown = holding.weight * max(0.0, 1.0 - sum(e.revenue_share for e in holding.exposures))
        holdings.append({"ticker": holding.ticker, "weight": holding.weight,
                         "countries": exposures, "unknown_weight": unknown})
    return {"by_ticker": holdings, "by_country": countries,
            "unknown_weight": sum(h["unknown_weight"] for h in holdings)}
