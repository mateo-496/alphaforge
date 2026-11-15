"""Filings agent: one company's SEC annual filing -> atomic geopolitical claims, each with a verbatim quote.

The model reads the filing through tools (core.llm.run_tools); code assigns ids, attaches sources and checks
every quote word for word against the text the tools returned.

    python -m agents.filings_agent NVDA --as-of 2026-06-30
"""
import argparse
import re
from datetime import date, datetime, timezone

from core import llm
from core.schemas import AgentOutput, Claim, DraftOutput, Entity, Source
from tools.filings import FilingSession

AGENT = "filings"

SYSTEM_PROMPT = """You are the Filings analyst of AlphaForge, a geopolitical portfolio-risk system.
Goal: for one company, extract atomic geopolitical claims using ONLY its SEC annual filing.

Method:
1. Call get_annual_filing_info, then get_risk_factors.
2. Call search_filing at most 6 times in total. Best patterns: "geographic", "China", "sanctions",
   "export control", "tariff", "supplier". Then call answer.
3. Emit one claim per finding. A claim has ONE channel from the fixed taxonomy
   (trade_tariffs, export_controls, sanctions, conflict_exposure, supply_chain, regulatory,
   fx_capital_controls, financial_stress), one statement, and a number (value + unit) when the filing gives one.

Rules:
- Never use knowledge of events after the filing.
- Every evidence_quote must be copied VERBATIM from tool output. Never paraphrase inside a quote.
- locator = the filing section or passage location the quote comes from.
- value only when the filing states a number (revenue shares as 0-1, unit "revenue_share"); otherwise null.
- score = severity 0-5; confidence = 0-1 that the claim is correctly read from the filing.
- summary: short prose where EVERY sentence ends with claim citations by position, e.g. "... [1][3]."
- At most ~6 claims, most material first."""


def run(ticker: str, as_of: str | None = None) -> AgentOutput:
    ticker, as_of = ticker.upper(), as_of or date.today().isoformat()
    session = FilingSession(ticker, as_of)
    draft = llm.run_tools(AGENT, SYSTEM_PROMPT, f"Analyze {ticker}. Analysis date: {as_of}.", session.tools(),
                          DraftOutput, max_turns=10)
    meta, now = session.meta, datetime.now(timezone.utc).isoformat(timespec="seconds")
    claims = []
    for n, d in enumerate(draft.claims, 1):
        src = Source(title=f"{ticker} {meta.get('form', 'annual filing')} filed {meta.get('filing_date', '?')}",
                     url=meta.get("url", ""), locator=d.locator, retrieved_at=now)
        claims.append(Claim(id=f"{AGENT}:{ticker}:{n:03d}", sources=[src], quote_verified=session.verified(d.evidence_quote),
                            **d.model_dump(exclude={"locator"})))
    summary = re.sub(r"\[(\d+)\]",   # the model cites claims by position; map to stable ids
                     lambda m: f"[{claims[int(m.group(1)) - 1].id}]" if 0 < int(m.group(1)) <= len(claims) else m.group(0),
                     draft.summary)
    return AgentOutput(agent=AGENT, entity=Entity(ticker=ticker), as_of=as_of, claims=claims, summary=summary)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("ticker")
    p.add_argument("--as-of", default=None)
    a = p.parse_args()
    print(run(a.ticker, a.as_of).model_dump_json(indent=2))
