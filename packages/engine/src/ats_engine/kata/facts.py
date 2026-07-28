"""The Immutable Fact Set -- the facts an employer can check with one call.

Employers, titles, dates, locations, degrees, institutions, certifications,
credential IDs, and every number stated in a bullet are not stylistic choices.
They are verifiable claims, and tailoring may re-word around them but may never
add to them or drop one.

The comparison is deliberately **set equality**, not similarity:

* a fact present in the source but missing from the render is ``lost`` -- this
  is the failure that deleted four credential IDs from a delivered PDF;
* a fact present in the render but absent from the source is ``invented`` --
  this is fabrication, and it is the more serious of the two.

There is intentionally no calibration, no suppression list, and no severity
tier in this module. Those mechanisms exist elsewhere for *stylistic* findings,
where a false positive is plausible. Here a mismatch is never a false positive:
either the employer can verify the claim or they cannot.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, fields
from typing import Any

from ats_engine.models import Profile

# A number in a bullet is a claim: "reduced prep time by 40%", "managed a team
# of 12", "$2.3M in savings", "3 years". Percentages, currency, and plain
# counts are all checkable, so all of them are facts.
_METRIC = re.compile(
    r"(?<![\w.])"
    r"(?:"
    r"[$€£]\s?\d[\d,]*(?:\.\d+)?\s*(?:[KMB]|thousand|million|billion)?"
    r"|\d[\d,]*(?:\.\d+)?\s*%"
    r"|\d[\d,]*(?:\.\d+)?\s*(?:[KMB]\b|x\b)"
    r"|\d[\d,]*(?:\.\d+)?"
    r")",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class FactViolation:
    """One fact that was dropped from, or invented in, a rendered document."""

    field: str
    value: str
    kind: str  # "lost" | "invented"

    def describe(self) -> str:
        if self.kind == "lost":
            return f"{self.field}: source fact missing from the rendered document: {self.value!r}"
        return f"{self.field}: rendered document states a fact absent from the source: {self.value!r}"


@dataclass(frozen=True, slots=True)
class ImmutableFactSet:
    """Every checkable fact in one resume, as comparable sets."""

    name: frozenset[str]
    contact: frozenset[str]
    employers: frozenset[str]
    titles: frozenset[str]
    date_ranges: frozenset[str]
    job_locations: frozenset[str]
    degrees: frozenset[str]
    institutions: frozenset[str]
    graduation_dates: frozenset[str]
    certification_names: frozenset[str]
    credential_ids: frozenset[str]
    metrics: frozenset[str]

    def as_dict(self) -> dict[str, Any]:
        return {item.name: getattr(self, item.name) for item in fields(self)}


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _nonempty(values: Any) -> frozenset[str]:
    return frozenset(cleaned for cleaned in (_clean(value) for value in values) if cleaned)


def extract_metrics(text: str) -> frozenset[str]:
    """Every number-bearing claim in *text*, normalized for comparison."""
    return frozenset(re.sub(r"\s+", "", match.group(0)) for match in _METRIC.finditer(text or ""))


def build_fact_set(profile: Profile) -> ImmutableFactSet:
    """Lock the checkable facts of *profile*."""

    contact = profile.contact
    metrics: set[str] = set()
    for experience in profile.experiences:
        for bullet in experience.bullets:
            metrics |= extract_metrics(bullet)
    for education in profile.education:
        for bullet in education.bullets:
            metrics |= extract_metrics(bullet)

    return ImmutableFactSet(
        name=_nonempty([contact.name]),
        contact=_nonempty([contact.email, contact.phone, contact.linkedin, contact.website]),
        employers=_nonempty(experience.company for experience in profile.experiences),
        titles=_nonempty(experience.title for experience in profile.experiences),
        date_ranges=_nonempty(experience.dates for experience in profile.experiences),
        job_locations=_nonempty(experience.location for experience in profile.experiences),
        degrees=_nonempty(education.degree for education in profile.education),
        institutions=_nonempty(education.institution for education in profile.education),
        graduation_dates=_nonempty(education.dates for education in profile.education),
        certification_names=_nonempty(item.name for item in profile.certifications),
        credential_ids=_nonempty(item.credential_id for item in profile.certifications),
        metrics=frozenset(metrics),
    )


def fact_set_violations(source: ImmutableFactSet, rendered: ImmutableFactSet) -> list[FactViolation]:
    """Report every fact lost from, or invented in, *rendered*.

    The result is sorted so the report is deterministic; callers treat a
    non-empty list as fatal.
    """

    violations: list[FactViolation] = []
    for item in fields(source):
        source_values: frozenset[str] = getattr(source, item.name)
        rendered_values: frozenset[str] = getattr(rendered, item.name)
        for value in sorted(source_values - rendered_values):
            violations.append(FactViolation(field=item.name, value=value, kind="lost"))
        for value in sorted(rendered_values - source_values):
            violations.append(FactViolation(field=item.name, value=value, kind="invented"))
    return violations
