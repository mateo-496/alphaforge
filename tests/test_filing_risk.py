import asyncio
import threading
import time
from types import SimpleNamespace

import pytest

from agents import filing_risk_agent
from core.filing_risk import DraftFilingRisks, QuoteCorrections
from core.citations import resolve_citations
from tests.test_market_stress import mcp_server_url
from tools import filings


@pytest.fixture(autouse=True)
def disable_filing_rag(monkeypatch):
    monkeypatch.setenv("ENABLE_FILING_RAG", "0")
    monkeypatch.setenv("ENABLE_FILINGS_RAG", "0")


def _draft(data):
    return DraftFilingRisks.model_validate({"risks": [
        {"score": 3, "confidence": 0.8, **risk} for risk in data["risks"]]})


def _filing(form, text, items, attachment=None):
    report = SimpleNamespace(risk_factors=text, items=items, aif_attachment=attachment)
    return SimpleNamespace(form=form, filing_date="2026-02-25", accession_no="123",
                           filing_url="https://www.sec.gov/filing", obj=lambda: report)


def test_full_10k_section_is_chunked_without_truncation(monkeypatch):
    text = "Item 1A. Risk Factors " + ("risk paragraph " * 2000) + "FINAL RISK"
    monkeypatch.setattr(filings, "SEC_IDENTITY", "Example researcher contact@domain.org")
    monkeypatch.setattr(filings, "_annual_filing",
                        lambda ticker, as_of: _filing("10-K", text, ["Item 1A", "Item 1B"]))
    result = filings.get_filing_risk_section("NVDA", "2026-11-14")
    assert result["status"] == "available"
    assert len(result["chunks"]) > 1
    assert result["chunks"][0].startswith("Item 1A")
    assert result["chunks"][-1].endswith("FINAL RISK")
    assert all(len(chunk) <= 12000 for chunk in result["chunks"])


def test_20f_requires_detectable_section_boundaries(monkeypatch):
    monkeypatch.setattr(filings, "SEC_IDENTITY", "Example researcher contact@domain.org")
    text = "Other financial information\nD. Risk Factors\nRisk disclosed in section."
    filing = _filing("20-F", text, ["Item 3", "Item 4"])
    monkeypatch.setattr(filings, "_annual_filing", lambda ticker, as_of: filing)
    result = filings.get_filing_risk_section("ASML", "2026-11-14")
    assert result["status"] == "available"
    assert result["chunks"] == ["D. Risk Factors\nRisk disclosed in section."]
    filing.obj().items.remove("Item 4")
    result = filings.get_filing_risk_section("ASML", "2026-11-14")
    assert result["status"] == "manual_review"
    assert result["chunks"] == []


def test_40f_reference_is_not_treated_as_complete_risks(monkeypatch):
    monkeypatch.setattr(filings, "SEC_IDENTITY", "Example researcher contact@domain.org")
    filing = _filing("40-F", "Risk factors are incorporated by reference in the annual report.",
                     ["Risk Factors"], SimpleNamespace(url="https://www.sec.gov/exhibit"))
    monkeypatch.setattr(filings, "_annual_filing", lambda ticker, as_of: filing)
    result = filings.get_filing_risk_section("RY", "2026-11-14")
    assert result["status"] == "manual_review"
    assert "other documents" in result["reason"]


def test_40f_direct_risks_cite_the_annual_information_form(monkeypatch):
    monkeypatch.setattr(filings, "SEC_IDENTITY", "Example researcher contact@domain.org")
    filing = _filing("40-F", "Risk Factors\nThe business faces supply disruptions.",
                     ["Risk Factors"], SimpleNamespace(url="https://www.sec.gov/exhibit"))
    monkeypatch.setattr(filings, "_annual_filing", lambda ticker, as_of: filing)
    result = filings.get_filing_risk_section("RY", "2026-11-14")
    assert result["status"] == "available"
    assert result["url"] == "https://www.sec.gov/exhibit"


