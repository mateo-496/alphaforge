from tools.risk_math import portfolio_risk, ticker_risk


def test_ticker_risk():
    assert ticker_risk({"CHN": 0.5}, {"CHN": 80}) == 40


def test_portfolio_risk():
    assert portfolio_risk({"A": 0.5, "B": 0.5}, {"A": 80, "B": 20}) == 50
