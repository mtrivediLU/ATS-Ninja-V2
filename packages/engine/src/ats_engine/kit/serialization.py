from __future__ import annotations

from typing import Any

from ats_engine.kit.contract import (
    APPLICATION_KIT_V1,
    APPLICATION_KIT_V2,
    APPLICATION_KIT_V3,
    APPLICATION_KIT_V4,
    SCHEMA_VERSION,
    AnswerArtifact,
    AnswerItem,
    ApplicationKit,
    ArtifactKind,
    ArtifactStatus,
    ArtifactValidation,
    AtsMatchScore,
    AtsQualityReportPayload,
    ChangeOperation,
    ChangeRecord,
    ChangeStatus,
    ChangeType,
    ClaimRecord,
    ClaimStatus,
    ClaimType,
    ConsistencyValidation,
    CoverLetterArtifact,
    CoverLetterDocument,
    EvidenceRef,
    FitBand,
    FitCategory,
    GapHandlingGuide,
    GenerationMetadata,
    InterviewAnswerGuide,
    InterviewerQuestion,
    InterviewFocusArea,
    InterviewPrepArtifact,
    InterviewPriority,
    InterviewQuestion,
    InterviewQuestionCategory,
    JobFitArtifact,
    LinkedInOutreachArtifact,
    MatchReport,
    OutreachAudience,
    OutreachContextKind,
    OutreachContextRef,
    OutreachDraft,
    OutreachFormat,
    OutreachIntent,
    PositioningRecommendation,
    RelationshipValidation,
    RequirementAssessment,
    RequirementClassification,
    RequirementRisk,
    ResumeArtifact,
    ResumeCertificationEntry,
    ResumeDocument,
    ResumeEducationEntry,
    ResumeExperienceEntry,
    ResumeSkillGroup,
    ScoreConfidence,
    StageTimings,
    StarCompleteness,
    StarSourceType,
    StarStoryCandidate,
    TechnicalStudyTopic,
    ValidationSummary,
)

"""JSON serialization boundary for the ApplicationKit contract.

The persisted form is a plain JSON-compatible ``dict`` — no pickle, no ``repr``,
no arbitrary Python objects. This module owns the *only* mapping between the
typed contract and its stored/wire representation, in both directions, plus a
compatibility adapter for kits that were persisted under the Phase 1 result
schema (which predates this contract). See ADR-0012 for the result-evolution
decision.
"""

# Result records written before Phase 2A carry no ``schema_version``. When we
# read one, we adapt it into the canonical response shape under this explicit
# marker rather than silently pretending it is a v1 ApplicationKit.
LEGACY_SCHEMA_VERSION = "phase-1/legacy"

# A result whose schema we do not recognize is surfaced under this marker with a
# warning; it is never silently reinterpreted as a known schema.
UNKNOWN_SCHEMA_VERSION = "unknown"


# --------------------------------------------------------------------------- #
# ApplicationKit -> JSON
# --------------------------------------------------------------------------- #
def application_kit_to_dict(kit: ApplicationKit) -> dict[str, Any]:
    """Serialize an :class:`ApplicationKit` to a JSON-compatible dict."""
    return {
        "schema_version": kit.schema_version,
        "engine_version": kit.engine_version,
        "orchestration_version": kit.orchestration_version,
        "requested_mode": kit.requested_mode,
        "resolved_mode": kit.resolved_mode,
        "generation": _generation_to_dict(kit.generation),
        "validation": _validation_summary_to_dict(kit.validation),
        "resume": _resume_to_dict(kit.resume) if kit.resume is not None else None,
        "cover_letter": (_cover_letter_to_dict(kit.cover_letter) if kit.cover_letter is not None else None),
        "answers": _answers_to_dict(kit.answers) if kit.answers is not None else None,
        "job_fit": _job_fit_to_dict(kit.job_fit) if kit.job_fit is not None else None,
        "interview_prep": (_interview_prep_to_dict(kit.interview_prep) if kit.interview_prep is not None else None),
        "linkedin_outreach": (
            _linkedin_outreach_to_dict(kit.linkedin_outreach) if kit.linkedin_outreach is not None else None
        ),
        "match_report": _match_report_to_dict(kit.match_report) if kit.match_report is not None else None,
        "stage_timings": {"stages_ms": dict(kit.stage_timings.stages_ms)},
        "revision": kit.revision,
        "warnings": list(kit.warnings),
    }


def _change_record_to_dict(record: ChangeRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "artifact": record.artifact.value,
        "change_type": record.change_type.value,
        "operation": record.operation.value,
        "original_text": record.original_text,
        "tailored_text": record.tailored_text,
        "reason": record.reason,
        "status": record.status.value,
        "reversible": record.reversible,
        "matched_keywords": list(record.matched_keywords),
        "evidence": [_evidence_to_dict(ref) for ref in record.evidence],
        "ats_impact": record.ats_impact,
        "ats_impact_delta": record.ats_impact_delta,
        "confidence": record.confidence.value,
        "linked_claim_ids": list(record.linked_claim_ids),
    }


def _ats_match_score_to_dict(score: AtsMatchScore) -> dict[str, Any]:
    return {
        "score": score.score,
        "matched_keywords": list(score.matched_keywords),
        "missing_keywords": list(score.missing_keywords),
        "total_keywords": score.total_keywords,
        "required_matched": score.required_matched,
        "required_total": score.required_total,
        "preferred_matched": score.preferred_matched,
        "preferred_total": score.preferred_total,
    }


def _quality_payload_to_dict(payload: AtsQualityReportPayload) -> dict[str, Any]:
    return {
        "required_term_count": payload.required_term_count,
        "required_supported_count": payload.required_supported_count,
        "required_coverage_percent": payload.required_coverage_percent,
        "preferred_term_count": payload.preferred_term_count,
        "preferred_supported_count": payload.preferred_supported_count,
        "preferred_coverage_percent": payload.preferred_coverage_percent,
        "exact_target_title_present": payload.exact_target_title_present,
        "section_presence": dict(payload.section_presence),
        "contact_issue_count": payload.contact_issue_count,
        "contact_issues": list(payload.contact_issues),
        "measurable_result_count": payload.measurable_result_count,
        "word_count": payload.word_count,
        "unsupported_requirement_count": payload.unsupported_requirement_count,
        "adjacency_count": payload.adjacency_count,
        "working_knowledge_count": payload.working_knowledge_count,
        "formatting_warnings": list(payload.formatting_warnings),
        "duplicate_keyword_warnings": list(payload.duplicate_keyword_warnings),
        "generic_language_warnings": list(payload.generic_language_warnings),
    }


