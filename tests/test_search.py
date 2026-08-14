from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase

import numpy as np
import pandas as pd

from app.models import QueryInterpretation, SearchFilters
from app.search import TransactionSearch


class FakeInterpreter:
    async def interpret(self, query: str, data_min: date, data_max: date) -> QueryInterpretation:
        return QueryInterpretation(
            semantic_intent="delivery de comida", evidence=["delivery"]
        )


class SearchTest(IsolatedAsyncioTestCase):
    async def test_semantic_score_returns_filtered_results(self) -> None:
        with TemporaryDirectory() as directory:
            index = Path(directory) / "index.parquet"
            pd.DataFrame(
                [
                    {
                        "transaction_id": "relevant",
                        "date": date(2026, 7, 10),
                        "merchant": "iFood",
                        "description": "IFOOD RESTAURANTE",
                        "amount_brl": 120.0,
                        "embedding": [1.0, 0.0],
                    },
                    {
                        "transaction_id": "weak",
                        "date": date(2026, 7, 11),
                        "merchant": "Cemig",
                        "description": "ENERGIA ELETRICA",
                        "amount_brl": 200.0,
                        "embedding": [0.0, 1.0],
                    },
                ]
            ).to_parquet(index, index=False)
            config = SimpleNamespace(
                embeddings_parquet=index,
                query_cache_size=8,
                model="text-embedding-3-small",
                feedback_file=Path(directory) / "feedback.jsonl",
            )
            search = TransactionSearch(config)
            search.interpreter = FakeInterpreter()  # type: ignore[assignment]

            async def fake_embedding(query: str) -> np.ndarray:
                return np.asarray([1.0, 0.0], dtype=np.float32)

            search._embed_query = fake_embedding  # type: ignore[method-assign]
            response = await search.search("delivery", SearchFilters())

            self.assertEqual(response.transaction_ids, ["relevant", "weak"])
            self.assertEqual(response.period.source, "latest_15_days")
            self.assertEqual(response.transactions[0].score, 1.0)
            self.assertIn("descrição original semanticamente semelhante", response.transactions[0].matched_signals)
