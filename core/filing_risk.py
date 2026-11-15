"""Report contracts for risks disclosed in annual filings."""
from typing import Literal

from pydantic import BaseModel, Field

from core.schemas import AgentOutput


class DraftFilingRisk(BaseModel):
    category: str = Field(min_length=1)
    evidence_quote: str = Field(min_length=1)
    score: int = Field(ge=0, le=5)
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)


class DraftFilingRisks(BaseModel):
    risks: list[DraftFilingRisk]


class QuoteCorrection(BaseModel):
    position: int = Field(ge=0)
    start_segment: int | None = Field(ge=0)
    end_segment: int | None = Field(ge=0)


class QuoteCorrections(BaseModel):
    corrections: list[QuoteCorrection]


class CompanyFilingRiskReport(BaseModel):
    ticker: str
    weight: float
    form: Literal["10-K", "20-F", "40-F"]
    filing_date: str
    filing_url: str
    section: str
    status: Literal["available", "manual_review"]
    reason: str | None = None


class FilingIndexStatus(BaseModel):
    status: Literal["disabled", "started", "sync_required"]
    ingestion_job_id: str | None = None
    ingestion_status: str | None = None
    filings: list[dict[str, str]] = Field(default_factory=list)


class PortfolioFilingRiskReport(BaseModel):
    as_of: str
    companies: list[CompanyFilingRiskReport]
    reports: list[AgentOutput]
    indexing: FilingIndexStatus
