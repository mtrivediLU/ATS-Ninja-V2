"""Candidate evidence: the truth-grounded gap ladder and adjacency clustering."""

from __future__ import annotations

from ats_engine.evidence.adjacency import TOOL_CATEGORIES, category_tools, find_category
from ats_engine.evidence.matrix import (
    build_evidence_matrix,
    classify_keyword,
    classify_requirement_category,
    interview_probability,
)
from ats_engine.evidence.transfer import CAPABILITY_TRANSFERS, CapabilityTransfer, transfer_capability

__all__ = [
    "CAPABILITY_TRANSFERS",
    "TOOL_CATEGORIES",
    "CapabilityTransfer",
    "build_evidence_matrix",
    "category_tools",
    "classify_keyword",
    "classify_requirement_category",
    "find_category",
    "interview_probability",
    "transfer_capability",
]
