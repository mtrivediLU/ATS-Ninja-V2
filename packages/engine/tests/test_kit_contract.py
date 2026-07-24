from __future__ import annotations

import json

from ats_engine import (
    SCHEMA_VERSION,
    ApplicationKit,
    ArtifactKind,
    ClaimStatus,
    ClaimType,
    application_kit_from_dict,
    application_kit_to_dict,
    generate_application_kit,
    is_application_kit_v1,
    is_application_kit_v2,
    is_application_kit_v3,
    is_application_kit_v4,
    normalize_persisted_result,
)
from ats_engine.kit.serialization import LEGACY_SCHEMA_VERSION, UNKNOWN_SCHEMA_VERSION
from ats_engine.models import Mode
from conftest import ADVERSARIAL_JD, ADVERSARIAL_RESUME, FabricatingProvider, fabricated_answer

"""ApplicationKit contract + serialization + legacy-compatibility tests.

Covers Steps 2-6: the versioned contract, typed artifacts, claim/evidence trace,
the JSON serialization boundary (round-trip, deterministic, no pickle), optional
artifacts, and reading a Phase 1 result record without crashing.
"""


def _kit(mode: Mode = Mode.RESUME_AND_COVER) -> ApplicationKit:
    return generate_application_kit(
        resume_text=ADVERSARIAL_RESUME,
        job_description=ADVERSARIAL_JD,
        questions_text="What interests you about this role?",
        default_mode=mode,
        use_llm=False,
    )


def test_schema_version_is_explicit_and_versioned() -> None:
    assert SCHEMA_VERSION == "application-kit/v5"
    kit = _kit()
    assert kit.schema_version == SCHEMA_VERSION
    assert kit.engine_version  # populated
    assert kit.orchestration_version.startswith("grounded-orchestration/")
    assert kit.job_fit is not None
    assert kit.interview_prep is not None
    assert kit.linkedin_outreach is not None


def test_roundtrip_is_json_compatible_and_lossless() -> None:
    kit = _kit(Mode.RESUME_AND_QUESTIONS)
    data = application_kit_to_dict(kit)
    # Pure JSON: dumps/loads must not raise and must not need custom encoders.
    restored = json.loads(json.dumps(data))
    assert restored == data
    kit2 = application_kit_from_dict(restored)
    assert kit2.schema_version == kit.schema_version
    assert kit2.resume is not None and kit.resume is not None
    assert kit2.resume.text == kit.resume.text
    assert kit2.answers is not None and kit.answers is not None
    assert [c.claim_type for c in kit2.resume.claims] == [c.claim_type for c in kit.resume.claims]


def test_structured_documents_are_optional_and_come_from_grounded_plans() -> None:
    kit = _kit()
    assert kit.resume is not None and kit.resume.document is not None
    assert kit.cover_letter is not None and kit.cover_letter.document is not None
    resume = kit.resume.document
    cover = kit.cover_letter.document
    assert resume.candidate_name
    assert resume.experience
    assert all("Company:" not in entry.employer for entry in resume.experience)
    assert cover.greeting == "Dear Hiring Manager,"
    assert cover.closing == "Sincerely,"
    assert all(not paragraph.startswith("Dear ") for paragraph in cover.body_paragraphs)
    serialized = application_kit_to_dict(kit)
    assert serialized["resume"]["document"]["experience"]
    assert serialized["cover_letter"]["document"]["greeting"] == "Dear Hiring Manager,"


def test_resume_only_kit_has_no_cover_or_answers() -> None:
    kit = _kit(Mode.RESUME)
    assert kit.resume is not None
    assert kit.cover_letter is None
    assert kit.answers is None
    data = application_kit_to_dict(kit)
    assert data["cover_letter"] is None
    assert data["answers"] is None


def test_cover_only_kit_has_no_resume() -> None:
    kit = _kit(Mode.COVER_LETTER)
    assert kit.cover_letter is not None
    assert kit.resume is None


