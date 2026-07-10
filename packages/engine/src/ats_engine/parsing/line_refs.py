from __future__ import annotations

from typing import Any

"""Shared line-numbering helpers for grounded LLM extraction.

Long-form extraction tasks (parse this resume/JD into structured fields) are
usually asked to retype the source sentences verbatim into JSON. That is wasted
decode time: token-by-token generation is the slow part of inference, and
retyping a bullet the model just read adds no information. Instead we number the
source lines once, ask the model to return which line numbers make up each
field, and resolve those numbers back to exact source text in Python. Same
grounding guarantee (the text is provably from the source, not paraphrased),
far fewer output tokens.
"""


def number_lines(text: str) -> list[str]:
    """Split text into its non-empty, stripped lines for 1-indexed referencing."""
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def render_numbered_lines(lines: list[str]) -> str:
    return "\n".join(f"{index + 1}: {line}" for index, line in enumerate(lines))


def resolve_line_numbers(numbers: Any, lines: list[str]) -> list[str]:
    """Map a list of 1-indexed line numbers back to their exact source text.

    Silently skips anything that is not a valid in-range integer, so a model
    that hallucinates a line number degrades gracefully instead of raising.
    """
    resolved: list[str] = []
    for number in numbers or []:
        try:
            index = int(number) - 1
        except (TypeError, ValueError):
            continue
        if 0 <= index < len(lines):
            resolved.append(lines[index])
    return resolved