def _match_report_to_dict(report: MatchReport) -> dict[str, Any]:
    return {
        "original_ats_match": _ats_match_score_to_dict(report.original_ats_match),
        "tailored_ats_match": (
            _ats_match_score_to_dict(report.tailored_ats_match) if report.tailored_ats_match is not None else None
        ),
        "alignment_score": report.alignment_score,
        "fit_band": report.fit_band.value,
        "fit_category": report.fit_category.value,
        "confidence": report.confidence.value,
        "confidence_reasons": list(report.confidence_reasons),
        "strongest_matches": list(report.strongest_matches),
        "genuine_gaps": list(report.genuine_gaps),
        "must_have_gaps": list(report.must_have_gaps),
        "keywords_matched_original": list(report.keywords_matched_original),
        "keywords_surfaced_by_tailoring": list(report.keywords_surfaced_by_tailoring),
        "keywords_still_missing": list(report.keywords_still_missing),
        "recommendation": report.recommendation,
        "kit_summary": report.kit_summary,
        "quality_report": _quality_payload_to_dict(report.quality_report),
        "disclaimer": report.disclaimer,
    }


def _evidence_to_dict(ref: EvidenceRef) -> dict[str, Any]:
    return {"source": ref.source, "locator": ref.locator, "excerpt": ref.excerpt}


def _claim_to_dict(claim: ClaimRecord) -> dict[str, Any]:
    return {
        "id": claim.id,
        "artifact": claim.artifact.value,
        "claim_type": claim.claim_type.value,
        "text": claim.text,
        "status": claim.status.value,
        "disposition": claim.disposition,
        "reason": claim.reason,
        "evidence": [_evidence_to_dict(ref) for ref in claim.evidence],
    }


def _artifact_validation_to_dict(validation: ArtifactValidation) -> dict[str, Any]:
    return {
        "status": validation.status.value,
        "fatal": validation.fatal,
        "errors": list(validation.errors),
        "warnings": list(validation.warnings),
        "repaired_claims": validation.repaired_claims,
        "rejected_claims": validation.rejected_claims,
    }


def _resume_to_dict(resume: ResumeArtifact) -> dict[str, Any]:
    return {
        "text": resume.text,
        "latex": resume.latex,
        "validation": _artifact_validation_to_dict(resume.validation),
        "claims": [_claim_to_dict(claim) for claim in resume.claims],
        "interview_probability": resume.interview_probability,
        "document": _resume_document_to_dict(resume.document) if resume.document is not None else None,
        "change_ledger": [_change_record_to_dict(record) for record in resume.change_ledger],
    }


def _cover_letter_to_dict(cover: CoverLetterArtifact) -> dict[str, Any]:
    return {
        "text": cover.text,
        "latex": cover.latex,
        "validation": _artifact_validation_to_dict(cover.validation),
        "claims": [_claim_to_dict(claim) for claim in cover.claims],
        "document": _cover_document_to_dict(cover.document) if cover.document is not None else None,
        "change_ledger": [_change_record_to_dict(record) for record in cover.change_ledger],
    }


def _resume_document_to_dict(document: ResumeDocument) -> dict[str, Any]:
    return {
        "candidate_name": document.candidate_name,
        "professional_headline": document.professional_headline,
        "contact_lines": list(document.contact_lines),
        "summary": document.summary,
        "skill_groups": [{"label": group.label, "items": list(group.items)} for group in document.skill_groups],
        "experience": [
            {
                "employer": item.employer,
                "title": item.title,
                "location": item.location,
                "date_range": item.date_range,
                "bullets": list(item.bullets),
            }
            for item in document.experience
        ],
        "education": [
            {
                "institution": item.institution,
                "degree": item.degree,
                "location": item.location,
                "date_range": item.date_range,
                "details": list(item.details),
            }
            for item in document.education
        ],
        "certifications": [
            {"name": item.name, "date": item.date, "link": item.link} for item in document.certifications
        ],
        "remaining_sections": [
            {"heading": heading, "lines": list(lines)} for heading, lines in document.remaining_sections
        ],
    }


def _cover_document_to_dict(document: CoverLetterDocument) -> dict[str, Any]:
    return {
        "sender_name": document.sender_name,
        "sender_contact_lines": list(document.sender_contact_lines),
        "date": document.date,
        "recipient_name": document.recipient_name,
        "recipient_title": document.recipient_title,
        "recipient_company": document.recipient_company,
        "recipient_address": list(document.recipient_address),
        "target_role": document.target_role,
        "greeting": document.greeting,
        "body_paragraphs": list(document.body_paragraphs),
        "closing": document.closing,
        "signature_name": document.signature_name,
    }


def _answers_to_dict(answers: AnswerArtifact) -> dict[str, Any]:
    return {
        "items": [{"question": item.question, "answer": item.answer} for item in answers.items],
        "text": answers.text,
        "validation": _artifact_validation_to_dict(answers.validation),
        "claims": [_claim_to_dict(claim) for claim in answers.claims],
        "placeholders": list(answers.placeholders),
    }


def _requirement_to_dict(item: RequirementAssessment) -> dict[str, Any]:
    return {
        "id": item.id,
        "requirement": item.requirement,
        "importance": item.importance,
        "must_have": item.must_have,
        "classification": item.classification.value,
        "explanation": item.explanation,
        "risk": item.risk.value,
        "permitted_positioning": item.permitted_positioning,
        "evidence": [_evidence_to_dict(ref) for ref in item.evidence],
    }


def _job_fit_to_dict(job_fit: JobFitArtifact) -> dict[str, Any]:
    return {
        "summary": job_fit.summary,
        "requirement_coverage_score": job_fit.requirement_coverage_score,
        "fit_band": job_fit.fit_band.value,
        "ats_keyword_score": job_fit.ats_keyword_score,
        "interview_probability": job_fit.interview_probability,
        "requirements": [_requirement_to_dict(item) for item in job_fit.requirements],
        "strongest_matches": list(job_fit.strongest_matches),
        "adjacent_capabilities": list(job_fit.adjacent_capabilities),
        "working_knowledge": list(job_fit.working_knowledge),
        "genuine_gaps": list(job_fit.genuine_gaps),
        "must_have_gaps": list(job_fit.must_have_gaps),
        "positioning_recommendations": [
            {"requirement_id": item.requirement_id, "text": item.text} for item in job_fit.positioning_recommendations
        ],
        "validation": _artifact_validation_to_dict(job_fit.validation),
        "consistency": {
            "passed": job_fit.consistency.passed,
            "errors": list(job_fit.consistency.errors),
            "repaired_violations": list(job_fit.consistency.repaired_violations),
        },
        "generation": _generation_to_dict(job_fit.generation),
        "claims": [_claim_to_dict(claim) for claim in job_fit.claims],
        "evidence": [_evidence_to_dict(ref) for ref in job_fit.evidence],
        "warnings": list(job_fit.warnings),
        "withheld": job_fit.withheld,
    }


