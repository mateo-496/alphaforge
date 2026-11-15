import json
import sys
import unittest
from pathlib import Path
from config import BASE_DIR, TRUSTED_SOURCES_PATH
from output_example import CountryReport, Claim, Event, Indicators, Source
from agents.source_agent import (
    SourceAgent,
    discover_sources,
    get_country_sources,
    get_trusted_sources_for_country,
    load_trusted_registry,
    save_trusted_registry,
    add_discovered_trusted_sources,
    normalize_country_key,
)
from agents.country_risk_agent import RiskAgent, analyze_country
from tools.country_domains import (
    get_country_domain,
    get_country_official_patterns,
    is_country_domain_match,
    score_source_priority,
)
from tools.source_discovery import assess_source, find_candidate_sources
from tools.sovereign_risk import country_risk
from tools.risk_calculator import calculate_risk
from tools.country_api import get_country_data
from tools.bank_api import get_bank_data
import main

class TestAlphaForgeArchitecture(unittest.TestCase):

    def test_country_domain_resolution_and_support(self):
        """Test country-code domain resolution across previously supported and new countries."""
        # Previously supported countries
        self.assertEqual(get_country_domain("Canada"), "ca")
        self.assertEqual(get_country_domain("China"), "cn")
        self.assertEqual(get_country_domain("United States"), "us")
        self.assertEqual(get_country_domain("US"), "us")
        self.assertEqual(get_country_domain("Japan"), "jp")
        self.assertEqual(get_country_domain("Russia"), "ru")
        self.assertEqual(get_country_domain("Europe"), "eu")

        # New and arbitrary global countries
        self.assertEqual(get_country_domain("Brazil"), "br")
        self.assertEqual(get_country_domain("Australia"), "au")
        self.assertEqual(get_country_domain("Germany"), "de")
        self.assertEqual(get_country_domain("United Kingdom"), "uk")
        self.assertEqual(get_country_domain("India"), "in")
        self.assertEqual(get_country_domain("South Africa"), "za")
        self.assertEqual(get_country_domain("Mexico"), "mx")
        self.assertEqual(get_country_domain("Singapore"), "sg")
        self.assertEqual(get_country_domain("South Korea"), "kr")

        # Direct 2-letter ccTLD inputs
        self.assertEqual(get_country_domain("fr"), "fr")
        self.assertEqual(get_country_domain("it"), "it")

        # Automatic fallback for arbitrary new country names
        fallback_code = get_country_domain("Atlantis Land")
        self.assertEqual(len(fallback_code), 2)

    def test_country_domain_prioritization_and_quality_check(self):
        """Test country-domain prioritization while verifying non-official domains are not auto-trusted."""
        # 1. Official national site matching country ccTLD: should receive stronger signal + high priority
        official_cand = {
            "title": "Bank of Canada Official Portal",
            "url": "https://www.bankofcanada.ca/stats",
            "snippet": "Official central bank statistics."
        }
        res_official = assess_source(official_cand, "Canada")
        self.assertTrue(res_official["country_domain_match"])
        self.assertEqual(res_official["preliminary_domain_signal"], "stronger")
        self.assertTrue(res_official["priority_score"] >= 80.0)

        # 2. General multilateral source: strong trust signal, but no country-domain match
        multilateral_cand = {
            "title": "World Bank Macro Data",
            "url": "https://data.worldbank.org/indicator",
            "snippet": "World Bank statistical database."
        }
        res_multi = assess_source(multilateral_cand, "Canada")
        self.assertFalse(res_multi["country_domain_match"])
        self.assertEqual(res_multi["preliminary_domain_signal"], "stronger")
        # Priority should be lower than country-matching official authority
        self.assertTrue(res_official["priority_score"] > res_multi["priority_score"])

        # 3. Random commercial / unverified domain on country ccTLD:
        # Matches country domain for prioritization, but MUST NOT be automatically marked trusted!
        commercial_cand = {
            "title": "Random Canadian Financial Blog",
            "url": "https://random-commercial-blog.ca/market-tips",
            "snippet": "Unofficial tips and opinion articles."
        }
        res_comm = assess_source(commercial_cand, "Canada")
        self.assertTrue(res_comm["country_domain_match"])
        # Crucial requirement: must remain unverified, not automatically trusted
        self.assertEqual(res_comm["preliminary_domain_signal"], "unverified")
        self.assertTrue(res_official["priority_score"] > res_comm["priority_score"])

    def test_polyfinance_isolation(self):
        """Verify AlphaForge has no imports, references, or runtime dependency on polyfinance."""
        import agents.source_agent
        import agents.country_risk_agent
        import tools.source_discovery
        import tools.bedrock_service
        import storage.s3_service
        import config

        # Ensure no module imported polyfinance in sys.modules from alphaforge packages
        alphaforge_modules = [m for name, m in sys.modules.items() if name.startswith("agents.") or name.startswith("tools.")]
        for mod in alphaforge_modules:
            file_path = getattr(mod, "__file__", "")
            if file_path:
                self.assertNotIn("/polyfinance/", file_path)

        # Ensure trusted_sources.json path is within AlphaForge
        self.assertTrue(str(TRUSTED_SOURCES_PATH).startswith(str(BASE_DIR / "data")))

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

    def test_source_agent_auto_persists_new_trusted_sources_independently(self):
        # 1. Run discovery for a new country: Brazil
        res1 = discover_sources("Brazil", limit=10)
        self.assertIsInstance(res1, dict)
        self.assertEqual(res1["country"], "Brazil")

        # Verify trusted_sources.json on disk was updated
        with open(TRUSTED_SOURCES_PATH, "r", encoding="utf-8") as f:
            disk_data = json.load(f)

        self.assertIn("brazil", disk_data)
        brazil_sources = disk_data["brazil"]
        self.assertTrue(len(brazil_sources) > 0)
        
        # Verify official domains were recognized and added
        brazil_urls = [s["url"] for s in brazil_sources]
        self.assertTrue(any(f".{get_country_domain('Brazil')}/" in u for u in brazil_urls))
        initial_count = len(brazil_sources)

        # 2. Run discovery a second time: verify no duplicates are added
        res2 = discover_sources("Brazil", limit=10)
        with open(TRUSTED_SOURCES_PATH, "r", encoding="utf-8") as f:
            disk_data_second = json.load(f)
        
        self.assertEqual(len(disk_data_second["brazil"]), initial_count)
        urls_after = [s["url"].rstrip("/").lower() for s in disk_data_second["brazil"]]
        self.assertEqual(len(urls_after), len(set(urls_after)))

    def test_risk_agent_auto_persists_discovered_trusted_sources(self):
        # Run risk_agent on another jurisdiction: Australia
        report = analyze_country("Australia")
        self.assertIsInstance(report, CountryReport)
        self.assertEqual(report.country, "Australia")

        # Verify that trusted_sources.json on disk includes australia
        with open(TRUSTED_SOURCES_PATH, "r", encoding="utf-8") as f:
            disk_data = json.load(f)

        self.assertIn("australia", disk_data)
        aus_sources = disk_data["australia"]
        self.assertTrue(len(aus_sources) > 0)
        initial_aus_count = len(aus_sources)

        # Run risk_agent again: verify no duplicates are added
        report2 = analyze_country("Australia")
        self.assertIsInstance(report2, CountryReport)
        with open(TRUSTED_SOURCES_PATH, "r", encoding="utf-8") as f:
            disk_data_again = json.load(f)

        self.assertEqual(len(disk_data_again["australia"]), initial_aus_count)

    def test_explicit_add_trusted_sources_avoids_duplicates(self):
        test_source = {
            "name": "Banco Central do Brasil",
            "url": "https://www.bcb.gov.br/en",
            "type": "central_bank",
            "notes": "Official Central Bank of Brazil portal"
        }
        # First add
        added1 = add_discovered_trusted_sources("Brazil", [test_source])

        # Check disk
        with open(TRUSTED_SOURCES_PATH, "r", encoding="utf-8") as f:
            disk_data = json.load(f)
        urls = [s["url"].rstrip("/").lower() for s in disk_data["brazil"]]
        self.assertIn("https://www.bcb.gov.br/en", urls)

        # Second add of the exact same source (and with trailing slash variant)
        duplicate_source = dict(test_source)
        duplicate_source["url"] = "https://www.bcb.gov.br/en/"
        added2 = add_discovered_trusted_sources("Brazil", [duplicate_source])
        self.assertEqual(len(added2), 0)

        # Check disk again
        with open(TRUSTED_SOURCES_PATH, "r", encoding="utf-8") as f:
            disk_data2 = json.load(f)
        urls2 = [s["url"].rstrip("/").lower() for s in disk_data2["brazil"]]
        self.assertEqual(urls2.count("https://www.bcb.gov.br/en"), 1)

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
