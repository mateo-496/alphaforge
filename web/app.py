"""AlphaForge web: portfolio + investor profile input, validation and review.

Run locally:  uvicorn web.app:app --reload   (from the repo root)
"""
import asyncio
import json
import math
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from core.schemas import AnalysisRequest, Holding, InvestorProfile, Portfolio
from web import mock, pipeline, universe as U
from web.store import runs
from web.samples import samples
from web.personas import COUNTRIES, INTERESTS, PERSONAS, SCENARIO_COUNTRIES

HERE = Path(__file__).parent
app = FastAPI(title="AlphaForge")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
tpl = Jinja2Templates(directory=HERE / "templates")
tpl.env.globals["annexes"] = pipeline.annexes
_tasks: set = set()
COUNTRY_NUM = {k: v["num"] for k, v in json.loads((HERE / "countries.json").read_text()).items() if v["num"]}

RISK_LABELS = {"low": "Low", "low_moderate": "Low to moderate", "moderate": "Moderate", "high": "High"}
VOL_LIMIT = {"low": 0.20, "low_moderate": 0.30, "moderate": 0.40, "high": None}  # our thresholds


def _ctx(**kw) -> dict:
    return {"universe": U.universe(), "sectors": U.sectors(), "personas": PERSONAS,
            "samples": samples(), "interests": INTERESTS, "countries": COUNTRIES, "scenario_countries": SCENARIO_COUNTRIES, "risk_labels": RISK_LABELS,
            "window": U.WINDOW, "prices_ok": U.prices_available(), **kw}


def _holdings(request: Request, mode: str, rows: list[dict], warnings: list[str]):
    return tpl.TemplateResponse(request, "_holdings.html",
                                _ctx(mode=mode, rows=rows, warnings=warnings))


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    rows = [{"ticker": "", "amount": ""} for _ in range(3)]
    return tpl.TemplateResponse(request, "index.html",
                                _ctx(mode="weight", rows=rows, warnings=[], as_of=U.WINDOW[1]))


@app.post("/portfolio/upload", response_class=HTMLResponse)
async def upload(request: Request, file: UploadFile = File(...)):
    raw = await file.read()
    if not file.filename.lower().endswith((".csv", ".txt", ".tsv")):
        return _holdings(request, "weight", [], ["Upload a .csv file (export from Excel with 'Save as CSV')."])
    mode, rows, warnings = U.parse_csv(raw.decode("utf-8-sig", errors="replace"))
    unknown = [r["raw"] for r in rows if r["ticker"] not in U.universe()]
    if unknown:
        warnings.append(f"Not in the asset universe, will be ignored: {', '.join(unknown)}.")
    return _holdings(request, mode, rows, warnings)


@app.get("/portfolio/example/{persona}", response_class=HTMLResponse)
def example(request: Request, persona: str):
    p = PERSONAS.get(persona) or samples().get(persona)
    rows = [{"ticker": t, "amount": w} for t, w in p["portfolio"]] if p else []
    return _holdings(request, "weight", rows, [])


@app.get("/portfolio/template.csv", response_class=PlainTextResponse)
def template_csv():
    return PlainTextResponse("ticker,weight\nNVDA,25\nRY.TO,15\nXBB.TO,20\nJNJ,10\nSPY,30\n",
                             headers={"Content-Disposition": "attachment; filename=portfolio_template.csv"})


def _vol_1y(ticker: str, as_of: str) -> float | None:
    s = U._series()
    if not s or ticker not in s[0]:
        return None
    dates, closes = s[0][ticker]
    end = U.bisect_right(dates, as_of)
    window = closes[max(0, end - 253):end]
    if len(window) < 60:
        return None
    rets = [math.log(b / a) for a, b in zip(window, window[1:]) if a > 0]
    m = sum(rets) / len(rets)
    sd = math.sqrt(sum((r - m) ** 2 for r in rets) / (len(rets) - 1))
    per_year = 365 if U.universe()[ticker]["asset_class"] == "crypto" else 252
    return sd * math.sqrt(per_year)


