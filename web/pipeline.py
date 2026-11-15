"""Run pipeline: what the server does after the user clicks Run analysis.

Agents and data, in order (every step writes progress events the page polls):
  1. Market data & filings    Yahoo prices + exposure agent (country revenue split, tiered fallback chain)
  2. Company disclosures      filings agent (f_i) + filing-risk agent (Risk Factors), largest holdings    ┐
  3. Scenarios                scenario agent, weekly                                                      │ parallel
  4. Macro & sources          country risk agent (World Bank -> macro M_c) + source agent                 ┘
  5. Country risk             geopolitical agent: GPR percentile g_c (code) + drivers; geopolitical claims agent
  6. Portfolio risk           Cedric's two-stage formula (web/scoring.py) + risk agent explanation (numbers checked)
  7. Recommendations          web/recommend.py (code) + remediation agent alternatives (validated, re-scored)
LLM output is shown as context and never enters the score; numbers it writes are checked against the facts.
No mock data: where a source is missing, the report says so. Every holding's country split is tagged with the
tier that produced it (agents/exposure_agent.py: XBRL, filing text, last year's filing, sector / home-bias prior,
returns-based), so the report shows how confident each split is.
"""
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from agents import (country_risk_agent, exposure_agent, geopolitical_agent, geopolitical_claims_agent,
                    remediation_agent, risk_agent)
from pipelines import scenarios as sc
from tools import gpr, market_data, risk_math
from web import firms, market, profile, recommend, scoring, universe as U
from web.options import NAMES as _NAMES
from web.store import runs

log = logging.getLogger(__name__)


class _Names(dict):
    """Country names, plus region rows reported by filings (REGION:EUROPE -> 'Europe (region)')."""
    def get(self, k, default=None):
        if isinstance(k, str) and k.startswith("REGION:"):
            return market.region_name(k)
        return super().get(k, default)


NAMES = _Names(_NAMES)

def _asset_report(ticker: str, h: dict, as_of: str, weight: float | None = None) -> dict:
    """The exposure agent's split; a failure falls back to the prior alone, never stops the run."""
    try:
        return exposure_agent.split(ticker, U.universe()[ticker], h, as_of, weight)
    except Exception as e:
        return {"ticker": ticker, "country_weights": {"Other": 1.0}, "estimated": True, "source": None, "quotes": [],
                "tier": {"code": "none", "label": "no country", "lambda": 0.0, "prior": "none", "detail": str(e)[:120]},
                "method": f"exposure agent failed: {type(e).__name__}: {str(e)[:120]}"}


def _sec_problem(holdings: dict) -> str:
    """Name the cause when SEC lookups fail, instead of a silent 0/N (e.g. SEC_IDENTITY without an email)."""
    blocked = [h for h in holdings.values() if h.get("exposure_status") == "blocked"]
    if blocked:
        return f" · SEC refused {len(blocked)} requests (HTTP {blocked[0].get('http_status')}): check SEC_IDENTITY"
    errs = [h.get("exposure_error") for h in holdings.values() if h.get("exposure_status") == "error"]
    return f" · SEC lookups failed: {errs[0]}" if errs and errs[0] else ""


