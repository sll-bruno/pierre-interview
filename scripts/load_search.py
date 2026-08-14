"""Send concurrent, repeatable requests to a running Pierre API."""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_SUITE = Path("data/evaluation/queries.jsonl")


def load_cases(path: Path, tags: set[str]) -> list[dict[str, Any]]:
    cases = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    selected = [case for case in cases if tags & set(case.get("tags", []))]
    if not selected:
        raise ValueError(f"Nenhum caso com as tags {sorted(tags)} em {path}")
    return selected


def send(base_url: str, case: dict[str, Any], timeout: float) -> tuple[int, float, str | None]:
    body = json.dumps({"query": case["query"], "filters": case["filters"]}).encode()
    request = Request(
        f"{base_url.rstrip('/')}/search",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=timeout) as response:
            response.read()
            return response.status, (time.perf_counter() - started) * 1000, None
    except HTTPError as error:
        error.read()
        return error.code, (time.perf_counter() - started) * 1000, None
    except (URLError, TimeoutError) as error:
        return 0, (time.perf_counter() - started) * 1000, str(error)


def percentile(values: list[float], point: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(len(ordered) * point) - 1)], 2)


def main() -> int:
    parser = argparse.ArgumentParser(description="Teste de carga HTTP para /search")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=45)
    parser.add_argument("--tag", action="append", default=["load"], help="Inclui casos com esta tag; pode repetir")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.requests < 1 or args.concurrency < 1:
        parser.error("--requests e --concurrency devem ser maiores que zero")

    cases = load_cases(args.suite, set(args.tag))
    randomizer = random.Random(args.seed)
    workload = [randomizer.choice(cases) for _ in range(args.requests)]
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        responses = list(pool.map(lambda item: send(args.base_url, item, args.timeout), workload))
    elapsed = time.perf_counter() - started
    statuses = Counter(status for status, _, _ in responses)
    latencies = [latency for _, latency, _ in responses]
    failures = sum(status < 200 or status >= 300 for status, _, _ in responses)
    report = {
        "requests": args.requests,
        "concurrency": args.concurrency,
        "tags": args.tag,
        "elapsed_seconds": round(elapsed, 3),
        "throughput_rps": round(args.requests / elapsed, 3),
        "failure_rate": round(failures / args.requests, 4),
        "statuses": dict(sorted(statuses.items())),
        "latency_ms": {
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "p99": percentile(latencies, 0.99),
            "max": round(max(latencies), 2),
        },
        "transport_errors": sum(error is not None for _, _, error in responses),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
