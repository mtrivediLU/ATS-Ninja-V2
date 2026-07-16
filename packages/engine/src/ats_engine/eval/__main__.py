from __future__ import annotations

import sys

from ats_engine.eval import format_report, run_all

"""CLI entry point: ``python -m ats_engine.eval``.

Prints the Phase 2A quality report and exits non-zero if any case had a
truth-grounding violation, so it can gate a build or a future provider comparison.
"""


def main() -> int:
    results = run_all()
    print(format_report(results))
    violations = sum(len(result.truth_violations) for result in results)
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
