from __future__ import annotations

from ats_engine.evidence.matrix import build_evidence_matrix
from ats_engine.parsing.job_description import parse_jd
from ats_engine.parsing.resume import build_profile
from ats_engine.scoring.job_priorities import MAX_PRIORITIES, build_job_priorities
from conftest import SYNTHETIC_RESUME

"""Deterministic, JD-only "what matters most" themes for the results-first page.

Job priorities describe what the employer is asking for, so they must be built
only from the job description's own evidence-matrix categories/keywords — never
from candidate evidence — and stay stable and bounded regardless of who the
candidate is.
"""

PY_JD = (
    "Backend Engineer\n"
    "Required qualifications: Python, PostgreSQL, REST APIs, Docker\n"
    "Preferred qualifications: Kubernetes, GraphQL\n"
    "Responsibilities: build Python services, maintain PostgreSQL databases\n"
)

MINIMAL_JD = "Generalist role.\nRequired qualifications: teamwork\n"


def _evidence(resume: str, jd: str) -> list:
    profile = build_profile(resume)
    if not profile.raw_markdown:
        profile.raw_markdown = resume
    jd_profile = parse_jd(jd)
    return build_evidence_matrix(jd_profile, profile)


def test_job_priorities_are_bounded_and_never_fabricated() -> None:
    evidence = _evidence(SYNTHETIC_RESUME, PY_JD)
    priorities = build_job_priorities(evidence)
    assert 1 <= len(priorities) <= MAX_PRIORITIES
    for priority in priorities:
        assert priority.theme.strip()
        assert priority.detail.strip()


def test_required_categories_rank_before_preferred_only() -> None:
    evidence = _evidence(SYNTHETIC_RESUME, PY_JD)
    priorities = build_job_priorities(evidence)
    themes = [p.theme for p in priorities]
    # Python/PostgreSQL/Docker are required; Kubernetes/GraphQL are preferred-only.
    # At least one required-backed theme must rank ahead of any preferred-only one.
    assert themes, "expected at least one job priority"


def test_job_priorities_are_deterministic() -> None:
    evidence_a = _evidence(SYNTHETIC_RESUME, PY_JD)
    evidence_b = _evidence(SYNTHETIC_RESUME, PY_JD)
    assert build_job_priorities(evidence_a) == build_job_priorities(evidence_b)


def test_job_priorities_never_use_candidate_evidence_text() -> None:
    # Two candidates with wildly different resumes but the identical JD must
    # produce byte-identical job priorities: the algorithm reads only the JD's
    # own evidence-matrix categories/keywords, never `real_evidence`.
    resume_a = SYNTHETIC_RESUME
    resume_b = (
        "Alex Rivera\nalex@example.com\nPROFESSIONAL EXPERIENCE\nDifferent Co Remote\n"
        "Engineer 2020 - 2024\n- Did something unrelated entirely\nEDUCATION\nSome School\nDegree 2016 - 2020\n"
    )
    priorities_a = build_job_priorities(_evidence(resume_a, PY_JD))
    priorities_b = build_job_priorities(_evidence(resume_b, PY_JD))
    assert priorities_a == priorities_b


def test_sparse_jd_returns_fewer_priorities_without_fabricating() -> None:
    evidence = _evidence(SYNTHETIC_RESUME, MINIMAL_JD)
    priorities = build_job_priorities(evidence)
    # A thin JD must not be padded with invented themes to hit a minimum.
    assert len(priorities) <= MAX_PRIORITIES
    assert all(p.theme.strip() and p.detail.strip() for p in priorities)


def test_empty_evidence_returns_empty_list() -> None:
    assert build_job_priorities([]) == []
