"""Test-only stand-ins for the network, SEC and Bedrock, so the full pipeline runs offline in pytest.
Plausible shapes only. Never imported by the application."""
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


TEXT_ONLY = {"JPM"}   # filing without an XBRL geographic table: the exposure agent reads the text
TEXT_PASSAGE = "Approximately 22% of our revenue came from customers outside the United States in fiscal 2025."
GDP = {"USA": .27, "CHN": .17, "DEU": .045, "JPN": .04, "IND": .036, "GBR": .033, "FRA": .03, "ITA": .021,
       "CAN": .021, "BRA": .02, "KOR": .017, "MEX": .017, "TWN": .008, "ESP": .015, "NLD": .011}


def _filing(ticker):
    return {"form": "10-K", "accession": f"000{sum(map(ord, ticker))}", "filing_date": "2026-02-20",
            "report_date": "2025-12-31", "base": f"https://www.sec.gov/Archives/edgar/data/1/{ticker}"}


def exposures(ticker, as_of=None):
    if ticker in SEC:
        s = _src(f"{ticker} SEC annual filing", f"https://www.sec.gov/Archives/edgar/data/{sum(map(ord, ticker))}/R4.htm",
                 "Revenue by geography; fiscal year 2025")
        return {"ticker": ticker, "status": "available", "fiscal_year": 2025, "stale": False, "filing": _filing(ticker),
                "exposures": [{"country": c, "revenue_share": v, "source": s} for c, v in SEC[ticker]]}
    if ticker in TEXT_ONLY:
        return {"ticker": ticker, "status": "no_country_revenue_found", "exposures": [], "stale": False,
                "filing": _filing(ticker), "fiscal_year": 2025}
    return {"ticker": ticker, "status": "no_annual_filing", "exposures": [], "stale": False, "filing": None}


class TextFiling:
    def text(self):
        return "Segment information. " + TEXT_PASSAGE

    def grep(self, pattern):
        from types import SimpleNamespace
        return [SimpleNamespace(location="Item 7", context=TEXT_PASSAGE)] if pattern.lower() in TEXT_PASSAGE.lower() else []


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


RISK_TEXT = ("Item 1A. Risk Factors. Export controls could limit our sales to customers in China. "
             "We rely on a limited number of suppliers in Taiwan for wafers. Currency fluctuations may reduce our margins.")
SOURCE_TEXT = {"eurasia_top_risks": "China is likely to step up military pressure on Taiwan, raising the risk of a blockade in 2026.",
               "blackrock_grd": "US tariffs on Canada and Mexico could escalate into a broader trade war across North America.",
               "cfr_pps": "Sanctions on Iran keep oil markets on edge this year amid renewed tensions in the Gulf.",
               "atlantic_foresight": "Elections across Latin America raise the risk of fiscal crises and capital controls."}
WB = {"USA": {"gdp_growth_pct": 2.8, "inflation_pct": 2.9, "public_debt_pct_gdp": 120.1, "nonperforming_loans_pct": 1.1,
              "capital_adequacy_pct": 9.0},
      "CHN": {"gdp_growth_pct": 5.0, "inflation_pct": 0.2, "public_debt_pct_gdp": 60.0},
      "CAN": {"gdp_growth_pct": 1.2, "inflation_pct": 2.4, "unemployment_pct": 6.5}}


def risk_section(ticker, as_of):
    return {"ticker": ticker, "form": "10-K", "filing_date": "2026-02-20", "section": "Item 1A",
            "url": f"https://www.sec.gov/Archives/{ticker}-10k.htm", "retrieved_at": "2026-11-14T00:00:00+00:00",
            "status": "available", "reason": None, "chunks": [RISK_TEXT]}


def wb_indicators(iso3, as_of):
    from tools.worldbank import INDICATORS
    return {k: {"value": v, "year": 2025, "code": INDICATORS[k][0], "label": INDICATORS[k][1],
                "url": f"https://data.worldbank.org/indicator/{INDICATORS[k][0]}"} for k, v in WB.get(iso3, {}).items()}


def fetch_sources(week, on_event=None):
    from tools.scenario_sources import SOURCES
    return [{"id": k, "name": v["name"], "url": v["url"], "ok": True, "text": SOURCE_TEXT[k], "chars": len(SOURCE_TEXT[k]),
             "error": None, "retrieved_at": "2026-11-14T00:00:00+00:00"} for k, v in SOURCES.items()]


def _scenario(id, name, countries, lk, impact, sid, quote, channels):
    return {"id": id, "name": name, "summary": name + ".", "countries": countries, "channels": channels,
            "likelihood": lk, "impact": impact, "signposts": [f"{name}: first sign", f"{name}: second sign"],
            "evidence": [{"source_id": sid, "quote": quote}]}


