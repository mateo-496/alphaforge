"""Data contracts shared by agents, orchestrator, API and website."""
from typing import Literal, Optional

from pydantic import BaseModel, Field, computed_field

# Fixed channel taxonomy shared by ALL data-retrieving agents.
Channel = Literal["trade_tariffs", "export_controls", "sanctions", "conflict_exposure",
                  "supply_chain", "regulatory", "fx_capital_controls", "financial_stress",
                  "filing_risk"]


# ---------- Common envelope for every data-retrieving agent ----------
class Source(BaseModel):
    title: str
    url: str
    locator: str = Field(description="Where in the source: page, section, passage")
    retrieved_at: str = Field(description="ISO date/time, set by code")


class Entity(BaseModel):
    ticker: Optional[str] = Field(None, description="Stock ticker of the company; null if unknown or not a company")
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


# ---------- Request inputs (web form -> orchestrator) ----------


class Holding(BaseModel):
    ticker: str = Field(description="Ticker from the 31-asset starter universe, e.g. 'NVDA', 'RY.TO'")
    weight: float = Field(ge=0, le=1, description="Portfolio weight, holdings sum to 1")


class Portfolio(BaseModel):
    holdings: list[Holding]
    base_currency: Literal["CAD", "USD"] = "CAD"


RISK_LEVELS = {1: "very_low", 2: "low", 3: "moderate", 4: "high", 5: "very_high"}
OBJECTIVE_LEVELS = {1: "preserve", 2: "income", 3: "balanced", 4: "growth", 5: "max_growth"}


class InvestorProfile(BaseModel):
    persona: Optional[str] = Field(None, description="'amira' | 'mateo' | 'robert' | sample id | None for custom")
    age: Optional[int] = Field(None, ge=18, le=100)
    horizon_years: int = Field(10, ge=1, le=40)
    risk_level: int = Field(3, ge=1, le=5, description="1 very low ... 5 very high")
    objective_level: int = Field(3, ge=1, le=5, description="1 preserve capital ... 5 maximum growth")
    experience: Literal["beginner", "intermediate", "advanced"] = "intermediate"
    esg_importance: Literal["none", "some", "high"] = "none"
    avoid_controversies: bool = False
    crypto_max: float = Field(0.0, ge=0, le=1, description="Max total weight in crypto assets")
    max_single_weight: float = Field(0.25, gt=0, le=1, description="Max weight of any single holding")
    excluded_sectors: list[str] = Field(default_factory=list, description="GICS sectors")
    excluded_themes: list[str] = Field(default_factory=list, description="e.g. 'Fossil fuels', 'Weapons', free text")
    excluded_tickers: list[str] = Field(default_factory=list)
    avoid_countries: list[str] = Field(default_factory=list, description="ISO 3166-1 alpha-3 codes")
    interests: list[str] = Field(default_factory=list, description="Labels or free text")
    notes: str = ""

    @computed_field
    @property
    def risk_tolerance(self) -> str:
        return RISK_LEVELS[self.risk_level]

    @computed_field
    @property
    def objective(self) -> str:
        return OBJECTIVE_LEVELS[self.objective_level]


class AnalysisRequest(BaseModel):
    portfolio: Portfolio
    profile: InvestorProfile
    as_of: str = Field(description="YYYY-MM-DD; agents only use data published on or before this date")
    scenario_country: Optional[str] = Field(None, description="ISO alpha-3: also show the 5 most dangerous scenarios for it (set from the report page)")


# ---------- Geopolitical scenarios (scenario agent) ----------
class ScenarioEvidence(BaseModel):
    source_id: str = Field(description="Id of the source block the quote comes from, e.g. 'eurasia_top_risks'")
    quote: str = Field(description="Verbatim sentence or phrase (20-250 chars) copied from that source's text")
    url: str = Field("", description="Set by code")
    quote_verified: Optional[bool] = Field(None, description="Set by code, not by the LLM")
    retrieved_at: Optional[str] = Field(None, description="Set by code")


class DraftScenario(BaseModel):
    """What the LLM produces for one scenario."""
    id: str = Field(description="Stable kebab-case slug. REUSE the id of a previous scenario when it is the same risk")
    name: str = Field(description="Short title, max ~6 words")
    summary: str = Field(description="At most 350 characters: what happens and why it matters for markets")
    countries: dict[str, float] = Field(description="ISO 3166-1 alpha-3 -> intensity 0-1 (1 = epicentre)")
    channels: list[Channel] = Field(description="Transmission channels from the fixed taxonomy")
    sector_shocks: dict[str, float] = Field(default_factory=dict,
                                            description="GICS sector -> expected direction/size -1..1")
    likelihood: float = Field(ge=0, le=1, description="Probability the scenario materialises within 12 months")
    impact: int = Field(ge=1, le=5, description="Severity for global markets if it happens")
    signposts: list[str] = Field(description="2 short observable early-warning signs")
    evidence: list[ScenarioEvidence] = Field(description="1-3 verbatim quotes, each from a DIFFERENT source when several support the scenario")


class DraftScenarioSet(BaseModel):
    scenarios: list[DraftScenario]
    notes: str = Field("", description="One or two sentences on judgement calls")


class Scenario(DraftScenario):
    status: Literal["new", "continuing", "fading"] = "new"
    first_seen: str
    last_updated: str
    weeks_seen: int = 1
    weeks_missing: int = 0
    history: list[dict] = Field(default_factory=list, description="[{week, likelihood, impact}] after each merge")


class ScenarioSet(BaseModel):
    scope: str = Field(description="'global' or 'country-<ISO3>'")
    week: str = Field(description="ISO week of generation, e.g. '2026-W46'")
    computed_at: str
    alpha: float = Field(description="EMA weight given to the newest run")
    query_keys: list[str] = Field(default_factory=list, description="Storage keys of the raw queries merged in")
    mock: bool = False
    inputs: list[dict] = Field(default_factory=list, description="Sources read for this set: id, name, url, retrieved_at, ok")
    scenarios: list[Scenario]
