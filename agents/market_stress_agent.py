"""Market-stress agent using shared MCP tools and the common report contract."""
import argparse
import asyncio
import json
import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from strands import Agent

load_dotenv()

from agents.base import build_model
from agents.mcp_client import call_tool as _call
from core.citations import resolve_citations
from core.market_stress import EnrichedPortfolio, Evaluations, MarketStressRequest, MarketStressResult
from core.schemas import AgentOutput, Claim, Entity, Source

AGENT = "market_stress"
SERIES = ("OFR_FSI", "STLFSI4", "VIXCLS")
SYSTEM_PROMPT = """Assess the severity and confidence of each supplied market-stress fact.
Return exactly one evaluation for each id, with severity score 0-5 and confidence 0-1.
Scores are subjective assessments, not observed market data or validated investment advice.
Use only the supplied facts. Do not calculate or modify values, invent sources, or infer
company or country stress from a global indicator. Consider the age and limitations of
the data when estimating confidence."""


async def collect(request: MarketStressRequest, as_of: date) -> tuple[list[dict], dict]:
    """Fetch data and perform all numerical calculations via MCP."""
    url = os.environ.get("MCP_SERVER_URL", "http://127.0.0.1:8000/mcp")
    async with streamable_http_client(url) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            enriched_holdings = []
            exposure_status = {}
            for holding in request.holdings:
                prices = await _call(session, "get_price_history",
                                     {"ticker": holding.ticker, "as_of": as_of.isoformat()})
                exposure = await _call(session, "get_country_exposures", {"ticker": holding.ticker})
                exposure_status[holding.ticker] = exposure["status"]
                enriched_holdings.append({**holding.model_dump(), "prices": prices,
                                          "exposures": exposure["exposures"]})
            portfolio = EnrichedPortfolio.model_validate({"holdings": enriched_holdings, "as_of": as_of})
            breakdown = await _call(session, "decompose_portfolio",
                                    {"request": portfolio.model_dump(mode="json")})
            breakdown["exposure_status"] = exposure_status
            facts = []
            for series_id in SERIES:
                series = await _call(session, "get_market_series",
                                     {"series_id": series_id, "as_of": as_of.isoformat()})
                variation = await _call(session, "calculate_variation", {"series": series})
                facts.append({"ticker": "GLOBAL", **variation})
            country_status = {}
            for country in sorted(breakdown["by_country"]):
                result = await _call(session, "get_country_market_series",
                                     {"country": country, "as_of": as_of.isoformat()})
                country_status[country] = result["status"]
                if result["status"] == "available":
                    variation = await _call(session, "calculate_variation", {"series": result["series"]})
                    facts.append({"ticker": f"COUNTRY-{country}", **variation})
            breakdown["country_indicator_status"] = country_status
            for holding in portfolio.holdings:
                variation = await _call(session, "calculate_variation",
                                        {"series": holding.prices.model_dump(mode="json")})
                facts.append({"ticker": holding.ticker, **variation})
    return facts, breakdown


def _claims_from_facts(facts: list[dict]) -> list[dict]:
    claims = []
    counters: dict[str, int] = {}
    for fact in facts:
        ticker = fact["ticker"]
        metrics = [
            ("level", fact["current"]["value"], fact["unit"]),
            ("absolute change", fact["absolute_change"], fact["unit"]),
        ]
        if ticker != "GLOBAL" and not ticker.startswith("COUNTRY-") and fact["relative_change"] is not None:
            metrics.append(("relative change", fact["relative_change"], "fraction"))
        for label, value, unit in metrics:
            counters[ticker] = counters.get(ticker, 0) + 1
            claim_id = f"{AGENT}:{ticker}:{counters[ticker]:03d}"
            statement = f"{fact['name']} {label}: {value} {unit}, observed {fact['current']['date']}"
            if label != "level":
                statement += f" relative to {fact['previous']['date']}"
            claims.append({"id": claim_id, "ticker": ticker, "statement": statement,
                           "value": value, "unit": unit, "source": fact["source"]})
    return claims


def _evaluate(claims: list[dict]) -> Evaluations:
    agent = Agent(model=build_model(), system_prompt=SYSTEM_PROMPT,
                  name="market_stress_agent", callback_handler=None)
    prompt = json.dumps(claims)
    return agent(prompt, structured_output_model=Evaluations).structured_output


def _reports(request: MarketStressRequest, as_of: date, facts: list[dict], evaluations: Evaluations) -> list[AgentOutput]:
    raw_claims = _claims_from_facts(facts)
    scores = {evaluation.id: evaluation for evaluation in evaluations.evaluations}
    expected = {claim["id"] for claim in raw_claims}
    if set(scores) != expected or len(scores) != len(evaluations.evaluations):
        raise ValueError("LLM evaluations must contain each claim id exactly once")
    reports = []
    country_tickers = sorted({item["ticker"] for item in raw_claims if item["ticker"].startswith("COUNTRY-")})
    for ticker in ["GLOBAL", *country_tickers, *(holding.ticker for holding in request.holdings)]:
        claims = [
            Claim(id=item["id"], channel="financial_stress", statement=item["statement"],
                  value=item["value"], unit=item["unit"], score=scores[item["id"]].score,
                  confidence=scores[item["id"]].confidence,
                  sources=[Source.model_validate(item["source"])])
            for item in raw_claims if item["ticker"] == ticker
        ]
        summary = "Market observations " + "".join(f"[{claim.id}]" for claim in claims) + "."
        country = ticker.removeprefix("COUNTRY-") if ticker.startswith("COUNTRY-") else None
        report = AgentOutput(agent=AGENT, entity=Entity(ticker=ticker, country=country),
                             as_of=as_of.isoformat(), claims=claims, summary=summary)
        resolve_citations(summary, [report])
        reports.append(report)
    return reports


async def run(request: MarketStressRequest) -> MarketStressResult:
    as_of = date.today()
    facts, breakdown = await collect(request, as_of)
    evaluations = _evaluate(_claims_from_facts(facts))
    return MarketStressResult(reports=_reports(request, as_of, facts, evaluations), breakdown=breakdown)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyze market stress from a JSON portfolio input")
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    request = MarketStressRequest.model_validate_json(args.input.read_text(encoding="utf-8"))
    print(asyncio.run(run(request)).model_dump_json(indent=2))
