"""Deterministic ATS keyword scoring and coverage analysis."""

from __future__ import annotations

from ats_engine.scoring.ats import (
    calculate_ats_score,
    compare_scores,
    extract_keywords,
    keyword_in_text,
)
from ats_engine.scoring.keyword_analysis import analyze_keyword_coverage
from ats_engine.scoring.match_report import (
    DISCLAIMER,
    build_match_report,
    build_recommendation,
    build_weighted_keywords,
    fit_category,
    match_report_style_errors,
    score_confidence,
    score_resume,
)

__all__ = [
    "DISCLAIMER",
    "analyze_keyword_coverage",
    "build_match_report",
    "build_recommendation",
    "build_weighted_keywords",
    "calculate_ats_score",
    "compare_scores",
    "extract_keywords",
    "fit_category",
    "keyword_in_text",
    "match_report_style_errors",
    "score_confidence",
    "score_resume",
]
