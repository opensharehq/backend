#!/usr/bin/env python3
"""Validate line and branch coverage thresholds from a coverage JSON report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Check line and branch coverage thresholds using `coverage json` output."
        )
    )
    parser.add_argument(
        "report_path",
        nargs="?",
        default="coverage.json",
        help="Path to the coverage JSON report (default: coverage.json).",
    )
    parser.add_argument(
        "--line-threshold",
        type=float,
        default=95.0,
        help="Minimum allowed line coverage percentage.",
    )
    parser.add_argument(
        "--branch-threshold",
        type=float,
        default=85.0,
        help="Minimum allowed branch coverage percentage.",
    )
    return parser


def _load_totals(report_path: Path) -> dict:
    data = json.loads(report_path.read_text(encoding="utf-8"))
    totals = data.get("totals")
    if not isinstance(totals, dict):
        msg = f"Coverage report at {report_path} is missing a totals section."
        raise ValueError(msg)
    return totals


def _calculate_percentage(covered: int, total: int) -> float:
    if total == 0:
        return 100.0
    return covered / total * 100


def _require_metric(totals: dict, key: str) -> int:
    if key not in totals:
        msg = f"Coverage report is missing required metric: {key}"
        raise ValueError(msg)
    return int(totals[key])


def main(argv: list[str] | None = None) -> int:
    """Run the coverage gate against a JSON report and return an exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        totals = _load_totals(Path(args.report_path))
        covered_lines = _require_metric(totals, "covered_lines")
        total_lines = _require_metric(totals, "num_statements")
        covered_branches = _require_metric(totals, "covered_branches")
        total_branches = _require_metric(totals, "num_branches")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"Coverage gate error: {exc}\n")
        return 1

    line_percent = _calculate_percentage(covered_lines, total_lines)
    branch_percent = _calculate_percentage(covered_branches, total_branches)

    failures = []
    if line_percent < args.line_threshold:
        failures.append(
            "line coverage "
            f"{line_percent:.2f}% is below threshold {args.line_threshold:.2f}%"
        )
    if branch_percent < args.branch_threshold:
        failures.append(
            "branch coverage "
            f"{branch_percent:.2f}% is below threshold {args.branch_threshold:.2f}%"
        )

    sys.stdout.write(
        "Coverage summary: "
        f"line={line_percent:.2f}% ({covered_lines}/{total_lines}), "
        f"branch={branch_percent:.2f}% ({covered_branches}/{total_branches})\n"
    )
    if failures:
        for failure in failures:
            sys.stderr.write(f"Coverage gate failed: {failure}\n")
        return 1

    sys.stdout.write(
        "Coverage gate passed: "
        f"line>={args.line_threshold:.2f}% and "
        f"branch>={args.branch_threshold:.2f}%\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