def _answer_guide_to_dict(guide: InterviewAnswerGuide) -> dict[str, Any]:
    return {
        "key_points": list(guide.key_points),
        "statements_to_avoid": list(guide.statements_to_avoid),
        "suggested_answer": guide.suggested_answer,
        "honest_gap_language": guide.honest_gap_language,
        "evidence": [_evidence_to_dict(ref) for ref in guide.evidence],
    }


def _interview_prep_to_dict(artifact: InterviewPrepArtifact) -> dict[str, Any]:
    return {
        "strategy_summary": artifact.strategy_summary,
        "focus_areas": [
            {
                "requirement_id": item.requirement_id,
                "topic": item.topic,
                "classification": item.classification.value,
                "priority": item.priority.value,
                "guidance": item.guidance,
                "evidence": [_evidence_to_dict(ref) for ref in item.evidence],
            }
            for item in artifact.focus_areas
        ],
        "questions": [
            {
                "id": item.id,
                "category": item.category.value,
                "question": item.question,
                "rationale": item.rationale,
                "related_requirement_ids": list(item.related_requirement_ids),
                "priority": item.priority.value,
                "answer_guide": _answer_guide_to_dict(item.answer_guide),
                "evidence": [_evidence_to_dict(ref) for ref in item.evidence],
                "gap_relevance": item.gap_relevance,
                "validation": _artifact_validation_to_dict(item.validation),
            }
            for item in artifact.questions
        ],
        "star_stories": [
            {
                "id": item.id,
                "source_type": item.source_type.value,
                "employer_or_institution": item.employer_or_institution,
                "title_or_degree": item.title_or_degree,
                "situation": item.situation,
                "task": item.task,
                "action": item.action,
                "result": item.result,
                "completeness": item.completeness.value,
                "missing_components": list(item.missing_components),
                "safe_usage_guidance": item.safe_usage_guidance,
                "evidence": [_evidence_to_dict(ref) for ref in item.evidence],
                "validation": _artifact_validation_to_dict(item.validation),
            }
            for item in artifact.star_stories
        ],
        "technical_study_topics": [
            {
                "requirement_id": item.requirement_id,
                "topic": item.topic,
                "reason": item.reason,
                "boundary": item.boundary,
                "priority": item.priority.value,
            }
            for item in artifact.technical_study_topics
        ],
        "gap_handling": [
            {
                "requirement_id": item.requirement_id,
                "requirement": item.requirement,
                "classification": item.classification.value,
                "must_have": item.must_have,
                "guidance": item.guidance,
                "what_to_avoid": list(item.what_to_avoid),
                "evidence": [_evidence_to_dict(ref) for ref in item.evidence],
            }
            for item in artifact.gap_handling
        ],
        "positioning_recommendations": [
            {"requirement_id": item.requirement_id, "text": item.text} for item in artifact.positioning_recommendations
        ],
        "interviewer_questions": [
            {"id": item.id, "question": item.question, "rationale": item.rationale, "source": item.source}
            for item in artifact.interviewer_questions
        ],
        "validation": _artifact_validation_to_dict(artifact.validation),
        "consistency": {
            "passed": artifact.consistency.passed,
            "errors": list(artifact.consistency.errors),
            "repaired_violations": list(artifact.consistency.repaired_violations),
        },
        "generation": _generation_to_dict(artifact.generation),
        "claims": [_claim_to_dict(claim) for claim in artifact.claims],
        "evidence": [_evidence_to_dict(ref) for ref in artifact.evidence],
        "warnings": list(artifact.warnings),
        "withheld": artifact.withheld,
    }


def _context_ref_to_dict(ref: OutreachContextRef) -> dict[str, Any]:
    return {"kind": ref.kind.value, "field": ref.field, "excerpt": ref.excerpt}


def _outreach_draft_to_dict(draft: OutreachDraft) -> dict[str, Any]:
    return {
        "id": draft.id,
        "audience": draft.audience.value,
        "intent": draft.intent.value,
        "format": draft.format.value,
        "text": draft.text,
        "character_count": draft.character_count,
        "character_limit": draft.character_limit,
        "target_company": draft.target_company,
        "target_role": draft.target_role,
        "personalization_fields": list(draft.personalization_fields),
        "call_to_action": draft.call_to_action,
        "evidence": [_evidence_to_dict(ref) for ref in draft.evidence],
        "target_context": [_context_ref_to_dict(ref) for ref in draft.target_context],
        "relationship_context": [_context_ref_to_dict(ref) for ref in draft.relationship_context],
        "validation": _artifact_validation_to_dict(draft.validation),
    }


def _linkedin_outreach_to_dict(artifact: LinkedInOutreachArtifact) -> dict[str, Any]:
    return {
        "strategy_summary": artifact.strategy_summary,
        "drafts": [_outreach_draft_to_dict(draft) for draft in artifact.drafts],
        "validation": _artifact_validation_to_dict(artifact.validation),
        "consistency": {
            "passed": artifact.consistency.passed,
            "errors": list(artifact.consistency.errors),
            "repaired_violations": list(artifact.consistency.repaired_violations),
        },
        "relationship_validation": {
            "passed": artifact.relationship_validation.passed,
            "errors": list(artifact.relationship_validation.errors),
            "repaired_violations": list(artifact.relationship_validation.repaired_violations),
        },
        "generation": _generation_to_dict(artifact.generation),
        "claims": [_claim_to_dict(claim) for claim in artifact.claims],
        "evidence": [_evidence_to_dict(ref) for ref in artifact.evidence],
        "target_context": [_context_ref_to_dict(ref) for ref in artifact.target_context],
        "relationship_context": [_context_ref_to_dict(ref) for ref in artifact.relationship_context],
        "warnings": list(artifact.warnings),
        "withheld": artifact.withheld,
    }


