"""Real agents for the web pipeline. Each function returns the report shape `pipeline.py` expects, or None when
the item has no real source (ETFs, funds, non-SEC issuers) or the agent fails: the caller then uses the mock."""
import asyncio
import os

from tools import market_data, market_inputs, risk_math, worldbank
from tools.country_risk_inputs import ISO2_TO_ISO3, country_risk_score

ISO3_TO_ISO2 = {v: k for k, v in ISO2_TO_ISO3.items()}


def enabled() -> bool:
    return os.environ.get("USE_REAL_AGENTS", "1") == "1"


def _iso3(iso2: str) -> str | None:
    """ISO2 -> ISO3; countries the World Bank does not list (Taiwan) come from the GPR country table."""
    try:
        info = worldbank.country_info(iso2)
    except Exception:
        info = None
    return info["iso3"] if info else ISO2_TO_ISO3.get(iso2)


async def _filing_risk(ticker: str) -> float | None:
    """F_i from the filing-risk agent (needs the MCP server, see agents/filing_risk_agent.md)."""
    if os.environ.get("USE_FILING_RISK_AGENT", "1") != "1":
        return None
    from agents import filing_risk_agent
    report = await filing_risk_agent.run(f"ticker,weight\n{ticker},1\n")
    return risk_math.filing_risk([c for r in report.reports for c in r.claims])


async def asset_report(ticker: str, asset: dict, as_of: str) -> dict | None:
    if not enabled() or asset.get("asset_class") != "equity":
        return None
    try:
        found = await asyncio.to_thread(market_data.get_country_exposures, ticker)
        if found["status"] != "available":
            return None
        weights: dict[str, float] = {}
        for e in found["exposures"]:
            iso3 = _iso3(e["country"])
            if iso3:
                weights[iso3] = weights.get(iso3, 0.0) + e["revenue_share"]
        if not weights:
            return None
        other = max(0.0, 1.0 - sum(weights.values()))
        if other > 1e-9:
            weights["Other"] = other  # revenue the filing does not attribute to a country stays explicit
    except Exception:
        return None
    try:
        m = await asyncio.to_thread(market_inputs.vol_and_beta, ticker, as_of)
        market = risk_math.market_risk(m["vol_1y"], m["beta"])
    except Exception:
        market = None
    try:
        filing = await _filing_risk(ticker)
    except Exception:
        filing = None
    return {"ticker": ticker, "as_of": as_of, "country_weights": weights,
            "firm_score": round(5 * filing, 2) if filing is not None else 0.0,
            "filing": filing, "market": market,
            "method": "SEC annual filing, geographic revenue note",
            "sources": [found["exposures"][0]["source"]], "mock": False}


def _driver(measured: dict) -> str:
    gpr, stress = measured["gpr"], measured["stress"]
    parts = []
    if gpr:
        parts.append(f"geopolitical-risk press share at its {gpr['percentile']:.0%} percentile of the last ten years")
    if stress:
        parts.append(f"global financial stress at its {stress['percentile']:.0%} percentile")
    return "; ".join(parts) or "no measured input available"


async def country_report(iso3: str, as_of: str) -> dict | None:
    if not enabled():
        return None
    try:
        try:
            info = worldbank.country_info(iso3)
        except Exception:
            info = None
        iso2 = info["iso2"] if info else ISO3_TO_ISO2.get(iso3)
        if iso2 is None:
            return None
        measured = None
        sources = []
        if info:  # the country agent adds the World Bank macro claims; it needs Bedrock for its explanation
            try:
                from agents.country_risk_agent import analyze_country_scored
                report, measured = await asyncio.to_thread(analyze_country_scored, info["name"])
                sources = [s.model_dump() for c in report.claims for s in c.sources][:3]
            except Exception:
                measured = None
        if measured is None:
            measured = await asyncio.to_thread(country_risk_score, iso2, as_of)
        if measured["gpr"]:
            sources.append({"title": "Geopolitical Risk (GPR) index, Caldara and Iacoviello",
                            "url": "https://www.matteoiacoviello.com/gpr.htm",
                            "locator": f"gprc_{iso3.lower()}, {measured['gpr']['month']}"})
        return {"country": iso3, "as_of": as_of, "R": round(100 * measured["score"], 1),
                "driver": _driver(measured), "sources": sources, "mock": False}
    except Exception:
        return None
