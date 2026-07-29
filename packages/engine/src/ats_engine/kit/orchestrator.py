from __future__ import annotations

import logging
import re
import time
from datetime import date

from ats_engine.config import EngineSettings
from ats_engine.generation.answers import generate_answers_text
from ats_engine.generation.cover_letter import (
    format_cover_letter_output,
    generate_cover_letter_latex,
    generate_cover_letter_text,
)
from ats_engine.generation.document_normalization import normalize_generated_prose
from ats_engine.generation.pipeline import resolve_artifact_selection, run_pipeline, validate_pipeline_result
from ats_engine.generation.resume import (
    format_resume_output,
    generate_resume_latex,
    generate_resume_text,
)
from ats_engine.interview_prep import build_interview_prep_artifact
from ats_engine.job_fit import build_job_fit_artifact
from ats_engine.kit.change_ledger import build_cover_letter_change_ledger, build_resume_change_ledger
from ats_engine.kit.contract import (
    ORCHESTRATION_VERSION,
    PRAMANA_VERSION,
    RACHANA_VERSION,
    SCHEMA_VERSION,
    AnswerArtifact,
    AnswerItem,
    ApplicationKit,
    ArtifactKind,
    ArtifactStatus,
    ArtifactValidation,
    ClaimRecord,
    ClaimStatus,
    CoverLetterArtifact,
    CoverLetterDocument,
    DeliveryReport,
    DocumentState,
    GenerationMetadata,
    InterviewPrepArtifact,
    JobFitArtifact,
    KitState,
    LinkedInOutreachArtifact,
    MatchReport,
    OptimizationTrace,
    OutreachContext,
    ResumeArtifact,
    ResumeCertificationEntry,
    ResumeDocument,
    ResumeEducationEntry,
    ResumeExperienceEntry,
    ResumeSkillGroup,
    StageTimings,
    ValidationSummary,
)
from ats_engine.kit.grounding import EvidenceContext, GroundingOutcome, build_evidence_context, ground_text
from ats_engine.kit.policy import MIN_COVER_LETTER_WORDS
from ats_engine.kit.routing import ResolvedProviders, resolve_providers
from ats_engine.linkedin_outreach import build_linkedin_outreach_artifact
from ats_engine.models import AnswerPlan, CoverLetterPlan, Mode, PipelineResult, Profile, ResumePlan
from ats_engine.parsing.resume import build_profile
from ats_engine.providers.base import LLMProvider
from ats_engine.scoring.match_report import build_match_report, build_weighted_keywords
from ats_engine.validation.findings import ValidationFinding
from ats_engine.validation.severity import is_fatal_validation_error, partition_validation_errors

logger = logging.getLogger(__name__)

"""Grounded AI generation orchestrator (Phase 2A, Step 7).

``generate_application_kit`` is the single entry point that turns candidate
evidence + a job description into a trusted, versioned
:class:`~ats_engine.kit.contract.ApplicationKit`. It sits *above* the proven
deterministic engine and composes it — it does not reimplement parsing,
evidence, scoring, or generation. The flow:

1. resolve providers (primary / optional fallback / deterministic);
2. run the existing pipeline (parse -> evidence -> plan -> AI prose -> validate);
3. build a deterministic evidence view of the candidate;
4. **ground every generated artifact's prose** against that evidence, removing or
   rejecting unsupported claims *inside the plans*;
5. re-render text and LaTeX from the sanitized plans, so both are clean by
   construction;
6. re-run the engine's artifact validators on the clean output; and
7. assemble the ApplicationKit with a full claim/evidence trace.

The worker calls this; the ApplicationKit logic never lives in FastAPI or Celery.
"""