def test_agent_reports_verified_risks_and_ambiguous_company(mcp_server_url, monkeypatch):
    monkeypatch.setenv("MCP_SERVER_URL", mcp_server_url)

    def section(ticker, as_of):
        base = {"ticker": ticker, "form": "10-K" if ticker == "NVDA" else "20-F",
                "filing_date": "2026-02-25", "section": "Risk Factors",
                "url": "https://www.sec.gov/filing"}
        if ticker == "ASML":
            return {**base, "status": "manual_review", "reason": "Ambiguous section", "chunks": []}
        return {**base, "status": "available", "reason": None,
                "chunks": ["Supply shortages may disrupt production."],
                "retrieved_at": "2026-11-14T00:00:00Z"}

    monkeypatch.setattr("tools.filings.get_filing_risk_section", section)
    quote = ["Supply shortages may disrupt production."]

    def extract(text):
        return _draft({"risks": [
            {"category": "Supply chain", "evidence_quote": quote[0]}]})

    monkeypatch.setattr(filing_risk_agent, "_extract_risks", extract)
    csv = "ticker,weight\nNVDA,0.4\nASML,0.6\n"
    report = asyncio.run(filing_risk_agent.run(csv))
    assert report.reports[0].claims[0].evidence_quote == quote[0]
    assert report.reports[0].claims[0].channel == "filing_risk"
    assert report.reports[0].claims[0].score == 3
    assert report.reports[0].claims[0].confidence == 0.8
    assert report.reports[0].claims[0].quote_verified is True
    assert report.reports[0].claims[0].value is None
    resolve_citations(report.reports[0].summary, report.reports)
    assert report.indexing.status == "disabled"
    assert report.companies[1].status == "manual_review"
    assert report.companies[1].reason == "Ambiguous section"
    assert report.reports[1].claims == []
    quote[0] = "Unsubstantiated quote"
    attempts = []

    def repair(segments, risks):
        attempts.append(risks)
        return QuoteCorrections.model_validate({"corrections": [
            {"position": risk["position"], "start_segment": None, "end_segment": None}
            for risk in risks]})

    monkeypatch.setattr(filing_risk_agent, "_repair_quotes", repair)
    report = asyncio.run(filing_risk_agent.run(csv))
    assert report.companies[0].status == "manual_review"
    assert "Unverified quote" in report.companies[0].reason
    assert report.reports[0].claims == []
    assert report.companies[1].status == "manual_review"
    assert len(attempts) == 2


def test_invalid_quotes_are_repaired_and_reverified(monkeypatch):
    text = ('Supply shortages may disrupt production. Customers may not adopt our new 16 '
            'products as fast as forecasted. Products may be resold on the unauthorized '
            '“gray market,” which makes demand forecasting difficult.')
    draft = _draft({"risks": [
        {"category": "Supply", "evidence_quote": "Supply shortages may disrupt production."},
        {"category": "Adoption", "evidence_quote": "Customers may not adopt our new products as fast as forecasted."},
        {"category": "Resale", "evidence_quote": "Products may be resold on the unauthorized 'gray market',"},
    ]})
    monkeypatch.setattr(filing_risk_agent, "_extract_risks", lambda _: draft)
    calls = []

    async def verify(session, name, arguments):
        calls.append(arguments["quotes"])
        return filings.verify_filing_risk_quotes(arguments["text"], arguments["quotes"])

    def repair(segments, rejected):
        assert all(segment in text for segment in segments)
        assert [item["position"] for item in rejected] == [1, 2]
        return QuoteCorrections.model_validate({"corrections": [
            {"position": 2, "start_segment": 0, "end_segment": 1},
            {"position": 1, "start_segment": 0, "end_segment": 1},
        ]})

    monkeypatch.setattr(filing_risk_agent, "call_tool", verify)
    monkeypatch.setattr(filing_risk_agent, "_repair_quotes", repair)
    result = asyncio.run(filing_risk_agent._verified_risks(None, "NVDA", 2, text))
    assert len(calls) == 2
    assert [risk.category for risk in result] == ["Supply", "Adoption", "Resale"]
    assert result[0] == draft.risks[0]
    assert "new 16 products" in result[1].evidence_quote
    assert "“gray market,”" in result[2].evidence_quote
    assert all(filings.quote_is_in_text(risk.evidence_quote, text) for risk in result)


def test_unverified_company_discards_partial_risks_and_continues(mcp_server_url, monkeypatch):
    monkeypatch.setenv("MCP_SERVER_URL", mcp_server_url)

    def section(ticker, as_of):
        return {"ticker": ticker, "form": "10-K", "filing_date": "2026-02-25",
                "section": "Risk Factors", "url": "https://www.sec.gov/filing",
                "status": "available", "reason": None,
                "chunks": ["First real risk.", "Second real risk."] if ticker == "NVDA" else ["Other real risk."],
                "retrieved_at": "2026-11-14T00:00:00Z"}

    monkeypatch.setattr("tools.filings.get_filing_risk_section", section)
    monkeypatch.setattr(filing_risk_agent, "_extract_risks", lambda text:
                        _draft({"risks": [
                            {"category": "Risk", "evidence_quote": "invented" if text.startswith("Second") else text}]}))
    monkeypatch.setattr(filing_risk_agent, "_repair_quotes", lambda segments, risks:
                        QuoteCorrections.model_validate({"corrections": [
                            {"position": item["position"], "start_segment": None, "end_segment": None}
                            for item in risks]}))
    report = asyncio.run(filing_risk_agent.run("ticker,weight\nNVDA,0.5\nMSFT,0.5\n"))
    assert report.companies[0].status == "manual_review"
    assert report.reports[0].claims == []
    assert "passage 2" in report.companies[0].reason
    assert report.companies[1].status == "available"
    assert report.reports[1].claims[0].evidence_quote == "Other real risk."


