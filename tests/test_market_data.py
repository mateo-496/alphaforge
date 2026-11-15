import io
import json
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest
from bs4 import BeautifulSoup
from botocore.exceptions import ClientError

from tools.market_cache import cached
from tools import market_data
from tools.mcp_server import get_country_market_series


class FakeS3:
    def __init__(self):
        self.objects = {}
        self.reads = 0

    def get_object(self, Bucket, Key):
        self.reads += 1
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": io.BytesIO(self.objects[Key])}

    def put_object(self, Bucket, Key, Body, **kwargs):
        self.objects[Key] = Body


def test_s3_cache_reuses_then_refreshes(monkeypatch):
    s3 = FakeS3()
    monkeypatch.setenv("S3_BUCKET", "example")
    monkeypatch.setattr("tools.market_cache.boto3.client", lambda service: s3)
    calls = []

    def fetch():
        calls.append(True)
        return {"value": len(calls)}

    assert cached("test", {"series": "US"}, fetch) == {"value": 1}
    assert cached("test", {"series": "US"}, fetch) == {"value": 1}
    assert len(calls) == 1
    key = next(iter(s3.objects))
    entry = json.loads(s3.objects[key])
    entry["cached_at"] = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    s3.objects[key] = json.dumps(entry).encode()
    assert cached("test", {"series": "US"}, fetch) == {"value": 2}


def test_s3_access_errors_not_hidden(monkeypatch):
    monkeypatch.setenv("S3_BUCKET", "example")

    class Denied:
        def get_object(self, **kwargs):
            raise ClientError({"Error": {"Code": "AccessDenied"}}, "GetObject")

    monkeypatch.setattr("tools.market_cache.boto3.client", lambda service: Denied())
    with pytest.raises(ClientError):
        cached("test", {}, lambda: {})


def test_euro_area_series_reused_across_countries(monkeypatch):
    s3 = FakeS3()
    monkeypatch.setenv("S3_BUCKET", "example")
    monkeypatch.setattr("tools.market_cache.boto3.client", lambda service: s3)
    calls = []

    def fetch(series_id, as_of, days):
        calls.append(series_id)
        return {"name": series_id}

    monkeypatch.setattr("tools.market_stress.get_market_series", fetch)
    first = get_country_market_series("FR", "2026-11-10")
    second = get_country_market_series("DE", "2026-11-10")
    assert first["series"] == second["series"]
    assert calls == ["DEXUSEU"]
    assert get_country_market_series("ZZ", "2026-11-10")["status"] == "unsupported"


def test_exposures_from_filing_and_unknown_ticker(monkeypatch):
    monkeypatch.setattr("tools.market_data.cached", lambda namespace, params, fetch: fetch())
    monkeypatch.setattr("tools.market_data._ticker_map",
                        lambda: {"0": {"ticker": "ASML", "cik_str": 123}})
    submission = {"filings": {"recent": {"form": ["20-F"], "accessionNumber": ["1-2-3"],
                                         "reportDate": ["2025-12-31"]}}}

    class Response:
        def __init__(self, value):
            self.value = value
            self.content = value.encode() if isinstance(value, str) else b""
            self.text = value if isinstance(value, str) else ""

        def json(self):
            return self.value

    def get(url):
        if url.endswith(".json"):
            return Response(submission)
        if url.endswith("FilingSummary.xml"):
            return Response("<FilingSummary><Report><ShortName>Geographic Revenue</ShortName>"
                            "<HtmlFileName>R3.htm</HtmlFileName></Report></FilingSummary>")
        return Response(
            "<h1>Geographic Revenue (in millions)</h1><table>"
            "<tr><th>Year ended 2025</th><th>Net sales</th></tr>"
            "<tr><td>United States</td><td>2,000</td></tr>"
            "<tr><td>China</td><td>1,000</td></tr>"
            "<tr><td>Total revenues</td><td>4,000</td></tr></table>")

    monkeypatch.setattr("tools.market_data._sec_get", get)
    result = market_data.get_country_exposures("ASML")
    assert result["exposures"][0]["revenue_share"] == 0.25
    assert result["exposures"][1]["revenue_share"] == 0.5
    assert result["exposures"][0]["source"]["url"].endswith("/R3.htm")
    assert market_data.get_country_exposures("UNKNOWN")["status"] == "no_sec_ticker"