def generate_application_kit(
    *,
    resume_text: str = "",
    job_description: str = "",
    requested_mode: str = "",
    questions_text: str = "",
    default_mode: Mode | None = None,
    include_resume: bool | None = None,
    include_cover_letter: bool | None = None,
    include_application_answers: bool | None = None,
    settings: EngineSettings | None = None,
    use_llm: bool = True,
    model_name: str = "",
    extraction_provider: LLMProvider | None = None,
    prose_provider: LLMProvider | None = None,
    fallback_provider: LLMProvider | None = None,
    include_job_fit: bool = True,
    include_interview_prep: bool = True,
    include_linkedin_outreach: bool = True,
    outreach_context: OutreachContext | None = None,
) -> ApplicationKit:
    """Generate a truth-grounded, versioned ApplicationKit."""
    resolved_settings = settings or EngineSettings.from_env()
    resolved = resolve_providers(
        settings=resolved_settings,
        use_llm=use_llm,
        model_name=model_name,
        extraction_provider=extraction_provider,
        prose_provider=prose_provider,
        fallback_provider=fallback_provider,
    )

    legacy_mode = default_mode if default_mode is not None and not requested_mode.strip() else None

    timings: dict[str, int] = {}
    grounding_ms = 0
    render_ms = 0

    _stage = time.perf_counter()
    result = run_pipeline(
        resume_text=resume_text,
        job_description=job_description,
        requested_mode=requested_mode,
        questions_text=questions_text,
        default_mode=default_mode,
        include_resume=include_resume,
        include_cover_letter=include_cover_letter,
        include_application_answers=include_application_answers,
        require_resume_plan=include_job_fit or include_interview_prep or include_linkedin_outreach,
        settings=resolved_settings,
        use_llm=resolved.llm_available,
        extraction_provider=resolved.extraction,
        prose_provider=resolved.prose,
    )
    timings["pipeline_ms"] = _elapsed_ms(_stage)

    # Deterministic evidence view of the candidate (the source of truth for
    # grounding). Never fabricated; the raw resume backstops the structured view.
    profile = build_profile(resume_text)
    if not profile.raw_markdown:
        profile.raw_markdown = resume_text
    context = build_evidence_context(profile, result.jd_profile)

    mode = legacy_mode or result.parsed_input.mode
    selection = resolve_artifact_selection(
        mode,
        include_resume=include_resume,
        include_cover_letter=include_cover_letter,
        include_application_answers=include_application_answers,
    )

    resume_claims: list[ClaimRecord] = []
    cover_claims: list[ClaimRecord] = []
    answer_claims: list[ClaimRecord] = []
    grounding: dict[str, _ArtifactGrounding] = {}

    if selection.resume and result.resume_plan is not None:
        _stage = time.perf_counter()
        discarded_summary = result.metadata.get("discarded_generated_resume_summary")
        resume_claims, grounding["resume"] = _ground_resume(
            result.resume_plan,
            context,
            profile,
            discarded_summary=discarded_summary if isinstance(discarded_summary, str) else "",
        )
        grounding_ms += _elapsed_ms(_stage)
        _stage = time.perf_counter()
        result.resume_text = generate_resume_text(result.resume_plan)
        result.resume_latex = generate_resume_latex(result.resume_plan)
        result.mode_outputs[Mode.RESUME.value] = format_resume_output(result.resume_plan, result.resume_latex)
        render_ms += _elapsed_ms(_stage)

    if selection.cover_letter and result.cover_letter_plan is not None:
        _stage = time.perf_counter()
        cover_claims, grounding["cover"] = _ground_cover_letter(result.cover_letter_plan, context)
        grounding_ms += _elapsed_ms(_stage)
        _stage = time.perf_counter()
        result.cover_letter_text = generate_cover_letter_text(result.cover_letter_plan)
        result.cover_letter_latex = generate_cover_letter_latex(result.cover_letter_plan)
        result.mode_outputs[Mode.COVER_LETTER.value] = format_cover_letter_output(
            result.cover_letter_plan, result.cover_letter_latex
        )
        render_ms += _elapsed_ms(_stage)

    if selection.application_answers and result.answer_plan is not None:
        _stage = time.perf_counter()
        answer_claims, grounding["answers"] = _ground_answers(result.answer_plan, context)
        grounding_ms += _elapsed_ms(_stage)
        result.answers_text = generate_answers_text(result.answer_plan)
        result.mode_outputs[Mode.QUESTIONS.value] = result.answers_text

    timings["grounding_ms"] = grounding_ms
    timings["rendering_ms"] = render_ms

    # Re-validate the clean artifacts with the engine's proven gates.
    result.validation_errors = validate_pipeline_result(result, profile)
    buckets = _bucket_errors(result.validation_errors)

    resume_artifact = (
        _build_resume_artifact(result, resume_claims, grounding.get("resume"), buckets)
        if selection.resume and result.resume_plan is not None
        else None
    )
    cover_artifact = (
        _build_cover_artifact(result, cover_claims, grounding.get("cover"), buckets)
        if selection.cover_letter and result.cover_letter_plan is not None
        else None
    )
    answers_artifact = (
        _build_answers_artifact(result, answer_claims, grounding.get("answers"), buckets)
        if selection.application_answers and result.answer_plan is not None
        else None
    )

    _stage = time.perf_counter()
    job_fit_assessment = None
    if (include_job_fit or include_interview_prep or include_linkedin_outreach) and result.resume_plan is not None:
        job_fit_assessment = build_job_fit_artifact(
            plan=result.resume_plan,
            profile=profile,
            jd_profile=result.jd_profile,
            resume_text=resume_text,
            job_description=job_description,
            context=context,
            provider=resolved.prose if include_job_fit else None,
        )
    job_fit_artifact = job_fit_assessment if include_job_fit else None
    interview_prep_artifact = None
    if include_interview_prep and job_fit_assessment is not None:
        interview_prep_artifact = build_interview_prep_artifact(
            profile=profile,
            jd_profile=result.jd_profile,
            job_fit=job_fit_assessment,
            context=context,
            provider=resolved.prose,
        )

    linkedin_outreach_artifact = None
    if include_linkedin_outreach and job_fit_assessment is not None:
        linkedin_outreach_artifact = build_linkedin_outreach_artifact(
            profile=profile,
            jd_profile=result.jd_profile,
            job_fit=job_fit_assessment,
            evidence_context=context,
            outreach_context=outreach_context,
            provider=resolved.prose,
        )
    timings["artifacts_ms"] = _elapsed_ms(_stage)

    # v5 match report + change ledgers. A failure here must never fail an
    # otherwise-safe kit: the match report becomes None and a bounded warning is
    # added. No candidate content or sensitive detail is ever logged.
    _stage = time.perf_counter()
    kit_warnings: list[str] = []
    trace_raw = result.metadata.get("optimization_trace")
    trace = trace_raw if isinstance(trace_raw, OptimizationTrace) else OptimizationTrace()
    if trace.delivery_state is DocumentState.NEEDS_INPUT_REVIEW and resume_artifact is not None:
        # A floor that failed structural fidelity or score parity is not a
        # deliverable resume. Retain its typed validation/report diagnostics,
        # but never expose or score the disputed projection as if generation
        # had succeeded.
        resume_artifact.text = ""
        resume_artifact.latex = ""
        resume_artifact.document = None
    match_report = _safe_match_report(
        profile=profile,
        result=result,
        resume_artifact=resume_artifact,
        job_fit=job_fit_assessment,
        original_resume_text=resume_text,
        extraction_warnings=list(result.metadata.get("resume_warnings", []) or []),
        kit_warnings=kit_warnings,
    )
    if (
        resolved_settings.tailoring_v2
        and match_report is not None
        and match_report.tailored_ats_match is not None
        and match_report.tailored_ats_match.score + 0.001 < match_report.original_ats_match.score
    ):
        raise AssertionError("Tailoring Engine v2 invariant failed: tailored score regressed below the original score.")
    _attach_change_ledgers(
        resume_artifact=resume_artifact,
        cover_artifact=cover_artifact,
        result=result,
        profile=profile,
        resume_claims=resume_claims,
        cover_claims=cover_claims,
    )
    timings["scoring_ms"] = _elapsed_ms(_stage)

    resume_findings_raw = result.metadata.get("resume_validation_findings")
    resume_findings = (
        [finding for finding in resume_findings_raw if isinstance(finding, ValidationFinding)]
        if isinstance(resume_findings_raw, (list, tuple))
        else []
    )
    delivery_reports = _delivery_reports(
        selection_resume=selection.resume,
        selection_cover=selection.cover_letter,
        selection_answers=selection.application_answers,
        include_job_fit=include_job_fit,
        include_interview_prep=include_interview_prep,
        include_linkedin_outreach=include_linkedin_outreach,
        resume=resume_artifact,
        cover=cover_artifact,
        answers=answers_artifact,
        job_fit=job_fit_artifact,
        interview_prep=interview_prep_artifact,
        linkedin_outreach=linkedin_outreach_artifact,
        resume_findings=resume_findings,
        trace=trace,
    )
    kit_state = _roll_up_kit_state(delivery_reports)
    validation = _kit_validation(
        result.validation_errors,
        [
            resume_artifact,
            cover_artifact,
            answers_artifact,
            job_fit_artifact,
            interview_prep_artifact,
            linkedin_outreach_artifact,
        ],
    )
    generation = _generation_metadata(resolved)
    if job_fit_artifact is not None:
        job_fit_artifact.generation = generation
    if interview_prep_artifact is not None:
        interview_prep_artifact.generation = generation
    if linkedin_outreach_artifact is not None:
        linkedin_outreach_artifact.generation = generation

    from ats_engine import __version__ as engine_version

    return ApplicationKit(
        schema_version=SCHEMA_VERSION,
        engine_version=engine_version,
        orchestration_version=ORCHESTRATION_VERSION,
        requested_mode=requested_mode,
        resolved_mode=selection.code,
        generation=generation,
        validation=validation,
        pramana_version=PRAMANA_VERSION,
        rachana_version=RACHANA_VERSION,
        target_role=(result.jd_profile.title if result.jd_profile.title != "Target Role" else ""),
        target_company=(result.jd_profile.company if result.jd_profile.company != "Target Company" else ""),
        target_confidence=result.jd_profile.parse_confidence,
        state=kit_state,
        delivery_reports=delivery_reports,
        resume=resume_artifact,
        cover_letter=cover_artifact,
        answers=answers_artifact,
        job_fit=job_fit_artifact,
        interview_prep=interview_prep_artifact,
        linkedin_outreach=linkedin_outreach_artifact,
        match_report=match_report,
        stage_timings=StageTimings(
            stages_ms={stage: 0 for stage in timings} if not use_llm else timings,
        ),
        revision=0,
        warnings=kit_warnings,
    )


