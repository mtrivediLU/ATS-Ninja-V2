from __future__ import annotations

import hashlib

from ats_engine.evidence.matrix import classify_keyword
from ats_engine.evidence.quality_report import AtsQualityReport, build_ats_quality_report
from ats_engine.job_fit.policy import fit_band_for_score, requirement_coverage_score
from ats_engine.kit.contract import (
    AtsMatchScore,
    AtsQualityReportPayload,
    FitCategory,
    JobFitArtifact,
    MatchReport,
    ScoreConfidence,
    WeightedKeyword,
)
from ats_engine.models import EvidenceItem, JDProfile, Profile, ResumePlan
from ats_engine.scoring.ats import keyword_in_text
from ats_engine.validation.style import validate_style

"""ApplicationKit v5 honest scoring — the deterministic match report.

Three deliberately separate scores, never merged into a single "ATS score":

1. **Original resume keyword match** — the *submitted* resume against the unified
   JD keyword vocabulary.
2. **Tailored resume keyword match** — the *final grounded* resume against the
   same vocabulary (absent when the resume was not requested or was withheld).
3. **Evidence-based role alignment** — the existing requirement-coverage index
   (:func:`ats_engine.job_fit.policy.requirement_coverage_score`), reused so this
   module never introduces a competing alignment formula.

Truth-safety guarantees (see also ADR-0019):

- The unified vocabulary is built **only** from the job description. No
  candidate-derived term is ever added to it.
- A keyword earns match credit only when the candidate's *parsed evidence*
  independently supports it (tier A/B/C via the same evidence gate that resists
  fabrication) **and** it is genuinely present in the measured resume. Appending
  the job description to the resume cannot raise the score, because raw appended
  text is not parsed into affirmative tier-A/B/C candidate evidence.
- Presence, not frequency, determines credit: a keyword counts at most once, so
  repeated occurrences and keyword stuffing never increase a score.
- Every score is a deterministic estimate, never an employer decision.
"""

# The exact disclaimer required on every user-facing recommendation/summary.
DISCLAIMER = (
    "These are estimates from deterministic keyword and evidence analysis, not a prediction of any employer's decision."
)

# Evidence tiers that mean the keyword itself is genuinely present in the
# candidate's own resume structure (proven, stated, or listed). ``adjacency``
# and ``missing`` are deliberately excluded: an adjacency means a *related* tool
# is present, not the keyword, and missing means no evidence at all.
_CREDIT_TIERS = frozenset({"A", "B", "C"})


# --------------------------------------------------------------------------- #
# Unified job keyword vocabulary
# --------------------------------------------------------------------------- #
def build_weighted_keywords(evidence: list[EvidenceItem], jd_profile: JDProfile) -> list[WeightedKeyword]:
    """Build the unified, deterministically ordered JD keyword vocabulary.

    Order and provenance:

    1. Evidence-matrix requirements first — required terms (weight 2.0) then
       preferred terms (weight 1.0), in matrix order.
    2. Remaining ``JDProfile.technical_keywords`` (weight 1.0) that are not
       already present, in JD order.

    Deduplication is case-insensitive; the first occurrence wins. No candidate-
    derived term is ever added — the vocabulary is purely the job's own.
    """
    keywords: list[WeightedKeyword] = []
    seen: set[str] = set()

    def _add(term: str, weight: float, source: str, required: bool) -> None:
        normalized = term.strip().casefold()
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        keywords.append(WeightedKeyword(term=term.strip(), weight=weight, source=source, required=required))

    for item in evidence:
        if item.required_or_preferred == "required":
            _add(item.keyword, 2.0, "required", required=True)
    for item in evidence:
        if item.required_or_preferred != "required":
            _add(item.keyword, 1.0, "preferred", required=False)
    for term in jd_profile.technical_keywords:
        _add(term, 1.0, "jd_keyword", required=False)

    return keywords


