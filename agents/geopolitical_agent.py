"""Geopolitical agent: country hazard on the analysis date (risk formula v2, tools/risk_math).

Code computes the number (tools/risk_math.hazard): g_c = L_c (1/2 + heat_c/2), where the level L_c averages
internal instability (World Bank WGI political stability) and external tension (the country's 12-month GPR level,
log scale, across countries), and heat_c is the percentile of its GPR among its own past months (point in time).
Countries the index does not cover use the global GPR for the heat, labelled as such.
Scenarios do not change the number; they are listed as context for the driver line.
One Bedrock call then writes a one-line driver per country from those facts. If the call fails,
the driver is a plain factual line built by code, so the report never shows invented text.
"""
import json

from pydantic import BaseModel, Field

from core import config, llm, storage
from tools import gpr, risk_math, worldbank

AGENT = "geopolitical"

MAX_LLM_COUNTRIES = 25

SYSTEM_PROMPT = """You are the Geopolitical analyst of AlphaForge, a portfolio-risk system.
For each country you get computed facts: its hazard (0-100, combining political stability and its
geopolitical-risk index), whether the index is the country's own or the global one, and the
scenarios in which it is directly involved.
Write ONE short driver per country (max 60 characters, a noun phrase, no full sentence) naming what drives it,
e.g. "Taiwan Strait crisis, chip export controls". The hazard is shown in its own column: do not repeat it.
Use only the supplied facts and scenario names. Do not add numbers. No advice."""


class CountryDriver(BaseModel):
    country: str = Field(description="ISO alpha-3 code exactly as supplied")
    driver: str = Field(description="Max 60 characters, noun phrase")


class CountryDrivers(BaseModel):
    drivers: list[CountryDriver]


def _fallback(f: dict) -> str:
    g = f.get("gpr")
    if not g:
        return "No GPR data"
    if f["scenarios"]:
        return ", ".join(s["name"] for s in f["scenarios"][:2])
    return "Global GPR (no country index)" if f["proxy"] else "No scenario involves it"


def assess(countries: list[str], as_of: str, scenarios: list[dict], market: dict, names: dict,
           exposure: dict, on_event=None) -> tuple[dict, dict]:
    """Returns ({iso3: {g, gpr, proxy, scenarios, driver, method}}, meta {gpr, llm, error}).
    `market` is accepted for context only (the amplifier is applied once, at portfolio level)."""
    emit = on_event or (lambda *a, **k: None)
    meta = {"gpr": None, "llm": False, "error": None}
    try:
        tbl = gpr.table()
        meta["gpr"] = {"name": f"Geopolitical Risk index — {gpr.CITATION}", "url": tbl["url"],
                       "retrieved": tbl["retrieved_at"]}
    except Exception as e:
        tbl, meta["error"] = None, f"GPR unavailable: {type(e).__name__}"
    glob = gpr.at(tbl, "GLOBAL", as_of) if tbl else None
    anchors = gpr.tension_anchors(tbl, as_of) if tbl else None
    try:
        wgi = worldbank.political_stability(as_of)
    except Exception as e:   # the hazard degrades to the GPR level alone; said so in the report
        wgi = {}
        meta["error"] = f"WGI political stability unavailable: {type(e).__name__}"
    meta["wgi"] = {"name": worldbank.WGI_PV[1], "url": "https://www.worldbank.org/en/publication/worldwide-governance-indicators"}
    out = {}
    for c in countries:
        own = gpr.at(tbl, c, as_of) if tbl else None
        g = own or glob
        pv = wgi.get(c)
        S = risk_math.instability(pv["value"] if pv else None)
        E = risk_math.tension(own["mean_12m"] if own else None, anchors, c)
        heat = g["pct"] if g else None
        involved = sorted(({"name": s["name"], "key": s.get("key"), "intensity": s["countries"][c]}
                           for s in scenarios if s["countries"].get(c, 0) >= risk_math.INVOLVED), key=lambda x: -x["intensity"])
        parts = (["WGI stability"] if S is not None else []) + (["GPR level"] if E is not None else [])
        out[c] = {"g": risk_math.hazard(S, E, heat), "S": S, "E": E, "heat": heat, "wgi": pv,
                  "gpr": g, "proxy": own is None and g is not None, "scenarios": involved[:3],
                  "method": (" + ".join(parts) or "no level data") + " · heat: " +
                            ("country GPR" if own else "global GPR (country not covered)" if g else "none")}
        out[c]["driver"] = _fallback(out[c])
    ranked = sorted((c for c in countries if out[c]["g"] is not None), key=lambda c: -exposure.get(c, 0))[:MAX_LLM_COUNTRIES]
    if ranked:
        facts = [{"country": c, "name": names.get(c, c), "hazard_percentile": round(100 * out[c]["g"]),
                  "index": "own" if not out[c]["proxy"] else "global",
                  "scenarios_involved": [s["name"] for s in out[c]["scenarios"]]} for c in ranked]
        # A driver depends only on its own country's facts: saved per country, so any portfolio reuses it.
        ident = lambda f: {"model": config.BEDROCK_MODEL_ID, "system": SYSTEM_PROMPT, "fact": f}
        todo = []
        for f in facts:
            saved = storage.memo_get(f"{AGENT}/drivers", ident(f))
            if saved:
                out[f["country"]]["driver"] = saved
            else:
                todo.append(f)
        meta["cached"] = len(facts) - len(todo)
        meta["llm"] = bool(meta["cached"])
        saved_note = f" · {meta['cached']} saved" if meta["cached"] else ""
        if not todo:
            emit("llm", "done", "bedrock", "Writing country drivers", f"{meta['cached']} saved, no call")
        else:
            emit("llm", "start", "bedrock", "Writing country drivers", f"{len(todo)} countries · one call{saved_note}")
            try:
                res = llm.ask(AGENT, SYSTEM_PROMPT, json.dumps(todo), CountryDrivers, max_tokens=3000)
                by = {f["country"]: f for f in todo}
                for d in res.drivers:
                    if d.country in by and d.driver.strip():
                        out[d.country]["driver"] = d.driver.strip()[:160]
                        storage.memo_put(f"{AGENT}/drivers", ident(by[d.country]), out[d.country]["driver"])
                meta["llm"] = True
                emit("llm", "done", "bedrock", "Writing country drivers", f"{len(res.drivers)} drivers{saved_note}")
            except Exception as e:
                meta["error"] = f"driver writing failed: {type(e).__name__}: {str(e)[:200]}"
                emit("llm", "done", "bedrock", "Writing country drivers", "unavailable, factual lines kept")
    return out, meta
