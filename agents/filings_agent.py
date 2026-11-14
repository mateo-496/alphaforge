from agents.base import run_agent
from core import config
from core.schemas import CountryExposure, ExposureReport, Portfolio, TickerExposure

PROMPT = "Extract each company's country exposures from its filings, with a verbatim evidence quote."
TOOLS: list = []  # tools.filings.get_filing_sections


def run(portfolio: Portfolio) -> ExposureReport:
    if config.USE_MOCK:
        return ExposureReport(tickers=[
            TickerExposure(ticker=h.ticker, exposures=[
                CountryExposure(country="CHN", exposure_type="revenue", revenue_share=0.2, evidence_quote="mock quote")
            ]) for h in portfolio.holdings])
    return run_agent(PROMPT, portfolio.model_dump_json(), ExposureReport, TOOLS)
