from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
from openai import OpenAI

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.search import record_hash, semantic_text  # noqa: E402

SOURCE_COLUMNS = ["transaction_id", "date", "merchant", "description", "amount_brl"]
BATCH_SIZE = 20


def load_source() -> pd.DataFrame:
    frame = pd.read_csv(settings.transactions_csv, dtype={"transaction_id": "string"})
    missing = set(SOURCE_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"CSV inválido; colunas ausentes: {sorted(missing)}")
    frame = frame[SOURCE_COLUMNS].copy()
    if frame.isna().any().any():
        raise ValueError("CSV contém valores nulos")
    if frame["transaction_id"].duplicated().any():
        raise ValueError("CSV contém transaction_id duplicado")
    frame["date"] = pd.to_datetime(frame["date"], format="%Y-%m-%d", errors="raise")
    frame["amount_brl"] = pd.to_numeric(frame["amount_brl"], errors="raise")
    frame["merchant"] = frame["merchant"].astype(str).str.strip()
    frame["description"] = frame["description"].astype(str).str.strip()
    if (frame["merchant"] == "").any() or (frame["description"] == "").any():
        raise ValueError("CSV contém merchant ou description vazio")
    frame["semantic_text"] = [semantic_text(merchant, description) for merchant, description in zip(frame["merchant"], frame["description"])]
    frame["record_hash"] = [record_hash(transaction_id, text) for transaction_id, text in zip(frame["transaction_id"], frame["semantic_text"])]
    return frame


def existing_embeddings() -> dict[str, list[float]]:
    if not settings.embeddings_parquet.exists():
        return {}
    previous = pd.read_parquet(settings.embeddings_parquet)
    if not {"record_hash", "embedding"}.issubset(previous.columns):
        return {}
    return dict(zip(previous["record_hash"], previous["embedding"]))


def main() -> None:
    frame = load_source()
    settings.transactions_parquet.parent.mkdir(parents=True, exist_ok=True)
    frame[SOURCE_COLUMNS].to_parquet(settings.transactions_parquet, index=False)
    cached = existing_embeddings()
    pending = frame.loc[~frame["record_hash"].isin(cached)]
    print(f"Registros: {len(frame)} | em cache: {len(frame) - len(pending)} | novos: {len(pending)}")
    if not pending.empty:
        client = OpenAI(timeout=30.0, max_retries=1)
        for start in range(0, len(pending), BATCH_SIZE):
            batch = pending.iloc[start : start + BATCH_SIZE]
            response = client.embeddings.create(model=settings.model, input=batch["semantic_text"].tolist(), encoding_format="float")
            for row_hash, item in zip(batch["record_hash"], response.data):
                cached[row_hash] = item.embedding
    frame["embedding"] = frame["record_hash"].map(cached)
    if frame["embedding"].isna().any():
        raise RuntimeError("Nem todos os registros receberam embedding")
    frame.to_parquet(settings.embeddings_parquet, index=False)
    print(f"Índice salvo em {settings.embeddings_parquet}")


if __name__ == "__main__":
    main()