# --------------------------------------------------------------------------- #
# Keyword-match scoring (evidence-gated, presence-not-frequency)
# --------------------------------------------------------------------------- #
def _evidence_supported(term: str, profile: Profile, tier_by_keyword: dict[str, str]) -> bool:
    """True when the candidate's parsed evidence genuinely supports ``term``.

    Reuses the evidence matrix's classification (tier A/B/C) — the same gate that
    resists fabrication. This is what makes an appended copy of the job
    description unable to inflate the score: raw trailing text is not parsed into
    an affirmative tier-A bullet or a genuine skills-tier entry.
    """
    normalized = term.casefold().strip()
    tier = tier_by_keyword.get(normalized)
    if tier is None:
        tier = classify_keyword(term, "required", profile).evidence_tier
    return tier in _CREDIT_TIERS


def score_resume(
    resume_text: str,
    keywords: list[WeightedKeyword],
    profile: Profile,
    tier_by_keyword: dict[str, str],
) -> AtsMatchScore:
    """Score one resume (0-100) against the unified vocabulary, evidence-gated.

    The score is *weighted*:

        100 * (sum of weights of credited keywords) / (sum of all keyword weights)

    Required keywords (weight 2.0) therefore contribute more than preferred/other
    keywords (weight 1.0). A keyword is credited only when it is present in
    ``resume_text`` (word-boundary, case-insensitive) *and* the candidate's
    parsed evidence supports it at tier A/B/C. Credit is boolean per unique
    keyword, so repetition never changes the score.
    """
    if not keywords:
        return AtsMatchScore(score=0.0, total_keywords=0)

    matched: list[str] = []
    missing: list[str] = []
    required_matched = required_total = 0
    preferred_matched = preferred_total = 0
    credited_weight = 0.0
    total_weight = 0.0
    for weighted in keywords:
        is_required = weighted.required
        total_weight += weighted.weight
        if is_required:
            required_total += 1
        else:
            preferred_total += 1
        credited = keyword_in_text(resume_text or "", weighted.term) and _evidence_supported(
            weighted.term, profile, tier_by_keyword
        )
        if credited:
            matched.append(weighted.term)
            credited_weight += weighted.weight
            if is_required:
                required_matched += 1
            else:
                preferred_matched += 1
        else:
            missing.append(weighted.term)

    score = round(credited_weight / total_weight * 100, 2) if total_weight else 0.0
    return AtsMatchScore(
        score=score,
        matched_keywords=matched,
        missing_keywords=missing,
        total_keywords=len(keywords),
        required_matched=required_matched,
        required_total=required_total,
        preferred_matched=preferred_matched,
        preferred_total=preferred_total,
    )


# --------------------------------------------------------------------------- #
# Fit category policy (centralized thresholds; boundary-safe ordering)
# --------------------------------------------------------------------------- #
# Documented, boundary-safe policy. The ordering deliberately gates every
# category on the must-have-gap count *before* the alignment-only "partial"
# rung, so a result with two or more must-have gaps is never classified more
# positively than ``stretch_role`` even when its alignment score is >= 50.
STRONG_FIT_MIN_ALIGNMENT = 85.0
GOOD_FIT_MIN_ALIGNMENT = 70.0
PARTIAL_FIT_MIN_ALIGNMENT = 50.0
STRETCH_ROLE_MIN_ALIGNMENT = 35.0


def fit_category(alignment: float, must_have_gap_count: int) -> FitCategory:
    """Map role alignment and must-have gap count to an honest fit category."""
    bounded = min(100.0, max(0.0, alignment))
    if bounded >= STRONG_FIT_MIN_ALIGNMENT and must_have_gap_count == 0:
        return FitCategory.STRONG_FIT
    if bounded >= GOOD_FIT_MIN_ALIGNMENT and must_have_gap_count <= 1:
        return FitCategory.GOOD_FIT
    if must_have_gap_count >= 2:
        # Two or more must-have gaps cap the result at a stretch role, never the
        # more positive "partial fit", regardless of alignment.
        return FitCategory.STRETCH_ROLE
    if bounded >= PARTIAL_FIT_MIN_ALIGNMENT:
        return FitCategory.PARTIAL_FIT
    if bounded >= STRETCH_ROLE_MIN_ALIGNMENT:
        return FitCategory.STRETCH_ROLE
    return FitCategory.LOW_ALIGNMENT


