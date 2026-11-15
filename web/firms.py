"""Company disclosures on the largest equity holdings, cached per company and month:
  * filings agent (agents/filings_agent.py): geopolitical claims -> firm term f_i = share of the 8 risk channels
    with a VERIFIED verbatim quote (code-checked); the agent's severity grades are context only;
  * filing-risk agent (agents/filing_risk_agent.py): every risk disclosed in the Risk Factors section, quotes
    checked word for word; context only."""
import threading
from concurrent.futures import Future, ThreadPoolExecutor, wait

from agents import filing_risk_agent, filings_agent
from core import config, storage
from tools import risk_math
from web.market import sec_ticker

TOP_N, PARALLEL = config.FILINGS_TOP_N, config.FILINGS_PARALLEL
# How long the run waits for the filings agent. Companies not finished by then keep running in the
# background and write their cache entry, so the next analysis this month picks them up instantly.
# The report never waits minutes for a term worth 20% of a holding's score.
WAIT_S = config.FILINGS_WAIT_S   # None (default): wait until every company is read and saved
# Step-1 statuses that mean the filing has no usable 10-K / 20-F text (40-F filers: RY, TD, ENB, CNQ...).
SKIP_STATUS = {"no_sec_ticker", "no_annual_filing", "error", "blocked"}


def _claims(ticker: str, sec_t: str, as_of: str) -> dict:
    """Filings agent -> f_i inputs (verified channels) and the claims shown in the report."""
    rep = filings_agent.run(sec_t, as_of)
    claims = sorted(rep.claims, key=lambda c: -(c.score * c.confidence))
    verified = [c for c in claims if c.quote_verified]
    src = next((s for c in claims for s in c.sources), None)
    return {"status": "ok", "score": round(5 * risk_math.claim_quality(claims), 2) if claims else None,   # shown, not scored
            "n_claims": len(claims), "n_verified": len(verified),
            "channels": sorted({c.channel for c in verified}),   # f_i = len(channels) / 8, counted by code
            "claims": [{"channel": c.channel, "statement": c.statement, "score": c.score, "confidence": c.confidence,
                        "quote": c.evidence_quote, "verified": bool(c.quote_verified),
                        "url": c.sources[0].url if c.sources else "", "locator": c.sources[0].locator if c.sources else ""}
                       for c in (verified or claims)[:4]],
            "filing": {"name": src.title, "url": src.url, "retrieved": src.retrieved_at} if src else None}


def _err(e: Exception) -> str:
    return f"{type(e).__name__}: {str(e)[:160]}"


def _read(ticker: str, sec_t: str, as_of: str, key: str) -> dict:
    """Both filing agents on one company, at the same time; saved when the filings agent succeeded."""
    with ThreadPoolExecutor(max_workers=2) as pool:
        f_claims = pool.submit(_claims, ticker, sec_t, as_of)
        f_risks = pool.submit(filing_risk_agent.run, sec_t, as_of)
        try:
            out = f_claims.result()
        except Exception as e:   # missing filing, SEC or Bedrock error: recorded, never fatal
            out = {"status": "error", "score": None, "claims": [], "error": _err(e)}
        try:
            out["risk_factors"] = f_risks.result()
        except Exception as e:
            out["risk_factors"] = {"status": "error", "risks": [], "reason": _err(e)}
    out = {"ticker": ticker, "sec_ticker": sec_t, **out}
    if out["status"] == "ok":
        storage.write_json(key, out)
    return out


# Reads in progress, shared by every run that needs the same company and month: a second analysis started while
# the first is still reading (or reading in the background) waits for that read instead of starting another.
_inflight: dict[str, Future] = {}
_inflight_lock = threading.Lock()
_readers = ThreadPoolExecutor(max_workers=PARALLEL * 2, thread_name_prefix="firms")


def _shared_read(ticker: str, sec_t: str, as_of: str, key: str) -> Future:
    with _inflight_lock:
        fut = _inflight.get(key)
        if fut is None:
            fut = _inflight[key] = _readers.submit(_read, ticker, sec_t, as_of, key)
            fut.add_done_callback(lambda f: _inflight.pop(key, None))
        return fut


def _one(ticker: str, sec_t: str, as_of: str, emit) -> dict:
    """One company: the saved read for this month, else the (shared) read in progress."""
    key = f"firms/v3/{sec_t}_{as_of[:7]}.json"
    cached = storage.read_json(key)
    if cached:
        cached = {**cached, "ticker": ticker}
        emit("done", ticker, sec_t, cached, True)
        return cached
    emit("start", ticker, sec_t, None, False)
    out = {**_shared_read(ticker, sec_t, as_of, key).result(), "ticker": ticker}
    emit("done", ticker, sec_t, out, False)
    return out


def picks(weights: dict, uni: dict, statuses: dict | None = None) -> list[tuple[str, str]]:
    """The TOP_N largest equity holdings with a readable 10-K / 20-F: (ticker, SEC ticker)."""
    statuses = statuses or {}
    out = [(t, sec_ticker(t, uni[t])) for t, _ in sorted(weights.items(), key=lambda kv: -kv[1])
           if uni[t]["asset_class"] == "equity" and statuses.get(t) not in SKIP_STATUS]
    return [(t, s) for t, s in out if s][:TOP_N]


def analyse(weights: dict, uni: dict, as_of: str, emit, statuses: dict | None = None,
            wait_s: float | None | str = "default") -> dict[str, dict]:
    """Run the filings agent on the TOP_N largest equity holdings with a readable 10-K / 20-F.
    Cached companies return at once; the rest get `wait_s` seconds (None = until done), then come back as status
    "pending" while their agent finishes in the background (result cached for the next run)."""
    chosen = picks(weights, uni, statuses)
    if not chosen:
        return {}
    wait_s = WAIT_S if wait_s == "default" else wait_s
    closed, lock = set(), threading.Lock()

    def once(status, t, sec_t, out, cached):   # a late background thread must not emit a second "done"
        with lock:
            if status == "done":
                if t in closed:
                    return
                closed.add(t)
        emit(status, t, sec_t, out, cached)

    pool = ThreadPoolExecutor(max_workers=PARALLEL)
    futs = {pool.submit(_one, t, s, as_of, once): (t, s) for t, s in chosen}
    done, pending = wait(futs, timeout=wait_s)
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
