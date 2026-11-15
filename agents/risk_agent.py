"""Final portfolio risk: gathers measured inputs, then tools.portfolio_risk computes the score (no LLM numbers)."""
import argparse
import json
from datetime import date
from pathlib import Path

from core.portfolio_risk import PortfolioRiskReport
from core.schemas import AgentOutput, Claim
from tools import market_data, market_inputs, portfolio_csv
from tools.country_risk_inputs import country_risk_score
from tools.portfolio_risk import compute_portfolio_risk


def run(csv_text: str, filing_reports: list[AgentOutput] | None = None,
        scenario: tuple[dict[str, float], float] | None = None) -> PortfolioRiskReport:
    """filing_reports: per-ticker outputs of the filing-risk agent (omit to leave the filing term missing)."""
    as_of = date.today().isoformat()
    weights = {h["ticker"]: float(h["weight"]) for h in portfolio_csv.convert_portfolio_csv(csv_text)["holdings"]}
    exposures, market = {}, {}
    for ticker in weights:
        found = market_data.get_country_exposures(ticker)
        exposures[ticker] = {e["country"]: e["revenue_share"] for e in found["exposures"]}
        try:
            market[ticker] = market_inputs.vol_and_beta(ticker, as_of)
        except Exception:
            market[ticker] = {}
    country_scores = {}
    for country in sorted({c for shares in exposures.values() for c in shares}):
        result = country_risk_score(country, as_of)
        country_scores[country] = {"score": result["score"], "missing_inputs": result["missing_inputs"]}
    claims: dict[str, list[Claim]] = {}
    for report in filing_reports or []:
        claims.setdefault(report.entity.ticker, []).extend(report.claims)
    return compute_portfolio_risk(as_of, weights, exposures, country_scores, claims, market, scenario=scenario)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compute the final risk of a CSV portfolio")
    parser.add_argument("portfolio", type=Path)
    parser.add_argument("--filings", type=Path, help="JSON output of agents.filing_risk_agent")
    args = parser.parse_args()
    reports = None
    if args.filings:
        data = json.loads(args.filings.read_text(encoding="utf-8"))
        reports = [AgentOutput.model_validate(r) for r in data["reports"]]
    print(run(args.portfolio.read_text(encoding="utf-8-sig"), reports).model_dump_json(indent=2))
