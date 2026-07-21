"""Generation: turn grounded plans into resume/cover-letter/answer artifacts.

Prose comes from a provider when available and from deterministic fallbacks
otherwise; either way the output passes the validation gates before it is
considered deliverable. LaTeX is the produced downloadable artifact format.
"""

from __future__ import annotations

from ats_engine.generation.answers import generate_answers_text
from ats_engine.generation.cover_letter import (
    format_cover_letter_output,
    generate_cover_letter_latex,
    generate_cover_letter_text,
)
from ats_engine.generation.filenames import build_export_filename, sanitize_filename_component
from ats_engine.generation.html_renderer import (
    render_cover_letter_html,
    render_plain_text_html,
    render_resume_html,
)
from ats_engine.generation.pipeline import (
    mode_from_text,
    resolve_artifact_selection,
    run_pipeline,
    validate_pipeline_result,
)
from ats_engine.generation.planning import (
    build_answer_plan,
    build_cover_letter_plan,
    build_resume_plan,
    choose_role_identity,
)
from ats_engine.generation.resume import (
    format_resume_output,
    generate_resume_latex,
    generate_resume_text,
)

__all__ = [
    "build_answer_plan",
    "build_cover_letter_plan",
    "build_export_filename",
    "build_resume_plan",
    "choose_role_identity",
    "format_cover_letter_output",
    "format_resume_output",
    "generate_answers_text",
    "generate_cover_letter_latex",
    "generate_cover_letter_text",
    "generate_resume_latex",
    "generate_resume_text",
    "mode_from_text",
    "render_cover_letter_html",
    "render_plain_text_html",
    "render_resume_html",
    "resolve_artifact_selection",
    "run_pipeline",
    "sanitize_filename_component",
    "validate_pipeline_result",
]
