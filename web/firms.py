"""Company disclosures: the filings agent (agents/filings_agent.py, Strands tool loop over the SEC filing)
run on the largest equity holdings. Each result is cached per company and month, so repeat analyses are instant.

Firm term f_i = share of the 8 risk channels for which the filing has a VERIFIED verbatim quote (code-checked).
The agent's own severity scores are shown as context only; they never enter the risk score."""
import os
import threading
from concurrent.futures import ThreadPoolExecutor, wait

from core import storage
from tools import risk_math
from web.market import sec_ticker

TOP_N = int(os.environ.get("FILINGS_TOP_N", "5"))
PARALLEL = int(os.environ.get("FILINGS_PARALLEL", "3"))
# How long the run waits for the filings agent. Companies not finished by then keep running in the
# background and write their cache entry, so the next analysis this month picks them up instantly.
# The report never waits minutes for a term worth 20% of a holding's score.
WAIT_S = int(os.environ.get("FILINGS_WAIT_S", "45"))
# Step-1 statuses that mean the filing has no usable 10-K / 20-F text (40-F filers: RY, TD, ENB, CNQ...).
SKIP_STATUS = {"no_sec_ticker", "no_annual_filing", "error"}


def _one(ticker: str, sec_t: str, as_of: str, emit) -> dict:
    key = f"firms/{sec_t}_{as_of[:7]}.json"
    cached = storage.read_json(key)
    if cached and cached.get("status") == "ok" and "channels" not in cached:   # entries written before v2
        cached["channels"] = sorted({c["channel"] for c in cached.get("claims", []) if c.get("verified")})
    if cached:
        emit("done", ticker, sec_t, cached, True)
        return cached
    emit("start", ticker, sec_t, None, False)
    try:
        from agents import filings_agent
        rep = filings_agent.run(sec_t, as_of)
        claims = sorted(rep.claims, key=lambda c: -(c.score * c.confidence))
        verified = [c for c in claims if c.quote_verified]
        src = next((s for c in claims for s in c.sources), None)
        out = {"ticker": ticker, "sec_ticker": sec_t, "status": "ok",
               "score": round(risk_math.q_bar(claims), 2) if claims else None,
               "n_claims": len(claims), "n_verified": len(verified),
               "channels": sorted({c.channel for c in verified}),   # f_i = len(channels) / 8, counted by code
               "claims": [{"channel": c.channel, "statement": c.statement, "score": c.score, "confidence": c.confidence,
                           "quote": c.evidence_quote, "verified": bool(c.quote_verified),
                           "url": c.sources[0].url if c.sources else "", "locator": c.sources[0].locator if c.sources else ""}
                          for c in (verified or claims)[:4]],
               "filing": {"name": src.title, "url": src.url, "retrieved": src.retrieved_at} if src else None}
        storage.write_json(key, out)
    except Exception as e:  # missing filing, SEC or Bedrock error: recorded, never fatal
        out = {"ticker": ticker, "sec_ticker": sec_t, "status": "error", "score": None, "claims": [],
               "error": f"{type(e).__name__}: {str(e)[:160]}"}
    emit("done", ticker, sec_t, out, False)
    return out


def analyse(weights: dict, uni: dict, as_of: str, emit, statuses: dict | None = None) -> dict[str, dict]:
    """Run the filings agent on the TOP_N largest equity holdings with a readable 10-K / 20-F.
    Cached companies return at once; the rest get WAIT_S seconds, then come back as status "pending"
    while their agent finishes in the background (result cached for the next run)."""
    statuses = statuses or {}
    picks = [(t, sec_ticker(t, uni[t])) for t, _ in sorted(weights.items(), key=lambda kv: -kv[1])
             if uni[t]["asset_class"] == "equity" and statuses.get(t) not in SKIP_STATUS]
    picks = [(t, s) for t, s in picks if s][:TOP_N]
    if not picks:
        return {}
    closed, lock = set(), threading.Lock()

    def once(status, t, sec_t, out, cached):   # a late background thread must not emit a second "done"
        with lock:
            if status == "done":
                if t in closed:
                    return
                closed.add(t)
        emit(status, t, sec_t, out, cached)

    pool = ThreadPoolExecutor(max_workers=PARALLEL)
    futs = {pool.submit(_one, t, s, as_of, once): (t, s) for t, s in picks}
    done, pending = wait(futs, timeout=WAIT_S)
    pool.shutdown(wait=False)   # unfinished agents keep going and fill the cache
    res = {}
    for f in done:
        r = f.result()
        res[r["ticker"]] = r
    for f in pending:
        t, s = futs[f]
        res[t] = {"ticker": t, "sec_ticker": s, "status": "pending", "score": None, "claims": [],
                  "error": "still reading; included in the next analysis"}
        once("done", t, s, res[t], False)
    return res