def _mock_geography_tables(monkeypatch, year_headers):
    monkeypatch.setattr("tools.market_data.cached", lambda namespace, params, fetch: fetch())
    monkeypatch.setattr("tools.market_data._ticker_map",
                        lambda: {"0": {"ticker": "ASML", "cik_str": 123}})
    submission = {"filings": {"recent": {"form": ["20-F"], "accessionNumber": ["1-2-3"],
                                         "reportDate": ["2025-12-31"]}}}

    class Response:
        def __init__(self, value):
            self.value = value
            self.content = value.encode() if isinstance(value, str) else b""
            self.text = value if isinstance(value, str) else ""

        def json(self):
            return self.value

    def get(url):
        if url.endswith(".json"):
            return Response(submission)
        if url.endswith("FilingSummary.xml"):
            return Response("<FilingSummary>" + "".join(
                f"<Report><ShortName>Geographic Revenue</ShortName>"
                f"<HtmlFileName>R{i}.htm</HtmlFileName></Report>"
                for i in range(1, len(year_headers) + 1)
            ) + "</FilingSummary>")
        index = int(url.rsplit("R", 1)[1].split(".")[0]) - 1
        years = year_headers[index]
        return Response(f"<table><tr><th>Year ended {years}</th></tr>"
                        "<tr><td>Net sales</td></tr><tr><td>China</td><td>9,500</td></tr>"
                        "<tr><td>United States</td><td>4,000</td></tr>"
                        "<tr><td>Total</td><td>32,000</td></tr></table>")

    monkeypatch.setattr("tools.market_data._sec_get", get)
    monkeypatch.setattr("tools.market_data.geo.find_geo_table",
                        lambda html: BeautifulSoup(html, "html.parser").table)


def test_exposures_skip_oldest_first_table_and_use_latest_year(monkeypatch):
    _mock_geography_tables(monkeypatch, ["2023 2024 2025", "2025 2024 2023"])
    parsed = []

    def parse(table, html, fiscal_year):
        parsed.append(table.get_text(" ", strip=True))
        return {"fiscal_year": fiscal_year, "segments": [("CN", 29.14), ("US", 12.52)]}

    monkeypatch.setattr("tools.market_data.geo.parse_geo_table", parse)
    result = market_data.get_country_exposures("ASML")
    assert len(parsed) == 1
    assert "2025 2024 2023" in parsed[0]
    assert result["status"] == "available"
    assert result["exposures"][0]["revenue_share"] == pytest.approx(0.2914)
    assert result["exposures"][0]["source"]["url"].endswith("/R2.htm")


def test_exposures_oldest_first_only_stay_unknown(monkeypatch):
    _mock_geography_tables(monkeypatch, ["2023 2024 2025"])
    result = market_data.get_country_exposures("ASML")
    assert result["status"] == "unsupported_fiscal_year_order"
    assert result["exposures"] == []


def test_exposures_conflicting_usable_tables_still_fail(monkeypatch):
    _mock_geography_tables(monkeypatch, ["2025 2024 2023", "2025 2024 2023"])
    results = iter([
        {"fiscal_year": 2025, "segments": [("CN", 29.0)]},
        {"fiscal_year": 2025, "segments": [("CN", 30.0)]},
    ])
    monkeypatch.setattr("tools.market_data.geo.parse_geo_table", lambda *args: next(results))
    with pytest.raises(ValueError, match="Conflicting geographic revenue tables"):
        market_data.get_country_exposures("ASML")


def test_price_history_uses_adjusted_prices_and_cites_currency(monkeypatch):
    class Instrument:
        history_metadata = {"currency": "EUR"}

        def history(self, **kwargs):
            assert kwargs["auto_adjust"]
            return pd.DataFrame({"Close": [10.0, 12.0]}, index=pd.to_datetime(["2026-01-02", "2026-01-05"]))

    monkeypatch.setattr("tools.market_data.cached", lambda namespace, params, fetch: fetch())
    monkeypatch.setattr("tools.market_data.yf.Ticker", lambda ticker: Instrument())
    result = market_data.get_price_history("ASML.AS", "2026-01-05")
    assert result["unit"] == "EUR"
    assert result["observations"][-1] == {"date": "2026-01-05", "value": 12.0}
    assert "finance.yahoo.com" in result["source"]["url"]


def test_price_history_rejects_future_dates():
    with pytest.raises(ValueError, match="Invalid as_of"):
        market_data.get_price_history("MSFT", (date.today() + timedelta(days=1)).isoformat())


def test_combined_china_hong_kong_label_is_attributed_to_china():
    assert market_data._geo_parser._resolve_seg("China (including Hong Kong)") == "CN"
    assert market_data._geo_parser._resolve_seg("China (including Hong Kong) (2)") == "CN"
    assert market_data._geo_parser._resolve_seg("Hong Kong") == "HK"


def _two_tables(monkeypatch, results):
    _mock_geography_tables(monkeypatch, ["2025 2024 2023"] * len(results))
    outputs = iter(results)
    monkeypatch.setattr("tools.market_data.geo.parse_geo_table",
                        lambda table, html, year: {"fiscal_year": year, "segments": next(outputs)})


def test_exposures_prefer_fullest_consistent_table(monkeypatch):
    _two_tables(monkeypatch, [[("US", 69.0), ("TW", 20.0), ("CN", 9.0)], [("US", 69.0), ("CN", 9.0)]])
    result = market_data.get_country_exposures("ASML")
    assert {e["country"] for e in result["exposures"]} == {"US", "TW", "CN"}


def test_exposures_with_contradicting_tables_need_review(monkeypatch):
    _two_tables(monkeypatch, [[("US", 69.0), ("CN", 9.0)], [("US", 60.0), ("CN", 9.0)]])
    with pytest.raises(ValueError, match="Conflicting"):
        market_data.get_country_exposures("ASML")
