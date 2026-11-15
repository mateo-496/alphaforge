"""Website adapter for the market-stress agent.

Calls the same tool functions the MCP server exposes (tools.market_data, tools.market_stress), in-process,
so the website needs no second server. The command-line agent (agents/market_stress_agent.py) still uses MCP.
Differences from the CLI agent, needed for a live website:
  * one failing ticker or series never fails the run: its status is recorded and the report says so;
  * holdings are fetched in parallel, with progress events;
  * Yahoo symbols are mapped to SEC tickers (RY.TO -> RY, CNR.TO -> CNI) for the filings lookup;
  * the analysis date is the user's as_of, not today.
Stress is turned into features for the risk formula (tools/risk_math), not scored by an LLM.
"""
import json
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from agents import market_stress_agent as msa
from tools import market_data, market_stress, risk_math
from tools.market_cache import cached

_COUNTRIES = json.loads((Path(__file__).parent / "countries.json").read_text())
ISO2_TO_3 = {v["iso2"]: k for k, v in _COUNTRIES.items() if v.get("iso2")}
ISO3_TO_2 = {k: v["iso2"] for k, v in _COUNTRIES.items() if v.get("iso2")}

SEC_ALIAS = {"CNR.TO": "CNI", "BRK.B": "BRK-B"}
NO_FILINGS = {"etf_equity", "etf_bond", "etf_commodity", "crypto"}
# Country indicators available through FRED (same table as the MCP server).
COUNTRY_SERIES = {
    "US": "DGS10", "CN": "DEXCHUS", "JP": "DEXJPUS", "CA": "DEXCAUS", "GB": "DEXUSUK",
    "AT": "DEXUSEU", "BE": "DEXUSEU", "DE": "DEXUSEU", "ES": "DEXUSEU",
    "FI": "DEXUSEU", "FR": "DEXUSEU", "IE": "DEXUSEU", "IT": "DEXUSEU",
    "NL": "DEXUSEU", "PT": "DEXUSEU",
}


NAMES = {"OFR_FSI": "OFR Financial Stress Index", "STLFSI4": "St. Louis Fed Financial Stress Index",
         "VIXCLS": "Cboe Volatility Index (VIX)"}


def sec_ticker(ticker: str, asset: dict) -> str | None:
    if asset.get("asset_class") in NO_FILINGS:
        return None
    if ticker in SEC_ALIAS:
        return SEC_ALIAS[ticker]
    return ticker.removesuffix(".TO")


def _err(e: Exception) -> str:
    return f"{type(e).__name__}: {str(e)[:140]}"


def price_stats(series: dict) -> dict:
    """1-year return, max drawdown and annualised volatility from daily adjusted closes."""
    v = [o["value"] for o in series["observations"]]
    if len(v) < 20:
        return {}
    rets = [math.log(b / a) for a, b in zip(v, v[1:]) if a > 0 and b > 0]
    m = sum(rets) / len(rets)
    sd = math.sqrt(sum((r - m) ** 2 for r in rets) / (len(rets) - 1))
    peak, mdd = v[0], 0.0
    for x in v:
        peak = max(peak, x)
        mdd = min(mdd, x / peak - 1)
    return {"ret": v[-1] / v[0] - 1, "max_drawdown": mdd, "vol": sd * math.sqrt(252),
            "first": series["observations"][0]["date"], "last": series["observations"][-1]["date"]}


def fetch_holding(ticker: str, asset: dict, as_of: str) -> dict:
    """Prices (Yahoo, 1 year) + disclosed country revenue shares (latest SEC 10-K / 20-F)."""
    out = {"ticker": ticker, "prices": None, "price_error": None, "exposure_status": "not_applicable",
           "exposures": {}, "exposure_source": None, "fiscal_year": None}
    try:
        out["prices"] = market_data.get_price_history(ticker, min(as_of, date.today().isoformat()), 365)
    except Exception as e:
        out["price_error"] = _err(e)
    st = sec_ticker(ticker, asset)
    if not st:
        return out
    try:
        res = market_data.get_country_exposures(st)
        out["exposure_status"] = res["status"]
        out["fiscal_year"] = res.get("fiscal_year")
        if res["status"] == "available":
            for e in res["exposures"]:
                iso3 = e["country"] if e["country"].startswith("REGION:") else ISO2_TO_3.get(e["country"])
                if iso3:
                    out["exposures"][iso3] = out["exposures"].get(iso3, 0) + e["revenue_share"]
            out["exposure_source"] = res["exposures"][0]["source"] if res["exposures"] else None
    except Exception as e:
        out["exposure_status"] = "error"
        out["exposure_error"] = _err(e)
    return out


