"""Scenario agent: one Bedrock call that turns 4 risk reports + a GPR table into ranked scenarios.

Inputs are fetched by code (tools/scenario_sources.py), not by the model, so a run is short and predictable:
~4 x 7k characters of source text + a 15-row GPR table in, 12 scenarios out.

Usage (from repo root):
    python -m agents.scenario_agent                 # 12 global scenarios, printed
    python -m agents.scenario_agent --country TWN   # 5 most dangerous for Taiwan
Normally called through pipelines/scenarios.py (merges with last week's set and saves it).
"""
import argparse
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone

from core import config, llm
from core.schemas import DraftScenario, DraftScenarioSet, ScenarioEvidence, ScenarioSet
from tools import scenario_sources as src

AGENT = "scenarios"

SYSTEM_PROMPT = """You are the Scenario analyst of AlphaForge, a geopolitical portfolio-risk system.
From the source texts and the GPR table you are given, write the geopolitical scenarios investors should stress-test.

A scenario:
- is a concrete event chain (who does what, what follows), not a theme.
- countries: ISO alpha-3 -> intensity 0-1 (1.0 epicentre, 0.5 heavily affected, 0.2 spillover), 3-8 countries.
- channels: from the fixed taxonomy only.
- sector_shocks: GICS sector -> -1..1 for global equities (Energy, Information Technology, Financials, Industrials,
  Utilities, Consumer Staples, Consumer Discretionary, Health Care, Communication Services, Materials, Real Estate).
- summary: at most 350 characters (about 2 short sentences): what happens and why it matters for markets.
- likelihood: probability within 12 months, calibrated (most are below 0.3). Use the sources' language and the
  GPR z-scores (z > 1 = elevated) as anchors.
- impact: 1-5 for global markets if it happens.
- sector_shocks: at most 4 sectors.
- signposts: 2 short observable early warnings.
- evidence: 1-3 quotes copied VERBATIM (one sentence or phrase, under 200 characters each). When several source blocks
  discuss the scenario, take each quote from a DIFFERENT source_id. A quote not found word-for-word in its source
  block is discarded, and a scenario with no valid quote is dropped, so copy exactly.

Continuity: if last week's scenario ids are listed and a scenario is the same risk, REUSE its id exactly.
Rank by likelihood x impact. Be brief everywhere: output length is what makes this slow."""


def _prompt(n: int, country: str | None, previous: ScenarioSet | None, sources: list[dict], gpr: dict | None) -> str:
    today = date.today().isoformat()
    if country:
        task = (f"Today is {today}. Write the {n} most dangerous geopolitical scenarios for {country} (ISO alpha-3): "
                f"{country} is the epicentre or heavily affected (intensity >= 0.6).")
    else:
        task = (f"Today is {today}. Write the {n} most likely and impactful geopolitical scenarios for global markets "
                f"over the next 12 months. Cover different regions and channels.")
    blocks = [f'<source id="{s["id"]}" name="{s["name"]}">\n{s["text"]}\n</source>' for s in sources if s["ok"]]
    if gpr and not gpr.get("error"):
        rows = "\n".join(f"{c['iso3']}: z={c['z']} (last {c['last']}, {c['last_month']})" for c in gpr["countries"])
        g = gpr.get("global") or {}
        blocks.append(f"<gpr>Global GPR z={g.get('z')} ({g.get('last_month')}). Countries with the highest GPR "
                      f"vs. their own history:\n{rows}\n</gpr>")
    if previous and previous.scenarios:
        blocks.append("<last_week>\n" + "\n".join(f"{s.id}: {s.name}" for s in previous.scenarios) + "\n</last_week>")
    return task + "\n\n" + "\n\n".join(blocks)


