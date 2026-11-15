"""Website adapter for the market-stress tools: real exposures replace estimates; failures degrade, never crash."""
import pytest

from web import market, pipeline, universe as U

SRC = {"title": "t", "url": "https://www.sec.gov/x/R4.htm", "locator": "Revenue by geography; fiscal year 2025",
       "retrieved_at": "2026-11-14T00:00:00+00:00"}


def obs(n, start=100.0, step=1.0):
    return [{"date": f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}", "value": start + step * i} for i in range(n)]


@pytest.fixture
def stub(monkeypatch):
    def prices(t, as_of, days=90):
        if t == "BADPX":
            raise ConnectionError("offline")
        return {"name": t, "unit": "USD", "observations": obs(60), "source": SRC}

    def expo(t):
        if t == "NVDA":
            return {"ticker": t, "status": "available", "fiscal_year": 2025,
                    "exposures": [{"country": "US", "revenue_share": .44, "source": SRC},
                                  {"country": "TW", "revenue_share": .16, "source": SRC}]}
        if t == "RY":
            return {"ticker": t, "status": "no_annual_filing", "exposures": []}
        raise RuntimeError("SEC down")
    monkeypatch.setattr(market.market_data, "get_price_history", prices)
    monkeypatch.setattr(market.market_data, "get_country_exposures", expo)


def test_sec_ticker_mapping():
    u = U.universe()
    assert market.sec_ticker("RY.TO", u["RY.TO"]) == "RY"
    assert market.sec_ticker("CNR.TO", u["CNR.TO"]) == "CNI"
    assert market.sec_ticker("SPY", u["SPY"]) is None and market.sec_ticker("BTC-USD", u["BTC-USD"]) is None


def test_disclosed_exposure_replaces_estimate(stub):
    h = market.fetch_holding("NVDA", U.universe()["NVDA"], "2026-11-12")
    rep = pipeline._asset_report("NVDA", h, "2026-11-12")
    assert not rep["estimated"] and rep["method"] == "SEC filing, FY2025"
    assert rep["country_weights"] == {"USA": .44, "TWN": .16, "Other": .4}   # unreported share kept as Other
    assert rep["source"]["url"] == SRC["url"]


def test_failures_fall_back_to_labelled_estimate(stub):
    h = market.fetch_holding("RY.TO", U.universe()["RY.TO"], "2026-11-12")
    rep = pipeline._asset_report("RY.TO", h, "2026-11-12")
    assert rep["estimated"] and "40-F" in rep["method"]
    h2 = market.fetch_holding("AAPL", U.universe()["AAPL"], "2026-11-12")
    assert h2["exposure_status"] == "error" and pipeline._asset_report("AAPL", h2, "2026-11-12")["estimated"]


def test_price_stats():
    st = market.price_stats({"observations": obs(30, 100, 1) + [{"date": "2026-03-01", "value": 65.0}]})
    assert st["ret"] == pytest.approx(65 / 100 - 1) and st["max_drawdown"] == pytest.approx(65 / 129 - 1)


def test_summarise_without_stress_data():
    res = {"facts": [], "series_status": {}, "country_status": {"BRA": "unsupported"}, "as_of": "2026-11-12",
           "global_z": {}, "m": None, "country_z": {}}
    holdings = {"NVDA": {"prices": None, "price_error": "offline", "exposure_status": "error"}}
    view = market.summarise(res, holdings, {"NVDA": 1.0}, U.universe(), {})
    assert view["unpriced"] == ["NVDA"] and view["unsupported_countries"] == ["BRA"]
    assert view["m"] is None and view["amplifier"] == 1.0
