import pytest

from core.citations import CitationError, format_references, resolve_citations
from core.schemas import AgentOutput, Claim, Entity, Source


def _out() -> AgentOutput:
    src = Source(title="ASML 2025 Annual Report", url="https://x", locator="p.112", retrieved_at="2026-11-10")
    c = Claim(id="filings:ASML:003", channel="export_controls", statement="~25% of revenue from China",
              value=0.25, unit="revenue_share", score=4, confidence=0.8, sources=[src])
    return AgentOutput(agent="filings", entity=Entity(ticker="ASML", country="NL"),
                       as_of="2026-11-10", claims=[c], summary="x [filings:ASML:003].")


def test_resolves_ids_to_references():
    text, cited = resolve_citations("China matters [filings:ASML:003]. Still true [filings:ASML:003].", [_out()])
    assert text == "China matters [1]. Still true [1]."
    assert "ASML 2025 Annual Report" in format_references(cited)


def test_sentence_without_id_fails():
    with pytest.raises(CitationError):
        resolve_citations("Cited [filings:ASML:003]. Uncited sentence.", [_out()])


def test_unknown_id_fails():
    with pytest.raises(CitationError):
        resolve_citations("Bogus [filings:ASML:099].", [_out()])
