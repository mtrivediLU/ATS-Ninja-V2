"""PRAMANA calibration against externally supplied Jobscan scores.

This module never estimates, synthesizes, or infers a Jobscan score. It only
reads whatever a human has recorded in a fixture's ``hand_labels.toml``
``[meta]`` block (``jobscan_base_score``, etc. -- see
``tests/fixtures/real_extraction/*/hand_labels.toml``). A fixture with no
such value is skipped and reported as "no calibration data", never filled in
with a guess.

Only the base-resume-vs-JD score is compared here. RACHANA (tailoring) is not
yet wired into these fixtures, so there is no PRAMANA "tailored" score to
compare against ``jobscan_tailored_score`` / ``jobscan_human_tailored_score``
yet -- that comparison is deferred to the PR that adds it.
"""

from __future__ import annotations

import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from ats_engine.evidence.resolver import resolve_requirements
from ats_engine.models import Profile
from ats_engine.parsing.job_description import parse_jd
from ats_engine.parsing.resume import build_profile
from ats_engine.pramana.requirements import extract_requirements
from ats_engine.pramana.scoring import score_resume

# packages/engine/src/ats_engine/pramana/calibration.py -> packages/engine
_ENGINE_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_FIXTURES_ROOT = _ENGINE_ROOT / "tests" / "fixtures" / "real_extraction"
DEFAULT_RESUME_PATH = DEFAULT_FIXTURES_ROOT / "candidate_resume.pymupdf.txt"


@dataclass(frozen=True, slots=True)
class CalibrationRow:
    """One fixture's PRAMANA-vs-Jobscan base-score comparison."""

    case: str
    pramana_score: float
    jobscan_score: float | None
    absolute_difference: float | None
    note: str


def run_calibration(
    fixtures_root: Path = DEFAULT_FIXTURES_ROOT,
    resume_path: Path = DEFAULT_RESUME_PATH,
) -> list[CalibrationRow]:
    """Compute PRAMANA's base score for every fixture under *fixtures_root*.

    Each fixture directory must contain ``job_description.txt`` and
    ``hand_labels.toml``. The shared candidate resume at *resume_path* is
    scored against each JD in turn -- this mirrors the real job-fit path
    (``tailored=False``, no placements), never a bespoke calibration formula.
    """
    resume_text = resume_path.read_text()
    profile = build_profile(resume_text)

    rows: list[CalibrationRow] = []
    for case_dir in sorted(p for p in fixtures_root.iterdir() if p.is_dir()):
        hand_labels_path = case_dir / "hand_labels.toml"
        jd_path = case_dir / "job_description.txt"
        if not hand_labels_path.exists() or not jd_path.exists():
            continue
        rows.append(_score_case(case_dir.name, jd_path, hand_labels_path, resume_text, profile))
    return rows


def _score_case(
    case: str,
    jd_path: Path,
    hand_labels_path: Path,
    resume_text: str,
    profile: Profile,
) -> CalibrationRow:
    jd_text = jd_path.read_text()
    meta = tomllib.loads(hand_labels_path.read_text()).get("meta", {})

    jd_profile = parse_jd(jd_text)
    requirements = extract_requirements(jd_text)
    links = resolve_requirements(requirements, profile, resume_text)
    result = score_resume(
        resume_text,
        requirements,
        links,
        jd_title=jd_profile.title,
        parse_confidence=jd_profile.parse_confidence,
    )

    jobscan_score = meta.get("jobscan_base_score")
    if jobscan_score is None:
        return CalibrationRow(
            case=case,
            pramana_score=result.score,
            jobscan_score=None,
            absolute_difference=None,
            note="no calibration data",
        )
    jobscan_score = float(jobscan_score)
    return CalibrationRow(
        case=case,
        pramana_score=result.score,
        jobscan_score=jobscan_score,
        absolute_difference=round(abs(result.score - jobscan_score), 2),
        note="",
    )


def format_report(rows: list[CalibrationRow]) -> str:
    """Render a plain-text comparison table -- observed values, not tuned toward."""
    lines = ["PRAMANA vs. Jobscan (base resume, no tailoring)", "-" * 48]
    for row in rows:
        if row.jobscan_score is None:
            lines.append(f"{row.case}: PRAMANA={row.pramana_score:.1f}  Jobscan=n/a  ({row.note})")
        else:
            lines.append(
                f"{row.case}: PRAMANA={row.pramana_score:.1f}  Jobscan={row.jobscan_score:.1f}  "
                f"diff={row.absolute_difference:.1f}"
            )
    return "\n".join(lines)


def main() -> int:
    print(format_report(run_calibration()))
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = ["CalibrationRow", "format_report", "run_calibration"]
