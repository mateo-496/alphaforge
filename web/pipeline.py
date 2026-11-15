"""Run pipeline: what the server does after the user clicks Run analysis.

Each step writes progress events to the run store (the page polls them) and its data to the cache.
Everything below is MOCKED: swap each `_mock_*` call for the real agent, keep the event and data shapes.
"""
import asyncio
import math
from datetime import date, timedelta

from tools import risk_math
from tools.portfolio_score import calculate_portfolio_risk
from web import mock, universe as U
from web.store import cache, runs

DELAY = {"asset": 0.7, "country": 0.35, "step": 0.8}  # mock latency, makes the progress view visible


# ---------- mock agents (replace with agents/*.run) ----------
def _mock_asset_report(ticker: str, as_of: str) -> dict:
    a = U.universe()[ticker]
    is_fund = a["asset_class"] != "equity"
    return {"ticker": ticker, "as_of": as_of, "country_weights": mock.exposure(ticker, a),
            "firm_score": mock.FIRM_SCORE.get(ticker, 1.0),
            "method": "ETF look-through" if a["asset_class"].startswith("etf") else
                      ("No issuer country" if is_fund else "Annual filing, segment note"),
            "sources": [mock.MOCK_SOURCE]}


def _mock_country_report(iso3: str, as_of: str) -> dict:
    r, driver = mock.COUNTRY.get(iso3, mock.COUNTRY["Other"])
    return {"country": iso3, "as_of": as_of, "R": r, "driver": driver, "sources": [mock.MOCK_SOURCE]}


# ---------- helpers ----------
def _ret_1y(ticker: str, as_of: str) -> float | None:
    s = U._series()
    if not s or ticker not in s[0]:
        return None
    d, c = s[0][ticker]
    end = U.bisect_right(d, as_of)
    start = U.bisect_right(d, (date.fromisoformat(as_of) - timedelta(days=365)).isoformat())
    return c[end - 1] / c[start - 1] - 1 if end and start else None


def _asset_risk(rep: dict, R: dict) -> float:
    """G_i = 0.8 * exposure-weighted country risk + 0.2 * firm-specific score (0-5 rescaled to 0-100)."""
    return 0.8 * risk_math.ticker_risk(rep["country_weights"], R) + 0.2 * rep["firm_score"] * 20


def _level(score: float) -> str:
    return "low" if score < 30 else "moderate" if score < 40 else "elevated" if score < 50 else "high"


def scenario_impacts(sets: list[dict], weights: dict, assets: dict) -> list[dict]:
    """Per scenario: share of portfolio revenue in affected countries, weighted by intensity."""
    out = []
    for group in sets:
        for s in group["scenarios"]:
            per = {t: w * sum(cw * s["countries"].get(c, 0) for c, cw in assets[t]["country_weights"].items())
                   for t, w in weights.items()}
            top = [t for t, v in sorted(per.items(), key=lambda kv: -kv[1]) if v > 0.005][:4]
            out.append({**s, "key": f"{group['scope']}/{s['id']}", "scope": group["scope"],
                        "group": group["label"], "exposure": round(sum(per.values()), 4), "holdings": top})
    return out


