from __future__ import annotations

from typing import Any

from ats_engine.kit.contract import (
    SCHEMA_VERSION,
    AnswerArtifact,
    AnswerItem,
    ApplicationKit,
    ArtifactKind,
    ArtifactStatus,
    ArtifactValidation,
    ClaimRecord,
    ClaimStatus,
    ClaimType,
    CoverLetterArtifact,
    EvidenceRef,
    GenerationMetadata,
    ResumeArtifact,
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
        "warnings": list(kit.warnings),
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
    }


def _cover_letter_to_dict(cover: CoverLetterArtifact) -> dict[str, Any]:
    return {
        "text": cover.text,
        "latex": cover.latex,
        "validation": _artifact_validation_to_dict(cover.validation),
        "claims": [_claim_to_dict(claim) for claim in cover.claims],
    }


def _answers_to_dict(answers: AnswerArtifact) -> dict[str, Any]:
    return {
        "items": [{"question": item.question, "answer": item.answer} for item in answers.items],
        "text": answers.text,
        "validation": _artifact_validation_to_dict(answers.validation),
        "claims": [_claim_to_dict(claim) for claim in answers.claims],
        "placeholders": list(answers.placeholders),
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
        warnings=[str(item) for item in data.get("warnings") or []],
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
    )


def _cover_letter_from_dict(raw: dict[str, Any] | None) -> CoverLetterArtifact | None:
    if raw is None:
        return None
    return CoverLetterArtifact(
        text=str(raw.get("text", "")),
        latex=str(raw.get("latex", "")),
        validation=_artifact_validation_from_dict(raw.get("validation") or {}),
        claims=[_claim_from_dict(claim) for claim in raw.get("claims") or []],
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
    if is_application_kit_v1(raw):
        return raw
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
        "warnings": ["Unrecognized result schema; not interpreted."],
    }
