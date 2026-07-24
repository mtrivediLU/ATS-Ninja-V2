from __future__ import annotations

from ats_engine.kit.contract import (
    EVIDENCE_EXCERPT_MAX_CHARS,
    ArtifactKind,
    ChangeOperation,
    ChangeRecord,
    ChangeStatus,
    ChangeType,
    ClaimRecord,
    ClaimStatus,
    CoverLetterDocument,
    EvidenceRef,
    ResumeDocument,
    ScoreConfidence,
    WeightedKeyword,
)
from ats_engine.models import PlanDecision, Profile
from ats_engine.scoring.match_report import score_resume

"""The transparent, evidence-linked change ledger (ApplicationKit v5).

Every material tailoring delta maps to exactly one :class:`ChangeRecord`, built
from two stable, deterministic sources — never fragile rendered-text diffing:

1. **Instrumented plan decisions** (:class:`ats_engine.models.PlanDecision`),
   captured where the decision happens (summary, targeting clause, bullet
   rewrite, skill surfacing). These carry the exact original and tailored text
   and a stable, location-aware id.
2. **Grounding claim records** — every repaired/rejected claim becomes a visible
   ``grounding_removal`` record, linked to the real claim id, and is marked
   ``reversible=False``: a truth-grounding removal can never be restored by a
   user or the API (see ADR-0020).

Impact is an *estimated keyword-match* impact computed by exact deterministic
re-scoring (never a model estimate) and never a claim about interview outcomes.
Frequency does not affect impact: scoring is presence-based.
"""

# Change types produced from an instrumented plan decision, mapped 1:1.
_DECISION_TYPE: dict[str, ChangeType] = {
    "summary": ChangeType.SUMMARY,
    "targeting_clause": ChangeType.TARGETING_CLAUSE,
    "bullet": ChangeType.BULLET,
    "skill": ChangeType.SKILL,
}

# Skill surfacing is recorded for transparency but is not individually
# reversible: skills are surfaced deterministically from evidence, and reverting
# one is a regeneration concern, not a single-unit toggle. Bullets, the summary,
# and the targeting clause are fully reversible.
_REVERSIBLE_TYPES: frozenset[ChangeType] = frozenset(
    {ChangeType.SUMMARY, ChangeType.TARGETING_CLAUSE, ChangeType.BULLET, ChangeType.COVER_LETTER_PARAGRAPH}
)


def _counterfactual_impact(
    *,
    full_text: str,
    original: str,
    tailored: str,
    is_grounding: bool,
    keywords: list[WeightedKeyword],
    profile: Profile,
    tier_by_keyword: dict[str, str],
) -> float:
    """Deterministic whole-document keyword-match impact of one change.

    Impact is computed *counterfactually against the complete resume*, not on an
    isolated snippet:

        impact = score(full document with the change)
               - score(full document without the change)

    so a keyword that already appears elsewhere in the document contributes zero
    additional impact. For a normal tailoring change the delivered ``full_text``
    already contains ``tailored``; the counterfactual reverts it (restoring
    ``original`` for a rewrite, or removing it for an addition). For a grounding
    removal the fabricated ``original`` is *absent* from the delivered document,
    so the counterfactual re-adds it — and, being unsupported, it never raises
    the evidence-gated score, yielding an honest ~0 impact.
    """

    def _score(text: str) -> float:
        return score_resume(text, keywords, profile, tier_by_keyword).score

    with_change = full_text
    if is_grounding:
        without_change = f"{full_text}\n{original}".strip()
    elif tailored and tailored in full_text:
        without_change = full_text.replace(tailored, original, 1)
    else:
        # The change's tailored text is not located in the delivered document
        # (e.g. it was further edited by grounding); fall back to a bounded local
        # comparison so the record still carries an honest, non-inflated figure.
        with_change = f"{full_text}\n{tailored}".strip() if tailored else full_text
        without_change = f"{full_text}\n{original}".strip() if original else full_text
    return round(_score(with_change) - _score(without_change), 2)


def _operation(value: str) -> ChangeOperation:
    try:
        return ChangeOperation(value)
    except ValueError:
        return ChangeOperation.ADDED


def _impact_text(delta: float) -> str:
    if delta > 0:
        return f"Estimated keyword-match impact: +{delta:.2f} points."
    if delta < 0:
        return f"Estimated keyword-match impact: {delta:.2f} points."
    return "No estimated keyword-match change."


def _document_bullet(document: ResumeDocument | None, location_id: str) -> str | None:
    """Resolve the final delivered bullet text at ``resume::exp{e}::bullet{b}``."""
    if document is None:
        return None
    try:
        _, exp_part, bullet_part = location_id.split("::")
        exp_index = int(exp_part.removeprefix("exp"))
        bullet_index = int(bullet_part.removeprefix("bullet"))
    except (ValueError, IndexError):
        return None
    if 0 <= exp_index < len(document.experience):
        bullets = document.experience[exp_index].bullets
        if 0 <= bullet_index < len(bullets):
            return bullets[bullet_index]
    return None