def build_request(form) -> tuple[AnalysisRequest | None, list[str], list[str]]:
    """Form -> AnalysisRequest. Returns (request, errors, notes)."""
    errors, notes = [], []
    mode = form.get("mode", "weight")
    base = form.get("base_currency", "CAD")
    as_of = form.get("as_of") or U.WINDOW[1]
    if not (U.WINDOW[0] <= as_of <= U.WINDOW[1]):
        errors.append(f"Analysis date must be between {U.WINDOW[0]} and {U.WINDOW[1]}.")

    amounts: dict[str, float] = {}
    for raw_t, raw_a in zip(form.getlist("ticker"), form.getlist("amount")):
        if not raw_t.strip() and not raw_a.strip():
            continue
        t = U.normalise_ticker(raw_t)
        if not t:
            notes.append(f"{raw_t.strip().upper()} is not in the asset universe and was ignored.")
            continue
        try:
            a = float(raw_a.replace(",", ".").replace("%", ""))
        except ValueError:
            errors.append(f"{t}: '{raw_a}' is not a number.")
            continue
        if a < 0:
            errors.append(f"{t}: negative amounts (short positions) are not supported.")
            continue
        if t in amounts:
            notes.append(f"{t} appeared twice; the two lines were added together.")
        amounts[t] = amounts.get(t, 0.0) + a

    if mode in ("quantity", "value") and not errors:
        if mode == "quantity":
            if not U.prices_available():
                errors.append("Quantities need the starter price data (set STARTER_DIR).")
            for t in list(amounts):
                px = U.price_in(t, as_of, base)
                if px is None:
                    errors.append(f"No price for {t} on or before {as_of}.")
                else:
                    amounts[t] *= px
            notes.append(f"Quantities converted to {base} market value with closing prices on or before {as_of}.")

    total = sum(amounts.values())
    if not amounts:
        errors.append("Add at least one holding.")
    elif total <= 0:
        errors.append("Holdings add up to zero.")
    elif mode == "weight" and abs(total - 100) > 0.5:
        notes.append(f"Weights added up to {total:.1f}%; they were rescaled to 100%.")

    pct = lambda k, d: float(form.get(k) or d) / 100
    try:
        profile = InvestorProfile(
            persona=form.get("persona") or None,
            age=int(form["age"]) if form.get("age") else None,
            horizon_years=int(form.get("horizon_years") or 10),
            risk_tolerance=form.get("risk_tolerance", "moderate"),
            objective=form.get("objective", "balanced"),
            experience=form.get("experience", "intermediate"),
            esg_importance=form.get("esg_importance", "none"),
            avoid_controversies=form.get("avoid_controversies") == "on",
            crypto_max=pct("crypto_max", 0), max_single_weight=pct("max_single_weight", 25),
            excluded_sectors=form.getlist("excluded_sectors"),
            excluded_tickers=[x for x in (U.normalise_ticker(s) for s in
                              (form.get("excluded_tickers") or "").replace(";", ",").split(",") if s.strip()) if x],
            avoid_countries=form.getlist("avoid_countries"),
            interests=form.getlist("interests"),
            notes=(form.get("notes") or "").strip()[:1000])
    except (ValidationError, ValueError) as e:
        errors.append(f"Profile: {e}")
        return None, errors, notes
    if errors:
        return None, errors, notes

    holdings = [Holding(ticker=t, weight=round(a / total, 6)) for t, a in
                sorted(amounts.items(), key=lambda kv: -kv[1]) if a > 0]
    return AnalysisRequest(portfolio=Portfolio(holdings=holdings, base_currency=base), profile=profile,
                           as_of=as_of, scenario_country=form.get("scenario_country") or None), errors, notes


def profile_checks(req: AnalysisRequest) -> list[dict]:
    """Hard-constraint checks of the portfolio against the stated profile (deterministic)."""
    p, u, out = req.profile, U.universe(), []
    w = {h.ticker: h.weight for h in req.portfolio.holdings}
    for t, x in w.items():  # diversified funds (ETFs) are exempt from the single-holding limit
        if not u[t]["asset_class"].startswith("etf") and x > p.max_single_weight + 1e-9:
            out.append({"ticker": t, "text": f"{t} is {x:.0%} of the portfolio, above the "
                                              f"{p.max_single_weight:.0%} single-holding limit."})
    crypto = sum(x for t, x in w.items() if u[t]["asset_class"] == "crypto")
    if crypto > p.crypto_max + 1e-9:
        out.append({"ticker": "crypto", "text": f"Crypto is {crypto:.0%} of the portfolio; the limit is {p.crypto_max:.0%}."})
    for t in w:
        if u[t]["sector"] in p.excluded_sectors:
            out.append({"ticker": t, "text": f"{t} is in an excluded sector ({u[t]['sector']})."})
        if t in p.excluded_tickers:
            out.append({"ticker": t, "text": f"{t} is on the exclusion list."})
    limit = VOL_LIMIT[p.risk_tolerance]
    if limit:
        for t in w:
            v = _vol_1y(t, req.as_of)
            if v and v > limit:
                out.append({"ticker": t, "text": f"{t} had {v:.0%} annualised volatility over the year to "
                                                  f"{req.as_of}, above {limit:.0%} for a "
                                                  f"{RISK_LABELS[p.risk_tolerance].lower()} risk profile."})
    return out


