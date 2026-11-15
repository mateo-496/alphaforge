"""Risk agent: explains the computed portfolio risk in a few sentences.

Numbers come from code (tools/risk_math, web/pipeline). The model only writes prose around them, and code
rejects any sentence containing a number that is not in the supplied facts (no invented figures)."""
import json
import re

from pydantic import BaseModel, Field

from core import llm

SYSTEM_PROMPT = """You are the Risk analyst of AlphaForge. Explain a portfolio's geopolitical risk to the investor
described in the facts, in four labelled points. Each point is ONE plain sentence of at most 140 characters:
- countries: which countries drive the score and why (revenue share, GPR percentile)
- holdings: which holdings matter most
- profile: how it fits the investor's horizon, risk tolerance and preferences; challenge any conflict
- watch: the one scenario to keep an eye on, and how much revenue it touches
The score itself is already shown: do not restate it. Use ONLY numbers that appear in the facts, written the same
way (e.g. 25%, 43); write shares as percentages. No advice to buy or sell."""

SECTIONS = {"countries": "Where it comes from", "holdings": "Holdings that matter", "profile": "Fit with the profile",
            "watch": "To watch"}


class Explanation(BaseModel):
    countries: str = Field(description="Max 140 characters")
    holdings: str = Field(description="Max 140 characters")
    profile: str = Field(description="Max 140 characters")
    watch: str = Field(description="Max 140 characters")


NUM = re.compile(r"(?<![\w.])[-+]?\d+(?:\.\d+)?%?")


def _allowed(facts) -> set[str]:
    out = set()

    def walk(x):
        if isinstance(x, bool):
            return
        if isinstance(x, (int, float)):
            for v in (x, x * 100):
                for f in (f"{v:.0f}", f"{v:.1f}", f"{v:g}"):
                    out.update({f, f + "%", f.lstrip("-"), f.lstrip("-") + "%"})
        elif isinstance(x, str):
            out.update(NUM.findall(x))
            out.update(n.rstrip("%") for n in NUM.findall(x))
        elif isinstance(x, dict):
            [walk(v) for v in x.values()]
        elif isinstance(x, list):
            [walk(v) for v in x]
    walk(facts)
    return out


def check(sentences: list[str], facts: dict) -> list[str]:
    """Keep sentences whose numbers all appear in the facts."""
    ok = _allowed(facts)
    return [s for s in sentences if all(n.lstrip("+") in ok or n.lstrip("+").rstrip("%") in ok for n in NUM.findall(s))]


def explain(facts: dict) -> list[dict]:
    """[{title, text}] in SECTIONS order; a point with a number not in the facts is dropped."""
    res = llm.ask("risk", SYSTEM_PROMPT, json.dumps(facts), Explanation, max_tokens=800)
    out = []
    for k, title in SECTIONS.items():
        text = (getattr(res, k) or "").strip()
        if text and check([text], facts):
            out.append({"title": title, "text": text})
    return out
