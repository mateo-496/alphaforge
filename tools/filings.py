"""Filings tools: SEC annual filings via edgartools, point-in-time.
Plain Strands @tool functions: used by agents locally, wrapped by Lambda for AgentCore Gateway later."""
import re
from functools import lru_cache

from edgar import Company, set_identity
from strands import tool

from core.config import SEC_IDENTITY

set_identity(SEC_IDENTITY)

ANNUAL_FORMS = ["10-K", "20-F", "40-F"]
MAX_CHARS = 12_000
# Searches per company. Without a cap the agent keeps searching filings that answer nothing (40-F wrappers),
# which made one company take minutes. After the cap the tool tells the model to write its answer.
MAX_SEARCHES = 6
SEARCHES: dict[str, int] = {}

# Every text returned to the model, used afterwards to verify evidence quotes.
RETRIEVED_TEXT: dict[str, list[str]] = {}
# Metadata of the filing each ticker's run used (form, filing_date, accession, url).
FILING_META: dict[str, dict] = {}


def _remember(ticker: str, text: str) -> str:
    RETRIEVED_TEXT.setdefault(ticker.upper(), []).append(text)
    return text


@lru_cache(maxsize=64)
def _annual_filing(ticker: str, as_of: str):
    """Most recent annual filing with filing_date <= as_of (YYYY-MM-DD)."""
    filings = Company(ticker).get_filings(form=ANNUAL_FORMS, amendments=False,
                                          filing_date=f":{as_of}")
    if filings is None or len(filings) == 0:
        raise ValueError(f"No annual filing found for {ticker} on or before {as_of}")
    return filings.latest()


def _meta(f, ticker: str | None = None) -> dict:
    meta = {"form": f.form, "filing_date": str(f.filing_date),
            "accession": f.accession_no, "url": f.filing_url}
    if ticker:
        FILING_META[ticker.upper()] = meta  # used by code to attach sources to claims
    return meta


@tool
def get_annual_filing_info(ticker: str, as_of: str) -> dict:
    """Get metadata of the latest annual filing (10-K, 20-F or 40-F) filed on or before a date.

    Args:
        ticker: Stock ticker, e.g. "NVDA".
        as_of: Point-in-time date YYYY-MM-DD. Never use information filed after it.
    """
    return _meta(_annual_filing(ticker.upper(), as_of), ticker)


@tool
def get_risk_factors(ticker: str, as_of: str) -> dict:
    """Get the Risk Factors section (Item 1A) of the latest annual filing on or before a date.

    Args:
        ticker: Stock ticker.
        as_of: Point-in-time date YYYY-MM-DD.
    """
    f = _annual_filing(ticker.upper(), as_of)
    text = None
    if f.form == "10-K":
        try:
            text = f.obj().risk_factors
        except Exception:
            text = None
    if not text:  # 20-F / 40-F or parsing failure: fall back to grep
        text = "\n...\n".join(m.context for m in f.grep("risk factor")[:20])
    text = re.sub(r"\s+", " ", str(text))
    truncated = len(text) > MAX_CHARS
    return {**_meta(f, ticker), "section": "Risk Factors", "truncated": truncated,
            "text": _remember(ticker, text[:MAX_CHARS])}


@tool
def search_filing(ticker: str, as_of: str, pattern: str, max_matches: int = 15) -> dict:
    """Case-insensitive search in the latest annual filing on or before a date.
    Use it for countries ("China", "Taiwan"), "geographic", "revenue by region",
    "sanctions", "export controls", "tariff", "supplier", "manufactur".

    Args:
        ticker: Stock ticker.
        as_of: Point-in-time date YYYY-MM-DD.
        pattern: Text to search for.
        max_matches: Max number of matching passages to return.
    """
    n = SEARCHES[ticker.upper()] = SEARCHES.get(ticker.upper(), 0) + 1
    if n > MAX_SEARCHES:
        return {"error": f"search budget of {MAX_SEARCHES} used. Stop calling tools and write the claims now."}
    f = _annual_filing(ticker.upper(), as_of)
    matches = [{"location": m.location,
                "context": _remember(ticker, re.sub(r"\s+", " ", m.context))}
               for m in f.grep(pattern)[:min(max_matches, 8)]]
    return {**_meta(f, ticker), "pattern": pattern, "n_matches": len(matches), "matches": matches}


def quote_is_verified(ticker: str, quote: str) -> bool:
    """Exact-substring check (whitespace/quotes normalized) against retrieved text."""
    def norm(s: str) -> str:
        s = s.replace("’", "'").replace("“", '"').replace("”", '"')
        return re.sub(r"\s+", " ", s).strip().lower()
    q = norm(quote)
    return bool(q) and any(q in norm(t) for t in RETRIEVED_TEXT.get(ticker.upper(), []))
