from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase

import numpy as np
import pandas as pd

from app.models import QueryInterpretation, SearchFilters
from app.search import TransactionSearch

# Two-dimensional unit vectors keep every similarity in these tests exact:
# ALIGNED matches the query direction, ORTHOGONAL is unrelated to it, and
# NEAR sits close enough to be pulled in as a sibling category.
ALIGNED = [1.0, 0.0]
ORTHOGONAL = [0.0, 1.0]
NEAR = [0.95, 0.3122]


def transaction(
    transaction_id: str,
    merchant: str,
    category: str,
    amount: float = 100.0,
    when: date = date(2026, 7, 10),
    raw: list[float] | None = None,
) -> dict:
    return {
        "transaction_id": transaction_id,
        "date": when,
        "merchant": merchant,
        "description": f"{merchant.upper()} COMPRA",
        "amount_brl": amount,
        "category": category,
        "category_confidence": 0.95,
        "raw_embedding": raw or ALIGNED,
        "enriched_embedding": raw or ALIGNED,
    }


class StubInterpreter:
    def __init__(self, **fields) -> None:
        self.fields = fields

    async def interpret(
        self, query: str, data_min: date, data_max: date
    ) -> QueryInterpretation:
        return QueryInterpretation(**self.fields)


def build_search(
    directory: str,
    rows: list[dict],
    categories: dict[str, list[float]] | None = None,
    *,
    search_min_score: float = 0.28,
    interpreter: StubInterpreter | None = None,
) -> TransactionSearch:
    index = Path(directory) / "index.parquet"
    pd.DataFrame(rows).to_parquet(index, index=False)

    category_index = Path(directory) / "categories.parquet"
    if categories:
        pd.DataFrame(
            {
                "category": list(categories),
                "embedding": list(categories.values()),
            }
        ).to_parquet(category_index, index=False)

    config = SimpleNamespace(
        embeddings_parquet=index,
        category_embeddings_parquet=category_index,
        query_cache_size=8,
        query_model="gpt-4.1-mini",
        model="text-embedding-3-small",
        search_min_score=search_min_score,
        category_gate_floor=0.5,
        category_gate_ratio=0.88,
        feedback_file=Path(directory) / "feedback.jsonl",
    )
    search = TransactionSearch(config)
    if interpreter is not None:
        search.interpreter = interpreter  # type: ignore[assignment]

    async def fake_embedding(query: str) -> np.ndarray:
        return np.asarray(ALIGNED, dtype=np.float32)

    search._embed_query = fake_embedding  # type: ignore[method-assign]
    return search


class SearchTest(IsolatedAsyncioTestCase):
    async def test_hybrid_score_exposes_evidence_and_drops_weak_result(self) -> None:
        with TemporaryDirectory() as directory:
            search = build_search(
                directory,
                [
                    transaction("relevant", "iFood", "delivery de comida"),
                    transaction(
                        "weak", "Cemig", "energia elétrica", raw=[0.2, 0.9798]
                    ),
                ],
                interpreter=StubInterpreter(
                    semantic_intent="delivery de comida", evidence=["delivery"]
                ),
            )
            response = await search.search("delivery", SearchFilters())

            self.assertEqual(response.transaction_ids, ["relevant"])
            self.assertEqual(response.period.source, "all_data")
            self.assertGreater(response.transactions[0].score, 0.9)

    async def test_filters_an_explicit_merchant_with_a_small_typo(self) -> None:
        with TemporaryDirectory() as directory:
            search = build_search(
                directory,
                [
                    transaction("carrefour", "Carrefour", "supermercado"),
                    transaction("other", "Localiza", "aluguel de carro"),
                ],
                interpreter=StubInterpreter(
                    semantic_intent="compras",
                    merchant="carrefur",
                    evidence=["carrefur"],
                ),
            )
            response = await search.search("compras no carrefur", SearchFilters())

            self.assertEqual(response.transaction_ids, ["carrefour"])