def _generation_to_dict(meta: GenerationMetadata) -> dict[str, Any]:
    return {
        "generation_mode": meta.generation_mode,
        "llm_available": meta.llm_available,
        "provider": meta.provider,
        "model": meta.model,
        "provider_calls": meta.provider_calls,
        "fallback_used": meta.fallback_used,
    }


def _validation_summary_to_dict(summary: ValidationSummary) -> dict[str, Any]:
    return {
        "passed": summary.passed,
        "fatal": summary.fatal,
        "error_count": summary.error_count,
        "warning_count": summary.warning_count,
        "errors": list(summary.errors),
        "warnings": list(summary.warnings),
    }


# --------------------------------------------------------------------------- #
# JSON -> ApplicationKit
# --------------------------------------------------------------------------- #
def application_kit_from_dict(data: dict[str, Any]) -> ApplicationKit:
    """Reconstruct an :class:`ApplicationKit` from its JSON-compatible dict."""
    return ApplicationKit(
        schema_version=str(data["schema_version"]),
        engine_version=str(data.get("engine_version", "")),
        orchestration_version=str(data.get("orchestration_version", "")),
        requested_mode=str(data.get("requested_mode", "")),
        resolved_mode=str(data.get("resolved_mode", "")),
        generation=_generation_from_dict(data.get("generation") or {}),
        validation=_validation_summary_from_dict(data.get("validation") or {}),
        resume=_resume_from_dict(data.get("resume")),
        cover_letter=_cover_letter_from_dict(data.get("cover_letter")),
        answers=_answers_from_dict(data.get("answers")),
        job_fit=_job_fit_from_dict(data.get("job_fit")),
        interview_prep=_interview_prep_from_dict(data.get("interview_prep")),
        linkedin_outreach=_linkedin_outreach_from_dict(data.get("linkedin_outreach")),
        match_report=_match_report_from_dict(data.get("match_report")),
        stage_timings=_stage_timings_from_dict(data.get("stage_timings")),
        revision=int(data.get("revision", 0)),
        warnings=[str(item) for item in data.get("warnings") or []],
    )


def _stage_timings_from_dict(raw: object) -> StageTimings:
    stages: dict[str, int] = {}
    if isinstance(raw, dict):
        source = raw.get("stages_ms") if isinstance(raw.get("stages_ms"), dict) else raw
        if isinstance(source, dict):
            for key, value in source.items():
                try:
                    stages[str(key)] = int(value)
                except (TypeError, ValueError):
                    continue
    return StageTimings(stages_ms=stages)


def _change_record_from_dict(raw: dict[str, Any]) -> ChangeRecord:
    return ChangeRecord(
        id=str(raw.get("id", "")),
        artifact=ArtifactKind(str(raw.get("artifact", ArtifactKind.RESUME.value))),
        change_type=ChangeType(str(raw.get("change_type", ChangeType.BULLET.value))),
        operation=ChangeOperation(str(raw.get("operation", ChangeOperation.ADDED.value))),
        original_text=str(raw.get("original_text", "")),
        tailored_text=str(raw.get("tailored_text", "")),
        reason=str(raw.get("reason", "")),
        status=ChangeStatus(str(raw.get("status", ChangeStatus.PROPOSED.value))),
        reversible=bool(raw.get("reversible", True)),
        matched_keywords=[str(item) for item in raw.get("matched_keywords") or []],
        evidence=[_evidence_from_dict(ref) for ref in raw.get("evidence") or []],
        ats_impact=str(raw.get("ats_impact", "")),
        ats_impact_delta=float(raw.get("ats_impact_delta", 0.0)),
        confidence=ScoreConfidence(str(raw.get("confidence", ScoreConfidence.MEDIUM.value))),
        linked_claim_ids=[str(item) for item in raw.get("linked_claim_ids") or []],
    )


def _ats_match_score_from_dict(raw: object) -> AtsMatchScore:
    data = raw if isinstance(raw, dict) else {}
    return AtsMatchScore(
        score=float(data.get("score", 0.0)),
        matched_keywords=[str(item) for item in data.get("matched_keywords") or []],
        missing_keywords=[str(item) for item in data.get("missing_keywords") or []],
        total_keywords=int(data.get("total_keywords", 0)),
        required_matched=int(data.get("required_matched", 0)),
        required_total=int(data.get("required_total", 0)),
        preferred_matched=int(data.get("preferred_matched", 0)),
        preferred_total=int(data.get("preferred_total", 0)),
    )


def _quality_payload_from_dict(raw: object) -> AtsQualityReportPayload:
    data = raw if isinstance(raw, dict) else {}
    section = data.get("section_presence")
    return AtsQualityReportPayload(
        required_term_count=int(data.get("required_term_count", 0)),
        required_supported_count=int(data.get("required_supported_count", 0)),
        required_coverage_percent=float(data.get("required_coverage_percent", 0.0)),
        preferred_term_count=int(data.get("preferred_term_count", 0)),
        preferred_supported_count=int(data.get("preferred_supported_count", 0)),
        preferred_coverage_percent=float(data.get("preferred_coverage_percent", 0.0)),
        exact_target_title_present=bool(data.get("exact_target_title_present", False)),
        section_presence={str(k): bool(v) for k, v in section.items()} if isinstance(section, dict) else {},
        contact_issue_count=int(data.get("contact_issue_count", 0)),
        contact_issues=[str(item) for item in data.get("contact_issues") or []],
        measurable_result_count=int(data.get("measurable_result_count", 0)),
        word_count=int(data.get("word_count", 0)),
        unsupported_requirement_count=int(data.get("unsupported_requirement_count", 0)),
        adjacency_count=int(data.get("adjacency_count", 0)),
        working_knowledge_count=int(data.get("working_knowledge_count", 0)),
        formatting_warnings=[str(item) for item in data.get("formatting_warnings") or []],
        duplicate_keyword_warnings=[str(item) for item in data.get("duplicate_keyword_warnings") or []],
        generic_language_warnings=[str(item) for item in data.get("generic_language_warnings") or []],
    )


