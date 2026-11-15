from tools.risk_math import portfolio_risk, ticker_risk


def test_ticker_risk():
    assert ticker_risk({"CHN": 0.5}, {"CHN": 80}) == 40


def test_portfolio_risk():
    assert portfolio_risk({"A": 0.5, "B": 0.5}, {"A": 80, "B": 20}) == 50


def test_v2_is_additive_and_mechanical():
    from tools.risk_math import firm_flags, holding_score, percentile, portfolio_score, scenario_exposure
    assert percentile(5, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]) == .5
    g = {"USA": .5, "TWN": .9, "Other": .7}
    a = holding_score({"USA": .6, "TWN": .4}, g, 1.0, None)          # 100 * (.6*.5 + .4*.9) = 66
    b = holding_score({"USA": 1.0}, g, 1.3, firm_flags(["sanctions", "sanctions", "tariffs"]))  # f = 2/8
    assert abs(a["G"] - 66) < 1e-9 and abs(b["G"] - (80 * 1.3 * .5 + 20 * .25)) < 1e-9
    ps = portfolio_score({"A": .5, "B": .5}, {"A": a, "B": b})
    assert abs(sum(ps["by_holding"].values()) - ps["P"]) < 1e-9
    assert abs(sum(ps["by_country"].values()) + ps["firm"] - ps["P"]) < 1e-9
    assert firm_flags(None) is None
    s = {"countries": {"TWN": 1.0, "USA": .3}}
    assert scenario_exposure(s, {"TWN": .2, "USA": .5}) == .2         # USA below the involvement threshold


def test_market_amplifier():
    from tools.risk_math import amplifier, market_stress_level
    assert market_stress_level({"OFR_FSI": 2.0, "STLFSI4": 1.0, "VIXCLS": None}) == 1.5
    assert amplifier(-1.0) == 1.0 and amplifier(None) == 1.0 and abs(amplifier(10) - 1.45) < 1e-9


def test_verdict_by_profile():
    from tools.risk_math import verdict
    assert verdict(58, 3, 1.0, 0)["clear"] and not verdict(58, 2, 1.0, 0)["clear"]   # tolerance 60 vs 55
    assert not verdict(40, 5, 1.3, 0)["clear"] and not verdict(40, 5, 1.0, 1)["clear"]


def test_z_features():
    from tools.risk_math import level_z, move_z
    assert level_z([1.0] * 40) is None and level_z([1.0] * 10) is None
    assert level_z([0.0] * 39 + [1.0]) > 5
    assert move_z(list(range(60))) is None
