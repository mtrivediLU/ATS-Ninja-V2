from __future__ import annotations

import re
from collections.abc import Callable

"""Deterministic repair of style violations in generated text.

The style validator bans cliche resume language, but much of that language
arrives verbatim from the candidate's own uploaded resume. Blocking the whole
document over the candidate's own wording is wrong, and regenerating via the LLM
is slow. Instead, offending words are rewritten in place with plain
replacements, preserving sentence meaning and leading capitalization. The
replacement map must cover the style validator's full banned list so a softened
text always passes validation.
"""

# Multi-word phrases first so they win over their component words.
_PHRASE_REPLACEMENTS: list[tuple[str, str]] = [
    ("I am excited to apply", "I am applying"),
    ("I was thrilled to see", "I noticed"),
    ("I would welcome the opportunity", "I would be glad"),
    ("I believe my skills align", "my skills match"),
    ("make a meaningful impact", "contribute"),
    ("esteemed organization", "organization"),
    ("perfect fit", "strong fit"),
    ("unique blend of", "mix of"),
    ("drive data-driven decision making", "support decisions with data"),
    ("data-driven decision making", "decisions with data"),
    ("fast-paced environment", "busy environment"),
    ("tailored solutions", "specific solutions"),
    ("dedicated professional", "professional"),
    ("proven track record", "record"),
    ("proven expertise", "expertise"),
    ("demonstrated ability", "ability"),
    ("hands-on experience", "direct experience"),
    ("results-driven", "focused"),
    ("detail-oriented", "careful"),
    ("passionate about", "focused on"),
    ("adept at", "skilled in"),
    ("best-in-class", "leading"),
    ("world-class", "excellent"),
    ("cutting-edge", "modern"),
    ("future-proof", "durable"),
    ("mission-critical", "critical"),
    ("enterprise-grade", "production-ready"),
    ("end-to-end", "full"),
    ("high-impact", "important"),
    ("cloud-native", "cloud-based"),
    ("transformational", "major"),
    ("revolutionized", "overhauled"),
    ("spearheaded", "led"),
    ("architected", "designed"),
    ("orchestrated", "coordinated"),
    ("streamlined", "simplified"),
    ("synergized", "combined"),
    ("facilitated", "ran"),
    ("transformed", "reworked"),
    ("championed", "promoted"),
    ("pioneered", "introduced"),
    ("empowered", "helped"),
    ("leveraged", "used"),
    ("elevated", "improved"),
    ("enabled", "allowed"),
    ("crafted", "built"),
    ("curated", "organized"),
    ("comprehensive", "complete"),
    ("holistic", "broad"),
    ("innovative", "new"),
    ("dynamic", "fast-moving"),
    ("strategic", "planned"),
    ("pivotal", "key"),
    ("robust", "reliable"),
    ("seamless", "smooth"),
]

_COMPILED = [
    (re.compile(rf"\b{re.escape(phrase)}\b", flags=re.IGNORECASE), replacement)
    for phrase, replacement in _PHRASE_REPLACEMENTS
]


def soften_banned_style(text: str) -> str:
    """Replace banned cliche wording with plain equivalents, preserving case."""
    if not text:
        return text

    result = text
    for pattern, replacement in _COMPILED:
        result = pattern.sub(_case_preserving_replacer(replacement), result)
    return result


def _case_preserving_replacer(replacement: str) -> Callable[[re.Match[str]], str]:
    def replace(match: re.Match[str]) -> str:
        return _match_case(match.group(0), replacement)

    return replace


def _match_case(original: str, replacement: str) -> str:
    if original[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement
