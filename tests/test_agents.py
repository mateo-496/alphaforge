import unittest
from output_example import CountryReport, Claim, Event, Indicators, Source
from agents.source_agent import (
    SourceAgent,
    discover_sources,
    get_country_sources,
    get_trusted_sources_for_country,
    load_trusted_registry,
    normalize_country_key,
)
from agents.risk_agent import RiskAgent, analyze_country
from tools.risk_math import country_risk
from tools.risk_calculator import calculate_risk
from tools.country_api import get_country_data
from tools.bank_api import get_bank_data
import main

class TestPolyfinanceArchitecture(unittest.TestCase):

    def test_trusted_registry_organization(self):
        registry = load_trusted_registry()
        self.assertIsInstance(registry, dict)
        self.assertIn("general", registry)
        self.assertIn("united_states", registry)
        self.assertIn("china", registry)
        self.assertIn("europe", registry)
        self.assertIn("japan", registry)
        self.assertIn("canada", registry)
        self.assertIn("russia", registry)

        # Check General
        general_urls = [s["url"] for s in registry["general"]]
        self.assertIn("https://documents.worldbank.org/en/publication/documents-reports/api", general_urls)
        self.assertIn(
            "https://datasupport.imf.org/knowledge?id=knowledge_category&sys_kb_id=5ca208d697bc4390d4f0b437f053af9e&category_id=9959b2bc1b6391903dba646fbd4bcb6a",
            general_urls
        )

        # Check United States
        us_urls = [s["url"] for s in registry["united_states"]]
        self.assertIn("https://fiscaldata.treasury.gov/api-documentation/", us_urls)
        self.assertIn("https://www.federalregister.gov/developers/documentation/api/v1", us_urls)

        # Check China
        china_urls = [s["url"] for s in registry["china"]]
        self.assertIn("https://pboc.io/api.html", china_urls)
        self.assertIn("https://www.pbc.gov.cn/english/130437/index.html", china_urls)
        self.assertIn("https://www.mof.gov.cn/en/abus/os/rd/", china_urls)

        # Check Europe
        europe_urls = [s["url"] for s in registry["europe"]]
        self.assertIn("https://www.ecb.europa.eu/home/html/index.en.html", europe_urls)

        # Check Japan
        japan_urls = [s["url"] for s in registry["japan"]]
        self.assertIn("https://www.boj.or.jp/en/statistics/outline/notice_2026/not260218a.htm", japan_urls)
        self.assertIn("https://www.mof.go.jp/english/index.htm", japan_urls)

        # Check Canada
        canada_urls = [s["url"] for s in registry["canada"]]
        self.assertIn("https://www.bankofcanada.ca/valet/docs", canada_urls)
        self.assertIn("https://www.statcan.gc.ca/en/microdata/api", canada_urls)

        # Check Russia
        russia_urls = [s["url"] for s in registry["russia"]]
        self.assertIn("https://minfin.gov.ru/ru/document/", russia_urls)
        self.assertIn("https://cbr.ru/", russia_urls)

    def test_country_specific_trusted_retrieval(self):
        us_sources = get_trusted_sources_for_country("United States")
        us_urls = [s["url"] for s in us_sources]
        self.assertIn("https://fiscaldata.treasury.gov/api-documentation/", us_urls)
        self.assertIn("https://documents.worldbank.org/en/publication/documents-reports/api", us_urls)

        canada_sources = get_trusted_sources_for_country("Canada")
        canada_urls = [s["url"] for s in canada_sources]
        self.assertIn("https://www.bankofcanada.ca/valet/docs", canada_urls)

    def test_source_agent_discovery(self):
        result = discover_sources("Canada", limit=5)
        self.assertIsInstance(result, dict)
        self.assertEqual(result["country"], "Canada")
        self.assertEqual(result["country_key"], "canada")
        self.assertIn("candidates", result)
        self.assertIn("existing_source_count", result)
        self.assertTrue(result["existing_source_count"] >= 2)

    def test_source_agent_sources_contract(self):
        sources = get_country_sources("Canada", limit=3)
        self.assertIsInstance(sources, list)
        self.assertTrue(len(sources) > 0)
        for src in sources:
            self.assertIsInstance(src, Source)
            self.assertTrue(src.title)
            self.assertTrue(src.url.startswith("http"))
            self.assertTrue(src.locator)
            self.assertTrue(src.retrieved_at)

    def test_risk_math_and_calculator(self):
        country_data = get_country_data("Canada")
        bank_data = get_bank_data("Canada")
        assessment = calculate_risk(country_data, bank_data)
        self.assertIn("score", assessment)
        self.assertIn("components", assessment)

        r_c = country_risk(country_data, bank_data)
        self.assertIsInstance(r_c, float)
        self.assertAlmostEqual(r_c, assessment["score"], places=2)

    def test_risk_agent_returns_country_report_instance(self):
        for country in ["Canada", "United States", "China", "Japan"]:
            report = analyze_country(country)
            self.assertIsInstance(report, CountryReport)
            self.assertEqual(report.country, country)
            self.assertTrue(report.as_of)
            self.assertIsInstance(report.indicators, Indicators)
            self.assertIsInstance(report.claims, list)
            self.assertIsInstance(report.events, list)
            self.assertIsInstance(report.R_c, float)

            # Validate Claims
            self.assertTrue(len(report.claims) >= 3)
            for claim in report.claims:
                self.assertIsInstance(claim, Claim)
                self.assertTrue(claim.id.startswith(f"risk_agent:{country}:"))
                self.assertIn(claim.channel, [
                    "trade_tariffs", "export_controls", "sanctions", "conflict_exposure",
                    "supply_chain", "regulatory", "fx_capital_controls", "financial_stress"
                ])
                self.assertTrue(0 <= claim.score <= 5)
                self.assertTrue(0.0 <= claim.confidence <= 1.0)
                self.assertTrue(len(claim.sources) > 0)
                for s in claim.sources:
                    self.assertIsInstance(s, Source)

            # Validate Events
            self.assertTrue(len(report.events) >= 2)
            for ev in report.events:
                self.assertIsInstance(ev, Event)
                self.assertTrue(ev.id.startswith(f"ev:{country}:"))
                self.assertIn(ev.channel, [
                    "trade_tariffs", "export_controls", "sanctions", "conflict_exposure",
                    "supply_chain", "regulatory", "fx_capital_controls", "financial_stress"
                ])
                self.assertTrue(0 <= ev.severity <= 5)
                self.assertTrue(0.0 <= ev.likelihood <= 1.0)
                self.assertTrue(len(ev.sources) > 0)

    def test_class_interface_agents(self):
        s_agent = SourceAgent("Japan")
        sources = s_agent.get_sources(limit=2)
        self.assertTrue(len(sources) > 0)
        trusted = s_agent.get_trusted()
        self.assertTrue(len(trusted) >= 2)

        r_agent = RiskAgent("Japan")
        report = r_agent.analyze()
        self.assertIsInstance(report, CountryReport)
        self.assertEqual(report.country, "Japan")

    def test_main_cli_execution_returns_country_report(self):
        result = main.main(["risk", "United States"])
        self.assertIsInstance(result, CountryReport)

        result_shorthand = main.main(["United States"])
        self.assertIsInstance(result_shorthand, CountryReport)

if __name__ == "__main__":
    unittest.main()
