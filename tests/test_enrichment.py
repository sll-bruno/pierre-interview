from datetime import date
from types import SimpleNamespace
from unittest import TestCase

from app.enrichment import (
    CategoryCandidate,
    LLMEnrichment,
    TransactionEnricher,
    TransactionInput,
    apply_unknown_threshold,
    embedding_text,
)


class FakeResponses:
    def __init__(self, parsed: LLMEnrichment) -> None:
        self.parsed = parsed
        self.call: dict[str, object] | None = None

    def parse(self, **kwargs: object) -> SimpleNamespace:
        self.call = kwargs
        return SimpleNamespace(output_parsed=self.parsed)


class FakeClient:
    def __init__(self, parsed: LLMEnrichment) -> None:
        self.responses = FakeResponses(parsed)


class EnrichmentTest(TestCase):
    def test_enricher_sends_history_and_uses_structured_output(self) -> None:
        parsed = LLMEnrichment(
            enriched_context="Refeição em restaurante.",
            candidates=[
                CategoryCandidate(
                    category="restaurante",
                    confidence=0.88,
                    explanation="O histórico do merchant indica restaurante.",
                )
            ],
        )
        client = FakeClient(parsed)
        enricher = TransactionEnricher(client=client)  # type: ignore[arg-type]
        result = enricher.enrich(
            TransactionInput(
                transaction_id="tx_2",
                date=date(2026, 1, 2),
                merchant="Outback",
                description="OUTBACK STEAKHOUSE",
                amount_brl=180,
            ),
            history=[{"merchant": "Outback", "category": "restaurante"}],
        )
        self.assertEqual(result.category, "restaurante")
        assert client.responses.call is not None
        self.assertEqual(client.responses.call["model"], "gpt-4.1-mini")
        self.assertIs(client.responses.call["text_format"], LLMEnrichment)
        self.assertIn("similar_past_transactions", str(client.responses.call["input"]))

    def test_keeps_high_confidence_category(self) -> None:
        result = apply_unknown_threshold(
            LLMEnrichment(
                enriched_context="Compra de alimentos em hipermercado.",
                candidates=[
                    CategoryCandidate(
                        category="Supermercado",
                        confidence=0.91,
                        explanation="Carrefour e a descrição hipermercado são sinais diretos.",
                    )
                ],
            ),
            threshold=0.62,
        )
        self.assertEqual(result.category, "supermercado")
        self.assertEqual(result.confidence, 0.91)

    def test_uses_unknown_instead_of_forcing_low_confidence_guess(self) -> None:
        result = apply_unknown_threshold(
            LLMEnrichment(
                enriched_context="Cobrança sem finalidade identificável.",
                candidates=[
                    CategoryCandidate(
                        category="serviços",
                        confidence=0.38,
                        explanation="O merchant não permite determinar o serviço.",
                    )
                ],
            ),
            threshold=0.62,
        )
        self.assertEqual(result.category, "desconhecido")
        self.assertAlmostEqual(result.confidence, 0.62)
        self.assertEqual(result.candidates[1].category, "serviços")

    def test_embedding_text_contains_enriched_classification(self) -> None:
        transaction = TransactionInput(
            transaction_id="tx_1",
            date=date(2026, 1, 1),
            merchant="Shell",
            description="POSTO SHELL",
            amount_brl=100,
        )
        result = apply_unknown_threshold(
            LLMEnrichment(
                enriched_context="Abastecimento em posto de combustível.",
                candidates=[
                    CategoryCandidate(
                        category="combustível",
                        confidence=0.95,
                        explanation="A descrição identifica um posto Shell.",
                    )
                ],
            ),
            threshold=0.62,
        )
        text = embedding_text(transaction, result)
        self.assertIn("categoria: combustível", text)
        self.assertIn("Abastecimento em posto", text)