def build_resume_change_ledger(
    *,
    decisions: list[PlanDecision],
    document: ResumeDocument | None,
    claims: list[ClaimRecord],
    keywords: list[WeightedKeyword],
    profile: Profile,
    tier_by_keyword: dict[str, str],
    full_text: str = "",
) -> list[ChangeRecord]:
    """Build the resume change ledger from plan decisions and grounding claims."""
    records: list[ChangeRecord] = []

    for decision in decisions:
        change_type = _DECISION_TYPE.get(decision.kind)
        if change_type is None:
            continue
        tailored = decision.tailored_text
        if decision.kind == "bullet":
            resolved = _document_bullet(document, decision.location_id)
            if resolved is not None:
                tailored = resolved
        reversible = change_type in _REVERSIBLE_TYPES
        delta = _counterfactual_impact(
            full_text=full_text,
            original=decision.original_text,
            tailored=tailored,
            is_grounding=False,
            keywords=keywords,
            profile=profile,
            tier_by_keyword=tier_by_keyword,
        )
        operation = _operation(decision.operation)
        evidence = (
            [
                EvidenceRef(
                    source="candidate_resume",
                    locator="original_bullet",
                    excerpt=decision.original_text[:EVIDENCE_EXCERPT_MAX_CHARS],
                )
            ]
            if decision.kind == "bullet" and decision.original_text
            else []
        )
        records.append(
            ChangeRecord(
                id=decision.location_id,
                artifact=ArtifactKind.RESUME,
                change_type=change_type,
                operation=operation,
                original_text=decision.original_text,
                tailored_text=tailored,
                reason=decision.reason,
                status=ChangeStatus.PROPOSED,
                reversible=reversible,
                matched_keywords=list(decision.matched_keywords),
                evidence=evidence,
                ats_impact=_impact_text(delta),
                ats_impact_delta=delta,
                confidence=ScoreConfidence.HIGH if decision.matched_keywords else ScoreConfidence.MEDIUM,
            )
        )

    records.extend(
        _grounding_records(claims, ArtifactKind.RESUME, keywords, profile, tier_by_keyword, full_text=full_text)
    )
    return records


def build_cover_letter_change_ledger(
    *,
    document: CoverLetterDocument | None,
    claims: list[ClaimRecord],
    keywords: list[WeightedKeyword],
    profile: Profile,
    tier_by_keyword: dict[str, str],
    full_text: str = "",
) -> list[ChangeRecord]:
    """Build the cover-letter change ledger.

    Cover-letter body paragraphs are fully generated prose, so each is an
    ``added`` reversible record (rejecting removes the paragraph). Grounding
    removals are irreversible, exactly as on the resume.
    """
    records: list[ChangeRecord] = []
    paragraphs = document.body_paragraphs if document is not None else []
    for index, paragraph in enumerate(paragraphs):
        if not paragraph.strip() or paragraph.strip().lower().startswith("dear "):
            continue
        delta = _counterfactual_impact(
            full_text=full_text,
            original="",
            tailored=paragraph,
            is_grounding=False,
            keywords=keywords,
            profile=profile,
            tier_by_keyword=tier_by_keyword,
        )
        records.append(
            ChangeRecord(
                id=f"cover::p{index}",
                artifact=ArtifactKind.COVER_LETTER,
                change_type=ChangeType.COVER_LETTER_PARAGRAPH,
                operation=ChangeOperation.ADDED,
                original_text="",
                tailored_text=paragraph,
                reason="Generated a tailored cover-letter paragraph grounded in the candidate's evidence.",
                status=ChangeStatus.PROPOSED,
                reversible=True,
                ats_impact=_impact_text(delta),
                ats_impact_delta=delta,
                confidence=ScoreConfidence.MEDIUM,
            )
        )
    records.extend(
        _grounding_records(claims, ArtifactKind.COVER_LETTER, keywords, profile, tier_by_keyword, full_text=full_text)
    )
    return records


def _grounding_records(
    claims: list[ClaimRecord],
    artifact: ArtifactKind,
    keywords: list[WeightedKeyword],
    profile: Profile,
    tier_by_keyword: dict[str, str],
    *,
    full_text: str = "",
) -> list[ChangeRecord]:
    """Convert repaired/rejected grounding claims into irreversible ledger records.

    These are the truth-grounding removals. They are linked to the real claim id,
    always ``reversible=False``, and can never be restored — the fabricated text
    is gone from the final artifact and must stay gone (ADR-0020).
    """
    records: list[ChangeRecord] = []
    for claim in claims:
        if claim.status not in (ClaimStatus.REPAIRED, ClaimStatus.REJECTED):
            continue
        # Counterfactual: the delivered document already excludes the fabrication,
        # so impact = score(delivered) - score(delivered + fabrication). Since the
        # fabrication is unsupported it never raises the evidence-gated score, so
        # this is an honest ~0 (removing a fabrication does not lower the real
        # keyword match). The reason is grounding-specific, never a generic label.
        delta = _counterfactual_impact(
            full_text=full_text,
            original=claim.text,
            tailored="",
            is_grounding=True,
            keywords=keywords,
            profile=profile,
            tier_by_keyword=tier_by_keyword,
        )
        records.append(
            ChangeRecord(
                id=f"grounding::{claim.id}",
                artifact=artifact,
                change_type=ChangeType.GROUNDING_REMOVAL,
                operation=ChangeOperation.REMOVED,
                original_text=claim.text,
                tailored_text="",
                reason=(
                    f"Removed an unsupported {claim.claim_type.value} claim ({claim.reason}). "
                    "Restoring it would reintroduce content the candidate's evidence does not support, "
                    "so this removal is permanent."
                ),
                status=ChangeStatus.PROPOSED,
                reversible=False,
                ats_impact=_impact_text(delta),
                ats_impact_delta=delta,
                confidence=ScoreConfidence.HIGH,
                linked_claim_ids=[claim.id],
            )
        )
    return records


__all__ = [
    "build_cover_letter_change_ledger",
    "build_resume_change_ledger",
]
