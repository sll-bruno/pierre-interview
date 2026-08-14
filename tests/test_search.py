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


class MerchantFakeInterpreter:
    async def interpret(
        self, query: str, data_min: date, data_max: date
    ) -> QueryInterpretation:
        return QueryInterpretation(
            semantic_intent="compras", merchant="carrefur", evidence=["carrefur"]
        )


class SearchTest(IsolatedAsyncioTestCase):
    async def test_hybrid_score_exposes_evidence_and_drops_weak_result(self) -> None:
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
                        "category": "delivery de comida",
                        "category_confidence": 0.91,
                        "raw_embedding": [1.0, 0.0],
                        "enriched_embedding": [1.0, 0.0],
                    },
                    {
                        "transaction_id": "weak",
                        "date": date(2026, 7, 11),
                        "merchant": "Cemig",
                        "description": "ENERGIA ELETRICA",
                        "amount_brl": 200.0,
                        "category": "energia elétrica",
                        "category_confidence": 0.96,
                        "raw_embedding": [1.0, 0.0],
                        "enriched_embedding": [1.0, 0.0],
                    },
                ]
            ).to_parquet(index, index=False)
            config = SimpleNamespace(
                embeddings_parquet=index,
                query_cache_size=8,
                query_model="gpt-4.1-mini",
                model="text-embedding-3-small",
                search_min_score=0.28,
                feedback_file=Path(directory) / "feedback.jsonl",
            )
            search = TransactionSearch(config)
            search.interpreter = FakeInterpreter()  # type: ignore[assignment]

            async def fake_embedding(query: str) -> np.ndarray:
                return np.asarray([1.0, 0.0], dtype=np.float32)

            search._embed_query = fake_embedding  # type: ignore[method-assign]
            response = await search.search("delivery", SearchFilters())

            self.assertEqual(response.transaction_ids, ["relevant"])
            self.assertEqual(response.period.source, "all_data")
            self.assertGreater(response.transactions[0].score, 0.9)
            self.assertIn(
                "categoria inferida: delivery de comida",
                response.transactions[0].matched_signals,
            )

    async def test_filters_an_explicit_merchant_with_a_small_typo(self) -> None:
        with TemporaryDirectory() as directory:
            index = Path(directory) / "index.parquet"
            pd.DataFrame(
                [
                    {
                        "transaction_id": "carrefour",
                        "date": date(2026, 7, 10),
                        "merchant": "Carrefour",
                        "description": "CARREFOUR HIPER",
                        "amount_brl": 120.0,
                        "category": "supermercado",
                        "category_confidence": 0.99,
                        "raw_embedding": [1.0, 0.0],
                        "enriched_embedding": [1.0, 0.0],
                    },
                    {
                        "transaction_id": "other",
                        "date": date(2026, 7, 10),
                        "merchant": "Localiza",
                        "description": "LOCALIZA RENT A CAR",
                        "amount_brl": 120.0,
                        "category": "aluguel de carro",
                        "category_confidence": 0.99,
                        "raw_embedding": [1.0, 0.0],
                        "enriched_embedding": [1.0, 0.0],
                    },
                ]
            ).to_parquet(index, index=False)
            config = SimpleNamespace(
                embeddings_parquet=index,
                query_cache_size=8,
                query_model="gpt-4.1-mini",
                model="text-embedding-3-small",
                search_min_score=0.28,
                feedback_file=Path(directory) / "feedback.jsonl",
            )
            search = TransactionSearch(config)
            search.interpreter = MerchantFakeInterpreter()  # type: ignore[assignment]

            async def fake_embedding(query: str) -> np.ndarray:
                return np.asarray([1.0, 0.0], dtype=np.float32)

            search._embed_query = fake_embedding  # type: ignore[method-assign]
            response = await search.search("compras no carrefur", SearchFilters())

            self.assertEqual(response.transaction_ids, ["carrefour"])
