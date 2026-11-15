"""Recommendations fitted to the investor's profile. Deterministic: code chooses every swap, so each one can be
explained line by line. No LLM picks tickers or sizes.

Order of work:
  1. Verdict (tools/risk_math.verdict). If clear: no swap, the report says there is no immediate danger.
  2. Profile fixes: holdings that break a stated limit (single-holding cap, crypto cap, exclusions, volatility).
  3. Risk fixes, only if the score is above the profile's tolerance: move the largest contributor into the
     best-fitting fund, sized to bring the score back to tolerance, at most 3 swaps.
Every swap is re-scored with the full formula on the new weights. A simulation, not advice.
"""
from tools import risk_math

FUNDS = ["XBB.TO", "ZST.TO", "AGG", "BND", "TLT", "XIU.TO", "SPY", "VTI", "ESGV", "ESGD", "VXUS", "GLD"]
ESG_FUNDS = {"ESGV", "ESGD"}
CLASS_LABEL = {"etf_bond": "bond fund", "etf_equity": "equity fund", "etf_commodity": "gold fund"}


def style(p: dict) -> dict:
    """What the profile wants from a replacement, with the reason shown to the user."""
    horizon, risk, obj = p.get("horizon_years", 10), p.get("risk_level", 3), p.get("objective_level", 3)
    if horizon <= 5 or obj <= 2 or risk <= 2:
        return {"prefer": ["etf_bond", "etf_commodity", "etf_equity"],
                "why": f"capital preservation over a {horizon}-year horizon" if horizon <= 5 else "a low-risk, capital-preservation profile"}
    if obj >= 4 or risk >= 4:
        return {"prefer": ["etf_equity"], "why": "the growth objective (equity kept, no bonds)"}
    return {"prefer": ["etf_equity", "etf_bond"], "why": "a balanced profile"}


def candidates(p: dict, weights: dict, uni: dict) -> list[str]:
    """Funds the profile allows."""
    excl_t = set(p.get("excluded_tickers", []))
    themes = " ".join(x.lower() for x in p.get("excluded_themes", []))
    st = style(p)
    out = []
    for c in FUNDS:
        if c not in uni or c in excl_t or uni[c]["asset_class"] not in st["prefer"]:
            continue
        if p.get("esg_importance") == "high" and uni[c]["asset_class"] == "etf_equity" and c not in ESG_FUNDS:
            continue
        if "gold" in themes and c == "GLD":
            continue
        out.append(c)
    return out


def _fit(c: str, p: dict, uni: dict, G: float, cw: dict) -> float | None:
    """Lower is better: the fund's own score, plus 10 points per step down the profile's preference list.
    None if the fund puts >= 5% in a country the profile wants to avoid."""
    if any(cw.get(a, 0) >= 0.05 for a in p.get("avoid_countries", [])):
        return None
    return G + 10 * style(p)["prefer"].index(uni[c]["asset_class"])


def _score(weights: dict, parts: dict) -> float:
    return risk_math.portfolio_score({t: w for t, w in weights.items() if w > 1e-9}, parts)["P"]


def _top_country(parts: dict, names: dict) -> str:
    c, pts = max(((c, v) for c, v in parts["countries"].items() if c != "Other"), key=lambda kv: kv[1], default=(None, 0))
    return names.get(c, c) if c else "unattributed revenue"


def propose(p: dict, weights: dict, parts: dict, cand_parts: dict, cand_cw: dict, checks: list[dict],
            verdict: dict, uni: dict, names: dict) -> list[dict]:
    """parts / cand_parts: risk_math.holding_score output per ticker. Returns swaps in order, each re-scored."""
    if verdict["clear"]:
        return []
    allp = {**parts, **cand_parts}
    w = dict(weights)
    P0 = P = _score(w, allp)
    st = style(p)
    ranked = sorted((c for c in cand_parts if _fit(c, p, uni, cand_parts[c]["G"], cand_cw[c]) is not None),
                    key=lambda c: _fit(c, p, uni, cand_parts[c]["G"], cand_cw[c]))
    if not ranked:
        return []
    out = []

    def swap(sell, frac, why_sell, kind):
        nonlocal P
        buy = ranked[0]
        move = w[sell] * frac
        before = P
        w[sell] -= move
        w[buy] = w.get(buy, 0) + move
        P = _score(w, allp)
        out.append({"from": sell, "to": buy, "fraction": frac, "move": move, "kind": kind,
                    "score_before": before, "score_after": P, "delta": P - before,
                    "why_sell": why_sell,
                    "why_buy": f"{buy} is a {CLASS_LABEL.get(uni[buy]['asset_class'], 'fund')} scoring "
                               f"{cand_parts[buy]['G']:.0f}, chosen for {st['why']}"
                               + (" and ESG screening" if buy in ESG_FUNDS else "") + "."})

    # 2. profile fixes: every stated limit the portfolio breaks
    seen = set()
    for chk in checks:
        t = chk.get("ticker")
        if t == "crypto":
            crypto = {x: v for x, v in w.items() if uni.get(x, {}).get("asset_class") == "crypto" and v > 0}
            excess = sum(crypto.values()) - p.get("crypto_max", 0)
            for x, v in sorted(crypto.items(), key=lambda kv: -kv[1]):
                if excess <= 1e-9 or x in seen:
                    break
                frac = min(1.0, excess / v)
                seen.add(x)
                excess -= v * frac
                swap(x, frac, chk["text"], "profile")
        elif t in w and t not in seen and w[t] > 0:
            seen.add(t)
            cap = p.get("max_single_weight", 1)
            frac = 1 - cap / w[t] if "single-holding limit" in chk["text"] else 0.5 if "volatility" in chk["text"] else 1.0
            swap(t, round(frac, 2), chk["text"], "profile")

    # 3. risk fixes, only above tolerance
    T = verdict["tolerance"]
    for _ in range(3):
        if P <= T:
            break
        best = ranked[0]
        Gb = cand_parts[best]["G"]
        cands = [(t, x * allp[t]["G"]) for t, x in w.items() if x > 1e-9 and t not in cand_parts and allp[t]["G"] > Gb + 5]
        if not cands:
            break
        t, contrib = max(cands, key=lambda kv: kv[1])
        need = (P - T) / (w[t] * (allp[t]["G"] - Gb))       # fraction that would bring P exactly to T
        frac = min(1.0, max(0.25, -(-need // 0.25) * 0.25))  # rounded up to quarters, at least 25%
        swap(t, frac, f"{t} adds {contrib:.1f} points ({contrib / P:.0%} of the score), mostly through "
                      f"{_top_country(allp[t], names)}; the score is above the profile's tolerance of {T}.", "risk")
    for s in out:
        s["score_start"] = P0
    return out
