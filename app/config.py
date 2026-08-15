from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _path(name: str, default: str) -> Path:
    return Path(os.getenv(name, default)).expanduser()


def _feedback_path() -> Path:
    # Vercel Functions only provide a writable filesystem under /tmp.
    serverless = (
        bool(os.getenv("VERCEL"))
        or bool(os.getenv("AWS_LAMBDA_FUNCTION_NAME"))
        or Path("/var/task").exists()
    )
    default = "/tmp/pierre-feedback.jsonl" if serverless else "data/feedback.jsonl"
    return _path("FEEDBACK_FILE", default)


@dataclass(frozen=True)
class Settings:
    model: str = "text-embedding-3-small"
    enable_enrichment: bool = os.getenv("ENABLE_ENRICHMENT", "true").casefold() == "true"
    enrichment_model: str = os.getenv("ENRICHMENT_MODEL", "gpt-4.1-mini")
    query_model: str = os.getenv("QUERY_MODEL", "gpt-4.1-mini")
    search_min_score: float = float(os.getenv("SEARCH_MIN_SCORE", "0.28"))
    unknown_category_threshold: float = float(
        os.getenv("UNKNOWN_CATEGORY_THRESHOLD", "0.62")
    )
    # A query only restricts results to a category when its intent resolves to
    # that category with at least this cosine similarity. Below the floor the
    # query is treated as broad and keeps full semantic retrieval.
    category_gate_floor: float = float(os.getenv("CATEGORY_GATE_FLOOR", "0.50"))
    # Categories scoring at least this fraction of the best one are kept
    # together, so "viagens" resolves to both "passagem aérea" and
    # "hospedagem". A ratio is used instead of an absolute distance because
    # similarity scale varies per query.
    category_gate_ratio: float = float(os.getenv("CATEGORY_GATE_RATIO", "0.88"))
    enrichment_history_limit: int = int(os.getenv("ENRICHMENT_HISTORY_LIMIT", "12"))
    transactions_csv: Path = _path(
        "TRANSACTIONS_CSV", "ai_engineer_semantic_transactions.csv"
    )
    transactions_parquet: Path = _path(
        "TRANSACTIONS_PARQUET", "data/ai_engineer_semantic_transactions.parquet"
    )
    embeddings_parquet: Path = _path(
        "EMBEDDINGS_PARQUET",
        "data/ai_engineer_semantic_transactions_embeddings.parquet",
    )
    category_embeddings_parquet: Path = _path(
        "CATEGORY_EMBEDDINGS_PARQUET",
        "data/ai_engineer_semantic_transactions_category_embeddings.parquet",
    )
    feedback_file: Path = _feedback_path()
    query_cache_size: int = int(os.getenv("QUERY_CACHE_SIZE", "256"))
    # Production uses the same tx_* corpus as the deployed search index. The
    # independent bench_* suite remains available through EVALUATION_SUITE.
    evaluation_suite: Path = _path(
        "EVALUATION_SUITE", "data/evaluation/production_queries.jsonl"
    )

    @property
    def cors_origins(self) -> list[str]:
        raw = os.getenv(
            "CORS_ORIGINS", "http://localhost:3000,http://localhost:5173"
        )
        return [value.strip() for value in raw.split(",") if value.strip()]


settings = Settings()
