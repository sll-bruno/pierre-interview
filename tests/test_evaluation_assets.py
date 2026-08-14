import csv
import json
from pathlib import Path
from unittest import TestCase


EVALUATION_DIR = Path(__file__).resolve().parents[1] / "data" / "evaluation"


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
