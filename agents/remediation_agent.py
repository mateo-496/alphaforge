"""Remediation agent: proposes up to 3 hypothetical swaps that lower geopolitical risk within the profile.

The model only chooses (sell, buy, fraction) from the supplied candidates and explains why.
Code validates every proposal (tickers, exclusions, crypto cap, single-holding limit) and computes the
resulting score and the past-year returns. Proposals that fail validation are dropped. Simulation, not advice."""
import json

from pydantic import BaseModel, Field
from strands import Agent

from agents.base import build_model

SYSTEM_PROMPT = """You are the Remediation analyst of AlphaForge. Propose up to 3 hypothetical swaps that would lower
the portfolio's geopolitical risk while respecting the investor's profile: horizon, risk level, objective,
exclusions, interests, crypto cap and single-holding limit.
Each swap sells a fraction (0.1-1.0) of ONE current holding and buys ONE ticker from the candidate list.
Prefer swaps that cut the largest risk contributions and keep the investor's stated interests where possible.
Rationale: max 200 characters, using only the supplied facts. This is a simulation, never investment advice."""


class Swap(BaseModel):
    sell: str
    buy: str
    fraction: float = Field(ge=0.1, le=1.0, description="Share of the current holding moved")
    rationale: str = Field(description="Max 200 characters")


class Swaps(BaseModel):
    swaps: list[Swap] = Field(description="At most 3")


def propose(facts: dict) -> list[Swap]:
    agent = Agent(model=build_model(max_tokens=1500), system_prompt=SYSTEM_PROMPT, name="remediation_agent",
                  callback_handler=None)
    return agent(json.dumps(facts), structured_output_model=Swaps).structured_output.swaps[:3]
