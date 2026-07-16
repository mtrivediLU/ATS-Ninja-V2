from __future__ import annotations

import json

from ats_engine.job_fit.policy import fit_band_for_score, requirement_coverage_score
from ats_engine.job_fit.validation import validate_job_fit_narrative
from ats_engine.kit.contract import (
    EVIDENCE_EXCERPT_MAX_CHARS,
    ArtifactKind,
    ArtifactStatus,
    ArtifactValidation,
    ConsistencyValidation,
    EvidenceRef,
    GenerationMetadata,
    JobFitArtifact,
    PositioningRecommendation,
    RequirementAssessment,
    RequirementClassification,
    RequirementRisk,
)
from ats_engine.kit.grounding import EvidenceContext, GroundingOutcome, ground_text
from ats_engine.models import EvidenceItem, JDProfile, Profile, ResumePlan
from ats_engine.providers.base import LLMProvider, generate_text
from ats_engine.scoring import calculate_ats_score

_UNSUITABLE_STANDALONE_REQUIREMENTS = frozenset(
    {"ability", "development", "experience", "knowledge", "power", "production", "proficiency"}
)


def _relevant_evidence(evidence: list[EvidenceItem]) -> list[EvidenceItem]:
    """Remove parser noise that is unsuitable as a standalone assessment.

    The source matrix remains unchanged. This presentation view removes generic
    qualifiers and a token that is already represented by a longer phrase (for
    example ``power`` beside ``power bi``), preventing duplicate or misleading
    user-facing requirements.
    """
    normalized = [item.keyword.casefold().strip() for item in evidence]
    relevant: list[EvidenceItem] = []
    for index, item in enumerate(evidence):
        term = normalized[index]
        if term in _UNSUITABLE_STANDALONE_REQUIREMENTS:
            continue
        if any(term != other and f" {term} " in f" {other} " for other in normalized):
            continue
        relevant.append(item)
    return relevant


def _classification(item: EvidenceItem) -> RequirementClassification:
    if item.evidence_tier in {"A", "B"}:
        return RequirementClassification.PROVEN
    if item.evidence_tier == "adjacency":
        return RequirementClassification.ADJACENT
    if item.evidence_tier == "C":
        return RequirementClassification.WORKING_KNOWLEDGE
    return RequirementClassification.GENUINE_GAP


def _evidence_ref(item: EvidenceItem, profile: Profile) -> list[EvidenceRef]:
    if not item.real_evidence:
        return []
    needle = item.keyword.casefold()
    fallback = item.real_evidence.split("(")[-1].rstrip(")").casefold()
    excerpt = item.real_evidence
    for line in profile.raw_markdown.splitlines():
        if needle in line.casefold() or (fallback and fallback in line.casefold()):
            excerpt = line.strip()
            break
    return [
        EvidenceRef(source="candidate_resume", locator="evidence_matrix", excerpt=excerpt[:EVIDENCE_EXCERPT_MAX_CHARS])
    ]


def _assessment(item: EvidenceItem, index: int, profile: Profile) -> RequirementAssessment:
    classification = _classification(item)
    must_have = item.required_or_preferred == "required"
    if classification is RequirementClassification.PROVEN:
        explanation = f"Candidate evidence supports {item.keyword} at evidence tier {item.evidence_tier}."
        risk = RequirementRisk.LOW
        positioning = f"State the demonstrated {item.keyword} experience and cite the supporting resume evidence."
    elif classification is RequirementClassification.ADJACENT:
        explanation = f"No direct {item.keyword} evidence; related capability is {item.real_evidence}."
        risk = RequirementRisk.HIGH if must_have else RequirementRisk.MODERATE
        positioning = (
            f"Describe {item.real_evidence} only as adjacent to {item.keyword}; do not claim direct experience."
        )
    elif classification is RequirementClassification.WORKING_KNOWLEDGE:
        explanation = f"{item.keyword} is listed only and is therefore working knowledge, not production evidence."
        risk = RequirementRisk.HIGH if must_have else RequirementRisk.MODERATE
        positioning = f"Use 'working knowledge of {item.keyword}' and avoid production or expert language."
    else:
        explanation = f"The resume contains no candidate evidence for {item.keyword}."
        risk = RequirementRisk.MUST_HAVE_GAP if must_have else RequirementRisk.HIGH
        positioning = f"Keep {item.keyword} visible as a gap; do not imply candidate experience."
    return RequirementAssessment(
        id=f"req-{index:03d}",
        requirement=item.keyword,
        importance=item.required_or_preferred,
        must_have=must_have,
        classification=classification,
        explanation=explanation,
        risk=risk,
        permitted_positioning=positioning,
        evidence=_evidence_ref(item, profile),
    )


