"""Candidate evidence: the truth-grounded gap ladder and adjacency clustering."""

from __future__ import annotations

from ats_engine.evidence.adjacency import TOOL_CATEGORIES, category_tools, find_category
from ats_engine.evidence.matrix import (
    build_evidence_matrix,
    classify_keyword,
    interview_probability,
)

__all__ = [
    "TOOL_CATEGORIES",
    "build_evidence_matrix",
    "category_tools",
    "classify_keyword",
    "find_category",
    "interview_probability",
]