def _match_report_from_dict(raw: object) -> MatchReport | None:
    if not isinstance(raw, dict):
        return None
    tailored = raw.get("tailored_ats_match")
    return MatchReport(
        original_ats_match=_ats_match_score_from_dict(raw.get("original_ats_match")),
        alignment_score=float(raw.get("alignment_score", 0.0)),
        fit_band=FitBand(str(raw.get("fit_band", FitBand.LOW.value))),
        fit_category=FitCategory(str(raw.get("fit_category", FitCategory.LOW_ALIGNMENT.value))),
        confidence=ScoreConfidence(str(raw.get("confidence", ScoreConfidence.MEDIUM.value))),
        confidence_reasons=[str(item) for item in raw.get("confidence_reasons") or []],
        tailored_ats_match=_ats_match_score_from_dict(tailored) if tailored is not None else None,
        strongest_matches=[str(item) for item in raw.get("strongest_matches") or []],
        genuine_gaps=[str(item) for item in raw.get("genuine_gaps") or []],
        must_have_gaps=[str(item) for item in raw.get("must_have_gaps") or []],
        keywords_matched_original=[str(item) for item in raw.get("keywords_matched_original") or []],
        keywords_surfaced_by_tailoring=[str(item) for item in raw.get("keywords_surfaced_by_tailoring") or []],
        keywords_still_missing=[str(item) for item in raw.get("keywords_still_missing") or []],
        recommendation=str(raw.get("recommendation", "")),
        kit_summary=str(raw.get("kit_summary", "")),
        quality_report=_quality_payload_from_dict(raw.get("quality_report")),
        disclaimer=str(raw.get("disclaimer", "")),
    )


def _evidence_from_dict(raw: dict[str, Any]) -> EvidenceRef:
    return EvidenceRef(
        source=str(raw.get("source", "")),
        locator=str(raw.get("locator", "")),
        excerpt=str(raw.get("excerpt", "")),
    )


def _claim_from_dict(raw: dict[str, Any]) -> ClaimRecord:
    return ClaimRecord(
        id=str(raw.get("id", "")),
        artifact=ArtifactKind(str(raw.get("artifact"))),
        claim_type=ClaimType(str(raw.get("claim_type"))),
        text=str(raw.get("text", "")),
        status=ClaimStatus(str(raw.get("status"))),
        disposition=str(raw.get("disposition", "")),
        reason=str(raw.get("reason", "")),
        evidence=[_evidence_from_dict(ref) for ref in raw.get("evidence") or []],
    )


def _artifact_validation_from_dict(raw: dict[str, Any]) -> ArtifactValidation:
    return ArtifactValidation(
        status=ArtifactStatus(str(raw.get("status", ArtifactStatus.GENERATED.value))),
        fatal=bool(raw.get("fatal", False)),
        errors=[str(item) for item in raw.get("errors") or []],
        warnings=[str(item) for item in raw.get("warnings") or []],
        repaired_claims=int(raw.get("repaired_claims", 0)),
        rejected_claims=int(raw.get("rejected_claims", 0)),
    )


def _resume_from_dict(raw: dict[str, Any] | None) -> ResumeArtifact | None:
    if raw is None:
        return None
    probability = raw.get("interview_probability")
    return ResumeArtifact(
        text=str(raw.get("text", "")),
        latex=str(raw.get("latex", "")),
        validation=_artifact_validation_from_dict(raw.get("validation") or {}),
        claims=[_claim_from_dict(claim) for claim in raw.get("claims") or []],
        interview_probability=int(probability) if probability is not None else None,
        document=_resume_document_from_dict(raw.get("document")),
        change_ledger=[_change_record_from_dict(record) for record in raw.get("change_ledger") or []],
    )


def _cover_letter_from_dict(raw: dict[str, Any] | None) -> CoverLetterArtifact | None:
    if raw is None:
        return None
    return CoverLetterArtifact(
        text=str(raw.get("text", "")),
        latex=str(raw.get("latex", "")),
        validation=_artifact_validation_from_dict(raw.get("validation") or {}),
        claims=[_claim_from_dict(claim) for claim in raw.get("claims") or []],
        document=_cover_document_from_dict(raw.get("document")),
        change_ledger=[_change_record_from_dict(record) for record in raw.get("change_ledger") or []],
    )


def _resume_document_from_dict(raw: object) -> ResumeDocument | None:
    if not isinstance(raw, dict):
        return None
    return ResumeDocument(
        candidate_name=str(raw.get("candidate_name", "")),
        professional_headline=str(raw.get("professional_headline", "")),
        contact_lines=[str(item) for item in raw.get("contact_lines") or []],
        summary=str(raw.get("summary", "")),
        skill_groups=[
            ResumeSkillGroup(label=str(item.get("label", "")), items=[str(value) for value in item.get("items") or []])
            for item in raw.get("skill_groups") or []
            if isinstance(item, dict)
        ],
        experience=[
            ResumeExperienceEntry(
                employer=str(item.get("employer", "")),
                title=str(item.get("title", "")),
                location=str(item.get("location", "")),
                date_range=str(item.get("date_range", "")),
                bullets=[str(value) for value in item.get("bullets") or []],
            )
            for item in raw.get("experience") or []
            if isinstance(item, dict)
        ],
        education=[
            ResumeEducationEntry(
                institution=str(item.get("institution", "")),
                degree=str(item.get("degree", "")),
                location=str(item.get("location", "")),
                date_range=str(item.get("date_range", "")),
                details=[str(value) for value in item.get("details") or []],
            )
            for item in raw.get("education") or []
            if isinstance(item, dict)
        ],
        certifications=[
            ResumeCertificationEntry(
                name=str(item.get("name", "")), date=str(item.get("date", "")), link=str(item.get("link", ""))
            )
            for item in raw.get("certifications") or []
            if isinstance(item, dict)
        ],
        remaining_sections=[
            (str(item.get("heading", "")), [str(value) for value in item.get("lines") or []])
            for item in raw.get("remaining_sections") or []
            if isinstance(item, dict)
        ],
    )


def _cover_document_from_dict(raw: object) -> CoverLetterDocument | None:
    if not isinstance(raw, dict):
        return None
    return CoverLetterDocument(
        sender_name=str(raw.get("sender_name", "")),
        sender_contact_lines=[str(item) for item in raw.get("sender_contact_lines") or []],
        date=str(raw.get("date", "")),
        recipient_name=str(raw.get("recipient_name", "")),
        recipient_title=str(raw.get("recipient_title", "")),
        recipient_company=str(raw.get("recipient_company", "")),
        recipient_address=[str(item) for item in raw.get("recipient_address") or []],
        target_role=str(raw.get("target_role", "")),
        greeting=str(raw.get("greeting", "")),
        body_paragraphs=[str(item) for item in raw.get("body_paragraphs") or []],
        closing=str(raw.get("closing", "")),
        signature_name=str(raw.get("signature_name", "")),
    )