# --------------------------------------------------------------------------- #
# Score confidence rubric (annotation only, never a delivery gate)
# --------------------------------------------------------------------------- #
def score_confidence(
    *,
    jd_profile: JDProfile,
    profile: Profile,
    evidence: list[EvidenceItem],
    keyword_count: int,
    extraction_warnings: list[str],
    contact_issue_count: int,
) -> tuple[ScoreConfidence, list[str]]:
    """Deterministically rate confidence in the scores, with readable reasons.

    Confidence annotates the scores and never blocks delivery. Signals include
    whether a real target title was found, how many required requirements were
    detected, resume extraction quality, and the size of the keyword set.
    """
    reasons: list[str] = []
    severe = 0

    has_title = bool(jd_profile.title) and jd_profile.title != "Target Role"
    if not has_title:
        severe += 1
        reasons.append("No specific target job title was detected in the job description.")

    required = [item for item in evidence if item.required_or_preferred == "required"]
    if not required:
        severe += 1
        reasons.append("No required qualifications were clearly detected in the job description.")
    elif len(required) < 3:
        reasons.append("Only a few required qualifications were detected, so coverage is measured on a small set.")

    if not jd_profile.required_qualifications and not jd_profile.responsibilities:
        severe += 1
        reasons.append("The job description was thin or hard to segment, which weakens keyword detection.")

    if keyword_count < 5:
        severe += 1
        reasons.append("The unified job keyword set is unusually small, so each keyword carries a large weight.")

    has_bullets = any(experience.bullets for experience in profile.experiences)
    if not profile.experiences:
        severe += 1
        reasons.append("No work experience was extracted from the resume.")
    elif not has_bullets:
        reasons.append("Experience was detected but few detail bullets were extracted from the resume.")

    review_warnings = [warning for warning in extraction_warnings if "manual review" in warning.lower()]
    if review_warnings:
        severe += 1
        reasons.append(
            "Resume extraction flagged the document for manual review, so parsed evidence may be incomplete."
        )

    if contact_issue_count > 0:
        reasons.append("A contact field looks malformed, which can affect how an ATS reads the resume.")

    if severe >= 3:
        level = ScoreConfidence.LOW
    elif severe >= 1:
        level = ScoreConfidence.MEDIUM
    else:
        level = ScoreConfidence.HIGH

    if not reasons:
        reasons.append("A specific title, a clear requirement set, and structured resume evidence were all detected.")
    return level, reasons


# --------------------------------------------------------------------------- #
# Recommendation + kit summary (deterministic, style-safe, varied)
# --------------------------------------------------------------------------- #
_CATEGORY_OPENINGS: dict[FitCategory, tuple[str, ...]] = {
    FitCategory.STRONG_FIT: (
        "Your background lines up closely with what this role asks for.",
        "This role sits squarely within your demonstrated experience.",
        "Your resume already covers most of what this posting calls for.",
    ),
    FitCategory.GOOD_FIT: (
        "You are a solid match for this role, with a small number of gaps to address.",
        "Your experience covers the core of this role, with a few areas to shore up.",
        "This role is a good match for your background, with some gaps to speak to.",
    ),
    FitCategory.PARTIAL_FIT: (
        "You match part of this role and will want to speak to the remaining areas directly.",
        "Your background covers some of this role; the rest is worth addressing head on.",
        "This role overlaps with part of your experience, with real areas left to cover.",
    ),
    FitCategory.STRETCH_ROLE: (
        "This is a stretch role: some core requirements are not yet in your evidence.",
        "This role reaches beyond your current evidence in one or more must-have areas.",
        "This posting is a stretch, with must-have areas your resume does not yet show.",
    ),
    FitCategory.LOW_ALIGNMENT: (
        "This role asks for a different core profile than your resume currently shows.",
        "The overlap between your evidence and this role is limited right now.",
        "Your current evidence covers little of what this specific role requires.",
    ),
}


def _stable_index(seed: str, count: int) -> int:
    """Deterministically pick an index in ``[0, count)`` from a stable seed.

    The same candidate/JD always resolves to the same filler, while different
    inputs vary it — deterministic, never random.
    """
    if count <= 0:
        return 0
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return int(digest, 16) % count


def _join(items: list[str], limit: int = 4) -> str:
    trimmed = [item for item in items if item][:limit]
    return ", ".join(trimmed)


