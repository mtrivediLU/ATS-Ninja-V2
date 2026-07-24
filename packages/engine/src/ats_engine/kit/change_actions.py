from __future__ import annotations

from dataclasses import dataclass, field

from ats_engine.evidence.matrix import build_evidence_matrix
from ats_engine.generation.document_render import (
    render_cover_letter_text_from_document,
    render_resume_text_from_document,
)
from ats_engine.generation.planning import split_targeting_clause
from ats_engine.kit.contract import (
    ApplicationKit,
    ArtifactKind,
    ChangeRecord,
    ChangeStatus,
    ChangeType,
    CoverLetterArtifact,
    MatchReport,
    ResumeArtifact,
    ResumeDocument,
    WeightedKeyword,
)
from ats_engine.kit.grounding import EvidenceContext, build_evidence_context, ground_text
from ats_engine.models import Profile
from ats_engine.parsing.job_description import parse_jd
from ats_engine.parsing.resume import build_profile
from ats_engine.scoring.match_report import build_kit_summary, build_weighted_keywords, score_resume
from ats_engine.validation.naturalness import validate_naturalness
from ats_engine.validation.style import validate_style

"""Safe, persisted change actions over the v5 change ledger (see ADR-0020).

An action batch is deterministic, LLM-free, and idempotent. It always rebuilds
the delivered artifacts from a stable baseline (the ledger records' own tailored
and original text) rather than cumulatively mutating already-mutated text, so a
reject followed by the same reject — or an accept applied twice — never drifts.

Safety rules:

- An irreversible record (a truth-grounding removal) can only be accepted; a
  reject or restore against it is refused. Fabricated text stays gone.
- Rejecting a rewrite restores the candidate's original text byte-for-byte.
- Rejecting an added unit (summary, targeting clause, cover paragraph) removes it.
- After a batch, the artifacts are re-rendered, re-grounded, re-validated, and
  the tailored keyword-match score, keyword coverage, and kit summary are
  recomputed. The revision is incremented once per successful batch.
"""

ACTION_ACCEPT = "accept"
ACTION_REJECT = "reject"
ACTION_RESTORE = "restore"
_VALID_ACTIONS = frozenset({ACTION_ACCEPT, ACTION_REJECT, ACTION_RESTORE})


@dataclass(slots=True)
class ChangeAction:
    change_id: str
    action: str


@dataclass(slots=True)
class ChangeActionResult:
    kit: ApplicationKit
    conflict: bool = False
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.conflict and not self.errors


def apply_change_actions(
    *,
    kit: ApplicationKit,
    resume_text: str,
    job_description: str,
    actions: list[ChangeAction],
    expected_revision: int,
) -> ChangeActionResult:
    """Apply a batch of change actions and return the updated, revalidated kit."""
    if kit.revision != expected_revision:
        return ChangeActionResult(
            kit=kit, conflict=True, errors=["Revision conflict: the kit changed since it was loaded."]
        )

    records: dict[str, ChangeRecord] = {}
    for artifact in (kit.resume, kit.cover_letter):
        if artifact is not None:
            for record in artifact.change_ledger:
                records[record.id] = record

    errors = _validate_actions(actions, records)
    if errors:
        return ChangeActionResult(kit=kit, errors=errors)

    # Apply statuses (idempotent: setting the same status twice is a no-op).
    for action in actions:
        record = records[action.change_id]
        if action.action == ACTION_ACCEPT:
            record.status = ChangeStatus.ACCEPTED
        elif action.action == ACTION_REJECT:
            record.status = ChangeStatus.REJECTED
        else:  # restore
            record.status = ChangeStatus.PROPOSED

    profile = build_profile(resume_text)
    if not profile.raw_markdown:
        profile.raw_markdown = resume_text
    jd_profile = parse_jd(job_description)
    evidence = build_evidence_matrix(jd_profile, profile)
    keywords = build_weighted_keywords(evidence, jd_profile)
    tier_by_keyword = {item.keyword.casefold().strip(): item.evidence_tier for item in evidence}
    context = build_evidence_context(profile, jd_profile)

    new_resume_text: str | None = None
    if kit.resume is not None and kit.resume.document is not None:
        new_resume_text = _rebuild_resume(kit.resume, context)
    if kit.cover_letter is not None and kit.cover_letter.document is not None:
        _rebuild_cover_letter(kit.cover_letter, context)

    # Recompute the tailored keyword-match score and kit summary from the
    # re-rendered resume. Alignment/confidence are evidence-based and unchanged
    # by content edits, so only the tailored figures move.
    if kit.match_report is not None and new_resume_text is not None:
        _recompute_match_report(kit.match_report, new_resume_text, keywords, profile, tier_by_keyword)

    kit.revision = expected_revision + 1
    return ChangeActionResult(kit=kit)