def _deterministic_summary(score: float, band: str, assessments: list[RequirementAssessment]) -> str:
    groups = {
        classification: [item.requirement for item in assessments if item.classification is classification]
        for classification in RequirementClassification
    }
    must_gaps = [
        item.requirement
        for item in assessments
        if item.must_have and item.classification is RequirementClassification.GENUINE_GAP
    ]
    parts = [f"Requirement coverage: {score:.2f}%. Fit band: {band}."]
    if groups[RequirementClassification.PROVEN]:
        parts.append("Proven matches: " + ", ".join(groups[RequirementClassification.PROVEN]) + ".")
    if groups[RequirementClassification.ADJACENT]:
        parts.append(
            "Adjacent capabilities, not direct experience: "
            + ", ".join(groups[RequirementClassification.ADJACENT])
            + "."
        )
    if groups[RequirementClassification.WORKING_KNOWLEDGE]:
        parts.append("Working knowledge only: " + ", ".join(groups[RequirementClassification.WORKING_KNOWLEDGE]) + ".")
    if groups[RequirementClassification.GENUINE_GAP]:
        parts.append("Genuine gaps: " + ", ".join(groups[RequirementClassification.GENUINE_GAP]) + ".")
    if must_gaps:
        parts.append("Must-have gaps: " + ", ".join(must_gaps) + ".")
    else:
        parts.append("No must-have requirement is classified as a genuine gap.")
    return " ".join(parts)


def _prompt(score: float, band: str, assessments: list[RequirementAssessment], fallback: str) -> str:
    brief = [
        {
            "requirement": item.requirement,
            "importance": item.importance,
            "classification": item.classification.value,
            "evidence": [ref.excerpt for ref in item.evidence],
            "permitted_positioning": item.permitted_positioning,
        }
        for item in assessments
    ]
    return (
        "Write a concise JOB FIT NARRATIVE from this bounded authoritative brief. "
        "Wording only: do not recalculate the score/band, change a classification, hide a gap, or invent any "
        "candidate employer, title, skill, metric, date, credential, project, team, ownership, or achievement. "
        "Adjacent means related capability only. Working knowledge is not production experience. Include every "
        "must-have genuine gap. Begin exactly with "
        f"'Requirement coverage: {score:.2f}%. Fit band: {band}.'.\n"
        f"Structured brief: {json.dumps(brief, ensure_ascii=False)}\n"
        f"Safe deterministic fallback: {fallback}"
    )


def _ground_authoritative_summary(
    text: str,
    *,
    score_text: str,
    assessments: list[RequirementAssessment],
    context: EvidenceContext,
    id_prefix: str,
) -> GroundingOutcome:
    """Ground candidate claims while preserving authoritative gap labels.

    A missing requirement named as a *gap* is analysis, not a candidate skill
    claim. The generic claim extractor cannot infer that semantic distinction,
    so deterministic non-proven labels are temporarily masked. Provider prose
    never uses this path until it has been rejected and replaced by the trusted
    deterministic narrative.
    """
    replacements = {"REQUIREMENT_COVERAGE_SCORE": score_text}
    masked = text.replace(score_text, "REQUIREMENT_COVERAGE_SCORE")
    for index, item in enumerate(assessments, start=1):
        if item.classification is RequirementClassification.PROVEN:
            continue
        token = f"FIT_REQUIREMENT_{index:03d}"
        masked = masked.replace(item.requirement, token)
        replacements[token] = item.requirement
    outcome = ground_text(masked, artifact=ArtifactKind.JOB_FIT, context=context, id_prefix=id_prefix)
    for token, value in replacements.items():
        outcome.clean_text = outcome.clean_text.replace(token, value)
    return outcome


