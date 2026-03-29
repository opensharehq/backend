"""Tests for the lightweight load-testing helpers."""

from __future__ import annotations

import io
import json
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import requests
from django.test import SimpleTestCase

from common.load_testing import (
    LoadTestSummary,
    RequestResult,
    RequestSpec,
    _close_session,
    _percentile,
    evaluate_thresholds,
    execute_request,
    format_summary,
    main,
    resolve_scenario,
    run_load_test,
    summarize_results,
)


class FakeResponse:
    """Minimal response object for exercising request helpers."""

    def __init__(self, status_code: int):
        self.status_code = status_code


class FakeSession:
    """Simple session stub that returns canned status codes."""

    def __init__(self, scripted_outcomes):
        self.scripted_outcomes = list(scripted_outcomes)
        self.calls: list[tuple[str, str, float]] = []
        self.closed = False

    def request(self, method, url, allow_redirects, timeout, data=None):
        self.calls.append((method, url, timeout))
        outcome = self.scripted_outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return FakeResponse(outcome)

    def close(self):
        self.closed = True


class LoadTestingHelpersTests(SimpleTestCase):
    """Cover the reusable request execution and reporting helpers."""

    def test_resolve_scenario_returns_known_anonymous_browse_requests(self):
        scenario = resolve_scenario("anonymous-browse")

        self.assertEqual(
            [request.name for request in scenario], ["homepage", "sign-in", "search"]
        )
        self.assertEqual(
            [request.path for request in scenario],
            ["/", "/accounts/login/", "/search/?q=open"],
        )

    def test_execute_request_marks_expected_status_as_success(self):
        session = FakeSession([200])
        timer = iter([10.0, 10.05]).__next__

        result = execute_request(
            session,
            base_url="http://example.com",
            spec=RequestSpec(name="homepage", path="/"),
            timeout_seconds=3,
            timer=timer,
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.status_code, 200)
        self.assertIsNone(result.error)
        self.assertAlmostEqual(result.elapsed_ms, 50.0)
        self.assertEqual(session.calls, [("GET", "http://example.com/", 3)])

    def test_execute_request_records_transport_errors(self):
        session = FakeSession([requests.Timeout("boom")])
        timer = iter([20.0, 20.02]).__next__

        result = execute_request(
            session,
            base_url="http://example.com",
            spec=RequestSpec(name="search", path="/search/?q=open"),
            timeout_seconds=2,
            timer=timer,
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "Timeout")
        self.assertIsNone(result.status_code)
        self.assertAlmostEqual(result.elapsed_ms, 20.0)

    def test_summarize_results_rolls_up_global_and_endpoint_metrics(self):
        summary = summarize_results(
            base_url="http://example.com",
            scenario_name="anonymous-browse",
            concurrency=4,
            elapsed_seconds=2.0,
            results=[
                RequestResult("homepage", 100.0, True, status_code=200),
                RequestResult(
                    "homepage",
                    300.0,
                    False,
                    status_code=500,
                    error="unexpected_status:500",
                ),
                RequestResult("sign-in", 50.0, True, status_code=200),
            ],
        )

        self.assertEqual(summary.total_requests, 3)
        self.assertEqual(summary.successful_requests, 2)
        self.assertEqual(summary.failed_requests, 1)
        self.assertAlmostEqual(summary.error_rate, 33.3333333333)
        self.assertAlmostEqual(summary.throughput_rps, 1.5)
        self.assertEqual(summary.p95_latency_ms, 300.0)
        self.assertEqual(summary.failure_reasons, {"unexpected_status:500": 1})
        self.assertEqual(summary.per_endpoint["homepage"]["failed"], 1)
        self.assertEqual(summary.per_endpoint["sign-in"]["ok"], 1)

    def test_run_load_test_executes_fixed_request_budget_and_closes_sessions(self):
        sessions: list[FakeSession] = []

        def session_factory():
            session = FakeSession([200, 200, 200])
            sessions.append(session)
            return session

        timer = iter([0.0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07]).__next__
        clock = iter([100.0, 101.0]).__next__
        summary = run_load_test(
            base_url="http://example.com",
            scenario_name="anonymous-browse",
            request_specs=(
                RequestSpec(name="homepage", path="/"),
                RequestSpec(name="sign-in", path="/accounts/login/"),
            ),
            concurrency=2,
            total_requests=4,
            timeout_seconds=5,
            session_factory=session_factory,
            clock=clock,
            timer=timer,
        )

        self.assertEqual(summary.total_requests, 4)
        self.assertEqual(summary.successful_requests, 4)
        self.assertEqual(summary.failed_requests, 0)
        self.assertEqual(summary.per_endpoint["homepage"]["total"], 2)
        self.assertEqual(summary.per_endpoint["sign-in"]["total"], 2)
        self.assertTrue(all(session.closed for session in sessions))

    def test_run_load_test_rejects_invalid_arguments(self):
        request_specs = (RequestSpec(name="homepage", path="/"),)

        cases = [
            (
                {
                    "request_specs": request_specs,
                    "concurrency": 0,
                    "duration_seconds": 1,
                    "total_requests": None,
                },
                "concurrency must be at least 1",
            ),
            (
                {
                    "request_specs": (),
                    "concurrency": 1,
                    "duration_seconds": 1,
                    "total_requests": None,
                },
                "at least one request spec is required",
            ),
            (
                {
                    "request_specs": request_specs,
                    "concurrency": 1,
                    "duration_seconds": None,
                    "total_requests": None,
                },
                "either total_requests or a positive duration_seconds must be provided",
            ),
            (
                {
                    "request_specs": request_specs,
                    "concurrency": 1,
                    "duration_seconds": 1,
                    "total_requests": 0,
                },
                "total_requests must be at least 1",
            ),
        ]

        for kwargs, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesMessage(ValueError, message):
                    run_load_test(
                        base_url="http://example.com",
                        scenario_name="anonymous-browse",
                        timeout_seconds=5,
                        **kwargs,
                    )

    def test_run_load_test_duration_mode_executes_requests_and_closes_sessions(self):
        sessions: list[FakeSession] = []

        def session_factory():
            session = FakeSession([200, 200, 200, 200])
            sessions.append(session)
            return session

        timer = iter([0.0, 0.01, 0.02, 0.03, 0.04, 0.05]).__next__
        clock = iter([100.0, 100.1, 100.2, 100.3, 101.0, 101.2]).__next__

        summary = run_load_test(
            base_url="http://example.com",
            scenario_name="anonymous-browse",
            request_specs=(
                RequestSpec(name="homepage", path="/"),
                RequestSpec(name="sign-in", path="/accounts/login/"),
            ),
            concurrency=1,
            duration_seconds=1,
            timeout_seconds=5,
            session_factory=session_factory,
            clock=clock,
            timer=timer,
        )

        self.assertEqual(summary.total_requests, 3)
        self.assertEqual(summary.successful_requests, 3)
        self.assertEqual(summary.per_endpoint["homepage"]["total"], 2)
        self.assertEqual(summary.per_endpoint["sign-in"]["total"], 1)
        self.assertTrue(all(session.closed for session in sessions))

    def test_run_load_test_duration_mode_supports_zero_iterations(self):
        sessions: list[FakeSession] = []

        def session_factory():
            session = FakeSession([])
            sessions.append(session)
            return session

        clock = iter([100.0, 101.0, 101.1]).__next__

        summary = run_load_test(
            base_url="http://example.com",
            scenario_name="anonymous-browse",
            request_specs=(RequestSpec(name="homepage", path="/"),),
            concurrency=1,
            duration_seconds=1,
            timeout_seconds=5,
            session_factory=session_factory,
            clock=clock,
        )

        self.assertEqual(summary.total_requests, 0)
        self.assertEqual(summary.failed_requests, 0)
        self.assertEqual(summary.per_endpoint, {})
        self.assertTrue(all(session.closed for session in sessions))

    def test_evaluate_thresholds_reports_latency_and_error_budget_breaches(self):
        summary = LoadTestSummary(
            base_url="http://example.com",
            scenario_name="anonymous-browse",
            concurrency=10,
            elapsed_seconds=5.0,
            total_requests=100,
            successful_requests=96,
            failed_requests=4,
            error_rate=4.0,
            throughput_rps=20.0,
            average_latency_ms=100.0,
            p95_latency_ms=900.0,
            slowest_latency_ms=1200.0,
            per_endpoint={},
            failure_reasons={},
        )

        failures = evaluate_thresholds(
            summary,
            max_error_rate=1.0,
            p95_ms=750.0,
        )

        self.assertEqual(
            failures,
            [
                "error rate 4.00% exceeded budget 1.00%",
                "p95 latency 900.00ms exceeded budget 750.00ms",
            ],
        )

    def test_evaluate_thresholds_returns_empty_when_summary_is_within_budget(self):
        summary = LoadTestSummary(
            base_url="http://example.com",
            scenario_name="anonymous-browse",
            concurrency=2,
            elapsed_seconds=1.0,
            total_requests=3,
            successful_requests=3,
            failed_requests=0,
            error_rate=0.0,
            throughput_rps=3.0,
            average_latency_ms=50.0,
            p95_latency_ms=60.0,
            slowest_latency_ms=60.0,
            per_endpoint={},
            failure_reasons={},
        )

        self.assertEqual(
            evaluate_thresholds(summary, max_error_rate=1.0, p95_ms=750.0),
            [],
        )

    def test_format_summary_reports_passed_thresholds_when_no_failures(self):
        summary = LoadTestSummary(
            base_url="http://example.com",
            scenario_name="anonymous-browse",
            concurrency=1,
            elapsed_seconds=1.0,
            total_requests=1,
            successful_requests=1,
            failed_requests=0,
            error_rate=0.0,
            throughput_rps=1.0,
            average_latency_ms=10.0,
            p95_latency_ms=10.0,
            slowest_latency_ms=10.0,
            per_endpoint={
                "homepage": {
                    "total": 1,
                    "ok": 1,
                    "failed": 0,
                    "average_latency_ms": 10.0,
                    "p95_latency_ms": 10.0,
                    "slowest_latency_ms": 10.0,
                }
            },
            failure_reasons={},
        )

        rendered = format_summary(summary, failures=[])

        self.assertIn("thresholds: passed", rendered)
        self.assertNotIn("failure-reasons:", rendered)

    def test_main_writes_json_summary_and_returns_non_zero_on_threshold_failure(self):
        summary = LoadTestSummary(
            base_url="http://example.com",
            scenario_name="anonymous-browse",
            concurrency=2,
            elapsed_seconds=1.0,
            total_requests=5,
            successful_requests=4,
            failed_requests=1,
            error_rate=20.0,
            throughput_rps=5.0,
            average_latency_ms=100.0,
            p95_latency_ms=100.0,
            slowest_latency_ms=120.0,
            per_endpoint={
                "homepage": {
                    "total": 5,
                    "ok": 4,
                    "failed": 1,
                    "average_latency_ms": 100.0,
                    "p95_latency_ms": 100.0,
                    "slowest_latency_ms": 120.0,
                }
            },
            failure_reasons={"unexpected_status:500": 1},
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "summary.json"
            buffer = io.StringIO()
            with (
                patch("common.load_testing.run_load_test", return_value=summary),
                redirect_stdout(buffer),
            ):
                exit_code = main(
                    [
                        "--base-url",
                        "http://example.com",
                        "--scenario",
                        "anonymous-browse",
                        "--total-requests",
                        "5",
                        "--max-error-rate",
                        "1",
                        "--json-output",
                        str(output_path),
                    ]
                )

            self.assertEqual(exit_code, 1)
            written = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(written["scenario_name"], "anonymous-browse")
            self.assertEqual(
                written["threshold_failures"],
                ["error rate 20.00% exceeded budget 1.00%"],
            )
            self.assertIn("threshold-failure", buffer.getvalue())

    def test_main_returns_zero_without_json_output_when_thresholds_pass(self):
        summary = LoadTestSummary(
            base_url="http://example.com",
            scenario_name="anonymous-browse",
            concurrency=1,
            elapsed_seconds=1.0,
            total_requests=1,
            successful_requests=1,
            failed_requests=0,
            error_rate=0.0,
            throughput_rps=1.0,
            average_latency_ms=10.0,
            p95_latency_ms=10.0,
            slowest_latency_ms=10.0,
            per_endpoint={
                "homepage": {
                    "total": 1,
                    "ok": 1,
                    "failed": 0,
                    "average_latency_ms": 10.0,
                    "p95_latency_ms": 10.0,
                    "slowest_latency_ms": 10.0,
                }
            },
            failure_reasons={},
        )

        buffer = io.StringIO()
        with (
            patch("common.load_testing.run_load_test", return_value=summary),
            redirect_stdout(buffer),
        ):
            exit_code = main(
                [
                    "--base-url",
                    "http://example.com",
                    "--scenario",
                    "anonymous-browse",
                    "--total-requests",
                    "1",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("thresholds: passed", buffer.getvalue())

    def test_close_session_ignores_non_callable_close_attribute(self):
        session = type("SessionWithoutCallableClose", (), {"close": 123})()

        _close_session(session)

    def test_percentile_returns_zero_for_empty_values(self):
        self.assertEqual(_percentile([], 95), 0.0)
