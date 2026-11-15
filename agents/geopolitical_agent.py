"""Geopolitical agent: country hazard on the analysis date (risk formula v2, tools/risk_math).

Code computes the number: g_c = percentile of the country's Caldara–Iacoviello GPR index among its own past
months (point in time). Countries the index does not cover use the global GPR, labelled as such.
Scenarios do not change the number; they are listed as context for the driver line.
One Bedrock call then writes a one-line driver per country from those facts. If the call fails,
the driver is a plain factual line built by code, so the report never shows invented text.
"""
from pydantic import BaseModel, Field
from strands import Agent

from agents.base import build_model
from tools import gpr

AGENT = "geopolitical"
MAX_LLM_COUNTRIES = 25

SYSTEM_PROMPT = """You are the Geopolitical analyst of AlphaForge, a portfolio-risk system.
For each country you get computed facts: its hazard (the percentile of its geopolitical-risk index among its
own past months, 0-100), whether that comes from the country's own index or the global one, and the
scenarios in which it is directly involved.
Write ONE driver line per country (max 140 characters) saying what drives its score.
Use only the supplied facts and scenario names. Do not add numbers that are not supplied. No advice."""


class CountryDriver(BaseModel):
    country: str = Field(description="ISO alpha-3 code exactly as supplied")
    driver: str = Field(description="Max 140 characters")


class CountryDrivers(BaseModel):
    drivers: list[CountryDriver]


def _fallback(f: dict) -> str:
    g = f.get("gpr")
    if not g:
        return "No GPR data"
    src = "global GPR (no country index)" if f["proxy"] else "GPR"
    parts = [f"{src} higher than {g['pct']:.0%} of months since {g['since']} ({g['month']})"]
    if f["scenarios"]:
        parts.append("involved in " + ", ".join(s["name"] for s in f["scenarios"][:2]))
    return "; ".join(parts)


def assess(countries: list[str], as_of: str, scenarios: list[dict], market: dict, names: dict,
           exposure: dict, on_event=None) -> tuple[dict, dict]:
    """Returns ({iso3: {g, gpr, proxy, scenarios, driver, method}}, meta {gpr, llm, error}).
    `market` is accepted for context only (the amplifier is applied once, at portfolio level)."""
    from tools.risk_math import INVOLVED
    emit = on_event or (lambda *a, **k: None)
    meta = {"gpr": None, "llm": False, "error": None}
    try:
        tbl = gpr.table()
        meta["gpr"] = {"name": f"Geopolitical Risk index — {gpr.CITATION}", "url": tbl["url"],
                       "retrieved": tbl["retrieved_at"]}
    except Exception as e:
        tbl, meta["error"] = None, f"GPR unavailable: {type(e).__name__}"
    glob = gpr.at(tbl, "GLOBAL", as_of) if tbl else None
    out = {}
    for c in countries:
        own = gpr.at(tbl, c, as_of) if tbl else None
        g = own or glob
        involved = sorted(({"name": s["name"], "key": s.get("key"), "intensity": s["countries"][c]}
                           for s in scenarios if s["countries"].get(c, 0) >= INVOLVED), key=lambda x: -x["intensity"])
        out[c] = {"g": g["pct"] if g else None, "gpr": g, "proxy": own is None and g is not None,
                  "scenarios": involved[:3],
                  "method": "country GPR" if own else "global GPR (country not covered)" if g else "no data"}
        out[c]["driver"] = _fallback(out[c])
    ranked = sorted((c for c in countries if out[c]["g"] is not None), key=lambda c: -exposure.get(c, 0))[:MAX_LLM_COUNTRIES]
    if ranked:
        emit("llm", "start", "bedrock", "Writing country drivers", f"{len(ranked)} countries · one call")
        facts = [{"country": c, "name": names.get(c, c), "hazard_percentile": round(100 * out[c]["g"]),
                  "index": "own" if not out[c]["proxy"] else "global",
                  "scenarios_involved": [s["name"] for s in out[c]["scenarios"]]} for c in ranked]
        try:
            import json
            agent = Agent(model=build_model(max_tokens=3000), system_prompt=SYSTEM_PROMPT, name="geopolitical_agent",
                          callback_handler=None)
            res = agent(json.dumps(facts), structured_output_model=CountryDrivers).structured_output
            for d in res.drivers:
                if d.country in out and d.driver.strip():
                    out[d.country]["driver"] = d.driver.strip()[:160]
            meta["llm"] = True
            emit("llm", "done", "bedrock", "Writing country drivers", f"{len(res.drivers)} drivers")
        except Exception as e:
            meta["error"] = f"driver writing failed: {type(e).__name__}"
            emit("llm", "done", "bedrock", "Writing country drivers", "unavailable, factual lines kept")
    return out, meta
