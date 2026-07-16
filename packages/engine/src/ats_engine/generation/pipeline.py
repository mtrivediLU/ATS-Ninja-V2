from __future__ import annotations

from typing import Any, cast

from ats_engine.config import EngineSettings
from ats_engine.generation.answers import generate_answers_text
from ats_engine.generation.cover_letter import (
    format_cover_letter_output,
    generate_cover_letter_latex,
    generate_cover_letter_text,
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
from ats_engine.models import JDProfile, Mode, ParsedInput, PipelineResult, Profile
from ats_engine.parsing.input import detect_mode, parse_input
from ats_engine.parsing.job_description import parse_jd
from ats_engine.parsing.resume import build_profile
from ats_engine.providers.base import LLMProvider, run_concurrently
from ats_engine.providers.ollama import ollama_provider_pair
from ats_engine.validation.claims import validate_claims
from ats_engine.validation.completeness import validate_completeness
from ats_engine.validation.latex import validate_latex
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
JobFit and InterviewPrep artifacts; LinkedIn outreach remains future work.
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
    mode = parsed_input.mode
    if default_mode is not None and not requested_mode.strip():
        mode = default_mode

    resolved_settings = settings or EngineSettings.from_env()
    if extraction_provider is not None or prose_provider is not None:
        extraction, prose = extraction_provider, prose_provider
    elif not use_llm:
        extraction, prose = None, None
    else:
        extraction, prose = ollama_provider_pair(resolved_settings, model=model_name or None)

    profile, jd_profile = _parse_profile_and_jd(parsed_input, extraction)

    result = PipelineResult(parsed_input=parsed_input, jd_profile=jd_profile)
    result.metadata["llm_available"] = extraction is not None
    resume_plan = None
    if mode in {Mode.RESUME, Mode.RESUME_AND_COVER, Mode.RESUME_AND_QUESTIONS}:
        resume_plan = build_resume_plan(
            contacts=parsed_input.contacts,
            jd_profile=jd_profile,
            profile=profile,
            provider=prose,
            batch_provider=extraction,
        )
        result.resume_plan = resume_plan
        result.resume_text = generate_resume_text(resume_plan)
        result.resume_latex = generate_resume_latex(resume_plan)
        result.mode_outputs[Mode.RESUME.value] = format_resume_output(resume_plan, result.resume_latex)

    if mode in {Mode.COVER_LETTER, Mode.RESUME_AND_COVER}:
        resume_plan = resume_plan or build_resume_plan(
            contacts=parsed_input.contacts,
            jd_profile=jd_profile,
            profile=profile,
            provider=prose,
            batch_provider=extraction,
        )
        result.resume_plan = resume_plan
        if not result.resume_text:
            result.resume_text = generate_resume_text(resume_plan)
        cover_plan = build_cover_letter_plan(resume_plan, profile, provider=prose)
        result.cover_letter_plan = cover_plan
        result.cover_letter_text = generate_cover_letter_text(cover_plan)
        result.cover_letter_latex = generate_cover_letter_latex(cover_plan)
        result.mode_outputs[Mode.COVER_LETTER.value] = format_cover_letter_output(cover_plan, result.cover_letter_latex)

    if mode in {Mode.QUESTIONS, Mode.RESUME_AND_QUESTIONS}:
        resume_plan = resume_plan or build_resume_plan(
            contacts=parsed_input.contacts,
            jd_profile=jd_profile,
            profile=profile,
            provider=prose,
            batch_provider=extraction,
        )
        result.resume_plan = resume_plan
        answer_plan = build_answer_plan(questions=parsed_input.questions, resume_plan=resume_plan, provider=prose)
        result.answer_plan = answer_plan
        result.answers_text = generate_answers_text(answer_plan)
        result.mode_outputs[Mode.QUESTIONS.value] = result.answers_text

    result.validation_errors = validate_pipeline_result(result, profile)
    return result


def _parse_profile_and_jd(parsed_input: ParsedInput, extraction: LLMProvider | None) -> tuple[Profile, JDProfile]:
    """Build the candidate profile and parse the JD.

    Both are independent provider calls, so when a model is available they run
    concurrently. Without a model, this is all fast heuristics anyway, and
    running profile extraction first lets JD parsing's heuristic fallback use the
    candidate's own tiered vocabulary for keyword matching.
    """
    if extraction is None:
        profile = build_profile(parsed_input.resume_text, provider=None)
        jd_profile = parse_jd(parsed_input.job_description, profile=profile, provider=None)
        return profile, jd_profile

    results = run_concurrently(
        {
            "profile": lambda: build_profile(parsed_input.resume_text, provider=extraction),
            "jd_profile": lambda: parse_jd(parsed_input.job_description, profile=None, provider=extraction),
        }
    )
    return cast(Profile, results["profile"]), cast(JDProfile, results["jd_profile"])


def validate_pipeline_result(result: PipelineResult, profile: Profile | None = None) -> list[str]:
    """Run all silent validation gates and return readable errors."""
    if profile is None:
        profile = build_profile(result.parsed_input.resume_text)
    errors: list[str] = []
    errors.extend(validate_completeness(result, profile))
    if result.resume_latex:
        errors.extend([f"resume: {error}" for error in validate_latex(result.resume_latex)])
        errors.extend([f"resume: {error}" for error in validate_style(result.resume_latex)])
        errors.extend([f"resume: {error}" for error in validate_claims(result.resume_latex, profile)])
        errors.extend(
            [
                f"resume output: {error}"
                for error in validate_output_format(result.mode_outputs[Mode.RESUME.value], Mode.RESUME)
            ]
        )
    if result.cover_letter_latex:
        errors.extend([f"cover letter: {error}" for error in validate_latex(result.cover_letter_latex)])
        errors.extend([f"cover letter: {error}" for error in validate_style(result.cover_letter_latex)])
        errors.extend([f"cover letter: {error}" for error in validate_claims(result.cover_letter_latex, profile)])
        errors.extend(
            [f"cover letter: {error}" for error in validate_cover_letter_word_count(result.cover_letter_text)]
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