class CategoryGateTest(IsolatedAsyncioTestCase):
    """Regression cover for 'Corridas de Aplicativo' and 'Viagens acima de 500':
    a query that resolves to a category must not return other categories, even
    when their embeddings score above the cutoff."""

    async def test_gate_restricts_results_to_the_resolved_category(self) -> None:
        with TemporaryDirectory() as directory:
            search = build_search(
                directory,
                [
                    transaction("ride_uber", "Uber", "transporte por aplicativo"),
                    transaction("ride_99", "99", "transporte por aplicativo"),
                    # Identical embeddings, so only the gate can exclude them.
                    transaction("netflix", "Netflix", "streaming de vídeo"),
                    transaction("rappi", "Rappi", "delivery de comida"),
                ],
                categories={
                    "transporte por aplicativo": ALIGNED,
                    "streaming de vídeo": ORTHOGONAL,
                    "delivery de comida": ORTHOGONAL,
                },
                interpreter=StubInterpreter(semantic_intent="corridas de aplicativo"),
            )
            response = await search.search("corridas de aplicativo", SearchFilters())

            self.assertEqual(
                sorted(response.transaction_ids), ["ride_99", "ride_uber"]
            )
            self.assertEqual(
                response.interpretation.categories, ["transporte por aplicativo"]
            )

    async def test_gate_keeps_sibling_categories_above_the_ratio(self) -> None:
        with TemporaryDirectory() as directory:
            search = build_search(
                directory,
                [
                    transaction("flight", "LATAM", "passagem aérea", amount=1200.0),
                    transaction("stay", "Airbnb", "hospedagem", amount=900.0),
                    transaction("sofa", "Tok&Stok", "móveis e decoração", amount=800.0),
                ],
                categories={
                    "passagem aérea": ALIGNED,
                    "hospedagem": NEAR,
                    "móveis e decoração": ORTHOGONAL,
                },
                interpreter=StubInterpreter(
                    semantic_intent="viagens", min_amount_brl=500.0
                ),
            )
            response = await search.search("viagens acima de 500", SearchFilters())

            self.assertEqual(sorted(response.transaction_ids), ["flight", "stay"])
            self.assertEqual(
                sorted(response.interpretation.categories),
                ["hospedagem", "passagem aérea"],
            )

    async def test_gate_applies_the_minimum_amount_from_the_query(self) -> None:
        with TemporaryDirectory() as directory:
            search = build_search(
                directory,
                [
                    transaction("expensive", "LATAM", "passagem aérea", amount=1200.0),
                    transaction("cheap", "LATAM", "passagem aérea", amount=120.0),
                ],
                categories={"passagem aérea": ALIGNED},
                interpreter=StubInterpreter(
                    semantic_intent="viagens", min_amount_brl=500.0
                ),
            )
            response = await search.search("viagens acima de 500", SearchFilters())

            self.assertEqual(response.transaction_ids, ["expensive"])

    async def test_gate_is_skipped_when_the_query_names_a_merchant(self) -> None:
        """'Compras no Carrefour' must follow the merchant filter, not be
        narrowed to whatever category the word 'compras' resolves to."""
        with TemporaryDirectory() as directory:
            search = build_search(
                directory,
                [
                    transaction("carrefour_food", "Carrefour", "supermercado"),
                    transaction("carrefour_other", "Carrefour", "marketplace"),
                    transaction("pao", "Pão de Açúcar", "supermercado"),
                ],
                categories={"supermercado": ALIGNED, "marketplace": ORTHOGONAL},
                interpreter=StubInterpreter(
                    semantic_intent="compras", merchant="Carrefour"
                ),
            )
            response = await search.search("compras no Carrefour", SearchFilters())

            self.assertEqual(
                sorted(response.transaction_ids),
                ["carrefour_food", "carrefour_other"],
            )
            self.assertEqual(response.interpretation.categories, [])

    async def test_broad_query_keeps_the_score_cutoff(self) -> None:
        """'Compras acima de R$ 300 em junho' does not resolve to a category,
        so retrieval stays open and the cutoff is what bounds the tail."""
        with TemporaryDirectory() as directory:
            search = build_search(
                directory,
                [
                    transaction(
                        "june_buy",
                        "Mercado Livre",
                        "marketplace",
                        amount=450.0,
                        when=date(2026, 6, 15),
                    ),
                    transaction(
                        "june_cheap",
                        "Mercado Livre",
                        "marketplace",
                        amount=90.0,
                        when=date(2026, 6, 16),
                    ),
                    transaction(
                        "july_buy",
                        "Mercado Livre",
                        "marketplace",
                        amount=450.0,
                        when=date(2026, 7, 15),
                    ),
                ],
                # Every category is unrelated to the query direction, so the
                # gate stays closed and the query keeps open retrieval.
                categories={"marketplace": ORTHOGONAL},
                interpreter=StubInterpreter(
                    semantic_intent="compras",
                    min_amount_brl=300.0,
                    date_from=date(2026, 6, 1),
                    date_to=date(2026, 6, 30),
                ),
            )
            response = await search.search(
                "compras acima de R$ 300 em junho", SearchFilters()
            )

            self.assertEqual(response.transaction_ids, ["june_buy"])
            self.assertEqual(response.interpretation.categories, [])
            self.assertEqual(response.period.date_from, date(2026, 6, 1))
            self.assertEqual(response.period.date_to, date(2026, 6, 30))

    async def test_a_missing_category_artifact_disables_gating(self) -> None:
        """An index deployed without the category vocabulary must keep serving
        searches instead of failing to start."""
        with TemporaryDirectory() as directory:
            search = build_search(
                directory,
                [transaction("ride", "Uber", "transporte por aplicativo")],
                categories=None,
                interpreter=StubInterpreter(semantic_intent="corridas"),
            )
            response = await search.search("corridas", SearchFilters())

            self.assertEqual(search.categories, [])
            self.assertEqual(response.transaction_ids, ["ride"])


