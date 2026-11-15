"""Country hazard (tools/risk_math.hazard), the company sleeve and the final calibration (tools/portfolio_score)."""
import math

from tools import gpr, risk_math as rm
from tools.portfolio_score import Params, portfolio_scores
from web import scoring


def test_instability_scale():
    assert rm.instability(None) is None
    assert rm.instability(rm.PV_SAFE) == 0.0
    assert rm.instability(rm.PV_DANGER) == 1.0
    assert rm.instability(2.5) == 0.0 and rm.instability(-2.5) == 1.0
    assert rm.instability(1.0) < rm.instability(0.0) < rm.instability(-1.0)


def test_tension_log_scale_and_press_countries():
    anchors = (math.log(0.03), math.log(2.0))
    assert rm.tension(0.03, anchors, "CHL") == 0.0
    assert rm.tension(2.0, anchors, "ISR") == 1.0
    assert 0 < rm.tension(0.2, anchors, "NOR") < rm.tension(1.2, anchors, "CHN") < 1
    for c in rm.PRESS_COUNTRIES:   # home coverage inflates their GPR level
        assert rm.tension(4.5, anchors, c) is None
    assert rm.tension(None, anchors) is None and rm.tension(0.5, None) is None


def test_hazard_level_times_heat():
    assert rm.hazard(None, None, 0.9) is None            # heat alone is not a hazard
    assert rm.hazard(0.2, None, 1.0) == 0.2              # full heat: the level itself
    assert rm.hazard(0.2, None, 0.0) == 0.1              # calm month: half the level
    assert rm.hazard(0.2, 0.6, 1.0) == 0.4               # level = mean of the available parts
    assert rm.hazard(0.2, None, None) == 0.2 * 0.75      # unknown heat: neutral
    # A calm country at a news peak stays below an unstable country in a quiet month.
    assert rm.hazard(0.15, 0.3, 0.98) < rm.hazard(0.7, 0.9, 0.3)


def test_tension_anchors_on_table():
    months = [f"{y}-{m:02d}" for y in range(2000, 2026) for m in range(1, 13)]
    series = {"GLOBAL": [100.0] * len(months)}
    for i, c in enumerate(["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG", "HHH", "III", "JJJ", "KKK", "USA"]):
        series[c] = [0.1 * (i + 1)] * len(months)
    lo, hi = gpr.tension_anchors({"months": months, "series": series}, "2026-01-15")
    assert math.isclose(hi, math.log(1.1))               # max over non-press countries (USA = 1.2 left out)
    assert lo < hi


def test_firm_share_one_is_original_formula():
    a = portfolio_scores(0.3, 0.4, 0.6, 0.5, conf=(1, 1, 0.8))
    b = portfolio_scores(0.3, 0.4, 0.6, 0.5, conf=(1, 1, 0.8), firm_share=1.0)
    assert a == b


def test_no_companies_means_no_company_term():
    """A bond fund has no filing: A3 must not count (neither its value nor the 0.5 prior)."""
    lo = portfolio_scores(0.3, 0.2, 0.0, 0.5, conf=(1, 1, 0), firm_share=0.0)
    hi = portfolio_scores(0.3, 0.2, 1.0, 0.5, conf=(1, 1, 1), firm_share=0.0)
    assert lo["objective"] == hi["objective"]
    assert lo["objective"] < portfolio_scores(0.3, 0.2, None, 0.5, conf=(1, 1, 0))["objective"]


def test_scoring_company_sleeve():
    cw = {"BOND": {"CAN": 1.0}, "CO": {"CAN": 1.0}}
    M, g, f = {"CAN": 0.3}, {"CAN": 0.2}, {"BOND": None, "CO": 1.0}
    funds = scoring.portfolio({"BOND": 1.0}, cw, M, g, f, 0.6, companies={"CO"})
    mixed = scoring.portfolio({"BOND": 0.5, "CO": 0.5}, cw, M, g, f, 0.6, companies={"CO"})
    assert funds["firm_share"] == 0.0 and mixed["firm_share"] == 0.5
    assert funds["objective"] < mixed["objective"]       # a risky filing on half the portfolio raises the score


def test_calibration_identity_by_default_and_monotone():
    p = Params(r_mid=0.5, r_k=1.0)
    assert portfolio_scores(0.4, 0.4, 0.4, 0.5, p=p)["objective"] == \
        portfolio_scores(0.4, 0.4, 0.4, 0.5, p=Params(r_mid=0.5, r_k=1.0, q=Params().q))["objective"]
    p = Params(r_mid=0.4, r_k=4.0)
    xs = [portfolio_scores(x, x, x, 0.5, p=p)["objective"] for x in (0.0, 0.2, 0.3, 0.4, 0.5, 0.7, 1.0)]
    assert xs == sorted(xs) and xs[0] == 0.0 and xs[-1] == 100.0
