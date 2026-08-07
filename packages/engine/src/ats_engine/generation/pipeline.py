from __future__ import annotations

import re
from dataclasses import asdict
from typing import Any, cast

from ats_engine.config import EngineSettings
from ats_engine.evidence.quality_report import build_ats_quality_report
from ats_engine.generation.answers import generate_answers_text
from ats_engine.generation.cover_letter import (
    format_cover_letter_output,
    generate_cover_letter_latex,
    generate_cover_letter_text,
)
from ats_engine.generation.optimizer import (
    ResumeGateContext,
    build_resume_gate_context,
    optimize,
    validate_resume_plan_findings,
)
from ats_engine.generation.planning import (
    build_answer_plan,
    build_cover_letter_plan,
    build_resume_plan,
)
from ats_engine.generation.resume import (
    format_resume_output,
    generate_resume_latex,
    generate_resume_text,
)
from ats_engine.models import ArtifactSelection, JDProfile, Mode, ParsedInput, PipelineResult, Profile
from ats_engine.parsing.contact_integrity import validate_contact_integrity
from ats_engine.parsing.input import detect_mode, parse_input
from ats_engine.parsing.job_description import parse_jd
from ats_engine.parsing.resume import build_profile
from ats_engine.providers.base import LLMProvider, run_concurrently
from ats_engine.providers.ollama import ollama_provider_pair
from ats_engine.validation.claims import validate_claims
from ats_engine.validation.completeness import validate_completeness
from ats_engine.validation.findings import ValidationFinding, ValidationSeverity
from ats_engine.validation.latex import validate_latex
from ats_engine.validation.naturalness import production_naturalness_warnings
from ats_engine.validation.output_format import (
    validate_cover_letter_word_count,
    validate_output_format,
)
from ats_engine.validation.style import validate_style

"""End-to-end generation pipeline.

Composes parsing -> evidence/scoring -> planning -> generation -> validation.
Every fact comes from the candidate's own resume plus the job description; no
hardcoded personal data is involved. When a provider is available it raises
generation quality; when it is not, every step falls back to deterministic,
validator-checked logic so the pipeline keeps working.

This lower-level pipeline produces the resume, cover letter, and application
answers. The grounded ApplicationKit orchestrator composes its result with
JobFit, InterviewPrep, and LinkedInOutreach artifacts.
"""


