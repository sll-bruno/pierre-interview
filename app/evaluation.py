"""Labelled-search evaluation helpers used by the API and the web dashboard."""

from __future__ import annotations

import json
import math
import time
from collections import Counter
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.models import SearchFilters
from app.search import TransactionSearch


# Curated examples for the demo UI. The full golden set remains untouched and
# continues to be available to the API/CLI for engineering evaluation.
SHOWCASE_CASES: tuple[dict[str, Any], ...] = (
    {
        "id": "showcase-delivery-high-value",
        "label": "Categoria + valor",
        "scenario": "Delivery de comida acima de R$ 100",
        "query": "Delivery de comida acima de 100 reais",
        "filters": {},
        "expected_status": 200,
        "relevant_ids": ["tx_0005", "tx_0007", "tx_0201", "tx_0202", "tx_0239", "tx_0249"],
    },
    {
        "id": "showcase-carrefour-typo",
        "label": "Tolerância a typo",
        "scenario": "Carrefur deve encontrar Carrefour",
        "query": "compras no Carrefur",
        "filters": {},
        "expected_status": 200,
        "relevant_ids": ["tx_0003", "tx_0004", "tx_0015", "tx_0129", "tx_0143", "tx_0161", "tx_0237"],
    },
    {
        "id": "showcase-netflix",
        "label": "Recorrência",
        "scenario": "Assinaturas de streaming da Netflix",
        "query": "Netflix",
        "filters": {},
        "expected_status": 200,
        "relevant_ids": ["tx_0019", "tx_0029", "tx_0042", "tx_0065", "tx_0113", "tx_0149", "tx_0150", "tx_0196"],
    },
    {
        "id": "showcase-uber-filters",
        "label": "Filtros compostos",
        "scenario": "Uber em uma data e faixa de valor específicas",
        "query": "Uber",
        "filters": {
            "date_from": "2026-07-10",
            "date_to": "2026-07-10",
            "min_amount_brl": 40,
            "max_amount_brl": 60,
        },
        "expected_status": 200,
        "relevant_ids": ["tx_0241"],
    },
    {
        "id": "showcase-cemig",
        "label": "Conta essencial",
        "scenario": "Pagamentos de energia elétrica da Cemig",
        "query": "Cemig",
        "filters": {},
        "expected_status": 200,
        "relevant_ids": ["tx_0024", "tx_0121", "tx_0138", "tx_0140", "tx_0162", "tx_0193", "tx_0211", "tx_0231"],
    },
    {
        "id": "showcase-empty",
        "label": "Resposta honesta",
        "scenario": "Uma consulta fora do período deve retornar vazio",
        "query": "compras no futuro",
        "filters": {"date_from": "2030-01-01", "date_to": "2030-01-31"},
        "expected_status": 200,
        "relevant_ids": [],
    },
)


def load_cases(path: Path) -> list[dict[str, Any]]:
    required = {"id", "query", "filters", "expected_status", "relevant_ids"}
    cases: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        case = json.loads(line)
        missing = required - set(case)
        if missing:
            raise ValueError(f"{path}:{line_number}: campos ausentes: {sorted(missing)}")
        cases.append(case)
    if not cases:
        raise ValueError(f"Suite vazia: {path}")
    return cases


def _percentile(values: list[float], point: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * point) - 1)
    return round(ordered[index], 2)


