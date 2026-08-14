from datetime import date
from unittest import TestCase

from app.query import fallback_interpretation


class QueryInterpretationTest(TestCase):
    def test_extracts_common_filters_without_model(self) -> None:
        result = fallback_interpretation(
            "delivery acima de R$ 100 em julho",
            date(2026, 1, 1),
            date(2026, 8, 9),
        )
        self.assertEqual(result.semantic_intent, "delivery")
        self.assertEqual(result.min_amount_brl, 100)
        self.assertEqual(result.date_from, date(2026, 7, 1))
        self.assertEqual(result.date_to, date(2026, 7, 31))

