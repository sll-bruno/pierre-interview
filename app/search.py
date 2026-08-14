from __future__ import annotations

import asyncio
from difflib import SequenceMatcher
import hashlib
import json
import re
import unicodedata
from collections import OrderedDict
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import HTTPException
from openai import AsyncOpenAI

from app.config import Settings
from app.models import (
    AppliedPeriod,
    QueryInterpretation,
    ScoreBreakdown,
    SearchFilters,
    SearchResponse,
    SearchResult,
)
from app.query import QueryInterpreter

REQUIRED_COLUMNS = [
    "transaction_id",
    "date",
    "merchant",
    "description",
    "amount_brl",
    "raw_embedding",
    "enriched_embedding",
    "category",
    "category_confidence",
]
VAGUE_QUERIES = {
    "algo",
    "coisa",
    "coisas",
    "gasto",
    "gastos",
    "transacao",
    "transacoes",
    "transaction",
    "transactions",
}


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold().strip()
    return re.sub(r"\s+", " ", value)


def merchant_key(value: str) -> str:
    """Normalize merchant names for accent-insensitive exact/fuzzy matching."""
    normalized = unicodedata.normalize("NFD", normalize_text(value))
    return "".join(
        character
        for character in normalized
        if unicodedata.category(character) != "Mn"
    )


def semantic_text(merchant: str, description: str) -> str:
    return f"merchant: {normalize_text(merchant)} | description: {normalize_text(description)}"


def record_hash(transaction_id: str, text: str) -> str:
    return hashlib.sha256(f"{transaction_id}\0{text}".encode()).hexdigest()


class QueryEmbeddingCache:
    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self._values: OrderedDict[str, np.ndarray] = OrderedDict()
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> np.ndarray | None:
        async with self._lock:
            value = self._values.get(key)
            if value is not None:
                self._values.move_to_end(key)
            return value

    async def put(self, key: str, value: np.ndarray) -> None:
        async with self._lock:
            self._values[key] = value
            self._values.move_to_end(key)
            while len(self._values) > self.capacity:
                self._values.popitem(last=False)