def status(engine: TransactionSearch | None, suite_path: Path) -> dict[str, Any]:
    try:
        cases = load_cases(suite_path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return {"available": False, "reason": f"Suite de avaliação indisponível: {error}"}
    if engine is None:
        return {
            "available": False,
            "reason": "O índice semântico não está disponível.",
            "case_count": len(cases),
        }
    corpus_ids = {str(value) for value in engine.frame["transaction_id"]}
    labelled_ids = {identifier for case in cases for identifier in case["relevant_ids"]}
    missing = labelled_ids - corpus_ids
    if missing:
        return {
            "available": False,
            "reason": "O índice ativo não corresponde ao corpus rotulado de avaliação.",
            "case_count": len(cases),
            "missing_transaction_count": len(missing),
        }
    return {
        "available": True,
        "case_count": len(cases),
        "load_case_count": sum("load" in case.get("tags", []) for case in cases),
    }


def public_cases(suite_path: Path, tag: str) -> list[dict[str, Any]]:
    return [
        {"id": case["id"], "query": case["query"], "filters": case["filters"]}
        for case in load_cases(suite_path)
        if tag in case.get("tags", [])
    ]


def showcase_cases(engine: TransactionSearch) -> list[dict[str, Any]]:
    """Return the six labelled cases shown in the demo UI with ground truth."""
    rows_by_id = engine.frame.set_index("transaction_id", drop=False)
    cases: list[dict[str, Any]] = []
    for case in SHOWCASE_CASES:
        expected_ids = case["relevant_ids"]
        missing = set(expected_ids) - set(rows_by_id.index)
        if missing:
            raise RuntimeError(
                "O índice ativo não contém todos os rótulos da demonstração."
            )
        transactions = []
        for transaction_id in expected_ids:
            row = rows_by_id.loc[transaction_id]
            transactions.append(
                {
                    "transaction_id": str(row.transaction_id),
                    "merchant": str(row.merchant),
                    "description": str(row.description),
                    "amount_brl": float(row.amount_brl),
                    "category": str(row.category),
                }
            )
        cases.append(
            {
                "id": case["id"],
                "label": case["label"],
                "scenario": case["scenario"],
                "query": case["query"],
                "filters": case["filters"],
                "expected_status": case["expected_status"],
                "ground_truth": {"transactions": transactions},
            }
        )
    return cases


async def run_quality(
    engine: TransactionSearch, suite_path: Path, top_k: int
) -> dict[str, Any]:
    """Run the golden set through the active engine and aggregate quality metrics."""
    cases = load_cases(suite_path)
    rows: list[dict[str, Any]] = []
    recalls: list[float] = []
    reciprocal_ranks: list[float] = []
    hit_cases = 0

    for case in cases:
        expected_ids = set(case["relevant_ids"])
        started = time.perf_counter()
        try:
            response = await engine.search(
                str(case["query"]), SearchFilters.model_validate(case["filters"])
            )
            actual_status = 200
            returned_ids = response.transaction_ids[:top_k]
        except HTTPException as error:
            actual_status = error.status_code
            returned_ids = []
        latency_ms = (time.perf_counter() - started) * 1000

        found = expected_ids & set(returned_ids)
        status_ok = actual_status == case["expected_status"]
        if expected_ids:
            recall = len(found) / len(expected_ids)
            first_rank = next(
                (index + 1 for index, identifier in enumerate(returned_ids) if identifier in expected_ids),
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
            semantic_ok = actual_status == 200 and not returned_ids
        else:
            recall = None
            reciprocal_rank = None
            semantic_ok = True
        rows.append(
            {
                "id": case["id"],
                "scenario": case.get("scenario", ""),
                "expected_status": case["expected_status"],
                "actual_status": actual_status,
                "status_ok": status_ok,
                "semantic_ok": semantic_ok,
                "recall_at_k": None if recall is None else round(recall, 4),
                "returned_ids": returned_ids,
                "found_ids": sorted(found),
                "latency_ms": round(latency_ms, 2),
            }
        )

    # The engine calls are deliberately measured outside HTTP serialization. The
    # browser load test complements this with end-to-end HTTP latency.
    quality_rows = [row for row in rows if row["expected_status"] == 200]
    latencies = [row["latency_ms"] for row in rows]
    exact_passes = sum(row["status_ok"] and row["semantic_ok"] for row in rows)
    return {
        "top_k": top_k,
        "summary": {
            "cases": len(rows),
            "exact_pass_rate": round(exact_passes / len(rows), 4),
            "status_pass_rate": round(sum(row["status_ok"] for row in rows) / len(rows), 4),
            "hit_rate_at_k": round(hit_cases / len(recalls), 4) if recalls else None,
            "mean_recall_at_k": round(sum(recalls) / len(recalls), 4) if recalls else None,
            "mrr_at_k": round(sum(reciprocal_ranks) / len(reciprocal_ranks), 4)
            if reciprocal_ranks
            else None,
            "statuses": dict(sorted(Counter(row["actual_status"] for row in rows).items())),
            "evaluated_search_cases": len(quality_rows),
            "latency_ms": {
                "p50": _percentile(latencies, 0.50),
                "p95": _percentile(latencies, 0.95),
                "p99": _percentile(latencies, 0.99),
            },
        },
        "cases": rows,
    }