# --------------------------------------------------------------------------- #
# Grounding of plans (mutates the plan prose in place, returns the trace)
# --------------------------------------------------------------------------- #
class _ArtifactGrounding:
    __slots__ = ("fatal", "repaired", "rejected")

    def __init__(self, fatal: bool, repaired: int, rejected: int) -> None:
        self.fatal = fatal
        self.repaired = repaired
        self.rejected = rejected


def _merge(outcome: GroundingOutcome, claims: list[ClaimRecord], state: list[int], fatal: list[bool]) -> str:
    claims.extend(outcome.claims)
    state[0] += outcome.repaired
    state[1] += outcome.rejected
    fatal[0] = fatal[0] or outcome.fatal
    return outcome.clean_text


def _ground_resume(
    plan: ResumePlan,
    context: EvidenceContext,
    profile: Profile,
    *,
    discarded_summary: str = "",
) -> tuple[list[ClaimRecord], _ArtifactGrounding]:
    claims: list[ClaimRecord] = []
    counts = [0, 0]
    fatal = [False]

    # Every delivered summary crosses the authoritative truth gate, including
    # summaries assembled from resolver-backed placement actions.  Placement
    # provenance is useful evidence, but it must never become a bypass through
    # which an otherwise-valid structured provider response can add an
    # unsupported responsibility, management claim, or level of expertise.
    plan.summary = _merge(
        ground_text(plan.summary, artifact=ArtifactKind.RESUME, context=context, id_prefix="resume-summary"),
        claims,
        counts,
        fatal,
    )

    if discarded_summary.strip():
        # Model prose replaced by the optimizer never reaches the artifact, but
        # its truth-gate disposition must remain auditable. It is already
        # withheld from output, so a repair/rejection here cannot make the
        # delivered source-backed resume fatal.
        outcome = ground_text(
            discarded_summary,
            artifact=ArtifactKind.RESUME,
            context=context,
            id_prefix="resume-discarded-summary",
        )
        claims.extend(outcome.claims)
        counts[0] += outcome.repaired

    source_bullets = {
        _normalized_source_bullet(bullet) for experience in profile.experiences for bullet in experience.bullets
    }
    for exp_index, experience in enumerate(plan.experience):
        cleaned_bullets: list[str] = []
        for bullet_index, bullet in enumerate(experience.bullets):
            # Candidate-authored bullets are evidence, not model output.  They
            # must pass through byte-for-byte rather than be paraphrased or
            # truncated by a heuristic claim repair pass.  Non-source bullets
            # are still fully grounded below.
            if _normalized_source_bullet(bullet) in source_bullets:
                claims.extend(
                    _supported_claim_trace(
                        bullet,
                        ArtifactKind.RESUME,
                        context,
                        f"resume-exp{exp_index}-bullet{bullet_index}",
                        granularity="span",
                    )
                )
                cleaned_bullets.append(bullet)
                continue
            cleaned_bullets.append(
                _merge(
                    ground_text(
                        bullet,
                        artifact=ArtifactKind.RESUME,
                        context=context,
                        id_prefix=f"resume-exp{exp_index}-bullet{bullet_index}",
                        granularity="span",
                    ),
                    claims,
                    counts,
                    fatal,
                )
            )
        experience.bullets = cleaned_bullets
    return claims, _ArtifactGrounding(fatal[0], counts[0], counts[1])


