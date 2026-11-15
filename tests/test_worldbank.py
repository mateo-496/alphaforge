import pytest

from tools import bank_api, country_api, worldbank


@pytest.fixture
def api(monkeypatch):
    worldbank._load.cache_clear()
    worldbank.fetch_indicators.cache_clear()
    monkeypatch.setenv("USE_WORLD_BANK", "1")
    calls = []

    def get_json(url, api_key="", params=None, timeout=20):
        calls.append(url)
        if url.endswith("/country"):
            return [{}, [{"id": "CHN", "iso2Code": "CN", "name": "China", "region": {"id": "EAS"}},
                         {"id": "WLD", "iso2Code": "1W", "name": "World", "region": {"id": "NA"}}]]
        code = url.rsplit("/", 1)[1]
        rows = {"FP.CPI.TOTL.ZG": [{"date": "2025", "value": None}, {"date": "2024", "value": 0.2}],
                "SL.UEM.TOTL.ZS": [{"date": "2025", "value": 5.0}],
                "FB.AST.NPER.ZS": [{"date": "2024", "value": 1.5}]}.get(code, [])
        return [{}, rows or None]
    monkeypatch.setattr(worldbank, "get_json", get_json)
    yield calls
    worldbank._load.cache_clear()
    worldbank.fetch_indicators.cache_clear()


def test_country_resolution_by_name_iso2_iso3_and_excludes_aggregates(api):
    assert {worldbank.resolve_country(x) for x in ("China", "cn", "CHN")} == {"CHN"}
    assert worldbank.resolve_country("World") is None
    assert worldbank.resolve_country("Taiwan") is None


def test_country_info_maps_between_code_systems(api):
    assert worldbank.country_info("CN") == {"iso3": "CHN", "iso2": "CN", "name": "China"}
    assert worldbank.country_info("China")["iso3"] == "CHN" and worldbank.country_info("Mars") is None


def test_country_data_takes_latest_observation_and_omits_missing(api):
    data = worldbank.country_data("China")
    assert data["inflation_pct"] == 0.2 and data["data_years"]["inflation_pct"] == 2024
    assert data["unemployment_pct"] == 5.0
    assert "gdp_growth_pct" not in data and "public_debt_pct_gdp" not in data
    assert data["data_source"] == "WORLD_BANK" and data["is_demo"] is False
    assert worldbank.country_data("Atlantis") is None


def test_bank_data_has_no_invented_liquidity(api):
    data = worldbank.bank_data("China")
    assert data["nonperforming_loans_pct"] == 1.5 and "capital_adequacy_pct" not in data
    assert "liquidity_coverage_pct" not in data


def test_country_api_uses_world_bank_then_falls_back_to_flagged_demo(api, monkeypatch):
    assert country_api.get_country_data("China")["data_source"] == "WORLD_BANK"
    demo = country_api.get_country_data("Canada")  # unknown to the fake API
    assert demo["is_demo"] is True and demo["data_source"] == "SYNTHETIC_DEMO_DATA"
    assert bank_api.get_bank_data("China")["data_source"] == "WORLD_BANK"
    monkeypatch.setattr(worldbank, "get_json", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    worldbank._load.cache_clear()
    assert country_api.get_country_data("China")["is_demo"] is True
