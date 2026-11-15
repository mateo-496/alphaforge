"""Filings tools: SEC annual filings via edgartools, point-in-time.
Plain Strands @tool functions: used by agents locally, wrapped by Lambda for AgentCore Gateway later."""
import re
from datetime import date, datetime, timezone
from functools import lru_cache

from edgar import Company, set_identity
from strands import tool

from core.config import SEC_IDENTITY

set_identity(SEC_IDENTITY)

ANNUAL_FORMS = ["10-K", "20-F", "40-F"]
MAX_CHARS = 12_000

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
    f = _annual_filing(ticker.upper(), as_of)
    matches = [{"location": m.location,
                "context": _remember(ticker, re.sub(r"\s+", " ", m.context))}
               for m in f.grep(pattern)[:max_matches]]
    return {**_meta(f, ticker), "pattern": pattern, "n_matches": len(matches), "matches": matches}


def quote_is_verified(ticker: str, quote: str) -> bool:
    """Exact-substring check (whitespace/quotes normalized) against retrieved text."""
    return any(quote_is_in_text(quote, text) for text in RETRIEVED_TEXT.get(ticker.upper(), []))


def quote_is_in_text(quote: str, text: str) -> bool:
    def norm(s: str) -> str:
        s = s.replace("’", "'").replace("“", '"').replace("”", '"')
        return re.sub(r"\s+", " ", s).strip().lower()
    q = norm(quote)
    return bool(q) and q in norm(text)


def _risk_chunks(text: str, size: int = 12000, overlap: int = 500) -> list[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            boundary = text.rfind(" ", start, end)
            if boundary > start + overlap:
                end = boundary
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap
    return chunks


def get_filing_risk_section(ticker: str, as_of: str) -> dict:
    """Get the annual filing's risk section, or request manual review if ambiguous."""
    date.fromisoformat(as_of)
    if not SEC_IDENTITY or "@" not in SEC_IDENTITY or "example.com" in SEC_IDENTITY.lower():
        raise ValueError("SEC_IDENTITY must contain an application name and real contact email")
    ticker = ticker.upper()
    filing = _annual_filing(ticker, as_of)
    report = filing.obj()
    meta = _meta(filing)
    section = "Item 1A" if filing.form == "10-K" else "Item 3.D" if filing.form == "20-F" else "Risk Factors"
    url = meta["url"]
    text = report.risk_factors
    reason = None
    if not isinstance(text, str) or not text.strip():
        reason = "The Risk Factors section could not be located."
    elif filing.form == "10-K":
        if not any(item in report.items for item in ("Item 1B", "Item 1C", "Item 2")):
            reason = "The end of the 10-K Risk Factors section could not be verified."
    elif filing.form == "20-F":
        if "Item 4" not in report.items:
            reason = "The end of the 20-F Risk Factors section could not be verified."
        else:
            heading = re.search(
                r"(?im)^[ \t]*(?:(?:item[ \t]+)?3[.\s]*d[.:\s-]*|d[.:\s-]+)?"
                r"risk[ \t]+factors[ \t]*[.:]?[ \t]*$", text)
            if heading is None:
                reason = "The 20-F Risk Factors heading could not be located."
            else:
                text = text[heading.start():]
    elif filing.form == "40-F":
        if re.search(r"\b(?:incorporat\w*\s+by\s+reference|refer(?:s|red)?\s+to)\b", text, re.I):
            reason = "The 40-F risk section refers to other documents and requires manual review."
        elif report.aif_attachment is not None:
            url = report.aif_attachment.url
    else:
        raise ValueError(f"Unsupported filing form: {filing.form}")
    base = {"ticker": ticker, "form": filing.form, "filing_date": meta["filing_date"],
            "section": section, "url": url}
    if reason:
        return {**base, "status": "manual_review", "reason": reason, "chunks": []}
    return {**base, "status": "available", "reason": None, "chunks": _risk_chunks(text),
            "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def verify_filing_risk_quotes(text: str, quotes: list[str]) -> dict:
    """Verify quotations against the exact section excerpt supplied to the model."""
    return {"verified": [quote_is_in_text(quote, text) for quote in quotes]}
