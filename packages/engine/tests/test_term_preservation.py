"""The term-preservation guard and the honest source-projection floor.

The regression these tests lock out was measured, not hypothetical. On a
posting that says "AI" nine times, the delivered resume replaced the
candidate's own headline --

    Senior Software Engineer | Full-Stack, Data & AI Solutions

with the most recent job title, "Business Intelligence Developer", dropping an
"AI" mention. The same run pushed "SQL" from 4 occurrences to 6 and "BI" from
4 to 5, terms the posting names once and three times. It inflated what was
abundant and deleted what was scarce, and the "improved" resume scored *below*
the untouched original on an independent matcher.

The guard makes that structurally impossible rather than merely fixed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ats_engine.kata.preservation import (
    count_occurrences,
    preserves_jd_terms,
    term_regressions,
)
from ats_engine.kensho.requirements import extract_requirements
from ats_engine.parsing.resume import build_profile

FIXTURES = Path(__file__).parent / "fixtures" / "real_extraction"

SOURCE_HEADLINE = "Senior Software Engineer | Full-Stack, Data & AI Solutions"
REPLACEMENT_HEADLINE = "Business Intelligence Developer"


@pytest.fixture(scope="module")
def latentview_requirements():
    return extract_requirements((FIXTURES / "latentview_bi_ai" / "job_description.txt").read_text())


@pytest.fixture(scope="module")
def profile():
    return build_profile((FIXTURES / "candidate_resume.pymupdf.txt").read_text())


# ------------------------------------------------------------- counting ----


@pytest.mark.parametrize(
    "text, term, expected",
    [
        ("AI and AI again", "AI", 2),
        ("Retail is not AI", "AI", 1),
        # A term must not match inside a longer word: "AI" is not in "SAID".
        ("SAID AIRLINE", "AI", 0),
        ("low-code and no-code", "low-code", 1),
        ("WCAG 2.1 compliance", "WCAG 2.1", 1),
        ("", "AI", 0),
        ("AI", "", 0),
    ],
)
def test_count_occurrences_respects_word_boundaries(text: str, term: str, expected: int) -> None:
    assert count_occurrences(text, term) == expected


# --------------------------------------------------------------- guard ----


def test_the_reported_headline_swap_is_rejected(latentview_requirements) -> None:
    """The exact change that caused the measured regression."""
    source = f"{SOURCE_HEADLINE}\nBuilt dashboards with SQL."
    candidate = f"{REPLACEMENT_HEADLINE}\nBuilt dashboards with SQL."

    regressions = term_regressions(source, candidate, latentview_requirements)

    assert regressions, "dropping an AI mention must be reported"
    assert not preserves_jd_terms(source, candidate, latentview_requirements)
    assert any(regression.term.casefold() == "ai" for regression in regressions)


def test_a_headline_that_keeps_the_term_is_allowed(latentview_requirements) -> None:
    """The fix is not 'never change the headline' -- it is 'never lose a term'.

    This is the headline a human wrote by hand for the same application.
    """
    source = f"{SOURCE_HEADLINE}\nBuilt dashboards with SQL."
    candidate = "Business Intelligence Engineer | Enterprise BI, SQL & AI\nBuilt dashboards with SQL."

    assert preserves_jd_terms(source, candidate, latentview_requirements)


def test_an_unchanged_document_never_regresses(latentview_requirements, profile) -> None:
    text = profile.raw_markdown
    assert term_regressions(text, text, latentview_requirements) == []


def test_a_term_absent_from_the_source_is_not_demanded(latentview_requirements) -> None:
    """Requiring a term the candidate never had is an instruction to fabricate."""
    source = "Built reporting pipelines."
    candidate = "Built reporting pipelines."
    assert preserves_jd_terms(source, candidate, latentview_requirements)


def test_adding_occurrences_is_always_allowed(latentview_requirements) -> None:
    source = "Worked with SQL."
    candidate = "Worked with SQL. Also used SQL for reporting."
    assert preserves_jd_terms(source, candidate, latentview_requirements)


def test_regression_report_carries_both_counts(latentview_requirements) -> None:
    source = "AI AI AI systems"
    candidate = "AI systems"
    regression = next(
        r for r in term_regressions(source, candidate, latentview_requirements) if r.term.casefold() == "ai"
    )
    assert (regression.source_count, regression.candidate_count) == (3, 1)
    assert regression.code == "TERM_REGRESSION"
    assert "AI" in regression.describe()


def test_regressions_are_reported_deterministically(latentview_requirements) -> None:
    source = "AI and SQL and Looker"
    candidate = "reporting"
    first = [item.term for item in term_regressions(source, candidate, latentview_requirements)]
    second = [item.term for item in term_regressions(source, candidate, latentview_requirements)]
    assert first == second == sorted(first, key=str.casefold)


# ------------------------------------------------- source headline floor ----


def test_the_source_headline_is_captured(profile) -> None:
    """Without this the floor had nothing to preserve and invented a headline."""
    assert profile.source_headline == SOURCE_HEADLINE


def test_the_source_headline_is_not_the_most_recent_job_title(profile) -> None:
    """`role_identities[0]` is exactly the wrong answer that shipped."""
    assert profile.source_headline != profile.role_identities[0]
    assert profile.role_identities[0] == REPLACEMENT_HEADLINE


def test_the_source_headline_retains_its_jd_relevant_terms(profile) -> None:
    assert count_occurrences(profile.source_headline, "AI") == 1


def test_a_resume_without_a_headline_reports_none() -> None:
    """A contact line is never a headline.

    A bare domain carries no scheme and no "www.", so a naive URL check misses
    it and `linkedin.com/in/alex-morgan` gets promoted to the headline slot.
    """
    resume = (
        "Alex Morgan\n"
        "alex.morgan@example.test | 555-010-0200 | Toronto, ON (Remote)\n"
        "linkedin.com/in/alex-morgan-example\n"
        "\n"
        "PROFESSIONAL SUMMARY\n"
        "Senior engineer with 10 years of experience.\n"
    )
    assert build_profile(resume).source_headline == ""


@pytest.mark.parametrize(
    "contact_line",
    [
        "linkedin.com/in/alex-morgan-example",
        "example.com",
        "alex.dev/portfolio",
        "github.com/alexmorgan",
        "www.example.com",
        "https://example.com/cv",
        "alex.morgan@example.test",
        "555-010-0200",
    ],
)
def test_contact_shapes_are_never_promoted_to_the_headline(contact_line: str) -> None:
    resume = f"Alex Morgan\n{contact_line}\n\nPROFESSIONAL SUMMARY\nEngineer.\n"
    assert build_profile(resume).source_headline == ""


def test_a_real_headline_is_still_captured_after_a_contact_line() -> None:
    resume = (
        "Alex Morgan\n"
        "Staff Data Engineer | Streaming & AI Platforms\n"
        "linkedin.com/in/alex-morgan-example\n"
        "\n"
        "PROFESSIONAL SUMMARY\n"
        "Engineer.\n"
    )
    assert build_profile(resume).source_headline == "Staff Data Engineer | Streaming & AI Platforms"