def _scenario_sets(run_id: str, req: dict) -> list[dict]:
    """Scenario step: reuse this week's sets, otherwise run the scenario agent (saved to S3), then pick the
    set matching the analysis date. Runs in a worker thread because the agent is blocking."""
    from pipelines.scenarios import run as sc
    ev = lambda **kw: runs.append_event(run_id, **kw)
    hook = lambda kind, status, id, label, detail="": ev(kind=kind, phase="scenarios", status=status,
                                                         id=id, label=label, detail=detail)
    from concurrent.futures import ThreadPoolExecutor
    countries = [None] + ([req["scenario_country"]] if req.get("scenario_country") else [])
    label_of = lambda c: "Global" if not c else f"Most dangerous for {mock.COUNTRY_NAMES.get(c, c)}"

    def ensure(country):
        label = label_of(country)
        if sc.is_fresh(sc.latest(sc.scope_for(country))):
            return
        ev(kind="note", phase="scenarios", status="done", label=label, detail="none this week, running the agent")
        try:
            new = sc.generate(country, on_event=hook)
            for s in new.scenarios:
                ev(kind="scenario", phase="scenarios", status="done", id="", label=s.name,
                   detail=f"{s.likelihood:.0%} · impact {s.impact}/5")
        except Exception as e:  # keep the report; show the newest earlier set if there is one
            ev(kind="note", phase="scenarios", status="error", label=label,
               detail=f"scenario agent failed: {type(e).__name__}: {str(e)[:160]}")

    with ThreadPoolExecutor(max_workers=2) as pool:   # global and country sets are written at the same time
        list(pool.map(ensure, countries))
    sets = []
    for country in countries:
        scope, label = sc.scope_for(country), label_of(country)
        chosen, after = sc.for_as_of(scope, req["as_of"])
        if chosen:
            sets.append({"scope": scope, "label": label, "week": chosen.week, "computed_at": chosen.computed_at,
                         "after_as_of": after, "inputs": chosen.inputs,
                         "scenarios": [s.model_dump() for s in chosen.scenarios]})
    return sets


# ---------- the run ----------
async def run(run_id: str) -> None:
    rec = runs.get(run_id)
    req = rec["request"]
    as_of = req["as_of"]
    weights = {h["ticker"]: h["weight"] for h in req["portfolio"]["holdings"]}
    uni = U.universe()
    ev = lambda **kw: runs.append_event(run_id, **kw)

    try:
        runs.set(run_id, status="running")

        # 1. Filings agent, one asset at a time (cache shared across runs)
        ev(kind="phase", phase="assets", status="start", label="Company filings")
        assets = {}
        for t in weights:
            ev(kind="asset", phase="assets", status="start", id=t, label=uni[t]["name"])
            rep = cache.get("assets", f"{t}_{as_of}")
            if rep is None:
                await asyncio.sleep(DELAY["asset"])
                rep = _mock_asset_report(t, as_of)
                cache.put("assets", f"{t}_{as_of}", rep)
            else:
                await asyncio.sleep(0.15)
            assets[t] = rep
            top = sorted(((c, w) for c, w in rep["country_weights"].items() if c != "Other"), key=lambda x: -x[1])[:3]
            ev(kind="asset", phase="assets", status="done", id=t, label=uni[t]["name"],
               detail=", ".join(f"{c} {w:.0%}" for c, w in top) or rep["method"])
        ev(kind="phase", phase="assets", status="done")

        # 2. Geopolitical agent, one country at a time, ordered by portfolio exposure
        X = {}
        for t, w in weights.items():
            for c, cw in assets[t]["country_weights"].items():
                X[c] = X.get(c, 0) + w * cw
        ev(kind="phase", phase="countries", status="start", label="Country risk")
        countries = {}
        for c in sorted((c for c in X if c != "Other"), key=lambda c: -X[c]):
            name = mock.COUNTRY_NAMES.get(c, c)
            ev(kind="country", phase="countries", status="start", id=c, label=name)
            rep = cache.get("countries", f"{c}_{as_of}")
            if rep is None:
                await asyncio.sleep(DELAY["country"])
                rep = _mock_country_report(c, as_of)
                cache.put("countries", f"{c}_{as_of}", rep)
            countries[c] = rep
            ev(kind="country", phase="countries", status="done", id=c, label=name, detail=f"risk {rep['R']}/100")
        countries["Other"] = _mock_country_report("Other", as_of)
        ev(kind="phase", phase="countries", status="done")

        # 3. Scenarios: weekly, shared by all users, generated only if missing
        ev(kind="phase", phase="scenarios", status="start", label="Scenarios")
        sets = await asyncio.to_thread(_scenario_sets, run_id, req)
        ev(kind="phase", phase="scenarios", status="done", label="Scenarios",
           detail=" · ".join(f"{g['label']}: {len(g['scenarios'])} ({g['week']})" for g in sets))

        # 4. Risk (deterministic 2-stage formula, tools/portfolio_score)
        ev(kind="phase", phase="risk", status="start", label="Portfolio risk")
        await asyncio.sleep(DELAY["step"])
        R = {c: r["R"] for c, r in countries.items()}
        G = {t: _asset_risk(assets[t], R) for t in weights}
        risk_calc = calculate_portfolio_risk(
            weights=weights,
            profile=req.get("profile"),
            assets=assets,
            countries=countries,
            scenarios=sets,
        )
        score = risk_calc["score"]
        ev(kind="phase", phase="risk", status="done", detail=f"{score:.0f}/100")

        # 5. Report: drivers, watchlist, what-ifs, scenarios
        ev(kind="phase", phase="report", status="start", label="Report")
        await asyncio.sleep(DELAY["step"])
        result = build_report(req, weights, assets, countries, X, G, score, sets, risk_calc=risk_calc)
        ev(kind="phase", phase="report", status="done")
        runs.set(run_id, status="done", result=result)
        ev(kind="run", status="done")
    except Exception as e:  # surface the error on the page instead of hanging
        runs.set(run_id, status="error", error=f"{type(e).__name__}: {e}")
        ev(kind="run", status="error", detail=str(e))


