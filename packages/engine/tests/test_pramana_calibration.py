"""PRAMANA calibration reads externally supplied Jobscan scores, never guesses one.

``run_calibration`` takes injectable ``fixtures_root``/``resume_path`` params
specifically so this file can prove the skip behavior against a synthetic
fixture, without depending on the real ``tests/fixtures/real_extraction``
corpus staying in a particular shape.
"""

from __future__ import annotations

from pathlib import Path

from ats_engine.pramana.calibration import run_calibration

_RESUME_TEXT = """John Doe

EXPERIENCE
Software Engineer, Example Corp
- Built data pipelines using Python and SQL.
"""

_JD_TEXT = """Software Engineer

Requirements
- Python
- SQL
"""


def _write_case(root: Path, name: str, *, meta_lines: str) -> None:
    case_dir = root / name
    case_dir.mkdir()
    (case_dir / "job_description.txt").write_text(_JD_TEXT)
    (case_dir / "hand_labels.toml").write_text(meta_lines)


def test_a_fixture_with_a_supplied_jobscan_score_is_compared(tmp_path: Path) -> None:
    resume_path = tmp_path / "resume.txt"
    resume_path.write_text(_RESUME_TEXT)
    _write_case(tmp_path, "with_score", meta_lines="[meta]\njobscan_base_score = 50\n")

    rows = run_calibration(fixtures_root=tmp_path, resume_path=resume_path)

    assert len(rows) == 1
    row = rows[0]
    assert row.case == "with_score"
    assert row.jobscan_score == 50.0
    assert row.absolute_difference == round(abs(row.pramana_score - 50.0), 2)
    assert row.note == ""


def test_a_fixture_with_no_jobscan_score_is_skipped_not_estimated(tmp_path: Path) -> None:
    resume_path = tmp_path / "resume.txt"
    resume_path.write_text(_RESUME_TEXT)
    _write_case(tmp_path, "no_score", meta_lines='[meta]\ncase = "no_score"\n')

    rows = run_calibration(fixtures_root=tmp_path, resume_path=resume_path)

    assert len(rows) == 1
    row = rows[0]
    assert row.jobscan_score is None
    assert row.absolute_difference is None
    assert row.note == "no calibration data"
    # A real PRAMANA score is still computed and reported -- only the
    # Jobscan side is absent.
    assert row.pramana_score >= 0.0


def test_a_fixture_with_no_meta_table_at_all_is_also_skipped(tmp_path: Path) -> None:
    resume_path = tmp_path / "resume.txt"
    resume_path.write_text(_RESUME_TEXT)
    _write_case(tmp_path, "bare", meta_lines="")

    rows = run_calibration(fixtures_root=tmp_path, resume_path=resume_path)

    assert len(rows) == 1
    assert rows[0].jobscan_score is None
    assert rows[0].note == "no calibration data"


def test_report_never_prints_a_fabricated_jobscan_number(tmp_path: Path) -> None:
    resume_path = tmp_path / "resume.txt"
    resume_path.write_text(_RESUME_TEXT)
    _write_case(tmp_path, "no_score", meta_lines='[meta]\ncase = "no_score"\n')

    from ats_engine.pramana.calibration import format_report

    rows = run_calibration(fixtures_root=tmp_path, resume_path=resume_path)
    report = format_report(rows)

    assert "n/a" in report
    assert "no calibration data" in report