def run_pipeline(
    *,
    uploaded_resume_pdf: Any | None = None,
    resume_text: str = "",
    job_description: str = "",
    overrides: dict[str, str] | None = None,
    logistics: dict[str, str] | None = None,
    questions_text: str = "",
    requested_mode: str = "",
    default_mode: Mode | None = None,
    include_resume: bool | None = None,
    include_cover_letter: bool | None = None,
    include_application_answers: bool | None = None,
    require_resume_plan: bool = False,
    model_name: str = "",
    settings: EngineSettings | None = None,
    use_llm: bool = True,
    extraction_provider: LLMProvider | None = None,
    prose_provider: LLMProvider | None = None,
) -> PipelineResult:
    """Run the complete ATS-Ninja generation pipeline.

    Provider selection:
      * Pass ``extraction_provider``/``prose_provider`` to inject providers explicitly.
      * Set ``use_llm=False`` to force the fully-deterministic path (used by tests).
      * Otherwise providers are auto-detected from ``settings`` (Ollama today);
        both are ``None`` when no server is reachable, so generation still works.

    ``default_mode`` lets a caller state the product's default output shape when
    the user did not request one explicitly (replacing a legacy UI-layer magic
    string). It only applies when ``requested_mode`` yields no explicit intent.
    """
    parsed_input = parse_input(
        uploaded_resume_pdf=uploaded_resume_pdf,
        resume_text=resume_text,
        job_description=job_description,
        overrides=overrides or {},
        logistics=logistics or {},
        questions_text=questions_text,
        requested_mode=requested_mode,
    )
    mode = default_mode if default_mode is not None and not requested_mode.strip() else parsed_input.mode
    selection = resolve_artifact_selection(
        mode,
        include_resume=include_resume,
        include_cover_letter=include_cover_letter,
        include_application_answers=include_application_answers,
    )

    resolved_settings = settings or EngineSettings.from_env()
    if extraction_provider is not None or prose_provider is not None:
        extraction, prose = extraction_provider, prose_provider
    elif not use_llm:
        extraction, prose = None, None
    else:
        extraction, prose = ollama_provider_pair(resolved_settings, model=model_name or None)

    profile, jd_profile = _parse_profile_and_jd(
        parsed_input,
        extraction,
        tailoring_v2=resolved_settings.tailoring_v2,
    )

    result = PipelineResult(parsed_input=parsed_input, jd_profile=jd_profile)
    result.metadata["llm_available"] = extraction is not None
    result.metadata["resume_warnings"] = list(profile.extraction_warnings)
    resume_plan = None
    if selection.resume or selection.cover_letter or selection.application_answers or require_resume_plan:
        resume_plan = build_resume_plan(
            contacts=parsed_input.contacts,
            jd_profile=jd_profile,
            profile=profile,
            provider=prose,
            batch_provider=extraction,
        )
        # V2 always projects the generated plan back onto candidate-authored
        # source content, even when the JD yields no actionable requirements.
        # In that zero-requirements case the optimizer has no placements to
        # make, but its source-content projection is still the boundary that
        # prevents an otherwise-valid LLM bullet rewrite from becoming the
        # delivered resume.
        if resolved_settings.tailoring_v2:
            generated_summary = resume_plan.summary
            gate_context = (
                build_resume_gate_context(profile, resume_plan)
                if resolved_settings.delivery_first
                else ResumeGateContext()
            )
            resume_plan, optimization_trace = optimize(
                profile,
                jd_profile,
                resume_plan.requirements,
                resume_plan.evidence_links,
                resume_plan,
                gate_context=gate_context,
                accept_generated_prose=prose is not None,
                delivery_first=resolved_settings.delivery_first,
                optimizer_policy=resolved_settings.optimizer_policy,
            )
            result.metadata["optimization_trace"] = optimization_trace
            result.metadata["resume_gate_context"] = gate_context
            if prose is not None and generated_summary.strip() and generated_summary != resume_plan.summary:
                # The optimizer intentionally starts from source content. Keep
                # discarded model prose for the orchestrator's claim trace so
                # an unsafe model attempt is visible rather than silently lost.
                result.metadata["discarded_generated_resume_summary"] = generated_summary
        result.resume_plan = resume_plan

    if selection.resume and resume_plan is not None:
        result.resume_text = generate_resume_text(resume_plan)
        result.resume_latex = generate_resume_latex(resume_plan)
        result.mode_outputs[Mode.RESUME.value] = format_resume_output(resume_plan, result.resume_latex)
        # Internal-only diagnostic (not the ApplicationKit contract): a
        # transparent tally of the grounded evidence matrix already computed
        # above, never a predicted match score. See evidence/quality_report.py.
        result.metadata["ats_quality_report"] = asdict(
            build_ats_quality_report(
                evidence=resume_plan.evidence,
                jd_profile=jd_profile,
                resume_plan=resume_plan,
                resume_text=result.resume_text,
            )
        )

    if selection.cover_letter and resume_plan is not None:
        cover_plan = build_cover_letter_plan(resume_plan, profile, provider=prose)
        result.cover_letter_plan = cover_plan
        result.cover_letter_text = generate_cover_letter_text(cover_plan)
        result.cover_letter_latex = generate_cover_letter_latex(cover_plan)
        result.mode_outputs[Mode.COVER_LETTER.value] = format_cover_letter_output(cover_plan, result.cover_letter_latex)

    if selection.application_answers and resume_plan is not None:
        answer_plan = build_answer_plan(questions=parsed_input.questions, resume_plan=resume_plan, provider=prose)
        result.answer_plan = answer_plan
        result.answers_text = generate_answers_text(answer_plan)
        result.mode_outputs[Mode.QUESTIONS.value] = result.answers_text

    result.validation_errors = validate_pipeline_result(result, profile)
    return result


