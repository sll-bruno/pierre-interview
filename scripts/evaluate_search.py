"""Evaluate the HTTP search API against a labelled golden set.

The script intentionally uses only the standard library so it can be used in
CI or against a deployed instance without adding a load-testing dependency.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_SUITE = Path("data/evaluation/queries.jsonl")


def load_suite(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    required = {"id", "query", "filters", "expected_status", "relevant_ids"}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        case = json.loads(line)
        missing = required - set(case)
        if missing:
            raise ValueError(f"{path}:{line_number}: campos ausentes: {sorted(missing)}")
        if not isinstance(case["relevant_ids"], list):
            raise ValueError(f"{path}:{line_number}: relevant_ids precisa ser uma lista")
        cases.append(case)
    if not cases:
        raise ValueError(f"Suite vazia: {path}")
    return cases


def call_search(base_url: str, case: dict[str, Any], timeout: float) -> tuple[int, dict[str, Any], float]:
    payload = json.dumps(
        {"query": case["query"], "filters": case["filters"]}, ensure_ascii=False
    ).encode("utf-8")
    request = Request(
        f"{base_url.rstrip('/')}/search",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body), (time.perf_counter() - started) * 1000
    except HTTPError as error:
        body = error.read().decode("utf-8")
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = {"raw_body": body}
        return error.code, parsed, (time.perf_counter() - started) * 1000
    except (URLError, TimeoutError) as error:
        return 0, {"error": str(error)}, (time.perf_counter() - started) * 1000


def percentile(values: list[float], point: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = max(0, math.ceil(len(ordered) * point) - 1)
    return round(ordered[position], 2)


def main() -> int:
    parser = argparse.ArgumentParser(description="Avalia relevância e latência de /search")
    parser.add_argument("--base-url", required=True, help="Ex.: http://127.0.0.1:8001")
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=45)
    parser.add_argument("--output", type=Path, help="Salva o relatório completo em JSON")
    args = parser.parse_args()
    if args.top_k < 1:
        parser.error("--top-k deve ser maior que zero")

    cases = load_suite(args.suite)
    rows: list[dict[str, Any]] = []
    recalls: list[float] = []
    reciprocal_ranks: list[float] = []
    hit_cases = 0

    for case in cases:
        status, response, latency_ms = call_search(args.base_url, case, args.timeout)
        expected_ids = set(case["relevant_ids"])
        returned_ids = response.get("transaction_ids", [])[: args.top_k] if status == 200 else []
        returned_set = set(returned_ids)
        found = expected_ids & returned_set
        status_ok = status == case["expected_status"]
        if expected_ids:
            recall = len(found) / len(expected_ids)
            first_rank = next(
                (index + 1 for index, value in enumerate(returned_ids) if value in expected_ids),
                None,
            )
            reciprocal_rank = 0.0 if first_rank is None else 1 / first_rank
            semantic_ok = bool(found)
            recalls.append(recall)
            reciprocal_ranks.append(reciprocal_rank)
            hit_cases += int(semantic_ok)
        elif case["expected_status"] == 200:
            recall = None
            reciprocal_rank = None
            semantic_ok = status == 200 and len(returned_ids) == 0
        else:
            recall = None
            reciprocal_rank = None
            semantic_ok = True

        rows.append(
            {
                "id": case["id"],
                "scenario": case.get("scenario", ""),
                "expected_status": case["expected_status"],
                "actual_status": status,
                "latency_ms": round(latency_ms, 2),
                "status_ok": status_ok,
                "semantic_ok": semantic_ok,
                "recall_at_k": None if recall is None else round(recall, 4),
                "reciprocal_rank": None if reciprocal_rank is None else round(reciprocal_rank, 4),
                "expected_ids": sorted(expected_ids),
                "found_ids": sorted(found),
                "returned_ids": returned_ids,
                "error": response.get("error") if status == 0 else None,
            }
        )

    latencies = [row["latency_ms"] for row in rows]
    exact_passes = sum(row["status_ok"] and row["semantic_ok"] for row in rows)
    report = {
        "suite": str(args.suite),
        "base_url": args.base_url,
        "top_k": args.top_k,
        "summary": {
            "cases": len(rows),
            "exact_pass_rate": round(exact_passes / len(rows), 4),
            "status_pass_rate": round(sum(row["status_ok"] for row in rows) / len(rows), 4),
            "hit_rate_at_k": round(hit_cases / len(recalls), 4) if recalls else None,
            "mean_recall_at_k": round(sum(recalls) / len(recalls), 4) if recalls else None,
            "mrr_at_k": round(sum(reciprocal_ranks) / len(reciprocal_ranks), 4)
            if reciprocal_ranks
            else None,
            "latency_ms": {
                "p50": percentile(latencies, 0.50),
                "p95": percentile(latencies, 0.95),
                "p99": percentile(latencies, 0.99),
            },
            "statuses": dict(sorted(Counter(row["actual_status"] for row in rows).items())),
        },
        "cases": rows,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if exact_passes == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
