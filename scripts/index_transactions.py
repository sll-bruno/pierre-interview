from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
from openai import OpenAI

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.enrichment import (  # noqa: E402
    CategoryCandidate,
    TransactionEnricher,
    TransactionEnrichment,
    TransactionInput,
    embedding_text,
)
from app.prompts import TRANSACTION_ENRICHMENT_SYSTEM_PROMPT  # noqa: E402
from app.search import normalize_text, record_hash, semantic_text  # noqa: E402

SOURCE_COLUMNS = ["transaction_id", "date", "merchant", "description", "amount_brl"]
ENRICHMENT_COLUMNS = [
    "enriched_context",
    "category",
    "category_confidence",
    "category_explanation",
    "category_candidates",
]
BATCH_SIZE = 20


def load_source() -> pd.DataFrame:
    frame = pd.read_csv(settings.transactions_csv, dtype={"transaction_id": "string"})
    missing = set(SOURCE_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"CSV inválido; colunas ausentes: {sorted(missing)}")
    frame = frame[SOURCE_COLUMNS].copy()
    if frame.isna().any().any():
        nulls = frame.isna().sum()
        raise ValueError(f"CSV contém valores nulos: {nulls[nulls > 0].to_dict()}")
    if frame["transaction_id"].duplicated().any():
        raise ValueError("CSV contém transaction_id duplicado")
    frame["date"] = pd.to_datetime(frame["date"], format="%Y-%m-%d", errors="raise")
    frame["amount_brl"] = pd.to_numeric(frame["amount_brl"], errors="raise")
    frame["merchant"] = frame["merchant"].map(lambda value: str(value).strip())
    frame["description"] = frame["description"].map(lambda value: str(value).strip())
    if (frame["merchant"] == "").any() or (frame["description"] == "").any():
        raise ValueError("CSV contém merchant ou description vazio")
    frame["raw_semantic_text"] = [
        semantic_text(merchant, description)
        for merchant, description in zip(frame["merchant"], frame["description"])
    ]
    enrichment_version = "\0".join(
        [
            settings.enrichment_model,
            str(settings.unknown_category_threshold),
            TRANSACTION_ENRICHMENT_SYSTEM_PROMPT,
        ]
    )
    frame["enrichment_base_hash"] = [
        record_hash(transaction_id, f"{text}\0{enrichment_version}")
        for transaction_id, text in zip(
            frame["transaction_id"], frame["raw_semantic_text"]
        )
    ]
    return frame


def existing_index() -> pd.DataFrame:
    if not settings.embeddings_parquet.exists():
        return pd.DataFrame()
    return pd.read_parquet(settings.embeddings_parquet)


def cached_enrichments(previous: pd.DataFrame) -> dict[str, dict[str, object]]:
    required = {"source_hash", *ENRICHMENT_COLUMNS}
    if previous.empty or not required.issubset(previous.columns):
        return {}
    return {
        str(row.source_hash): {column: getattr(row, column) for column in ENRICHMENT_COLUMNS}
        for row in previous.itertuples(index=False)
    }


def cached_embeddings(
    previous: pd.DataFrame, hash_column: str, embedding_column: str
) -> dict[str, list[float]]:
    if previous.empty or not {hash_column, embedding_column}.issubset(previous.columns):
        return {}
    return dict(zip(previous[hash_column], previous[embedding_column]))


def embed_pending(
    frame: pd.DataFrame,
    text_column: str,
    hash_column: str,
    cache: dict[str, list[float]],
) -> list[list[float]]:
    pending = frame.loc[~frame[hash_column].isin(cache)]
    if not pending.empty:
        client = OpenAI(timeout=30.0, max_retries=1)
        for start in range(0, len(pending), BATCH_SIZE):
            batch = pending.iloc[start : start + BATCH_SIZE]
            response = client.embeddings.create(
                model=settings.model,
                input=batch[text_column].tolist(),
                encoding_format="float",
            )
            for row_hash, item in zip(batch[hash_column], response.data):
                cache[row_hash] = item.embedding
    vectors = frame[hash_column].map(cache)
    if vectors.isna().any():
        raise RuntimeError(f"Nem todos os registros receberam {text_column}")
    return vectors.tolist()


def history_for(
    transaction: TransactionInput,
    past: list[dict[str, object]],
    limit: int,
) -> list[dict[str, object]]:
    """Prefer same-merchant and lexically similar past cases, then recent cases."""
    merchant = normalize_text(transaction.merchant)
    terms = set(normalize_text(f"{transaction.merchant} {transaction.description}").split())

    def relevance(item: dict[str, object]) -> tuple[int, int, str]:
        past_merchant = normalize_text(str(item["merchant"]))
        past_terms = set(
            normalize_text(f"{item['merchant']} {item['description']}").split()
        )
        return (
            int(past_merchant == merchant),
            len(terms & past_terms),
            str(item["date"]),
        )

    selected = sorted(past, key=relevance, reverse=True)[:limit]
    return [
        {
            "date": item["date"],
            "merchant": item["merchant"],
            "description": item["description"],
            "amount_brl": item["amount_brl"],
            "category": item["category"],
            "confidence": item["confidence"],
            "enriched_context": item["enriched_context"],
        }
        for item in selected
    ]


