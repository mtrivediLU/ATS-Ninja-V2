from __future__ import annotations

from ats_engine.evidence.matrix import build_evidence_matrix
from ats_engine.kit.change_actions import ChangeAction, apply_change_actions
from ats_engine.kit.change_ledger import build_resume_change_ledger
from ats_engine.kit.contract import (
    ArtifactKind,
    ChangeOperation,
    ChangeType,
    ClaimRecord,
    ClaimStatus,
    ClaimType,
    ResumeDocument,
    ResumeExperienceEntry,
)
from ats_engine.kit.orchestrator import generate_application_kit
from ats_engine.models import PlanDecision
from ats_engine.parsing.job_description import parse_jd
from ats_engine.parsing.resume import build_profile
from ats_engine.scoring.match_report import build_weighted_keywords
from conftest import SYNTHETIC_JD, SYNTHETIC_RESUME


def _ledger_context():
    profile = build_profile(SYNTHETIC_RESUME)
    jd_profile = parse_jd(SYNTHETIC_JD)
    evidence = build_evidence_matrix(jd_profile, profile)
    keywords = build_weighted_keywords(evidence, jd_profile)
    tiers = {item.keyword.casefold().strip(): item.evidence_tier for item in evidence}
    return profile, keywords, tiers


def test_plan_decisions_map_once_and_have_stable_ids() -> None:
    profile, keywords, tiers = _ledger_context()
    decisions = [
        PlanDecision(kind="summary", location_id="resume::summary", original_text="", tailored_text="A summary."),
        PlanDecision(
            kind="bullet",
            location_id="resume::exp0::bullet0",
            original_text="Built pipelines",
            tailored_text="Built Python data pipelines",
            operation="rewritten",
        ),
    ]
    document = ResumeDocument(experience=[ResumeExperienceEntry(bullets=["Built Python data pipelines"])])
    records_a = build_resume_change_ledger(
        decisions=decisions, document=document, claims=[], keywords=keywords, profile=profile, tier_by_keyword=tiers
    )
    records_b = build_resume_change_ledger(
        decisions=decisions, document=document, claims=[], keywords=keywords, profile=profile, tier_by_keyword=tiers
    )
    ids_a = [r.id for r in records_a]
    assert ids_a == [r.id for r in records_b], "ids must be stable across identical runs"
    assert len(ids_a) == len(set(ids_a)), "each decision maps to exactly one record"
    bullet = next(r for r in records_a if r.change_type is ChangeType.BULLET)
    assert bullet.original_text == "Built pipelines"
    assert bullet.reversible is True


def test_counterfactual_impact_is_zero_when_keyword_already_present() -> None:
    profile, keywords, tiers = _ledger_context()
    # A rewrite that surfaces "sql" where "sql" is already present elsewhere in
    # the full delivered resume must have zero whole-document ATS impact.
    full_text = "Technical Skills\nSQL, Python\nExperience\n- Built SQL reports"
    decisions = [
        PlanDecision(
            kind="bullet",
            location_id="resume::exp0::bullet0",
            original_text="Built reports",
            tailored_text="Built SQL reports",
            operation="rewritten",
        )
    ]
    document = ResumeDocument(experience=[ResumeExperienceEntry(bullets=["Built SQL reports"])])
    records = build_resume_change_ledger(
        decisions=decisions,
        document=document,
        claims=[],
        keywords=keywords,
        profile=profile,
        tier_by_keyword=tiers,
        full_text=full_text,
    )
    bullet = next(r for r in records if r.change_type is ChangeType.BULLET)
    assert bullet.ats_impact_delta == 0.0
    assert "No estimated keyword-match change" in bullet.ats_impact


def test_counterfactual_impact_of_grounding_removal_is_non_positive() -> None:
    profile, keywords, tiers = _ledger_context()
    claim = ClaimRecord(
        id="resume-summary-1",
        artifact=ArtifactKind.RESUME,
        claim_type=ClaimType.EMPLOYER,
        text="worked at Google",
        status=ClaimStatus.REPAIRED,
        disposition="repaired",
        reason="employer absent from candidate evidence",
    )
    records = build_resume_change_ledger(
        decisions=[],
        document=None,
        claims=[claim],
        keywords=keywords,
        profile=profile,
        tier_by_keyword=tiers,
        full_text="Experience\n- Built dashboards",
    )
    grounding = next(r for r in records if r.change_type is ChangeType.GROUNDING_REMOVAL)
    # Removing a fabrication never raises the real keyword match.
    assert grounding.ats_impact_delta <= 0.0