def _normalized_source_bullet(value: str) -> str:
    """Return a punctuation-insensitive identity key for source bullet checks."""
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _supported_claim_trace(
    text: str,
    artifact: ArtifactKind,
    context: EvidenceContext,
    id_prefix: str,
    *,
    granularity: str = "prose",
) -> list[ClaimRecord]:
    """Record supported source claims without allowing repair to mutate them."""
    outcome = ground_text(text, artifact=artifact, context=context, id_prefix=id_prefix, granularity=granularity)
    return [claim for claim in outcome.claims if claim.status is ClaimStatus.SUPPORTED]


def _ground_cover_letter(
    plan: CoverLetterPlan, context: EvidenceContext
) -> tuple[list[ClaimRecord], _ArtifactGrounding]:
    claims: list[ClaimRecord] = []
    counts = [0, 0]
    fatal = [False]

    cleaned: list[str] = []
    for index, paragraph in enumerate(plan.body_paragraphs):
        if paragraph.strip().lower().startswith("dear "):
            cleaned.append(paragraph)
            continue
        clean_paragraph = _merge(
            ground_text(
                paragraph,
                artifact=ArtifactKind.COVER_LETTER,
                context=context,
                id_prefix=f"cover-p{index}",
            ),
            claims,
            counts,
            fatal,
        )
        if clean_paragraph.strip():
            cleaned.append(clean_paragraph)
    plan.body_paragraphs = cleaned

    # If repair gutted the letter below a usable length, treat it as rejected.
    if _cover_body_words(cleaned) < MIN_COVER_LETTER_WORDS:
        fatal[0] = True
    return claims, _ArtifactGrounding(fatal[0], counts[0], counts[1])


