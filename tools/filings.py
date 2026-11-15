"""SEC annual filings (edgartools), point in time, as tools for the filings agent.

One `FilingSession` per company and run: it keeps every text returned to the model (to verify quotes afterwards),
the filing's metadata (to attach sources) and the search budget. No global state, so runs can overlap."""
import re
from datetime import datetime, timezone
from functools import lru_cache

from edgar import Company, set_identity

from core.config import SEC_IDENTITY
from core.llm import Tool

if SEC_IDENTITY:
    set_identity(SEC_IDENTITY)

ANNUAL_FORMS = ["10-K", "20-F", "40-F"]
MAX_CHARS = 12_000
MAX_SEARCHES = 6   # without a cap the agent keeps searching filings that answer nothing (40-F wrappers)


@lru_cache(maxsize=64)
def _annual_filing(ticker: str, as_of: str):
    """Most recent annual filing with filing_date <= as_of (YYYY-MM-DD)."""
    filings = Company(ticker).get_filings(form=ANNUAL_FORMS, amendments=False, filing_date=f":{as_of}")
    if filings is None or len(filings) == 0:
        raise ValueError(f"No annual filing found for {ticker} on or before {as_of}")
    return filings.latest()


def _norm(s: str) -> str:
    s = s.replace("’", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s).strip().lower()


def quote_in(quote: str, text: str) -> bool:
    q = _norm(quote)
    return bool(q) and q in _norm(text)


def _chunks(text: str, size: int = 12_000, overlap: int = 500) -> list[str]:
    out, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            boundary = text.rfind(" ", start, end)
            if boundary > start + overlap:
                end = boundary
        out.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap
    return out


def risk_section(ticker: str, as_of: str) -> dict:
    """The full Risk Factors section of the latest annual filing on or before as_of, in ~12k-character passages.
    status "manual_review" (no passages) when the section's boundaries cannot be verified."""
    ticker = ticker.upper()
    filing = _annual_filing(ticker, as_of)
    report = filing.obj()
    section = "Item 1A" if filing.form == "10-K" else "Item 3.D" if filing.form == "20-F" else "Risk Factors"
    url, text, reason = filing.filing_url, report.risk_factors, None
    if not isinstance(text, str) or not text.strip():
        reason = "The Risk Factors section could not be located."
    elif filing.form == "10-K":
        if not any(item in report.items for item in ("Item 1B", "Item 1C", "Item 2")):
            reason = "The end of the 10-K Risk Factors section could not be verified."
    elif filing.form == "20-F":
        heading = re.search(r"(?im)^[ \t]*(?:(?:item[ \t]+)?3[.\s]*d[.:\s-]*|d[.:\s-]+)?risk[ \t]+factors[ \t]*[.:]?[ \t]*$",
                            text) if "Item 4" in report.items else None
        if heading is None:
            reason = "The 20-F Risk Factors section could not be located."
        else:
            text = text[heading.start():]
    elif filing.form == "40-F":
        if re.search(r"\b(?:incorporat\w*\s+by\s+reference|refer(?:s|red)?\s+to)\b", text, re.I):
            reason = "The 40-F risk section refers to other documents."
        elif report.aif_attachment is not None:
            url = report.aif_attachment.url
    base = {"ticker": ticker, "form": filing.form, "filing_date": str(filing.filing_date), "section": section,
            "url": url, "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if reason:
        return {**base, "status": "manual_review", "reason": reason, "chunks": []}
    return {**base, "status": "available", "reason": None, "chunks": _chunks(text)}


class FilingSession:
    def __init__(self, ticker: str, as_of: str):
        self.ticker, self.as_of = ticker.upper(), as_of
        self.texts: list[str] = []
        self.meta: dict = {}
        self.searches = 0

    def _filing(self):
        f = _annual_filing(self.ticker, self.as_of)
        self.meta = {"form": f.form, "filing_date": str(f.filing_date), "accession": f.accession_no, "url": f.filing_url}
        return f

    def _keep(self, text: str) -> str:
        self.texts.append(text)
        return text

    def info(self) -> dict:
        self._filing()
        return self.meta

    def risk_factors(self) -> dict:
        f = self._filing()
        text = None
        if f.form == "10-K":
            try:
                text = f.obj().risk_factors
            except Exception:
                text = None
        if not text:   # 20-F / 40-F or parsing failure: fall back to grep
            text = "\n...\n".join(m.context for m in f.grep("risk factor")[:20])
        text = re.sub(r"\s+", " ", str(text))
        return {**self.meta, "section": "Risk Factors", "truncated": len(text) > MAX_CHARS,
                "text": self._keep(text[:MAX_CHARS])}

    def search(self, pattern: str) -> dict:
        self.searches += 1
        if self.searches > MAX_SEARCHES:
            return {"error": f"search budget of {MAX_SEARCHES} used. Stop calling tools and write the claims now."}
        f = self._filing()
        matches = [{"location": m.location, "context": self._keep(re.sub(r"\s+", " ", m.context))}
                   for m in f.grep(pattern)[:8]]
        return {**self.meta, "pattern": pattern, "n_matches": len(matches), "matches": matches}

    def verified(self, quote: str) -> bool:
        """Exact-substring check (whitespace and quotes normalised) against the text the model was given."""
        return any(quote_in(quote, t) for t in self.texts)

    def tools(self) -> list[Tool]:
        none = {"type": "object", "properties": {}}
        return [
            Tool("get_annual_filing_info", "Metadata of the latest annual filing (10-K, 20-F or 40-F) on or before "
                 "the analysis date.", none, lambda: self.info()),
            Tool("get_risk_factors", "The Risk Factors section (Item 1A) of that filing, cut to 12,000 characters.",
                 none, lambda: self.risk_factors()),
            Tool("search_filing", "Case-insensitive search in that filing, up to 8 passages. Good patterns: a country "
                 "('China', 'Taiwan'), 'geographic', 'sanctions', 'export control', 'tariff', 'supplier'.",
                 {"type": "object", "properties": {"pattern": {"type": "string"}}, "required": ["pattern"]},
                 lambda pattern: self.search(pattern)),
        ]