def test_bullet_original_text_is_the_raw_candidate_wording() -> None:
    # A raw candidate bullet with a banned style verb keeps its raw wording as the
    # ledger's original_text (softening happens later, but reject must restore the
    # candidate's own words).
    profile, keywords, tiers = _ledger_context()
    decisions = [
        PlanDecision(
            kind="bullet",
            location_id="resume::exp0::bullet0",
            original_text="Leveraged Python to build pipelines",
            tailored_text="Built Python data pipelines",
            operation="rewritten",
        )
    ]
    document = ResumeDocument(experience=[ResumeExperienceEntry(bullets=["Built Python data pipelines"])])
    records = build_resume_change_ledger(
        decisions=decisions, document=document, claims=[], keywords=keywords, profile=profile, tier_by_keyword=tiers
    )
    bullet = next(r for r in records if r.change_type is ChangeType.BULLET)
    assert bullet.original_text == "Leveraged Python to build pipelines"


def test_grounding_removal_reason_is_type_specific_not_generic() -> None:
    profile, keywords, tiers = _ledger_context()
    claim = ClaimRecord(
        id="c1",
        artifact=ArtifactKind.RESUME,
        claim_type=ClaimType.SKILL,
        text="Rust",
        status=ClaimStatus.REPAIRED,
        disposition="repaired",
        reason="claimed skill absent from candidate evidence",
    )
    records = build_resume_change_ledger(
        decisions=[], document=None, claims=[claim], keywords=keywords, profile=profile, tier_by_keyword=tiers
    )
    grounding = next(r for r in records if r.change_type is ChangeType.GROUNDING_REMOVAL)
    assert "skill" in grounding.reason.lower()
    assert "permanent" in grounding.reason.lower()


def test_grounding_removal_is_irreversible_and_linked() -> None:
    profile, keywords, tiers = _ledger_context()
    claim = ClaimRecord(
        id="resume-summary-1",
        artifact=ArtifactKind.RESUME,
        claim_type=ClaimType.EMPLOYER,
        text="Google",
        status=ClaimStatus.REPAIRED,
        disposition="repaired: removed unsupported claim",
        reason="employer absent from candidate evidence",
    )
    records = build_resume_change_ledger(
        decisions=[], document=None, claims=[claim], keywords=keywords, profile=profile, tier_by_keyword=tiers
    )
    grounding = [r for r in records if r.change_type is ChangeType.GROUNDING_REMOVAL]
    assert len(grounding) == 1
    assert grounding[0].reversible is False
    assert grounding[0].operation is ChangeOperation.REMOVED
    assert grounding[0].linked_claim_ids == ["resume-summary-1"]


def test_reject_grounding_removal_is_refused() -> None:
    kit = generate_application_kit(
        resume_text=SYNTHETIC_RESUME, job_description=SYNTHETIC_JD, use_llm=False, include_resume=True
    )
    # Inject a synthetic grounding removal record so a completed kit has one.
    from ats_engine.kit.contract import ChangeRecord

    assert kit.resume is not None
    kit.resume.change_ledger.append(
        ChangeRecord(
            id="grounding::x",
            artifact=ArtifactKind.RESUME,
            change_type=ChangeType.GROUNDING_REMOVAL,
            operation=ChangeOperation.REMOVED,
            original_text="Google",
            tailored_text="",
            reason="removed unsupported employer",
            reversible=False,
        )
    )
    result = apply_change_actions(
        kit=kit,
        resume_text=SYNTHETIC_RESUME,
        job_description=SYNTHETIC_JD,
        actions=[ChangeAction("grounding::x", "reject")],
        expected_revision=0,
    )
    assert not result.ok
    assert any("never be reverted" in e for e in result.errors)
    assert kit.revision == 0  # unchanged


