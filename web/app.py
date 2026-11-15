"""AlphaForge web: portfolio + investor profile form, run page and report.

Run locally:  uvicorn web.app:app --reload --port 8080   (from the repo root)
"""
import asyncio
import json
import logging
from pathlib import Path

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from core import config
from core.schemas import AnalysisRequest, Holding, InvestorProfile, Portfolio
from web import pipeline, profile, universe as U
from web.store import runs
from web.samples import samples
from web.personas import PERSONAS
from web import options as O

if "@" not in config.SEC_IDENTITY:
    logging.getLogger("uvicorn.error").warning(
        "SEC_IDENTITY has no email address: every SEC lookup will fail. Set it in .env, e.g. 'Your Name you@domain.com'.")
HERE = Path(__file__).parent
app = FastAPI(title="AlphaForge")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
tpl = Jinja2Templates(directory=HERE / "templates")
tpl.env.globals["annexes"] = pipeline.annexes


def short_driver(text: str | None, limit: int = 90) -> str:
    """Driver as a short phrase: drop the percentile clause (it has its own column) and filler words."""
    import re
    t = re.sub(r"^[A-Z][\w .'-]{1,30}:\s+", "", text or "")   # "Japan: ..." (the country is in its own column)
    t = re.sub(r"^\s*(own|global) index at \d+\w* percentile[^;:,.]*[;:,.]\s*", "", t, flags=re.I)
    t = re.sub(r"^(a (low|high) reading[;,]\s*)", "", t, flags=re.I)
    if re.match(r"no scenarios? (directly )?involves? (it|them)", t, flags=re.I):
        return "No scenario involves it"
    t = re.sub(r"\b(driven by |exposed through |involved in |involvement in |directly )(the )?", "", t, flags=re.I)
    t = re.sub(r"(?<!\bno)\s+scenarios?\b", "", t, flags=re.I).strip(" ;,.")
    t = t[:1].upper() + t[1:]
    return t if len(t) <= limit else t[:limit].rsplit(" ", 1)[0].rstrip(",;") + "…"


tpl.env.globals["short_driver"] = short_driver
_tasks: set = set()
COUNTRY_NUM = {k: v["num"] for k, v in json.loads((HERE / "countries.json").read_text()).items() if v["num"]}

RISK_LABELS = profile.RISK_LABELS
OBJECTIVE_LABELS = {1: "Preserve capital", 2: "Income", 3: "Balanced", 4: "Growth", 5: "Maximum growth"}


def _ctx(**kw) -> dict:
    return {"universe": U.universe(), "sectors": U.sectors(), "personas": PERSONAS,
            "samples": samples(), "scenario_countries": O.COUNTRIES, "risk_labels": RISK_LABELS,
            "objective_labels": OBJECTIVE_LABELS, "exclusion_options": O.exclusion_options(U.universe()),
            "country_options": O.country_options(), "interest_options": O.interest_options(),
            "holding_options": [{"v": ticker, "l": f"{ticker} - {asset['name']}"} for ticker, asset in U.universe().items()],
            "window": U.WINDOW, "prices_ok": U.prices_available(), "names": pipeline.NAMES, **kw}


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
            for t in list(amounts):
                px, src = U.price_in(t, as_of, base)
                if px is None:
                    errors.append(f"No price for {t} on or before {as_of} ({src}). Enter weights or market values instead.")
                else:
                    amounts[t] *= px
            if not errors:
                notes.append(f"Quantities converted to {base} market value with the last close on or before {as_of}.")

    total = sum(amounts.values())
    if not amounts:
        errors.append("Add at least one holding.")
    elif total <= 0:
        errors.append("Holdings add up to zero.")
    elif mode == "weight" and abs(total - 100) > 0.5:
        notes.append(f"Weights added up to {total:.1f}%; they were rescaled to 100%.")

    pct = lambda k, d: float(form.get(k) or d) / 100
    sectors, themes, tickers = [], [], []
    for v in form.getlist("exclusions"):
        kind, _, val = v.partition(":")
        if kind == "sector":
            sectors.append(val)
        elif kind == "ticker":
            tickers.append(val)
        elif kind in ("theme", "text"):
            t = U.normalise_ticker(val) if kind == "text" else None   # a typed ticker is a ticker
            (tickers if t else themes).append(t or val)
    esg = {"0": "none", "1": "some", "2": "high"}.get(form.get("esg", "0"), "none")
    protected_holdings = form.getlist("protected_holdings")
    if any(ticker not in amounts or amounts[ticker] <= 0 for ticker in protected_holdings):
        errors.append("Holdings to keep must be in the portfolio.")
    try:
        profile = InvestorProfile(
            persona=form.get("persona") or None,
            age=int(form["age"]) if form.get("age") else None,
            horizon_years=int(form.get("horizon_years") or 10),
            risk_level=int(form.get("risk_level") or 3),
            objective_level=int(form.get("objective_level") or 3),
            experience={"1": "beginner", "2": "intermediate", "3": "advanced"}.get(form.get("experience", "2"), "intermediate"),
            esg_importance=esg, avoid_controversies=esg == "high",
            crypto_max=pct("crypto_max", 0), max_single_weight=pct("max_single_weight", 25),
            protected_holdings=protected_holdings, max_turnover=pct("max_turnover", 100),
            replacement_types=form.getlist("replacement_types") or None,
            excluded_sectors=sectors, excluded_themes=themes, excluded_tickers=tickers,
            avoid_countries=[c for c in form.getlist("avoid_countries") if c in dict(O.COUNTRIES)],
            interests=[i.strip()[:60] for i in form.getlist("interests") if i.strip()][:20],
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
    weights = {holding.ticker: holding.weight for holding in req.portfolio.holdings}
    return profile.checks(req.profile.model_dump(), weights, U.universe(), req.as_of)


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
    return tpl.TemplateResponse(request, "run.html", _ctx(run=rec, req=rec["request"],
                                                         stale=rec["status"] == "done" and _stale(rec), stale_note=STALE_NOTE))


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
    if _stale(rec):
        return HTMLResponse(STALE_NOTE)
    return tpl.TemplateResponse(request, "_result.html", _ctx(run=rec, req=rec["request"], r=rec["result"]))


REPORT_VERSION = 3   # bump when the report's shape changes (v3: Cedric's formula, exposure tiers)
STALE_NOTE = ('<p class="notice">This report was produced by an earlier version of AlphaForge and cannot be shown '
              'with the current page. <a href="/">Run the analysis again</a>.</p>')


def _stale(rec: dict) -> bool:
    r = rec.get("result") or {}
    return r.get("version", 1) < REPORT_VERSION


@app.get("/runs/{run_id}/scenarios.json")
def run_scenarios(run_id: str):
    rec = runs.get(run_id)
    if not rec or rec["status"] != "done":
        return JSONResponse({"error": "not ready"}, status_code=404)
    r = rec["result"]
    return {"scenarios": r["scenarios"], "names": O.NAMES, "num": COUNTRY_NUM, "highlight": r.get("highlight"),
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
    if country and country not in dict(O.COUNTRIES):
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
