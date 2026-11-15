"""Country risk agent: macro and banking fragility of the countries the portfolio earns in.

Facts come from the World Bank (tools/worldbank.py, point in time); the 0-100 macro score is computed by
tools/risk_calculator.py and is the national-risk input A1 of the risk formula (web/scoring.py). For the most
exposed countries, the source agent adds official sources and one LLM call writes a one-line note per country;
code drops any note with a number not in that country's facts.

    python -m agents.country_risk_agent CAN CHN --as-of 2026-11-12
"""
import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel, Field

from agents import source_agent
from agents.risk_agent import check
from core import llm
from tools import risk_calculator, worldbank

AGENT = "country_risk"
SYSTEM_PROMPT = """You are the Country risk analyst of AlphaForge. For each country you get World Bank macro and
banking indicators (with their year) and a computed macro-fragility score (0 = lower risk, 100 = higher).
Write ONE short note per country (max 80 characters) naming the one or two indicators that drive its score,
e.g. "High public debt (120.1% of GDP), low growth". Do not restate the score or the years.
Use only the supplied numbers, written the same way. No forecasts, no advice."""


class CountryNote(BaseModel):
    country: str = Field(description="ISO alpha-3 code exactly as supplied")
    note: str = Field(description="Max 80 characters")


class CountryNotes(BaseModel):
    notes: list[CountryNote]


def _fallback(ind: dict) -> str:
    keys = ("public_debt_pct_gdp", "inflation_pct", "gdp_growth_pct", "nonperforming_loans_pct")
    parts = [f"{ind[k]['label'].split(',')[0].lower()} {ind[k]['value']:g} ({ind[k]['year']})" for k in keys if k in ind]
    return "; ".join(parts).capitalize() or "No World Bank data"


NOT_MEMBERS = {"TWN": "Taiwan is not a World Bank member", "HKG": "Hong Kong is reported with China",
               "MAC": "Macao is reported with China"}


def _one(iso3: str, as_of: str, detail: bool = True) -> dict:
    ind, err = {}, None
    for attempt in range(3):   # the World Bank API drops requests under load: retry before giving up
        try:
            ind, err = worldbank.indicators(iso3, as_of), None
            break
        except Exception as e:
            err = f"World Bank unavailable: {type(e).__name__}: {str(e)[:80]}"
            time.sleep(1.5 * (attempt + 1))
    try:   # a country without data still gets its official sources, so the reader can look it up
        sources = source_agent.official_sources(iso3) if detail or not ind else []
    except Exception:
        sources = []
    macro = None
    if ind:
        vals = {k: v["value"] for k, v in ind.items()}
        a = risk_calculator.calculate_risk({k: vals.get(k) for k in worldbank.COUNTRY_FIELDS},
                                           {k: vals.get(k) for k in worldbank.BANK_FIELDS})
        macro = {"score": a["score"], "label": a["label"], "coverage_pct": a["coverage_pct"]}
    missing = NOT_MEMBERS.get(iso3, "No World Bank data before the analysis date")
    return {"indicators": ind, "macro": macro, "sources": sources, "note": _fallback(ind) if ind else
            (err or f"{missing}; see the official sources"), "error": err}


def assess(countries: list[str], as_of: str, names: dict, on_event=None,
           detail_for: list[str] | None = None) -> tuple[dict, dict]:
    """({iso3: {indicators, macro, sources, note, error}}, meta {llm, error}). Macro scores for every country;
    sources and LLM notes only for `detail_for` (default: all)."""
    emit = on_event or (lambda *a, **k: None)
    detail = set(countries if detail_for is None else detail_for)
    for c in countries:
        if c in detail:
            emit("country", "start", c, names.get(c, c), "World Bank")
    with ThreadPoolExecutor(max_workers=4) as pool:
        out = dict(zip(countries, pool.map(lambda c: _one(c, as_of, c in detail), countries)))
    for c in (c for c in countries if c in detail):
        m = out[c]["macro"]
        emit("country", "done", c, names.get(c, c), f"macro {m['score']:.0f}/100 · {m['label'].lower()}" if m
             else out[c]["note"])
    meta = {"llm": False, "error": None}
    facts = [{"country": c, "name": names.get(c, c), "macro_score": round(out[c]["macro"]["score"]),
              "label": out[c]["macro"]["label"],
              "indicators": {v["label"]: f"{v['value']:g} ({v['year']})" for v in out[c]["indicators"].values()}}
             for c in countries if out[c]["macro"] and c in detail]
    if facts:
        emit("llm", "start", "bedrock", "Writing macro notes", f"{len(facts)} countries · one call")
        try:
            res = llm.ask(AGENT, SYSTEM_PROMPT, json.dumps(facts), CountryNotes, max_tokens=2500)
            by = {f["country"]: f for f in facts}
            for n in res.notes:
                if n.country in by and n.note.strip() and check([n.note], by[n.country]):
                    out[n.country]["note"] = n.note.strip()[:100]
            meta["llm"] = True
            emit("llm", "done", "bedrock", "Writing macro notes", f"{len(res.notes)} notes")
        except Exception as e:
            meta["error"] = f"note writing failed: {type(e).__name__}: {str(e)[:200]}"
            emit("llm", "done", "bedrock", "Writing macro notes", "unavailable, factual lines kept")
    return out, meta


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("countries", nargs="+")
    p.add_argument("--as-of", required=True)
    a = p.parse_args()
    print(json.dumps(assess([c.upper() for c in a.countries], a.as_of, {})[0], indent=2))
