"""Inputs and intermediate results for the market-stress tools."""
from datetime import date
from math import isclose
from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.schemas import AgentOutput, Source


class Observation(BaseModel):
    date: date
    value: float = Field(allow_inf_nan=False)


class MarketSeries(BaseModel):
    name: str
    unit: str
    observations: list[Observation] = Field(min_length=2)
    source: Source

    @model_validator(mode="after")
    def ordered_observations(self):
        dates = [item.date for item in self.observations]
        if dates != sorted(set(dates)):
            raise ValueError("Observations must have unique dates in ascending order")
        if not all((self.source.title, self.source.url, self.source.locator, self.source.retrieved_at)):
            raise ValueError("Series source metadata must not be empty")
        return self


class CountryShare(BaseModel):
    country: str = Field(pattern=r"^[A-Z]{2}$")
    revenue_share: float = Field(ge=0, le=1, allow_inf_nan=False)
    source: Source


class Holding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str = Field(pattern=r"^[A-Z0-9][A-Z0-9.\-]*$")
    weight: float = Field(gt=0, le=1, allow_inf_nan=False)


class MarketHolding(Holding):
    exposures: list[CountryShare] = Field(default_factory=list)
    prices: MarketSeries

    @model_validator(mode="after")
    def validate_exposures_and_prices(self):
        countries = [item.country for item in self.exposures]
        if len(set(countries)) != len(countries):
            raise ValueError(f"Duplicate country for {self.ticker}")
        if sum(item.revenue_share for item in self.exposures) > 1 + 1e-9:
            raise ValueError(f"Revenue shares exceed 1 for {self.ticker}")
        if any(item.value <= 0 for item in self.prices.observations):
            raise ValueError(f"Prices must be positive for {self.ticker}")
        return self


class MarketStressRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    holdings: list[Holding] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_portfolio(self):
        tickers = [h.ticker for h in self.holdings]
        if len(tickers) != len(set(tickers)):
            raise ValueError("Duplicate portfolio ticker")
        if "GLOBAL" in tickers or any(ticker.startswith("COUNTRY-") for ticker in tickers):
            raise ValueError("GLOBAL and COUNTRY- prefixes are reserved for market reports")
        if not isclose(sum(h.weight for h in self.holdings), 1.0, abs_tol=1e-9):
            raise ValueError("Portfolio weights must sum to 1")
        return self


class EnrichedPortfolio(MarketStressRequest):
    as_of: date
    holdings: list[MarketHolding] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_dates(self):
        if any(o.date > self.as_of for h in self.holdings for o in h.prices.observations):
            raise ValueError("Price observations cannot be after as_of")
        return self


class Evaluation(BaseModel):
    id: str
    score: int = Field(ge=0, le=5)
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)


class Evaluations(BaseModel):
    evaluations: list[Evaluation]


class MarketStressResult(BaseModel):
    reports: list[AgentOutput]
    breakdown: dict
