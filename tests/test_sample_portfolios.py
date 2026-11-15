import math

from core.sample_portfolios import countries, em_weight, load, regions

ISO3_REGIONS_REQUIRED = {"Japan & Korea", "Europe", "Latin America", "Africa", "Asia ex Japan/Korea"}


def test_sample_portfolios_valid():
    data = load()
    assets, ports = data["assets"], data["portfolios"]
    assert len(ports) == 10 and len({p["id"] for p in ports}) == 10
    for p in ports:
        pid, tickers = p["id"], [h["ticker"] for h in p["holdings"]]
        assert len(tickers) == len(set(tickers)), pid
        assert all(t in assets for t in tickers), pid
        assert math.isclose(sum(h["weight"] for h in p["holdings"]), 1.0, abs_tol=1e-6), pid
        assert max(h["weight"] for h in p["holdings"]) <= p["profile"]["max_single_holding"] + 1e-9, pid
        assert em_weight(p, assets) <= p["profile"]["max_em"] + 1e-9, pid
        assert len(countries(p, assets)) >= 15, pid
        assert ISO3_REGIONS_REQUIRED <= regions(p, data), (pid, ISO3_REGIONS_REQUIRED - regions(p, data))
        for c, cap in p["profile"].get("max_country", {}).items():
            assert sum(h["weight"] for h in p["holdings"] if assets[h["ticker"]]["country"] == c) <= cap, pid
        assert p["scenarios"] and all(len(c) == 3 for s in p["scenarios"] for c in s["countries"])


def test_all_countries_iso3():
    data = load()
    known = set().union(*map(set, data["regions"].values()))
    for t, a in data["assets"].items():
        for c in [a.get("country"), *a.get("ops", [])]:
            assert c is None or (len(c) == 3 and c in known), (t, c)