def build_recommendation(
    *,
    category: FitCategory,
    seed: str,
    strongest_matches: list[str],
    genuine_gaps: list[str],
    must_have_gaps: list[str],
) -> str:
    """A constructive, plain-language recommendation that passes style validation.

    Never promises an interview or ATS behavior, never says "do not apply", and
    always ends with the required disclaimer.
    """
    openings = _CATEGORY_OPENINGS[category]
    parts = [openings[_stable_index(seed, len(openings))]]

    if strongest_matches:
        parts.append(f"Your clearest supported strengths are {_join(strongest_matches)}.")

    ordered_gaps = list(dict.fromkeys([*must_have_gaps, *genuine_gaps]))
    if must_have_gaps:
        parts.append(
            f"Give priority to the must-have gaps first: {_join(must_have_gaps)}. "
            "Be honest about them and point to the closest experience you do have."
        )
    elif ordered_gaps:
        parts.append(f"Areas worth addressing: {_join(ordered_gaps)}.")

    if category in (FitCategory.STRONG_FIT, FitCategory.GOOD_FIT):
        parts.append("Lead with the evidence you already have and apply.")
    else:
        parts.append("You can still apply; be candid about the gaps and how you would close them.")

    parts.append(DISCLAIMER)
    return " ".join(parts)


def build_kit_summary(
    *,
    original: AtsMatchScore,
    tailored: AtsMatchScore | None,
    alignment: float,
    category: FitCategory,
    confidence: ScoreConfidence,
) -> str:
    """A short summary that clearly distinguishes the three scores.

    Honestly explains a tailored score that is lower than the original rather
    than assuming tailoring always raises the number.
    """
    label = category.value.replace("_", " ")
    parts = [
        f"Original resume keyword match: {original.score:.0f} out of 100.",
    ]
    if tailored is not None:
        parts.append(f"Tailored resume keyword match: {tailored.score:.0f} out of 100.")
        if tailored.score < original.score:
            parts.append(
                "The tailored match is lower because grounding removed content the candidate evidence did not support; "
                "the tailored resume is more accurate, not weaker."
            )
        elif tailored.score > original.score:
            parts.append("Tailoring surfaced supported keywords the original resume did not state directly.")
    else:
        parts.append("A tailored resume was not produced for this kit, so only the original match is shown.")
    parts.append(f"Evidence-based role alignment: {alignment:.0f} out of 100.")
    parts.append(f"Fit category: {label}. Score confidence: {confidence.value}.")
    return " ".join(parts)


# --------------------------------------------------------------------------- #
# Quality report projection
# --------------------------------------------------------------------------- #
def _quality_payload(report: AtsQualityReport) -> AtsQualityReportPayload:
    contact_issues = list(report.contact_integrity.warnings)
    return AtsQualityReportPayload(
        required_term_count=report.required_term_count,
        required_supported_count=report.required_supported_count,
        required_coverage_percent=report.required_coverage_percent,
        preferred_term_count=report.preferred_term_count,
        preferred_supported_count=report.preferred_supported_count,
        preferred_coverage_percent=report.preferred_coverage_percent,
        exact_target_title_present=report.exact_target_title_present,
        section_presence=dict(report.section_presence),
        contact_issue_count=len(contact_issues),
        contact_issues=contact_issues,
        measurable_result_count=report.measurable_result_count,
        word_count=report.word_count,
        unsupported_requirement_count=report.unsupported_requirement_count,
        adjacency_count=report.adjacency_count,
        working_knowledge_count=report.working_knowledge_count,
        formatting_warnings=list(report.formatting_warnings),
        duplicate_keyword_warnings=list(report.duplicate_keyword_warnings),
        generic_language_warnings=list(report.generic_language_warnings),
    )


