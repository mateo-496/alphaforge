import asyncio
import socket
import threading
import time

import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from pydantic import ValidationError

from agents.market_stress_agent import _claims_from_facts, _reports, run
from core.citations import resolve_citations
from core.market_stress import EnrichedPortfolio, Evaluations, MarketStressRequest
from tools.market_stress import calculate_variation, decompose_portfolio, get_market_series
from tools.mcp_server import server


SOURCE = {"title": "Price feed", "url": "https://example.com/prices",
          "locator": "closing prices", "retrieved_at": "2026-11-10T00:00:00Z"}


@pytest.fixture
def mcp_server_url():
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    app = server.streamable_http_app()
    http = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    thread = threading.Thread(target=http.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not http.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("MCP server did not start")
            time.sleep(0.01)
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        http.should_exit = True
        thread.join(timeout=10)
        listener.close()


def _request():
    return {
        "as_of": "2026-11-10",
        "holdings": [
            {"ticker": "ASML", "weight": 0.6,
             "exposures": [{"country": "CN", "revenue_share": 0.25, "source": SOURCE}],
             "prices": {"name": "ASML", "unit": "USD", "source": SOURCE,
                        "observations": [{"date": "2026-11-09", "value": 100},
                                         {"date": "2026-11-10", "value": 90}]}},
            {"ticker": "NVDA", "weight": 0.4, "exposures": [],
             "prices": {"name": "NVDA", "unit": "USD", "source": SOURCE,
                        "observations": [{"date": "2026-11-09", "value": 50},
                                         {"date": "2026-11-10", "value": 55}]}},
        ],
    }


def test_breakdown_preserves_unknown_and_claim_reference():
    result = decompose_portfolio(_request())
    assert result["by_country"]["CN"] == pytest.approx(0.15)
    assert result["unknown_weight"] == pytest.approx(0.85)
    assert result["by_ticker"][0]["countries"][0]["source"] == SOURCE


def test_variation_and_zero_base():
    series = _request()["holdings"][0]["prices"]
    result = calculate_variation(series)
    assert result["absolute_change"] == -10
    assert result["relative_change"] == pytest.approx(-0.1)
    series["observations"][0]["value"] = 0
    assert calculate_variation(series)["relative_change"] is None


def test_input_rejects_future_data_and_overallocated_revenue():
    request = _request()
    request["holdings"][0]["prices"]["observations"][-1]["date"] = "2026-11-11"
    with pytest.raises(ValidationError, match="after as_of"):
        EnrichedPortfolio.model_validate(request)
    request = _request()
    request["holdings"][0]["exposures"].append(
        {"country": "US", "revenue_share": 0.8, "source": SOURCE})
    with pytest.raises(ValidationError, match="exceed"):
        EnrichedPortfolio.model_validate(request)


def test_public_input_is_portfolio_only():
    request = MarketStressRequest.model_validate(
        {"holdings": [{"ticker": "ASML", "weight": 1.0}]})
    assert request.holdings[0].ticker == "ASML"
    with pytest.raises(ValidationError):
        MarketStressRequest.model_validate({"holdings": [{"ticker": "ASML", "weight": 1.0}],
                                            "as_of": "2026-01-01"})


def test_ofr_data_filters_future_and_attaches_provenance(monkeypatch):
    csv = ("Date,OFR FSI\n2026-11-08,1.0\n2026-11-09,2.0\n"
           "2026-11-10,3.0\n2026-11-11,4.0\n")
    monkeypatch.setattr("tools.market_stress._download", lambda url: csv)
    series = get_market_series("OFR_FSI", "2026-11-10")
    assert series["observations"][-1] == {"date": "2026-11-10", "value": 3.0}
    assert "financialresearch.gov" in series["source"]["url"]


def test_fred_missing_values_and_incomplete_series(monkeypatch):
    monkeypatch.setattr("tools.market_stress._download",
                        lambda url: "observation_date,VIXCLS\n2026-11-09,.\n2026-11-10,23\n")
    with pytest.raises(ValidationError):
        get_market_series("VIXCLS", "2026-11-10")


def test_reports_preserve_tool_values_and_reject_missing_evaluations():
    request = EnrichedPortfolio.model_validate(_request())
    facts = [{"ticker": h.ticker, **calculate_variation(h.prices.model_dump(mode="json"))}
             for h in request.holdings]
    facts.insert(0, {"ticker": "GLOBAL", **calculate_variation(request.holdings[0].prices.model_dump(mode="json"))})
    claims = _claims_from_facts(facts)
    evaluations = Evaluations(evaluations=[{"id": c["id"], "score": 2, "confidence": 0.8}
                                            for c in claims])
    reports = _reports(request, request.as_of, facts, evaluations)
    assert reports[1].claims[-1].value == pytest.approx(-0.1)
    assert reports[1].claims[-1].sources[0].url == SOURCE["url"]
    resolve_citations(reports[1].summary, [reports[1]])
    evaluations.evaluations.pop()
    with pytest.raises(ValueError, match="exactly once"):
        _reports(request, request.as_of, facts, evaluations)


def test_mcp_server_exposes_working_tools(mcp_server_url):
    async def check():
        async with streamable_http_client(mcp_server_url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                names = {tool.name for tool in (await session.list_tools()).tools}
                assert {"get_market_series", "get_price_history", "get_country_exposures", "get_country_market_series",
                        "calculate_variation", "decompose_portfolio", "convert_portfolio_csv"} <= names
                result = await session.call_tool("decompose_portfolio", {"request": _request()})
                assert not result.is_error
                assert result.structured_content["unknown_weight"] == pytest.approx(0.85)
                result = await session.call_tool("convert_portfolio_csv",
                                                 {"csv_text": "ticker,weight\nASML,0.6\nNVDA,0.4\n"})
                assert not result.is_error
                assert result.structured_content["holdings"][0] == {"ticker": "ASML", "weight": 0.6}
    asyncio.run(check())


def test_agent_calls_http_mcp_and_returns_reports(mcp_server_url, monkeypatch):
    monkeypatch.setenv("MCP_SERVER_URL", mcp_server_url)
    enriched = _request()
    enriched["holdings"][1]["exposures"] = [
        {"country": "CN", "revenue_share": 0.1, "source": SOURCE}]
    calls = []

    def fake_cache(namespace, params, fetch):
        calls.append(params["series_id"])
        return {"name": params["series_id"], "unit": "index", "source": SOURCE,
                "observations": [{"date": "2026-11-09", "value": 1}, {"date": "2026-11-10", "value": 2}]}

    monkeypatch.setattr("tools.mcp_server.cached", fake_cache)
    monkeypatch.setattr("tools.market_data.get_price_history",
                        lambda ticker, as_of, lookback_days: next(
                            h["prices"] for h in enriched["holdings"] if h["ticker"] == ticker))
    monkeypatch.setattr("tools.market_data.get_country_exposures",
                        lambda ticker: {"status": "available", "exposures": next(
                            h["exposures"] for h in enriched["holdings"] if h["ticker"] == ticker)})
    monkeypatch.setattr("agents.market_stress_agent._evaluate",
                        lambda claims: Evaluations(evaluations=[
                            {"id": c["id"], "score": 2, "confidence": 0.8} for c in claims]))
    request = {"holdings": [{"ticker": h["ticker"], "weight": h["weight"]}
                            for h in enriched["holdings"]]}
    result = asyncio.run(run(MarketStressRequest.model_validate(request)))
    assert [r.entity.ticker for r in result.reports] == ["GLOBAL", "COUNTRY-CN", "ASML", "NVDA"]
    assert result.reports[0].claims[0].value == 2
    assert result.breakdown["by_country"]["CN"] == pytest.approx(0.19)
    assert calls.count("DEXCHUS") == 1
