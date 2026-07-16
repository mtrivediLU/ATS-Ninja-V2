from __future__ import annotations

import sys

from ats_engine.eval import format_report, run_all

"""CLI entry point: ``python -m ats_engine.eval``.

Prints the grounding + JobFit quality report and exits non-zero if any case had
a truth-grounding or fit-consistency violation.
"""


def main() -> int:
    results = run_all()
    print(format_report(results))
    violations = sum(len(result.truth_violations) for result in results)
    consistency_failures = sum(
        int(not result.job_fit_consistent) + len(result.missing_job_fit_expectations) for result in results
    )
    return 1 if violations or consistency_failures else 0


if __name__ == "__main__":
    sys.exit(main())
