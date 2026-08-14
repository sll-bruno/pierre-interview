from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class SearchFilters(BaseModel):
    date_from: date | None = None
    date_to: date | None = None
    min_amount_brl: float | None = Field(default=None, ge=0)
    max_amount_brl: float | None = Field(default=None, ge=0)
    merchant: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_ranges(self) -> "SearchFilters":
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from não pode ser posterior a date_to")
        if (
            self.min_amount_brl is not None
            and self.max_amount_brl is not None
            and self.min_amount_brl > self.max_amount_brl
        ):
            raise ValueError("min_amount_brl não pode ser maior que max_amount_brl")
        return self


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    filters: SearchFilters = Field(default_factory=SearchFilters)


class Transaction(BaseModel):
    transaction_id: str
    date: date
    merchant: str
    description: str
    amount_brl: float


class AppliedPeriod(BaseModel):
    date_from: date
    date_to: date
    source: Literal["request", "query", "all_data"]


class QueryInterpretation(BaseModel):
    semantic_intent: str
    date_from: date | None = None
    date_to: date | None = None
    min_amount_brl: float | None = None
    max_amount_brl: float | None = None
    merchant: str | None = None
    evidence: list[str] = Field(default_factory=list)


class ScoreBreakdown(BaseModel):
    raw_similarity: float
    enriched_similarity: float
    category_match: float
    merchant_match: float
    final_score: float


class SearchResult(Transaction):
    category: str
    category_confidence: float
    score: float
    score_breakdown: ScoreBreakdown
    matched_signals: list[str]
    explanation: str


class SearchResponse(BaseModel):
    query: str
    count: int
    transaction_ids: list[str]
    interpretation: QueryInterpretation
    transactions: list[SearchResult]
    period: AppliedPeriod


class FeedbackRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    transaction_id: str = Field(min_length=1, max_length=100)
    relevant: bool


class FeedbackResponse(BaseModel):
    status: Literal["recorded"] = "recorded"


class EvaluationRunRequest(BaseModel):
    top_k: int = Field(default=10, ge=1, le=100)
