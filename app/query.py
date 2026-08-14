from __future__ import annotations

import asyncio
import json
import re
import unicodedata
from collections import OrderedDict
from datetime import date

from openai import AsyncOpenAI
from pydantic import BaseModel, Field, model_validator

from app.models import QueryInterpretation


MONTHS = {
    "janeiro": 1,
    "fevereiro": 2,
    "marco": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}

QUERY_SYSTEM_PROMPT = """
Extraia a intenção de uma busca de transações financeiras brasileiras.
Retorne somente informações explicitamente sustentadas pela consulta.
- semantic_intent: o conceito buscado sem período, valor ou estabelecimento.
- Datas devem ser ISO. Resolva mês sem ano usando o ano compatível com os
  limites da base fornecidos. Não invente período se ele não foi mencionado.
- merchant só pode ser preenchido quando a consulta nomear um estabelecimento.
- evidence deve conter trechos curtos e literais da consulta que sustentam a
  interpretação.
""".strip()


class ParsedQuery(BaseModel):
    semantic_intent: str = Field(min_length=1, max_length=200)
    date_from: date | None = None
    date_to: date | None = None
    min_amount_brl: float | None = Field(default=None, ge=0)
    max_amount_brl: float | None = Field(default=None, ge=0)
    merchant: str | None = Field(default=None, max_length=200)
    evidence: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def validate_ranges(self) -> "ParsedQuery":
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("intervalo de datas inválido")
        if (
            self.min_amount_brl is not None
            and self.max_amount_brl is not None
            and self.min_amount_brl > self.max_amount_brl
        ):
            raise ValueError("intervalo de valores inválido")
        return self


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFD", value.casefold())
    return "".join(char for char in value if unicodedata.category(char) != "Mn")


def _number(value: str) -> float:
    if "," in value:
        return float(value.replace(".", "").replace(",", "."))
    return float(value)


def fallback_interpretation(
    query: str, data_min: date, data_max: date
) -> QueryInterpretation:
    """Deterministic fallback for API failures and common numeric filters."""
    del data_min
    normalized = _normalize(query)
    evidence: list[str] = []
    amount_pattern = r"(?: de)?\s*(?:r\$)?\s*([\d.,]+)(?:\s*reais?)?"
    minimum = re.search(r"(?:acima|mais|maior)" + amount_pattern, normalized)
    maximum = re.search(r"(?:abaixo|menos|menor)" + amount_pattern, normalized)
    min_amount = _number(minimum.group(1)) if minimum else None
    max_amount = _number(maximum.group(1)) if maximum else None
    if minimum:
        evidence.append(minimum.group(0))
    if maximum:
        evidence.append(maximum.group(0))

    date_from = date_to = None
    for name, month in MONTHS.items():
        if name in normalized:
            year_match = re.search(r"\b(20\d{2})\b", normalized)
            year = int(year_match.group(1)) if year_match else data_max.year
            date_from = date(year, month, 1)
            next_month = date(year + int(month == 12), 1 if month == 12 else month + 1, 1)
            date_to = date.fromordinal(next_month.toordinal() - 1)
            evidence.append(name)
            break

    intent = re.sub(
        r"(?:acima|mais|maior|abaixo|menos|menor)(?: de)?\s*(?:r\$)?\s*[\d.,]+(?:\s*reais?)?",
        " ",
        query,
        flags=re.IGNORECASE,
    )
    month_pattern = r"\b(?:em|de)?\s*(?:" + "|".join(MONTHS) + r")(?:\s+de)?\s*(?:20\d{2})?\b"
    intent = re.sub(month_pattern, " ", intent, flags=re.IGNORECASE)
    intent = " ".join(intent.split()).strip(" ,") or query.strip()
    return QueryInterpretation(
        semantic_intent=intent,
        date_from=date_from,
        date_to=date_to,
        min_amount_brl=min_amount,
        max_amount_brl=max_amount,
        evidence=evidence,
    )


class _InterpretationCache:
    """Async LRU cache for parsed queries, mirroring QueryEmbeddingCache in
    app/search.py. Repeated queries (demo clicks, evaluation/load runs) skip
    the interpretation call entirely instead of paying for it every time."""

    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self._values: OrderedDict[str, QueryInterpretation] = OrderedDict()
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> QueryInterpretation | None:
        async with self._lock:
            value = self._values.get(key)
            if value is not None:
                self._values.move_to_end(key)
            return value

    async def put(self, key: str, value: QueryInterpretation) -> None:
        async with self._lock:
            self._values[key] = value
            self._values.move_to_end(key)
            while len(self._values) > self.capacity:
                self._values.popitem(last=False)


class QueryInterpreter:
    def __init__(
        self,
        model: str,
        client: AsyncOpenAI | None = None,
        cache_size: int = 256,
    ) -> None:
        self.model = model
        self.client = client
        self.cache = _InterpretationCache(cache_size)

    async def interpret(
        self, query: str, data_min: date, data_max: date
    ) -> QueryInterpretation:
        cache_key = f"{query}\0{data_min.isoformat()}\0{data_max.isoformat()}"
        cached = await self.cache.get(cache_key)
        if cached is not None:
            return cached

        fallback = fallback_interpretation(query, data_min, data_max)
        try:
            if self.client is None:
                self.client = AsyncOpenAI(timeout=12.0, max_retries=1)
            response = await self.client.responses.parse(
                model=self.model,
                # Deterministic sampling: the same query should not drift
                # across requests into a longer or shorter paraphrase, which
                # would otherwise move the hybrid score around SEARCH_MIN_SCORE.
                temperature=0,
                input=[
                    {"role": "system", "content": QUERY_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "query": query,
                                "data_min": data_min.isoformat(),
                                "data_max": data_max.isoformat(),
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
                text_format=ParsedQuery,
            )
            parsed = response.output_parsed
            if parsed is None:
                return fallback
            # Numeric and month expressions are easy to parse deterministically.
            # Prefer that cleaned intent so they cannot pollute the semantic vector.
            result = QueryInterpretation(
                semantic_intent=(
                    fallback.semantic_intent
                    if fallback.evidence
                    else parsed.semantic_intent
                ),
                date_from=fallback.date_from or parsed.date_from,
                date_to=fallback.date_to or parsed.date_to,
                min_amount_brl=(
                    fallback.min_amount_brl
                    if fallback.min_amount_brl is not None
                    else parsed.min_amount_brl
                ),
                max_amount_brl=(
                    fallback.max_amount_brl
                    if fallback.max_amount_brl is not None
                    else parsed.max_amount_brl
                ),
                merchant=parsed.merchant,
                evidence=list(dict.fromkeys([*fallback.evidence, *parsed.evidence])),
            )
        except Exception:
            return fallback

        # Only successful, model-backed interpretations are cached. A failure
        # falls back to the deterministic parser but should not lock later
        # retries of the same query into that degraded result.
        await self.cache.put(cache_key, result)
        return result
