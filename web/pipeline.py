"""Run pipeline: what the server does after the user clicks Run analysis.

Agents and data, in order (every step writes progress events the page polls):
  1. Market data & filings    Yahoo prices + SEC country revenue (market-stress tools)
  2. Company disclosures      filings agent (Strands tool loop over each large holding's SEC filing)   ┐
  3. Market stress            stress indices + country FX/yield -> z-score features (no score of its own) ├ in parallel
  4. Scenarios                scenario agent, weekly                                                    ┘
  5. Country risk             geopolitical agent: (GPR + scenarios) x market-stress amplifier -> score (code)
  6. Portfolio risk           tools/risk_math (code) + risk agent explanation (LLM, numbers checked)
  7. Remediation              remediation agent proposes swaps; code validates and scores them
No synthetic data: where a source is missing, the report says so. Exposure without a filing is an equal
split over recorded countries (web/estimates.py), labelled "estimated".
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from tools import risk_math
from web import estimates, universe as U
from web.options import NAMES as _NAMES


class _Names(dict):
    """Country names, plus region rows reported by filings (REGION:EUROPE -> 'Europe (region)')."""
    def get(self, k, default=None):
        if isinstance(k, str) and k.startswith("REGION:"):
            from web.market import region_name
            return region_name(k)
        return super().get(k, default)


NAMES = _Names(_NAMES)
from web.store import runs

EXPOSURE_REASON = {"no_sec_ticker": "not an SEC filer", "no_annual_filing": "files a 40-F or no annual report with the SEC",
                   "no_country_revenue_found": "no geographic revenue table found in the filing",
                   "unsupported_fiscal_year_order": "revenue table not parseable", "error": "SEC lookup failed",
                   "not_applicable": "fund or crypto"}


def _asset_report(ticker: str, h: dict, as_of: str) -> dict:
    """Disclosed SEC revenue split when the filing gives one; otherwise the labelled estimate."""
    a = U.universe()[ticker]
    if h.get("exposures"):
        known = sum(h["exposures"].values())
        cw = {c: round(v, 4) for c, v in h["exposures"].items()}
        if known < 0.999:
            cw["Other"] = round(1 - known, 4)   # unreported share stays unattributed, never invented
        src = h["exposure_source"] or {}
        return {"ticker": ticker, "country_weights": cw, "estimated": False,
                "method": f"SEC filing, FY{h.get('fiscal_year') or '?'}",
                "source": {"name": f"{ticker} SEC annual filing ({src.get('locator', '')})".replace(" ()", ""),
                           "url": src.get("url", ""), "retrieved": src.get("retrieved_at", "")}}
    cw, basis = estimates.estimate(ticker, a)
    why = EXPOSURE_REASON.get(h.get("exposure_status"), h.get("exposure_status") or "")
    return {"ticker": ticker, "country_weights": cw, "estimated": True, "source": None,
            "method": f"Estimated: {basis}" + (f" ({why})" if why and why != "fund or crypto" else "")}


def _sec_problem(holdings: dict) -> str:
    """Name the cause when SEC lookups fail, instead of a silent 0/N (e.g. SEC_IDENTITY without an email)."""
    errs = [h.get("exposure_error") for h in holdings.values() if h.get("exposure_status") == "error"]
    return f" · SEC lookups failed: {errs[0]}" if errs and errs[0] else ""


def _ret_1y(series: dict | None) -> float | None:
    from web.market import price_stats
    return price_stats(series).get("ret") if series else None


def scenario_impacts(sets: list[dict], weights: dict, assets: dict) -> list[dict]:
    """What-if per scenario (not in the score): share of portfolio revenue in countries directly involved
    (intensity >= risk_math.INVOLVED). No probability, no impact weight: both are LLM judgements."""
    inv = risk_math.INVOLVED
    out = []
    for group in sets:
        for s in group["scenarios"]:
            per = {t: w * sum(cw for c, cw in assets[t]["country_weights"].items() if s["countries"].get(c, 0) >= inv)
                   for t, w in weights.items()}
            top = [t for t, v in sorted(per.items(), key=lambda kv: -kv[1]) if v > 0.005][:4]
            out.append({**s, "key": f"{group['scope']}/{s['id']}", "scope": group["scope"],
                        "group": group["label"], "exposure": round(sum(per.values()), 4), "holdings": top,
                        "involved": sorted(c for c, k in s["countries"].items() if k >= inv)})
    return out


def _scenario_sets(run_id: str, req: dict) -> list[dict]:
    """Scenario step: reuse this week's sets, otherwise run the scenario agent (saved to S3), then pick the
    set matching the analysis date. Runs in a worker thread because the agent is blocking."""
    from pipelines.scenarios import run as sc
    ev = lambda **kw: runs.append_event(run_id, **kw)
    hook = lambda kind, status, id, label, detail="": ev(kind=kind, phase="scenarios", status=status,
                                                         id=id, label=label, detail=detail)
    countries = [None] + ([req["scenario_country"]] if req.get("scenario_country") else [])
    label_of = lambda c: "Global" if not c else f"Most dangerous for {NAMES.get(c, c)}"

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
    from web import firms, market
    rec = runs.get(run_id)
    req = rec["request"]
    as_of = req["as_of"]
    weights = {h["ticker"]: h["weight"] for h in req["portfolio"]["holdings"]}
    uni = U.universe()
    ev = lambda **kw: runs.append_event(run_id, **kw)

    try:
        runs.set(run_id, status="running")

        # 1. Market data and filings: Yahoo prices + SEC country revenue per holding (parallel)
        ev(kind="phase", phase="assets", status="start", label="Market data & filings")

        def hold_ev(status, t, name, h):
            if status == "start":
                ev(kind="asset", phase="assets", status="start", id=t, label=name)
                return
            rep = _asset_report(t, h, as_of)
            top = sorted(((NAMES.get(c, c) if c.startswith("REGION:") else c, w) for c, w in rep["country_weights"].items()
                          if c != "Other"), key=lambda x: -x[1])[:3]
            tag = rep["method"] if not rep["estimated"] else "estimated (" + (
                EXPOSURE_REASON.get(h.get("exposure_status"), h.get("exposure_status") or "?")
                + (f": {h['exposure_error'][:80]}" if h.get("exposure_error") else "")) + ")"
            ev(kind="asset", phase="assets", status="done", id=t, label=name,
               detail=f"{tag} · " + (", ".join(f"{c} {w:.0%}" for c, w in top) or "no country") +
                      ("" if h.get("prices") else " · no prices"))
        holdings = await asyncio.to_thread(market.fetch_holdings, weights, uni, as_of, hold_ev)
        assets = {t: _asset_report(t, holdings[t], as_of) for t in weights}
        X: dict[str, float] = {}
        for t, w in weights.items():
            for c, cw in assets[t]["country_weights"].items():
                X[c] = X.get(c, 0) + w * cw
        ev(kind="phase", phase="assets", status="done", label="Market data & filings",
           detail=f"{sum(not a['estimated'] for a in assets.values())}/{len(assets)} exposures from SEC filings" + _sec_problem(holdings))

        # 2-4 in parallel: company disclosures (filings agent), market stress, scenarios
        def firms_step():
            ev(kind="phase", phase="firms", status="start", label="Company disclosures")

            def fev(status, t, sec_t, out, cached):
                name = uni[t]["name"]
                if status == "start":
                    ev(kind="asset", phase="firms", status="start", id=t, label=name)
                elif out["status"] == "ok":
                    ev(kind="asset", phase="firms", status="done", id=t, label=name,
                       detail=f"{out['n_claims']} claims, {out['n_verified']} verified" + (" · cached" if cached else ""))
                else:
                    ev(kind="asset", phase="firms", status="done", id=t, label=name,
                       detail="continues in background" if out["status"] == "pending" else "unavailable")
            res = firms.analyse(weights, uni, as_of, fev, {t: h.get("exposure_status") for t, h in holdings.items()})
            ev(kind="phase", phase="firms", status="done", label="Company disclosures",
               detail=f"{sum(r['status'] == 'ok' for r in res.values())}/{len(res)} companies read" +
                      (f" · {sum(r['status'] == 'pending' for r in res.values())} finishing in background"
                       if any(r["status"] == "pending" for r in res.values()) else ""))
            return res

        def market_step():
            ev(kind="phase", phase="market", status="start", label="Market stress")
            mev = lambda kind, status, id, label, detail="": ev(kind=kind, phase="market", status=status, id=id,
                                                                 label=market.NAMES.get(label, label), detail=detail)
            st = market.stress(weights, holdings, [c for c in sorted(X, key=lambda c: -X[c]) if c != "Other"], as_of, mev)
            view = market.summarise(st, holdings, weights, uni, NAMES)
            ev(kind="phase", phase="market", status="done", label="Market stress",
               detail=(f"stress level m {view['m']:+.2f} → amplifier ×{view['amplifier']:.2f}" if view["m"] is not None
                       else "stress indices unavailable, amplifier ×1.00") + f" · {len(view['countries'])} country indicators")
            return view

        def scen_step():
            ev(kind="phase", phase="scenarios", status="start", label="Scenarios")
            sets = _scenario_sets(run_id, req)
            ev(kind="phase", phase="scenarios", status="done", label="Scenarios",
               detail=" · ".join(f"{g['label']}: {len(g['scenarios'])} ({g['week']})" for g in sets) or "none available")
            return sets

        firm_res, stress_view, sets = await asyncio.gather(
            asyncio.to_thread(firms_step), asyncio.to_thread(market_step), asyncio.to_thread(scen_step))
        scen = scenario_impacts(sets, weights, {t: {"country_weights": a["country_weights"]} for t, a in assets.items()})

        # 5. Country hazard (geopolitical agent): GPR percentile per country. Candidate funds' countries too.
        from agents import geopolitical_agent
        from web import recommend
        prof = req["profile"]
        cands = recommend.candidates(prof, weights, uni)
        cand_assets = {c: _asset_report(c, {}, as_of) for c in cands}
        from web.market import region_members
        keys = {c for a in list(assets.values()) + list(cand_assets.values()) for c in a["country_weights"] if c != "Other"}
        regions = {k: region_members(k) for k in keys if k.startswith("REGION:")}
        countries_needed = sorted((keys - set(regions)) | {m for mem in regions.values() for m in mem})
        ev(kind="phase", phase="countries", status="start", label="Country risk")
        gev = lambda kind, status, id, label, detail="": ev(kind=kind, phase="countries", status=status, id=id,
                                                             label=label, detail=detail)
        countries, cmeta = await asyncio.to_thread(geopolitical_agent.assess, countries_needed, as_of, scen, {},
                                                   NAMES, X, gev)
        for k, mem in regions.items():   # region hazard = weighted mean of its main countries' hazard
            known = {m: w for m, w in mem.items() if countries.get(m, {}).get("g") is not None}
            gk = sum(w * countries[m]["g"] for m, w in known.items()) / sum(known.values()) if known else None
            countries[k] = {"g": gk, "gpr": None, "proxy": False, "scenarios": [], "region": True,
                            "method": "average of the region's main countries",
                            "driver": (f"Reported only as a region; hazard is the average of {', '.join(NAMES.get(m, m) for m in list(known)[:4])}"
                                       + ("…" if len(known) > 4 else "")) if known else "Reported only as a region; no GPR data"}
        for c in sorted((c for c in X if c != "Other"), key=lambda c: -X[c])[:12]:
            g = countries[c]["g"]
            ev(kind="country", phase="countries", status="done", id=c, label=NAMES.get(c, c),
               detail=f"GPR above {g:.0%} of its history · {countries[c]['method']}" if g is not None else "no data")
        ev(kind="phase", phase="countries", status="done", label="Country risk",
           detail=f"{sum(v['g'] is not None for v in countries.values())}/{len(countries)} countries with GPR data")

        # 6. Portfolio risk: formula v2, all in code
        ev(kind="phase", phase="risk", status="start", label="Portfolio risk")
        g = {c: v["g"] for c, v in countries.items() if v["g"] is not None and not v.get("region")}
        g["Other"] = sum(g.values()) / len(g) if g else 0.5   # unattributed revenue: mean of known countries
        g.update({k: v["g"] for k, v in countries.items() if v.get("region") and v["g"] is not None})
        A = stress_view["amplifier"]
        f = {t: risk_math.firm_flags((firm_res.get(t) or {}).get("channels")) if (firm_res.get(t) or {}).get("status") == "ok"
             else None for t in weights}
        parts = {t: risk_math.holding_score(assets[t]["country_weights"], g, A, f[t]) for t in weights}
        cand_parts = {c: risk_math.holding_score(cand_assets[c]["country_weights"], g, A, None) for c in cands}
        ps = risk_math.portfolio_score(weights, parts)
        score = ps["P"]
        report = build_report(req, weights, assets, countries, X, parts, ps, f, scen, sets, firm_res, stress_view, cmeta,
                              g["Other"])
        ev(kind="phase", phase="risk", status="done", label="Portfolio risk",
           detail=f"{score:.0f}/100 · " + {"clear": "no immediate danger", "watch": "watch", "act": "action suggested"}[report["verdict"]["status"]])

        # 7. Recommendations: deterministic, fitted to the profile; the risk agent only writes the summary
        ev(kind="phase", phase="remediation", status="start", label="Recommendations")
        report["remediation"] = recommend.propose(prof, weights, parts, cand_parts,
                                                  {c: a["country_weights"] for c, a in cand_assets.items()},
                                                  report["checks"], report["verdict"], uni, NAMES)
        report["style"] = recommend.style(prof)
        explain_facts = _explain_facts(req, report)

        def explain():
            from agents import risk_agent
            ev(kind="llm", phase="risk", status="start", id="bedrock", label="Explaining the risk", detail="risk agent")
            try:
                return risk_agent.explain(explain_facts)
            except Exception:
                return None
        sentences = await asyncio.to_thread(explain)
        if sentences:
            report["summary"], report["summary_by"] = sentences, "risk agent"
        if report["remediation"]:
            used = sorted({w["to"] for w in report["remediation"]})
            cand_prices = await asyncio.to_thread(_prices, used, as_of)
            for w in report["remediation"]:
                w["ret_from"] = _ret_1y((holdings.get(w["from"]) or {}).get("prices"))
                w["ret_to"] = _ret_1y(cand_prices.get(w["to"]))
        ev(kind="phase", phase="remediation", status="done", label="Recommendations",
           detail="nothing to change" if not report["remediation"] else f"{len(report['remediation'])} changes suggested")
        report["market"] = stress_view
        runs.set(run_id, status="done", result=report)
        ev(kind="run", status="done")
    except Exception as e:  # surface the error on the page instead of hanging
        runs.set(run_id, status="error", error=f"{type(e).__name__}: {e}")
        ev(kind="run", status="error", detail=str(e))


# ---------- what each agent extracts, and what the risk formula uses ----------
# status: "used" = a term of risk formula v2 (tools/risk_math); "context" = shown, never scored (LLM judgement
# or not yet validated); "candidate" = could enter the formula once measured mechanically.
FORMULA_INPUTS = [
    {"agent": "Market data & filings", "field": "Country revenue split w_ic (SEC 10-K / 20-F tables, parsed by code)", "term": "X_c", "status": "used"},
    {"agent": "Market data & filings", "field": "1-year return, volatility, max drawdown", "term": "profile volatility check", "status": "used"},
    {"agent": "Market data & filings", "field": "Beta of returns to GPR changes", "term": "holding sensitivity", "status": "candidate"},
    {"agent": "Filings agent", "field": "Risk channels with a verified verbatim quote (code-checked)", "term": "f_i = channels / 8", "status": "used"},
    {"agent": "Filings agent", "field": "Severity 0–5 and confidence per claim", "term": "—", "status": "context"},
    {"agent": "Filings agent", "field": "Political-risk word counts on the filing (Hassan et al. PRisk)", "term": "replaces f_i", "status": "candidate"},
    {"agent": "Market stress", "field": "OFR FSI, STLFSI4, VIX: z vs. 3-year window", "term": "m → A", "status": "used"},
    {"agent": "Market stress", "field": "Country FX / 10y-yield 1-month move", "term": "—", "status": "context"},
    {"agent": "Market stress", "field": "Economic policy uncertainty (EPU) by country", "term": "second hazard index", "status": "candidate"},
    {"agent": "Scenarios", "field": "Countries directly involved, with verified quotes", "term": "what-if E_s (not in P)", "status": "used"},
    {"agent": "Scenarios", "field": "Likelihood, impact, intensity", "term": "—", "status": "context"},
    {"agent": "Scenarios", "field": "Prediction-market price for the event (Polymarket / Kalshi)", "term": "probability for E_s", "status": "candidate"},
    {"agent": "Country risk", "field": "GPR index percentile vs. the country's own past months", "term": "g_c", "status": "used"},
    {"agent": "Country risk", "field": "Driver line (LLM, from the computed facts)", "term": "—", "status": "context"},
    {"agent": "Profile", "field": "Risk level → tolerance; horizon, objective, ESG, exclusions → choice of fund", "term": "verdict, swaps", "status": "used"},
]


def _method(stress_view: dict) -> dict:
    return {"gamma": risk_math.GAMMA, "lam": risk_math.LAMBDA_FIRM, "m": stress_view.get("m"),
            "A": stress_view.get("amplifier", 1.0), "tolerance": risk_math.TOLERANCE,
            "involved": risk_math.INVOLVED, "inputs": FORMULA_INPUTS}


# ---------- helpers ----------
def _prices(tickers: list[str], as_of: str) -> dict:
    from datetime import date as _d
    from tools.market_data import get_price_history
    out = {}
    for t in tickers:
        try:
            out[t] = get_price_history(t, min(as_of, _d.today().isoformat()), 365)
        except Exception:
            out[t] = None
    return out


def _explain_facts(req: dict, r: dict) -> dict:
    p = req["profile"]
    return {"score": round(r["score"]), "level": r["level"], "verdict": r["verdict"]["status"],
            "tolerance": r["verdict"]["tolerance"], "market_amplifier": round(r["market_A"], 2),
            "profile": {k: p.get(k) for k in ("horizon_years", "risk_level", "objective_level", "esg_importance",
                                               "excluded_themes", "interests", "notes")},
            "top_holdings": [{"ticker": h["ticker"], "weight": round(h["weight"], 3), "points": round(h["points"], 1)}
                             for h in r["by_holding"][:4]],
            "top_countries": [{"country": c["name"], "revenue_share": round(c["X"], 3), "points": round(c["points"], 1),
                               "gpr_percentile": round(100 * c["g"]) if c["g"] is not None else None}
                              for c in r["by_country"][:4]],
            "conflicts": [c["text"] for c in r["checks"]],
            "largest_what_if": [{"name": s["name"], "revenue_in_involved_countries": round(s["exposure"], 2)}
                                for s in sorted(r["scenarios"], key=lambda s: -s["exposure"])[:2]],
            "changes_suggested": [f"{w['from']} -> {w['to']}" for w in r.get("remediation", [])]}


def build_report(req, weights, assets, countries, X, parts, ps, f, scen, sets, firm_res, stress_view, cmeta,
                 g_other: float = 0.5) -> dict:
    uni, as_of, prof = U.universe(), req["as_of"], req["profile"]
    score, A = ps["P"], stress_view["amplifier"]
    by_holding = sorted(({"ticker": t, "name": uni[t]["name"], "weight": w, "G": round(parts[t]["G"], 1),
                          "points": ps["by_holding"][t], "firm_points": w * parts[t]["firm"], "f": f[t],
                          "contribution": ps["by_holding"][t] / score if score else 0,
                          "method": assets[t]["method"], "estimated": assets[t].get("estimated", True),
                          "channels": (firm_res.get(t) or {}).get("channels"),
                          "source_url": (assets[t].get("source") or {}).get("url")} for t, w in weights.items()),
                        key=lambda r: -r["points"])
    by_country = sorted(({"iso3": c, "name": NAMES.get(c, c), "X": round(x, 4), "g": countries[c]["g"],
                          "points": ps["by_country"].get(c, 0.0), "proxy": countries[c]["proxy"],
                          "driver": countries[c]["driver"], "method": countries[c]["method"],
                          "gpr": countries[c]["gpr"], "scenarios": countries[c]["scenarios"],
                          "holdings": [t for t in weights if assets[t]["country_weights"].get(c, 0) >= 0.05]}
                         for c, x in X.items() if c != "Other" and c in countries),
                        key=lambda r: -r["points"])
    if ps["by_country"].get("Other", 0) > 0.05:   # revenue no filing attributes: shown so the points add up
        by_country.append({"iso3": "Other", "name": "Unattributed revenue", "X": round(X.get("Other", 0), 4),
                           "g": g_other, "points": ps["by_country"]["Other"], "proxy": False,
                           "driver": "Revenue the filings do not split by country; uses the mean hazard of the known countries",
                           "method": "mean of known countries", "gpr": None, "scenarios": [], "holdings": []})

    # Signposts: early warnings of the scenarios with the most revenue in directly involved countries
    seen, signposts = set(), []
    for s in sorted(scen, key=lambda s: -s["exposure"]):
        if s["name"] in seen or s["exposure"] < 0.01:
            continue
        seen.add(s["name"])
        for sp in s.get("signposts", [])[:2]:
            signposts.append({"text": sp, "scenario": s["name"], "key": s["key"], "exposure": s["exposure"],
                              "holdings": s["holdings"],
                              "evidence": [e for e in s.get("evidence", []) if e.get("quote_verified")]})
        if len(signposts) >= 5:
            break

    checks = list(req.get("checks", []))
    for c in prof.get("avoid_countries", []):
        if X.get(c, 0) >= 0.005:
            via = [t for t in weights if assets[t]["country_weights"].get(c, 0) >= 0.02]
            checks.append({"ticker": c, "text": f"{X[c]:.1%} of portfolio revenue comes from {NAMES.get(c, c)}, "
                                                f"a country the profile wants to limit" + (f" (through {', '.join(via)})." if via else ".")})

    v = risk_math.verdict(score, prof.get("risk_level", 3), A, len(checks))
    only_market = not v["clear"] and all(t["ok"] for t in v["tests"] if "stress" not in t["name"])
    v["status"] = "clear" if v["clear"] else "watch" if only_market else "act"

    top = by_holding[0]
    lvl = risk_math.level(score)
    summary = [f"The geopolitical risk score is {score:.0f} out of 100 ({lvl}); 50 is a typical month for the "
               f"countries this portfolio earns in. The profile's tolerance is {v['tolerance']}."]
    if v["status"] == "clear":
        summary.append("No immediate danger for this profile: every test below passes, so nothing needs to change.")
    named = [c for c in by_country if c["iso3"] != "Other"]
    if named:
        c = named[0]
        summary.append(f"The largest contributor is {c['name']}: {c['X']:.0%} of revenue, with geopolitical risk "
                       f"higher than {c['g']:.0%} of its past months, adding {c['points']:.1f} points.")
    if top["contribution"] > top["weight"] * 1.2:
        summary.append(f"{top['ticker']} is {top['weight']:.0%} of the portfolio but {top['contribution']:.0%} of the score.")

    return {"version": 2, "as_of": as_of, "score": round(score, 1), "level": lvl, "summary": summary, "summary_by": "code",
            "verdict": v, "market_A": A, "firm_points": ps["firm"],
            "by_holding": by_holding, "by_country": by_country, "signposts": signposts[:5],
            "checks": checks, "scenarios": scen,
            "scenario_sets": [{k: v for k, v in g.items() if k != "scenarios"} for g in sets],
            "highlight": req.get("scenario_country"),
            "assets": {t: {"weight": w, "country_weights": assets[t]["country_weights"]} for t, w in weights.items()},
            "exposure_sources": {t: assets[t]["source"] for t in weights if assets[t].get("source")},
            "firms": firm_res, "country_meta": cmeta, "method": _method(stress_view),
            "n_estimated": sum(a["estimated"] for a in assets.values())}


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
        name = NAMES.get(country, country)
        sets.append(_set_entry(sc.scope_for(country), f"Most dangerous for {name}", c, as_of))
    weights = {t: a["weight"] for t, a in r["assets"].items()}
    r.update(scenarios=scenario_impacts(sets, weights, r["assets"]), highlight=country,
             scenario_sets=[{k: v for k, v in g.items() if k != "scenarios"} for g in sets])
    runs.set(run_id, result=r)


def _country_names():
    from web.options import COUNTRIES
    return COUNTRIES


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
    for h in r.get("by_holding", []):      # company filings behind disclosed exposures
        src = (r.get("exposure_sources") or {}).get(h["ticker"])
        if src and src.get("url"):
            a = add(src["url"], src["name"], src.get("retrieved"))
            a["cited_by"].append(f"Exposure of {h['ticker']}")
    for m in (r.get("market") or {}).get("sources", []):
        a = add(m["url"], m["name"], m.get("retrieved"))
        for c in m["cited_by"]:
            if c not in a["cited_by"]:
                a["cited_by"].append(c)
    for t, f in (r.get("firms") or {}).items():   # filings read by the filings agent
        if f.get("filing") and f["filing"].get("url"):
            a = add(f["filing"]["url"], f["filing"]["name"], f["filing"].get("retrieved"))
            if f"Disclosures of {t}" not in a["cited_by"]:
                a["cited_by"].append(f"Disclosures of {t}")
    g = (r.get("country_meta") or {}).get("gpr")
    if g:
        a = add(g["url"], g["name"], g.get("retrieved"))
        a["cited_by"].append("Country risk")
    out = []
    for n, a in enumerate(entries.values()):
        letter = chr(65 + n) if n < 26 else f"A{chr(65 + n - 26)}"
        out.append({**a, "letter": letter})
    return {"list": out, "by_url": {a["url"]: a["letter"] for a in out}}