# ---------- regions disclosed instead of countries ----------
REGION_LABEL = {"AMERICAS": "Americas", "NORTHAM": "North America", "LATAM": "Latin America", "EUROPE": "Europe",
                "EMEA": "Europe, Middle East & Africa", "MEA": "Middle East & Africa", "APAC": "Asia-Pacific",
                "GCHINA": "Greater China", "JPKR": "Japan & Korea", "ROW": "Rest of world", "INTL": "International"}


def region_members(key: str) -> dict[str, float]:
    """REGION:EUROPE -> {iso3: weight} from the parser's reference splits. Used ONLY to average country hazard
    for a region the company reports as one line; never shown as country exposure."""
    from edgar_geo_revenue import REGION_SPLITS
    out = {}
    for iso2, w in REGION_SPLITS.get(key.split(":", 1)[1], []):
        if ISO2_TO_3.get(iso2):
            out[ISO2_TO_3[iso2]] = out.get(ISO2_TO_3[iso2], 0) + w
    return out


def region_name(key: str) -> str:
    return REGION_LABEL.get(key.split(":", 1)[1], key.split(":", 1)[1].title()) + " (region)"


def fetch_holdings(weights: dict, uni: dict, as_of: str, emit) -> dict[str, dict]:
    def one(t):
        emit("start", t, uni[t]["name"], "")
        h = fetch_holding(t, uni[t], as_of)
        emit("done", t, uni[t]["name"], h)
        return t, h
    with ThreadPoolExecutor(max_workers=6) as pool:   # SEC requests stay rate-limited by the tool's own lock
        return dict(pool.map(one, list(weights)))


def _series(sid: str, day: str) -> dict:
    return cached("market-series", {"series_id": sid, "as_of": day, "days": risk_math.Z_WINDOW_DAYS},
                  lambda: market_stress.get_market_series(sid, day, risk_math.Z_WINDOW_DAYS))


def stress(weights: dict, holdings: dict, countries_iso3: list[str], as_of: str, emit) -> dict:
    """Market-stress FEATURES for the risk formula (no score of its own, no LLM):
      * z_k: each global stress index (OFR FSI, STLFSI4, VIX) against its own 3-year window;
      * m = mean z_k, the market-stress level;
      * z_c: the country's FX / yield move over ~1 month against its 3-year history of such moves.
    Holdings' price statistics are kept as context for the report."""
    day = min(as_of, date.today().isoformat())
    facts, status, global_z = [], {}, {}
    for sid in msa.SERIES:
        emit("source", "start", sid, sid, "")
        try:
            series = _series(sid, day)
            var = market_stress.calculate_variation(series)   # validates the series first
            vals = [o["value"] for o in series["observations"]]
            global_z[sid] = risk_math.level_z(vals)
            facts.append({"ticker": "GLOBAL", **var, "z": global_z[sid],
                          "n_obs": len(vals), "first": series["observations"][0]["date"]})
            status[sid] = "available"
        except Exception as e:
            status[sid] = _err(e)
        emit("source", "done", sid, sid, f"z {global_z[sid]:+.2f}" if global_z.get(sid) is not None else "unavailable")
    country_status, country_z = {}, {}
    for iso3 in countries_iso3:
        sid = COUNTRY_SERIES.get(ISO3_TO_2.get(iso3) or "")
        if not sid:
            country_status[iso3] = "unsupported"
            continue
        try:
            series = _series(sid, day)
            var = market_stress.calculate_variation(series)
            country_z[iso3] = risk_math.move_z([o["value"] for o in series["observations"]])
            facts.append({"ticker": f"COUNTRY-{ISO3_TO_2[iso3]}", **var, "z": country_z[iso3]})
            country_status[iso3] = "available"
        except Exception as e:
            country_status[iso3] = _err(e)
    for t, h in holdings.items():
        if h["prices"] and len(h["prices"]["observations"]) >= 2:
            facts.append({"ticker": t, **market_stress.calculate_variation(h["prices"])})
    return {"facts": facts, "series_status": status, "country_status": country_status, "as_of": day,
            "global_z": global_z, "m": risk_math.market_stress_level(global_z), "country_z": country_z}


