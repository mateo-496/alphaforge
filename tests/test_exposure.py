"""Exposure agent: fallback chain, tier tags, lambda blending, home-bias prior, region splitting, returns-based."""
import httpx
import numpy as np
import pytest

from agents import exposure_agent as X
from tools import exposure_priors as P
from tools import market_data


def test_home_bias_prior():
    """w_ic = h_s 1[c = home] + (1 - h_s) pi_sc, pi renormalised without the home country."""
    w = P.home_bias("USA", .6, {"USA": .5, "CHN": .3, "DEU": .2})
    assert w == pytest.approx({"USA": .6, "CHN": .4 * .6, "DEU": .4 * .4})
    assert P.home_bias("CAN", .6, {}) == {"CAN": .6, "Other": pytest.approx(.4)}   # no mix: left unattributed


def test_blend_by_tier():
    """w = lambda w_reported + (1 - lambda) w_prior."""
    w = X.blend(X.LAMBDA["text"], {"USA": 1.0}, {"USA": .5, "CHN": .5})
    assert w == pytest.approx({"USA": .9, "CHN": .1})
    assert X.LAMBDA == {"xbrl": 1.0, "text": .8, "stale": .6}


def test_regions_and_foreign_lines_follow_the_prior(monkeypatch):
    monkeypatch.setattr(X, "region_members", lambda k: {"DEU": .4, "FRA": .3, "GBR": .3})
    prior = {"USA": .5, "DEU": .3, "GBR": .1, "CHN": .1}
    out = X.resolve({"USA": .6, "REGION:EUROPE": .3}, "USA", prior, "2026-11-12")
    assert out["DEU"] == pytest.approx(.3 * .75) and out["GBR"] == pytest.approx(.3 * .25)   # by pi, not evenly
    assert "FRA" not in out and out["CHN"] == pytest.approx(.1)                              # unattributed 10% -> prior
    out = X.resolve({"HOME": .78, "FOREIGN": .22}, "USA", prior, "2026-11-12")
    assert out["USA"] == pytest.approx(.78) and out["DEU"] == pytest.approx(.22 * .6)


def test_text_tier_keeps_only_quotes_that_state_the_number(monkeypatch):
    from tests import fakes
    from core import llm
    monkeypatch.setattr(X.filings, "_annual_filing", lambda t, a: fakes.TextFiling())
    monkeypatch.setattr(llm, "ask", fakes.fake_ask)
    split, rows = X.llm_split(X.snippets(fakes.TextFiling().text()), "JPM")
    assert split == pytest.approx({"FOREIGN": .22, "HOME": .78}) and len(rows) == 1
    assert X.states("about 22 percent of revenue", .22) and not X.states("about 22 percent of revenue", .3)


def test_sector_prior_uses_only_peers_filed_by_as_of():
    for t, h, d in (("A", .5, "2025-03-01"), ("B", .7, "2025-03-01"), ("C", .6, "2025-03-01"), ("D", .1, "2027-01-01")):
        P.record(t, "USA", {"USA": h, "CHN": 1 - h}, d, "Semiconductors", "Information Technology")
    st = P.sector_stats("2026-11-12", "NVDA", "Semiconductors", "Information Technology")
    assert st["h"] == pytest.approx(.6) and st["pi"] == {"CHN": pytest.approx(1.0)} and st["h_from"] == "industry (3)"
    assert P.sector_stats("2026-11-12", "NVDA", None, "Information Technology")["h_from"] == "sector (3)"
    assert P.sector_stats("2026-11-12", "A", "Semiconductors", None)["h"] is None        # 2 peers by then: too few


def test_returns_based_recovers_country_mix():
    rng = np.random.default_rng(0)
    n, k = 104, 4
    world = rng.normal(0, .02, n)
    countries = np.column_stack([world * rng.uniform(.8, 1.2) + rng.normal(0, .015, n) for _ in range(k)])
    true = np.array([.6, .4, 0, 0])
    y = countries @ true + rng.normal(0, .002, n)
    w, r2 = P.style_weights(y, world, countries)
    assert w == pytest.approx(true, abs=.05) and abs(w.sum() - 1) < 1e-9 and (w >= 0).all() and r2 > .8


def test_blocked_sec_request_is_not_no_filing(monkeypatch):
    monkeypatch.setenv("SEC_IDENTITY", "Test t@test.org")
    monkeypatch.setattr(market_data.httpx, "get", lambda url, **kw: httpx.Response(403, request=httpx.Request("GET", url)))
    with pytest.raises(market_data.SecBlocked) as e:
        market_data._sec_get("https://data.sec.gov/submissions/CIK0000000001.json")
    assert e.value.status == 403


def test_xbrl_is_point_in_time_and_stale_falls_back(monkeypatch):
    monkeypatch.setattr(market_data, "_ticker_map", lambda: {"0": {"ticker": "ACME", "cik_str": 1}})
    recent = {"form": ["10-K", "10-K", "10-K"], "accessionNumber": ["3", "2", "1"],
              "filingDate": ["2027-02-01", "2026-02-01", "2025-02-01"], "reportDate": ["2026-12-31", "2025-12-31", "2024-12-31"]}
    monkeypatch.setattr(market_data, "cached", lambda ns, params, fetch, **kw:
                        {"filings": {"recent": recent}} if ns == "sec-submissions" else fetch())
    splits = {"2": {"status": "no_country_revenue_found", "exposures": [], "fiscal_year": 2025},
              "1": {"status": "available", "exposures": [{"country": "US", "revenue_share": .7}], "fiscal_year": 2024}}
    monkeypatch.setattr(market_data, "_xbrl_split", lambda t, f: splits[f["accession"]])
    out = market_data.get_country_exposures("ACME", "2026-11-12")      # the 2027 filing is after as_of: ignored
    assert out["status"] == "available" and out["stale"] and out["used_filing"]["accession"] == "1"
    assert out["filing"]["accession"] == "2"                           # the latest filing, for the text tier


