"""The completeness gate distinguishes a ledgered removal from a silent loss.

``validation.completeness`` exists to stop candidate content disappearing from
a delivered resume. Pruning deliberately removes a low-relevance bullet, which
without a record is indistinguishable from exactly that failure. The gate is
therefore *ledger-aware* rather than loosened, and these tests pin the
asymmetry that makes that claim true rather than merely asserted:

* an unledgered disappearance still fails, and still withholds the resume
  (``completeness:`` is in ``validation.severity.FATAL_MARKERS``);
* a ledger entry is verified, not trusted -- it must name real source text
  that is really absent from the render;
* the arithmetic allowance alone cannot launder a swap, because each excused
  bullet must additionally be proven individually absent.
"""

from __future__ import annotations

from ats_engine.models import ContactInfo, JDProfile, Mode, ParsedInput, PipelineResult, RemovedContent
from ats_engine.parsing.resume import extract_profile
from ats_engine.validation.completeness import resume_completeness_errors, validate_completeness
from ats_engine.validation.severity import is_fatal_validation_error
from conftest import BASIC_JD

_RESUME = (
    "Jordan Rivera\n"
    "555-201-9876 | jordan@example.com\n"
    "PROFESSIONAL EXPERIENCE\n"
    "Acme Corp Remote\n"
    "Software Engineer 2022 to 2024\n"
    "*Built Python and SQL data pipelines for the finance team.\n"
    "*Reduced processing time by 40% across nightly jobs.\n"
    "*Documented the on-call rotation handbook for new joiners.\n"
)

_KEPT_BULLETS = (
    "- Built Python and SQL data pipelines for the finance team.\n"
    "- Reduced processing time by 40% across nightly jobs.\n"
)
_DROPPED_BULLET = "Documented the on-call rotation handbook for new joiners."


def _rendered(bullets: str) -> str:
    return (
        "Candidate Header\n"
        "Professional Summary\nExperienced engineer.\n\n"
        "Technical Skills\nGeneral: SQL, Python\n\n"
        "Professional Experience\n"
        "Company: Acme Corp Remote | Title: Software Engineer | Dates: 2022 to 2024\n"
        f"{bullets}\n"
        "Education\n"
        "Certifications\n"
    )


def _result(text: str) -> PipelineResult:
    parsed_input = ParsedInput(
        resume_text=_RESUME,
        job_description=BASIC_JD,
        contacts=ContactInfo(),
        questions=[],
        logistics={},
        mode=Mode.RESUME,
    )
    result = PipelineResult(parsed_input=parsed_input, jd_profile=JDProfile())
    result.resume_text = text
    return result


def _profile():  # type: ignore[no-untyped-def]
    profile = extract_profile(_RESUME)
    assert len(profile.experiences) == 1
    assert len(profile.experiences[0].bullets) == 3
    return profile


def test_a_bullet_removed_without_a_ledger_entry_still_fails_and_withholds_the_resume() -> None:
    """The negative case the ledger allowance must never swallow."""
    profile = _profile()
    errors = validate_completeness(_result(_rendered(_KEPT_BULLETS)), profile)

    assert any("experience bullets" in error for error in errors)
    # Withholding, not merely reporting: this prefix is a fatal marker, which is
    # what marks resume delivery failed and rolls the Kit up honestly.
    assert any(is_fatal_validation_error(error) for error in errors)


def test_a_verified_ledger_entry_permits_exactly_the_bullet_it_names() -> None:
    profile = _profile()
    ledger = [
        RemovedContent(kind="bullet", location="experience:0:bullet:2", original_text=_DROPPED_BULLET),
    ]
    errors = validate_completeness(_result(_rendered(_KEPT_BULLETS)), profile, ledger)

    assert errors == []


def test_a_ledger_entry_naming_text_the_source_never_had_is_rejected() -> None:
    """A fabricated entry buys no allowance -- the count shortfall still fails."""
    profile = _profile()
    ledger = [
        RemovedContent(
            kind="bullet",
            location="experience:0:bullet:2",
            original_text="Invented a bullet that was never in the candidate's resume.",
        )
    ]
    errors = validate_completeness(_result(_rendered(_KEPT_BULLETS)), profile, ledger)

    assert any("is not a source bullet" in error for error in errors)
    assert any("experience bullets" in error for error in errors)


def test_a_ledger_entry_whose_bullet_is_still_rendered_is_rejected() -> None:
    """Claiming a removal that did not happen is itself an error."""
    profile = _profile()
    all_three = _KEPT_BULLETS + f"- {_DROPPED_BULLET}\n"
    ledger = [
        RemovedContent(kind="bullet", location="experience:0:bullet:2", original_text=_DROPPED_BULLET),
    ]
    errors = validate_completeness(_result(_rendered(all_three)), profile, ledger)

    assert any("still rendered" in error for error in errors)


def test_a_ledger_entry_cannot_launder_a_different_bullets_disappearance() -> None:
    """The laundering route a count-only allowance would have opened.

    The ledger claims bullet C was removed; in fact C is on the page and
    bullet B vanished. The arithmetic balances (3 source - 1 ledgered == 2
    rendered), so a count-only allowance would pass this. The per-entry
    absence proof is what catches it.
    """
    profile = _profile()
    swapped = (
        "- Built Python and SQL data pipelines for the finance team.\n"
        f"- {_DROPPED_BULLET}\n"
    )  # "Reduced processing time by 40%..." silently gone
    ledger = [
        RemovedContent(kind="bullet", location="experience:0:bullet:2", original_text=_DROPPED_BULLET),
    ]
    errors = validate_completeness(_result(_rendered(swapped)), profile, ledger)

    assert any("still rendered" in error for error in errors)
    assert any(is_fatal_validation_error(error) for error in errors)


def test_the_text_only_rebuild_entry_point_enforces_the_same_rule() -> None:
    """A persisted revision cannot launder a removal through a rebuild."""
    profile = _profile()
    text = _rendered(_KEPT_BULLETS)

    assert any("experience bullets" in error for error in resume_completeness_errors(text, profile))

    ledger = [
        RemovedContent(kind="bullet", location="experience:0:bullet:2", original_text=_DROPPED_BULLET),
    ]
    assert resume_completeness_errors(text, profile, ledger) == []


def test_an_empty_ledger_is_byte_for_byte_the_original_behavior() -> None:
    """Every caller that predates pruning is unaffected."""
    profile = _profile()
    text = _rendered(_KEPT_BULLETS)

    assert resume_completeness_errors(text, profile) == resume_completeness_errors(text, profile, [])