def _ret_1y(series: dict | None) -> float | None:
    return market.price_stats(series).get("ret") if series else None


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

        # Each holding: fetch (Yahoo + SEC XBRL), then the exposure agent's split. Holdings with a filing table run
        # first and join the peer library; the others follow, in parallel, with a bounded filing-text pass.

        def finish(t, rep, h):
            top = sorted(((c, w) for c, w in rep["country_weights"].items() if c != "Other"), key=lambda x: -x[1])[:3]
            ev(kind="asset", phase="assets", status="done", id=t, label=uni[t]["name"],
               detail=f"{rep.get('step', '?')} · {rep['tier']['label']} · " + (", ".join(f"{c} {w:.0%}" for c, w in top) or "no country") +
                      ("" if h.get("prices") else " · no prices"))

        def fetch_one(t):
            ev(kind="asset", phase="assets", status="start", id=t, label=uni[t]["name"])
            h = market.fetch_holding(t, uni[t], as_of)
            if h.get("exposures") and not h.get("stale"):     # tier 1: no LLM, record it for the peers at once
                rep = _asset_report(t, h, as_of, weights[t])
                finish(t, rep, h)
                return t, h, rep
            return t, h, None

        def split_one(t, h):
            rep = _asset_report(t, h, as_of, weights[t])
            finish(t, rep, h)
            return t, rep

        def assets_step():
            with ThreadPoolExecutor(max_workers=6) as pool:
                fetched = list(pool.map(fetch_one, list(weights)))
                holdings = {t: h for t, h, _ in fetched}
                assets = {t: rep for t, _, rep in fetched if rep}
                assets.update(pool.map(lambda t: split_one(t, holdings[t]), [t for t in weights if t not in assets]))
            return holdings, assets

        holdings, assets = await asyncio.to_thread(assets_step)
        X: dict[str, float] = {}
        for t, w in weights.items():
            for c, cw in assets[t]["country_weights"].items():
                X[c] = X.get(c, 0) + w * cw
        tiers = [a["tier"]["code"] for a in assets.values()]
        ev(kind="phase", phase="assets", status="done", label="Market data & filings",
           detail=" · ".join(f"{tiers.count(k)} {exposure_agent.LABEL[k]}" for k in exposure_agent.LABEL if k in tiers)
                  + _sec_problem(holdings))
        steps = [a.get("step") or "?" for a in assets.values()]
        log.info("exposure steps: %s", {k: steps.count(k) for k in sorted(set(steps))})

        # 2-4 in parallel: company disclosures (filings agents), scenarios, macro & sources
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

        def scen_step():
            ev(kind="phase", phase="scenarios", status="start", label="Scenarios")
            sets = _scenario_sets(run_id, req)
            ev(kind="phase", phase="scenarios", status="done", label="Scenarios",
               detail=" · ".join(f"{g['label']}: {len(g['scenarios'])} ({g['week']})" for g in sets) or "none available")
            return sets

        # Candidate funds' countries are needed too: recommendations are scored with the same inputs.
        prof = req["profile"]
        cands = recommend.candidates(prof, weights, uni)
        cand_assets = {c: _asset_report(c, {}, as_of) for c in cands}
        countries_needed = sorted({c for a in list(assets.values()) + list(cand_assets.values())
                                   for c in a["country_weights"] if c != "Other"})

        def macro_step():
            ev(kind="phase", phase="macro", status="start", label="Macro & sources")
            top = [c for c in sorted(X, key=lambda c: -X[c]) if c != "Other" and not c.startswith("REGION:")][:MACRO_TOP_N]
            mev = lambda kind, status, id, label, detail="": ev(kind=kind, phase="macro", status=status, id=id,
                                                                 label=label, detail=detail)
            out, meta = country_risk_agent.assess(countries_needed, as_of, NAMES, mev, detail_for=top)
            ev(kind="phase", phase="macro", status="done", label="Macro & sources",
               detail=f"{sum(v['macro'] is not None for v in out.values())}/{len(out)} countries with World Bank data · "
                      f"{sum(len(v['sources']) for v in out.values())} official sources reachable")
            return {"countries": out, "meta": meta, "top": top}

        firm_res, sets, macro = await asyncio.gather(
            asyncio.to_thread(firms_step), asyncio.to_thread(scen_step), asyncio.to_thread(macro_step))
        scen = scenario_impacts(sets, weights, {t: {"country_weights": a["country_weights"]} for t, a in assets.items()})

        # 5. Country hazard (geopolitical agent): GPR percentile per country, candidate funds' countries included.
        ev(kind="phase", phase="countries", status="start", label="Country risk")
        gev = lambda kind, status, id, label, detail="": ev(kind=kind, phase="countries", status=status, id=id,
                                                             label=label, detail=detail)
        countries, cmeta = await asyncio.to_thread(geopolitical_agent.assess, countries_needed, as_of, scen, {},
                                                   NAMES, X, gev)
        for c in sorted((c for c in X if c != "Other"), key=lambda c: -X[c])[:12]:
            g = countries[c]["g"]
            ev(kind="country", phase="countries", status="done", id=c, label=NAMES.get(c, c),
               detail=f"GPR above {g:.0%} of its history · {countries[c]['method']}" if g is not None else "no data")
        top_c = [c for c in sorted(X, key=lambda c: -X[c]) if countries.get(c, {}).get("gpr")][:CLAIMS_TOP_N]
        gpr_claims = await asyncio.to_thread(_gpr_claims, top_c, as_of, gev)
        ev(kind="phase", phase="countries", status="done", label="Country risk",
           detail=f"{sum(v['g'] is not None for v in countries.values())}/{len(countries)} countries with GPR data · "
                  f"{sum(len(c['claims']) for c in gpr_claims.values())} verified GPR claims")

        # 6. Portfolio risk: Cedric's two-stage formula on measured inputs (web/scoring.py), all in code
        ev(kind="phase", phase="risk", status="start", label="Portfolio risk")
        g = {c: v["g"] for c, v in countries.items() if v["g"] is not None}
        M = {c: v["macro"]["score"] / 100 for c, v in macro["countries"].items() if v["macro"]}
        f = {t: risk_math.firm_flags((firm_res.get(t) or {}).get("channels")) if (firm_res.get(t) or {}).get("status") == "ok"
             else None for t in weights}
        tol = scoring.tolerance(prof)
        cw = {t: a["country_weights"] for t, a in {**assets, **cand_assets}.items()}
        hold = {t: scoring.holding(cw[t], M, g, f[t], tol) for t in weights}
        cand = {c: scoring.holding(cw[c], M, g, None, tol) for c in cands}
        ctry = {c: scoring.country(c, M, g, tol) for c in set(X) - {"Other"}}
        port = scoring.portfolio(weights, cw, M, g, f, tol)
        score_fn = lambda w: scoring.portfolio(w, cw, M, g, f, tol)["objective"]
        report = build_report(req, weights, assets, countries, X, hold, ctry, port, tol, M, f, scen, sets, firm_res, cmeta)
        report["macro"], report["gpr_claims"] = macro, gpr_claims
        ev(kind="phase", phase="risk", status="done", label="Portfolio risk",
           detail=f"concern {port['personalized']:.0f}/100 · objective {port['objective']:.0f} · "
                  + {"clear": "no immediate danger", "act": "action suggested"}[report["verdict"]["status"]])

        # 7. Recommendations: deterministic, fitted to the profile; the risk agent only writes the summary
        ev(kind="phase", phase="remediation", status="start", label="Recommendations")
        parts = {t: _parts(hold[t], cw[t], ctry) for t in weights}
        cand_parts = {c: _parts(cand[c], cw[c], ctry) for c in cands}
        report["remediation"] = recommend.propose(prof, weights, parts, cand_parts,
                                                  {c: a["country_weights"] for c, a in cand_assets.items()},
                                                  report["checks"], report["verdict"], uni, NAMES, score_fn)
        report["profile_outcome"] = profile.assess_swaps(prof, weights, report["remediation"], uni, as_of, cw, NAMES)
        report["style"] = recommend.style(prof)
        explain_facts = _explain_facts(req, report)

        def explain():
            ev(kind="llm", phase="risk", status="start", id="bedrock", label="Explaining the risk", detail="risk agent")
            try:
                return risk_agent.explain(explain_facts)
            except Exception:
                return None
        sentences = await asyncio.to_thread(explain)
        if sentences:   # the verdict section below carries the all-clear: no need to repeat it here
            report["summary"], report["summary_by"] = sentences, "risk agent"
        report["agent_swaps"] = None
        report["agent_status"] = "not_needed" if report["verdict"]["status"] != "act" else "no_eligible_funds"
        agent_cand_parts = {c: p for c, p in cand_parts.items()
                            if recommend._fit(c, prof, uni, p["G"], cand_assets[c]["country_weights"]) is not None}
        if report["verdict"]["status"] == "act" and agent_cand_parts:
            rf = remediation_agent.facts(prof, weights, parts, agent_cand_parts, port["objective"],
                                         report["verdict"]["tolerance"], report["remediation"], uni, report, cand_assets)
            ev(kind="llm", phase="remediation", status="start", id="bedrock", label="Alternative swaps", detail="remediation agent")
            try:
                report["agent_swaps"] = await asyncio.to_thread(remediation_agent.propose, rf, weights, parts, agent_cand_parts,
                                                                report["remediation"], score_fn)
                for swap in report["agent_swaps"]:
                    profile.assess_swaps(prof, weights, [swap], uni, as_of, cw, NAMES)
                report["agent_status"] = "completed"
                detail = f"{len(report['agent_swaps'])} kept after validation"
            except Exception as e:
                report["agent_status"] = "unavailable"
                detail = f"unavailable: {type(e).__name__}: {str(e)[:120]}"
            ev(kind="llm", phase="remediation", status="done", id="bedrock", label="Alternative swaps", detail=detail)
        if report["remediation"]:
            used = sorted({w["to"] for w in report["remediation"]})
            cand_prices = await asyncio.to_thread(_prices, used, as_of)
            for w in report["remediation"]:
                w["ret_from"] = _ret_1y((holdings.get(w["from"]) or {}).get("prices"))
                w["ret_to"] = _ret_1y(cand_prices.get(w["to"]))
        ev(kind="phase", phase="remediation", status="done", label="Recommendations",
           detail=("nothing to change" if not report["remediation"] else f"{len(report['remediation'])} changes suggested")
                  + (f" · {len(report['agent_swaps'])} agent alternatives" if report["agent_swaps"] else ""))
        runs.set(run_id, status="done", result=report)
        ev(kind="run", status="done")
    except Exception as e:  # surface the error on the page instead of hanging
        runs.set(run_id, status="error", error=f"{type(e).__name__}: {e}")
        ev(kind="run", status="error", detail=str(e))