# --------------------------------------------------------------------------- #
# Top-level assembly
# --------------------------------------------------------------------------- #
def build_match_report(
    *,
    profile: Profile,
    jd_profile: JDProfile,
    resume_plan: ResumePlan,
    original_resume_text: str,
    tailored_resume_text: str | None,
    job_fit: JobFitArtifact | None,
    extraction_warnings: list[str] | None = None,
) -> MatchReport:
    """Assemble the complete v5 match report from already-computed pipeline data.

    ``tailored_resume_text`` is ``None`` when the resume was not requested or was
    withheld — the tailored score is then absent. ``job_fit``, when present,
    provides the authoritative alignment score, fit band, strengths, and gaps so
    the match report never contradicts the job-fit artifact.
    """
    evidence = resume_plan.evidence
    keywords = build_weighted_keywords(evidence, jd_profile)
    tier_by_keyword = {item.keyword.casefold().strip(): item.evidence_tier for item in evidence}

    original = score_resume(original_resume_text, keywords, profile, tier_by_keyword)
    tailored = (
        score_resume(tailored_resume_text, keywords, profile, tier_by_keyword)
        if tailored_resume_text is not None
        else None
    )

    if job_fit is not None:
        alignment = job_fit.requirement_coverage_score
        fit_band = job_fit.fit_band
        strongest = list(job_fit.strongest_matches)
        genuine_gaps = list(job_fit.genuine_gaps)
        must_have_gaps = list(job_fit.must_have_gaps)
    else:
        alignment = requirement_coverage_score(evidence)
        fit_band = fit_band_for_score(alignment)
        strongest = [item.keyword for item in evidence if item.evidence_tier in ("A", "B")]
        genuine_gaps = [item.keyword for item in evidence if item.evidence_tier == "missing"]
        must_have_gaps = [
            item.keyword
            for item in evidence
            if item.evidence_tier == "missing" and item.required_or_preferred == "required"
        ]

    category = fit_category(alignment, len(must_have_gaps))

    # Keyword analysis: original / surfaced-by-tailoring / still-missing, gated by
    # the same evidence credit used for scoring so nothing unsupported appears.
    matched_original = set(original.matched_keywords)
    matched_tailored = set(tailored.matched_keywords) if tailored is not None else set(matched_original)
    surfaced = [term for term in matched_tailored if term not in matched_original]
    still_missing = [w.term for w in keywords if w.term not in matched_original and w.term not in matched_tailored]

    quality = build_ats_quality_report(
        evidence=evidence,
        jd_profile=jd_profile,
        resume_plan=resume_plan,
        resume_text=tailored_resume_text or original_resume_text,
    )
    payload = _quality_payload(quality)

    confidence, confidence_reasons = score_confidence(
        jd_profile=jd_profile,
        profile=profile,
        evidence=evidence,
        keyword_count=len(keywords),
        extraction_warnings=extraction_warnings or [],
        contact_issue_count=payload.contact_issue_count,
    )

    seed = f"{jd_profile.company}|{jd_profile.title}|{profile.contact.name}|{category.value}"
    recommendation = build_recommendation(
        category=category,
        seed=seed,
        strongest_matches=strongest,
        genuine_gaps=genuine_gaps,
        must_have_gaps=must_have_gaps,
    )
    kit_summary = build_kit_summary(
        original=original,
        tailored=tailored,
        alignment=alignment,
        category=category,
        confidence=confidence,
    )

    return MatchReport(
        original_ats_match=original,
        alignment_score=alignment,
        fit_band=fit_band,
        fit_category=category,
        confidence=confidence,
        confidence_reasons=confidence_reasons,
        tailored_ats_match=tailored,
        strongest_matches=strongest,
        genuine_gaps=genuine_gaps,
        must_have_gaps=must_have_gaps,
        keywords_matched_original=sorted(matched_original),
        keywords_surfaced_by_tailoring=sorted(surfaced),
        keywords_still_missing=still_missing,
        recommendation=recommendation,
        kit_summary=kit_summary,
        quality_report=payload,
        disclaimer=DISCLAIMER,
    )


def match_report_style_errors(report: MatchReport) -> list[str]:
    """Style-validate every generated prose field (used by tests and the orchestrator)."""
    errors: list[str] = []
    for text in (report.recommendation, report.kit_summary, *report.confidence_reasons):
        errors.extend(validate_style(text))
    return errors


__all__ = [
    "DISCLAIMER",
    "build_weighted_keywords",
    "score_resume",
    "fit_category",
    "score_confidence",
    "build_recommendation",
    "build_kit_summary",
    "build_match_report",
    "match_report_style_errors",
]
