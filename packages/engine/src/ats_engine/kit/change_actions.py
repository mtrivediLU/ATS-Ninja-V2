from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field

from ats_engine.evidence.matrix import build_evidence_matrix
from ats_engine.generation.document_render import (
    render_cover_letter_text_from_document,
    render_resume_text_from_document,
)
from ats_engine.generation.latex_renderer import cover_letter_to_latex, resume_to_latex
from ats_engine.generation.planning import split_targeting_clause
from ats_engine.kit.contract import (
    ApplicationKit,
    ArtifactKind,
    ArtifactStatus,
    ArtifactValidation,
    ChangeRecord,
    ChangeStatus,
    ChangeType,
    ClaimRecord,
    CoverLetterArtifact,
    CoverLetterDocument,
    MatchReport,
    ResumeArtifact,
    ResumeDocument,
    ValidationSummary,
    WeightedKeyword,
)
from ats_engine.kit.grounding import EvidenceContext, GroundingOutcome, build_evidence_context, ground_text
from ats_engine.models import Profile
from ats_engine.parsing.job_description import parse_jd
from ats_engine.parsing.resume import build_profile
from ats_engine.scoring.match_report import build_kit_summary, build_weighted_keywords, score_resume
from ats_engine.validation.completeness import resume_completeness_errors
from ats_engine.validation.latex import validate_latex
from ats_engine.validation.naturalness import (
    detect_jd_echo,
    jd_appended_to_resume,
    production_naturalness_warnings,
)
from ats_engine.validation.output_format import validate_cover_letter_word_count
from ats_engine.validation.severity import is_fatal_validation_error
from ats_engine.validation.style import validate_style

# A cover letter shorter than this many body words (or with no body paragraphs) is
# not a usable letter. Initial generation treats the ideal 280-320 band as a soft
# warning, but a *change action* that would leave the delivered letter degenerate
# (e.g. rejecting most paragraphs down to a couple of sentences) must be refused
# atomically rather than persisting an unusable artifact. This floor sits well
# below a legitimately short letter, so only genuinely broken results are refused.
MIN_USABLE_COVER_WORDS = 100

