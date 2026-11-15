"""Data contracts shared by agents, orchestrator, API and website."""
from typing import Literal, Optional

from pydantic import BaseModel, Field

# Fixed channel taxonomy shared by ALL data-retrieving agents.
Channel = Literal["trade_tariffs", "export_controls", "sanctions", "conflict_exposure",
                  "supply_chain", "regulatory", "fx_capital_controls", "financial_stress"]


# ---------- Common envelope for every data-retrieving agent ----------
class Source(BaseModel):
    title: str
    url: str
    locator: str = Field(description="Where in the source: page, section, passage")
    retrieved_at: str = Field(description="ISO date/time, set by code")


class Entity(BaseModel):
    ticker: str
    country: Optional[str] = Field(None, description="ISO 3166-1 alpha-2 code of the issuer, if known")


class Claim(BaseModel):
    """Atomic finding: one statement, one number, its own sources."""
    id: str = Field(description="'<agent>:<ticker>:<nnn>'. Assigned by code, not by the LLM")
    channel: Channel
    statement: str = Field(description="One factual sentence")
    value: Optional[float] = Field(None, description="Number backing the statement, only if the source gives one")
    unit: Optional[str] = Field(None, description="e.g. revenue_share (0-1), usd, pct, count")
    score: int = Field(ge=0, le=5, description="Severity 0-5")
    confidence: float = Field(ge=0, le=1)
    sources: list[Source] = Field(default_factory=list, description="Attached by code from tool metadata")
    evidence_quote: Optional[str] = Field(None, description="Verbatim quote (max ~300 chars) copied from tool output")
    quote_verified: Optional[bool] = Field(None, description="Set by code after the run, not by the LLM")


class AgentOutput(BaseModel):
    agent: str
    entity: Entity
    as_of: str
    claims: list[Claim]
    summary: str = Field(description="Prose that cites claim ids only, e.g. [filings:ASML:003]")


# ---------- What the LLM actually produces (code completes it into AgentOutput) ----------
class DraftClaim(BaseModel):
    channel: Channel
    statement: str
    value: Optional[float] = None
    unit: Optional[str] = None
    score: int = Field(ge=0, le=5)
    confidence: float = Field(ge=0, le=1)
    evidence_quote: str = Field(description="Verbatim quote copied from tool output")
    locator: str = Field(description="Filing section or passage location the quote comes from")


class DraftOutput(BaseModel):
    claims: list[DraftClaim]
    summary: str = Field(description="Cite claims by position as [1], [2]... (1-based, order of `claims`)")


# ---------- Country / Asset layers (all use the claim envelope) ----------
class Event(BaseModel):
    """Dated, sourced event. Feeds the top-5 watchlist, so a summary is never enough."""
    id: str = Field(description="'ev:<CN or ticker>:<nn>', assigned by code")
    type: str = Field(description="e.g. tariff_deadline, license_renewal, litigation")
    date: str = Field(description="YYYY-MM-DD")
    channel: Channel
    severity: int = Field(ge=0, le=5)
    likelihood: float = Field(ge=0, le=1)
    sources: list[Source] = Field(default_factory=list)
    country: Optional[str] = Field(None, description="Set for country events")
    ticker: Optional[str] = Field(None, description="Set for firm-specific events")


class Indicators(BaseModel):
    gpr: Optional[float] = None
    gpr_z: Optional[float] = None
    epu: Optional[float] = None
    vol_index: Optional[float] = None
    stress: Optional[float] = None


class CountryReport(BaseModel):
    country: str
    as_of: str
    indicators: Indicators
    claims: list[Claim]
    events: list[Event]
    R_c: float = Field(0.0, description="Computed in code (tools.risk_math.country_risk), never by the LLM")


class MarketStats(BaseModel):
    beta_m: Optional[float] = None
    beta_gpr: Optional[float] = None
    vol_1y: Optional[float] = None
    ret_1y: Optional[float] = None


class AssetReport(BaseModel):
    ticker: str
    filing: str = Field(description="e.g. '10-K FY2025'; annual report for non-SEC filers")
    country_weights: dict[str, float] = Field(description="Blended revenue/production weights, sum to 1, incl. 'Other'")
    weights_estimated: bool = Field(description="True if any region was split into countries by proxy")
    market: MarketStats
    claims: list[Claim]
    events: list[Event]