def build_job_fit_artifact(
    *,
    plan: ResumePlan,
    profile: Profile,
    jd_profile: JDProfile,
    resume_text: str,
    job_description: str,
    context: EvidenceContext,
    provider: LLMProvider | None,
) -> JobFitArtifact:
    """Build the complete artifact; deterministic structure always wins."""
    fit_evidence = _relevant_evidence(plan.evidence)
    assessments = [_assessment(item, index, profile) for index, item in enumerate(fit_evidence, start=1)]
    score = requirement_coverage_score(fit_evidence)
    band = fit_band_for_score(score)
    ats = calculate_ats_score(resume_text, job_description)
    ats_score = float(ats["score"]) if isinstance(ats["score"], (int, float)) else 0.0
    fallback = _deterministic_summary(score, band.value, assessments)
    candidate = generate_text(provider, _prompt(score, band.value, assessments, fallback))
    raw_summary = candidate or fallback

    # The coverage index is an authoritative analysis value, not a claim about
    # the candidate. Mask only the exact deterministic value while the existing
    # candidate-claim grounder checks every other number and assertion.
    score_text = f"{score:.2f}%"
    score_token = "REQUIREMENT_COVERAGE_SCORE"
    if candidate:
        grounded = ground_text(
            raw_summary.replace(score_text, score_token),
            artifact=ArtifactKind.JOB_FIT,
            context=context,
            id_prefix="job-fit-summary",
        )
        grounded.clean_text = grounded.clean_text.replace(score_token, score_text)
    else:
        grounded = _ground_authoritative_summary(
            raw_summary,
            score_text=score_text,
            assessments=assessments,
            context=context,
            id_prefix="job-fit-summary",
        )
    consistency_errors = validate_job_fit_narrative(
        grounded.clean_text,
        score=score,
        band=band,
        requirements=assessments,
        jd_profile=jd_profile,
    )
    repaired_violations = list(consistency_errors)
    summary = grounded.clean_text
    final_grounded = None
    if consistency_errors:
        # One bounded deterministic repair: replace contradictory prose with the
        # authoritative narrative. The violation remains visible in the trace.
        final_grounded = _ground_authoritative_summary(
            fallback,
            score_text=score_text,
            assessments=assessments,
            context=context,
            id_prefix="job-fit-fallback",
        )
        summary = final_grounded.clean_text
    final_errors = validate_job_fit_narrative(
        summary, score=score, band=band, requirements=assessments, jd_profile=jd_profile
    )
    fatal = grounded.fatal or bool(final_errors) or bool(final_grounded and final_grounded.fatal)
    repaired = grounded.repaired + len(repaired_violations) + (final_grounded.repaired if final_grounded else 0)
    status = ArtifactStatus.REJECTED if fatal else (ArtifactStatus.REPAIRED if repaired else ArtifactStatus.GENERATED)
    warnings = [f"Job-fit narrative repaired: {error}" for error in repaired_violations]
    if candidate and grounded.repaired:
        warnings.append("Unsupported candidate claims were removed from provider job-fit prose.")

    classifications: dict[RequirementClassification, list[str]] = {
        classification: [] for classification in RequirementClassification
    }
    for item in assessments:
        classifications[item.classification].append(item.requirement)
    all_evidence = [ref for item in assessments for ref in item.evidence]
    recommendations = [PositioningRecommendation(item.id, item.permitted_positioning) for item in assessments]
    return JobFitArtifact(
        summary="" if fatal else summary,
        requirement_coverage_score=score,
        fit_band=band,
        ats_keyword_score=ats_score,
        interview_probability=plan.interview_probability,
        requirements=assessments,
        strongest_matches=classifications[RequirementClassification.PROVEN],
        adjacent_capabilities=classifications[RequirementClassification.ADJACENT],
        working_knowledge=classifications[RequirementClassification.WORKING_KNOWLEDGE],
        genuine_gaps=classifications[RequirementClassification.GENUINE_GAP],
        must_have_gaps=[
            item.requirement
            for item in assessments
            if item.must_have and item.classification is RequirementClassification.GENUINE_GAP
        ],
        positioning_recommendations=recommendations,
        validation=ArtifactValidation(
            status=status,
            fatal=fatal,
            errors=final_errors,
            warnings=warnings,
            repaired_claims=repaired,
            rejected_claims=grounded.rejected + (final_grounded.rejected if final_grounded else 0),
        ),
        consistency=ConsistencyValidation(
            passed=not final_errors,
            errors=final_errors,
            repaired_violations=repaired_violations,
        ),
        generation=GenerationMetadata(generation_mode="deterministic", llm_available=False),
        claims=grounded.claims + (final_grounded.claims if final_grounded else []),
        evidence=all_evidence,
        warnings=warnings,
        withheld=fatal,
    )