def resolve_artifact_selection(
    mode: Mode,
    *,
    include_resume: bool | None = None,
    include_cover_letter: bool | None = None,
    include_application_answers: bool | None = None,
) -> ArtifactSelection:
    """Resolve optional explicit flags over a backward-compatible legacy mode."""
    legacy = ArtifactSelection(
        resume=mode in {Mode.RESUME, Mode.RESUME_AND_COVER, Mode.RESUME_AND_QUESTIONS},
        cover_letter=mode in {Mode.COVER_LETTER, Mode.RESUME_AND_COVER},
        application_answers=mode in {Mode.QUESTIONS, Mode.RESUME_AND_QUESTIONS},
    )
    return ArtifactSelection(
        resume=legacy.resume if include_resume is None else include_resume,
        cover_letter=legacy.cover_letter if include_cover_letter is None else include_cover_letter,
        application_answers=(
            legacy.application_answers if include_application_answers is None else include_application_answers
        ),
    )


def _parse_profile_and_jd(
    parsed_input: ParsedInput,
    extraction: LLMProvider | None,
    *,
    tailoring_v2: bool,
) -> tuple[Profile, JDProfile]:
    """Build the candidate profile and parse the JD.

    Both are independent provider calls, so when a model is available they run
    concurrently. Without a model, this is all fast heuristics anyway, and
    running profile extraction first lets JD parsing's heuristic fallback use the
    candidate's own tiered vocabulary for keyword matching.
    """
    if extraction is None:
        profile = build_profile(parsed_input.resume_text, provider=None)
        jd_profile = parse_jd(
            parsed_input.job_description,
            profile=profile,
            provider=None,
            tailoring_v2=tailoring_v2,
        )
        return profile, jd_profile

    results = run_concurrently(
        {
            "profile": lambda: build_profile(parsed_input.resume_text, provider=extraction),
            "jd_profile": lambda: parse_jd(
                parsed_input.job_description,
                profile=None,
                provider=extraction,
                tailoring_v2=tailoring_v2,
            ),
        }
    )
    return cast(Profile, results["profile"]), cast(JDProfile, results["jd_profile"])


