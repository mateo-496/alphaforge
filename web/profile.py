"""Deterministic investor-profile checks for current and simulated portfolios."""
import math

from web import universe as U

RISK_LABELS = {1: "Very low", 2: "Low", 3: "Moderate", 4: "High", 5: "Very high"}
VOL_LIMIT = {1: 0.15, 2: 0.25, 3: 0.35, 4: 0.50, 5: None}


def volatility(ticker: str, as_of: str) -> float | None:
    series = U._series()
    if not series or ticker not in series[0]:
        return None
    dates, closes = series[0][ticker]
    end = U.bisect_right(dates, as_of)
    window = closes[max(0, end - 253):end]
    if len(window) < 60:
        return None
    returns = [math.log(after / before) for before, after in zip(window, window[1:]) if before > 0]
    mean = sum(returns) / len(returns)
    deviation = math.sqrt(sum((value - mean) ** 2 for value in returns) / (len(returns) - 1))
    per_year = 365 if U.universe()[ticker]["asset_class"] == "crypto" else 252
    return deviation * math.sqrt(per_year)


def checks(investor: dict, weights: dict, universe: dict, as_of: str, country_weights: dict | None = None,
           names: dict | None = None, vol_fn=None) -> list[dict]:
    weights = {ticker: weight for ticker, weight in weights.items() if weight > 1e-9}
    names = names or {}
    vol_fn = vol_fn or volatility
    out = []
    max_single = investor.get("max_single_weight", .25)
    for ticker, weight in weights.items():
        if not universe[ticker]["asset_class"].startswith("etf") and weight > max_single + 1e-9:
            out.append({"id": f"single:{ticker}", "ticker": ticker, "text": f"{ticker} is {weight:.0%} of the portfolio, above the {max_single:.0%} single-holding limit."})
    crypto = sum(weight for ticker, weight in weights.items() if universe[ticker]["asset_class"] == "crypto")
    crypto_max = investor.get("crypto_max", 0)
    if crypto > crypto_max + 1e-9:
        out.append({"id": "crypto:limit", "ticker": "crypto", "text": f"Crypto is {crypto:.0%} of the portfolio; the limit is {crypto_max:.0%}."})
    themes = {value.lower() for value in investor.get("excluded_themes", [])}
    fossil = {"fossil fuels", "coal", "oil sands"} & themes
    for ticker in weights:
        sector = universe[ticker].get("sector")
        if sector and sector in investor.get("excluded_sectors", []):
            out.append({"id": f"sector:{ticker}", "ticker": ticker, "text": f"{ticker} is in an excluded sector ({sector})."})
        if ticker in investor.get("excluded_tickers", []):
            out.append({"id": f"ticker:{ticker}", "ticker": ticker, "text": f"{ticker} is on the exclusion list."})
        if fossil and sector == "Energy":
            out.append({"id": f"fossil:{ticker}", "ticker": ticker, "text": f"{ticker} is an energy company; the profile excludes {', '.join(sorted(fossil))}."})
    if "crypto assets" in themes and crypto > 1e-9:
        out.append({"id": "crypto:excluded", "ticker": "crypto", "text": f"Crypto assets are excluded but make up {crypto:.0%} of the portfolio."})
    risk_level = investor.get("risk_level", 3)
    limit = VOL_LIMIT[risk_level]
    if limit:
        for ticker in weights:
            value = vol_fn(ticker, as_of)
            if value and value > limit:
                out.append({"id": f"volatility:{ticker}", "ticker": ticker, "text": f"{ticker} had {value:.0%} annualised volatility over the year to {as_of}, above {limit:.0%} for a {RISK_LABELS[risk_level].lower()} risk profile."})
    if country_weights is not None:
        for country in investor.get("avoid_countries", []):
            exposure = sum(weight * country_weights[ticker].get(country, 0) for ticker, weight in weights.items())
            if exposure >= .005:
                via = [ticker for ticker in weights if country_weights[ticker].get(country, 0) >= .02]
                text = f"{exposure:.1%} of portfolio revenue comes from {names.get(country, country)}, a country the profile wants to limit"
                out.append({"id": f"country:{country}", "ticker": country,
                            "text": text + (f" (through {', '.join(via)})." if via else ".")})
    return out


def assess_swaps(investor: dict, weights: dict, swaps: list[dict], universe: dict, as_of: str,
                 country_weights: dict, names: dict, vol_fn=None) -> dict:
    current = dict(weights)
    initial = checks(investor, current, universe, as_of, country_weights, names, vol_fn)
    previous = {item["id"]: item for item in initial}
    total_moved = 0.0
    protected = set(investor.get("protected_holdings") or [])
    protected_sold = set()
    for swap in swaps:
        sell, buy, move = swap["from"], swap["to"], swap["move"]
        current[sell] -= move
        current[buy] = current.get(buy, 0) + move
        total_moved += move
        if sell in protected and move > 1e-9:
            protected_sold.add(sell)
        after = {item["id"]: item for item in checks(investor, current, universe, as_of, country_weights, names, vol_fn)}
        relevant = lambda item: (item["ticker"] == sell or
                                 (item["ticker"] == "crypto" and universe[sell]["asset_class"] == "crypto"))
        changes = []
        for key, item in previous.items():
            if key not in after:
                changes.append({"status": "resolved", "text": item["text"]})
            elif relevant(item) or after[key]["text"] != item["text"]:
                changes.append({"status": "remaining", "text": after[key]["text"]})
        changes.extend({"status": "new", "text": item["text"]} for key, item in after.items() if key not in previous)
        swap["conflict_changes"] = changes
        max_turnover = investor.get("max_turnover", 1.0)
        notes = [f"Portfolio traded: {total_moved:.1%} of the {max_turnover:.1%} limit."]
        selected = investor.get("replacement_types")
        if selected and universe[buy]["asset_class"] in selected:
            labels = {"etf_equity": "equity fund", "etf_bond": "bond fund", "etf_commodity": "gold fund"}
            notes.append(f"{buy} is a {labels.get(universe[buy]['asset_class'], 'fund')} from your selected replacement types.")
        if protected and not protected_sold:
            notes.append(f"Holdings kept: {', '.join(sorted(protected))}.")
        swap["profile_notes"] = notes
        previous = after
    initial_by_id = {item["id"]: item for item in initial}
    return {"resolved": [item for key, item in initial_by_id.items() if key not in previous],
            "remaining": [item for key, item in previous.items() if key in initial_by_id],
            "new": [item for key, item in previous.items() if key not in initial_by_id]}