def _ground_answers(plan: AnswerPlan, context: EvidenceContext) -> tuple[list[ClaimRecord], _ArtifactGrounding]:
    claims: list[ClaimRecord] = []
    counts = [0, 0]
    fatal = [False]

    cleaned: list[str] = []
    for index, answer in enumerate(plan.answers):
        cleaned.append(
            _merge(
                ground_text(
                    answer,
                    artifact=ArtifactKind.ANSWERS,
                    context=context,
                    id_prefix=f"answer-{index}",
                ),
                claims,
                counts,
                fatal,
            )
        )
    plan.answers = cleaned
    return claims, _ArtifactGrounding(fatal[0], counts[0], counts[1])


def _cover_body_words(paragraphs: list[str]) -> int:
    body = " ".join(p for p in paragraphs if not p.strip().lower().startswith("dear "))
    return len(body.split())


# --------------------------------------------------------------------------- #
# Artifact assembly
# --------------------------------------------------------------------------- #
def _bucket_errors(errors: list[str]) -> dict[str, list[str]]:
    buckets: dict[str, list[str]] = {"resume": [], "cover": [], "answers": []}
    for error in errors:
        lowered = error.lower()
        if lowered.startswith("cover letter") or "cover letter" in lowered:
            buckets["cover"].append(error)
        elif lowered.startswith("answers"):
            buckets["answers"].append(error)
        else:
            buckets["resume"].append(error)
    return buckets


_DeliverableArtifact = (
    ResumeArtifact
    | CoverLetterArtifact
    | AnswerArtifact
    | JobFitArtifact
    | InterviewPrepArtifact
    | LinkedInOutreachArtifact
)


def _document_delivery_report(
    *,
    requested: bool,
    artifact: _DeliverableArtifact | None,
    findings: list[ValidationFinding] | None = None,
    preferred_state: DocumentState = DocumentState.GENERATED,
    fallback_reason: str = "",
    calibration_suppressed: list[str] | None = None,
) -> DeliveryReport:
    if not requested:
        return DeliveryReport(state=DocumentState.NOT_REQUESTED)
    if preferred_state is DocumentState.NEEDS_INPUT_REVIEW:
        return DeliveryReport(
            state=DocumentState.NEEDS_INPUT_REVIEW,
            findings=list(findings or []),
            fallback_reason=fallback_reason or "The input requires review before this artifact can be delivered.",
            calibration_suppressed=list(calibration_suppressed or []),
        )
    if artifact is None:
        return DeliveryReport(
            state=DocumentState.FAILED,
            findings=list(findings or []),
            fallback_reason=fallback_reason or "The requested artifact could not be generated.",
            calibration_suppressed=list(calibration_suppressed or []),
        )
    if artifact.validation.fatal:
        return DeliveryReport(
            state=DocumentState.FAILED,
            findings=list(findings or []),
            fallback_reason=fallback_reason or "A truth-critical validation gate blocked this artifact.",
            calibration_suppressed=list(calibration_suppressed or []),
        )
    repaired = artifact.validation.status is ArtifactStatus.REPAIRED
    state = (
        DocumentState.GENERATED_WITH_FALLBACK
        if preferred_state is DocumentState.GENERATED_WITH_FALLBACK or repaired
        else DocumentState.GENERATED
    )
    reason = fallback_reason
    if repaired and not reason:
        reason = "Unsupported generated claims were removed before delivery."
    return DeliveryReport(
        state=state,
        findings=list(findings or []),
        fallback_reason=reason or None,
        calibration_suppressed=list(calibration_suppressed or []),
    )


