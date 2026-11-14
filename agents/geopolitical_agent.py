from agents.base import run_agent
from core import config
from core.schemas import CountryRisk, ExposureReport, GeopoliticalReport, Scenario

PROMPT = "Assess geopolitical risk (0-100) per country under the given scenario, citing drivers."
TOOLS: list = []  # tools.geopolitics.*


def run(exposures: ExposureReport, scenario: Scenario) -> GeopoliticalReport:
    if config.USE_MOCK:
        countries = {e.country for t in exposures.tickers for e in t.exposures} | set(scenario.countries)
        return GeopoliticalReport(scenario=scenario.name, countries=[
            CountryRisk(country=c, score=60.0, drivers=["mock driver"]) for c in sorted(countries)])
    prompt = f"{scenario.model_dump_json()}\n{exposures.model_dump_json()}"
    return run_agent(PROMPT, prompt, GeopoliticalReport, TOOLS)
