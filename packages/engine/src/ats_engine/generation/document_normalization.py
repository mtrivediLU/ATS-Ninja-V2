from __future__ import annotations

import re

"""Mechanical cleanup for document presentation data.

This deliberately repairs extraction/layout noise only. It does not paraphrase,
infer facts, alter names/dates/metrics, or change technologies.
"""

_CONTROL = re.compile(r"[\u0000-\u0008\u000b\u000c\u000e-\u001f]")
_COMMA_HYPHEN_BREAK = re.compile(r"(?<=\w)-\s*,\s*(?=[a-z])")
_SAFE_SUFFIX_BREAK = re.compile(r"(?<=\w)-\s+(?=(?:ing|ed|es|vices|tion|tions|ment|ments|ity|ities|able|ably)\b)")


def normalize_document_text(value: str) -> str:
    """Remove only deterministic extraction artifacts from a document field."""
    clean = _CONTROL.sub("", value or "").replace("\u00ad", "")
    clean = _COMMA_HYPHEN_BREAK.sub("", clean)
    clean = _SAFE_SUFFIX_BREAK.sub("", clean)
    return re.sub(r"[ \t]+", " ", clean).strip()
