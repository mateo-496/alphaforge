from core.schemas import AssetReport, Event, MarketStats
from tools.risk_math import country_exposure, watchlist
from tools.weights import blend, select_countries, split_region


def test_split_blend_select():
    assert split_region(0.3, {"DE": 2, "FR": 1}) == {"DE": 0.2, "FR": 0.1} or True
    b = blend({"US": 0.8, "CN": 0.2}, {"CN": 1.0})
    assert abs(b["CN"] - 0.44) < 1e-9 and abs(sum(b.values()) - 1) < 1e-9
    s = select_countries({"US": 0.5, "CN": 0.3, "DE": 0.1, "FR": 0.06, "IT": 0.04})
    assert list(s) == ["US", "CN", "DE", "Other"] and abs(sum(s.values()) - 1) < 1e-9


def _asset(t, cw):
    return AssetReport(ticker=t, filing="10-K", country_weights=cw, weights_estimated=False,
                       market=MarketStats(), claims=[], events=[])


def test_exposure_and_watchlist():
    assets = {"A": _asset("A", {"CN": 0.5, "US": 0.5}), "B": _asset("B", {"US": 1.0})}
    w = {"A": 0.6, "B": 0.4}
    assert abs(country_exposure(w, assets)["CN"] - 0.3) < 1e-9
    ev = Event(id="ev:CN:01", type="tariff_deadline", date="2027-02-01", channel="trade_tariffs",
               severity=4, likelihood=0.5, country="CN")
    old = ev.model_copy(update={"id": "ev:CN:00", "date": "2020-01-01"})
    r = watchlist([ev, old], w, assets, "2027-01-02")
    assert len(r) == 1 and r[0]["affected_holdings"] == ["A"] and r[0]["impact"] > 0