MACRO_TOP_N = 8     # countries read by the country risk agent (largest revenue exposure)
CLAIMS_TOP_N = 3    # countries read by the geopolitical claims agent


def _gpr_claims(countries: list[str], as_of: str, emit) -> dict:
    """Geopolitical claims agent on the most exposed countries, in parallel; failures are recorded per country."""

    def one(c):
        emit("llm", "start", c, f"GPR claims · {NAMES.get(c, c)}", "geopolitical claims agent")
        try:
            r = geopolitical_claims_agent.run(c, as_of, gpr.table())
            out = {"claims": [x.model_dump() for x in r.claims] if r else [], "summary": r.summary if r else "", "error": None}
        except Exception as e:
            out = {"claims": [], "summary": "", "error": f"{type(e).__name__}: {str(e)[:120]}"}
        emit("llm", "done", c, f"GPR claims · {NAMES.get(c, c)}", out["error"] or f"{len(out['claims'])} verified claims")
        return c, out
    with ThreadPoolExecutor(max_workers=3) as pool:
        return dict(pool.map(one, countries))


# ---------- what each agent extracts, and what the risk formula uses ----------
# status: "used" = an input of the risk formula (web/scoring.py); "context" = shown, never scored (LLM judgement
# or not yet validated); "candidate" = could enter the formula once measured mechanically.
FORMULA_INPUTS = [
    {"agent": "Market data & filings", "field": "Country revenue split w_ic (SEC tables, parsed by code)", "term": "X_c, weights of A1 and A2", "status": "used"},
    {"agent": "Market data & filings", "field": "1-year return, volatility", "term": "profile volatility check", "status": "used"},
    {"agent": "Filings agent", "field": "Risk channels with a verified verbatim quote (code-checked)", "term": "A3: f_i = channels / 8", "status": "used"},
    {"agent": "Filings agent", "field": "Severity 0–5 and confidence per claim", "term": "—", "status": "context"},
    {"agent": "Filing-risk agent", "field": "Every risk in the Risk Factors section, quotes verified; severity, confidence", "term": "—", "status": "context"},
    {"agent": "Country risk agent", "field": "World Bank macro and banking indicators → macro score (tools/risk_calculator)", "term": "A1: M_c", "status": "used"},
    {"agent": "Country risk", "field": "GPR index percentile vs. the country's own past months", "term": "A2: g_c", "status": "used"},
    {"agent": "Country risk", "field": "Driver line (LLM, from the computed facts)", "term": "—", "status": "context"},
    {"agent": "Geopolitical claims agent", "field": "Claims on the GPR history, quotes verified against the data", "term": "—", "status": "context"},
    {"agent": "Scenarios", "field": "Countries directly involved, with verified quotes", "term": "what-if E_s (not in the score)", "status": "context"},
    {"agent": "Scenarios", "field": "Likelihood, impact, intensity", "term": "—", "status": "context"},
    {"agent": "Source agent", "field": "Reachable official sources per country", "term": "—", "status": "context"},
    {"agent": "Remediation agent", "field": "Alternative swaps, validated and re-scored by code", "term": "—", "status": "context"},
    {"agent": "Profile", "field": "Risk level → tolerance t; horizon, objective, ESG, exclusions → choice of fund", "term": "t, verdict, swaps", "status": "used"},
]


