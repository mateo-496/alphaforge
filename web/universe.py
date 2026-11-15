"""Starter universe, prices and FX lookups used to validate and normalise uploaded portfolios."""
import csv
import io
import json
import os
from bisect import bisect_right
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).parent
STARTER_DIR = Path(os.environ.get("STARTER_DIR", "data/alphaforge_starter"))
WINDOW = ("2021-11-12", "2026-11-12")

ALIASES = {"BTC": "BTC-USD", "ETH": "ETH-USD", "BITCOIN": "BTC-USD", "ETHER": "ETH-USD",
           "GOOG": "GOOGL", "CNI": "CNR.TO"}


KIND = {"equity": "equity", "etf": "etf_equity", "bond_etf": "etf_bond", "commodity": "etf_commodity", "crypto": "crypto"}


@lru_cache
def load() -> dict:
    """Sample portfolios and their assets' countries (examples/portfolios.json)."""
    return json.loads((HERE.parent / "examples" / "portfolios.json").read_text())


@lru_cache
def starter() -> dict[str, dict]:
    """The 31 starter assets (with daily prices)."""
    with open(HERE / "assets_universe.csv", newline="") as f:
        return {r["ticker"]: {**r, "starter": True} for r in csv.DictReader(f)}


@lru_cache
def universe() -> dict[str, dict]:
    """Starter assets + the sample-portfolio assets (examples/portfolios.json). Starter wins on conflicts,
    and sample tickers that alias a starter one (RY -> RY.TO, BTC -> BTC-USD) are not duplicated."""
    u = dict(starter())
    for t, a in load()["assets"].items():
        if _starter_alias(t):
            continue
        u[t] = {"ticker": t, "name": a["name"], "asset_class": KIND.get(a["kind"], a["kind"]),
                "market": a.get("listing") or "", "currency": "CAD" if (a.get("listing") == "TSX" or t.endswith(".TO")) else "USD",
                "sector": "", "country": a.get("country"), "ops": a.get("ops", []),
                "primary_countries": a.get("primary_countries", []), "em": a.get("em", False), "starter": False}
    return u


def _starter_alias(raw: str) -> str | None:
    t = raw.strip().upper().replace(" ", "")
    st = starter()
    for cand in (t, ALIASES.get(t), f"{t}.TO", t.replace(".TSX", ".TO"), t.replace("-CA", ".TO")):
        if cand and cand in st:
            return cand
    return None


def sectors() -> list[str]:
    return sorted({a["sector"] for a in starter().values() if a["asset_class"] == "equity"})


def normalise_ticker(raw: str) -> str | None:
    t = raw.strip().upper().replace(" ", "")
    return _starter_alias(t) or (t if t in universe() else None)


@lru_cache
def _series() -> tuple[dict, list, list] | None:
    """(prices[ticker] = (dates, closes), fx_dates, fx_usdcad). None if starter data is missing."""
    p, fx = STARTER_DIR / "prices_daily.csv", STARTER_DIR / "fx_usdcad_daily.csv"
    if not (p.exists() and fx.exists()):
        return None
    prices: dict[str, tuple[list, list]] = {}
    with open(p, newline="") as f:
        for r in csv.DictReader(f):
            d, c = prices.setdefault(r["ticker"], ([], []))
            d.append(r["date"]); c.append(float(r["close"]))
    fd, fv = [], []
    with open(fx, newline="") as f:
        for r in csv.DictReader(f):
            fd.append(r["date"]); fv.append(float(r["usdcad"]))
    return prices, fd, fv


def _last_on_or_before(dates: list, values: list, day: str) -> float | None:
    i = bisect_right(dates, day)
    return values[i - 1] if i else None


def _usdcad(day: str) -> float | None:
    s = _series()
    if s:
        rate = _last_on_or_before(s[1], s[2], day)
        if rate:
            return rate
    try:  # FRED DEXCAUS (CAD per USD) through the shared market tools and cache
        from datetime import date as _d
        from core.storage import cached
        from tools.market_stress import get_market_series
        day = min(day, _d.today().isoformat())
        ser = cached("market-series", {"series_id": "DEXCAUS", "as_of": day, "days": 30},
                     lambda: get_market_series("DEXCAUS", day, 30))
        return ser["observations"][-1]["value"]
    except Exception:
        return None


def price_in(ticker: str, day: str, base: str) -> tuple[float | None, str]:
    """(close on or before `day`, converted to the base currency; source or error).
    Starter dataset first, then Yahoo Finance through the shared market tools (any listed ticker)."""
    px, ccy, src = None, universe().get(ticker, {}).get("currency", "USD"), "starter dataset"
    s = _series()
    if s and ticker in s[0]:
        px = _last_on_or_before(*s[0][ticker], day)
    if px is None:
        try:
            from datetime import date as _d
            from tools.market_data import get_price_history
            ser = get_price_history(ticker, min(day, _d.today().isoformat()), 10)
            px, ccy, src = ser["observations"][-1]["value"], ser["unit"].upper(), "Yahoo Finance"
        except Exception as e:
            return None, f"no starter price and Yahoo failed: {type(e).__name__}"
    if ccy == base:
        return px, src
    if {ccy, base} != {"USD", "CAD"}:
        return None, f"price in {ccy}, no conversion to {base}"
    rate = _usdcad(day)
    if rate is None:
        return None, "no USD/CAD rate"
    return (px * rate if base == "CAD" else px / rate), src


def prices_available() -> bool:
    return _series() is not None


COLS = {"ticker": ("ticker", "symbol", "asset", "code"),
        "weight": ("weight", "weight_pct", "allocation", "pct", "%"),
        "quantity": ("quantity", "qty", "shares", "units"),
        "value": ("value", "market_value", "amount", "mv")}


def parse_csv(text: str) -> tuple[str, list[dict], list[str]]:
    """Return (mode, rows[{ticker, amount, raw}], warnings). mode is weight | quantity | value."""
    sample = text[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    header = {h.strip().lower(): h for h in (reader.fieldnames or [])}
    pick = {k: next((header[a] for a in al if a in header), None) for k, al in COLS.items()}
    if not pick["ticker"]:
        return "weight", [], ["No ticker column found. Expected a header like: ticker,weight"]
    mode = next((m for m in ("weight", "quantity", "value") if pick[m]), None)
    if not mode:
        return "weight", [], ["No weight, quantity or value column found."]
    rows, warnings = [], []
    for i, r in enumerate(reader, start=2):
        raw_t = (r.get(pick["ticker"]) or "").strip()
        raw_a = (r.get(pick[mode]) or "").strip().replace("%", "").replace(" ", "").replace(",", ".")
        if not raw_t:
            continue
        try:
            amount = float(raw_a)
        except ValueError:
            warnings.append(f"Line {i}: '{raw_a}' is not a number, row skipped.")
            continue
        rows.append({"ticker": normalise_ticker(raw_t) or raw_t.upper(), "amount": amount, "raw": raw_t})
    if mode == "weight" and rows and sum(r["amount"] for r in rows) <= 1.5:
        for r in rows:  # fractions -> percent
            r["amount"] = round(r["amount"] * 100, 4)
    return mode, rows, warnings
