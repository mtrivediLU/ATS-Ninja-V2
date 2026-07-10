from __future__ import annotations

from ats_engine.scoring.ats import keyword_in_text

"""Before/after keyword coverage analysis.

A deterministic diff of which JD keywords were already present in the original
resume, which the tailoring surfaced, and which remain genuinely absent. This is
pure computation: no keyword is ever added to a resume here, only measured.
"""


def analyze_keyword_coverage(
    base_resume_text: str,
    tailored_resume: str,
    job_keywords: list[str],
) -> dict[str, list[str]]:
    """Compare job keywords across the original and tailored resumes."""
    keywords = job_keywords or []
    matched_original = [keyword for keyword in keywords if keyword_in_text(base_resume_text or "", keyword)]
    added_by_tailoring = [
        keyword
        for keyword in keywords
        if not keyword_in_text(base_resume_text or "", keyword) and keyword_in_text(tailored_resume or "", keyword)
    ]
    still_missing = [
        keyword
        for keyword in keywords
        if not keyword_in_text(base_resume_text or "", keyword) and not keyword_in_text(tailored_resume or "", keyword)
    ]

    return {
        "matched_original": matched_original,
        "added_by_tailoring": added_by_tailoring,
        "still_missing": still_missing,
    }