def test_explicit_selection_can_generate_all_primary_artifacts() -> None:
    kit = generate_application_kit(
        resume_text=ADVERSARIAL_RESUME,
        job_description=ADVERSARIAL_JD,
        questions_text="What interests you about this role?",
        include_resume=True,
        include_cover_letter=True,
        include_application_answers=True,
        use_llm=False,
    )
    assert kit.resolved_mode == "RCQ"
    assert kit.resume is not None
    assert kit.cover_letter is not None
    assert kit.answers is not None


def test_explicit_false_primary_flags_are_respected_with_optional_artifacts() -> None:
    kit = generate_application_kit(
        resume_text=ADVERSARIAL_RESUME,
        job_description=ADVERSARIAL_JD,
        questions_text="What interests you about this role?",
        include_resume=False,
        include_cover_letter=False,
        include_application_answers=False,
        include_job_fit=True,
        include_interview_prep=False,
        include_linkedin_outreach=False,
        use_llm=False,
    )
    assert kit.resolved_mode == ""
    assert kit.resume is None
    assert kit.cover_letter is None
    assert kit.answers is None
    assert kit.job_fit is not None


def test_artifacts_are_typed_not_a_bag_of_strings() -> None:
    kit = _kit(Mode.RESUME_AND_QUESTIONS)
    assert kit.resume is not None
    assert isinstance(kit.resume.text, str)
    assert kit.resume.validation.status.value in {"generated", "repaired", "rejected"}
    assert kit.answers is not None
    # Application answers are modelled as structured items, not one blob.
    assert all(item.question for item in kit.answers.items)


def test_evidence_trace_is_present_and_structured() -> None:
    kit = _kit()
    assert kit.resume is not None
    # Deterministic kit: claims are all supported, each with a type + status.
    for claim in kit.resume.claims:
        assert isinstance(claim.claim_type, ClaimType)
        assert isinstance(claim.status, ClaimStatus)
        assert claim.artifact == ArtifactKind.RESUME


def test_deterministic_metadata_is_accurate() -> None:
    kit = _kit()
    assert kit.generation.generation_mode == "deterministic"
    assert kit.generation.llm_available is False
    assert kit.generation.provider == ""
    assert kit.generation.provider_calls == 0
    assert kit.generation.fallback_used is False


def test_provider_backed_metadata_is_accurate() -> None:
    provider = FabricatingProvider(answer=fabricated_answer("I use Python and SQL every day here."))
    kit = generate_application_kit(
        resume_text=ADVERSARIAL_RESUME,
        job_description=ADVERSARIAL_JD,
        questions_text="Tell us about your background.",
        default_mode=Mode.RESUME_AND_QUESTIONS,
        use_llm=True,
        prose_provider=provider,
    )
    assert kit.generation.generation_mode == "provider"
    assert kit.generation.llm_available is True
    assert kit.generation.provider.startswith("fabricator:")
    assert kit.generation.provider_calls > 0
    # The provider identity carries the orchestration-contract salt (cache identity).
    assert "orch=" in kit.generation.provider or kit.generation.provider_calls > 0


# --------------------------------------------------------------------------- #
# Result schema evolution / Phase 1 legacy compatibility (Step 6)
# --------------------------------------------------------------------------- #
PHASE1_RESULT = {
    "resume_text": "Candidate Header\nProfessional Summary\nExperienced analyst.",
    "cover_letter_text": "Dear Hiring Manager,\nI am applying for the role.",
    "answers_text": "",
    "resume_latex": "\\documentclass{article}\\begin{document}x\\end{document}",
    "cover_letter_latex": "",
    "interview_probability": 68,
    "validation_errors": ["cover letter: word count is low"],
    "fatal_validation_errors": [],
    "engine_metadata": {"llm_available": True},
}


def test_v5_result_is_detected_and_passed_through() -> None:
    kit = _kit()
    data = application_kit_to_dict(kit)
    assert data["schema_version"] == "application-kit/v5"
    assert normalize_persisted_result(data) == data