def _delivery_reports(
    *,
    selection_resume: bool,
    selection_cover: bool,
    selection_answers: bool,
    include_job_fit: bool,
    include_interview_prep: bool,
    include_linkedin_outreach: bool,
    resume: ResumeArtifact | None,
    cover: CoverLetterArtifact | None,
    answers: AnswerArtifact | None,
    job_fit: JobFitArtifact | None,
    interview_prep: InterviewPrepArtifact | None,
    linkedin_outreach: LinkedInOutreachArtifact | None,
    resume_findings: list[ValidationFinding],
    trace: OptimizationTrace,
) -> dict[ArtifactKind, DeliveryReport]:
    return {
        ArtifactKind.RESUME: _document_delivery_report(
            requested=selection_resume,
            artifact=resume,
            findings=resume_findings,
            preferred_state=trace.delivery_state,
            fallback_reason=trace.fallback_reason,
            calibration_suppressed=trace.calibration_suppressed,
        ),
        ArtifactKind.COVER_LETTER: _document_delivery_report(
            requested=selection_cover,
            artifact=cover,
        ),
        ArtifactKind.ANSWERS: _document_delivery_report(
            requested=selection_answers,
            artifact=answers,
        ),
        ArtifactKind.JOB_FIT: _document_delivery_report(
            requested=include_job_fit,
            artifact=job_fit,
        ),
        ArtifactKind.INTERVIEW_PREP: _document_delivery_report(
            requested=include_interview_prep,
            artifact=interview_prep,
        ),
        ArtifactKind.LINKEDIN_OUTREACH: _document_delivery_report(
            requested=include_linkedin_outreach,
            artifact=linkedin_outreach,
        ),
    }


def _roll_up_kit_state(reports: dict[ArtifactKind, DeliveryReport]) -> KitState:
    delivered = {DocumentState.GENERATED, DocumentState.GENERATED_WITH_FALLBACK}
    primary = [
        reports[kind]
        for kind in (ArtifactKind.RESUME, ArtifactKind.COVER_LETTER)
        if reports[kind].state is not DocumentState.NOT_REQUESTED
    ]
    secondary = [
        report
        for kind, report in reports.items()
        if kind not in {ArtifactKind.RESUME, ArtifactKind.COVER_LETTER}
        and report.state is not DocumentState.NOT_REQUESTED
    ]
    requested = [*primary, *secondary]
    if not requested:
        return KitState.COMPLETED
    if primary:
        if any(report.state is DocumentState.NEEDS_INPUT_REVIEW for report in primary):
            return KitState.NEEDS_INPUT_REVIEW
        if all(report.state in delivered for report in primary):
            if any(report.state not in delivered for report in secondary):
                return KitState.PARTIALLY_COMPLETED
            return KitState.COMPLETED
        if any(report.state in delivered for report in primary):
            return KitState.PARTIALLY_COMPLETED
        return KitState.FAILED
    if any(report.state is DocumentState.NEEDS_INPUT_REVIEW for report in requested):
        return KitState.NEEDS_INPUT_REVIEW
    if all(report.state in delivered for report in requested):
        return KitState.COMPLETED
    if any(report.state in delivered for report in requested):
        return KitState.PARTIALLY_COMPLETED
    return KitState.FAILED


def _artifact_validation(
    errors: list[str],
    grounding: _ArtifactGrounding | None,
) -> ArtifactValidation:
    fatal_errors = [error for error in errors if is_fatal_validation_error(error)]
    warnings = [error for error in errors if not is_fatal_validation_error(error)]
    repaired = grounding.repaired if grounding else 0
    rejected = grounding.rejected if grounding else 0
    grounding_fatal = grounding.fatal if grounding else False
    fatal = bool(fatal_errors) or grounding_fatal

    if fatal:
        status = ArtifactStatus.REJECTED
    elif repaired > 0:
        status = ArtifactStatus.REPAIRED
    else:
        status = ArtifactStatus.GENERATED

    return ArtifactValidation(
        status=status,
        fatal=fatal,
        errors=fatal_errors,
        warnings=warnings,
        repaired_claims=repaired,
        rejected_claims=rejected,
    )


def _build_resume_artifact(
    result: PipelineResult,
    claims: list[ClaimRecord],
    grounding: _ArtifactGrounding | None,
    buckets: dict[str, list[str]],
) -> ResumeArtifact:
    validation = _artifact_validation(buckets["resume"], grounding)
    withheld = validation.fatal
    return ResumeArtifact(
        text="" if withheld else result.resume_text,
        latex="" if withheld else result.resume_latex,
        validation=validation,
        claims=claims,
        interview_probability=(result.resume_plan.interview_probability if result.resume_plan else None),
        document=None if withheld or result.resume_plan is None else _resume_document(result.resume_plan),
    )


