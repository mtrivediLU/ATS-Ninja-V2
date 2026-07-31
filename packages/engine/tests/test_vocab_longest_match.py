"""Longest-match: a multi-word vocabulary entry must beat its own prefix.

The CGI case's "Spring Boot" degrading to "Spring" was diagnosed and corrected
against the brief here: the matcher already preferred the longer entry for
every multi-word pair that existed in the vocabulary before this PR (Power
BI, React Native, GitHub Copilot all beat their prefixes on `main`, verified
directly). The actual defect was that `spring boot` was simply absent from
the vocabulary, not that the matcher mishandled it. This file is therefore a
regression PIN, not a repair test: it proves the existing matcher behaviour
holds for every pair this PR adds, and stays true for the pairs that already
worked, so neither regresses silently.
"""

from __future__ import annotations

import pytest

from ats_engine.pramana.requirements import extract_requirements

# (JD snippet naming both the long form and, elsewhere, its bare prefix,
#  expected long-form surface that must be extracted)
CASES = [
    ("Spring Boot", "Spring Boot experience required."),
    ("Power BI", "Strong Power BI experience required."),
    ("SQL Server", "Strong SQL Server experience required."),
    ("React Native", "Strong React Native experience required."),
    ("Spring MVC", "Strong Spring MVC experience required."),
    ("GitHub Copilot", "Experience with GitHub Copilot required."),
    ("GitHub Actions", "Experience with GitHub Actions required."),
]


@pytest.mark.parametrize(("term", "snippet"), CASES)
def test_multiword_term_beats_its_own_prefix(term: str, snippet: str) -> None:
    """The full term's literal text must be what gets matched, never truncated.

    Checked on ``surface`` (the literal matched text), not ``canonical``: a
    term can legitimately be filed under a different canonical name via an
    alias without that being a longest-match failure. What must never happen
    is the surface truncating to the bare first word.
    """
    jd = f"Required Qualifications\n- {snippet}\n"
    requirements = extract_requirements(jd)
    surfaces = {requirement.surface for requirement in requirements}
    canonicals = {requirement.canonical for requirement in requirements}

    prefix = term.split()[0]
    assert term.casefold() in {s.casefold() for s in surfaces}, (
        f"expected the full term {term!r} to be the matched surface; got {surfaces}"
    )
    # The bare first word must never appear as its OWN separate requirement
    # alongside the full term -- that would mean the prefix was matched
    # independently rather than being absorbed into the longer entry.
    assert not any(s.casefold() == prefix.casefold() for s in surfaces), (
        f"{prefix!r} leaked out as its own surface alongside {term!r}: {surfaces}"
    )
    assert len(canonicals) == 1, f"expected exactly one requirement for {snippet!r}, got {canonicals}"


def test_spring_boot_specifically_does_not_degrade_to_bare_spring() -> None:
    """The exact CGI regression, pinned directly rather than only parametrised."""
    jd = "Required Qualifications\n- 5+ years with Java, J2EE and Spring Boot.\n"
    requirements = extract_requirements(jd)
    canonicals = {r.canonical for r in requirements}

    assert "spring boot" in canonicals
    assert "spring" not in canonicals