def test_slow_filing_text_falls_back_to_the_prior(monkeypatch):
    import time
    from core import config
    from tests import fakes
    fakes.install(monkeypatch)
    monkeypatch.setattr(config, "EXPOSURE_TEXT_WAIT_S", 1)
    monkeypatch.setattr(X, "text_split", lambda *a: time.sleep(5))
    monkeypatch.setattr(X.storage, "read_json", lambda k: None)
    h = {"sec_ticker": "TM", "exposure_status": "no_country_revenue_found", "exposures": {},
         "filing": {"report_date": "2026-03-31", "filing_date": "2026-06-20", "form": "20-F", "base": "u"}}
    t0 = time.monotonic()
    rep = X.split("TM", {"asset_class": "equity", "country": "Japan", "sector": "Consumer"}, h, "2026-11-12")
    assert time.monotonic() - t0 < 4 and rep["estimated"] and "not read within 1s" in rep["method"]


def _fx(monkeypatch, store=None):
    from tests import fakes
    fakes.install(monkeypatch)
    store = {} if store is None else store
    monkeypatch.setattr(X.storage, "read_json", lambda k: store.get(k))
    monkeypatch.setattr(X.storage, "write_json", lambda k, v: store.__setitem__(k, v))
    return store


H = {"sec_ticker": "TM", "exposure_status": "no_country_revenue_found", "exposures": {},
     "filing": {"accession": "000123", "report_date": "2026-03-31", "filing_date": "2026-06-20", "form": "20-F", "base": "u"}}
EQ = {"asset_class": "equity", "country": "JPN", "sector": "Consumer Discretionary"}


def test_regex_reads_the_split_without_the_llm():
    sn = ["Segment information. In fiscal 2025, 38% of our net revenues were from Japan, 30% of our revenues "
          "came from North America, 17% of our revenue from Europe and 15% of our revenue from other countries. "
          "In fiscal 2024, 40% of our net revenues were from Japan."]
    split, rows = X.regex_split(sn, "JPN")
    assert split == pytest.approx({"HOME": .38, "REGION:NORTHAM": .30, "REGION:EUROPE": .17, "REGION:ROW": .15})
    assert X.regex_split(["Sales in China accounted for 12% of our revenue. Sales in Taiwan were 88% of our revenue."],
                         "TWN")[0] == pytest.approx({"CHN": .12, "HOME": .88})
    assert X.regex_split(["Substantially all of our revenue is generated in India."], "IND")[0] == {"IND": 1.0}


def test_cheap_checks_stop_before_the_text(monkeypatch):
    _fx(monkeypatch)
    read = []
    monkeypatch.setattr(X, "main_text", lambda *a: read.append(1) or "")
    assert X.split("TM", EQ, H, "2026-11-12", weight=0.01)["step"] == "prior:small"
    monkeypatch.setattr(X.P, "industry", lambda t: "Banks - Regional")
    rep = X.split("TM", EQ, H, "2026-11-12", weight=0.10)
    assert rep["step"] == "prior:domestic" and rep["country_weights"]["JPN"] == pytest.approx(.9) and not read


def test_text_result_is_cached_by_accession(monkeypatch):
    from core import llm
    store = _fx(monkeypatch)
    calls = []
    monkeypatch.setattr(X, "main_text", lambda *a: calls.append(1) or
                        "Geographic information: 22% of our revenue came from customers outside Japan.")
    monkeypatch.setattr(llm, "ask", lambda *a, **k: pytest.fail("the regex should have been enough"))
    first = X.split("TM", EQ, H, "2026-11-12", weight=0.10)
    assert first["step"] == "regex" and first["tier"]["code"] == "text"
    again = X.split("TM", EQ, H, "2026-11-12", weight=0.10)
    assert again["step"] == "cache" and again["country_weights"] == first["country_weights"] and len(calls) == 1
    amended = {**H, "filing": {**H["filing"], "accession": "000999"}}
    assert X.split("TM", EQ, amended, "2026-11-12", weight=0.10)["step"] == "carry" and len(calls) == 1


def test_no_snippet_means_no_llm(monkeypatch):
    from core import llm
    _fx(monkeypatch)
    monkeypatch.setattr(X, "main_text", lambda *a: "Nothing about where sales come from.")
    monkeypatch.setattr(llm, "ask", lambda *a, **k: pytest.fail("no LLM without a snippet"))
    assert X.split("TM", EQ, H, "2026-11-12", weight=0.10)["step"] == "prior:nomatch"


def test_late_text_result_is_saved_for_the_next_run(monkeypatch):
    """A text pass that misses the deadline still lands in the cache: this run uses the prior, the next one reads it."""
    import threading
    from core import config
    store = _fx(monkeypatch)
    monkeypatch.setattr(config, "EXPOSURE_TEXT_WAIT_S", 0.2)
    gate = threading.Event()

    def slow(*a):
        gate.wait(5)
        return {"HOME": .78, "USA": .22}, [], "regex"
    monkeypatch.setattr(X, "text_split", slow)
    first = X.split("TM", EQ, H, "2026-11-12", weight=0.10)
    assert first["step"] == "prior:timeout" and first["estimated"]
    gate.set()
    for _ in range(50):                                  # the callback runs on the worker thread
        if f"{X.SPLITS}/000123.json" in store:
            break
        threading.Event().wait(0.05)
    monkeypatch.setattr(X, "text_split", lambda *a: pytest.fail("saved: no second read"))
    again = X.split("TM", EQ, H, "2026-11-12", weight=0.10)
    assert again["step"] == "cache" and again["tier"]["code"] == "text"
