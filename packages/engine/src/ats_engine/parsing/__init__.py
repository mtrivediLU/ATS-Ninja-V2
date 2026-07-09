"""Deterministic input parsing: PDF text, contacts, resume profile, and JD structure.

Every parser degrades to a heuristic path with no LLM, and layers optional LLM
extraction on top only to improve quality. Nothing here fabricates candidate
facts: extracted employers and bullets are verified against the source text.
"""

from __future__ import annotations

from ats_engine.parsing.input import (
    detect_mode,
    extract_contacts,
    parse_input,
    resolve_contacts,
    split_questions,
)
from ats_engine.parsing.job_description import parse_jd
from ats_engine.parsing.line_refs import number_lines, render_numbered_lines, resolve_line_numbers
from ats_engine.parsing.pdf import clean_extracted_text, extract_text_from_pdf
from ats_engine.parsing.resume import (
    build_profile,
    empty_profile,
    extract_profile,
    find_metrics,
    term_in_text,
)

__all__ = [
    "build_profile",
    "clean_extracted_text",
    "detect_mode",
    "empty_profile",
    "extract_contacts",
    "extract_profile",
    "extract_text_from_pdf",
    "find_metrics",
    "number_lines",
    "parse_input",
    "parse_jd",
    "render_numbered_lines",
    "resolve_contacts",
    "resolve_line_numbers",
    "split_questions",
    "term_in_text",
]
