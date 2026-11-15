"""Volatility and beta of a holding from Yahoo Finance daily prices."""
from math import log, sqrt
from statistics import fmean

from tools import market_data

BENCHMARK = "SPY"
LOOKBACK_DAYS = 400
MIN_RETURNS = 120


def _returns(series: dict) -> dict[str, float]:
    obs = series["observations"]
    return {b["date"]: log(b["value"] / a["value"]) for a, b in zip(obs, obs[1:])}


def vol_and_beta(ticker: str, as_of: str) -> dict:
    """Annualised volatility and beta vs SPY over about one year of daily returns, using only dates both share.
    Fields are None when there are too few observations."""
    own = _returns(market_data.get_price_history(ticker, as_of, LOOKBACK_DAYS))
    bench = _returns(market_data.get_price_history(BENCHMARK, as_of, LOOKBACK_DAYS))
    dates = sorted(set(own) & set(bench))
    if len(dates) < MIN_RETURNS:
        return {"vol_1y": None, "beta": None, "observations": len(dates)}
    x = [own[d] for d in dates]
    y = [bench[d] for d in dates]
    mx, my = fmean(x), fmean(y)
    var_x = sum((a - mx) ** 2 for a in x) / (len(x) - 1)
    var_y = sum((b - my) ** 2 for b in y) / (len(y) - 1)
    cov = sum((a - mx) * (b - my) for a, b in zip(x, y)) / (len(x) - 1)
    return {"vol_1y": sqrt(var_x * 252), "beta": cov / var_y if var_y else None, "observations": len(dates)}
