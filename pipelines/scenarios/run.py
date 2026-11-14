"""Scenario pipeline: generate weekly, save every query, merge with the previous set (moving average).

Storage layout (local ./data/<key> or s3://$S3_BUCKET/<key>):
    scenarios/queries/<UTC timestamp>_<scope>.json   every agent query, raw: prompt, tool calls, draft, merged result
    scenarios/<scope>/<YYYY-Www>.json                merged set for that ISO week
    scenarios/<scope>/latest.json                    pointer copy of the newest merged set
    scenarios/inputs/<YYYY-Www>/<source>.json       source texts + GPR table fetched that week (reused on reruns)
scope = 'global' (12 scenarios) or 'country-<ISO3>' (5 most dangerous for that country).

Weekly job (EventBridge Scheduler -> Lambda or ECS task):
    python -m pipelines.scenarios.run --scope global
"""
import argparse
import re
from datetime import date, datetime, timedelta, timezone

from agents import scenario_agent
from core import config, storage
from core.schemas import DraftScenario, Scenario, ScenarioSet

N_GLOBAL, N_COUNTRY = 12, 5
DROP_AFTER_MISSING = 3      # weeks a scenario may be absent from new runs before it is removed
MIN_LIKELIHOOD = 0.02


def scope_for(country: str | None) -> str:
    return f"country-{country.upper()}" if country else "global"


def week_of(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _usable(s: ScenarioSet | None) -> ScenarioSet | None:
    """Real mode never uses sets produced by the offline test mode, and vice versa."""
    return s if s and s.mock == config.SCENARIO_USE_MOCK else None


def latest(scope: str) -> ScenarioSet | None:
    d = storage.read_json(f"scenarios/{scope}/latest.json")
    return _usable(ScenarioSet(**d)) if d else None


def _weekly(scope: str) -> list[tuple[str, ScenarioSet]]:
    keys = [k for k in storage.list_keys(f"scenarios/{scope}/") if re.search(r"/\d{4}-W\d{2}\.json$", k)]
    out = []
    for k in keys:
        s = _usable(ScenarioSet(**storage.read_json(k)))
        if s:
            out.append((k.rsplit("/", 1)[1][:-5], s))
    return out


def merge_base(scope: str, prev: ScenarioSet | None) -> ScenarioSet | None:
    """Set to average against: last week's. A rerun in the same week replaces this week's result
    rather than averaging twice."""
    week = week_of(_now().date())
    if not prev or prev.week != week:
        return prev
    older = [s for w, s in _weekly(scope) if w < week]
    return older[-1] if older else None


def is_fresh(s: ScenarioSet | None) -> bool:
    if not s:
        return False
    age = _now() - datetime.fromisoformat(s.computed_at)
    return age < timedelta(days=config.SCENARIO_MAX_AGE_DAYS)


def for_as_of(scope: str, as_of: str) -> tuple[ScenarioSet | None, bool]:
    """Newest weekly set generated on or before as_of (no look-ahead). If none exists, the latest one,
    flagged True = 'generated after the analysis date'."""
    target = week_of(date.fromisoformat(as_of))
    past = [s for w, s in _weekly(scope) if w <= target]
    if past:
        return past[-1], False
    s = latest(scope)
    return s, s is not None


# ---------- moving-average merge ----------
def _tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z]{3,}", s.lower())) - {"the", "and", "war", "risk", "crisis"}


def _match_ids(prev: dict[str, Scenario], fresh: list[DraftScenario]) -> dict[str, str]:
    """fresh id -> previous id. Exact id first, then name similarity (Jaccard >= 0.4) as a fallback."""
    out, free = {}, set(prev)
    for f in fresh:
        if f.id in free:
            out[f.id] = f.id
            free.discard(f.id)
    for f in fresh:
        if f.id in out:
            continue
        best = max(free, key=lambda p: _jacc(f, prev[p]), default=None)
        if best and _jacc(f, prev[best]) >= 0.4:
            out[f.id] = best
            free.discard(best)
    return out


def _jacc(a, b) -> float:
    x, y = _tokens(a.name + " " + a.id), _tokens(b.name + " " + b.id)
    return len(x & y) / len(x | y) if x | y else 0


def _ema(new: float, old: float, a: float) -> float:
    return round(a * new + (1 - a) * old, 4)