def _answers_from_dict(raw: dict[str, Any] | None) -> AnswerArtifact | None:
    if raw is None:
        return None
    return AnswerArtifact(
        items=[
            AnswerItem(question=str(item.get("question", "")), answer=str(item.get("answer", "")))
            for item in raw.get("items") or []
        ],
        text=str(raw.get("text", "")),
        validation=_artifact_validation_from_dict(raw.get("validation") or {}),
        claims=[_claim_from_dict(claim) for claim in raw.get("claims") or []],
        placeholders=[str(item) for item in raw.get("placeholders") or []],
    )


def _requirement_from_dict(raw: dict[str, Any]) -> RequirementAssessment:
    return RequirementAssessment(
        id=str(raw.get("id", "")),
        requirement=str(raw.get("requirement", "")),
        importance=str(raw.get("importance", "")),
        must_have=bool(raw.get("must_have", False)),
        classification=RequirementClassification(str(raw.get("classification", "genuine_gap"))),
        explanation=str(raw.get("explanation", "")),
        risk=RequirementRisk(str(raw.get("risk", "high"))),
        permitted_positioning=str(raw.get("permitted_positioning", "")),
        evidence=[_evidence_from_dict(ref) for ref in raw.get("evidence") or []],
    )


def _job_fit_from_dict(raw: dict[str, Any] | None) -> JobFitArtifact | None:
    if raw is None:
        return None
    probability = raw.get("interview_probability")
    consistency = raw.get("consistency") or {}
    return JobFitArtifact(
        summary=str(raw.get("summary", "")),
        requirement_coverage_score=float(raw.get("requirement_coverage_score", 0.0)),
        fit_band=FitBand(str(raw.get("fit_band", FitBand.LOW.value))),
        ats_keyword_score=float(raw.get("ats_keyword_score", 0.0)),
        interview_probability=int(probability) if probability is not None else None,
        requirements=[_requirement_from_dict(item) for item in raw.get("requirements") or []],
        strongest_matches=[str(item) for item in raw.get("strongest_matches") or []],
        adjacent_capabilities=[str(item) for item in raw.get("adjacent_capabilities") or []],
        working_knowledge=[str(item) for item in raw.get("working_knowledge") or []],
        genuine_gaps=[str(item) for item in raw.get("genuine_gaps") or []],
        must_have_gaps=[str(item) for item in raw.get("must_have_gaps") or []],
        positioning_recommendations=[
            PositioningRecommendation(
                requirement_id=str(item.get("requirement_id", "")), text=str(item.get("text", ""))
            )
            for item in raw.get("positioning_recommendations") or []
        ],
        validation=_artifact_validation_from_dict(raw.get("validation") or {}),
        consistency=ConsistencyValidation(
            passed=bool(consistency.get("passed", False)),
            errors=[str(item) for item in consistency.get("errors") or []],
            repaired_violations=[str(item) for item in consistency.get("repaired_violations") or []],
        ),
        generation=_generation_from_dict(raw.get("generation") or {}),
        claims=[_claim_from_dict(claim) for claim in raw.get("claims") or []],
        evidence=[_evidence_from_dict(ref) for ref in raw.get("evidence") or []],
        warnings=[str(item) for item in raw.get("warnings") or []],
        withheld=bool(raw.get("withheld", False)),
    )


def _answer_guide_from_dict(raw: dict[str, Any]) -> InterviewAnswerGuide:
    return InterviewAnswerGuide(
        key_points=[str(item) for item in raw.get("key_points") or []],
        statements_to_avoid=[str(item) for item in raw.get("statements_to_avoid") or []],
        suggested_answer=str(raw.get("suggested_answer", "")),
        honest_gap_language=str(raw.get("honest_gap_language", "")),
        evidence=[_evidence_from_dict(ref) for ref in raw.get("evidence") or []],
    )


def _interview_prep_from_dict(raw: dict[str, Any] | None) -> InterviewPrepArtifact | None:
    if raw is None:
        return None
    consistency = raw.get("consistency") or {}
    return InterviewPrepArtifact(
        strategy_summary=str(raw.get("strategy_summary", "")),
        focus_areas=[
            InterviewFocusArea(
                requirement_id=str(item.get("requirement_id", "")),
                topic=str(item.get("topic", "")),
                classification=RequirementClassification(str(item.get("classification", "genuine_gap"))),
                priority=InterviewPriority(str(item.get("priority", "medium"))),
                guidance=str(item.get("guidance", "")),
                evidence=[_evidence_from_dict(ref) for ref in item.get("evidence") or []],
            )
            for item in raw.get("focus_areas") or []
        ],
        questions=[
            InterviewQuestion(
                id=str(item.get("id", "")),
                category=InterviewQuestionCategory(str(item.get("category", "role_specific"))),
                question=str(item.get("question", "")),
                rationale=str(item.get("rationale", "")),
                related_requirement_ids=[str(value) for value in item.get("related_requirement_ids") or []],
                priority=InterviewPriority(str(item.get("priority", "medium"))),
                answer_guide=_answer_guide_from_dict(item.get("answer_guide") or {}),
                evidence=[_evidence_from_dict(ref) for ref in item.get("evidence") or []],
                gap_relevance=str(item.get("gap_relevance", "")),
                validation=_artifact_validation_from_dict(item.get("validation") or {}),
            )
            for item in raw.get("questions") or []
        ],
        star_stories=[
            StarStoryCandidate(
                id=str(item.get("id", "")),
                source_type=StarSourceType(str(item.get("source_type", "professional"))),
                employer_or_institution=str(item.get("employer_or_institution", "")),
                title_or_degree=str(item.get("title_or_degree", "")),
                situation=str(item.get("situation", "")),
                task=str(item.get("task", "")),
                action=str(item.get("action", "")),
                result=str(item.get("result", "")),
                completeness=StarCompleteness(str(item.get("completeness", "incomplete"))),
                missing_components=[str(value) for value in item.get("missing_components") or []],
                safe_usage_guidance=str(item.get("safe_usage_guidance", "")),
                evidence=[_evidence_from_dict(ref) for ref in item.get("evidence") or []],
                validation=_artifact_validation_from_dict(item.get("validation") or {}),
            )
            for item in raw.get("star_stories") or []
        ],
        technical_study_topics=[
            TechnicalStudyTopic(
                requirement_id=str(item.get("requirement_id", "")),
                topic=str(item.get("topic", "")),
                reason=str(item.get("reason", "")),
                boundary=str(item.get("boundary", "")),
                priority=InterviewPriority(str(item.get("priority", "medium"))),
            )
            for item in raw.get("technical_study_topics") or []
        ],
        gap_handling=[
            GapHandlingGuide(
                requirement_id=str(item.get("requirement_id", "")),
                requirement=str(item.get("requirement", "")),
                classification=RequirementClassification(str(item.get("classification", "genuine_gap"))),
                must_have=bool(item.get("must_have", False)),
                guidance=str(item.get("guidance", "")),
                what_to_avoid=[str(value) for value in item.get("what_to_avoid") or []],
                evidence=[_evidence_from_dict(ref) for ref in item.get("evidence") or []],
            )
            for item in raw.get("gap_handling") or []
        ],
        positioning_recommendations=[
            PositioningRecommendation(
                requirement_id=str(item.get("requirement_id", "")), text=str(item.get("text", ""))
            )
            for item in raw.get("positioning_recommendations") or []
        ],
        interviewer_questions=[
            InterviewerQuestion(
                id=str(item.get("id", "")),
                question=str(item.get("question", "")),
                rationale=str(item.get("rationale", "")),
                source=str(item.get("source", "")),
            )
            for item in raw.get("interviewer_questions") or []
        ],
        validation=_artifact_validation_from_dict(raw.get("validation") or {}),
        consistency=ConsistencyValidation(
            passed=bool(consistency.get("passed", False)),
            errors=[str(item) for item in consistency.get("errors") or []],
            repaired_violations=[str(item) for item in consistency.get("repaired_violations") or []],
        ),
        generation=_generation_from_dict(raw.get("generation") or {}),
        claims=[_claim_from_dict(item) for item in raw.get("claims") or []],
        evidence=[_evidence_from_dict(item) for item in raw.get("evidence") or []],
        warnings=[str(item) for item in raw.get("warnings") or []],
        withheld=bool(raw.get("withheld", False)),
    )