def build_report(req, weights, assets, countries, X, G, score, sets, risk_calc: dict | None = None) -> dict:
    uni, as_of, prof = U.universe(), req["as_of"], req["profile"]
    if risk_calc is None:
        risk_calc = calculate_portfolio_risk(
            weights=weights,
            profile=prof,
            assets=assets,
            countries=countries,
            scenarios=sets,
        )
        score = risk_calc["score"]

    by_holding = sorted(({"ticker": t, "name": uni[t]["name"], "weight": w, "G": round(G[t], 1),
                          "contribution": w * G[t] / score if score else 0,
                          "method": assets[t]["method"]} for t, w in weights.items()),
                        key=lambda r: -r["contribution"])
    by_country = sorted(({"iso3": c, "name": mock.COUNTRY_NAMES.get(c, c), "X": round(x, 4),
                          "R": countries[c]["R"], "driver": countries[c]["driver"],
                          "holdings": [t for t in weights if assets[t]["country_weights"].get(c, 0) >= 0.05]}
                         for c, x in X.items() if c != "Other"), key=lambda r: -r["X"] * r["R"])

    # Watchlist: I_e = X * severity * likelihood / (1 + days/90)
    watch = []
    for e in mock.EVENTS:
        x = weights.get(e["ticker"], 0) if e.get("ticker") else X.get(e.get("country"), 0)
        if x <= 0:
            continue
        holdings = [e["ticker"]] if e.get("ticker") else \
                   [t for t in weights if assets[t]["country_weights"].get(e["country"], 0) >= 0.05]
        watch.append({**e, "date": (date.fromisoformat(as_of) + timedelta(days=e["days"])).isoformat(),
                      "impact": x * e["severity"] * e["likelihood"] / (1 + e["days"] / 90),
                      "holdings": holdings, "source": mock.MOCK_SOURCE})
    watch = sorted(watch, key=lambda e: -e["impact"])[:5]

    # What-ifs: move half of a top contributor into the lowest-risk allowed fund (simulation, not advice)
    candidates = ["ZST.TO", "XBB.TO", "AGG", "XIU.TO", "ESGV", "SPY"]
    if prof["objective"] == "growth":
        candidates = ["XIU.TO", "ESGV", "SPY"]
    if prof["esg_importance"] == "high":
        candidates = [c for c in candidates if c != "SPY"]
    candidates = [c for c in candidates if c not in prof["excluded_tickers"]]
    R = {c: r["R"] for c, r in countries.items()}
    alt_G = {c: _asset_risk(_mock_asset_report(c, as_of), R) for c in candidates}
    whatifs = []
    for row in [r for r in by_holding if not uni[r["ticker"]]["asset_class"].startswith("etf")][:2]:
        t = row["ticker"]
        alt = min((c for c in candidates if c != t), key=alt_G.get, default=None)
        if not alt:
            continue
        move = weights[t] / 2
        # Deterministically re-score the simulated rebalanced portfolio
        sim_weights = dict(weights)
        sim_weights[t] = sim_weights[t] - move
        sim_weights[alt] = sim_weights.get(alt, 0.0) + move
        sim_assets = dict(assets)
        if alt not in sim_assets:
            sim_assets[alt] = _mock_asset_report(alt, as_of)
        sim_calc = calculate_portfolio_risk(
            weights=sim_weights,
            profile=prof,
            assets=sim_assets,
            countries=countries,
            scenarios=sets,
        )
        new = sim_calc["score"]
        r_t, r_a = _ret_1y(t, as_of), _ret_1y(alt, as_of)
        whatifs.append({"from": t, "to": alt, "move": move, "score_after": new, "delta": new - score,
                        "ret_from": r_t, "ret_to": r_a})

    top = by_holding[0]
    foreign = [c for c in by_country if c["iso3"] not in ("CAN", "USA")]
    obj_score = risk_calc.get("objective", score)
    conf_pct = risk_calc.get("confidence", 1.0) * 100.0
    summary = [
        f"The portfolio's risk score is {score:.0f} out of 100, which we classify as {_level(score)} "
        f"(objective portfolio risk: {obj_score:.0f}/100, confidence: {conf_pct:.0f}%)."
    ]
    if top["contribution"] > top["weight"] * 1.2:
        summary.append(f"{top['ticker']} is {top['weight']:.0%} of the portfolio but {top['contribution']:.0%} of the risk.")
    if foreign:
        f = foreign[0]
        summary.append(f"The largest exposure outside North America is {f['name']}, at {f['X']:.0%} of "
                       f"portfolio revenue, through {', '.join(f['holdings']) or 'several holdings'}.")
    if prof["horizon_years"] <= 5 and prof["risk_tolerance"] in ("low", "low_moderate"):
        summary.append(f"With a {prof['horizon_years']}-year horizon and a "
                       f"{prof['risk_tolerance'].replace('_', ' to ')} risk tolerance, a shock on "
                       f"{top['ticker']} would leave little time to recover.")
    if prof["esg_importance"] == "high":
        held = [t for t in weights if uni[t]["sector"] == "Energy"]
        if held:
            summary.append(f"{', '.join(held)} should be checked against the controversy exclusion; "
                           "filings alone do not settle it.")

    return {"as_of": as_of, "score": round(score, 1), "objective_score": round(obj_score, 1),
            "personalized_score": round(risk_calc.get("personalized", score), 1),
            "confidence": round(risk_calc.get("confidence", 1.0), 2),
            "risk_components": risk_calc.get("components", {}),
            "level": _level(score), "summary": summary,
            "by_holding": by_holding, "by_country": by_country, "watchlist": watch, "whatifs": whatifs,
            "checks": req.get("checks", []), "scenarios": scenario_impacts(sets, weights, assets),
            "scenario_sets": [{k: v for k, v in g.items() if k != "scenarios"} for g in sets],
            "highlight": req.get("scenario_country"),
            "assets": {t: {"weight": w, "country_weights": assets[t]["country_weights"]} for t, w in weights.items()},
            "mock": True}


