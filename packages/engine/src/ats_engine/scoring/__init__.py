"""Deterministic ATS keyword scoring and coverage analysis."""

from __future__ import annotations

from ats_engine.scoring.ats import (
    calculate_ats_score,
    compare_scores,
    extract_keywords,
    keyword_in_text,
)
from ats_engine.scoring.keyword_analysis import analyze_keyword_coverage

__all__ = [
    "analyze_keyword_coverage",
    "calculate_ats_score",
    "compare_scores",
    "extract_keywords",
    "keyword_in_text",
]