def test_accept_is_idempotent_and_reject_restores_original() -> None:
    kit = generate_application_kit(
        resume_text=SYNTHETIC_RESUME, job_description=SYNTHETIC_JD, use_llm=False, include_resume=True
    )
    assert kit.resume is not None and kit.resume.document is not None
    summary_id = "resume::summary"
    # Accept twice -> idempotent (revision advances by one each successful batch,
    # but the delivered content is stable).
    r1 = apply_change_actions(
        kit=kit,
        resume_text=SYNTHETIC_RESUME,
        job_description=SYNTHETIC_JD,
        actions=[ChangeAction(summary_id, "accept")],
        expected_revision=0,
    )
    assert r1.ok and r1.kit.revision == 1
    summary_after_accept = r1.kit.resume.document.summary
    r2 = apply_change_actions(
        kit=r1.kit,
        resume_text=SYNTHETIC_RESUME,
        job_description=SYNTHETIC_JD,
        actions=[ChangeAction(summary_id, "accept")],
        expected_revision=1,
    )
    assert r2.kit.resume.document.summary == summary_after_accept, "accept must not drift the content"

    # Reject the summary -> removed; restore -> back.
    r3 = apply_change_actions(
        kit=r2.kit,
        resume_text=SYNTHETIC_RESUME,
        job_description=SYNTHETIC_JD,
        actions=[ChangeAction(summary_id, "reject")],
        expected_revision=2,
    )
    assert r3.kit.resume.document.summary != summary_after_accept
    r4 = apply_change_actions(
        kit=r3.kit,
        resume_text=SYNTHETIC_RESUME,
        job_description=SYNTHETIC_JD,
        actions=[ChangeAction(summary_id, "restore")],
        expected_revision=3,
    )
    assert r4.kit.resume.document.summary == summary_after_accept, "restore must return the tailored summary"


def test_no_cumulative_revision_drift() -> None:
    kit = generate_application_kit(
        resume_text=SYNTHETIC_RESUME, job_description=SYNTHETIC_JD, use_llm=False, include_resume=True
    )
    assert kit.resume is not None and kit.resume.document is not None
    summary_id = "resume::summary"
    # The first rebuild deterministically normalizes the summary composition; from
    # then on, repeated reject/restore must always return to that stable baseline
    # (no cumulative drift from mutating already-mutated text).
    first = apply_change_actions(
        kit=kit,
        resume_text=SYNTHETIC_RESUME,
        job_description=SYNTHETIC_JD,
        actions=[ChangeAction(summary_id, "restore")],
        expected_revision=0,
    )
    baseline = first.kit.resume.document.summary
    current = first.kit
    rev = 1
    for action in ["reject", "restore", "reject", "restore"]:
        result = apply_change_actions(
            kit=current,
            resume_text=SYNTHETIC_RESUME,
            job_description=SYNTHETIC_JD,
            actions=[ChangeAction(summary_id, action)],
            expected_revision=rev,
        )
        assert result.ok
        current = result.kit
        rev += 1
    assert current.resume.document.summary == baseline


def test_revision_conflict_returns_conflict() -> None:
    kit = generate_application_kit(
        resume_text=SYNTHETIC_RESUME, job_description=SYNTHETIC_JD, use_llm=False, include_resume=True
    )
    result = apply_change_actions(
        kit=kit,
        resume_text=SYNTHETIC_RESUME,
        job_description=SYNTHETIC_JD,
        actions=[ChangeAction("resume::summary", "accept")],
        expected_revision=99,
    )
    assert result.conflict
    assert not result.ok


def test_unknown_change_id_is_rejected() -> None:
    kit = generate_application_kit(
        resume_text=SYNTHETIC_RESUME, job_description=SYNTHETIC_JD, use_llm=False, include_resume=True
    )
    result = apply_change_actions(
        kit=kit,
        resume_text=SYNTHETIC_RESUME,
        job_description=SYNTHETIC_JD,
        actions=[ChangeAction("does::not::exist", "accept")],
        expected_revision=0,
    )
    assert not result.ok
    assert any("Unknown change id" in e for e in result.errors)
