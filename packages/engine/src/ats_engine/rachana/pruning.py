"""PRUNE: remove low-relevance content so what remains concentrates.

Density is ``distinct relevant canonicals / (words / 100)``. Measured on the
real fixtures, the numerator is saturated -- CGI expressed 15 distinct
requirement canonicals before tailoring and the same 15 after seventeen
accepted additive actions, while the document grew. Every additive operation
this engine has can only push the denominator up. The only remaining lever is
to push it down, which is also what the human-tailored comparison did: it cut
128 words and gained 39 external points where the engine added 46 words and
gained 1.

That makes this the first operation whose purpose is subtraction, and
subtraction from a truth-grounded product is the riskiest thing in the
codebase. Every gate below therefore **fails closed to keeping the content**:
a bullet is removed only when this module can prove, against structured
evidence rather than string presence, that removing it costs the candidate
nothing checkable and nothing credited.

Three properties do the work:

* **Nothing credited is ever removed.** A bullet that is the sole evidence
  location for any requirement the resume currently earns PRAMANA credit for
  is protected, whatever else is true of it. This is checked against the
  evidence graph (``EvidenceLink``), never by looking for the term in text.
* **Nothing checkable is ever removed.** Metrics, team sizes, credential ids,
  and any employer/title/date/institution/certification drawn from the
  candidate's own :class:`~ats_engine.rachana.facts.ImmutableFactSet` block a
  removal outright, as does any named entity in the bullet's body that is not
  independently evidenced elsewhere in the same role -- the "named client"
  case, where "Vale (Tier-1 mining client)" must never quietly vanish.
* **Nothing is removed silently.** Every accepted prune produces a
  ``RemovedContent`` ledger entry carrying the original text verbatim, which
  ``validation.completeness`` independently verifies and the user can revert.
  A removal the ledger cannot account for still fails completeness and still
  withholds the whole resume.

Candidate class 3 from the brief -- removing a redundant *phrase* inside an
otherwise-kept bullet -- is **deliberately not implemented**. Sub-sentence
excision cannot be proven fact-preserving with the deterministic machinery
here (the fact set is computed per bullet, not per clause), and a partial
sentence is a grammaticality risk with no ledger primitive to restore it.
Classes 1 and 2 are implemented.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ats_engine.models import EvidenceLink, Experience, RequirementTerm
from ats_engine.rachana.facts import (
    ImmutableFactSet,
    extract_credential_ids,
    extract_metrics,
    extract_proper_nouns,
    extract_team_facts,
)
from ats_engine.validation.fidelity import contains_fact, extract_named_entities

# Content floors. A resume that tailors itself down to a stub is a worse
# product than one that is merely long, so a role keeps a readable minimum
# regardless of how little of it the JD happens to ask about.
MIN_BULLETS_MOST_RECENT_ROLE = 3
MIN_BULLETS_OLDER_ROLE = 2

# Recency policy, stated explicitly because the brief asks for it:
#
# * The most recent role (index 0) is the one a recruiter reads first and the
#   one an employer verifies hardest. It keeps a strictly higher floor (3
#   bullets, versus 2 elsewhere) and is eligible for class-1 removal only --
#   a bullet with *zero* requirement relevance. It is never eligible for the
#   more permissive class-2 rule below.
# * Roles at index >= OLDER_ROLE_FROM are "older roles" for class-2 purposes.
#   Index 1 and 2 sit in between: eligible for class 1, not for class 2.
OLDER_ROLE_FROM = 3

# Rejection reasons. Each maps 1:1 to a GateCode in generation.diagnostics, so
# a reviewer reading the benchmark histogram can tell which protection fired.
REJECT_UNIQUE_EVIDENCE = "prune_unique_evidence"
REJECT_PROTECTED_FACT = "prune_protected_fact"
REJECT_UNEVIDENCED_ENTITY = "prune_unevidenced_entity"
REJECT_ROLE_FLOOR = "prune_role_floor"

_LABEL_MAX_WORDS = 6


@dataclass(frozen=True, slots=True)
class PruneProposal:
    """One bullet screened as a removal candidate, with why it was screened."""

    experience_index: int
    bullet_index: int
    location: str
    text: str
    rationale: str  # "no_requirement_relevance" | "relevance_expressed_elsewhere"

    @property
    def word_count(self) -> int:
        return len(self.text.split())


@dataclass(frozen=True, slots=True)
class PruneRejection:
    """A removal that failed closed, with the reason a caller maps to a gate code."""

    reason: str
    detail: str


def bullet_body(text: str) -> str:
    """The bullet minus the candidate's own leading ``Label:`` heading.

    Every bullet in the real fixtures is written as ``Short Heading: prose``,
    and ``extract_named_entities`` stops at colons, so the heading always
    surfaces as an "entity" of its own ("UI/UX Optimization", "Real-Time
    Architecture"). Those are the candidate's section labels, not verifiable
    claims about an employer or client, and treating them as unevidenced
    facts would block every removal on the page for a formatting choice.
    Only the body is checked for entities; the heading is discarded with the
    bullet either way.
    """
    head, separator, tail = text.partition(":")
    if separator and tail.strip() and len(head.split()) <= _LABEL_MAX_WORDS:
        return tail.strip()
    return text


def _requirement_hits(text: str, requirements: list[RequirementTerm]) -> list[str]:
    canonicals = {requirement.canonical for requirement in requirements if requirement.canonical}
    return sorted(canonical for canonical in canonicals if contains_fact(text, canonical))


def _evidence_locations(links: list[EvidenceLink]) -> dict[str, set[str]]:
    """Every source location supporting each requirement that has evidence."""
    locations: dict[str, set[str]] = {}
    for link in links:
        if link.tier == "missing":
            continue
        supporting = {link.resume_location, *link.supporting_locations}
        locations.setdefault(link.requirement.canonical, set()).update(item for item in supporting if item)
    return locations


def _immutable_facts_in(text: str, fact_set: ImmutableFactSet) -> list[str]:
    """Checkable facts from the candidate's own fact set that this text states.

    ``name`` and ``contact`` are excluded deliberately: they live in the
    header, never in a bullet, and a candidate's own name legitimately appears
    in prose without the bullet being the thing that evidences it.
    """
    checked = (
        fact_set.employers
        | fact_set.titles
        | fact_set.date_ranges
        | fact_set.job_locations
        | fact_set.degrees
        | fact_set.institutions
        | fact_set.graduation_dates
        | fact_set.certification_names
        | fact_set.credential_ids
    )
    return sorted(value for value in checked if value and contains_fact(text, value))


def screen_bullet(
    experience_index: int,
    bullet_index: int,
    text: str,
    *,
    requirements: list[RequirementTerm],
    document_text: str,
) -> PruneProposal | None:
    """Return a removal candidate for this bullet, or None if it is not one.

    None means "not a candidate", which is the ordinary case and is not a
    rejection: a bullet carrying live, uniquely-expressed JD relevance is
    simply not the kind of content this operation removes, and recording a
    gate rejection for every such bullet would drown the diagnostics.
    """
    stripped = (text or "").strip()
    if not stripped:
        return None
    hits = _requirement_hits(stripped, requirements)
    if not hits:
        return PruneProposal(
            experience_index=experience_index,
            bullet_index=bullet_index,
            location=f"experience:{experience_index}:bullet:{bullet_index}",
            text=stripped,
            rationale="no_requirement_relevance",
        )
    # Class 2: an older role's bullet whose every requirement canonical is
    # also expressed somewhere else in the delivered document. Removing it
    # cannot lower the density numerator, because the numerator counts
    # distinct canonicals *visible in the document*, not occurrences.
    if experience_index < OLDER_ROLE_FROM:
        return None
    remainder = document_text.replace(stripped, " ")
    if any(not contains_fact(remainder, canonical) for canonical in hits):
        return None
    return PruneProposal(
        experience_index=experience_index,
        bullet_index=bullet_index,
        location=f"experience:{experience_index}:bullet:{bullet_index}",
        text=stripped,
        rationale="relevance_expressed_elsewhere",
    )


def check_prune(
    proposal: PruneProposal,
    *,
    role: Experience,
    links: list[EvidenceLink],
    fact_set: ImmutableFactSet,
    credited_canonicals: frozenset[str],
) -> PruneRejection | None:
    """The hard gates, in fail-closed order. None means the removal is safe.

    ``credited_canonicals`` is the set of requirements the *current* document
    actually earns PRAMANA credit for; a requirement with no credit has
    nothing to lose, and protecting its sole evidence location would block
    removals for no benefit.
    """
    text = proposal.text

    # 1. Unique-evidence protection, against the evidence graph.
    locations = _evidence_locations(links)
    sole_support = sorted(
        canonical
        for canonical, where in locations.items()
        if canonical in credited_canonicals and where == {proposal.location}
    )
    if sole_support:
        return PruneRejection(
            reason=REJECT_UNIQUE_EVIDENCE,
            detail=f"sole evidence for credited requirement(s): {', '.join(sole_support)}",
        )

    # 2. Protected facts: nothing an employer can check may leave with it.
    metrics = sorted(extract_metrics(text))
    if metrics:
        return PruneRejection(reason=REJECT_PROTECTED_FACT, detail=f"states metric(s) {', '.join(metrics)}")
    team = sorted(extract_team_facts(text))
    if team:
        return PruneRejection(reason=REJECT_PROTECTED_FACT, detail=f"states team size {', '.join(team)}")
    credentials = sorted(extract_credential_ids(text))
    if credentials:
        return PruneRejection(reason=REJECT_PROTECTED_FACT, detail=f"states credential id(s) {', '.join(credentials)}")
    immutable = _immutable_facts_in(text, fact_set)
    if immutable:
        return PruneRejection(
            reason=REJECT_PROTECTED_FACT,
            detail=f"states immutable fact(s) {', '.join(repr(value) for value in immutable)}",
        )

    # 3. Named entities in the body must be independently evidenced elsewhere
    #    in the same role -- the named-client and named-tool protection.
    others = " ".join(bullet for bullet in role.bullets if (bullet or "").strip() != text)
    body = bullet_body(text)
    seen: set[str] = set()
    unevidenced: list[str] = []
    for entity in (*extract_named_entities(body), *extract_proper_nouns(body)):
        key = entity.casefold()
        if key in seen or contains_fact(others, entity):
            continue
        seen.add(key)
        unevidenced.append(entity)
    if unevidenced:
        return PruneRejection(
            reason=REJECT_UNEVIDENCED_ENTITY,
            detail=f"names {', '.join(repr(entity) for entity in unevidenced)} not evidenced elsewhere in this role",
        )
    return None


def role_floor(experience_index: int) -> int:
    """The minimum bullet count this role must retain (see the recency policy)."""
    return MIN_BULLETS_MOST_RECENT_ROLE if experience_index == 0 else MIN_BULLETS_OLDER_ROLE


def check_role_floor(experience_index: int, remaining_bullets: int) -> PruneRejection | None:
    """Fail closed when removing one more bullet would breach the role's floor."""
    floor = role_floor(experience_index)
    if remaining_bullets - 1 < floor:
        return PruneRejection(
            reason=REJECT_ROLE_FLOOR,
            detail=(
                f"role would fall to {remaining_bullets - 1} bullet(s), below the "
                f"{floor}-bullet floor for {'the most recent role' if experience_index == 0 else 'this role'}"
            ),
        )
    return None


def normalize_for_match(text: str) -> str:
    """Whitespace/punctuation-insensitive key, matching completeness's own."""
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


__all__ = [
    "MIN_BULLETS_MOST_RECENT_ROLE",
    "MIN_BULLETS_OLDER_ROLE",
    "OLDER_ROLE_FROM",
    "REJECT_PROTECTED_FACT",
    "REJECT_ROLE_FLOOR",
    "REJECT_UNEVIDENCED_ENTITY",
    "REJECT_UNIQUE_EVIDENCE",
    "PruneProposal",
    "PruneRejection",
    "bullet_body",
    "check_prune",
    "check_role_floor",
    "normalize_for_match",
    "role_floor",
    "screen_bullet",
]
