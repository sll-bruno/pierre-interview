from datetime import date
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase

from app.query import ParsedQuery, QueryInterpreter, fallback_interpretation


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

    def test_removes_currency_word_after_amount(self) -> None:
        result = fallback_interpretation(
            "Delivery acima de 100 reais",
            date(2026, 1, 1),
            date(2026, 8, 9),
        )
        self.assertEqual(result.semantic_intent, "Delivery")
        self.assertEqual(result.min_amount_brl, 100)

    def test_combines_amount_and_month_in_one_query(self) -> None:
        """'Compras acima de R$ 300 em junho' must apply both constraints."""
        result = fallback_interpretation(
            "Compras acima de R$ 300 em junho",
            date(2026, 1, 1),
            date(2026, 8, 9),
        )
        self.assertEqual(result.semantic_intent, "Compras")
        self.assertEqual(result.min_amount_brl, 300)
        self.assertEqual(result.date_from, date(2026, 6, 1))
        self.assertEqual(result.date_to, date(2026, 6, 30))
        self.assertIsNone(result.aggregation)

    def test_detects_aggregation_and_strips_it_from_the_intent(self) -> None:
        result = fallback_interpretation(
            "Quanto paguei em streaming?",
            date(2026, 1, 1),
            date(2026, 8, 9),
        )
        self.assertEqual(result.aggregation, "sum")
        self.assertEqual(result.semantic_intent, "streaming")

    def test_detects_other_aggregation_phrasings(self) -> None:
        for query, intent in [
            ("qual o total gasto com farmácia", "farmácia"),
            ("quanto gastei com academia", "academia"),
            ("soma de cinema", "cinema"),
        ]:
            with self.subTest(query=query):
                result = fallback_interpretation(
                    query, date(2026, 1, 1), date(2026, 8, 9)
                )
                self.assertEqual(result.aggregation, "sum")
                self.assertEqual(result.semantic_intent, intent)

    def test_plain_query_is_not_treated_as_aggregation(self) -> None:
        for query in ["corridas de aplicativo", "compras no Carrefour", "viagens"]:
            with self.subTest(query=query):
                result = fallback_interpretation(
                    query, date(2026, 1, 1), date(2026, 8, 9)
                )
                self.assertIsNone(result.aggregation)
                self.assertEqual(result.semantic_intent, query)


class FakeResponses:
    def __init__(self, parsed: ParsedQuery) -> None:
        self._parsed = parsed
        self.calls: list[dict] = []

    async def parse(self, **kwargs) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(output_parsed=self._parsed)


class FakeClient:
    def __init__(self, parsed: ParsedQuery) -> None:
        self.responses = FakeResponses(parsed)


class QueryInterpreterTest(IsolatedAsyncioTestCase):
    async def test_requests_deterministic_sampling(self) -> None:
        client = FakeClient(
            ParsedQuery(semantic_intent="corridas de aplicativo", evidence=["corridas"])
        )
        interpreter = QueryInterpreter("gpt-4.1-mini", client=client)

        await interpreter.interpret(
            "corridas de aplicativo", date(2026, 1, 1), date(2026, 8, 9)
        )

        self.assertEqual(client.responses.calls[0]["temperature"], 0)

    async def test_repeated_query_is_served_from_cache(self) -> None:
        client = FakeClient(
            ParsedQuery(semantic_intent="delivery de comida", evidence=["delivery"])
        )
        interpreter = QueryInterpreter("gpt-4.1-mini", client=client, cache_size=8)
        data_min, data_max = date(2026, 1, 1), date(2026, 8, 9)

        first = await interpreter.interpret("delivery", data_min, data_max)
        second = await interpreter.interpret("delivery", data_min, data_max)

        self.assertEqual(first, second)
        self.assertEqual(len(client.responses.calls), 1)

    async def test_distinct_queries_are_not_conflated_in_the_cache(self) -> None:
        client = FakeClient(
            ParsedQuery(semantic_intent="delivery de comida", evidence=["delivery"])
        )
        interpreter = QueryInterpreter("gpt-4.1-mini", client=client, cache_size=8)
        data_min, data_max = date(2026, 1, 1), date(2026, 8, 9)

        await interpreter.interpret("delivery", data_min, data_max)
        await interpreter.interpret("corridas de aplicativo", data_min, data_max)

        self.assertEqual(len(client.responses.calls), 2)

    async def test_a_failed_call_is_not_cached_and_is_retried(self) -> None:
        class FailingResponses:
            def __init__(self) -> None:
                self.calls = 0

            async def parse(self, **kwargs):
                self.calls += 1
                raise RuntimeError("upstream unavailable")

        client = SimpleNamespace(responses=FailingResponses())
        interpreter = QueryInterpreter("gpt-4.1-mini", client=client)
        data_min, data_max = date(2026, 1, 1), date(2026, 8, 9)

        first = await interpreter.interpret("delivery", data_min, data_max)
        second = await interpreter.interpret("delivery", data_min, data_max)

        self.assertEqual(first.semantic_intent, "delivery")
        self.assertEqual(second.semantic_intent, "delivery")
        self.assertEqual(client.responses.calls, 2)