def deserialize_enrichment(cached: dict[str, object]) -> TransactionEnrichment:
    raw_candidates = cached["category_candidates"]
    if isinstance(raw_candidates, str):
        raw_candidates = json.loads(raw_candidates)
    return TransactionEnrichment(
        enriched_context=str(cached["enriched_context"]),
        category=str(cached["category"]),
        confidence=float(cached["category_confidence"]),
        explanation=str(cached["category_explanation"]),
        candidates=[CategoryCandidate.model_validate(item) for item in raw_candidates],
    )


def main() -> None:
    frame = load_source()
    settings.transactions_parquet.parent.mkdir(parents=True, exist_ok=True)
    frame[SOURCE_COLUMNS].to_parquet(settings.transactions_parquet, index=False)

    previous = existing_index()
    enrichment_cache = cached_enrichments(previous)
    raw_embedding_cache = cached_embeddings(
        previous, "raw_record_hash", "raw_embedding"
    )
    enriched_embedding_cache = cached_embeddings(
        previous, "enriched_record_hash", "enriched_embedding"
    )

    if not settings.enable_enrichment:
        raise RuntimeError(
            "ENABLE_ENRICHMENT precisa estar ativo para gerar os dois canais semânticos"
        )

    enricher = TransactionEnricher(
        model=settings.enrichment_model,
        unknown_threshold=settings.unknown_category_threshold,
    )
    past: list[dict[str, object]] = []
    enrichments: dict[int, TransactionEnrichment] = {}
    frame["source_hash"] = ""

    # Processing in chronological order guarantees that a new case only sees the past.
    ordered = frame.sort_values(["date", "transaction_id"], kind="stable")
    for index, row in ordered.iterrows():
        transaction = TransactionInput(
            transaction_id=str(row["transaction_id"]),
            date=row["date"].date(),
            merchant=str(row["merchant"]),
            description=str(row["description"]),
            amount_brl=float(row["amount_brl"]),
        )
        history = history_for(transaction, past, settings.enrichment_history_limit)
        history_signature = json.dumps(
            history, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        source_hash = record_hash(
            transaction.transaction_id,
            f"{row['enrichment_base_hash']}\0{history_signature}",
        )
        frame.at[index, "source_hash"] = source_hash
        cached = enrichment_cache.get(source_hash)
        if cached is not None:
            result = deserialize_enrichment(cached)
        else:
            result = enricher.enrich(transaction, history)
        enrichments[index] = result
        past.append(
            {
                "date": transaction.date.isoformat(),
                "merchant": transaction.merchant,
                "description": transaction.description,
                "amount_brl": transaction.amount_brl,
                "category": result.category,
                "confidence": result.confidence,
                "enriched_context": result.enriched_context,
            }
        )

    frame["enriched_context"] = [enrichments[index].enriched_context for index in frame.index]
    frame["category"] = [enrichments[index].category for index in frame.index]
    frame["category_confidence"] = [enrichments[index].confidence for index in frame.index]
    frame["category_explanation"] = [enrichments[index].explanation for index in frame.index]
    frame["category_candidates"] = [
        json.dumps(
            [candidate.model_dump() for candidate in enrichments[index].candidates],
            ensure_ascii=False,
        )
        for index in frame.index
    ]
    frame["enriched_semantic_text"] = [
        embedding_text(
            TransactionInput(
                transaction_id=str(row.transaction_id),
                date=row.date.date(),
                merchant=str(row.merchant),
                description=str(row.description),
                amount_brl=float(row.amount_brl),
            ),
            enrichments[index],
        )
        for index, row in frame.iterrows()
    ]
    frame["raw_record_hash"] = [
        record_hash(transaction_id, text)
        for transaction_id, text in zip(
            frame["transaction_id"], frame["raw_semantic_text"]
        )
    ]
    frame["enriched_record_hash"] = [
        record_hash(transaction_id, text)
        for transaction_id, text in zip(
            frame["transaction_id"], frame["enriched_semantic_text"]
        )
    ]
    frame["raw_embedding"] = embed_pending(
        frame, "raw_semantic_text", "raw_record_hash", raw_embedding_cache
    )
    frame["enriched_embedding"] = embed_pending(
        frame,
        "enriched_semantic_text",
        "enriched_record_hash",
        enriched_embedding_cache,
    )
    frame.to_parquet(settings.embeddings_parquet, index=False)
    print(f"Índice salvo em {settings.embeddings_parquet}")

    write_category_embeddings(frame)


def write_category_embeddings(frame: pd.DataFrame) -> None:
    """Embed the category vocabulary once, offline, so search can resolve a
    query to categories without an extra model call per request."""
    categories = sorted({str(value) for value in frame["category"]})
    client = OpenAI(timeout=30.0, max_retries=1)
    vectors: list[list[float]] = []
    for start in range(0, len(categories), BATCH_SIZE):
        batch = categories[start : start + BATCH_SIZE]
        response = client.embeddings.create(
            model=settings.model,
            input=[normalize_text(value) for value in batch],
            encoding_format="float",
        )
        vectors.extend(item.embedding for item in response.data)
    pd.DataFrame({"category": categories, "embedding": vectors}).to_parquet(
        settings.category_embeddings_parquet, index=False
    )
    print(
        f"{len(categories)} categorias salvas em "
        f"{settings.category_embeddings_parquet}"
    )


if __name__ == "__main__":
    main()
