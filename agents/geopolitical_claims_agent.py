"""Geopolitical agent: country -> geopolitical risk claims from the GPR index in S3, as an AgentOutput.

Same contract as the filings agent: the LLM produces a DraftOutput (claims + summary); code turns it
into an AgentOutput (claim ids, sources, quote verification). One AgentOutput per country.

Usage (from repo root):
    python -m agents.geopolitical_claims_agent Taiwan China --as-of 2026-10-31
"""
import argparse
import os
import re
from datetime import date, datetime, timezone

from strands import Agent

from agents.base import build_model
from core import config
from core.citations import CitationError, resolve_citations
from core.schemas import AgentOutput, Claim, DraftOutput, Entity, Source
from tools import geopolitics

AGENT = "geopolitical"

SYSTEM_PROMPT = """You are the Geopolitical analyst of AlphaForge, a geopolitical portfolio-risk system.
Goal: for one country, extract atomic geopolitical-risk claims using ONLY the GPR index data in S3.

Data: extract_portfolio_from_s3_excel returns monthly rows with
- gpr: global Geopolitical Risk index (1985-2019 = 100),
- gprc_<iso3>: share (%) of newspaper articles about geopolitical risk involving the country (since 1985),
- gprhc_<iso3>: same, historical series (3 newspapers, since 1900).

Method:
1. Call extract_portfolio_from_s3_excel for the country (months=24 is a good default; use more,
   e.g. 120, to compare the current level with its own history).
2. Emit one claim per finding: current level, trend (rising / falling), spikes, level versus the
   country's own history, level versus the global index.

Rules:
- Point-in-time: ignore rows after the given as_of date; never use outside knowledge of events.
- channel: the GPR index measures conflict and tension news, so use "conflict_exposure" unless the
  data clearly supports another channel of the taxonomy.
- value + unit: the number the claim rests on (unit "pct_articles" for gprc/gprhc, "index" for gpr).
- evidence_quote: copied VERBATIM from the tool output JSON, e.g. "month": "2026-10", "gpr": 150.52
  (a contiguous piece of one row). Never reformat or round numbers inside a quote.
- locator: series and month, e.g. "gprc_twn, 2026-10".
- score = severity 0-5; confidence = 0-1 that the claim is correctly read from the data.
- Do NOT set ids or sources; code does that.
- summary: short prose where EVERY sentence ends with claim citations by position, e.g. "... [1][3]."
- At most ~8 claims, most material first."""


def build_agent() -> Agent:
    return Agent(model=build_model(), system_prompt=SYSTEM_PROMPT, name=AGENT,
                 tools=geopolitics.tools())


def run(country: str, as_of: str | None = None) -> AgentOutput:
    """Analyze one country (name or ISO3 code) and return a validated AgentOutput."""
    as_of = as_of or date.today().isoformat()
    geopolitics.RETRIEVED_TEXT.clear()
    geopolitics.MATCHED_COUNTRIES.clear()
    result = build_agent()(f"Analyze the geopolitical risk of {country} as of {as_of}.",
                           structured_output_model=DraftOutput)
    draft: DraftOutput = result.structured_output

    # Entity: the country's ISO3 code from the tool (the claim ids need a stable key).
    iso3 = next((code for name, code in geopolitics.MATCHED_COUNTRIES.items()
                 if country.strip().lower() in (name.lower(), code.lower())), country.upper())

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    src_url = f"s3://{config.GEO_S3_BUCKET}/raw/gpr_data/data_gpr_export.xls"
    claims = []
    for n, d in enumerate(draft.claims, 1):  # ids, sources and quote check are done by code
        src = Source(title="Geopolitical Risk (GPR) index, data_gpr_export.xls", url=src_url,
                     locator=d.locator, retrieved_at=now)
        claims.append(Claim(id=f"{AGENT}:{iso3}:{n:03d}", sources=[src],
                            quote_verified=geopolitics.quote_is_verified(d.evidence_quote),
                            **d.model_dump(exclude={"locator"})))
    # The LLM cites claims by position ([1], [2]...); map them to stable claim ids.
    summary = re.sub(r"\[(\d+)\]",
                     lambda m: f"[{claims[int(m.group(1)) - 1].id}]" if 0 < int(m.group(1)) <= len(claims) else m.group(0),
                     draft.summary)
    return AgentOutput(agent=AGENT, entity=Entity(ticker=iso3), as_of=as_of, claims=claims, summary=summary)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # model output may contain emoji (cp1252 on Windows pipes)

    p = argparse.ArgumentParser()
    p.add_argument("countries", nargs="*", default=["Taiwan", "China"])
    p.add_argument("--as-of", default=None)
    args = p.parse_args()

    os.makedirs("outputs", exist_ok=True)
    for c in args.countries:
        report = run(c, args.as_of)
        print("\n" + report.model_dump_json(indent=2))
        with open(f"outputs/{report.entity.ticker}_geopolitical.json", "w", encoding="utf-8") as fh:
            fh.write(report.model_dump_json(indent=2))
        unverified = [cl.id for cl in report.claims if not cl.quote_verified]
        if unverified:
            print(f"WARNING: quotes not found in tool output: {unverified}")
        try:
            resolve_citations(report.summary, [report])  # every sentence must cite a valid claim id
        except CitationError as e:
            print(f"WARNING: citation check failed: {e}")