class AggregationTest(IsolatedAsyncioTestCase):
    """Regression cover for 'Quanto paguei em streaming?'."""

    async def test_aggregation_query_returns_the_total_over_all_matches(self) -> None:
        with TemporaryDirectory() as directory:
            search = build_search(
                directory,
                [
                    transaction("netflix", "Netflix", "streaming de vídeo", amount=55.90),
                    transaction("youtube", "YouTube Premium", "streaming de vídeo", amount=24.90),
                    transaction("spotify", "Spotify", "streaming de música", amount=21.90),
                    transaction("market", "Carrefour", "supermercado", amount=300.0),
                ],
                categories={
                    "streaming de vídeo": ALIGNED,
                    "streaming de música": NEAR,
                    "supermercado": ORTHOGONAL,
                },
                interpreter=StubInterpreter(
                    semantic_intent="streaming", aggregation="sum"
                ),
            )
            response = await search.search(
                "Quanto paguei em streaming?", SearchFilters()
            )

            self.assertEqual(response.interpretation.aggregation, "sum")
            self.assertEqual(
                sorted(response.transaction_ids), ["netflix", "spotify", "youtube"]
            )
            self.assertEqual(response.count, 3)
            self.assertAlmostEqual(response.total_amount_brl, 102.70, places=2)

    async def test_total_is_present_for_non_aggregation_queries(self) -> None:
        with TemporaryDirectory() as directory:
            search = build_search(
                directory,
                [transaction("ride", "Uber", "transporte por aplicativo", amount=33.45)],
                categories={"transporte por aplicativo": ALIGNED},
                interpreter=StubInterpreter(semantic_intent="corridas de aplicativo"),
            )
            response = await search.search("corridas de aplicativo", SearchFilters())

            self.assertIsNone(response.interpretation.aggregation)
            self.assertAlmostEqual(response.total_amount_brl, 33.45, places=2)