"""Safe, persisted change actions over the v5 change ledger (see ADR-0020).

An action batch is deterministic, LLM-free, idempotent, and **atomic**. It always
rebuilds the delivered artifacts from a stable, immutable baseline — the ledger
records' own original and tailored text — rather than cumulatively mutating
already-mutated document state, so reject/restore is drift-free and a rejected
unit can always be reconstructed exactly.

After applying the batch to a rebuilt document the whole artifact is re-rendered
(text **and** LaTeX), re-grounded per unit (refreshing the claim/evidence trace,
never retaining revision-zero claims), and revalidated (grounding + style +
naturalness + LaTeX). If the rebuilt artifact would be fatally invalid or
ungrounded the batch is refused atomically: nothing is persisted and the revision
does not advance.

Safety rules:

- An irreversible record (a truth-grounding removal) can only be accepted; a
  reject or restore against it is refused. Fabricated text stays gone.
- Rejecting a rewrite restores the candidate's original text.
- Rejecting an added unit (summary, targeting clause, cover paragraph) removes it.
- The tailored keyword-match score, keyword coverage, and kit summary are
  recomputed; the revision increments once per successful batch.
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


@dataclass(slots=True)
class _RebuildOutcome:
    text: str
    fatal: bool
    errors: list[str] = field(default_factory=list)


def apply_change_actions(
    *,
    kit: ApplicationKit,
    resume_text: str,
    job_description: str,
    actions: list[ChangeAction],
    expected_revision: int,
) -> ChangeActionResult:
    """Apply a batch of change actions and return the updated, revalidated kit.

    Atomic by construction: the proposed revision is built on a deep copy of the
    kit, so a batch that fails validation leaves the caller's ``kit`` byte-for-byte
    unchanged (documents, claims, ledger statuses, rendered text, LaTeX, match
    report, revision, and validation). Only a fully-valid revision is returned; on
    any failure the original kit is returned untouched.
    """
    if kit.revision != expected_revision:
        return ChangeActionResult(
            kit=kit, conflict=True, errors=["Revision conflict: the kit changed since it was loaded."]
        )

    # An empty batch is a no-op: it must never advance the revision or rebuild the
    # artifacts. The caller's kit is returned exactly as received.
    if not actions:
        return ChangeActionResult(kit=kit)

    # A batch that targets the same change twice is ambiguous (which disposition
    # wins?). Refuse it rather than silently letting the last action win.
    seen_ids: set[str] = set()
    duplicate_ids: set[str] = set()
    for action in actions:
        if action.change_id in seen_ids:
            duplicate_ids.add(action.change_id)
        seen_ids.add(action.change_id)
    if duplicate_ids:
        return ChangeActionResult(
            kit=kit,
            errors=[
                f"Duplicate change id in one batch: '{cid}'. Send at most one action per change."
                for cid in sorted(duplicate_ids)
            ],
        )

    original_records: dict[str, ChangeRecord] = {}
    for artifact in (kit.resume, kit.cover_letter):
        if artifact is not None:
            for record in artifact.change_ledger:
                original_records[record.id] = record

    errors = _validate_actions(actions, original_records)
    if errors:
        return ChangeActionResult(kit=kit, errors=errors)

    # Everything below mutates a working copy only. The caller's kit is never
    # touched until (and unless) a valid revision is returned.
    working = deepcopy(kit)
    records: dict[str, ChangeRecord] = {}
    for artifact in (working.resume, working.cover_letter):
        if artifact is not None:
            for record in artifact.change_ledger:
                records[record.id] = record

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

    keyword_terms = [keyword.term for keyword in keywords]

    rebuild_errors: list[str] = []
    new_resume_text: str | None = None
    if working.resume is not None and working.resume.document is not None:
        outcome = _rebuild_resume(
            working.resume, context, job_description=job_description, profile=profile, keyword_terms=keyword_terms
        )
        new_resume_text = outcome.text
        if outcome.fatal:
            rebuild_errors.extend(outcome.errors)
    if working.cover_letter is not None and working.cover_letter.document is not None:
        outcome = _rebuild_cover_letter(
            working.cover_letter, context, job_description=job_description, keyword_terms=keyword_terms
        )
        if outcome.fatal:
            rebuild_errors.extend(outcome.errors)

    if rebuild_errors:
        # Atomic refusal: the working copy is discarded; the original kit is
        # returned exactly as it was received.
        return ChangeActionResult(
            kit=kit, errors=["The change could not be applied without invalidating the artifact.", *rebuild_errors]
        )

    if working.match_report is not None and new_resume_text is not None:
        _recompute_match_report(working.match_report, new_resume_text, keywords, profile, tier_by_keyword)

    # Refresh the kit-wide validation roll-up so global warnings/status can never
    # go stale relative to the artifacts a successful batch just rebuilt.
    working.validation = _recompute_kit_validation(working)

    working.revision = expected_revision + 1
    return ChangeActionResult(kit=working)


# Prefixes `validate_pipeline_result` gives resume/cover-letter entries in the
# kit-wide validation roll-up (see `generation/pipeline.py`). A change action
# revalidates only these two artifacts, so only their prefixed entries are
# stale after a batch and need replacing.
_REFRESHED_VALIDATION_PREFIXES = ("resume:", "cover letter:")


def _recompute_kit_validation(kit: ApplicationKit) -> ValidationSummary:
    """Refresh ``ApplicationKit.validation`` after a successful change-action batch.

    `kit.validation` is built once at initial generation from the pipeline's
    prefixed error/warning strings (``"resume: ..."``, ``"cover letter: ..."``,
    ``"contact: ..."``, ...). A change action revalidates only the resume and
    cover-letter artifacts, so this drops their stale prefixed entries and
    re-adds fresh ones from the just-rebuilt artifacts' own validation, leaving
    every other artifact's contribution (contact/answers/job-fit/...) untouched.
    ``fatal`` is recomputed across every artifact, matching the same rule
    initial generation uses.
    """
    previous = kit.validation
    carried_errors = [e for e in previous.errors if not e.startswith(_REFRESHED_VALIDATION_PREFIXES)]
    carried_warnings = [w for w in previous.warnings if not w.startswith(_REFRESHED_VALIDATION_PREFIXES)]

    fresh_errors: list[str] = []
    fresh_warnings: list[str] = []
    for label, artifact in (("resume", kit.resume), ("cover letter", kit.cover_letter)):
        if artifact is None:
            continue
        fresh_errors.extend(f"{label}: {error}" for error in artifact.validation.errors)
        fresh_warnings.extend(f"{label}: {warning}" for warning in artifact.validation.warnings)

    errors = [*carried_errors, *fresh_errors]
    warnings = [*carried_warnings, *fresh_warnings]
    fatal = any(
        artifact is not None and artifact.validation.fatal
        for artifact in (
            kit.resume,
            kit.cover_letter,
            kit.answers,
            kit.job_fit,
            kit.interview_prep,
            kit.linkedin_outreach,
        )
    )
    return ValidationSummary(
        passed=not fatal,
        fatal=fatal,
        error_count=len(errors),
        warning_count=len(warnings),
        errors=errors,
        warnings=warnings,
    )


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


# --------------------------------------------------------------------------- #
# Resume rebuild (stable baseline -> ledger state -> re-render -> re-ground)
# --------------------------------------------------------------------------- #
def _rebuild_resume(
    resume: ResumeArtifact,
    context: EvidenceContext,
    *,
    job_description: str,
    profile: Profile,
    keyword_terms: list[str],
) -> _RebuildOutcome:
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

    # Re-ground every editable unit and refresh the claim trace from scratch, so
    # no revision-zero claims survive a content change.
    claims: list[ClaimRecord] = []
    repaired = 0
    rejected = 0
    if document.summary:
        outcome = ground_text(
            document.summary, artifact=ArtifactKind.RESUME, context=context, id_prefix="resume-rev-summary"
        )
        document.summary = outcome.clean_text
        claims, repaired, rejected = _merge_outcome(outcome, claims, repaired, rejected)
    for exp_index, entry in enumerate(document.experience):
        cleaned: list[str] = []
        for bullet_index, bullet in enumerate(entry.bullets):
            if not bullet.strip():
                cleaned.append(bullet)
                continue
            outcome = ground_text(
                bullet,
                artifact=ArtifactKind.RESUME,
                context=context,
                id_prefix=f"resume-rev-exp{exp_index}-bullet{bullet_index}",
                granularity="span",
            )
            cleaned.append(outcome.clean_text)
            claims, repaired, rejected = _merge_outcome(outcome, claims, repaired, rejected)
        entry.bullets = cleaned

    text = render_resume_text_from_document(document)
    latex = resume_to_latex(text, _resume_user_info(document))

    # Authoritative post-action validation: LaTeX + JD-append + completeness are
    # fatal (an unusable or lossy resume must never persist); style + anti-stuffing
    # + JD-echo are warnings, matching initial generation's severity.
    errors = _structural_errors(text, latex, job_description)
    errors.extend(resume_completeness_errors(text, profile))
    units = [document.summary, *(bullet for entry in document.experience for bullet in entry.bullets)]
    warnings = _naturalness_warnings(text, units=units, keyword_terms=keyword_terms, job_description=job_description)
    fatal = rejected > 0 or any(is_fatal_validation_error(error) for error in errors)
    _apply_validation(
        resume,
        claims=claims,
        repaired=repaired,
        rejected=rejected,
        fatal=fatal,
        text=text,
        latex=latex,
        extra_warnings=warnings,
    )
    return _RebuildOutcome(text=text, fatal=fatal, errors=errors)


def _rebuild_cover_letter(
    cover: CoverLetterArtifact,
    context: EvidenceContext,
    *,
    job_description: str,
    keyword_terms: list[str],
) -> _RebuildOutcome:
    document = cover.document
    assert document is not None

    # Reconstruct body paragraphs from the immutable ledger records in index
    # order, dropping only rejected ones. This never destroys a paragraph, so a
    # reject followed by a restore reproduces the exact prior document.
    paragraph_records = sorted(
        (r for r in cover.change_ledger if r.change_type is ChangeType.COVER_LETTER_PARAGRAPH),
        key=lambda record: _paragraph_index(record.id),
    )
    if paragraph_records:
        document.body_paragraphs = [
            record.tailored_text for record in paragraph_records if record.status is not ChangeStatus.REJECTED
        ]

    claims: list[ClaimRecord] = []
    repaired = 0
    rejected = 0
    cleaned_paragraphs: list[str] = []
    for index, paragraph in enumerate(document.body_paragraphs):
        outcome = ground_text(
            paragraph, artifact=ArtifactKind.COVER_LETTER, context=context, id_prefix=f"cover-rev-p{index}"
        )
        cleaned_paragraphs.append(outcome.clean_text)
        claims, repaired, rejected = _merge_outcome(outcome, claims, repaired, rejected)
    document.body_paragraphs = cleaned_paragraphs

    text = render_cover_letter_text_from_document(document)
    latex = cover_letter_to_latex(text, _cover_user_info(document))

    # Fatal gates: broken LaTeX, and a letter that a change action has reduced to
    # an unusable length (e.g. rejecting most/all paragraphs). The latter is the
    # atomic-refusal that keeps a valid artifact rather than persisting a
    # degenerate 22-word letter.
    errors = [f"cover letter latex: {error}" for error in validate_latex(latex)]
    body_word_count = sum(len(paragraph.split()) for paragraph in document.body_paragraphs)
    if not document.body_paragraphs or body_word_count < MIN_USABLE_COVER_WORDS:
        errors.append(
            f"completeness: cover letter is not usable after this change "
            f"({body_word_count} body words, minimum {MIN_USABLE_COVER_WORDS})"
        )
    # Warnings, matching initial-generation severity: ideal word-count band,
    # anti-stuffing, JD echo, style.
    warnings = [f"cover letter word count: {message}" for message in validate_cover_letter_word_count(text)]
    warnings.extend(
        _naturalness_warnings(
            text, units=document.body_paragraphs, keyword_terms=keyword_terms, job_description=job_description
        )
    )
    fatal = rejected > 0 or any(is_fatal_validation_error(error) for error in errors)
    _apply_validation(
        cover,
        claims=claims,
        repaired=repaired,
        rejected=rejected,
        fatal=fatal,
        text=text,
        latex=latex,
        extra_warnings=warnings,
    )
    return _RebuildOutcome(text=text, fatal=fatal, errors=errors)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _merge_outcome(
    outcome: GroundingOutcome, claims: list[ClaimRecord], repaired: int, rejected: int
) -> tuple[list[ClaimRecord], int, int]:
    claims.extend(outcome.claims)
    return claims, repaired + outcome.repaired, rejected + outcome.rejected


def _structural_errors(text: str, latex: str, job_description: str) -> list[str]:
    """Structural + anti-stuffing checks that can make a rebuilt resume unusable."""
    errors = [f"resume latex: {error}" for error in validate_latex(latex)]
    if jd_appended_to_resume(text, job_description):
        errors.append("stuffing: the resume echoes a large block of the job description verbatim")
    return errors


def _naturalness_warnings(text: str, *, units: list[str], keyword_terms: list[str], job_description: str) -> list[str]:
    """Style + the authoritative production anti-stuffing / JD-echo report.

    Runs the *same* authoritative naturalness gate initial generation runs, with
    the real unified JD keyword vocabulary and structured units, instead of the
    previous ``validate_naturalness(text, [])`` call whose empty keyword list
    silently disabled keyword-repetition detection.
    """
    warnings = [f"style: {error}" for error in validate_style(text)]
    warnings.extend(
        f"naturalness: {message}"
        for message in production_naturalness_warnings(
            text=text,
            units=[unit for unit in units if unit and unit.strip()],
            keywords=keyword_terms,
            job_description=job_description,
        )
    )
    return warnings


def _apply_validation(
    artifact: ResumeArtifact | CoverLetterArtifact,
    *,
    claims: list[ClaimRecord],
    repaired: int,
    rejected: int,
    fatal: bool,
    text: str,
    latex: str,
    extra_warnings: list[str],
) -> None:
    """Replace the artifact's claim trace, validation, rendered text, and LaTeX.

    Revision-zero claims and rendered output are discarded — everything is rebuilt
    from the current revision's content.
    """
    warnings = list(extra_warnings)
    status = ArtifactStatus.REJECTED if fatal else (ArtifactStatus.REPAIRED if repaired else ArtifactStatus.GENERATED)
    artifact.claims = claims
    artifact.text = "" if fatal else text
    artifact.latex = "" if fatal else latex
    # Reconcile ledger claim links against the freshly rebuilt claim trace: the
    # re-grounding assigns new claim ids, so any link left pointing at a
    # revision-that-no-longer-exists claim is dropped. This guarantees no
    # ``linked_claim_id`` dangles and no stale revision-zero link survives an
    # action. Grounding-removal records keep their permanent-removal reason and
    # text even when their historical link is cleared (the removed content stays
    # gone regardless).
    valid_claim_ids = {claim.id for claim in claims}
    for record in artifact.change_ledger:
        if record.linked_claim_ids:
            record.linked_claim_ids = [cid for cid in record.linked_claim_ids if cid in valid_claim_ids]
    artifact.validation = ArtifactValidation(
        status=status,
        fatal=fatal,
        errors=[] if not fatal else ["revision: rebuilt artifact failed validation"],
        warnings=warnings,
        repaired_claims=repaired,
        rejected_claims=rejected,
    )


def _effective_added(record: ChangeRecord | None) -> str:
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


def _paragraph_index(location_id: str) -> int:
    try:
        return int(location_id.rsplit("::p", 1)[-1])
    except (ValueError, IndexError):
        return 0


def _resume_user_info(document: ResumeDocument) -> dict[str, str]:
    return {"name": document.candidate_name, "headline": document.professional_headline}


def _cover_user_info(document: CoverLetterDocument) -> dict[str, str]:
    return {"name": document.sender_name}


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
    "detect_jd_echo",
    "split_targeting_clause",
]