class TransactionSearch:
    def __init__(self, config: Settings) -> None:
        self.config = config
        self.client: AsyncOpenAI | None = None
        self.interpreter = QueryInterpreter(
            config.query_model, cache_size=config.query_cache_size
        )
        self.cache = QueryEmbeddingCache(config.query_cache_size)
        self.frame = self._load(config.embeddings_parquet)
        self.raw_matrix = self._matrix(self.frame, "raw_embedding")
        self.enriched_matrix = self._matrix(self.frame, "enriched_embedding")

    @staticmethod
    def _load(path: Path) -> pd.DataFrame:
        if not path.exists():
            raise RuntimeError(
                f"Índice não encontrado em {path}. Execute: python scripts/index_transactions.py"
            )
        frame = pd.read_parquet(path)
        missing = set(REQUIRED_COLUMNS) - set(frame.columns)
        if missing:
            raise RuntimeError(f"Índice inválido; colunas ausentes: {sorted(missing)}")
        if frame.empty:
            raise RuntimeError("O índice de transações está vazio")
        frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.date
        return frame.reset_index(drop=True)

    @staticmethod
    def _matrix(frame: pd.DataFrame, column: str) -> np.ndarray:
        matrix = np.asarray(frame[column].tolist(), dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        if np.any(norms == 0):
            raise RuntimeError("O índice contém embedding com norma zero")
        return matrix / norms

    async def _embed_query(self, query: str) -> np.ndarray:
        normalized = normalize_text(query)
        cached = await self.cache.get(normalized)
        if cached is not None:
            return cached
        if self.client is None:
            self.client = AsyncOpenAI(timeout=30.0, max_retries=1)
        response = await self.client.embeddings.create(
            model=self.config.model,
            input=normalized,
            encoding_format="float",
        )
        vector = np.asarray(response.data[0].embedding, dtype=np.float32)
        norm = np.linalg.norm(vector)
        if norm == 0:
            raise RuntimeError("A API retornou um embedding com norma zero")
        vector = vector / norm
        await self.cache.put(normalized, vector)
        return vector

    def _resolve_interpreted_merchant(self, merchant: str | None) -> str | None:
        """Resolve an explicit merchant from the query without trusting weak guesses."""
        if not merchant:
            return None
        target = merchant_key(merchant)
        if not target:
            return None
        known = {
            merchant_key(value): str(value)
            for value in self.frame["merchant"].dropna().unique()
        }
        if target in known:
            return known[target]

        candidate, score = max(
            (
                (name, SequenceMatcher(None, target, name).ratio())
                for name in known
            ),
            key=lambda item: item[1],
        )
        # A typo such as "carrefur" resolves to Carrefour. Longer phrases such
        # as "uber eats" do not collapse to the generic merchant "Uber".
        if (
            len(target) >= 4
            and abs(len(target) - len(candidate)) <= 2
            and score >= 0.86
        ):
            return known[candidate]
        return None

    def _candidate_mask(
        self, filters: SearchFilters, interpretation: QueryInterpretation
    ) -> tuple[np.ndarray, AppliedPeriod]:
        earliest = min(self.frame["date"])
        latest = max(self.frame["date"])
        if filters.date_from or filters.date_to:
            date_from = filters.date_from or earliest
            date_to = filters.date_to or latest
            source = "request"
        elif interpretation.date_from or interpretation.date_to:
            date_from = interpretation.date_from or earliest
            date_to = interpretation.date_to or latest
            source = "query"
        else:
            date_from = earliest
            date_to = latest
            source = "all_data"

        mask = np.asarray(
            (self.frame["date"] >= date_from) & (self.frame["date"] <= date_to)
        )
        minimum = (
            filters.min_amount_brl
            if filters.min_amount_brl is not None
            else interpretation.min_amount_brl
        )
        maximum = (
            filters.max_amount_brl
            if filters.max_amount_brl is not None
            else interpretation.max_amount_brl
        )
        if minimum is not None:
            mask &= np.asarray(self.frame["amount_brl"] >= minimum)
        if maximum is not None:
            mask &= np.asarray(self.frame["amount_brl"] <= maximum)
        if filters.merchant:
            merchant = re.escape(normalize_text(filters.merchant))
            normalized_merchants = self.frame["merchant"].map(normalize_text)
            mask &= np.asarray(normalized_merchants.str.contains(merchant, regex=True))
        else:
            resolved_merchant = self._resolve_interpreted_merchant(
                interpretation.merchant
            )
            if resolved_merchant:
                mask &= np.asarray(
                    self.frame["merchant"].map(normalize_text)
                    == normalize_text(resolved_merchant)
                )
        return mask, AppliedPeriod(
            date_from=date_from, date_to=date_to, source=source  # type: ignore[arg-type]
        )

    @staticmethod
    def _term_match(left: str, right: str) -> float:
        left_terms = set(normalize_text(left).split())
        right_terms = set(normalize_text(right).split())
        if not left_terms or not right_terms:
            return 0.0
        if normalize_text(left) in normalize_text(right) or normalize_text(right) in normalize_text(left):
            return 1.0
        return len(left_terms & right_terms) / max(len(left_terms), len(right_terms))

    def _explanation(
        self,
        row: object,
        interpretation: QueryInterpretation,
        filters: SearchFilters,
        breakdown: ScoreBreakdown,
    ) -> tuple[list[str], str]:
        signals: list[str] = []
        merchant = str(getattr(row, "merchant"))
        category = str(getattr(row, "category"))
        if breakdown.merchant_match:
            signals.append(f"estabelecimento: {merchant}")
        if breakdown.category_match:
            signals.append(f"categoria inferida: {category}")
        if breakdown.raw_similarity >= 0.35:
            signals.append("descrição original semanticamente semelhante")
        if breakdown.enriched_similarity >= 0.35:
            signals.append("contexto enriquecido semanticamente semelhante")
        if filters.date_from or filters.date_to or interpretation.date_from or interpretation.date_to:
            signals.append("período solicitado atendido")
        if (
            filters.min_amount_brl is not None
            or filters.max_amount_brl is not None
            or interpretation.min_amount_brl is not None
            or interpretation.max_amount_brl is not None
        ):
            signals.append("faixa de valor atendida")
        if filters.merchant:
            signals.append(f"filtro de estabelecimento atendido: {filters.merchant}")
        if not signals:
            signals.append("similaridade semântica acima do limiar mínimo")
        return signals, "Apareceu porque " + "; ".join(signals) + "."

    async def search(self, query: str, filters: SearchFilters) -> SearchResponse:
        normalized = normalize_text(query)
        if normalized in VAGUE_QUERIES:
            raise HTTPException(
                status_code=422,
                detail="Consulta muito vaga. Forneça mais informações.",
            )

        data_min = min(self.frame["date"])
        data_max = max(self.frame["date"])
        interpretation = await self.interpreter.interpret(normalized, data_min, data_max)
        mask, period = self._candidate_mask(filters, interpretation)
        candidate_indices = np.flatnonzero(mask)
        if candidate_indices.size == 0:
            return SearchResponse(
                query=query,
                count=0,
                transaction_ids=[],
                interpretation=interpretation,
                transactions=[],
                period=period,
            )

        embedding_query = interpretation.semantic_intent
        if interpretation.merchant:
            embedding_query += f" | estabelecimento: {interpretation.merchant}"
        query_vector = await self._embed_query(embedding_query)
        raw_scores = self.raw_matrix[candidate_indices] @ query_vector
        enriched_scores = self.enriched_matrix[candidate_indices] @ query_vector
        categories = self.frame.iloc[candidate_indices]["category"].astype(str)
        category_scores = np.asarray(
            [self._term_match(interpretation.semantic_intent, value) for value in categories]
        )
        merchants = self.frame.iloc[candidate_indices]["merchant"].astype(str)
        merchant_scores = np.asarray(
            [
                self._term_match(interpretation.merchant or "", value)
                for value in merchants
            ]
        )
        scores = (
            0.45 * raw_scores
            + 0.35 * enriched_scores
            + 0.15 * category_scores
            + 0.05 * merchant_scores
        )
        accepted = scores >= self.config.search_min_score
        # When the query names a category exactly (e.g. "delivery"), semantic
        # similarity alone is too permissive: expensive flights and utilities
        # can leak into the long tail. Keep only that category's candidates.
        # Queries without an exact category signal retain the broader semantic
        # retrieval behavior.
        if (
            not interpretation.merchant
            and category_scores.size
            and category_scores.max() == 1.0
        ):
            accepted &= category_scores > 0
        candidate_indices = candidate_indices[accepted]
        raw_scores = raw_scores[accepted]
        enriched_scores = enriched_scores[accepted]
        category_scores = category_scores[accepted]
        merchant_scores = merchant_scores[accepted]
        scores = scores[accepted]
        order_positions = np.argsort(-scores, kind="stable")
        order = candidate_indices[order_positions]
        rows = self.frame.iloc[order]
        transactions: list[SearchResult] = []
        for position, row in enumerate(rows.itertuples(index=False)):
            score_position = order_positions[position]
            breakdown = ScoreBreakdown(
                raw_similarity=round(float(raw_scores[score_position]), 4),
                enriched_similarity=round(float(enriched_scores[score_position]), 4),
                category_match=round(float(category_scores[score_position]), 4),
                merchant_match=round(float(merchant_scores[score_position]), 4),
                final_score=round(float(scores[score_position]), 4),
            )
            signals, explanation = self._explanation(
                row, interpretation, filters, breakdown
            )
            transactions.append(
                SearchResult(
                    transaction_id=row.transaction_id,
                    date=row.date,
                    merchant=row.merchant,
                    description=row.description,
                    amount_brl=float(row.amount_brl),
                    category=row.category,
                    category_confidence=float(row.category_confidence),
                    score=breakdown.final_score,
                    score_breakdown=breakdown,
                    matched_signals=signals,
                    explanation=explanation,
                )
            )
        ids = [transaction.transaction_id for transaction in transactions]
        return SearchResponse(
            query=query,
            count=len(transactions),
            transaction_ids=ids,
            interpretation=interpretation,
            transactions=transactions,
            period=period,
        )

    def record_feedback(self, query: str, transaction_id: str, relevant: bool) -> None:
        if transaction_id not in set(self.frame["transaction_id"]):
            raise HTTPException(status_code=404, detail="Transação não encontrada")
        feedback_file = self.config.feedback_file
        if Path("/var/task").exists() and not feedback_file.is_absolute():
            feedback_file = Path("/tmp") / feedback_file.name
        feedback_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "query": query,
            "transaction_id": transaction_id,
            "relevant": relevant,
        }
        with feedback_file.open("a", encoding="utf-8") as output:
            output.write(json.dumps(payload, ensure_ascii=False) + "\n")
