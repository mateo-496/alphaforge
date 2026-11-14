"""Run pipeline: what the server does after the user clicks Run analysis.

Each step writes progress events to the run store (the page polls them) and its data to the cache.
Everything below is MOCKED: swap each `_mock_*` call for the real agent, keep the event and data shapes.
"""
import asyncio
import math
from datetime import date, timedelta

from tools import risk_math
from web import mock, universe as U
from web.store import cache, runs

DELAY = {"asset": 0.7, "country": 0.35, "step": 0.8}  # mock latency, makes the progress view visible


# ---------- mock agents (replace with agents/*.run) ----------
def _mock_asset_report(ticker: str, as_of: str) -> dict:
    a = U.universe()[ticker]
    is_fund = a["asset_class"] != "equity"
    return {"ticker": ticker, "as_of": as_of, "country_weights": mock.EXPOSURE[ticker],
            "firm_score": mock.FIRM_SCORE.get(ticker, 1.0),
            "method": "ETF look-through" if a["asset_class"].startswith("etf") else
                      ("No issuer country" if is_fund else "10-K / 40-F segment note"),
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


def load_scenarios() -> dict:
    """Precomputed scenario set. Production: weekly job writes S3 scenarios/<week>.json. Mock: seeded once."""
    sc = cache.get("scenarios", "latest")
    if sc is None:
        sc = {"computed_at": date.today().isoformat(), "scenarios": mock.SCENARIOS, "mock": True}
        cache.put("scenarios", "latest", sc)
    return sc


def scenario_impacts(weights: dict, assets: dict) -> list[dict]:
    """Per scenario: share of portfolio revenue in affected countries, weighted by intensity."""
    out = []
    for s in load_scenarios()["scenarios"]:
        per = {t: w * sum(cw * s["countries"].get(c, 0) for c, cw in assets[t]["country_weights"].items())
               for t, w in weights.items()}
        total = sum(per.values())
        top = [t for t, v in sorted(per.items(), key=lambda kv: -kv[1]) if v > 0.005][:4]
        out.append({**s, "exposure": round(total, 4), "holdings": top,
                    "holding_exposure": {t: round(v, 4) for t, v in per.items() if v > 0}})
    return out


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

        # 3. Risk (deterministic, tools/risk_math)
        ev(kind="phase", phase="risk", status="start", label="Portfolio risk")
        await asyncio.sleep(DELAY["step"])
        R = {c: r["R"] for c, r in countries.items()}
        G = {t: _asset_risk(assets[t], R) for t in weights}
        score = risk_math.portfolio_risk(weights, G)
        ev(kind="phase", phase="risk", status="done", detail=f"{score:.0f}/100")

        # 4. Report: drivers, watchlist, what-ifs, scenarios
        ev(kind="phase", phase="report", status="start", label="Report")
        await asyncio.sleep(DELAY["step"])
        result = build_report(req, weights, assets, countries, X, G, score)
        ev(kind="phase", phase="report", status="done")
        ev(kind="phase", phase="scenarios", status="done", label="Scenarios",
           detail=f"{len(result['scenarios'])} precomputed, {load_scenarios()['computed_at']}")
        runs.set(run_id, status="done", result=result)
        ev(kind="run", status="done")
    except Exception as e:  # surface the error on the page instead of hanging
        runs.set(run_id, status="error", error=f"{type(e).__name__}: {e}")
        ev(kind="run", status="error", detail=str(e))


def build_report(req, weights, assets, countries, X, G, score) -> dict:
    uni, as_of, prof = U.universe(), req["as_of"], req["profile"]
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
        new = score - move * G[t] + move * alt_G[alt]
        r_t, r_a = _ret_1y(t, as_of), _ret_1y(alt, as_of)
        whatifs.append({"from": t, "to": alt, "move": move, "score_after": new, "delta": new - score,
                        "ret_from": r_t, "ret_to": r_a})

    top = by_holding[0]
    foreign = [c for c in by_country if c["iso3"] not in ("CAN", "USA")]
    summary = [f"The portfolio's geopolitical risk score is {score:.0f} out of 100, which we classify as {_level(score)}."]
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

    return {"as_of": as_of, "score": round(score, 1), "level": _level(score), "summary": summary,
            "by_holding": by_holding, "by_country": by_country, "watchlist": watch, "whatifs": whatifs,
            "checks": req.get("checks", []), "scenarios": scenario_impacts(weights, assets),
            "assets": {t: {"weight": w, "country_weights": assets[t]["country_weights"]} for t, w in weights.items()},
            "mock": True}
