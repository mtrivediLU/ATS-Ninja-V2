from __future__ import annotations

from ats_engine.kit.contract import ChangeType
from ats_engine.kit.orchestrator import generate_application_kit
from conftest import SYNTHETIC_JD, SYNTHETIC_RESUME

"""Fairness regressions: identity information must never enter scoring policy.

Two candidates with identical qualifications but different names, pronouns,
and neutral address/city values must receive identical match numbers, alignment,
fit category, and confidence. Names, pronouns, and addresses are not evidence.
"""


def _kit(resume: str):
    return generate_application_kit(
        resume_text=resume,
        job_description=SYNTHETIC_JD,
        use_llm=False,
        include_resume=True,
        include_cover_letter=False,
        include_job_fit=True,
    )


def _identity_variant(resume: str) -> str:
    return resume.replace("Alex Morgan", "Wei Chen", 1).replace(
        "Springfield, Ontario, Canada", "Lagos, Lagos, Nigeria", 1
    )


def test_name_and_city_do_not_change_scores() -> None:
    base = _kit(SYNTHETIC_RESUME)
    variant = _kit(_identity_variant(SYNTHETIC_RESUME))
    assert base.match_report is not None and variant.match_report is not None
    b, v = base.match_report, variant.match_report

    assert b.original_ats_match.score == v.original_ats_match.score
    assert (b.tailored_ats_match is None) == (v.tailored_ats_match is None)
    if b.tailored_ats_match is not None and v.tailored_ats_match is not None:
        assert b.tailored_ats_match.score == v.tailored_ats_match.score
    assert b.alignment_score == v.alignment_score
    assert b.fit_category == v.fit_category
    assert b.fit_band == v.fit_band
    assert b.confidence == v.confidence


def test_ledger_shape_is_identity_independent() -> None:
    base = _kit(SYNTHETIC_RESUME)
    variant = _kit(_identity_variant(SYNTHETIC_RESUME))
    assert base.resume is not None and variant.resume is not None

    def shape(kit_resume) -> list[tuple[ChangeType, bool]]:
        return [(record.change_type, record.reversible) for record in kit_resume.change_ledger]

    assert shape(base.resume) == shape(variant.resume)


def test_pronoun_line_does_not_change_scores() -> None:
    with_pronouns = SYNTHETIC_RESUME.replace("Alex Morgan\n", "Alex Morgan\nPronouns: they/them\n", 1)
    base = _kit(SYNTHETIC_RESUME)
    variant = _kit(with_pronouns)
    assert base.match_report is not None and variant.match_report is not None
    assert base.match_report.alignment_score == variant.match_report.alignment_score
    assert base.match_report.fit_category == variant.match_report.fit_category
    assert base.match_report.original_ats_match.score == variant.match_report.original_ats_match.score
