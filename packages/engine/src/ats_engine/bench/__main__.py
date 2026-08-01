"""CLI entry point for ``python -m ats_engine.bench``."""

from __future__ import annotations

import argparse
from pathlib import Path

from ats_engine.bench import format_report, json_report, run_all


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic ATS-Ninja fixture benchmarks.")
    parser.add_argument("--json", type=Path, help="optional destination for a machine-readable JSON report")
    args = parser.parse_args()
    results = run_all()
    print(format_report(results))
    if args.json is not None:
        args.json.write_text(json_report(results), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
