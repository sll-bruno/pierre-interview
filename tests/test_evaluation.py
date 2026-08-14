import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase

import pandas as pd
from fastapi import HTTPException

from app.evaluation import public_cases, run_quality, status


def write_suite(path: Path) -> None:
    cases = [
        {
            "id": "found",
            "query": "encontrar",
            "filters": {},
            "expected_status": 200,
            "relevant_ids": ["tx_a"],
            "tags": ["load"],
        },
        {
            "id": "empty",
            "query": "vazio",
            "filters": {},
            "expected_status": 200,
            "relevant_ids": [],
            "tags": ["load"],
        },
        {
            "id": "invalid",
            "query": "vaga",
            "filters": {},
            "expected_status": 422,
            "relevant_ids": [],
            "tags": [],
        },
    ]
    path.write_text("\n".join(json.dumps(case) for case in cases), encoding="utf-8")


class FakeEngine:
    def __init__(self) -> None:
        self.frame = pd.DataFrame({"transaction_id": ["tx_a"]})

    async def search(self, query: str, filters: object) -> SimpleNamespace:
        del filters
        if query == "vaga":
            raise HTTPException(status_code=422, detail="Consulta muito vaga")
        return SimpleNamespace(transaction_ids=["tx_a"] if query == "encontrar" else [])


class EvaluationStatusTest(TestCase):
    def test_requires_the_active_index_to_match_labels(self) -> None:
        with TemporaryDirectory() as directory:
            suite = Path(directory) / "suite.jsonl"
            write_suite(suite)
            self.assertTrue(status(FakeEngine(), suite)["available"])
            wrong_engine = SimpleNamespace(frame=pd.DataFrame({"transaction_id": ["other"]}))
            self.assertFalse(status(wrong_engine, suite)["available"])
            self.assertEqual(len(public_cases(suite, "load")), 2)


class EvaluationRunTest(IsolatedAsyncioTestCase):
    async def test_aggregates_labelled_quality_metrics(self) -> None:
        with TemporaryDirectory() as directory:
            suite = Path(directory) / "suite.jsonl"
            write_suite(suite)
            report = await run_quality(FakeEngine(), suite, top_k=10)
            self.assertEqual(report["summary"]["exact_pass_rate"], 1.0)
            self.assertEqual(report["summary"]["mean_recall_at_k"], 1.0)
            self.assertEqual(report["summary"]["mrr_at_k"], 1.0)
            self.assertIn("p95", report["summary"]["latency_ms"])