def test_verification_rejects_modified_numbers_and_fabricated_quotes():
    text = "Revenue fell 16 percent. Customers may not adopt our new 16 products."
    assert not filings.quote_is_in_text("Revenue fell 6 percent.", text)
    assert not filings.quote_is_in_text("Customers may not adopt our new products.", text)
    assert not filings.quote_is_in_text("Revenue rose 16 percent.", text)


def test_corrections_must_match_rejected_positions(monkeypatch):
    monkeypatch.setattr(filing_risk_agent, "_extract_risks", lambda _: _draft(
        {"risks": [{"category": "Risk", "evidence_quote": "invented"}]}))

    async def verify(session, name, arguments):
        return {"verified": [False]}

    monkeypatch.setattr(filing_risk_agent, "call_tool", verify)
    monkeypatch.setattr(filing_risk_agent, "_repair_quotes", lambda segments, risks:
                        QuoteCorrections.model_validate({"corrections": [
                            {"position": 1, "start_segment": 0, "end_segment": 0}]}))
    with pytest.raises(filing_risk_agent.UnverifiedFilingQuotesError, match="invalid correction positions"):
        asyncio.run(filing_risk_agent._verified_risks(None, "NVDA", 2, "real risk"))


@pytest.mark.parametrize("start,end", [(None, 0), (1, 0), (0, 3), (0, 1)])
def test_invalid_segment_selection_is_rejected(monkeypatch, start, end):
    monkeypatch.setattr(filing_risk_agent, "_extract_risks", lambda _: _draft(
        {"risks": [{"category": "Risk", "evidence_quote": "invented"}]}))

    async def verify(session, name, arguments):
        return {"verified": [False]}

    monkeypatch.setattr(filing_risk_agent, "call_tool", verify)
    monkeypatch.setattr(filing_risk_agent, "_repair_quotes", lambda segments, risks:
                        QuoteCorrections.model_validate({"corrections": [
                            {"position": 0, "start_segment": start, "end_segment": end}]}))
    with pytest.raises(filing_risk_agent.UnverifiedFilingQuotesError, match="invalid segment selection"):
        asyncio.run(filing_risk_agent._verified_risks(None, "NVDA", 2, "real risk"))


def test_invalid_segment_selection_retries_and_verifies(monkeypatch):
    text = "Supply shortages may disrupt production."
    monkeypatch.setattr(filing_risk_agent, "_extract_risks", lambda _: _draft(
        {"risks": [{"category": "Supply", "evidence_quote": "invented"}]}))
    calls = []

    async def verify(session, name, arguments):
        return filings.verify_filing_risk_quotes(arguments["text"], arguments["quotes"])

    def repair(segments, risks):
        calls.append(risks)
        end = 5 if len(calls) == 1 else 0
        return QuoteCorrections.model_validate({"corrections": [
            {"position": 0, "start_segment": 0, "end_segment": end}]})

    monkeypatch.setattr(filing_risk_agent, "call_tool", verify)
    monkeypatch.setattr(filing_risk_agent, "_repair_quotes", repair)
    result = asyncio.run(filing_risk_agent._verified_risks(None, "NVDA", 3, text))
    assert len(calls) == 2
    assert result[0].evidence_quote == text


def test_three_adjacent_source_segments_are_accepted(monkeypatch):
    text = " ".join(f"word{i}" for i in range(75))
    monkeypatch.setattr(filing_risk_agent, "_extract_risks", lambda _: _draft(
        {"risks": [{"category": "Risk", "evidence_quote": "invented"}]}))

    async def verify(session, name, arguments):
        return filings.verify_filing_risk_quotes(arguments["text"], arguments["quotes"])

    monkeypatch.setattr(filing_risk_agent, "call_tool", verify)
    monkeypatch.setattr(filing_risk_agent, "_repair_quotes", lambda segments, risks:
                        QuoteCorrections.model_validate({"corrections": [
                            {"position": 0, "start_segment": 0, "end_segment": 2}]}))
    result = asyncio.run(filing_risk_agent._verified_risks(None, "NVDA", 3, text))
    assert result[0].evidence_quote == text