def _method(tol: float) -> dict:
    p = scoring.P
    return {"params": {k: getattr(p, k) for k in ("lam", "w_S", "w_G", "alpha", "eta", "tau", "kappa", "k", "a", "b", "mu")},
            "t": tol, "rho": scoring.comfort(tol), "tolerance_map": scoring.RISK_LEVEL_TOLERANCE,
            "involved": risk_math.INVOLVED, "inputs": FORMULA_INPUTS}


def _parts(h: dict, cw: dict, ctry: dict) -> dict:
    """Shape a holding's score for web/recommend.py: its risk, and which country drives it."""
    return {"G": h["objective"], "countries": {c: w * ctry[c]["objective"] for c, w in cw.items() if c in ctry}}


# ---------- helpers ----------
def _prices(tickers: list[str], as_of: str) -> dict:
    out = {}
    for t in tickers:
        try:
            out[t] = market_data.get_price_history(t, min(as_of, date.today().isoformat()), 365)
        except Exception:
            out[t] = None
    return out


def _explain_facts(req: dict, r: dict) -> dict:
    p = req["profile"]
    return {"concern_score": round(r["score"]), "objective_risk": round(r["objective"]), "level": r["level"],
            "verdict": r["verdict"]["status"], "comfort_level": r["verdict"]["tolerance"],
            "inputs_0_to_100": {k: round(100 * v) for k, v in r["inputs"].items() if v is not None},
            "profile": {k: p.get(k) for k in ("horizon_years", "risk_level", "objective_level", "esg_importance",
                                               "excluded_themes", "interests", "notes")},
            "top_holdings": [{"ticker": h["ticker"], "weight": round(h["weight"], 3), "holding_risk": round(h["R"])}
                             for h in r["by_holding"][:4]],
            "top_countries": [{"country": c["name"], "revenue_share": round(c["X"], 3), "country_risk": round(c["R"]),
                               "gpr_percentile": round(100 * c["g"]) if c["g"] is not None else None}
                              for c in r["by_country"][:4]],
            "conflicts": [c["text"] for c in r["checks"]],
            "largest_what_if": [{"name": s["name"], "revenue_in_involved_countries": round(s["exposure"], 2)}
                                for s in sorted(r["scenarios"], key=lambda s: -s["exposure"])[:2]],
            "changes_suggested": [f"{w['from']} -> {w['to']}" for w in r.get("remediation", [])]}


