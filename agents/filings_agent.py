"""Filings/Exposure agent: ticker -> geopolitical exposure by country, with cited evidence.

Usage (from repo root):
    python -m agents.filings_agent NVDA --as-of 2025-06-30
"""
import argparse
import json
import os
import re
from datetime import date, datetime, timezone

from strands import Agent

from agents.base import build_model
from core.citations import resolve_citations
from core.schemas import AgentOutput, Claim, DraftOutput, Entity, Source
from tools.filings import (FILING_META, RETRIEVED_TEXT, get_annual_filing_info,
                           get_risk_factors, quote_is_verified, search_filing)

AGENT = "filings"

SYSTEM_PROMPT = """You are the Filings analyst of AlphaForge, a geopolitical portfolio-risk system.
Goal: for one company, extract atomic geopolitical claims using ONLY its SEC annual filing.

Method:
1. Call get_annual_filing_info, then get_risk_factors.
2. Call search_filing for geographic revenue ("geographic", "revenue by", "long-lived assets"),
   for the countries you see mentioned, and for "sanctions", "export control", "tariff", "supplier".
3. Emit one claim per finding. A claim has ONE channel from the fixed taxonomy
   (trade_tariffs, export_controls, sanctions, conflict_exposure, supply_chain, regulatory,
   fx_capital_controls, financial_stress), one statement, and a number (value + unit) when the filing gives one.

Rules:
- Point-in-time: always pass the given as_of date; never use knowledge of later events.
- Every evidence_quote must be copied VERBATIM from tool output. Never paraphrase inside a quote.
- locator = the filing section or passage location the quote comes from.
- value only when the filing states a number (revenue shares as 0-1, unit "revenue_share"); otherwise null.
- score = severity 0-5; confidence = 0-1 that the claim is correctly read from the filing.
- Do NOT set ids or sources; code does that.
- summary: short prose where EVERY sentence ends with claim citations by position, e.g. "... [1][3]."
- At most ~10 claims, most material first."""


def build_agent() -> Agent:
    return Agent(model=build_model(), system_prompt=SYSTEM_PROMPT, name="filings_agent",
                 tools=[get_annual_filing_info, get_risk_factors, search_filing])


def run(ticker: str, as_of: str | None = None) -> AgentOutput:
    ticker = ticker.upper()
    as_of = as_of or date.today().isoformat()
    RETRIEVED_TEXT.pop(ticker, None)
    FILING_META.pop(ticker, None)
    result = build_agent()(f"Analyze {ticker} as of {as_of}.", structured_output_model=DraftOutput)
    draft: DraftOutput = result.structured_output

    meta = FILING_META.get(ticker, {})
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    claims = []
    for n, d in enumerate(draft.claims, 1):  # ids, sources and quote check are done by code
        src = Source(title=f"{ticker} {meta.get('form', 'annual filing')} filed {meta.get('filing_date', '?')}",
                     url=meta.get("url", ""), locator=d.locator, retrieved_at=now)
        claims.append(Claim(id=f"{AGENT}:{ticker}:{n:03d}", sources=[src],
                            quote_verified=quote_is_verified(ticker, d.evidence_quote),
                            **d.model_dump(exclude={"locator"})))
    # The LLM cites claims by position ([1], [2]...); map them to stable claim ids.
    summary = re.sub(r"\[(\d+)\]",
                     lambda m: f"[{claims[int(m.group(1)) - 1].id}]" if 0 < int(m.group(1)) <= len(claims) else m.group(0),
                     draft.summary)
    return AgentOutput(agent=AGENT, entity=Entity(ticker=ticker), as_of=as_of,
                       claims=claims, summary=summary)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("ticker")
    p.add_argument("--as-of", default=None)
    args = p.parse_args()
    report = run(args.ticker, args.as_of)
    print("\n" + report.model_dump_json(indent=2))
    resolve_citations(report.summary, [report])  # fails loudly if a sentence has no valid claim id
    os.makedirs("outputs", exist_ok=True)
    with open(f"outputs/{args.ticker.upper()}_exposure.json", "w") as fh:
        fh.write(report.model_dump_json(indent=2))
