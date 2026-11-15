"""Orchestrator chain: Portfolio + InvestorProfile → filings → geopolitical → risk → remediation.

Each of the four steps is recorded as a Step (agent, input, output, ms) in the ChainResult.
With USE_MOCK=1 (the default) every agent call uses deterministic mock data so the chain and
web work without AWS credentials.  Swap the _mock_* helpers for the real agent calls to go live.

Scoring flow
------------
1. filings      → list[AgentOutput], one per holding ticker
                  score_filings(out) → firm_score ∈ [0,5]  (A3)
2. geopolitical → list[AgentOutput], one per unique country
                  score_geopolitical(out) → R ∈ [0,100]  (A1)
3. risk         → PortfolioRisk via tools.portfolio_score.calculate_portfolio_risk (2-stage)
4. remediation  → RemediationPlan
"""
from __future__ import annotations

from datetime import date

from agents.base import timed
from core import config
from core.schemas import (
    AgentOutput, Claim, ChainResult, Entity, InvestorProfile,
    Portfolio, PortfolioRisk, RemediationPlan, Step,
)


# ── Mock builders (USE_MOCK=1) ────────────────────────────────────────────────

def _mock_filings(ticker: str, as_of: str) -> AgentOutput:
    """Deterministic mock filings output – uses FIRM_SCORE from web/mock.py."""
    from web import mock as _m
    raw_score = _m.FIRM_SCORE.get(ticker, 1.0)
    s1 = min(5, max(0, round(raw_score)))
    s2 = min(5, max(0, round(raw_score * 0.8)))
    claims = [
        Claim(id=f"filings:{ticker}:001", channel="export_controls",
              statement=f"{ticker}: export-control disclosure (mock).",
              score=s1, confidence=0.80, sources=[],
              value=None, unit=None, evidence_quote=None, quote_verified=None),
        Claim(id=f"filings:{ticker}:002", channel="trade_tariffs",
              statement=f"{ticker}: tariff-exposure disclosure (mock).",
              score=s2, confidence=0.75, sources=[],
              value=None, unit=None, evidence_quote=None, quote_verified=None),
    ]
    return AgentOutput(
        agent="filings", entity=Entity(ticker=ticker, country=None), as_of=as_of,
        claims=claims,
        summary=(f"Mock filings for {ticker}: export-control and tariff exposure "
                 f"[filings:{ticker}:001][filings:{ticker}:002]."),
    )


def _mock_geo(country: str, as_of: str) -> AgentOutput:
    """Deterministic mock geopolitical output – uses COUNTRY table from web/mock.py."""
    from web import mock as _m
    r, driver = _m.COUNTRY.get(country, _m.COUNTRY["Other"])
    score_val = min(5, max(0, round(r / 20)))
    claims = [
        Claim(id=f"geopolitical:{country}:001", channel="conflict_exposure",
              statement=driver, score=score_val, confidence=0.85, sources=[],
              value=None, unit=None, evidence_quote=None, quote_verified=None),
    ]
    return AgentOutput(
        agent="geopolitical", entity=Entity(ticker=country, country=None), as_of=as_of,
        claims=claims,
        summary=f"Mock geopolitical for {country}: {driver} [geopolitical:{country}:001].",
    )


def _extract_countries(portfolio: Portfolio, as_of: str) -> list[str]:
    """Return unique ISO-3 country codes to analyze, derived from mock exposure table."""
    if not config.USE_MOCK:
        return []  # real path: countries come from filings_agent country_weights
    from web import mock as _m
    seen: set[str] = set()
    for h in portfolio.holdings:
        for c in _m.EXPOSURE.get(h.ticker, {}):
            if c != "Other":
                seen.add(c)
    return sorted(seen)


# ── Grouped step runners ──────────────────────────────────────────────────────

def _run_filings(portfolio: Portfolio, as_of: str) -> list[AgentOutput]:
    """Run filings agent for every holding and return all outputs."""
    if config.USE_MOCK:
        return [_mock_filings(h.ticker, as_of) for h in portfolio.holdings]
    from agents import filings_agent  # lazy – requires edgar + AWS
    return [filings_agent.run(h.ticker, as_of) for h in portfolio.holdings]


def _run_geopolitical(countries: list[str], as_of: str) -> list[AgentOutput]:
    """Run geopolitical agent for every country and return all outputs."""
    if config.USE_MOCK:
        return [_mock_geo(c, as_of) for c in countries]
    from agents import geopolitical_agent  # lazy – requires boto3/S3
    return [geopolitical_agent.run(c, as_of) for c in countries]


# ── Main chain ────────────────────────────────────────────────────────────────

def run(
    portfolio: Portfolio,
    profile: InvestorProfile,
    scenario=None,          # accepted but unused; scenarios come from pipeline in real mode
    as_of: str | None = None,
) -> ChainResult:
    """Run the full analysis chain in four recorded steps.

    Returns a ChainResult with exactly 4 Steps:
      0  filings      – all tickers grouped
      1  geopolitical – all countries grouped
      2  risk         – deterministic 2-stage portfolio score
      3  remediation  – suggested trades
    """
    steps: list[Step] = []
    as_of = as_of or date.today().isoformat()

    def step(name: str, fn, inputs: dict, *args):
        out, ms = timed(fn, *args)
        steps.append(Step(agent=name, input=inputs, output=_to_dict(out), ms=ms))
        return out

    # 1. Filings: all holdings in one grouped step
    countries = _extract_countries(portfolio, as_of)
    filings_outputs: list[AgentOutput] = step(
        "filings",
        _run_filings,
        {"tickers": [h.ticker for h in portfolio.holdings], "as_of": as_of},
        portfolio, as_of,
    )

    # 2. Geopolitical: all countries in one grouped step
    geo_outputs: list[AgentOutput] = step(
        "geopolitical",
        _run_geopolitical,
        {"countries": countries, "as_of": as_of},
        countries, as_of,
    )

    # 3. Risk: deterministic 2-stage formula
    from agents import risk_agent  # lazy import
    risk_result: PortfolioRisk = step(
        "risk",
        risk_agent.run,
        {"tickers": [h.ticker for h in portfolio.holdings],
         "num_filings": len(filings_outputs),
         "num_countries": len(geo_outputs)},
        portfolio, filings_outputs, geo_outputs, profile,
    )

    # 4. Remediation
    from agents import remediation_agent  # lazy import
    plan: RemediationPlan = step(
        "remediation",
        remediation_agent.run,
        {"score": risk_result.score},
        portfolio, risk_result, profile,
    )

    return ChainResult(steps=steps, final=plan)


def _to_dict(obj) -> dict:
    """Safely convert any agent output to a plain dict for Step.output."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, list):
        return {"items": [_to_dict(x) for x in obj], "count": len(obj)}
    if isinstance(obj, dict):
        return obj
    return {"value": str(obj)}


if __name__ == "__main__":
    p = Portfolio(holdings=[{"ticker": "NVDA", "weight": 0.6}, {"ticker": "AAPL", "weight": 0.4}])
    result = run(p, InvestorProfile())
    print(result.model_dump_json(indent=2))