def merge(previous: ScenarioSet | None, fresh: list[DraftScenario], scope: str, alpha: float,
          query_key: str, n: int, mock: bool, inputs: list[dict] | None = None) -> ScenarioSet:
    """x_t = alpha * x_new + (1 - alpha) * x_{t-1} for likelihood, impact, country intensities and sector shocks.
    New scenarios enter at their fresh values; scenarios missing from the new run decay and are dropped after
    DROP_AFTER_MISSING weeks. Text fields (name, summary, signposts) come from the newest run."""
    now, week = _now(), week_of(_now().date())
    prev = {s.id: s for s in (previous.scenarios if previous else [])}
    matched = _match_ids(prev, fresh)
    out: list[Scenario] = []
    for f in fresh:
        p = prev.get(matched.get(f.id, ""))
        if p:
            countries = {c: _ema(f.countries.get(c, 0), p.countries.get(c, 0), alpha)
                         for c in set(f.countries) | set(p.countries)}
            sectors = {k: _ema(f.sector_shocks.get(k, 0), p.sector_shocks.get(k, 0), alpha)
                       for k in set(f.sector_shocks) | set(p.sector_shocks)}
            have = {e.source_id for e in f.evidence}   # one quote per source: fresh first, older ones fill other sources
            evidence = f.evidence + [e for e in p.evidence if e.quote_verified and e.source_id not in have
                                     and not have.add(e.source_id)]
            s = Scenario(**f.model_dump(exclude={"id", "countries", "sector_shocks", "likelihood", "impact", "evidence"}),
                         id=p.id, countries={c: v for c, v in countries.items() if v >= 0.05},
                         sector_shocks={k: v for k, v in sectors.items() if abs(v) >= 0.05},
                         likelihood=_ema(f.likelihood, p.likelihood, alpha),
                         impact=round(_ema(f.impact, p.impact, alpha)) or 1,
                         evidence=evidence[:3], status="continuing", first_seen=p.first_seen,
                         last_updated=now.isoformat(timespec="seconds"), weeks_seen=p.weeks_seen + 1,
                         weeks_missing=0, history=p.history)
        else:
            s = Scenario(**f.model_dump(), status="new", first_seen=now.isoformat(timespec="seconds"),
                         last_updated=now.isoformat(timespec="seconds"))
        out.append(s)
    seen = {s.id for s in out}
    for p in prev.values():  # absent from this run: decay
        if p.id in seen:
            continue
        lk = round(p.likelihood * (1 - alpha), 4)
        if p.weeks_missing + 1 >= DROP_AFTER_MISSING or lk < MIN_LIKELIHOOD:
            continue
        out.append(p.model_copy(update={"likelihood": lk, "status": "fading", "weeks_missing": p.weeks_missing + 1}))
    for s in out:
        s.history = (s.history + [{"week": week, "likelihood": s.likelihood, "impact": s.impact}])[-12:]
    out.sort(key=lambda s: -s.likelihood * s.impact)
    return ScenarioSet(scope=scope, week=week, computed_at=now.isoformat(timespec="seconds"), alpha=alpha,
                       query_keys=((previous.query_keys if previous else []) + [query_key])[-12:],
                       mock=mock, inputs=inputs or [], scenarios=out[:n])


# ---------- entry point ----------
def generate(country: str | None = None, force: bool = False, on_event=None) -> ScenarioSet:
    """Return the current set for the scope; run the agent only if the latest set is missing or stale."""
    scope = scope_for(country)
    prev = latest(scope)
    if is_fresh(prev) and not force:
        return prev
    n = N_COUNTRY if country else N_GLOBAL
    prev = merge_base(scope, prev)
    stamp = _now().strftime("%Y%m%dT%H%M%SZ")
    query_key = f"scenarios/queries/{stamp}_{scope}.json"
    try:
        draft, record = scenario_agent.run(n=n, country=country, previous=prev,
                                           week=week_of(_now().date()), on_event=on_event)
    except Exception as e:  # the failed query is saved too
        storage.write_json(query_key, {"scope": scope, "error": f"{type(e).__name__}: {e}"})
        raise
    merged = merge(prev, draft.scenarios, scope, config.SCENARIO_ALPHA, query_key, n, config.SCENARIO_USE_MOCK,
                   record.get("inputs"))
    storage.write_json(query_key, {"scope": scope, **record, "previous_week": prev.week if prev else None,
                                   "merged": merged.model_dump()})
    storage.write_json(f"scenarios/{scope}/{merged.week}.json", merged.model_dump())
    storage.write_json(f"scenarios/{scope}/latest.json", merged.model_dump())
    return merged


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--country", default=None, help="ISO alpha-3 for the 5 most dangerous scenarios of a country")
    ap.add_argument("--force", action="store_true", help="run even if this week's set exists")
    a = ap.parse_args()
    s = generate(a.country, a.force, on_event=lambda *e: print("  ", *e))
    print(f"{s.scope} {s.week}: {len(s.scenarios)} scenarios")
    for x in s.scenarios:
        print(f"  {x.status:10} {x.likelihood:5.2f} x {x.impact}  {x.name}")
