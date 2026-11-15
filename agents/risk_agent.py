"""Risk agent: explains the computed portfolio risk in a few sentences.

Numbers come from code (tools/risk_math, web/pipeline). The model only writes prose around them, and code
rejects any sentence containing a number that is not in the supplied facts (no invented figures)."""
import json
import re

from pydantic import BaseModel, Field
from strands import Agent

from agents.base import build_model

SYSTEM_PROMPT = """You are the Risk analyst of AlphaForge. Explain a portfolio's geopolitical risk to the investor
described in the facts, in 3 to 4 short sentences (max 260 characters each).
Say what drives the score, which holdings and countries matter most, and how it fits the investor's horizon,
risk tolerance and stated preferences. Challenge the investor where the portfolio conflicts with the profile.
Use ONLY numbers that appear in the facts, written the same way (e.g. 25%, 43). No advice to buy or sell."""


class Explanation(BaseModel):
    sentences: list[str] = Field(description="3-4 sentences, max 260 characters each")


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


def explain(facts: dict) -> list[str]:
    agent = Agent(model=build_model(max_tokens=1200), system_prompt=SYSTEM_PROMPT, name="risk_agent",
                  callback_handler=None)
    res = agent(json.dumps(facts), structured_output_model=Explanation).structured_output
    return [s.strip() for s in check(res.sentences, facts) if s.strip()][:4]