def _build_cover_artifact(
    result: PipelineResult,
    claims: list[ClaimRecord],
    grounding: _ArtifactGrounding | None,
    buckets: dict[str, list[str]],
) -> CoverLetterArtifact:
    validation = _artifact_validation(buckets["cover"], grounding)
    withheld = validation.fatal
    return CoverLetterArtifact(
        text="" if withheld else result.cover_letter_text,
        latex="" if withheld else result.cover_letter_latex,
        validation=validation,
        claims=claims,
        document=None if withheld or result.cover_letter_plan is None else _cover_document(result.cover_letter_plan),
    )


def _contact_lines(plan: ResumePlan | CoverLetterPlan) -> list[str]:
    contact = plan.contacts
    return [
        normalize_generated_prose(value)
        for value in (contact.email, contact.phone, contact.location, contact.linkedin, contact.website)
        if normalize_generated_prose(value)
    ]


def _resume_document(plan: ResumePlan) -> ResumeDocument:
    """Project the already-grounded plan into presentation fields without inference."""
    return ResumeDocument(
        candidate_name=normalize_generated_prose(plan.contacts.name),
        professional_headline=normalize_generated_prose(plan.headline),
        contact_lines=_contact_lines(plan),
        summary=normalize_generated_prose(plan.summary),
        skill_groups=[
            ResumeSkillGroup(
                normalize_generated_prose(label),
                [normalize_generated_prose(item) for item in items if normalize_generated_prose(item)],
            )
            for label, items in plan.skill_groups
            if normalize_generated_prose(label) or items
        ],
        experience=[
            ResumeExperienceEntry(
                employer=normalize_generated_prose(item.company),
                title=normalize_generated_prose(item.title),
                location=normalize_generated_prose(item.location),
                date_range=normalize_generated_prose(item.dates),
                bullets=[
                    normalize_generated_prose(bullet) for bullet in item.bullets if normalize_generated_prose(bullet)
                ],
            )
            for item in plan.experience
        ],
        education=[
            ResumeEducationEntry(
                institution=normalize_generated_prose(item.institution),
                degree=normalize_generated_prose(item.degree),
                location=normalize_generated_prose(item.location),
                date_range=normalize_generated_prose(item.dates),
                details=[
                    normalize_generated_prose(detail) for detail in item.bullets if normalize_generated_prose(detail)
                ],
            )
            for item in plan.education
        ],
        certifications=[
            ResumeCertificationEntry(
                normalize_generated_prose(item.name),
                normalize_generated_prose(item.date),
                normalize_generated_prose(item.link),
                normalize_generated_prose(item.credential_id),
            )
            for item in plan.certifications
            if normalize_generated_prose(item.name)
        ],
        remaining_sections=[
            (
                normalize_generated_prose(heading),
                [normalize_generated_prose(line) for line in lines if normalize_generated_prose(line)],
            )
            for heading, lines in plan.remaining_sections
            if any(normalize_generated_prose(line) for line in lines)
        ],
    )


def _cover_document(plan: CoverLetterPlan) -> CoverLetterDocument:
    company = plan.jd_profile.company if plan.jd_profile.company != "Target Company" else ""
    role = plan.jd_profile.title if plan.jd_profile.title != "Target Role" else ""
    return CoverLetterDocument(
        sender_name=normalize_generated_prose(plan.contacts.name),
        sender_contact_lines=_contact_lines(plan),
        date=date.today().strftime("%B %d, %Y").replace(" 0", " "),
        recipient_company=normalize_generated_prose(company),
        target_role=normalize_generated_prose(role),
        greeting="Dear Hiring Manager,",
        body_paragraphs=[
            normalize_generated_prose(paragraph)
            for paragraph in plan.body_paragraphs
            if normalize_generated_prose(paragraph)
        ],
        closing="Sincerely,",
        signature_name=normalize_generated_prose(plan.contacts.name),
    )


def _build_answers_artifact(
    result: PipelineResult,
    claims: list[ClaimRecord],
    grounding: _ArtifactGrounding | None,
    buckets: dict[str, list[str]],
) -> AnswerArtifact:
    validation = _artifact_validation(buckets["answers"], grounding)
    withheld = validation.fatal
    items: list[AnswerItem] = []
    placeholders: list[str] = []
    if result.answer_plan is not None:
        items = [
            AnswerItem(question=question, answer=answer)
            for question, answer in zip(result.answer_plan.questions, result.answer_plan.answers, strict=False)
        ]
        placeholders = list(result.answer_plan.placeholders)
    return AnswerArtifact(
        items=[] if withheld else items,
        text="" if withheld else result.answers_text,
        validation=validation,
        claims=claims,
        placeholders=placeholders,
    )


