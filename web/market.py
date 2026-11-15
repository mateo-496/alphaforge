"""Market data for the web pipeline (no LLM): Yahoo prices + SEC country revenue per holding, fetched in parallel;
one failing ticker never fails the run. Yahoo symbols are mapped to SEC tickers (RY.TO -> RY, CNR.TO -> CNI)."""
import json
import logging
import math
from datetime import date
from pathlib import Path

from tools import market_data

log = logging.getLogger("alphaforge.market")

_COUNTRIES = json.loads((Path(__file__).parent / "countries.json").read_text())
ISO2_TO_3 = {v["iso2"]: k for k, v in _COUNTRIES.items() if v.get("iso2")}
ISO3_TO_2 = {k: v["iso2"] for k, v in _COUNTRIES.items() if v.get("iso2")}

SEC_ALIAS = {"CNR.TO": "CNI", "BRK.B": "BRK-B"}
NO_FILINGS = {"etf_equity", "etf_bond", "etf_commodity", "crypto"}
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
    """Prices (Yahoo, 1 year) + XBRL country revenue shares from the latest annual filing on or before as_of.
    exposure_status "blocked" (with http_status) means EDGAR refused the request, not that there is no filing."""
    out = {"ticker": ticker, "prices": None, "price_error": None, "exposure_status": "not_applicable",
           "exposures": {}, "exposure_source": None, "fiscal_year": None, "stale": False, "filing": None,
           "sec_ticker": sec_ticker(ticker, asset)}
    try:
        out["prices"] = market_data.get_price_history(ticker, min(as_of, date.today().isoformat()), 365)
    except Exception as e:
        out["price_error"] = _err(e)
    st = sec_ticker(ticker, asset)
    if not st:
        return out
    try:
        res = market_data.get_country_exposures(st, as_of)
        out.update(exposure_status=res["status"], fiscal_year=res.get("fiscal_year"), stale=res.get("stale", False),
                   filing=res.get("filing"))
        if res["status"] == "available":
            for e in res["exposures"]:
                iso3 = e["country"] if e["country"].startswith("REGION:") else ISO2_TO_3.get(e["country"])
                if iso3:
                    out["exposures"][iso3] = out["exposures"].get(iso3, 0) + e["revenue_share"]
            out["exposure_source"] = res["exposures"][0]["source"] if res["exposures"] else None
    except market_data.SecBlocked as e:
        log.warning("SEC refused %s: HTTP %s (check SEC_IDENTITY and the request rate)", st, e.status)
        out.update(exposure_status="blocked", http_status=e.status, exposure_error=_err(e))
    except Exception as e:
        out["exposure_status"] = "error"
        out["exposure_error"] = _err(e)
        out["http_status"] = getattr(getattr(e, "response", None), "status_code", None)
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