def _validate_actions(actions: list[ChangeAction], records: dict[str, ChangeRecord]) -> list[str]:
    errors: list[str] = []
    for action in actions:
        if action.action not in _VALID_ACTIONS:
            errors.append(f"Unknown action '{action.action}' for change '{action.change_id}'.")
            continue
        record = records.get(action.change_id)
        if record is None:
            errors.append(f"Unknown change id '{action.change_id}'.")
            continue
        if not record.reversible and action.action in (ACTION_REJECT, ACTION_RESTORE):
            if record.change_type is ChangeType.GROUNDING_REMOVAL:
                errors.append(
                    f"Change '{action.change_id}' is a truth-grounding removal and can never be reverted or restored."
                )
            else:
                errors.append(
                    f"Change '{action.change_id}' is informational and is managed through regeneration, "
                    "not individual reversal."
                )
    return errors


def _rebuild_resume(resume: ResumeArtifact, context: EvidenceContext) -> str:
    """Rebuild the resume document from ledger statuses, re-render, and re-ground."""
    document = resume.document
    assert document is not None
    ledger = {record.id: record for record in resume.change_ledger}

    base = _effective_added(ledger.get("resume::summary"))
    targeting = _effective_added(ledger.get("resume::summary::targeting"))
    document.summary = " ".join(part for part in (base, targeting) if part).strip()

    for record in resume.change_ledger:
        if record.change_type is not ChangeType.BULLET:
            continue
        text = record.original_text if record.status is ChangeStatus.REJECTED else record.tailored_text
        _set_bullet(document, record.id, text)

    rendered = render_resume_text_from_document(document)
    rendered = _reground(rendered, ArtifactKind.RESUME, context)
    resume.text = rendered
    _revalidate_warnings(resume, rendered)
    return rendered


def _rebuild_cover_letter(cover: CoverLetterArtifact, context: EvidenceContext) -> None:
    document = cover.document
    assert document is not None
    rejected_paragraphs = {
        record.tailored_text
        for record in cover.change_ledger
        if record.change_type is ChangeType.COVER_LETTER_PARAGRAPH and record.status is ChangeStatus.REJECTED
    }
    document.body_paragraphs = [
        paragraph for paragraph in document.body_paragraphs if paragraph not in rejected_paragraphs
    ]
    rendered = render_cover_letter_text_from_document(document)
    rendered = _reground(rendered, ArtifactKind.COVER_LETTER, context)
    cover.text = rendered
    _revalidate_warnings(cover, rendered)


def _effective_added(record: ChangeRecord | None) -> str:
    """The delivered text of an added unit: its tailored text unless rejected."""
    if record is None:
        return ""
    return "" if record.status is ChangeStatus.REJECTED else record.tailored_text


def _set_bullet(document: ResumeDocument, location_id: str, text: str) -> None:
    try:
        _, exp_part, bullet_part = location_id.split("::")
        exp_index = int(exp_part.removeprefix("exp"))
        bullet_index = int(bullet_part.removeprefix("bullet"))
    except (ValueError, IndexError):
        return
    if 0 <= exp_index < len(document.experience):
        bullets = document.experience[exp_index].bullets
        if 0 <= bullet_index < len(bullets):
            bullets[bullet_index] = text


def _reground(text: str, artifact: ArtifactKind, context: EvidenceContext) -> str:
    """Re-run the grounding gate over changed text as a safety net.

    Restoring candidate-original text or removing generated text can never
    introduce a fabrication, so this normally returns ``text`` unchanged; it
    exists so a change action can never ship ungrounded content.
    """
    outcome = ground_text(text, artifact=artifact, context=context, id_prefix=f"{artifact.value}-revision")
    return outcome.clean_text


def _revalidate_warnings(artifact: ResumeArtifact | CoverLetterArtifact, text: str) -> None:
    """Refresh non-fatal style/naturalness warnings on the artifact after a change."""
    warnings = [warning for warning in artifact.validation.warnings if not warning.startswith("revision:")]
    for message in (*validate_style(text), *validate_naturalness(text, [])):
        warnings.append(f"revision: {message}")
    artifact.validation.warnings = warnings


def _recompute_match_report(
    report: MatchReport,
    resume_text: str,
    keywords: list[WeightedKeyword],
    profile: Profile,
    tier_by_keyword: dict[str, str],
) -> None:
    tailored = score_resume(resume_text, keywords, profile, tier_by_keyword)
    report.tailored_ats_match = tailored

    matched_original = set(report.keywords_matched_original)
    matched_tailored = set(tailored.matched_keywords)
    report.keywords_surfaced_by_tailoring = sorted(term for term in matched_tailored if term not in matched_original)
    report.keywords_still_missing = [
        w.term for w in keywords if w.term not in matched_original and w.term not in matched_tailored
    ]
    report.kit_summary = build_kit_summary(
        original=report.original_ats_match,
        tailored=tailored,
        alignment=report.alignment_score,
        category=report.fit_category,
        confidence=report.confidence,
    )


__all__ = [
    "ACTION_ACCEPT",
    "ACTION_REJECT",
    "ACTION_RESTORE",
    "ChangeAction",
    "ChangeActionResult",
    "apply_change_actions",
    "split_targeting_clause",
]
