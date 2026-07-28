"""Compatibility shim: the demand model now lives in :mod:`ats_engine.kensho`.

Requirement extraction became the front half of KENSHO (Keyword & Evidence
Normalized Scoring, Honest Output), because the same typed requirements feed
both scoring and tailoring and there must be exactly one extractor. The
implementation moved to :mod:`ats_engine.kensho.requirements`; this module
re-exports it so existing imports keep working.

Import from :mod:`ats_engine.kensho.requirements` in new code.
"""

from __future__ import annotations

from ats_engine.kensho.requirements import (
    JDHygiene,
    extract_requirements,
    filter_hygienic_jd_values,
    is_org_role_reference,
    is_person_name,
    sanitize_jd_for_parsing,
)

__all__ = [
    "JDHygiene",
    "extract_requirements",
    "filter_hygienic_jd_values",
    "is_org_role_reference",
    "is_person_name",
    "sanitize_jd_for_parsing",
]