# ---------- regenerate / highlight from the report page ----------
def _set_entry(scope: str, label: str, s, as_of: str) -> dict:
    return {"scope": scope, "label": label, "week": s.week, "computed_at": s.computed_at,
            "after_as_of": s.computed_at[:10] > as_of, "inputs": s.inputs,
            "scenarios": [x.model_dump() for x in s.scenarios]}


def _refresh_sync(run_id: str, country: str | None, force: bool) -> None:
    from pipelines.scenarios import run as sc
    rec = runs.get(run_id)
    r, as_of = rec["result"], rec["request"]["as_of"]
    ev = lambda **kw: runs.append_event(run_id, **kw)
    hook = lambda kind, status, id, label, detail="": ev(kind=kind, phase="regen", status=status,
                                                         id=id, label=label, detail=detail)
    current = {g["scope"]: g for g in r["scenario_sets"]}
    by_scope = {g["scope"]: [x for x in r["scenarios"] if x["scope"] == g["scope"]] for g in r["scenario_sets"]}
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as pool:   # global and country sets in parallel
        f_g = pool.submit(sc.generate, None, True, hook) if (force or "global" not in current) else None
        f_c = pool.submit(sc.generate, country, force, hook) if country else None
        g, c = (f_g.result() if f_g else None), (f_c.result() if f_c else None)
    sets = [_set_entry("global", "Global", g, as_of) if g else {**current["global"], "scenarios": by_scope["global"]}]
    if c:
        name = mock.COUNTRY_NAMES.get(country) or dict(_country_names()).get(country, country)
        sets.append(_set_entry(sc.scope_for(country), f"Most dangerous for {name}", c, as_of))
    weights = {t: a["weight"] for t, a in r["assets"].items()}
    r.update(scenarios=scenario_impacts(sets, weights, r["assets"]), highlight=country,
             scenario_sets=[{k: v for k, v in g.items() if k != "scenarios"} for g in sets])
    runs.set(run_id, result=r)


