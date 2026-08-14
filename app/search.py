from __future__ import annotations

import asyncio
import hashlib
import json
import re
import unicodedata
from collections import OrderedDict
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import HTTPException
from openai import AsyncOpenAI

from app.config import Settings
from app.models import AppliedPeriod, QueryInterpretation, ScoreBreakdown, SearchFilters, SearchResponse, SearchResult
from app.query import fallback_interpretation

REQUIRED_COLUMNS = ["transaction_id", "date", "merchant", "description", "amount_brl", "embedding"]
VAGUE_QUERIES = {"algo", "coisa", "coisas", "gasto", "gastos", "transacao", "transacoes", "transação", "transações", "transaction", "transactions"}


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold().strip()
    return re.sub(r"\s+", " ", value)


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
        self.cache = QueryEmbeddingCache(config.query_cache_size)
        self.frame = self._load(config.embeddings_parquet)
        self.matrix = self._matrix(self.frame)

    @staticmethod
    def _load(path: Path) -> pd.DataFrame:
        if not path.exists():
            raise RuntimeError(f"Índice não encontrado em {path}. Execute: python scripts/index_transactions.py")
        frame = pd.read_parquet(path)
        missing = set(REQUIRED_COLUMNS) - set(frame.columns)
        if missing:
            raise RuntimeError(f"Índice inválido; colunas ausentes: {sorted(missing)}")
        if frame.empty:
            raise RuntimeError("O índice de transações está vazio")
        frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.date
        return frame.reset_index(drop=True)

    @staticmethod
    def _matrix(frame: pd.DataFrame) -> np.ndarray:
        matrix = np.asarray(frame["embedding"].tolist(), dtype=np.float32)
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
        response = await self.client.embeddings.create(model=self.config.model, input=normalized, encoding_format="float")
        vector = np.asarray(response.data[0].embedding, dtype=np.float32)
        norm = np.linalg.norm(vector)
        if norm == 0:
            raise RuntimeError("A API retornou um embedding com norma zero")
        vector = vector / norm
        await self.cache.put(normalized, vector)
        return vector

    def _candidate_mask(self, filters: SearchFilters, interpretation: QueryInterpretation) -> tuple[np.ndarray, AppliedPeriod]:
        earliest, latest = min(self.frame["date"]), max(self.frame["date"])
        if filters.date_from or filters.date_to:
            date_from, date_to, source = filters.date_from or earliest, filters.date_to or latest, "request"
        elif interpretation.date_from or interpretation.date_to:
            date_from, date_to, source = interpretation.date_from or earliest, interpretation.date_to or latest, "query"
        else:
            date_to, date_from, source = latest, latest - timedelta(days=14), "latest_15_days"

        mask = np.asarray((self.frame["date"] >= date_from) & (self.frame["date"] <= date_to))
        minimum = filters.min_amount_brl if filters.min_amount_brl is not None else interpretation.min_amount_brl
        maximum = filters.max_amount_brl if filters.max_amount_brl is not None else interpretation.max_amount_brl
        if minimum is not None:
            mask &= np.asarray(self.frame["amount_brl"] >= minimum)
        if maximum is not None:
            mask &= np.asarray(self.frame["amount_brl"] <= maximum)
        merchant_filter = filters.merchant or interpretation.merchant
        if merchant_filter:
            merchant = re.escape(normalize_text(merchant_filter))
            mask &= np.asarray(self.frame["merchant"].map(normalize_text).str.contains(merchant, regex=True))
        return mask, AppliedPeriod(date_from=date_from, date_to=date_to, source=source)

    @staticmethod
    def _explanation(row: object, interpretation: QueryInterpretation, filters: SearchFilters) -> tuple[list[str], str]:
        signals = ["descrição original semanticamente semelhante"]
        if interpretation.merchant or filters.merchant:
            signals.append(f"estabelecimento: {getattr(row, 'merchant')}")
        if interpretation.date_from or interpretation.date_to or filters.date_from or filters.date_to:
            signals.append("período solicitado atendido")
        if interpretation.min_amount_brl is not None or interpretation.max_amount_brl is not None or filters.min_amount_brl is not None or filters.max_amount_brl is not None:
            signals.append("faixa de valor atendida")
        return signals, "Apareceu porque " + "; ".join(signals) + "."

    async def search(self, query: str, filters: SearchFilters) -> SearchResponse:
        normalized = normalize_text(query)
        if normalized in VAGUE_QUERIES:
            raise HTTPException(status_code=422, detail="Consulta muito vaga. Forneça mais informações.")
        interpretation = fallback_interpretation(normalized, min(self.frame["date"]), max(self.frame["date"]))
        mask, period = self._candidate_mask(filters, interpretation)
        candidate_indices = np.flatnonzero(mask)
        if candidate_indices.size == 0:
            return SearchResponse(query=query, count=0, transaction_ids=[], interpretation=interpretation, transactions=[], period=period)

        scores = self.matrix[candidate_indices] @ await self._embed_query(interpretation.semantic_intent)
        positions = np.argsort(-scores, kind="stable")
        rows = self.frame.iloc[candidate_indices[positions]]
        transactions: list[SearchResult] = []
        for position, row in enumerate(rows.itertuples(index=False)):
            score = round(float(scores[positions[position]]), 4)
            signals, explanation = self._explanation(row, interpretation, filters)
            transactions.append(SearchResult(
                transaction_id=row.transaction_id, date=row.date, merchant=row.merchant,
                description=row.description, amount_brl=float(row.amount_brl), score=score,
                score_breakdown=ScoreBreakdown(raw_similarity=score, final_score=score),
                matched_signals=signals, explanation=explanation,
            ))
        return SearchResponse(
            query=query, count=len(transactions), transaction_ids=[item.transaction_id for item in transactions],
            interpretation=interpretation, transactions=transactions, period=period,
        )

    def record_feedback(self, query: str, transaction_id: str, relevant: bool) -> None:
        if transaction_id not in set(self.frame["transaction_id"]):
            raise HTTPException(status_code=404, detail="Transação não encontrada")
        feedback_file = self.config.feedback_file
        if Path("/var/task").exists() and not feedback_file.is_absolute():
            feedback_file = Path("/tmp") / feedback_file.name
        feedback_file.parent.mkdir(parents=True, exist_ok=True)
        with feedback_file.open("a", encoding="utf-8") as output:
            output.write(json.dumps({"query": query, "transaction_id": transaction_id, "relevant": relevant}, ensure_ascii=False) + "\n")