@app.post("/runs")
async def create_run(request: Request):
    """Validate, store the request, start the agents in the background, send the user to the run page."""
    req, errors, notes = build_request(await request.form())
    if errors:
        return tpl.TemplateResponse(request, "error.html", _ctx(errors=errors, notes=notes), status_code=422)
    payload = req.model_dump() | {"checks": profile_checks(req), "notes": notes}
    run_id = runs.create(payload)
    _tasks.add(t := asyncio.create_task(pipeline.run(run_id)))  # keep a reference until done
    t.add_done_callback(_tasks.discard)
    return RedirectResponse(f"/runs/{run_id}", status_code=303)


@app.get("/runs/{run_id}", response_class=HTMLResponse)
def run_page(request: Request, run_id: str):
    rec = runs.get(run_id)
    if not rec:
        return HTMLResponse("Run not found", status_code=404)
    return tpl.TemplateResponse(request, "run.html", _ctx(run=rec, req=rec["request"]))


@app.get("/runs/{run_id}/events")
def run_events(run_id: str, after: int = 0):
    rec = runs.get(run_id)
    if not rec:
        return JSONResponse({"error": "not found"}, status_code=404)
    return {"status": rec["status"], "error": rec["error"], "events": runs.events_after(run_id, after)}


@app.get("/runs/{run_id}/result", response_class=HTMLResponse)
def run_result(request: Request, run_id: str):
    rec = runs.get(run_id)
    if not rec or rec["status"] != "done":
        return HTMLResponse("", status_code=404)
    return tpl.TemplateResponse(request, "_result.html", _ctx(run=rec, req=rec["request"], r=rec["result"]))


@app.get("/runs/{run_id}/scenarios.json")
def run_scenarios(run_id: str):
    rec = runs.get(run_id)
    if not rec or rec["status"] != "done":
        return JSONResponse({"error": "not ready"}, status_code=404)
    r = rec["result"]
    return {"scenarios": r["scenarios"], "names": mock.COUNTRY_NAMES, "num": COUNTRY_NUM, "highlight": r.get("highlight"),
            "exposure": {c["iso3"]: c["X"] for c in r["by_country"]}, "assets": r["assets"],
            "sets": r.get("scenario_sets", [])}


@app.post("/runs/{run_id}/scenarios")
async def run_refresh_scenarios(request: Request, run_id: str):
    """Regenerate the scenarios (force) and/or load the 5 most dangerous for a highlight country."""
    rec = runs.get(run_id)
    if not rec or rec["status"] != "done":
        return JSONResponse({"error": "run not finished"}, status_code=409)
    if rec.get("scenario_job") == "running":
        return JSONResponse({"error": "already running"}, status_code=409)
    form = await request.form()
    country = (form.get("country") or "").upper() or None
    if country and country not in dict(SCENARIO_COUNTRIES):
        return JSONResponse({"error": f"unknown country {country}"}, status_code=422)
    seq = len(rec["events"])
    _tasks.add(t := asyncio.create_task(pipeline.refresh_scenarios(run_id, country, form.get("force") == "1")))
    t.add_done_callback(_tasks.discard)
    return {"seq": seq}


@app.get("/runs/{run_id}/scenarios-section", response_class=HTMLResponse)
def run_scenarios_section(request: Request, run_id: str):
    rec = runs.get(run_id)
    return tpl.TemplateResponse(request, "_scenarios.html", _ctx(run=rec, req=rec["request"], r=rec["result"]))


@app.get("/runs/{run_id}/annexes", response_class=HTMLResponse)
def run_annexes(request: Request, run_id: str):
    rec = runs.get(run_id)
    return tpl.TemplateResponse(request, "_annexes.html", _ctx(run=rec, req=rec["request"], r=rec["result"]))


@app.post("/api/request")
async def api_request(request: Request):
    """Same validation as /review, returns the AnalysisRequest JSON (for the orchestrator)."""
    req, errors, notes = build_request(await request.form())
    if errors:
        return JSONResponse({"errors": errors, "notes": notes}, status_code=422)
    return {"request": req.model_dump(), "notes": notes, "checks": profile_checks(req)}