def summarise(result: dict, holdings: dict, weights: dict, uni: dict, names: dict) -> dict:
    """Shape the stress features for the report template."""
    glob = []
    for f in [f for f in result["facts"] if f["ticker"] == "GLOBAL"]:
        glob.append({"id": f["name"], "name": f["source"]["title"], "unit": f["unit"], "level": f["current"]["value"],
                     "date": f["current"]["date"], "change": f["absolute_change"], "prev_date": f["previous"]["date"],
                     "z": f.get("z"), "window_start": f.get("first"), "url": f["source"]["url"]})
    countries, by_series = [], {}
    for f in [f for f in result["facts"] if f["ticker"].startswith("COUNTRY-")]:
        iso2 = f["ticker"][8:]
        name = names.get(ISO2_TO_3.get(iso2, ""), iso2)
        if f["name"] in by_series:   # one row per indicator: EUR/USD covers every euro-area country
            by_series[f["name"]]["members"].append(name)
            by_series[f["name"]]["iso3s"].append(ISO2_TO_3.get(iso2, iso2))
            continue
        row = {"iso3": ISO2_TO_3.get(iso2, iso2), "iso3s": [ISO2_TO_3.get(iso2, iso2)], "name": name, "members": [name],
               "indicator": f["source"]["title"], "unit": f["unit"], "level": f["current"]["value"],
               "change": f["absolute_change"], "date": f["current"]["date"], "z": f.get("z"), "url": f["source"]["url"]}
        by_series[f["name"]] = row
        countries.append(row)
    for row in countries:
        if len(row["members"]) > 1:
            row["name"] = "Euro area (" + ", ".join(row["members"]) + ")" if "EUR" in row["unit"] else ", ".join(row["members"])
    rows = []
    for t, w in sorted(weights.items(), key=lambda kv: -kv[1]):
        h = holdings.get(t, {})
        st = price_stats(h["prices"]) if h.get("prices") else {}
        fact = next((f for f in result["facts"] if f["ticker"] == t), None)
        rows.append({"ticker": t, "name": uni[t]["name"], "weight": w, **st,
                     "day_change": fact["relative_change"] if fact else None,
                     "price_error": h.get("price_error"), "exposure_status": h.get("exposure_status")})
    sources = []
    for f in result["facts"]:
        if f["ticker"] == "GLOBAL" or f["ticker"].startswith("COUNTRY-"):
            sources.append({"name": f["source"]["title"], "url": f["source"]["url"],
                            "retrieved": f["source"]["retrieved_at"], "cited_by": ["Market stress"]})
    priced = [t for t, h in holdings.items() if h.get("prices")]
    if priced:
        sources.append({"name": "Yahoo Finance adjusted daily close (via yfinance)", "url": "https://finance.yahoo.com/",
                        "retrieved": next(holdings[t]["prices"]["source"]["retrieved_at"] for t in priced),
                        "cited_by": [f"Prices: {', '.join(priced[:12])}{'…' if len(priced) > 12 else ''}"]})
    m = result.get("m")
    return {"global": glob, "countries": countries, "holdings": rows, "sources": sources, "as_of": result["as_of"],
            "m": m, "amplifier": risk_math.amplifier(m), "country_z": result.get("country_z", {}),
            "unpriced": [r["ticker"] for r in rows if r["price_error"]],
            "unsupported_countries": [c for c, s in result["country_status"].items() if s == "unsupported"]}
