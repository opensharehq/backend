"""Reusable helpers for repeatable HTTP load tests."""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests


@dataclass(frozen=True)
class RequestSpec:
    """Describe one HTTP request shape inside a load-test scenario."""

    name: str
    path: str
    method: str = "GET"
    expected_statuses: tuple[int, ...] = (200,)
    data: dict[str, Any] | None = None


@dataclass(frozen=True)
class RequestResult:
    """Capture the outcome of a single HTTP request."""

    name: str
    elapsed_ms: float
    ok: bool
    status_code: int | None = None
    error: str | None = None


@dataclass(frozen=True)
class LoadTestSummary:
    """Aggregate metrics emitted by a load-test run."""

    base_url: str
    scenario_name: str
    concurrency: int
    elapsed_seconds: float
    total_requests: int
    successful_requests: int
    failed_requests: int
    error_rate: float
    throughput_rps: float
    average_latency_ms: float
    p95_latency_ms: float
    slowest_latency_ms: float
    per_endpoint: dict[str, dict[str, float | int]]
    failure_reasons: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation of the summary."""
        return {
            "base_url": self.base_url,
            "scenario_name": self.scenario_name,
            "concurrency": self.concurrency,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "error_rate": round(self.error_rate, 3),
            "throughput_rps": round(self.throughput_rps, 3),
            "average_latency_ms": round(self.average_latency_ms, 3),
            "p95_latency_ms": round(self.p95_latency_ms, 3),
            "slowest_latency_ms": round(self.slowest_latency_ms, 3),
            "per_endpoint": {
                name: {
                    metric_name: round(metric_value, 3)
                    if isinstance(metric_value, float)
                    else metric_value
                    for metric_name, metric_value in metrics.items()
                }
                for name, metrics in self.per_endpoint.items()
            },
            "failure_reasons": self.failure_reasons,
        }


DEFAULT_SCENARIOS: dict[str, tuple[RequestSpec, ...]] = {
    "anonymous-browse": (
        RequestSpec(name="homepage", path="/"),
        RequestSpec(name="sign-in", path="/accounts/login/"),
        RequestSpec(name="search", path="/search/?q=open"),
    ),
}


def resolve_scenario(name: str) -> tuple[RequestSpec, ...]:
    """Return the configured request sequence for the named scenario."""
    try:
        return DEFAULT_SCENARIOS[name]
    except KeyError as exc:  # pragma: no cover - argparse enforces choices in CLI.
        available = ", ".join(sorted(DEFAULT_SCENARIOS))
        msg = f"Unknown scenario '{name}'. Available scenarios: {available}"
        raise ValueError(msg) from exc


def execute_request(
    session: requests.Session,
    *,
    base_url: str,
    spec: RequestSpec,
    timeout_seconds: float,
    timer=time.perf_counter,
) -> RequestResult:
    """Execute one request and normalize success/failure bookkeeping."""
    started_at = timer()
    try:
        response = session.request(
            spec.method,
            urljoin(base_url, spec.path),
            allow_redirects=True,
            timeout=timeout_seconds,
            data=spec.data,
        )
    except requests.RequestException as exc:
        elapsed_ms = (timer() - started_at) * 1000
        return RequestResult(
            name=spec.name,
            elapsed_ms=elapsed_ms,
            ok=False,
            error=exc.__class__.__name__,
        )

    elapsed_ms = (timer() - started_at) * 1000
    ok = response.status_code in spec.expected_statuses
    error = None if ok else f"unexpected_status:{response.status_code}"
    return RequestResult(
        name=spec.name,
        elapsed_ms=elapsed_ms,
        ok=ok,
        status_code=response.status_code,
        error=error,
    )


def summarize_results(
    *,
    base_url: str,
    scenario_name: str,
    concurrency: int,
    elapsed_seconds: float,
    results: list[RequestResult],
) -> LoadTestSummary:
    """Roll up request-level observations into human-friendly metrics."""
    total_requests = len(results)
    successful_requests = sum(1 for result in results if result.ok)
    failed_requests = total_requests - successful_requests
    latencies = [result.elapsed_ms for result in results]
    error_rate = failed_requests / total_requests * 100 if total_requests else 0.0
    throughput_rps = total_requests / elapsed_seconds if elapsed_seconds else 0.0
    average_latency_ms = sum(latencies) / total_requests if total_requests else 0.0
    p95_latency_ms = _percentile(latencies, 95)
    slowest_latency_ms = max(latencies, default=0.0)

    endpoint_buckets: dict[str, list[RequestResult]] = {}
    failure_reasons: dict[str, int] = {}
    for result in results:
        endpoint_buckets.setdefault(result.name, []).append(result)
        if result.error:
            failure_reasons[result.error] = failure_reasons.get(result.error, 0) + 1

    per_endpoint: dict[str, dict[str, float | int]] = {}
    for endpoint_name, endpoint_results in endpoint_buckets.items():
        endpoint_latencies = [result.elapsed_ms for result in endpoint_results]
        endpoint_total = len(endpoint_results)
        endpoint_failed = sum(1 for result in endpoint_results if not result.ok)
        endpoint_successful = endpoint_total - endpoint_failed
        per_endpoint[endpoint_name] = {
            "total": endpoint_total,
            "ok": endpoint_successful,
            "failed": endpoint_failed,
            "average_latency_ms": (
                sum(endpoint_latencies) / endpoint_total if endpoint_total else 0.0
            ),
            "p95_latency_ms": _percentile(endpoint_latencies, 95),
            "slowest_latency_ms": max(endpoint_latencies, default=0.0),
        }

    return LoadTestSummary(
        base_url=base_url,
        scenario_name=scenario_name,
        concurrency=concurrency,
        elapsed_seconds=elapsed_seconds,
        total_requests=total_requests,
        successful_requests=successful_requests,
        failed_requests=failed_requests,
        error_rate=error_rate,
        throughput_rps=throughput_rps,
        average_latency_ms=average_latency_ms,
        p95_latency_ms=p95_latency_ms,
        slowest_latency_ms=slowest_latency_ms,
        per_endpoint=per_endpoint,
        failure_reasons=failure_reasons,
    )


def run_load_test(  # noqa: PLR0913 - orchestration boundary mirrors CLI knobs.
    *,
    base_url: str,
    scenario_name: str,
    request_specs: tuple[RequestSpec, ...],
    concurrency: int,
    timeout_seconds: float,
    duration_seconds: int | None = None,
    total_requests: int | None = None,
    session_factory=requests.Session,
    clock=time.monotonic,
    timer=time.perf_counter,
) -> LoadTestSummary:
    """Execute a load test either for a duration or a fixed number of requests."""
    if concurrency < 1:
        msg = "concurrency must be at least 1"
        raise ValueError(msg)
    if not request_specs:
        msg = "at least one request spec is required"
        raise ValueError(msg)
    if total_requests is None and (duration_seconds is None or duration_seconds < 1):
        msg = "either total_requests or a positive duration_seconds must be provided"
        raise ValueError(msg)
    if total_requests is not None and total_requests < 1:
        msg = "total_requests must be at least 1"
        raise ValueError(msg)

    started_at = clock()
    results: list[RequestResult] = []

    if total_requests is not None:
        worker_count = min(concurrency, total_requests)

        def run_fixed_worker(worker_id: int) -> list[RequestResult]:
            session = session_factory()
            worker_results: list[RequestResult] = []
            try:
                for request_index in range(worker_id, total_requests, worker_count):
                    spec = request_specs[request_index % len(request_specs)]
                    worker_results.append(
                        execute_request(
                            session,
                            base_url=base_url,
                            spec=spec,
                            timeout_seconds=timeout_seconds,
                            timer=timer,
                        )
                    )
            finally:
                _close_session(session)
            return worker_results

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = [
                executor.submit(run_fixed_worker, worker_id)
                for worker_id in range(worker_count)
            ]
            for future in futures:
                results.extend(future.result())
    else:
        deadline = started_at + duration_seconds

        def run_duration_worker(worker_id: int) -> list[RequestResult]:
            session = session_factory()
            worker_results: list[RequestResult] = []
            spec_index = worker_id % len(request_specs)
            try:
                while clock() < deadline:
                    spec = request_specs[spec_index]
                    worker_results.append(
                        execute_request(
                            session,
                            base_url=base_url,
                            spec=spec,
                            timeout_seconds=timeout_seconds,
                            timer=timer,
                        )
                    )
                    spec_index = (spec_index + 1) % len(request_specs)
            finally:
                _close_session(session)
            return worker_results

        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [
                executor.submit(run_duration_worker, worker_id)
                for worker_id in range(concurrency)
            ]
            for future in futures:
                results.extend(future.result())

    elapsed_seconds = max(clock() - started_at, 0.001)
    return summarize_results(
        base_url=base_url,
        scenario_name=scenario_name,
        concurrency=concurrency,
        elapsed_seconds=elapsed_seconds,
        results=results,
    )


def evaluate_thresholds(
    summary: LoadTestSummary,
    *,
    max_error_rate: float,
    p95_ms: float,
) -> list[str]:
    """Return human-readable threshold failures for the completed run."""
    failures = []
    if summary.error_rate > max_error_rate:
        failures.append(
            "error rate "
            f"{summary.error_rate:.2f}% exceeded budget {max_error_rate:.2f}%"
        )
    if summary.p95_latency_ms > p95_ms:
        failures.append(
            f"p95 latency {summary.p95_latency_ms:.2f}ms exceeded budget {p95_ms:.2f}ms"
        )
    return failures


def format_summary(summary: LoadTestSummary, failures: list[str]) -> str:
    """Render a concise CLI summary for humans."""
    lines = [
        (f"Load test scenario '{summary.scenario_name}' against {summary.base_url}"),
        (
            "summary: "
            f"requests={summary.total_requests}, "
            f"ok={summary.successful_requests}, "
            f"failed={summary.failed_requests}, "
            f"error_rate={summary.error_rate:.2f}%, "
            f"throughput={summary.throughput_rps:.2f} req/s, "
            f"avg={summary.average_latency_ms:.2f}ms, "
            f"p95={summary.p95_latency_ms:.2f}ms, "
            f"max={summary.slowest_latency_ms:.2f}ms, "
            f"elapsed={summary.elapsed_seconds:.2f}s"
        ),
        "per-endpoint:",
    ]
    for endpoint_name in sorted(summary.per_endpoint):
        endpoint = summary.per_endpoint[endpoint_name]
        lines.append(
            "  "
            f"{endpoint_name}: total={endpoint['total']}, "
            f"ok={endpoint['ok']}, failed={endpoint['failed']}, "
            f"avg={endpoint['average_latency_ms']:.2f}ms, "
            f"p95={endpoint['p95_latency_ms']:.2f}ms, "
            f"max={endpoint['slowest_latency_ms']:.2f}ms"
        )
    if summary.failure_reasons:
        lines.append(
            "failure-reasons: "
            + ", ".join(
                f"{reason}={count}"
                for reason, count in sorted(summary.failure_reasons.items())
            )
        )
    if failures:
        lines.extend(f"threshold-failure: {failure}" for failure in failures)
    else:
        lines.append("thresholds: passed")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Run the configured load test from CLI arguments."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    request_specs = resolve_scenario(args.scenario)
    summary = run_load_test(
        base_url=args.base_url,
        scenario_name=args.scenario,
        request_specs=request_specs,
        concurrency=args.concurrency,
        duration_seconds=args.duration,
        total_requests=args.total_requests,
        timeout_seconds=args.timeout,
    )
    failures = evaluate_thresholds(
        summary,
        max_error_rate=args.max_error_rate,
        p95_ms=args.p95_ms,
    )

    payload = summary.to_dict() | {"threshold_failures": failures}
    if args.json_output:
        output_path = Path(args.json_output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    sys.stdout.write(format_summary(summary, failures) + "\n")
    return 1 if failures else 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a lightweight HTTP load test against a running OpenShare site."
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="Base URL for the running OpenShare instance.",
    )
    parser.add_argument(
        "--scenario",
        choices=sorted(DEFAULT_SCENARIOS),
        default="anonymous-browse",
        help="Named request scenario to execute.",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=20,
        help="Number of concurrent workers to run.",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=30,
        help="Run duration in seconds when --total-requests is not supplied.",
    )
    parser.add_argument(
        "--total-requests",
        type=int,
        default=None,
        help="Optional fixed request budget for deterministic dry runs.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="Per-request timeout in seconds.",
    )
    parser.add_argument(
        "--max-error-rate",
        type=float,
        default=1.0,
        help="Maximum allowed error rate as a percentage.",
    )
    parser.add_argument(
        "--p95-ms",
        type=float,
        default=750.0,
        help="Maximum allowed p95 latency in milliseconds.",
    )
    parser.add_argument(
        "--json-output",
        default="",
        help="Optional path for writing a JSON summary.",
    )
    return parser


def _close_session(session: Any) -> None:
    close = getattr(session, "close", None)
    if callable(close):
        close()


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    rank = math.ceil((percentile / 100) * len(sorted_values))
    return sorted_values[max(rank - 1, 0)]
