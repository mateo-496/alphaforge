"""Remediation agent: up to 3 alternative swaps, as a second opinion next to the code's recommendations.

The model only picks (sell, buy, fraction) among the current holdings and the profile-approved funds, and explains why.
Code then validates each swap (known tickers, fraction 0.1-1, no duplicate of a code recommendation), re-scores the
portfolio with the full formula and keeps it only if the score goes down. Rationales with numbers not in the facts
are replaced by a code-written line. A simulation, not advice."""
import json

from pydantic import BaseModel, Field

from agents.risk_agent import check
from core import llm
from tools import risk_math

AGENT = "remediation"
SYSTEM_PROMPT = """You are the Remediation analyst of AlphaForge. Propose up to 3 hypothetical swaps that lower the
portfolio's geopolitical risk score while respecting the investor's profile (horizon, risk level, objective,
exclusions, interests). Each swap sells a fraction (0.1-1.0) of ONE current holding and buys ONE ticker from the
candidate funds. Prefer cutting the largest contributions while keeping the investor's interests where possible.
Do not repeat the swaps already recommended. Rationale: max 200 characters, using only the supplied facts."""


class Swap(BaseModel):
    sell: str
    buy: str
    fraction: float = Field(ge=0.1, le=1.0, description="Share of the current holding moved")
    rationale: str = Field(description="Max 200 characters")


class Swaps(BaseModel):
    swaps: list[Swap] = Field(description="At most 3")


def facts(profile: dict, weights: dict, parts: dict, cand_parts: dict, score: float, tolerance: int,
          code_swaps: list[dict], uni: dict) -> dict:
    return {"score": round(score, 1), "tolerance": tolerance,
            "profile": {k: profile.get(k) for k in ("horizon_years", "risk_level", "objective_level", "esg_importance",
                                                     "excluded_themes", "interests", "notes")},
            "holdings": [{"ticker": t, "name": uni[t]["name"], "weight": round(w, 3), "holding_risk": round(parts[t]["G"], 1)}
                         for t, w in sorted(weights.items(), key=lambda kv: -kv[1] * parts[kv[0]]["G"])],
            "candidates": [{"ticker": c, "name": uni[c]["name"], "class": uni[c]["asset_class"],
                            "holding_risk": round(p["G"], 1)} for c, p in cand_parts.items()],
            "already_recommended": [f"{s['from']} -> {s['to']}" for s in code_swaps]}


def propose(f: dict, weights: dict, parts: dict, cand_parts: dict, code_swaps: list[dict], score_fn=None) -> list[dict]:
    """Validated, re-scored swaps, each applied alone to the current portfolio. score_fn(weights) -> portfolio score."""
    res = llm.ask(AGENT, SYSTEM_PROMPT, json.dumps(f), Swaps, max_tokens=1500)
    allp = {**parts, **cand_parts}
    score_fn = score_fn or (lambda w: risk_math.portfolio_score({t: x for t, x in w.items() if x > 1e-9}, allp)["P"])
    before = score_fn(weights)
    done = {(s["from"], s["to"]) for s in code_swaps}
    out = []
    for s in res.swaps[:3]:
        if s.sell not in weights or s.buy not in cand_parts or s.sell == s.buy or (s.sell, s.buy) in done:
            continue
        done.add((s.sell, s.buy))
        move = weights[s.sell] * s.fraction
        w = {**weights, s.sell: weights[s.sell] - move, s.buy: weights.get(s.buy, 0) + move}
        after = score_fn(w)
        if after >= before:
            continue
        why = s.rationale.strip()[:220]
        if not why or not check([why], f):
            why = f"Moves {s.fraction:.0%} of {s.sell} into {s.buy}, a fund scoring {cand_parts[s.buy]['G']:.0f}."
        out.append({"from": s.sell, "to": s.buy, "fraction": s.fraction, "move": move, "score_before": before,
                    "score_after": after, "delta": after - before, "rationale": why})
    return out