def build_report(req, weights, assets, countries, X, hold, ctry, port, tol, M, f, scen, sets, firm_res, cmeta) -> dict:
    uni, as_of, prof = U.universe(), req["as_of"], req["profile"]
    wr = sum(w * hold[t]["objective"] for t, w in weights.items()) or 1.0
    by_holding = sorted(({"ticker": t, "name": uni[t]["name"], "weight": w, "R": hold[t]["objective"],
                          "concern": hold[t]["personalized"], "confidence": hold[t]["confidence"],
                          "A": [hold[t][k] for k in ("A1", "A2", "A3")], "f": f[t],
                          "share": w * hold[t]["objective"] / wr,
                          "method": assets[t]["method"], "estimated": assets[t].get("estimated", True),
                          "tier": assets[t].get("tier"), "channels": (firm_res.get(t) or {}).get("channels"),
                          "source_url": (assets[t].get("source") or {}).get("url")} for t, w in weights.items()),
                        key=lambda r: -r["weight"] * r["R"])
    by_country = sorted(({"iso3": c, "name": NAMES.get(c, c), "X": round(x, 4), "g": countries[c]["g"],
                          "M": M.get(c), "R": ctry[c]["objective"], "proxy": countries[c].get("proxy", False),
                          "driver": countries[c]["driver"], "method": countries[c]["method"],
                          "gpr": countries[c].get("gpr"), "scenarios": countries[c].get("scenarios", []),
                          "holdings": [t for t in weights if assets[t]["country_weights"].get(c, 0) >= 0.05]}
                         for c, x in X.items() if c != "Other" and c in countries and c in ctry),
                        key=lambda r: -r["X"] * r["R"])
    unattributed = X.get("Other", 0.0)

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
            checks.append({"id": f"country:{c}", "ticker": c, "text": f"{X[c]:.1%} of portfolio revenue comes from {NAMES.get(c, c)}, "
                                                f"a country the profile wants to limit" + (f" (through {', '.join(via)})." if via else ".")})

    v = scoring.verdict(port["objective"], tol, len(checks))
    lvl = scoring.level(port["personalized"])
    summary = []   # [{title, text}]: short labelled points (the risk agent rewrites them when it can)
    if by_country:
        c = by_country[0]
        summary.append({"title": "Where it comes from", "text":
                        f"{c['name']}: {c['X']:.0%} of revenue" + (f", GPR above {c['g']:.0%} of its past months."
                                                                   if c["g"] is not None else ".")})
    top = by_holding[0]
    summary.append({"title": "Holdings that matter", "text":
                    f"{top['ticker']}: {top['weight']:.0%} of the portfolio, {top['share']:.0%} of the weighted risk."})
    summary.append({"title": "Fit with the profile", "text":
                    f"Objective risk {port['objective']:.1f} against a comfort level of {v['tolerance']:g}."})

    return {"version": 3, "as_of": as_of, "score": port["personalized"], "objective": port["objective"],
            "confidence": port["confidence"], "inputs": {"A1": port["A1"], "A2": port["A2"], "A3": port["A3"]},
            "conf": port["conf"], "level": lvl, "summary": summary, "summary_by": "code", "verdict": v,
            "by_holding": by_holding, "by_country": by_country, "unattributed": unattributed,
            "signposts": signposts[:5], "checks": checks, "scenarios": scen,
            "scenario_sets": [{k: v for k, v in g.items() if k != "scenarios"} for g in sets],
            "highlight": req.get("scenario_country"),
            "assets": {t: {"weight": w, "country_weights": assets[t]["country_weights"]} for t, w in weights.items()},
            "exposure_sources": {t: assets[t]["source"] for t in weights if assets[t].get("source")},
            "firms": firm_res, "country_meta": cmeta, "method": _method(tol),
            "exposure_status": {k: sum(1 for t in weights if (assets[t].get("status") or "") == k)
                                for k in {assets[t].get("status") for t in weights} if k},
            "n_estimated": sum(a["estimated"] for a in assets.values())}