def clip(text: str, limit: int = config.SUMMARY_MAX_CHARS) -> str:
    """Hard limit: cut at the last sentence end before the limit, else at a word, with an ellipsis."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("; "))
    return cut[:end + 1] if end > limit * 0.5 else cut[:cut.rfind(" ")].rstrip(",;:") + "…"


def _verify(draft: DraftScenarioSet, sources: list[dict]) -> tuple[DraftScenarioSet, list[str]]:
    """Code-side citation check: keep scenarios with at least one quote found verbatim in its source."""
    by_id = {s["id"]: s for s in sources if s["ok"]}
    kept, dropped = [], []
    for sc in draft.scenarios:
        ev = []
        for e in sc.evidence:
            s = by_id.get(e.source_id)
            ok = bool(s) and src.quote_is_verified(s["text"], e.quote)
            ev.append(e.model_copy(update={"quote_verified": ok, "url": s["url"] if s else "",
                                           "retrieved_at": s["retrieved_at"] if s else None}))
        seen, uniq = set(), []
        for e in ev:  # one quote per source on the card; keep unverified ones out
            if e.quote_verified and e.source_id not in seen:
                seen.add(e.source_id)
                uniq.append(e)
        if uniq:
            kept.append(sc.model_copy(update={"evidence": uniq, "summary": clip(sc.summary), "countries": {
                k.upper(): round(min(max(v, 0), 1), 3) for k, v in sc.countries.items()}}))
        else:
            dropped.append(sc.id)
    return draft.model_copy(update={"scenarios": kept}), dropped


def run(n: int = 12, country: str | None = None, previous: ScenarioSet | None = None,
        week: str | None = None, on_event=None) -> tuple[DraftScenarioSet, dict]:
    """Returns (verified draft set, query record). The record is saved by the pipeline, always."""
    emit = on_event or (lambda *a, **k: None)
    week = week or f"{date.today().isocalendar()[0]}-W{date.today().isocalendar()[1]:02d}"
    record = {"agent": AGENT, "model": config.SCENARIO_MODEL_ID, "n": n,
              "country": country, "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=2) as pool:   # sources and GPR download at the same time
        f_src, f_gpr = pool.submit(src.fetch_sources, week, emit), pool.submit(src.gpr_snapshot, week, emit)
        sources, gpr = f_src.result(), f_gpr.result()
    if not any(s["ok"] for s in sources):
        raise RuntimeError("No source could be fetched: " + "; ".join(f"{s['id']}: {s['error']}" for s in sources))
    prompt = _prompt(n, country, previous, sources, gpr)
    t_llm = time.time()
    emit("llm", "start", "bedrock", "Writing scenarios", f"one call · {len(prompt):,} characters in")
    result = llm.ask(AGENT, SYSTEM_PROMPT, prompt, DraftScenarioSet, model_id=config.SCENARIO_MODEL_ID, max_tokens=16000)
    draft, dropped = _verify(result, sources)
    record["llm_seconds"] = round(time.time() - t_llm, 1)
    emit("llm", "done", "bedrock", "Writing scenarios",
         f"{len(draft.scenarios)} in {record['llm_seconds']:.0f} s" + (f", {len(dropped)} dropped (no verified quote)" if dropped else ""))
    record.update(seconds=round(time.time() - t0, 1), prompt=prompt, prompt_chars=len(prompt),
                  inputs=[{k: s[k] for k in ("id", "name", "url", "retrieved_at", "ok")} for s in sources]
                         + ([{"id": "gpr", "name": "Caldara & Iacoviello, Geopolitical Risk index", "url": src.GPR_URL,
                              "retrieved_at": gpr.get("retrieved_at"), "ok": True}] if gpr and not gpr.get("error") else []),
                  sources=[{k: v for k, v in s.items() if k != "text"} for s in sources],
                  gpr=gpr, dropped_unverified=dropped, draft=draft.model_dump())
    return draft, record


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--country", default=None)
    p.add_argument("-n", type=int, default=None)
    a = p.parse_args()
    d, rec = run(a.n or (5 if a.country else 12), a.country, on_event=lambda *e: print("  ", *e))
    print(d.model_dump_json(indent=2))
    print(f"\n{len(d.scenarios)} scenarios in {rec['seconds']} s, prompt {rec['prompt_chars']:,} chars, "
          f"dropped: {rec['dropped_unverified']}")
