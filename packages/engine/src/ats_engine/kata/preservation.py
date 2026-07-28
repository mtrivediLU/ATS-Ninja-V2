"""The term-preservation guard.

A tailored resume may never contain fewer occurrences of a JD-relevant term
than the source resume did. This is a small rule with a large consequence.

It exists because of a measured regression. On a posting that says "AI" nine
times, the optimizer replaced a source headline reading

    Senior Software Engineer | Full-Stack, Data & AI Solutions

with

    Business Intelligence Developer

and the delivered resume scored *lower* than the untouched original -- 75 to 73
on an independent third-party matcher. The same run raised ``SQL`` from four
occurrences to six and ``BI`` from four to five, terms the posting mentions
once and three times respectively. It inflated what was already abundant and
deleted what was scarce.

No scorer tuning fixes that class of bug reliably; a hard floor does. With this
guard the headline swap is rejected at the moment it drops an ``AI``, and the
optimizer must find a headline that keeps it -- which is exactly what a human
tailoring the same resume by hand wrote.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from ats_engine.models import RequirementTerm


@dataclass(frozen=True, slots=True)
class TermRegression:
    """One JD-relevant term that the candidate document weakened."""

    term: str
    source_count: int
    candidate_count: int

    @property
    def code(self) -> str:
        return "TERM_REGRESSION"

    def describe(self) -> str:
        return (
            f"term regression: {self.term!r} appears {self.candidate_count} time(s) in the "
            f"tailored document but {self.source_count} time(s) in the source"
        )


def _forms(requirement: RequirementTerm) -> tuple[str, ...]:
    values = {requirement.canonical, requirement.surface, *requirement.aliases}
    return tuple(sorted({value.strip() for value in values if value and value.strip()}))


# A requirement is protected as a whole phrase, but the phrase is not the only
# thing a recruiter's ATS searches for. "Generative AI" contains "AI", which the
# posting that triggered this guard used nine times and which the delivered
# resume dropped -- while the phrase "Generative AI" never appeared in either
# document, so phrase-only matching saw nothing wrong.
#
# Only *distinctive* constituents are protected: an acronym such as AI, BI, SQL
# or ETL, or a token that is a known technology term in its own right. Ordinary
# words ("data", "systems", "business") are deliberately left unprotected, since
# guarding them would block legitimate rewrites without protecting anything a
# keyword matcher cares about.
_ACRONYM = re.compile(r"^[A-Z][A-Za-z0-9]{1,5}$")
_TOKEN = re.compile(r"[A-Za-z0-9+#.-]+")


def _distinctive_tokens(requirement: RequirementTerm) -> set[str]:
    surface = requirement.surface or requirement.canonical
    tokens = _TOKEN.findall(surface)
    if len(tokens) < 2:
        return set()
    return {token for token in tokens if _ACRONYM.match(token) and token.upper() == token}


def protected_terms(requirements: Iterable[RequirementTerm]) -> list[str]:
    """Every phrase and distinctive token the guard defends, deduplicated."""
    terms: set[str] = set()
    for requirement in requirements:
        terms.update(_forms(requirement))
        terms.update(_distinctive_tokens(requirement))
    return sorted(terms, key=str.casefold)


def count_occurrences(text: str, term: str) -> int:
    """Case-insensitive, word-boundary count of *term* in *text*."""
    if not term or not text:
        return 0
    # Terms carry punctuation ("WCAG 2.1", "low-code", "C#"), so the boundaries
    # are asserted manually rather than with \b, which behaves differently
    # either side of a non-word character.
    pattern = rf"(?<![\w+#.-]){re.escape(term)}(?![\w+#.-])"
    return len(re.findall(pattern, text, flags=re.IGNORECASE))


def _best_count(text: str, requirement: RequirementTerm) -> int:
    """Occurrences of the requirement in whichever surface form appears most."""
    return max((count_occurrences(text, form) for form in _forms(requirement)), default=0)


@dataclass(frozen=True, slots=True)
class PreservationGuard:
    """A guard with the source side already measured.

    The optimizer evaluates many candidate documents against one unchanging
    source, and re-scanning that source for every requirement on every batch
    (and again on every step of a failed batch's bisection) is pure waste.
    Building the guard once measures the source a single time and reduces each
    later check to a scan of the candidate for the handful of terms the source
    actually contains.
    """

    # term -> (display form, source occurrences), only for terms present in the source.
    _expected: tuple[tuple[str, str, int], ...]

    def regressions(self, candidate_text: str) -> list[TermRegression]:
        found = [
            TermRegression(term=display, source_count=expected, candidate_count=actual)
            for term, display, expected in self._expected
            if (actual := count_occurrences(candidate_text, term)) < expected
        ]
        found.sort(key=lambda item: item.term.casefold())
        return found

    def preserves(self, candidate_text: str) -> bool:
        return not self.regressions(candidate_text)


def build_guard(source_text: str, requirements: Iterable[RequirementTerm]) -> PreservationGuard:
    """Measure *source_text* once, ready to check many candidates against it.

    Only terms the source actually contains are retained: a term the candidate
    never had cannot regress, and demanding one would be an instruction to
    fabricate.
    """

    requirements = list(requirements)
    expected: dict[str, tuple[str, int]] = {}

    for requirement in requirements:
        display = requirement.surface or requirement.canonical
        best_form, best_count = "", 0
        for form in _forms(requirement):
            count = count_occurrences(source_text, form)
            if count > best_count:
                best_form, best_count = form, count
        if best_count:
            expected[best_form.casefold()] = (display, best_count)

    for token in {token for requirement in requirements for token in _distinctive_tokens(requirement)}:
        if token.casefold() in expected:
            continue
        count = count_occurrences(source_text, token)
        if count:
            expected[token.casefold()] = (token, count)

    # The key is casefolded for dedupe, but counting is case-insensitive anyway,
    # so the folded form is a faithful search term.
    return PreservationGuard(
        _expected=tuple(sorted((term, display, count) for term, (display, count) in expected.items()))
    )


def term_regressions(
    source_text: str,
    candidate_text: str,
    requirements: Iterable[RequirementTerm],
) -> list[TermRegression]:
    """Every JD-relevant term the candidate document states less often."""
    return build_guard(source_text, requirements).regressions(candidate_text)


def preserves_jd_terms(
    source_text: str,
    candidate_text: str,
    requirements: Iterable[RequirementTerm],
) -> bool:
    """Whether *candidate_text* is safe to deliver under this guard."""
    return not term_regressions(source_text, candidate_text, requirements)
