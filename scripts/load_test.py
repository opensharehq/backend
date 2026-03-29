#!/usr/bin/env python3
"""CLI entrypoint for the lightweight OpenShare load test runner."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if __name__ == "__main__":
    from common.load_testing import main

    raise SystemExit(main())