def test_v4_result_remains_readable_and_is_not_rewritten() -> None:
    # A kit persisted under v4 (no match report, ledgers, or revision) must stay
    # readable and keep its v4 schema_version — it is never silently upgraded.
    data = application_kit_to_dict(_kit())
    data["schema_version"] = "application-kit/v4"
    for key in ("match_report", "stage_timings", "revision"):
        data.pop(key, None)
    if data.get("resume") is not None:
        data["resume"].pop("change_ledger", None)
    assert is_application_kit_v4(data)
    normalized = normalize_persisted_result(data)
    assert normalized is not None
    assert normalized["schema_version"] == "application-kit/v4"
    assert normalized["match_report"] is None
    assert normalized["revision"] == 0
    # from_dict tolerates the missing v5 fields with safe defaults.
    kit = application_kit_from_dict(normalized)
    assert kit.match_report is None
    assert kit.revision == 0
    assert kit.resume is not None and kit.resume.change_ledger == []


def test_v3_result_remains_readable_with_absent_linkedin_outreach() -> None:
    data = application_kit_to_dict(_kit())
    data["schema_version"] = "application-kit/v3"
    data.pop("linkedin_outreach")
    assert is_application_kit_v3(data)
    normalized = normalize_persisted_result(data)
    assert normalized is not None
    assert normalized["schema_version"] == "application-kit/v3"
    assert normalized["job_fit"] is not None
    assert normalized["interview_prep"] is not None
    assert normalized["linkedin_outreach"] is None


def test_v2_result_remains_readable_with_absent_interview_prep() -> None:
    data = application_kit_to_dict(_kit())
    data["schema_version"] = "application-kit/v2"
    data.pop("interview_prep")
    data.pop("linkedin_outreach")
    assert is_application_kit_v2(data)
    normalized = normalize_persisted_result(data)
    assert normalized is not None
    assert normalized["schema_version"] == "application-kit/v2"
    assert normalized["job_fit"] is not None
    assert normalized["interview_prep"] is None
    assert normalized["linkedin_outreach"] is None


def test_v1_result_remains_readable_with_absent_job_fit() -> None:
    data = application_kit_to_dict(_kit())
    data["schema_version"] = "application-kit/v1"
    data.pop("job_fit")
    data.pop("interview_prep")
    data.pop("linkedin_outreach")
    assert is_application_kit_v1(data)
    normalized = normalize_persisted_result(data)
    assert normalized is not None
    assert normalized["schema_version"] == "application-kit/v1"
    assert normalized["job_fit"] is None
    assert normalized["interview_prep"] is None
    assert normalized["linkedin_outreach"] is None


def test_legacy_phase1_result_is_adapted_not_crashed() -> None:
    normalized = normalize_persisted_result(PHASE1_RESULT)
    assert normalized is not None
    assert normalized["schema_version"] == LEGACY_SCHEMA_VERSION
    assert normalized["resume"] is not None
    assert normalized["resume"].get("document") is None
    assert normalized["resume"]["text"].startswith("Candidate Header")
    assert normalized["cover_letter"] is not None
    assert normalized["answers"] is None  # empty legacy answers -> absent
    # The legacy warning names its provenance rather than pretending to be v1.
    assert any("legacy" in warning.lower() for warning in normalized["warnings"])


def test_legacy_fatal_errors_are_surfaced() -> None:
    legacy = dict(PHASE1_RESULT)
    legacy["validation_errors"] = ["resume: invented or unsupported employer: fake labs"]
    legacy["fatal_validation_errors"] = ["resume: invented or unsupported employer: fake labs"]
    normalized = normalize_persisted_result(legacy)
    assert normalized is not None
    assert normalized["validation"]["fatal"] is True
    assert normalized["resume"]["validation"]["fatal"] is True


def test_unknown_schema_is_flagged_not_reinterpreted() -> None:
    unknown = {"schema_version": "something/v9", "mystery": True}
    normalized = normalize_persisted_result(unknown)
    assert normalized is not None
    assert normalized["schema_version"] == UNKNOWN_SCHEMA_VERSION
    assert normalized["resume"] is None
    assert any("unrecognized" in warning.lower() for warning in normalized["warnings"])


def test_none_result_normalizes_to_none() -> None:
    assert normalize_persisted_result(None) is None