def _country_names():
    from web.personas import SCENARIO_COUNTRIES
    return SCENARIO_COUNTRIES


async def refresh_scenarios(run_id: str, country: str | None, force: bool) -> None:
    runs.set(run_id, scenario_job="running")
    runs.append_event(run_id, kind="regen", status="start", label="Scenarios",
                      detail="regenerating" if force else (country or "global"))
    try:
        await asyncio.to_thread(_refresh_sync, run_id, country, force)
        runs.set(run_id, scenario_job="done")
        runs.append_event(run_id, kind="regen", status="done", label="Scenarios")
    except Exception as e:
        runs.set(run_id, scenario_job="error")
        runs.append_event(run_id, kind="regen", status="error", detail=f"{type(e).__name__}: {e}")


# ---------- annexes: every source listed once, scenarios point to letters ----------
def annexes(r: dict) -> dict:
    """{"list": [{letter, name, url, retrieved, cited_by[]}], "by_url": {url: letter}}.
    Order: sources cited by scenarios (first citation first), then sources read but not cited, then data."""
    entries: dict[str, dict] = {}

    def add(url, name, retrieved=None):
        if url and url not in entries:
            entries[url] = {"name": name, "url": url, "retrieved": (retrieved or "")[:10], "cited_by": []}
        return entries.get(url)

    inputs = {i["url"]: i for g in r.get("scenario_sets", []) for i in g.get("inputs", []) if i.get("ok")}
    for s in r.get("scenarios", []):
        for e in s.get("evidence", []):
            if e.get("quote_verified") and e.get("url"):
                i = inputs.get(e["url"], {})
                a = add(e["url"], i.get("name") or e["source_id"].replace("_", " "), e.get("retrieved_at") or i.get("retrieved_at"))
                if s["name"] not in a["cited_by"]:
                    a["cited_by"].append(s["name"])
    for url, i in inputs.items():
        add(url, i["name"], i.get("retrieved_at"))
    add("https://finance.yahoo.com", "AlphaForge starter dataset: daily prices (Yahoo Finance) and USD/CAD (Bank of Canada)")
    out = []
    for n, a in enumerate(entries.values()):
        letter = chr(65 + n) if n < 26 else f"A{chr(65 + n - 26)}"
        out.append({**a, "letter": letter})
    return {"list": out, "by_url": {a["url"]: a["letter"] for a in out}}
