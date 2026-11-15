"""Agents and their data tools, each on its real code path with only the network / Bedrock replaced."""
import json
from types import SimpleNamespace

from agents import filings_agent, source_agent
from core import llm
from tools import filings, worldbank


def test_worldbank_is_point_in_time(monkeypatch):
    monkeypatch.setattr(worldbank, "_countries", lambda: {"CAN": {"name": "Canada", "iso2": "CA"}})
    monkeypatch.setattr(worldbank, "_all", lambda code: {"CAN": [(2025, 9.9), (2024, 2.4)]})
    got = worldbank.indicators("CAN", "2025-11-12")             # 2025 data is not published yet in 2025
    assert got["inflation_pct"]["value"] == 2.4 and got["inflation_pct"]["year"] == 2024
    assert worldbank.indicators("TWN", "2025-11-12") == {}     # not covered by the World Bank: nothing invented


def test_source_agent_prefers_reachable_sources_and_falls_back_to_multilaterals(monkeypatch):
    monkeypatch.setattr(source_agent, "_check", lambda url: {"live": "ecb.europa.eu" in url, "final_url": url})
    assert [s["name"] for s in source_agent.official_sources("FRA")] == ["European Central Bank"]
    fallback = source_agent.official_sources("BRA")   # nothing answered: IMF / World Bank pages, flagged unchecked
    assert [s["type"] for s in fallback] == ["multilateral", "multilateral"] and not any(s["checked"] for s in fallback)
    assert all(c["url"].startswith("https://") for c in source_agent.candidates("USA"))


class FakeFiling:
    form, filing_date, accession_no, filing_url = "10-K", "2026-02-20", "0001", "https://www.sec.gov/x/nvda-10k.htm"
    TEXT = "Item 1A. Export controls could limit our sales to China. We rely on suppliers in Taiwan."

    def obj(self):
        return SimpleNamespace(risk_factors=self.TEXT, items=["Item 1A", "Item 1B"])

    def grep(self, pattern):
        return [SimpleNamespace(location="Item 1A", context=self.TEXT)] if pattern.lower() in self.TEXT.lower() else []


def test_filings_agent_tool_loop_verifies_quotes(monkeypatch):
    monkeypatch.setattr(filings, "_annual_filing", lambda t, a: FakeFiling())
    replies = iter([
        [{"toolUse": {"toolUseId": "1", "name": "get_risk_factors", "input": {}}}],
        [{"toolUse": {"toolUseId": "2", "name": "search_filing", "input": {"pattern": "Taiwan"}}}],
        [{"toolUse": {"toolUseId": "3", "name": "answer", "input": {"summary": "Export limits [1]. Suppliers [2].", "claims": [
            {"channel": "export_controls", "statement": "Export controls limit sales to China.", "score": 4, "confidence": .8,
             "evidence_quote": "Export controls could limit our sales to China", "locator": "Item 1A"},
            {"channel": "supply_chain", "statement": "Invented.", "score": 3, "confidence": .5,
             "evidence_quote": "we own every fab we use", "locator": "Item 1A"}]}}}]])

    class Bedrock:
        def converse(self, **req):
            return {"output": {"message": {"role": "assistant", "content": next(replies)}},
                    "usage": {"inputTokens": 10, "outputTokens": 5}, "ResponseMetadata": {"RequestId": "r"}}
    monkeypatch.setattr(llm, "_client", lambda service, region=None: Bedrock())
    rep = filings_agent.run("NVDA", "2026-11-12")
    assert [c.quote_verified for c in rep.claims] == [True, False]
    assert rep.claims[0].sources[0].url == FakeFiling.filing_url and "[filings:NVDA:001]" in rep.summary
    traces = [json.loads(line) for p in llm.TRACE_DIR.glob("*.jsonl") for line in p.read_text().splitlines()]
    assert [t["agent"] for t in traces] == ["filings"] * 3


def test_risk_section_passages(monkeypatch):
    monkeypatch.setattr(filings, "_annual_filing", lambda t, a: FakeFiling())
    sec = filings.risk_section("NVDA", "2026-11-12")
    assert sec["status"] == "available" and sec["chunks"] == [FakeFiling.TEXT] and sec["section"] == "Item 1A"
