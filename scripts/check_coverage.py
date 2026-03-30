#!/usr/bin/env python3
"""Validate thresholds and ensure repo-owned source files appear in coverage."""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from fnmatch import fnmatch
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = REPO_ROOT / "pyproject.toml"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Check line and branch coverage thresholds and verify the coverage "
            "report contains every repo-owned source file configured in coverage."
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
    parser.add_argument(
        "--config-path",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to the coverage configuration file (default: pyproject.toml).",
    )
    return parser


def _load_report(report_path: Path) -> dict:
    return json.loads(report_path.read_text(encoding="utf-8"))


def _load_totals(report_path: Path) -> dict:
    data = _load_report(report_path)
    totals = data.get("totals")
    if not isinstance(totals, dict):
        msg = f"Coverage report at {report_path} is missing a totals section."
        raise ValueError(msg)
    return totals


def _load_coverage_run_config(config_path: Path) -> dict:
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    run_config = config.get("tool", {}).get("coverage", {}).get("run", {})
    if not isinstance(run_config, dict):
        msg = f"Coverage config at {config_path} is missing [tool.coverage.run]."
        raise ValueError(msg)
    source_entries = run_config.get("source")
    if not isinstance(source_entries, list) or not source_entries:
        msg = f"Coverage config at {config_path} must declare tool.coverage.run.source."
        raise ValueError(msg)
    return run_config


def _calculate_percentage(covered: int, total: int) -> float:
    if total == 0:
        return 100.0
    return covered / total * 100


def _require_metric(totals: dict, key: str) -> int:
    if key not in totals:
        msg = f"Coverage report is missing required metric: {key}"
        raise ValueError(msg)
    return int(totals[key])


def _normalize_report_path(repo_root: Path, raw_path: str) -> str:
    path = Path(raw_path)
    if path.is_absolute():
        try:
            path = path.relative_to(repo_root)
        except ValueError:
            return path.as_posix()
    return path.as_posix()


def _is_omitted(relative_path: str, omit_patterns: list[str]) -> bool:
    return any(fnmatch(relative_path, pattern) for pattern in omit_patterns)


def _iter_source_files(
    repo_root: Path, config_path: Path, run_config: dict
) -> list[str]:
    config_root = config_path.resolve().parent
    omit_patterns = list(run_config.get("omit", []))
    expected_files: set[str] = set()

    for entry in run_config["source"]:
        candidate = (config_root / entry).resolve()
        if not candidate.exists():
            msg = f"Coverage source entry {entry!r} does not exist under {config_root}"
            raise ValueError(msg)

        files = [candidate] if candidate.is_file() else candidate.rglob("*.py")
        for path in files:
            if not path.is_file():
                continue
            relative_path = path.resolve().relative_to(repo_root.resolve()).as_posix()
            if _is_omitted(relative_path, omit_patterns):
                continue
            expected_files.add(relative_path)

    return sorted(expected_files)


def _find_missing_files(report: dict, repo_root: Path, config_path: Path) -> list[str]:
    run_config = _load_coverage_run_config(config_path)
    expected_files = _iter_source_files(repo_root, config_path, run_config)
    reported_files = {
        _normalize_report_path(repo_root, path) for path in report.get("files", {})
    }
    return sorted(set(expected_files) - reported_files)


def main(argv: list[str] | None = None) -> int:
    """Run the coverage gate against a JSON report and return an exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    report_path = Path(args.report_path)
    config_path = Path(args.config_path)
    repo_root = config_path.resolve().parent

    try:
        report = _load_report(report_path)
        totals = report.get("totals")
        if not isinstance(totals, dict):
            msg = f"Coverage report at {report_path} is missing a totals section."
            raise ValueError(msg)
        covered_lines = _require_metric(totals, "covered_lines")
        total_lines = _require_metric(totals, "num_statements")
        covered_branches = _require_metric(totals, "covered_branches")
        total_branches = _require_metric(totals, "num_branches")
        run_config = _load_coverage_run_config(config_path)
        expected_files = _iter_source_files(repo_root, config_path, run_config)
        missing_files = _find_missing_files(report, repo_root, config_path)
    except (OSError, ValueError, json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
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
    if missing_files:
        failures.append(
            f"coverage report is missing source files: {', '.join(missing_files)}"
        )

    sys.stdout.write(
        "Coverage summary: "
        f"line={line_percent:.2f}% ({covered_lines}/{total_lines}), "
        f"branch={branch_percent:.2f}% ({covered_branches}/{total_branches}), "
        f"expected_files={len(expected_files)}, "
        f"reported_files={len(report.get('files', {}))}\n"
    )
    if failures:
        for failure in failures:
            sys.stderr.write(f"Coverage gate failed: {failure}\n")
        return 1

    sys.stdout.write(
        "Coverage gate passed: "
        f"line>={args.line_threshold:.2f}% and "
        f"branch>={args.branch_threshold:.2f}% with complete source reporting\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