def _kit_validation(
    errors: list[str],
    artifacts: list[
        ResumeArtifact
        | CoverLetterArtifact
        | AnswerArtifact
        | JobFitArtifact
        | InterviewPrepArtifact
        | LinkedInOutreachArtifact
        | None
    ],
) -> ValidationSummary:
    fatal_errors, warnings = partition_validation_errors(errors)
    fatal = any(artifact is not None and artifact.validation.fatal for artifact in artifacts)
    return ValidationSummary(
        passed=not fatal,
        fatal=fatal,
        error_count=len(fatal_errors),
        warning_count=len(warnings),
        errors=fatal_errors,
        warnings=warnings,
    )


def _generation_metadata(resolved: ResolvedProviders) -> GenerationMetadata:
    return GenerationMetadata(
        generation_mode=resolved.generation_mode,
        llm_available=resolved.llm_available,
        provider=resolved.provider_identity,
        model=resolved.model,
        provider_calls=resolved.stats.calls,
        fallback_used=resolved.stats.fallback_used,
    )


# --------------------------------------------------------------------------- #
# v5 match report + change ledger (Step 10-11)
# --------------------------------------------------------------------------- #
def _elapsed_ms(start: float) -> int:
    return max(0, int((time.perf_counter() - start) * 1000))


def _safe_match_report(
    *,
    profile: Profile,
    result: PipelineResult,
    resume_artifact: ResumeArtifact | None,
    job_fit: JobFitArtifact | None,
    original_resume_text: str,
    extraction_warnings: list[str],
    kit_warnings: list[str],
) -> MatchReport | None:
    """Compute the match report; never fail an otherwise-safe kit if it errors."""
    if result.resume_plan is None:
        return None
    tailored_text: str | None = None
    if resume_artifact is not None and not resume_artifact.validation.fatal and resume_artifact.text:
        tailored_text = resume_artifact.text
    try:
        trace = result.metadata.get("optimization_trace")
        return build_match_report(
            profile=profile,
            jd_profile=result.jd_profile,
            resume_plan=result.resume_plan,
            original_resume_text=original_resume_text,
            tailored_resume_text=tailored_text,
            job_fit=job_fit,
            extraction_warnings=extraction_warnings,
            optimization_trace=trace if isinstance(trace, OptimizationTrace) else None,
        )
    except Exception:  # noqa: BLE001 - a scoring failure must not fail a safe kit.
        logger.warning("match report computation failed; delivering kit without scores")
        kit_warnings.append("Match scores were unavailable for this run.")
        return None


def _attach_change_ledgers(
    *,
    resume_artifact: ResumeArtifact | None,
    cover_artifact: CoverLetterArtifact | None,
    result: PipelineResult,
    profile: Profile,
    resume_claims: list[ClaimRecord],
    cover_claims: list[ClaimRecord],
) -> None:
    """Build and attach the transparent change ledgers to the artifacts."""
    if result.resume_plan is None:
        return
    try:
        evidence = result.resume_plan.evidence
        keywords = build_weighted_keywords(evidence, result.jd_profile)
        tier_by_keyword = {item.keyword.casefold().strip(): item.evidence_tier for item in evidence}
        if resume_artifact is not None:
            resume_artifact.change_ledger = build_resume_change_ledger(
                decisions=result.resume_plan.plan_decisions,
                document=resume_artifact.document,
                claims=resume_claims,
                keywords=keywords,
                profile=profile,
                tier_by_keyword=tier_by_keyword,
                full_text=resume_artifact.text,
                # Typed inputs, preferred: each change's impact then uses the
                # same PRAMANA-backed formula as the headline MatchReport
                # score, not a coarser WeightedKeyword conversion that could
                # silently disagree with it.
                requirements=result.resume_plan.requirements,
                links=result.resume_plan.evidence_links,
            )
        if cover_artifact is not None:
            cover_artifact.change_ledger = build_cover_letter_change_ledger(
                document=cover_artifact.document,
                claims=cover_claims,
                keywords=keywords,
                profile=profile,
                tier_by_keyword=tier_by_keyword,
                full_text=cover_artifact.text,
                requirements=result.resume_plan.requirements,
                links=result.resume_plan.evidence_links,
            )
    except Exception:  # noqa: BLE001 - a ledger failure must not fail a safe kit.
        logger.warning("change ledger construction failed; delivering kit without a ledger")
