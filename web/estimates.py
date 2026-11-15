"""Fallback country exposure when no SEC filing gives a revenue split. No invented percentages:
an equal split across the countries recorded for the asset, labelled as an estimate everywhere it appears.

Country lists come from examples/portfolios.json (home country, main operating countries, ETF look-through
hints). Assets missing there use their listing country."""
from functools import lru_cache

from core.sample_portfolios import load
from web import universe as U

LISTING = {"TSX": "CAN", "NASDAQ": "USA", "NYSE": "USA", "NYSE Arca": "USA", "Cboe BZX": "USA"}


@lru_cache
def _meta() -> dict[str, dict]:
    """Sample-asset metadata keyed by our ticker (RY -> RY.TO, BTC -> BTC-USD)."""
    out = {}
    for t, a in load()["assets"].items():
        out[U.normalise_ticker(t) or t] = a
    return out


def estimate(ticker: str, asset: dict) -> tuple[dict[str, float], str]:
    """(country weights summing to 1, basis)."""
    if asset.get("asset_class") in ("crypto", "etf_commodity"):
        return {"Other": 1.0}, "no issuer country"
    m = _meta().get(ticker, {})
    look = m.get("primary_countries") or asset.get("primary_countries") or []
    if look:
        return {c: round(1 / len(look), 4) for c in look}, ("equal split across the ETF's main countries" if len(look) > 1 else "the ETF's main country")
    home = m.get("country") or asset.get("country") or LISTING.get(asset.get("market", ""))
    ops = [c for c in (m.get("ops") or asset.get("ops") or []) if c != home]
    countries = ([home] if home else []) + ops
    if not countries:
        return {"Other": 1.0}, "no country information"
    basis = "equal split across home and operating countries" if ops else "home country"
    return {c: round(1 / len(countries), 4) for c in countries}, basis