# ---------- regenerate / highlight from the report page ----------
def _set_entry(scope: str, label: str, s, as_of: str) -> dict:
    return {"scope": scope, "label": label, "week": s.week, "computed_at": s.computed_at,
            "after_as_of": s.computed_at[:10] > as_of, "inputs": s.inputs,
            "scenarios": [x.model_dump() for x in s.scenarios]}


def _refresh_sync(run_id: str, country: str | None, force: bool) -> None:
    rec = runs.get(run_id)
    r, as_of = rec["result"], rec["request"]["as_of"]
    ev = lambda **kw: runs.append_event(run_id, **kw)
    hook = lambda kind, status, id, label, detail="": ev(kind=kind, phase="regen", status=status,
                                                         id=id, label=label, detail=detail)
    current = {g["scope"]: g for g in r["scenario_sets"]}
    by_scope = {g["scope"]: [x for x in r["scenarios"] if x["scope"] == g["scope"]] for g in r["scenario_sets"]}
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
    for t, f in (r.get("firms") or {}).items():   # filings read by the filing-risk agent
        rf = f.get("risk_factors") or {}
        if rf.get("status") == "ok" and rf.get("url"):
            a = add(rf["url"], f"{t} {rf.get('form', '')} filed {rf.get('filing_date', '')}, {rf.get('section', '')}",
                    rf.get("retrieved_at"))
            if f"Risk factors of {t}" not in a["cited_by"]:
                a["cited_by"].append(f"Risk factors of {t}")
    for c, m in ((r.get("macro") or {}).get("countries") or {}).items():   # World Bank pages behind macro context
        for i in m.get("indicators", {}).values():
            a = add(i["url"], f"World Bank open data — {i['label']}")
            if f"Macro: {NAMES.get(c, c)}" not in a["cited_by"]:
                a["cited_by"].append(f"Macro: {NAMES.get(c, c)}")
    g = (r.get("country_meta") or {}).get("gpr")
    if g:
        a = add(g["url"], g["name"], g.get("retrieved"))
        a["cited_by"].append("Country risk")
    letter = lambda n: (letter(n // 26 - 1) if n >= 26 else "") + chr(65 + n % 26)   # A..Z, AA, AB...
    out = [{**a, "letter": letter(n)} for n, a in enumerate(entries.values())]
    return {"list": out, "by_url": {a["url"]: a["letter"] for a in out}}
