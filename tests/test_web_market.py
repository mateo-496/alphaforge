"""Market data per holding and the exposure agent on top of it: reported splits win, failures degrade, never crash."""
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

    def expo(t, as_of=None):
        if t == "NVDA":
            return {"ticker": t, "status": "available", "fiscal_year": 2025, "stale": False, "filing": None,
                    "exposures": [{"country": "US", "revenue_share": .44, "source": SRC},
                                  {"country": "TW", "revenue_share": .16, "source": SRC}]}
        if t == "RY":
            return {"ticker": t, "status": "no_annual_filing", "exposures": [], "stale": False, "filing": None}
        raise RuntimeError("SEC down")
    monkeypatch.setattr(market.market_data, "get_price_history", prices)
    monkeypatch.setattr(market.market_data, "get_country_exposures", expo)
    from tools import exposure_priors, worldbank
    monkeypatch.setattr(exposure_priors, "industry", lambda t: None)
    monkeypatch.setattr(worldbank, "gdp_weights", lambda as_of, top=60: {"USA": .5, "CHN": .3, "DEU": .2})


def test_sec_ticker_mapping():
    u = U.universe()
    assert market.sec_ticker("RY.TO", u["RY.TO"]) == "RY"
    assert market.sec_ticker("CNR.TO", u["CNR.TO"]) == "CNI"
    assert market.sec_ticker("SPY", u["SPY"]) is None and market.sec_ticker("BTC-USD", u["BTC-USD"]) is None


def test_disclosed_exposure_wins(stub):
    h = market.fetch_holding("NVDA", U.universe()["NVDA"], "2026-11-12")
    rep = pipeline._asset_report("NVDA", h, "2026-11-12")
    cw = rep["country_weights"]
    assert not rep["estimated"] and rep["tier"]["code"] == "xbrl" and rep["source"]["url"] == SRC["url"]
    assert cw["USA"] >= .44 and cw["TWN"] >= .16 and abs(sum(cw.values()) - 1) < 1e-6   # unreported 40% follows the prior


def test_failures_fall_back_to_the_prior(stub):
    h = market.fetch_holding("RY.TO", U.universe()["RY.TO"], "2026-11-12")
    rep = pipeline._asset_report("RY.TO", h, "2026-11-12")
    assert rep["estimated"] and rep["tier"]["code"] == "home_bias" and "no annual filing" in rep["method"]
    assert rep["country_weights"]["CAN"] == pytest.approx(.6)          # home share, foreign mix from GDP
    h2 = market.fetch_holding("AAPL", U.universe()["AAPL"], "2026-11-12")
    assert h2["exposure_status"] == "error" and pipeline._asset_report("AAPL", h2, "2026-11-12")["estimated"]


def test_price_stats():
    st = market.price_stats({"observations": obs(30, 100, 1) + [{"date": "2026-03-01", "value": 65.0}]})
    assert st["ret"] == pytest.approx(65 / 100 - 1) and st["max_drawdown"] == pytest.approx(65 / 129 - 1)
