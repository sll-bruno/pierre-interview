from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Iterable

from openai import OpenAI
from pydantic import BaseModel, Field, field_validator

from app.prompts import TRANSACTION_ENRICHMENT_SYSTEM_PROMPT


class CategoryCandidate(BaseModel):
    category: str = Field(min_length=1, max_length=60)
    confidence: float = Field(ge=0, le=1)
    explanation: str = Field(min_length=1, max_length=500)

    @field_validator("category")
    @classmethod
    def normalize_category(cls, value: str) -> str:
        return " ".join(value.casefold().strip().split())


class LLMEnrichment(BaseModel):
    enriched_context: str = Field(min_length=1, max_length=1000)
    candidates: list[CategoryCandidate] = Field(min_length=1, max_length=3)


class TransactionEnrichment(BaseModel):
    enriched_context: str
    category: str
    confidence: float = Field(ge=0, le=1)
    explanation: str
    candidates: list[CategoryCandidate]


@dataclass(frozen=True)
class TransactionInput:
    transaction_id: str
    date: date
    merchant: str
    description: str
    amount_brl: float


def apply_unknown_threshold(
    result: LLMEnrichment, threshold: float
) -> TransactionEnrichment:
    """Turn low-confidence guesses into an explicit unknown classification."""
    candidates = sorted(result.candidates, key=lambda item: item.confidence, reverse=True)
    best = candidates[0]
    if best.category == "desconhecido" or best.confidence >= threshold:
        return TransactionEnrichment(
            enriched_context=result.enriched_context.strip(),
            category=best.category,
            confidence=best.confidence,
            explanation=best.explanation.strip(),
            candidates=candidates,
        )

    explanation = (
        f"Evidência insuficiente para confirmar '{best.category}' "
        f"(score {best.confidence:.2f}, limiar {threshold:.2f})."
    )
    unknown = CategoryCandidate(
        category="desconhecido",
        confidence=round(1 - best.confidence, 4),
        explanation=explanation,
    )
    return TransactionEnrichment(
        enriched_context=result.enriched_context.strip(),
        category=unknown.category,
        confidence=unknown.confidence,
        explanation=unknown.explanation,
        candidates=[unknown, *candidates][:3],
    )


def embedding_text(transaction: TransactionInput, result: TransactionEnrichment) -> str:
    """Text for the enrichment channel; raw banking fields stay separate."""
    del transaction
    return " | ".join(
        [
            f"categoria: {result.category}",
            f"contexto: {result.enriched_context}",
        ]
    )


class TransactionEnricher:
    def __init__(
        self,
        model: str = "gpt-4.1-mini",
        unknown_threshold: float = 0.62,
        client: OpenAI | None = None,
    ) -> None:
        self.model = model
        self.unknown_threshold = unknown_threshold
        self.client = client or OpenAI()

    def enrich(
        self,
        transaction: TransactionInput,
        history: Iterable[dict[str, object]] = (),
    ) -> TransactionEnrichment:
        payload = {
            "transaction": {
                "transaction_id": transaction.transaction_id,
                "date": transaction.date.isoformat(),
                "merchant": transaction.merchant,
                "description": transaction.description,
                "amount_brl": transaction.amount_brl,
            },
            "similar_past_transactions": list(history),
        }
        response = self.client.responses.parse(
            model=self.model,
            input=[
                {"role": "system", "content": TRANSACTION_ENRICHMENT_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=False),
                },
            ],
            text_format=LLMEnrichment,
        )
        if response.output_parsed is None:
            raise RuntimeError("O LLM não retornou um enriquecimento estruturado")
        return apply_unknown_threshold(response.output_parsed, self.unknown_threshold)