def fake_ask(agent, system, prompt, schema, **kw):
    """Stands in for core.llm.ask: a valid object built from the prompt's facts."""
    name = schema.__name__
    facts = json.loads(prompt) if prompt.lstrip().startswith(("{", "[")) else {}
    if name == "CountryDrivers":
        out = {"drivers": [{"country": f["country"], "driver": f"{f['name']}: elevated GPR and exposure to "
                            + (f["scenarios_involved"][0] if f["scenarios_involved"] else "no scenario")} for f in facts]}
    elif name == "Explanation":
        h = facts["top_holdings"][0]
        out = {"countries": "Mostly North American revenue.",
               "holdings": f"{h['ticker']} carries a large share of the risk for this profile.",
               "profile": "Within the comfort level of this profile.",
               "watch": "It could fall 73% overnight."}   # invented number: must be filtered
    elif name == "DraftScenarioSet":
        out = {"scenarios": [
            _scenario("taiwan-blockade", "Taiwan Strait blockade", {"TWN": 1, "CHN": .8, "JPN": .4}, .08, 5,
                      "eurasia_top_risks", "raising the risk of a blockade in 2026", ["conflict_exposure", "supply_chain"]),
            _scenario("us-canada-tariffs", "US-Canada tariff escalation", {"CAN": 1, "USA": .6, "MEX": .5}, .3, 3,
                      "blackrock_grd", "could escalate into a broader trade war", ["trade_tariffs"]),
            _scenario("invented", "Unsupported scenario", {"FRA": 1}, .2, 2, "cfr_pps", "not in any source text", ["regulatory"])]}
    elif name == "DraftSplit":
        out = {"rows": [{"place": "FOREIGN", "share": .22, "quote": "Approximately 22% of our revenue came from customers outside the United States"},
                        {"place": "CHN", "share": .3, "quote": "30% of revenue from China"}]}   # not in the text: dropped
    elif name == "DraftRisks":
        out = {"risks": [{"category": "export controls", "evidence_quote": "Export controls could limit our sales", "score": 4, "confidence": .8},
                         {"category": "supply chain", "evidence_quote": "We depend on Taiwan suppliers", "score": 3, "confidence": .7}]}
    elif name == "Corrections":
        out = {"corrections": [{"position": r["position"], "start_segment": 0, "end_segment": 0} for r in facts["rejected_risks"]]}
    elif name == "DraftOutput":   # geopolitical claims agent: quote the last row of the data it was sent
        row = facts["rows"][-1]
        out = {"claims": [{"channel": "conflict_exposure", "statement": f"Country GPR was {row['gprc']} in {row['month']}.",
                           "value": row["gprc"], "unit": "pct_articles", "score": 3, "confidence": .9,
                           "evidence_quote": f'"month": "{row["month"]}"', "locator": f"gprc, {row['month']}"},
                          {"channel": "conflict_exposure", "statement": "Invented spike.", "score": 5, "confidence": .5,
                           "evidence_quote": '"gprc": 99.99', "locator": "gprc"}],
               "summary": "GPR level [1]."}
    elif name == "CountryNotes":
        out = {"notes": [{"country": f["country"], "note": f"{f['name']}: macro score {f['macro_score']}."} for f in facts]
               + [{"country": facts[0]["country"], "note": "Debt will hit 300% next year."}] if facts else []}
    elif name == "Swaps":
        top, cands = facts["holdings"][0]["ticker"], facts["candidates"]
        out = {"swaps": [{"sell": top, "buy": cands[-1]["ticker"], "fraction": .5, "rationale": "Cuts the largest contribution."},
                         {"sell": "NOPE", "buy": cands[0]["ticker"], "fraction": .5, "rationale": "Invalid ticker."}]}
    else:
        raise ValueError(name)
    return schema.model_validate(out)


def install(monkeypatch):
    """Patch every external call for the duration of one test."""
    from agents import filings_agent, source_agent
    from core import llm
    from tools import exposure_priors, filings, gpr, market_data, market_stress, scenario_sources, worldbank
    setp = monkeypatch.setattr
    setp(exposure_priors, "industry", lambda t: None)
    setp(worldbank, "gdp_weights", lambda as_of, top=60: dict(GDP))
    setp(filings, "_annual_filing", lambda t, a: TextFiling())
    setp(filings, "risk_section", risk_section)
    setp(worldbank, "indicators", wb_indicators)
    setp(source_agent, "_check", lambda url: {"live": "imf.org" in url or "bankofcanada" in url, "final_url": url})
    setp(scenario_sources, "fetch_sources", fetch_sources)
    setp(scenario_sources, "gpr_snapshot", lambda week, on_event=None: {"error": "offline"})
    setp(market_data, "get_price_history", prices)
    setp(market_data, "get_country_exposures", exposures)
    setp(market_stress, "get_market_series", market_series)
    setp(gpr, "table", gpr_table)
    setp(filings_agent, "run", filings_run)
    setp(llm, "ask", fake_ask)