def _context_ref_from_dict(raw: dict[str, Any]) -> OutreachContextRef:
    return OutreachContextRef(
        kind=OutreachContextKind(str(raw.get("kind", OutreachContextKind.TARGET_JOB.value))),
        field=str(raw.get("field", "")),
        excerpt=str(raw.get("excerpt", "")),
    )


def _outreach_draft_from_dict(raw: dict[str, Any]) -> OutreachDraft:
    return OutreachDraft(
        id=str(raw.get("id", "")),
        audience=OutreachAudience(str(raw.get("audience", OutreachAudience.RECRUITER.value))),
        intent=OutreachIntent(str(raw.get("intent", OutreachIntent.CONNECT.value))),
        format=OutreachFormat(str(raw.get("format", OutreachFormat.CONNECTION_NOTE.value))),
        text=str(raw.get("text", "")),
        character_count=int(raw.get("character_count", 0)),
        character_limit=int(raw.get("character_limit", 0)),
        target_company=str(raw.get("target_company", "")),
        target_role=str(raw.get("target_role", "")),
        personalization_fields=[str(item) for item in raw.get("personalization_fields") or []],
        call_to_action=str(raw.get("call_to_action", "")),
        evidence=[_evidence_from_dict(ref) for ref in raw.get("evidence") or []],
        target_context=[_context_ref_from_dict(ref) for ref in raw.get("target_context") or []],
        relationship_context=[_context_ref_from_dict(ref) for ref in raw.get("relationship_context") or []],
        validation=_artifact_validation_from_dict(raw.get("validation") or {}),
    )


def _linkedin_outreach_from_dict(raw: dict[str, Any] | None) -> LinkedInOutreachArtifact | None:
    if raw is None:
        return None
    consistency = raw.get("consistency") or {}
    relationship = raw.get("relationship_validation") or {}
    return LinkedInOutreachArtifact(
        strategy_summary=str(raw.get("strategy_summary", "")),
        drafts=[_outreach_draft_from_dict(item) for item in raw.get("drafts") or []],
        validation=_artifact_validation_from_dict(raw.get("validation") or {}),
        consistency=ConsistencyValidation(
            passed=bool(consistency.get("passed", False)),
            errors=[str(item) for item in consistency.get("errors") or []],
            repaired_violations=[str(item) for item in consistency.get("repaired_violations") or []],
        ),
        relationship_validation=RelationshipValidation(
            passed=bool(relationship.get("passed", False)),
            errors=[str(item) for item in relationship.get("errors") or []],
            repaired_violations=[str(item) for item in relationship.get("repaired_violations") or []],
        ),
        generation=_generation_from_dict(raw.get("generation") or {}),
        claims=[_claim_from_dict(item) for item in raw.get("claims") or []],
        evidence=[_evidence_from_dict(item) for item in raw.get("evidence") or []],
        target_context=[_context_ref_from_dict(item) for item in raw.get("target_context") or []],
        relationship_context=[_context_ref_from_dict(item) for item in raw.get("relationship_context") or []],
        warnings=[str(item) for item in raw.get("warnings") or []],
        withheld=bool(raw.get("withheld", False)),
    )


def _generation_from_dict(raw: dict[str, Any]) -> GenerationMetadata:
    return GenerationMetadata(
        generation_mode=str(raw.get("generation_mode", "deterministic")),
        llm_available=bool(raw.get("llm_available", False)),
        provider=str(raw.get("provider", "")),
        model=str(raw.get("model", "")),
        provider_calls=int(raw.get("provider_calls", 0)),
        fallback_used=bool(raw.get("fallback_used", False)),
    )


def _validation_summary_from_dict(raw: dict[str, Any]) -> ValidationSummary:
    errors = [str(item) for item in raw.get("errors") or []]
    warnings = [str(item) for item in raw.get("warnings") or []]
    return ValidationSummary(
        passed=bool(raw.get("passed", not errors)),
        fatal=bool(raw.get("fatal", False)),
        error_count=int(raw.get("error_count", len(errors))),
        warning_count=int(raw.get("warning_count", len(warnings))),
        errors=errors,
        warnings=warnings,
    )


# --------------------------------------------------------------------------- #
# Result schema evolution (Phase 1 legacy compatibility)
# --------------------------------------------------------------------------- #
def is_application_kit_v1(raw: dict[str, Any]) -> bool:
    """True when a persisted result is a v1 ApplicationKit."""
    return str(raw.get("schema_version", "")) == APPLICATION_KIT_V1


