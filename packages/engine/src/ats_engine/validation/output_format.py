from __future__ import annotations

import re

from ats_engine.models import Mode


def validate_output_format(text: str, mode: Mode) -> list[str]:
    """Validate final user-facing Mode R, C, or Q output formatting."""
    if mode == Mode.RESUME:
        return _validate_resume_format(text)
    if mode == Mode.COVER_LETTER:
        return _validate_cover_format(text)
    if mode == Mode.QUESTIONS:
        return _validate_question_format(text)
    return []


def validate_cover_letter_word_count(body_text: str, minimum: int = 280, maximum: int = 320) -> list[str]:
    """Validate the cover letter body word count."""
    words = [
        word
        for word in re.findall(r"\b[\w']+\b", body_text)
        if word.lower() not in {"dear", "hiring", "manager", "sincerely"}
    ]
    count = len(words)
    if minimum <= count <= maximum:
        return []
    return [f"cover letter word count {count} outside {minimum} to {maximum}"]


def _validate_resume_format(text: str) -> list[str]:
    errors: list[str] = []
    if not text.startswith("**Role:**"):
        errors.append("Mode R must start with role line")
    if "**Interview Call Probability:**" not in text:
        errors.append("Mode R missing probability")
    if "**Analysis:**" not in text:
        errors.append("Mode R missing analysis")
    errors.extend(_validate_single_final_latex_block(text))
    return errors


def _validate_cover_format(text: str) -> list[str]:
    errors: list[str] = []
    if not text.startswith("**Letter angle:**"):
        errors.append("Mode C must start with letter angle")
    if "**Word count:**" not in text:
        errors.append("Mode C missing word count")
    errors.extend(_validate_single_final_latex_block(text))
    return errors


def _validate_question_format(text: str) -> list[str]:
    if not re.search(r"^\*\*Q1:", text, flags=re.MULTILINE):
        return ["Mode Q missing question labels"]
    return []


def _validate_single_final_latex_block(text: str) -> list[str]:
    errors: list[str] = []
    matches = list(re.finditer(r"```latex\n.*?\n```", text, flags=re.DOTALL))
    if len(matches) != 1:
        errors.append("expected exactly one complete LaTeX code block")
        return errors
    if text[matches[0].end() :].strip():
        errors.append("text after final code block is not allowed")
    return errors
