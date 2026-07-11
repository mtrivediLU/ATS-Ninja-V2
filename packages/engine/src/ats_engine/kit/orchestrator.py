from __future__ import annotations

from ats_engine.config import EngineSettings
from ats_engine.generation.answers import generate_answers_text
from ats_engine.generation.cover_letter import (
    format_cover_letter_output,
    generate_cover_letter_latex,
    generate_cover_letter_text,
)
from ats_engine.generation.pipeline import run_pipeline, validate_pipeline_result
from ats_engine.generation.resume import (
    format_resume_output,
    generate_resume_latex,
    generate_resume_text,
)
from ats_engine.kit.contract import (
    ORCHESTRATION_VERSION,
    SCHEMA_VERSION,
    AnswerArtifact,
    AnswerItem,
    ApplicationKit,
    ArtifactKind,
    ArtifactStatus,
    ArtifactValidation,
    ClaimRecord,
    CoverLetterArtifact,
    GenerationMetadata,
    ResumeArtifact,
    ValidationSummary,
)
from ats_engine.kit.grounding import EvidenceContext, GroundingOutcome, build_evidence_context, ground_text
from ats_engine.kit.policy import MIN_COVER_LETTER_WORDS
from ats_engine.kit.routing import ResolvedProviders, resolve_providers
from ats_engine.models import AnswerPlan, CoverLetterPlan, Mode, PipelineResult, ResumePlan
from ats_engine.parsing.resume import build_profile
from ats_engine.providers.base import LLMProvider
from ats_engine.validation.severity import is_fatal_validation_error, partition_validation_errors

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

_RESUME_MODES = {Mode.RESUME, Mode.RESUME_AND_COVER, Mode.RESUME_AND_QUESTIONS}
_COVER_MODES = {Mode.COVER_LETTER, Mode.RESUME_AND_COVER}
_ANSWER_MODES = {Mode.QUESTIONS, Mode.RESUME_AND_QUESTIONS}


def generate_application_kit(
    *,
    resume_text: str = "",
    job_description: str = "",
    requested_mode: str = "",
    questions_text: str = "",
    default_mode: Mode | None = None,
    settings: EngineSettings | None = None,
    use_llm: bool = True,
    model_name: str = "",
    extraction_provider: LLMProvider | None = None,
    prose_provider: LLMProvider | None = None,
    fallback_provider: LLMProvider | None = None,
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

    result = run_pipeline(
        resume_text=resume_text,
        job_description=job_description,
        requested_mode=requested_mode,
        questions_text=questions_text,
        default_mode=default_mode,
        settings=resolved_settings,
        use_llm=resolved.llm_available,
        extraction_provider=resolved.extraction,
        prose_provider=resolved.prose,
    )

    # Deterministic evidence view of the candidate (the source of truth for
    # grounding). Never fabricated; the raw resume backstops the structured view.
    profile = build_profile(resume_text)
    if not profile.raw_markdown:
        profile.raw_markdown = resume_text
    context = build_evidence_context(profile, result.jd_profile)

    mode = default_mode if (default_mode is not None and not requested_mode.strip()) else result.parsed_input.mode

    resume_claims: list[ClaimRecord] = []
    cover_claims: list[ClaimRecord] = []
    answer_claims: list[ClaimRecord] = []
    grounding: dict[str, _ArtifactGrounding] = {}

    if mode in _RESUME_MODES and result.resume_plan is not None:
        resume_claims, grounding["resume"] = _ground_resume(result.resume_plan, context)
        result.resume_text = generate_resume_text(result.resume_plan)
        result.resume_latex = generate_resume_latex(result.resume_plan)
        result.mode_outputs[Mode.RESUME.value] = format_resume_output(result.resume_plan, result.resume_latex)

    if mode in _COVER_MODES and result.cover_letter_plan is not None:
        cover_claims, grounding["cover"] = _ground_cover_letter(result.cover_letter_plan, context)
        result.cover_letter_text = generate_cover_letter_text(result.cover_letter_plan)
        result.cover_letter_latex = generate_cover_letter_latex(result.cover_letter_plan)
        result.mode_outputs[Mode.COVER_LETTER.value] = format_cover_letter_output(
            result.cover_letter_plan, result.cover_letter_latex
        )

    if mode in _ANSWER_MODES and result.answer_plan is not None:
        answer_claims, grounding["answers"] = _ground_answers(result.answer_plan, context)
        result.answers_text = generate_answers_text(result.answer_plan)
        result.mode_outputs[Mode.QUESTIONS.value] = result.answers_text

    # Re-validate the clean artifacts with the engine's proven gates.
    result.validation_errors = validate_pipeline_result(result, profile)
    buckets = _bucket_errors(result.validation_errors)

    resume_artifact = (
        _build_resume_artifact(result, resume_claims, grounding.get("resume"), buckets)
        if mode in _RESUME_MODES and result.resume_plan is not None
        else None
    )
    cover_artifact = (
        _build_cover_artifact(result, cover_claims, grounding.get("cover"), buckets)
        if mode in _COVER_MODES and result.cover_letter_plan is not None
        else None
    )
    answers_artifact = (
        _build_answers_artifact(result, answer_claims, grounding.get("answers"), buckets)
        if mode in _ANSWER_MODES and result.answer_plan is not None
        else None
    )

    validation = _kit_validation(result.validation_errors, [resume_artifact, cover_artifact, answers_artifact])
    generation = _generation_metadata(resolved)

    from ats_engine import __version__ as engine_version

    return ApplicationKit(
        schema_version=SCHEMA_VERSION,
        engine_version=engine_version,
        orchestration_version=ORCHESTRATION_VERSION,
        requested_mode=requested_mode,
        resolved_mode=mode.value,
        generation=generation,
        validation=validation,
        resume=resume_artifact,
        cover_letter=cover_artifact,
        answers=answers_artifact,
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


def _ground_resume(plan: ResumePlan, context: EvidenceContext) -> tuple[list[ClaimRecord], _ArtifactGrounding]:
    claims: list[ClaimRecord] = []
    counts = [0, 0]
    fatal = [False]

    plan.summary = _merge(
        ground_text(plan.summary, artifact=ArtifactKind.RESUME, context=context, id_prefix="resume-summary"),
        claims,
        counts,
        fatal,
    )
    for exp_index, experience in enumerate(plan.experience):
        cleaned_bullets: list[str] = []
        for bullet_index, bullet in enumerate(experience.bullets):
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
    artifacts: list[ResumeArtifact | CoverLetterArtifact | AnswerArtifact | None],
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
