"""Single source of truth for data shapes. Agent output N is agent input N+1; the web renders these JSONs."""
from pydantic import BaseModel, Field


class Holding(BaseModel):
    ticker: str
    weight: float = Field(ge=0, le=1)


class Portfolio(BaseModel):
    holdings: list[Holding]


class InvestorProfile(BaseModel):
    risk_tolerance: str = "moderate"  # low | moderate | high
    horizon_years: int = 5
    constraints: list[str] = []


class Scenario(BaseModel):
    name: str  # e.g. "Taiwan Strait blockade"
    description: str
    countries: list[str]  # ISO3 codes affected


class CountryExposure(BaseModel):
    country: str  # ISO3
    exposure_type: str  # revenue | supply_chain | operations
    revenue_share: float | None = None
    evidence_quote: str


class TickerExposure(BaseModel):
    ticker: str
    exposures: list[CountryExposure]


class ExposureReport(BaseModel):
    tickers: list[TickerExposure]


class CountryRisk(BaseModel):
    country: str
    score: float = Field(ge=0, le=100)
    drivers: list[str]


class GeopoliticalReport(BaseModel):
    scenario: str
    countries: list[CountryRisk]


class PortfolioRisk(BaseModel):
    score: float = Field(ge=0, le=100)  # computed by tools/risk_math.py, not the LLM
    top_drivers: list[str]
    by_ticker: dict[str, float]
    explanation: str


class Trade(BaseModel):
    ticker: str
    action: str  # buy | sell | hold
    delta_weight: float
    rationale: str


class RemediationPlan(BaseModel):
    trades: list[Trade]
    expected_risk_after: float
    summary: str


class Step(BaseModel):
    agent: str
    input: dict
    output: dict
    tools_called: list[str] = []
    ms: int


class ChainResult(BaseModel):
    steps: list[Step]
    final: RemediationPlan
