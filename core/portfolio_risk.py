"""Report contract for the final portfolio risk."""
from typing import Optional

from pydantic import BaseModel, Field


class TickerRisk(BaseModel):
    ticker: str
    weight: float
    score: float = Field(ge=0, le=1, description="G_i on [0, 1]")
    contributions: dict[str, float] = Field(description="exposure / filing / market share of the score; sums to it")
    country_contributions: dict[str, float] = Field(description="sum_c w_ic * R_c terms of the exposure component")
    unknown_revenue_share: float
    missing_inputs: list[str]


class CountryRiskSummary(BaseModel):
    country: str
    score: float
    missing_inputs: list[str]


class PortfolioRiskReport(BaseModel):
    as_of: str
    score: float = Field(ge=0, le=1, description="P = sum_i w_i G_i on [0, 1]")
    asset_weights: dict[str, float]
    tickers: list[TickerRisk]
    contributions: dict[str, float] = Field(description="w_i * G_i per ticker; sums to score")
    countries: list[CountryRiskSummary]
    stressed_score: Optional[float] = None
    scenario_shock: Optional[float] = None
    ranking_stability: float = Field(description="Share of +/-20% weight perturbations keeping the ticker ranking")
    notes: list[str] = Field(default_factory=list)