def test_invalid_selections_result_in_manual_review_and_continue(mcp_server_url, monkeypatch):
    monkeypatch.setenv("MCP_SERVER_URL", mcp_server_url)

    def section(ticker, as_of):
        return {"ticker": ticker, "form": "10-K", "filing_date": "2026-02-25",
                "section": "Risk Factors", "url": "https://www.sec.gov/filing",
                "status": "available", "reason": None,
                "chunks": [f"{ticker} faces supply risk."],
                "retrieved_at": "2026-11-14T00:00:00Z"}

    monkeypatch.setattr("tools.filings.get_filing_risk_section", section)
    monkeypatch.setattr(filing_risk_agent, "_extract_risks", lambda text:
                        _draft({"risks": [
                            {"category": "Supply", "evidence_quote": "invented" if text.startswith("NVDA") else text}]}))
    monkeypatch.setattr(filing_risk_agent, "_repair_quotes", lambda segments, risks:
                        QuoteCorrections.model_validate({"corrections": [
                            {"position": 0, "start_segment": 0, "end_segment": 100}]}))
    report = asyncio.run(filing_risk_agent.run("ticker,weight\nNVDA,0.5\nMSFT,0.5\n"))
    assert report.companies[0].status == "manual_review"
    assert "invalid segment selection" in report.companies[0].reason
    assert report.reports[0].claims == []
    assert report.companies[1].status == "available"
    assert report.reports[1].claims[0].evidence_quote == "MSFT faces supply risk."


def test_passages_run_concurrently_with_a_limit_and_keep_order(mcp_server_url, monkeypatch):
    monkeypatch.setenv("MCP_SERVER_URL", mcp_server_url)
    monkeypatch.setattr("tools.filings.get_filing_risk_section", lambda ticker, as_of: {
        "ticker": ticker, "form": "10-K", "filing_date": "2026-02-25",
        "section": "Risk Factors", "url": "https://www.sec.gov/filing",
        "status": "available", "reason": None,
        "chunks": [f"Risk passage {i}." for i in range(7)],
        "retrieved_at": "2026-11-14T00:00:00Z"})
    lock = threading.Lock()
    barrier = threading.Barrier(filing_risk_agent.MAX_CONCURRENT_PASSAGES, timeout=5)
    active = 0
    maximum = 0

    def extract(text):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        if int(text.split()[-1].rstrip(".")) < filing_risk_agent.MAX_CONCURRENT_PASSAGES:
            barrier.wait()
        time.sleep(0.01)
        with lock:
            active -= 1
        return _draft({"risks": [{"category": "Risk", "evidence_quote": text}]})

    monkeypatch.setattr(filing_risk_agent, "_extract_risks", extract)
    report = asyncio.run(filing_risk_agent.run("ticker,weight\nNVDA,1\n"))
    assert maximum == filing_risk_agent.MAX_CONCURRENT_PASSAGES
    assert [claim.evidence_quote for claim in report.reports[0].claims] == [
        f"Risk passage {i}." for i in range(7)]


def test_rag_enabled_starts_indexing_and_reports_job(mcp_server_url, monkeypatch):
    monkeypatch.setenv("MCP_SERVER_URL", mcp_server_url)
    monkeypatch.setenv("ENABLE_FILING_RAG", "1")
    calls = []

    def index(tickers, as_of):
        calls.append((tickers, as_of))
        return {"filings": [{"ticker": "NVDA", "accession": "123"}],
                "ingestion_job_id": "job1", "status": "STARTING"}

    monkeypatch.setattr("tools.filings_rag.index_annual_filings", index)
    monkeypatch.setattr("tools.filings.get_filing_risk_section", lambda ticker, as_of: {
        "ticker": ticker, "form": "10-K", "filing_date": "2026-02-25",
        "section": "Risk Factors", "url": "https://www.sec.gov/filing",
        "status": "manual_review", "reason": "Ambiguous section", "chunks": []})
    report = asyncio.run(filing_risk_agent.run("ticker,weight\nNVDA,1\n"))
    assert calls == [(["NVDA"], report.as_of)]
    assert report.indexing.status == "started"
    assert report.indexing.ingestion_job_id == "job1"
    assert report.indexing.ingestion_status == "STARTING"
    assert report.indexing.filings[0]["accession"] == "123"
