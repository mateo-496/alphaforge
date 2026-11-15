"""Profile-fitted recommendations: deterministic, re-scored, empty when there is no immediate danger."""
from tools import risk_math
from web import recommend

UNI = {"NVDA": {"asset_class": "equity"}, "BTC-USD": {"asset_class": "crypto"},
       **{f: {"asset_class": c} for f, c in [("XBB.TO", "etf_bond"), ("AGG", "etf_bond"), ("SPY", "etf_equity"),
                                             ("ESGV", "etf_equity"), ("GLD", "etf_commodity")]}}
G = {"USA": .5, "TWN": .95, "CAN": .3, "Other": .6}


def parts(cw):
    return risk_math.holding_score(cw, G, 1.0, None)


def setup(p, weights):
    cands = recommend.candidates(p, weights, UNI)
    cw = {"XBB.TO": {"CAN": 1.0}, "AGG": {"USA": 1.0}, "SPY": {"USA": 1.0}, "ESGV": {"USA": 1.0}, "GLD": {"Other": 1.0}}
    hp = {"NVDA": parts({"TWN": .6, "USA": .4}), "BTC-USD": parts({"Other": 1.0})}
    return cands, {c: parts(cw[c]) for c in cands}, {c: cw[c] for c in cands}, hp


def test_profile_drives_the_fund():
    retiree = {"horizon_years": 4, "risk_level": 2, "objective_level": 1, "max_single_weight": .1}
    growth = {"horizon_years": 15, "risk_level": 5, "objective_level": 5, "max_single_weight": .25}
    esg = {"horizon_years": 10, "risk_level": 3, "objective_level": 3, "esg_importance": "high"}
    assert set(recommend.candidates(retiree, {}, UNI)) == {"XBB.TO", "AGG", "GLD", "SPY", "ESGV"}
    assert set(recommend.candidates(growth, {}, UNI)) == {"SPY", "ESGV"}           # no bonds for growth
    assert "SPY" not in recommend.candidates(esg, {}, UNI)                          # ESG funds only


def test_clear_means_no_trade():
    p = {"horizon_years": 15, "risk_level": 5, "objective_level": 5, "max_single_weight": 1}
    cands, cp, ccw, hp = setup(p, {"NVDA": 1.0})
    hp["NVDA"] = parts({"USA": 1.0})                         # score 50, tolerance 70
    v = risk_math.verdict(risk_math.portfolio_score({"NVDA": 1.0}, hp)["P"], 5, 1.0, 0)
    assert v["clear"] and recommend.propose(p, {"NVDA": 1.0}, hp, cp, ccw, [], v, UNI, {}) == []


def test_limits_then_risk_with_rescoring():
    p = {"horizon_years": 4, "risk_level": 2, "objective_level": 1, "max_single_weight": .4, "crypto_max": 0.0}
    w = {"NVDA": .8, "BTC-USD": .2}
    cands, cp, ccw, hp = setup(p, w)
    checks = [{"ticker": "NVDA", "text": "NVDA is 80% of the portfolio, above the 40% single-holding limit."},
              {"ticker": "crypto", "text": "Crypto is 20% of the portfolio; the limit is 0%."}]
    P = risk_math.portfolio_score(w, hp)["P"]
    v = risk_math.verdict(P, 2, 1.0, len(checks))
    out = recommend.propose(p, w, hp, cp, ccw, checks, v, UNI, {"TWN": "Taiwan"})
    assert [s["kind"] for s in out[:2]] == ["profile", "profile"]
    assert out[0]["from"] == "NVDA" and abs(out[0]["fraction"] - .5) < 1e-9 and out[1]["from"] == "BTC-USD"
    assert all(s["to"] == "XBB.TO" for s in out)          # lowest-hazard bond fund for a retiree
    assert all(s["score_after"] < s["score_before"] for s in out) and out[-1]["score_after"] < P
