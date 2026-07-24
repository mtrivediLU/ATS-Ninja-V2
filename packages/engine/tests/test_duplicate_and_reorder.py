from __future__ import annotations

from ats_engine.generation.planning import _reject_generated_duplicates
from ats_engine.kit.contract import ChangeOperation
from ats_engine.kit.orchestrator import generate_application_kit

"""Regression coverage for two candidate-facing correctness defects:

1. Duplicate *source* bullets must never withhold an otherwise-valid resume.
   The candidate authored them; preserving them keeps completeness intact and
   loses no candidate fact.
2. Resume bullet order within an employer is preserved (never silently
   reordered), so a material candidate-facing change is never invisible.
"""

# Three bullets, two of them exact duplicates. The parser-friendly layout keeps
# the deterministic resume parser happy (name / contact / EXPERIENCE / company /
# title+dates / "- bullet").
DUP_RESUME = (
    "Jordan Lee\n"
    "jordan@example.com | linkedin.com/in/jordanlee\n"
    "PROFESSIONAL SUMMARY\n"
    "Backend engineer building Python services.\n"
    "PROFESSIONAL EXPERIENCE\n"
    "Acme Corp Remote\n"
    "Software Engineer 2019 - 2024\n"
    "- Documented release procedures for stakeholders\n"
    "- Built Python services and REST APIs\n"
    "- Built Python services and REST APIs\n"
    "EDUCATION\n"
    "State University\n"
    "Bachelor of Computer Science 2015 - 2019\n"
)

PY_JD = (
    "Backend Engineer\n"
    "Required qualifications: Python, REST APIs, microservices\n"
    "Responsibilities: build Python services and REST APIs\n"
)


def _bullets(kit) -> list[str]:  # type: ignore[no-untyped-def]
    assert kit.resume is not None and kit.resume.document is not None
    return [bullet for entry in kit.resume.document.experience for bullet in entry.bullets]


def test_duplicate_source_bullets_do_not_withhold_the_resume() -> None:
    kit = generate_application_kit(
        resume_text=DUP_RESUME,
        job_description=PY_JD,
        use_llm=False,
        include_resume=True,
    )
    assert kit.resume is not None
    # The resume is delivered, not withheld.
    assert kit.resume.validation.fatal is False
    assert kit.resume.text.strip() != ""
    assert kit.resume.document is not None
    # No completeness failure about lost bullets.
    for error in kit.resume.validation.errors:
        assert "completeness" not in error.lower(), error


def test_candidate_facts_survive_duplicate_bullets() -> None:
    kit = generate_application_kit(resume_text=DUP_RESUME, job_description=PY_JD, use_llm=False, include_resume=True)
    text = kit.resume.text.lower()  # type: ignore[union-attr]
    # Both distinct facts remain present.
    assert "release procedures" in text
    assert "python services" in text


def test_bullet_order_is_preserved_within_an_employer() -> None:
    # Source order: "Documented release procedures" first, then the Python bullet.
    # Even though the Python bullet is more JD-relevant, order must not silently
    # change (a reorder would be a material, unledgered candidate-facing change).
    kit = generate_application_kit(resume_text=DUP_RESUME, job_description=PY_JD, use_llm=False, include_resume=True)
    bullets = [b.lower() for b in _bullets(kit)]
    documented = next(i for i, b in enumerate(bullets) if "release procedures" in b)
    built = next(i for i, b in enumerate(bullets) if "python services" in b)
    assert documented < built, bullets

    # Source order is preserved, so there is neither a silent reorder nor a silent
    # omission of candidate content in the ledger.
    assert kit.resume is not None
    for record in kit.resume.change_ledger:
        assert record.operation != ChangeOperation.REORDERED, record
        assert record.operation != ChangeOperation.OMITTED, record


def test_duplicate_bullets_across_employers_are_never_combined() -> None:
    resume = (
        "Robin Fox\n"
        "robin@example.com | linkedin.com/in/robinfox\n"
        "PROFESSIONAL SUMMARY\n"
        "Engineer across two companies.\n"
        "PROFESSIONAL EXPERIENCE\n"
        "First Company Remote\n"
        "Software Engineer 2021 - 2024\n"
        "- Built REST APIs in Python\n"
        "Second Company Remote\n"
        "Software Engineer 2018 - 2021\n"
        "- Built REST APIs in Python\n"
        "EDUCATION\n"
        "State University\n"
        "Bachelor of Computer Science 2014 - 2018\n"
    )
    kit = generate_application_kit(resume_text=resume, job_description=PY_JD, use_llm=False, include_resume=True)
    assert kit.resume is not None and kit.resume.document is not None
    assert kit.resume.validation.fatal is False
    # Two employers, each still carrying its own copy of the identical bullet.
    entries = kit.resume.document.experience
    assert len(entries) == 2
    for entry in entries:
        joined = " ".join(entry.bullets).lower()
        assert "rest apis in python" in joined


def test_generated_duplicate_rewrite_is_reverted_not_dropped() -> None:
    # Two DISTINCT source bullets; a model rewrite collapses them into identical
    # prose. The later one is reverted to its own original, never dropped, so the
    # bullet count is preserved and generated stuffing is undone.
    originals = ["Built Python services", "Documented release procedures"]
    rewritten = ["Built Python services and REST APIs", "Built Python services and REST APIs"]
    repaired = _reject_generated_duplicates(originals, rewritten)
    assert len(repaired) == 2
    assert repaired[0] == "Built Python services and REST APIs"
    assert repaired[1] == "Documented release procedures"  # restored original


def test_genuine_source_duplicates_are_preserved_by_the_repair() -> None:
    # When the two ORIGINALS are themselves identical, the duplication is the
    # candidate's own content and must be preserved (dropping it breaks
    # completeness).
    originals = ["Built Python services", "Built Python services"]
    rewritten = list(originals)
    repaired = _reject_generated_duplicates(originals, rewritten)
    assert repaired == ["Built Python services", "Built Python services"]


def test_near_duplicate_but_different_bullets_both_survive() -> None:
    resume = (
        "Dana Kim\n"
        "dana@example.com | linkedin.com/in/danakim\n"
        "PROFESSIONAL SUMMARY\n"
        "Engineer building services.\n"
        "PROFESSIONAL EXPERIENCE\n"
        "Acme Corp Remote\n"
        "Software Engineer 2019 - 2024\n"
        "- Built Python services for the billing team\n"
        "- Built Python services for the payments team\n"
        "EDUCATION\n"
        "State University\n"
        "Bachelor of Computer Science 2015 - 2019\n"
    )
    kit = generate_application_kit(resume_text=resume, job_description=PY_JD, use_llm=False, include_resume=True)
    assert kit.resume is not None and kit.resume.validation.fatal is False
    text = kit.resume.text.lower()
    assert "billing team" in text
    assert "payments team" in text
