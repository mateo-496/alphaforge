"""Offline stand-ins for the network, SEC and Bedrock, so the full pipeline can run in tests and demos.
They return plausible shapes only. Never imported by the application itself."""
import json
import math
import random
from datetime import date, datetime, timedelta, timezone

from core.schemas import AgentOutput, Claim, Entity, Source


def _src(title, url, loc):
    return {"title": title, "url": url, "locator": loc, "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def _series(name, unit, n, start, drift, vol, url, title, seed):
    rng, v, obs = random.Random(seed), start, []
    for i in range(n):
        d = date(2026, 11, 12) - timedelta(days=n - i)
        if d.weekday() < 5:
            v = max(0.01, v * math.exp(drift + rng.gauss(0, vol)))
            obs.append({"date": d.isoformat(), "value": round(v, 4)})
    return {"name": name, "unit": unit, "observations": obs, "source": _src(title, url, name)}


def prices(ticker, as_of, lookback_days=90):
    h = sum(map(ord, ticker))
    return _series(ticker, "USD", lookback_days, 50 + h % 100, 0.0004, 0.01 + (h % 5) * 0.004,
                   f"https://finance.yahoo.com/quote/{ticker}/history/", "Yahoo Finance adjusted daily close", h)


SEC = {"AAPL": [("US", .42), ("REGION:EUROPE", .26), ("CN", .17)], "NVDA": [("US", .44), ("TW", .16), ("CN", .13)], "MSFT": [("US", .51)],
       "TSM": [("US", .66), ("CN", .11), ("TW", .08)], "JNJ": [("US", .55)], "PG": [("US", .52)]}


def exposures(ticker):
    if ticker in SEC:
        s = _src(f"{ticker} SEC annual filing", f"https://www.sec.gov/Archives/edgar/data/{sum(map(ord, ticker))}/R4.htm",
                 "Revenue by geography; fiscal year 2025")
        return {"ticker": ticker, "status": "available", "fiscal_year": 2025,
                "exposures": [{"country": c, "revenue_share": v, "source": s} for c, v in SEC[ticker]]}
    return {"ticker": ticker, "status": "no_annual_filing", "exposures": []}


def market_series(sid, as_of, lookback_days=90):
    s = _series(sid, "index", lookback_days, 20 if sid == "VIXCLS" else 1.3, 0, 0.03,
                f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}", f"{sid} via FRED", len(sid))
    return s


def gpr_table(week=None):
    months = [f"{y}-{m:02d}" for y in range(2000, 2027) for m in range(1, 13)][:-1]
    rng = random.Random(1)
    ser = {k: [round(1 + rng.random() * (3 if k in ("TWN", "CHN", "ISR") else 1), 3) for _ in months]
           for k in ["GLOBAL", "USA", "CAN", "CHN", "TWN", "JPN", "KOR", "DEU", "GBR", "MEX", "ISR", "IND"]}
    return {"retrieved_at": "2026-11-14T00:00:00+00:00", "url": "https://www.matteoiacoviello.com/gpr_files/data_gpr_export.xls",
            "months": months, "series": ser}


def filings_run(ticker, as_of=None):
    src = Source(title=f"{ticker} 10-K filed 2026-02-20", url=f"https://www.sec.gov/Archives/{ticker}-10k.htm",
                 locator="Item 1A", retrieved_at="2026-11-14T00:00:00+00:00")
    claims = [Claim(id=f"filings:{ticker}:001", channel="export_controls", statement=f"{ticker} discloses export-control limits on sales to China.",
                    score=4, confidence=.8, sources=[src], evidence_quote="export controls could limit our sales", quote_verified=True),
              Claim(id=f"filings:{ticker}:002", channel="supply_chain", statement=f"{ticker} depends on suppliers in Taiwan.",
                    score=3, confidence=.7, sources=[src], evidence_quote="we rely on suppliers in Taiwan", quote_verified=False)]
    return AgentOutput(agent="filings", entity=Entity(ticker=ticker), as_of=as_of or "2026-11-12", claims=claims,
                       summary="[filings:x:001]")


class FakeAgent:
    """Answers any structured-output call with a valid object built from the prompt's facts."""
    def __init__(self, *a, **k):
        pass

    def __call__(self, prompt, structured_output_model=None):
        from types import SimpleNamespace
        name = structured_output_model.__name__
        facts = json.loads(prompt) if prompt.lstrip().startswith(("{", "[")) else {}
        if name == "CountryDrivers":
            out = {"drivers": [{"country": f["country"], "driver": f"{f['name']}: elevated GPR and exposure to "
                                + (f["scenarios_involved"][0] if f["scenarios_involved"] else "no scenario")} for f in facts]}
        elif name == "Explanation":
            h = facts["top_holdings"][0]
            out = {"sentences": [f"The score is {facts['score']}, driven by {h['ticker']}.",
                                 f"{h['ticker']} carries a large share of the risk for this profile.",
                                 "It could fall 73% overnight."]}   # invented number: must be filtered
        elif name == "Swaps":
            top, cands = facts["holdings"][0]["ticker"], facts["candidates"]
            out = {"swaps": [{"sell": top, "buy": cands[0]["ticker"], "fraction": .5, "rationale": "Cuts the largest contribution."},
                             {"sell": "NOPE", "buy": cands[0]["ticker"], "fraction": .5, "rationale": "invalid ticker"}]}
        elif name == "Evaluations":
            out = {"evaluations": [{"id": c["id"], "score": 2, "confidence": .6} for c in facts]}
        else:
            raise ValueError(name)
        return SimpleNamespace(structured_output=structured_output_model.model_validate(out))


def install(monkeypatch=None):
    """Patch every external call. With a pytest monkeypatch, patches are undone after the test."""
    from agents import filings_agent, geopolitical_agent, market_stress_agent, remediation_agent, risk_agent
    from tools import gpr, market_data, market_stress
    setp = (lambda o, n, v: monkeypatch.setattr(o, n, v)) if monkeypatch else setattr
    setp(market_data, "get_price_history", prices)
    setp(market_data, "get_country_exposures", exposures)
    setp(market_stress, "get_market_series", market_series)
    setp(gpr, "table", gpr_table)
    setp(filings_agent, "run", filings_run)
    for mod in (geopolitical_agent, risk_agent, remediation_agent, market_stress_agent):
        setp(mod, "Agent", FakeAgent)