def is_application_kit_v2(raw: dict[str, Any]) -> bool:
    """True when a persisted result is a v2 ApplicationKit."""
    return str(raw.get("schema_version", "")) == APPLICATION_KIT_V2


def is_application_kit_v3(raw: dict[str, Any]) -> bool:
    """True when a persisted result is a v3 ApplicationKit."""
    return str(raw.get("schema_version", "")) == APPLICATION_KIT_V3


def is_application_kit_v4(raw: dict[str, Any]) -> bool:
    """True when a persisted result is a v4 ApplicationKit."""
    return str(raw.get("schema_version", "")) == APPLICATION_KIT_V4


def is_application_kit_v5(raw: dict[str, Any]) -> bool:
    """True when a persisted result is a v5 ApplicationKit (current)."""
    return str(raw.get("schema_version", "")) == SCHEMA_VERSION


def _looks_like_phase1_result(raw: dict[str, Any]) -> bool:
    """A Phase 1 ``KitResult`` has no schema_version but these known fields."""
    if "schema_version" in raw:
        return False
    phase1_markers = {"resume_text", "cover_letter_text", "answers_text", "validation_errors"}
    return bool(phase1_markers & set(raw.keys()))


def adapt_legacy_result(raw: dict[str, Any]) -> dict[str, Any]:
    """Map a Phase 1 ``KitResult`` payload onto the canonical response shape.

    The old record predates typed artifacts and claim traces, so the adapted
    view carries the legacy text/latex and validation errors but an empty claim
    trace, under the explicit ``phase-1/legacy`` schema marker. This lets the API
    serve historical completed kits without crashing and without pretending the
    old record had Phase 2A truth-grounding metadata it never had.
    """
    errors = [str(item) for item in raw.get("validation_errors") or []]
    fatal = [str(item) for item in raw.get("fatal_validation_errors") or []]
    warnings = [error for error in errors if error not in set(fatal)]

    def _artifact(text_key: str, latex_key: str, status: str) -> dict[str, Any] | None:
        text = str(raw.get(text_key, "") or "")
        latex = str(raw.get(latex_key, "") or "")
        if not text and not latex:
            return None
        return {
            "text": text,
            "latex": latex,
            "validation": {
                "status": status,
                "fatal": bool(fatal),
                "errors": fatal,
                "warnings": warnings,
                "repaired_claims": 0,
                "rejected_claims": 0,
            },
            "claims": [],
        }

    resume = _artifact("resume_text", "resume_latex", ArtifactStatus.GENERATED.value)
    if resume is not None:
        probability = raw.get("interview_probability")
        resume["interview_probability"] = int(probability) if probability is not None else None
    cover = _artifact("cover_letter_text", "cover_letter_latex", ArtifactStatus.GENERATED.value)

    answers_text = str(raw.get("answers_text", "") or "")
    answers = None
    if answers_text:
        answers = {
            "items": [],
            "text": answers_text,
            "validation": {
                "status": ArtifactStatus.GENERATED.value,
                "fatal": bool(fatal),
                "errors": fatal,
                "warnings": warnings,
                "repaired_claims": 0,
                "rejected_claims": 0,
            },
            "claims": [],
            "placeholders": [],
        }

    return {
        "schema_version": LEGACY_SCHEMA_VERSION,
        "engine_version": "",
        "orchestration_version": "",
        "requested_mode": "",
        "resolved_mode": "",
        "generation": {
            "generation_mode": "unknown",
            "llm_available": bool((raw.get("engine_metadata") or {}).get("llm_available", False)),
            "provider": "",
            "model": "",
            "provider_calls": 0,
            "fallback_used": False,
        },
        "validation": {
            "passed": not fatal,
            "fatal": bool(fatal),
            "error_count": len(errors),
            "warning_count": len(warnings),
            "errors": errors,
            "warnings": warnings,
        },
        "resume": resume,
        "cover_letter": cover,
        "answers": answers,
        "job_fit": None,
        "interview_prep": None,
        "linkedin_outreach": None,
        "warnings": ["Served from a legacy Phase 1 result record (pre-ApplicationKit)."],
    }


def normalize_persisted_result(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return a canonical response dict for any persisted kit result.

    Dispatches on the stored schema: a v1 ApplicationKit is returned as-is, a
    Phase 1 record is adapted, and anything else is surfaced under the explicit
    ``unknown`` marker (never silently reinterpreted).
    """
    if raw is None:
        return None
    if is_application_kit_v5(raw):
        return raw
    if is_application_kit_v4(raw):
        # A stored v4 kit is read as-is: it never had a match report or change
        # ledgers, and it is NOT rewritten into v5 (its schema_version stays v4).
        # Missing v5 fields default safely (match_report -> None, ledgers -> []).
        normalized = dict(raw)
        normalized.setdefault("match_report", None)
        normalized.setdefault("stage_timings", {"stages_ms": {}})
        normalized.setdefault("revision", 0)
        return normalized
    if is_application_kit_v3(raw):
        normalized = dict(raw)
        normalized.setdefault("linkedin_outreach", None)
        return normalized
    if is_application_kit_v2(raw):
        normalized = dict(raw)
        normalized.setdefault("interview_prep", None)
        normalized.setdefault("linkedin_outreach", None)
        return normalized
    if is_application_kit_v1(raw):
        normalized = dict(raw)
        normalized.setdefault("job_fit", None)
        normalized.setdefault("interview_prep", None)
        normalized.setdefault("linkedin_outreach", None)
        return normalized
    if _looks_like_phase1_result(raw):
        return adapt_legacy_result(raw)
    return {
        "schema_version": UNKNOWN_SCHEMA_VERSION,
        "engine_version": "",
        "orchestration_version": "",
        "requested_mode": "",
        "resolved_mode": "",
        "generation": {
            "generation_mode": "unknown",
            "llm_available": False,
            "provider": "",
            "model": "",
            "provider_calls": 0,
            "fallback_used": False,
        },
        "validation": {
            "passed": False,
            "fatal": False,
            "error_count": 0,
            "warning_count": 1,
            "errors": [],
            "warnings": ["Unrecognized result schema; not interpreted."],
        },
        "resume": None,
        "cover_letter": None,
        "answers": None,
        "job_fit": None,
        "interview_prep": None,
        "linkedin_outreach": None,
        "warnings": ["Unrecognized result schema; not interpreted."],
    }
