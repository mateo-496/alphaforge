"""Geopolitical claims agent: atomic, cited claims about one country's Geopolitical Risk (GPR) index history.

Code sends the last 36 monthly rows published before the analysis date (country GPR = % of newspaper articles,
global GPR index) from tools/gpr.py. The model writes claims (level, trend, spikes, versus history or the global
index), each with a quote; code keeps only claims whose quote is found verbatim in the data it sent.
Severity and confidence are shown as the agent's view, never scored.

    python -m agents.geopolitical_claims_agent TWN --as-of 2026-11-12
"""
import argparse
import json
from datetime import datetime, timezone

from core import llm
from core.schemas import AgentOutput, Claim, DraftOutput, Entity, Source
from tools import gpr
from tools.filings import quote_in

AGENT = "geopolitical_claims"
MONTHS = 36
SYSTEM_PROMPT = """You are the Geopolitical analyst of AlphaForge. From the GPR data you are given for ONE country,
write atomic claims: current level, trend, spikes, level versus the country's own past rows, versus the global index.
Data: "gprc" = share (%) of newspaper articles about geopolitical risk involving the country; "gpr" = global
index (1985-2019 = 100). Use no outside knowledge of events.
- channel: "conflict_exposure" unless the data clearly supports another channel of the taxonomy.
- value + unit: the number the claim rests on ("pct_articles" for gprc, "index" for gpr).
- evidence_quote: copied VERBATIM from the data JSON, a contiguous piece of one row,
  e.g. "month": "2026-10", "gprc": 0.52 . Never reformat numbers.
- locator: series and month, e.g. "gprc, 2026-10".
- score = severity 0-5; confidence = 0-1 that the claim is correctly read.
- summary: one or two sentences, each ending with claim citations by position, e.g. "... [1][3]."
- At most 5 claims, most material first."""


def data(tbl: dict, iso3: str, as_of: str) -> dict | None:
    s = tbl["series"].get(iso3)
    if not s:
        return None
    g = tbl["series"]["GLOBAL"]
    rows = [{"month": m, "gpr": gv, "gprc": cv} for m, gv, cv in zip(tbl["months"], g, s)
            if m < as_of[:7] and cv is not None][-MONTHS:]
    return {"country": iso3, "rows": rows} if rows else None


def run(iso3: str, as_of: str, tbl: dict | None = None) -> AgentOutput | None:
    """Verified claims for one country; None if the GPR index does not cover it."""
    tbl = tbl or gpr.table()
    d = data(tbl, iso3, as_of)
    if not d:
        return None
    text = json.dumps(d)
    draft = llm.ask(AGENT, SYSTEM_PROMPT, text, DraftOutput, max_tokens=2000)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    claims = [Claim(id=f"{AGENT}:{iso3}:{n:03d}", quote_verified=True,
                    sources=[Source(title=f"Geopolitical Risk index — {gpr.CITATION}", url=tbl["url"],
                                    locator=c.locator, retrieved_at=tbl.get("retrieved_at") or now)],
                    **c.model_dump(exclude={"locator"}))
              for n, c in enumerate((c for c in draft.claims if quote_in(c.evidence_quote, text)), 1)]
    whole = claims and len(claims) == len(draft.claims)   # the summary cites by position: only valid if none dropped
    return AgentOutput(agent=AGENT, entity=Entity(country=iso3), as_of=as_of, claims=claims,
                       summary=draft.summary if whole else "")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("country")
    p.add_argument("--as-of", required=True)
    a = p.parse_args()
    r = run(a.country.upper(), a.as_of)
    print(r.model_dump_json(indent=2) if r else "Not covered by the GPR index")