def validate_pipeline_result(result: PipelineResult, profile: Profile | None = None) -> list[str]:
    """Run all silent validation gates and return readable errors."""
    if profile is None:
        profile = build_profile(result.parsed_input.resume_text)
    errors: list[str] = []
    errors.extend(f"extraction_suspect: {warning}" for warning in profile.extraction_warnings)
    # The plan's own removal ledger is what makes an accepted PRUNE legible to
    # the completeness gate. It is not taken on trust: every entry is verified
    # against the source profile and the rendered text inside the gate, and an
    # unledgered disappearance still fails and still withholds the resume.
    removed = list(result.resume_plan.removed_content) if result.resume_plan is not None else []
    errors.extend(validate_completeness(result, profile, removed))
    # Non-fatal by design (the "contact:" prefix is not in FATAL_MARKERS): a
    # syntactically odd contact field is worth a review warning, not a
    # withheld artifact — the reviewed text is never rewritten or guessed.
    errors.extend(
        [f"contact: {warning}" for warning in validate_contact_integrity(result.parsed_input.contacts).warnings]
    )
    jd_keywords = list(result.jd_profile.technical_keywords)
    job_description = result.parsed_input.job_description
    if result.resume_latex:
        errors.extend([f"resume: {error}" for error in validate_latex(result.resume_latex)])
        # Style policy governs generated prose, not verbatim candidate bullets.
        # Checking the complete rendered document used to force a global repair
        # pass that weakened source wording. Validate only the plan units that
        # the engine authored or explicitly rewrote.
        if result.resume_plan is not None:
            errors.extend(f"resume: {error}" for error in validate_style(result.resume_plan.summary))
            for decision in result.resume_plan.plan_decisions:
                if decision.kind == "bullet" and decision.original_text != decision.tailored_text:
                    errors.extend(f"resume: {error}" for error in validate_style(decision.tailored_text))
            context = result.metadata.get("resume_gate_context")
            gate_context = (
                context
                if isinstance(context, ResumeGateContext)
                else build_resume_gate_context(profile, result.resume_plan)
            )
            findings = validate_resume_plan_findings(
                result.resume_plan,
                profile,
                result.resume_plan.requirements,
                result.resume_plan.placement_actions,
                gate_context,
                rendered_text=result.resume_text,
            )
            result.metadata["resume_validation_findings"] = findings
            errors.extend(_finding_message(finding) for finding in findings)
        errors.extend([f"resume: {error}" for error in validate_claims(result.resume_latex, profile)])
        errors.extend(
            [
                f"resume output: {error}"
                for error in validate_output_format(result.mode_outputs[Mode.RESUME.value], Mode.RESUME)
            ]
        )
        # Authoritative anti-stuffing / JD-echo gate on the delivered resume text
        # (the same gate the change-action path runs). Warnings, not fatal.
        errors.extend(
            f"resume: naturalness: {message}"
            for message in production_naturalness_warnings(
                text=result.resume_text,
                units=_resume_bullet_units(result.resume_text),
                keywords=jd_keywords,
                job_description=job_description,
            )
        )
    if result.cover_letter_latex:
        errors.extend([f"cover letter: {error}" for error in validate_latex(result.cover_letter_latex)])
        errors.extend([f"cover letter: {error}" for error in validate_style(result.cover_letter_latex)])
        errors.extend([f"cover letter: {error}" for error in validate_claims(result.cover_letter_latex, profile)])
        errors.extend(
            [f"cover letter: {error}" for error in validate_cover_letter_word_count(result.cover_letter_text)]
        )
        errors.extend(
            f"cover letter: naturalness: {message}"
            for message in production_naturalness_warnings(
                text=result.cover_letter_text,
                units=_cover_paragraph_units(result.cover_letter_text),
                keywords=jd_keywords,
                job_description=job_description,
            )
        )
        errors.extend(
            [
                f"cover letter output: {error}"
                for error in validate_output_format(
                    result.mode_outputs[Mode.COVER_LETTER.value],
                    Mode.COVER_LETTER,
                )
            ]
        )
    if result.answers_text:
        errors.extend([f"answers: {error}" for error in validate_style(result.answers_text)])
        errors.extend(
            [f"answers output: {error}" for error in validate_output_format(result.answers_text, Mode.QUESTIONS)]
        )
    return _dedupe(errors)


def _resume_bullet_units(resume_text: str) -> list[str]:
    """Structured bullet units for the stuffing checks, parsed from rendered text."""
    from ats_engine.generation.latex_renderer import parse_resume_sections

    sections = parse_resume_sections(resume_text or "")
    bullets: list[str] = []
    for entry in sections.get("experience") or []:
        bullets.extend(bullet for bullet in (entry.get("bullets") or []) if bullet and bullet.strip())
    return bullets


def _cover_paragraph_units(cover_text: str) -> list[str]:
    """Structured paragraph units for the stuffing checks, split on blank lines."""
    return [block.strip() for block in re.split(r"\n\s*\n", cover_text or "") if block.strip()]


def _finding_message(finding: ValidationFinding) -> str:
    """Legacy-readable message whose prefix keeps calibrated warnings honest."""
    if finding.severity is ValidationSeverity.FATAL:
        return f"resume: {finding.detail}"
    return f"resume validation [{finding.severity.value}:{finding.code}]: {finding.detail}"


def mode_from_text(requested_text: str, job_description: str = "", questions: list[str] | None = None) -> Mode:
    """Public helper for tests and callers that only need mode detection."""
    return detect_mode(
        requested_text=requested_text,
        job_description=job_description,
        questions=questions or [],
    )


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            out.append(item)
            seen.add(item)
    return out
