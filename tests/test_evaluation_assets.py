import csv
import json
from pathlib import Path
from unittest import TestCase

from app.evaluation import SHOWCASE_CASES

EVALUATION_DIR = Path(__file__).resolve().parents[1] / "data" / "evaluation"
PRODUCTION_CSV = Path(__file__).resolve().parents[1] / "ai_engineer_semantic_transactions.csv"


class EvaluationAssetsTest(TestCase):
    def test_golden_set_references_only_known_transactions(self) -> None:
        with (EVALUATION_DIR / "transactions.csv").open(encoding="utf-8", newline="") as source:
            records = list(csv.DictReader(source))
        transaction_ids = [record["transaction_id"] for record in records]
        self.assertGreaterEqual(len(records), 50)
        self.assertEqual(len(transaction_ids), len(set(transaction_ids)))

        cases = [
            json.loads(line)
            for line in (EVALUATION_DIR / "queries.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertGreaterEqual(len(cases), 20)
        for case in cases:
            self.assertIn("expected_status", case)
            self.assertIn("filters", case)
            self.assertTrue(set(case["relevant_ids"]).issubset(transaction_ids))

    def test_suite_has_empty_and_invalid_cases(self) -> None:
        cases = [
            json.loads(line)
            for line in (EVALUATION_DIR / "queries.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertTrue(any(case["expected_status"] == 422 for case in cases))
        self.assertTrue(
            any(case["expected_status"] == 200 and not case["relevant_ids"] for case in cases)
        )

    def test_production_golden_set_references_deployed_transactions(self) -> None:
        with PRODUCTION_CSV.open(encoding="utf-8", newline="") as source:
            transaction_ids = {record["transaction_id"] for record in csv.DictReader(source)}
        cases = [
            json.loads(line)
            for line in (EVALUATION_DIR / "production_queries.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
        self.assertGreaterEqual(len(cases), 12)
        self.assertTrue(any("load" in case.get("tags", []) for case in cases))
        self.assertTrue(any(case["expected_status"] == 422 for case in cases))
        self.assertTrue(
            all(set(case["relevant_ids"]).issubset(transaction_ids) for case in cases)
        )

    def test_showcase_has_six_labelled_cases_from_the_production_corpus(self) -> None:
        with PRODUCTION_CSV.open(encoding="utf-8", newline="") as source:
            transaction_ids = {record["transaction_id"] for record in csv.DictReader(source)}
        self.assertEqual(len(SHOWCASE_CASES), 6)
        self.assertEqual(len({case["id"] for case in SHOWCASE_CASES}), 6)
        self.assertTrue(all(case["label"] and case["scenario"] for case in SHOWCASE_CASES))
        self.assertTrue(
            all(
                set(case["relevant_ids"]).issubset(transaction_ids)
                for case in SHOWCASE_CASES
            )
        )
