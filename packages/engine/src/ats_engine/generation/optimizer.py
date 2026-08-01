"""Monotone deterministic optimization for Tailoring Engine v2."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass, field, replace

from ats_engine.generation.diagnostics import GateCode, ProposalRecord, ProposalStatus, RunDiagnostics
from ats_engine.generation.integration_planner import plan_placements_with_inventory
from ats_engine.generation.planning import rewrite_summary
from ats_engine.generation.resume import generate_resume_text
from ats_engine.kit.contract import ArtifactKind, DocumentState, OptimizationRejection, OptimizationTrace
from ats_engine.kit.grounding import build_evidence_context, ground_text
from ats_engine.models import (
    EvidenceLink,
    JDProfile,
    PlacementAction,
    PlanDecision,
    Profile,
    RequirementTerm,
    ResumePlan,
)
from ats_engine.parsing.vocab import normalize_term
from ats_engine.rachana.preservation import PreservationGuard, build_guard
from ats_engine.scoring.ats_v2 import AtsScoreV2, score_resume_v2
from ats_engine.validation.calibration import (
    CalibrationProfile,
    apply_calibration,
    calibrate_identity,
)
from ats_engine.validation.fidelity import (
    BulletPair,
    contains_fact,
    match_bullet_indices,
    match_experience_indices,
    validate_raw_source_findings,
)
from ats_engine.validation.findings import ValidationFinding, ValidationSeverity
from ats_engine.validation.stuffing import (
    STUFFING_DETECTOR_VERSION,
    validate_resume_stuffing_findings,
)

_BATCH_SIZE = 8
_MAX_ITERATIONS = 4


@dataclass(frozen=True, slots=True)
class ResumeGateContext:
    """One run's exact identity calibration, retained in memory only.

    The calibration profile contains source spans and fact identities, so it is
    deliberately excluded from the persisted ApplicationKit. Only codes that
    were actually calibrated are copied into the public optimization trace.
    """

    calibration: CalibrationProfile = field(default_factory=CalibrationProfile)
    identity_findings: tuple[ValidationFinding, ...] = ()


@dataclass(slots=True)
class _ProposalRecorder:
    """Mutable assembly helper for the immutable public diagnostics contract."""

    records: dict[str, ProposalRecord]
    ids_by_label: dict[str, str]

    @classmethod
    def from_inventory(
        cls,
        actions: list[PlacementAction],
        inventory: tuple[ProposalRecord, ...],
    ) -> _ProposalRecorder:
        if len(actions) != len(inventory):
            raise AssertionError("proposal inventory must have one record per planner action")
        labels = [_action_label(action) for action in actions]
        if len(set(labels)) != len(labels):
            raise AssertionError("planner actions must have stable unique labels")
        return cls(
            records={record.id: record for record in inventory},
            ids_by_label={label: record.id for label, record in zip(labels, inventory, strict=True)},
        )

    def reject(
        self,
        action: PlacementAction,
        *,
        code: GateCode,
        detail: str,
        score_before: float | None,
        score_after: float | None,
        iteration: int,
    ) -> None:
        self._set(
            action,
            ProposalStatus.REJECTED,
            code=code,
            detail=detail,
            score_before=score_before,
            score_after=score_after,
            iteration=iteration,
        )

    def accept(
        self,
        actions: Iterable[PlacementAction],
        *,
        score_before: float,
        score_after: float,
        iteration: int,
    ) -> None:
        for action in actions:
            self._set(
                action,
                ProposalStatus.ACCEPTED,
                code=None,
                detail="",
                score_before=score_before,
                score_after=score_after,
                iteration=iteration,
            )

    def rollback(self, *, detail: str) -> None:
        for record_id, record in self.records.items():
            if record.status is ProposalStatus.ACCEPTED:
                self.records[record_id] = replace(
                    record,
                    status=ProposalStatus.ROLLED_BACK,
                    gate_code=GateCode.FINAL_PLAN_SCORE_REGRESSION,
                    gate_detail=detail,
                )

    def is_recorded(self, action: PlacementAction) -> bool:
        return self.records[self.ids_by_label[_action_label(action)]].status is not ProposalStatus.NOT_EVALUATED

    def _set(
        self,
        action: PlacementAction,
        status: ProposalStatus,
        *,
        code: GateCode | None,
        detail: str,
        score_before: float | None,
        score_after: float | None,
        iteration: int,
    ) -> None:
        record_id = self.ids_by_label[_action_label(action)]
        record = self.records[record_id]
        # A bisection may have already rejected this exact proposal.  Preserve
        # that specific finding instead of overwriting it with the enclosing
        # batch's generic score result.
        if record.status is not ProposalStatus.NOT_EVALUATED:
            return
        delta = score_after - score_before if score_before is not None and score_after is not None else None
        self.records[record_id] = replace(
            record,
            status=status,
            gate_code=code,
            gate_detail=detail,
            score_before=score_before,
            score_after=score_after,
            score_delta=delta,
            iteration=iteration,
        )


def optimize(
    profile: Profile,
    jd_profile: JDProfile,
    requirements: list[RequirementTerm],
    links: list[EvidenceLink],
    base_plan: ResumePlan,
    *,
    gate_context: ResumeGateContext | None = None,
    accept_generated_prose: bool = False,
    delivery_first: bool = True,
) -> tuple[ResumePlan, OptimizationTrace]:
    """Apply safe quality and score actions without ever regressing ATS v2.

    Candidate-authored content is the delivery floor. Quality-only changes
    (headline, summary, individually validated provider rewrites) may be
    accepted at an equal score; keyword-placement actions must strictly improve
    the authoritative ATS v2 score. Failed placement batches are bisected so one
    unsafe proposal cannot discard unrelated safe work.
    """
    if not delivery_first:
        return _optimize_pr21_compat(
            profile,
            jd_profile,
            requirements,
            links,
            base_plan,
        )

    source = profile.raw_markdown
    # Measured once: every candidate below is checked against this same source,
    # and the optimizer evaluates many of them per run.
    guard = build_guard(source, requirements)
    source_plan = _source_content_plan(base_plan, profile, links)
    context = gate_context or (
        build_resume_gate_context(profile, source_plan) if delivery_first else ResumeGateContext()
    )
    original = score_resume_v2(source, requirements, links, source_resume_text=source)
    trace = OptimizationTrace(
        iterations=0,
        score_path=[original.score],
        unreachable_terms=[link.requirement.canonical for link in links if link.tier == "missing"],
        delivery_state=DocumentState.GENERATED_WITH_FALLBACK,
    )
    actions, inventory = plan_placements_with_inventory(links, profile, jd_profile)
    recorder = _ProposalRecorder.from_inventory(actions, inventory)
    source_findings = validate_resume_plan_findings(
        source_plan,
        profile,
        requirements,
        (),
        context,
    )
    trace.calibration_suppressed = _calibrated_codes(source_findings)
    source_blockers = _optimization_blockers(source_findings)
    if any(finding.severity is ValidationSeverity.FATAL for finding in source_blockers):
        trace.delivery_state = DocumentState.NEEDS_INPUT_REVIEW
        trace.fallback_reason = "The source projection could not preserve every protected resume fact."
        trace.rejected_actions.append(
            _rejection(
                action="source_content_plan",
                reason=_finding_reason(source_blockers),
                code=GateCode.SOURCE_PROJECTION_FAILURE,
            )
        )
        _finalize_diagnostics(trace, recorder, source_plan, source_plan, requirements)
        return source_plan, trace

    accepted: list[PlacementAction] = []
    current_plan = source_plan
    current_score = _score_plan(current_plan, source, requirements, links, accepted)
    source_score = current_score
    accepted_quality: list[str] = []

    if current_score.score + 0.001 < original.score:
        trace.delivery_state = DocumentState.NEEDS_INPUT_REVIEW
        trace.rejected_actions.append(
            _rejection(
                action="source_content_plan",
                reason="source projection scored below raw resume; input extraction requires review",
                code=GateCode.SOURCE_PROJECTION_FAILURE,
            )
        )
        trace.fallback_reason = (
            "The structured source projection did not preserve the original ATS score; "
            "review the extracted resume before delivery."
        )
        _finalize_diagnostics(trace, recorder, source_plan, source_plan, requirements)
        return source_plan, trace

    # Deterministic quality proposals preserve the source summary and use only
    # direct/certification-backed resolver links. They are accepted even when
    # ATS presence scoring is unchanged.
    headline_candidate = deepcopy(current_plan)
    headline_candidate.headline = base_plan.headline
    current_plan, current_score = _accept_quality_candidate(
        label="quality:headline",
        current=current_plan,
        candidate=headline_candidate,
        current_score=current_score,
        profile=profile,
        requirements=requirements,
        links=links,
        source=source,
        context=context,
        trace=trace,
        accepted_quality=accepted_quality,
    )

    summary_candidate = deepcopy(current_plan)
    summary_candidate.summary = rewrite_summary(
        summary_candidate.role_identity,
        profile,
        jd_profile,
        links,
    )
    current_plan, current_score = _accept_quality_candidate(
        label="quality:summary",
        current=current_plan,
        candidate=summary_candidate,
        current_score=current_score,
        profile=profile,
        requirements=requirements,
        links=links,
        source=source,
        context=context,
        trace=trace,
        accepted_quality=accepted_quality,
    )

    if accept_generated_prose:
        generated_summary = deepcopy(current_plan)
        generated_summary.summary = base_plan.summary
        current_plan, current_score = _accept_quality_candidate(
            label="ai:summary",
            current=current_plan,
            candidate=generated_summary,
            current_score=current_score,
            profile=profile,
            requirements=requirements,
            links=links,
            source=source,
            context=context,
            trace=trace,
            accepted_quality=accepted_quality,
        )
        current_plan, current_score = _accept_generated_bullets(
            current_plan=current_plan,
            base_plan=base_plan,
            current_score=current_score,
            profile=profile,
            requirements=requirements,
            links=links,
            source=source,
            context=context,
            trace=trace,
            accepted_quality=accepted_quality,
        )

    for offset in range(0, len(actions), _BATCH_SIZE):
        if trace.iterations >= _MAX_ITERATIONS:
            break
        batch = actions[offset : offset + _BATCH_SIZE]
        trace.iterations += 1
        candidate_plan, candidate_actions, rejected = _accept_safe_actions(
            current_plan,
            accepted,
            batch,
            profile,
            requirements,
            links,
            source,
            context,
            guard,
        )
        trace.rejected_actions.extend(rejected)
        candidate_score = _score_plan(candidate_plan, source, requirements, links, candidate_actions)
        if candidate_score.score > current_score.score:
            newly_accepted = candidate_actions[len(accepted) :]
            recorder.accept(
                newly_accepted,
                score_before=current_score.score,
                score_after=candidate_score.score,
                iteration=trace.iterations,
            )
            current_plan = candidate_plan
            accepted = candidate_actions
            current_score = candidate_score
            trace.score_path.append(current_score.score)
            trace.accepted_actions.extend(_action_label(action) for action in newly_accepted)
        else:
            rejected_by_label = {rejection.action: rejection for rejection in rejected}
            for action in batch:
                rejection = rejected_by_label.get(_action_label(action))
                if rejection is not None:
                    recorder.reject(
                        action,
                        code=rejection.code or GateCode.VALIDATION_FINDING,
                        detail=rejection.reason,
                        score_before=current_score.score,
                        score_after=candidate_score.score,
                        iteration=trace.iterations,
                    )
                    continue
                trace.rejected_actions.append(
                    _rejection(
                        action=_action_label(action),
                        reason="score did not strictly improve",
                        code=GateCode.SCORE_DID_NOT_STRICTLY_IMPROVE,
                    )
                )
                recorder.reject(
                    action,
                    code=GateCode.SCORE_DID_NOT_STRICTLY_IMPROVE,
                    detail="score did not strictly improve",
                    score_before=current_score.score,
                    score_after=candidate_score.score,
                    iteration=trace.iterations,
                )
        if len(trace.score_path) >= 2 and trace.score_path[-1] - trace.score_path[-2] < 0.5:
            break

    # The accepted-action expression above intentionally records exactly the
    # action list present in the final plan below, avoiding an untrusted
    # re-parse of rendered prose as a provenance source.
    current_plan.placement_actions = list(accepted)
    current_plan.plan_decisions = _v2_plan_decisions(
        base_plan.plan_decisions,
        current_plan,
        profile,
        accepted,
    )
    final_score = _score_plan(current_plan, source, requirements, links, accepted)
    if final_score.score + 0.001 < original.score:
        trace.rejected_actions.append(
            _rejection(
                action="final_plan",
                reason="would regress below original source score",
                code=GateCode.FINAL_PLAN_SCORE_REGRESSION,
            )
        )
        _record_source_rollback(
            trace,
            source_score,
            reason="No safe evidence-backed improvement was accepted; delivered the source projection.",
        )
        recorder.rollback(detail=trace.fallback_reason)
        _finalize_diagnostics(trace, recorder, source_plan, source_plan, requirements)
        return source_plan, trace

    # A delivered document must never state a JD-relevant term less often than
    # the candidate's own source did.  This is checked once more at the end
    # because the summary and bullet rewrites above take a different path into
    # the plan than the batched placements do.
    final_regressions = guard.regressions(generate_resume_text(current_plan))
    if final_regressions:
        trace.rejected_actions.append(
            _rejection(
                action="final_plan",
                reason=final_regressions[0].describe(),
                code=GateCode.PROTECTED_FACT_LOSS,
            )
        )
        _record_source_rollback(
            trace,
            source_score,
            reason="Tailoring would have weakened a job-relevant term; delivered the protected source projection.",
        )
        recorder.rollback(detail=trace.fallback_reason)
        _finalize_diagnostics(trace, recorder, source_plan, source_plan, requirements)
        return source_plan, trace

    final_findings = validate_resume_plan_findings(
        current_plan,
        profile,
        requirements,
        accepted,
        context,
    )
    final_blockers = _optimization_blockers(final_findings)
    if final_blockers:
        trace.rejected_actions.append(
            _rejection(
                action="final_plan",
                reason=_finding_reason(final_blockers),
                code=_gate_code_for_findings(final_blockers),
            )
        )
        _record_source_rollback(
            trace,
            source_score,
            reason="Tailoring proposals failed validation; delivered the protected source projection.",
        )
        trace.calibration_suppressed = _calibrated_codes(source_findings)
        recorder.rollback(detail=trace.fallback_reason)
        _finalize_diagnostics(trace, recorder, source_plan, source_plan, requirements)
        return source_plan, trace

    trace.accepted_actions = [*accepted_quality, *[_action_label(action) for action in accepted]]
    if not trace.score_path or trace.score_path[-1] != final_score.score:
        trace.score_path.append(final_score.score)
    trace.calibration_suppressed = _calibrated_codes(final_findings)
    if trace.accepted_actions or final_score.score > original.score + 0.001:
        trace.delivery_state = DocumentState.GENERATED
        trace.fallback_reason = ""
    else:
        trace.delivery_state = DocumentState.GENERATED_WITH_FALLBACK
        trace.fallback_reason = "No safe evidence-backed improvement was accepted; delivered the source projection."
    _finalize_diagnostics(trace, recorder, source_plan, current_plan, requirements)
    return current_plan, trace


def _optimize_pr21_compat(
    profile: Profile,
    jd_profile: JDProfile,
    requirements: list[RequirementTerm],
    links: list[EvidenceLink],
    base_plan: ResumePlan,
) -> tuple[ResumePlan, OptimizationTrace]:
    """Run the retained PR-21 score-only optimizer behind the kill switch.

    Detector correctness and truth-grounding fixes remain active, but this path
    deliberately skips identity calibration and the delivery-first quality
    stage. It exists for one release so ``ENGINE_DELIVERY_FIRST=0`` is a real
    behavioral rollback rather than a no-op diagnostic setting.
    """
    source = profile.raw_markdown
    guard = build_guard(source, requirements)
    source_plan = _source_content_plan(base_plan, profile, links)
    original = score_resume_v2(source, requirements, links, source_resume_text=source)
    trace = OptimizationTrace(
        iterations=0,
        score_path=[original.score],
        unreachable_terms=[link.requirement.canonical for link in links if link.tier == "missing"],
        delivery_state=DocumentState.GENERATED_WITH_FALLBACK,
        fallback_reason="PR-21 compatibility path delivered the source projection.",
    )
    actions, inventory = plan_placements_with_inventory(links, profile, jd_profile)
    recorder = _ProposalRecorder.from_inventory(actions, inventory)
    if not requirements or not links:
        _finalize_diagnostics(trace, recorder, source_plan, source_plan, requirements)
        return source_plan, trace

    accepted: list[PlacementAction] = []
    current_plan = source_plan
    current_score = _score_plan(current_plan, source, requirements, links, accepted)
    source_score = current_score
    if current_score.score + 0.001 < original.score:
        trace.rejected_actions.append(
            _rejection(
                action="source_content_plan",
                reason="source projection scored below raw resume; retained PR-21 source-content fallback",
                code=GateCode.SOURCE_PROJECTION_FAILURE,
            )
        )
        if current_score.score != original.score:
            trace.score_path.append(current_score.score)
        _finalize_diagnostics(trace, recorder, source_plan, source_plan, requirements)
        return source_plan, trace

    context = ResumeGateContext()
    for offset in range(0, len(actions), _BATCH_SIZE):
        if trace.iterations >= _MAX_ITERATIONS:
            break
        batch = actions[offset : offset + _BATCH_SIZE]
        trace.iterations += 1
        candidate_plan, candidate_actions, rejected = _accept_safe_actions(
            current_plan,
            accepted,
            batch,
            profile,
            requirements,
            links,
            source,
            context,
            guard,
        )
        trace.rejected_actions.extend(rejected)
        candidate_score = _score_plan(candidate_plan, source, requirements, links, candidate_actions)
        if candidate_score.score > current_score.score:
            recorder.accept(
                candidate_actions[len(accepted) :],
                score_before=current_score.score,
                score_after=candidate_score.score,
                iteration=trace.iterations,
            )
            current_plan = candidate_plan
            accepted = candidate_actions
            current_score = candidate_score
            trace.score_path.append(current_score.score)
        else:
            rejected_by_label = {rejection.action: rejection for rejection in rejected}
            for action in batch:
                rejection = rejected_by_label.get(_action_label(action))
                if rejection is not None:
                    recorder.reject(
                        action,
                        code=rejection.code or GateCode.VALIDATION_FINDING,
                        detail=rejection.reason,
                        score_before=current_score.score,
                        score_after=candidate_score.score,
                        iteration=trace.iterations,
                    )
                    continue
                trace.rejected_actions.append(
                    _rejection(
                        action=_action_label(action),
                        reason="score did not strictly improve",
                        code=GateCode.SCORE_DID_NOT_STRICTLY_IMPROVE,
                    )
                )
                recorder.reject(
                    action,
                    code=GateCode.SCORE_DID_NOT_STRICTLY_IMPROVE,
                    detail="score did not strictly improve",
                    score_before=current_score.score,
                    score_after=candidate_score.score,
                    iteration=trace.iterations,
                )
        if len(trace.score_path) >= 2 and trace.score_path[-1] - trace.score_path[-2] < 0.5:
            break

    current_plan.placement_actions = list(accepted)
    current_plan.plan_decisions = _v2_plan_decisions(
        base_plan.plan_decisions,
        current_plan,
        profile,
        accepted,
    )
    final_score = _score_plan(current_plan, source, requirements, links, accepted)
    if final_score.score + 0.001 < original.score:
        trace.rejected_actions.append(
            _rejection(
                action="final_plan",
                reason="would regress below original source score",
                code=GateCode.FINAL_PLAN_SCORE_REGRESSION,
            )
        )
        _record_source_rollback(
            trace,
            source_score,
            reason="PR-21 compatibility path rolled back to the source projection.",
        )
        recorder.rollback(detail=trace.fallback_reason)
        _finalize_diagnostics(trace, recorder, source_plan, source_plan, requirements)
        return source_plan, trace

    trace.accepted_actions = [_action_label(action) for action in accepted]
    if not trace.score_path or trace.score_path[-1] != final_score.score:
        trace.score_path.append(final_score.score)
    if accepted or final_score.score > original.score + 0.001:
        trace.delivery_state = DocumentState.GENERATED
        trace.fallback_reason = ""
    _finalize_diagnostics(trace, recorder, source_plan, current_plan, requirements)
    return current_plan, trace


def _record_source_rollback(
    trace: OptimizationTrace,
    source_score: AtsScoreV2,
    *,
    reason: str,
) -> None:
    """Make an optimizer rollback describe the content actually delivered."""
    trace.accepted_actions = []
    if not trace.score_path or trace.score_path[-1] != source_score.score:
        trace.score_path.append(source_score.score)
    trace.delivery_state = DocumentState.GENERATED_WITH_FALLBACK
    trace.fallback_reason = reason


def _source_content_plan(
    base_plan: ResumePlan,
    profile: Profile,
    links: list[EvidenceLink],
) -> ResumePlan:
    plan = deepcopy(base_plan)
    plan.experience = deepcopy(profile.experiences)
    plan.education = deepcopy(profile.education)
    plan.certifications = deepcopy(profile.certifications)
    # Do not retain the legacy fallback summary here: it can infer a career
    # duration from date ranges (for example "2+ years") that the candidate
    # never stated. A source summary wins; otherwise a verified role title is
    # the only safe deterministic seed before v2 placements are applied.
    plan.summary = _with_targeting(profile.source_summary or _source_role_summary(profile), plan.jd_profile)
    # The source projection is the honest floor, so it keeps the candidate's own
    # headline. Synthesizing one from `role_identity` -- which is the most
    # recent job title whenever nothing matches -- is what replaced
    # "Senior Software Engineer | Full-Stack, Data & AI Solutions" with
    # "Business Intelligence Developer" on a posting that says "AI" nine times,
    # making the "source-preserving" fallback score below the untouched source.
    plan.headline = profile.source_headline or plan.role_identity
    plan.placement_actions = []
    plan.remaining_sections = deepcopy(profile.remaining_sections)
    if profile.source_skill_groups:
        plan.skill_groups = deepcopy(profile.source_skill_groups)
    else:
        values = _dedupe_text([*profile.tier_a.values(), *profile.tier_b.values(), *profile.tier_c.values()])
        plan.skill_groups = [("Technical Skills", values)] if values else []
    plan.skill_groups = _annotate_tier_c_skills(plan.skill_groups, links)
    # The planner may contain model proposals that this source projection has
    # discarded. Rebuild the ledger from delivered content so a fallback never
    # claims that an absent rewrite or generated skill was accepted.
    plan.plan_decisions = _v2_plan_decisions([], plan, profile, [])
    return plan


def build_resume_gate_context(
    profile: Profile,
    source_plan: ResumePlan,
) -> ResumeGateContext:
    """Calibrate only exact self-inconsistencies on an identity projection.

    A fidelity finding is eligible only when the shared canonicalizer proves
    that its fact exists in both the immutable source and the rendered identity.
    That excludes genuine deletions. Anti-stuffing findings from an unchanged
    projection are also eligible because source-authored repetition cannot be
    repaired by deleting candidate evidence.
    """
    identity = deepcopy(source_plan)
    identity.contacts = deepcopy(profile.contact)
    identity.role_identity = profile.role_identities[0] if profile.role_identities else ""
    identity.experience = deepcopy(profile.experiences)
    identity.education = deepcopy(profile.education)
    identity.certifications = deepcopy(profile.certifications)
    identity.remaining_sections = deepcopy(profile.remaining_sections)
    identity.summary = profile.source_summary or _source_role_summary(profile)
    identity.headline = identity.role_identity
    identity.skill_groups = (
        deepcopy(profile.source_skill_groups)
        if profile.source_skill_groups
        else (
            [
                (
                    "Technical Skills",
                    _dedupe_text(
                        [
                            *profile.tier_a.values(),
                            *profile.tier_b.values(),
                            *profile.tier_c.values(),
                        ]
                    ),
                )
            ]
            if profile.tier_a or profile.tier_b or profile.tier_c
            else []
        )
    )
    identity.placement_actions = []
    identity.plan_decisions = []
    rendered = generate_resume_text(identity)
    fidelity = validate_raw_source_findings(
        profile.raw_markdown,
        rendered,
        profile=profile,
        candidate_experiences=identity.experience,
    )
    stuffing = validate_resume_stuffing_findings(
        summary=identity.summary,
        bullets=[bullet for experience in identity.experience for bullet in experience.bullets],
        skill_groups=identity.skill_groups,
        requirements=identity.requirements,
        source_skill_groups=profile.source_skill_groups,
        source_resume_text=profile.raw_markdown,
    )
    findings = (*fidelity, *stuffing)
    eligible = [
        finding
        for finding in findings
        if finding.detector_version == STUFFING_DETECTOR_VERSION
        or (contains_fact(profile.raw_markdown, finding.fact) and contains_fact(rendered, finding.fact))
    ]
    return ResumeGateContext(
        calibration=calibrate_identity(eligible),
        identity_findings=tuple(findings),
    )


def validate_resume_plan_findings(
    plan: ResumePlan,
    profile: Profile,
    requirements: list[RequirementTerm],
    actions: Iterable[PlacementAction],
    context: ResumeGateContext,
    *,
    rendered_text: str | None = None,
) -> tuple[ValidationFinding, ...]:
    """Run the shared calibrated fidelity and anti-stuffing gate for a plan."""
    action_list = list(actions)
    rendered = rendered_text if rendered_text is not None else generate_resume_text(plan)
    bullet_pairs: list[BulletPair] = []
    experience_matches = match_experience_indices(profile.experiences, plan.experience)
    for source_experience_index, source_experience in enumerate(profile.experiences):
        candidate_experience_index = experience_matches[source_experience_index]
        candidate_bullets = (
            plan.experience[candidate_experience_index].bullets if candidate_experience_index is not None else []
        )
        bullet_matches = match_bullet_indices(source_experience.bullets, candidate_bullets)
        for source_bullet_index, source_bullet in enumerate(source_experience.bullets):
            candidate_bullet_index = bullet_matches[source_bullet_index]
            bullet_pairs.append(
                BulletPair(
                    original=source_bullet,
                    candidate=(candidate_bullets[candidate_bullet_index] if candidate_bullet_index is not None else ""),
                    location=(f"experience:{source_experience_index}:bullet:{source_bullet_index}"),
                )
            )
    fidelity = validate_raw_source_findings(
        profile.raw_markdown,
        rendered,
        profile=profile,
        candidate_experiences=plan.experience,
        bullet_pairs=bullet_pairs,
        calibrations=context.calibration,
    )
    stuffing = apply_calibration(
        validate_resume_stuffing_findings(
            actions=action_list,
            summary=plan.summary,
            bullets=[bullet for experience in plan.experience for bullet in experience.bullets],
            skill_groups=plan.skill_groups,
            requirements=requirements,
            source_skill_groups=profile.source_skill_groups,
            source_resume_text=profile.raw_markdown,
        ),
        context.calibration,
    )
    return _dedupe_findings((*fidelity, *stuffing))


def _accept_quality_candidate(
    *,
    label: str,
    current: ResumePlan,
    candidate: ResumePlan,
    current_score: AtsScoreV2,
    profile: Profile,
    requirements: list[RequirementTerm],
    links: list[EvidenceLink],
    source: str,
    context: ResumeGateContext,
    trace: OptimizationTrace,
    accepted_quality: list[str],
) -> tuple[ResumePlan, AtsScoreV2]:
    """Accept one independently validated quality proposal at score parity."""
    if generate_resume_text(candidate) == generate_resume_text(current):
        return current, current_score
    if label.endswith(":summary"):
        outcome = ground_text(
            candidate.summary,
            artifact=ArtifactKind.RESUME,
            context=build_evidence_context(profile, candidate.jd_profile),
            id_prefix="optimizer-summary",
        )
        if outcome.fatal or outcome.repaired or outcome.rejected:
            trace.rejected_actions.append(
                _rejection(
                    action=label,
                    reason="truth gate rejected an unsupported candidate-specific summary claim",
                    code=GateCode.TRUTH_GATE_REJECTION,
                )
            )
            return current, current_score
    findings = validate_resume_plan_findings(candidate, profile, requirements, (), context)
    blockers = _optimization_blockers(findings)
    if blockers:
        trace.rejected_actions.append(
            _rejection(action=label, reason=_finding_reason(blockers), code=_gate_code_for_findings(blockers))
        )
        return current, current_score
    candidate_score = _score_plan(candidate, source, requirements, links, [])
    if candidate_score.score + 0.001 < current_score.score:
        trace.rejected_actions.append(
            _rejection(
                action=label,
                reason="quality proposal would reduce ATS v2 score",
                code=GateCode.QUALITY_SCORE_REGRESSION,
            )
        )
        return current, current_score
    accepted_quality.append(label)
    if candidate_score.score != current_score.score:
        trace.score_path.append(candidate_score.score)
    return candidate, candidate_score


def _accept_generated_bullets(
    *,
    current_plan: ResumePlan,
    base_plan: ResumePlan,
    current_score: AtsScoreV2,
    profile: Profile,
    requirements: list[RequirementTerm],
    links: list[EvidenceLink],
    source: str,
    context: ResumeGateContext,
    trace: OptimizationTrace,
    accepted_quality: list[str],
) -> tuple[ResumePlan, AtsScoreV2]:
    """Evaluate every provider bullet independently, falling back per item."""
    current = current_plan
    score = current_score
    for exp_index, source_experience in enumerate(profile.experiences):
        if exp_index >= len(base_plan.experience) or exp_index >= len(current.experience):
            continue
        for bullet_index, source_bullet in enumerate(source_experience.bullets):
            if bullet_index >= len(base_plan.experience[exp_index].bullets) or bullet_index >= len(
                current.experience[exp_index].bullets
            ):
                continue
            proposed = base_plan.experience[exp_index].bullets[bullet_index]
            if proposed.strip() == source_bullet.strip():
                continue
            candidate = deepcopy(current)
            candidate.experience[exp_index].bullets[bullet_index] = proposed
            label = f"ai:experience:{exp_index}:bullet:{bullet_index}"
            current, score = _accept_quality_candidate(
                label=label,
                current=current,
                candidate=candidate,
                current_score=score,
                profile=profile,
                requirements=requirements,
                links=links,
                source=source,
                context=context,
                trace=trace,
                accepted_quality=accepted_quality,
            )
    return current, score


def _accept_safe_actions(
    plan: ResumePlan,
    accepted: list[PlacementAction],
    pending: list[PlacementAction],
    profile: Profile,
    requirements: list[RequirementTerm],
    links: list[EvidenceLink],
    source: str,
    context: ResumeGateContext,
    guard: PreservationGuard | None = None,
) -> tuple[ResumePlan, list[PlacementAction], list[OptimizationRejection]]:
    """Bisect a failed batch down to individually safe actions.

    ``guard`` is optional purely so a caller can never *lose* term protection by
    forgetting the argument: omitting it measures the source here instead of
    disabling the check. The optimizer passes a prebuilt guard because it
    evaluates many candidates against one unchanging source.
    """

    if guard is None:
        guard = build_guard(source, requirements)
    candidate_actions = [*accepted, *pending]
    candidate = _apply_actions(plan, pending, profile)
    findings = validate_resume_plan_findings(
        candidate,
        profile,
        requirements,
        candidate_actions,
        context,
    )
    blockers = _optimization_blockers(findings)
    # Rendering the candidate is the expensive step here, and a batch that
    # already has a blocker is rejected regardless, so only pay for the term
    # check when the batch would otherwise be accepted.
    regressions = [] if blockers else guard.regressions(generate_resume_text(candidate))
    if not blockers and not regressions:
        return candidate, candidate_actions, []
    if len(pending) == 1:
        action = pending[0]
        reason = _finding_reason(blockers) if blockers else regressions[0].describe()
        return (
            plan,
            accepted,
            [
                _rejection(
                    action=_action_label(action),
                    reason=reason,
                    code=_gate_code_for_findings(blockers) if blockers else GateCode.PROTECTED_FACT_LOSS,
                )
            ],
        )
    midpoint = len(pending) // 2
    left_plan, left_actions, left_rejected = _accept_safe_actions(
        plan,
        accepted,
        pending[:midpoint],
        profile,
        requirements,
        links,
        source,
        context,
        guard,
    )
    right_plan, right_actions, right_rejected = _accept_safe_actions(
        left_plan,
        left_actions,
        pending[midpoint:],
        profile,
        requirements,
        links,
        source,
        context,
        guard,
    )
    return right_plan, right_actions, [*left_rejected, *right_rejected]


def _apply_actions(base: ResumePlan, actions: list[PlacementAction], profile: Profile) -> ResumePlan:
    plan = deepcopy(base)
    summary_links = [action.link for action in actions if action.target == "summary"]
    _apply_summary(plan, summary_links)
    _apply_skills(plan, [action for action in actions if action.target == "skills"], profile)
    _apply_headline(plan, [action for action in actions if action.target == "headline"])
    # Bullet actions are source-order annotations only. A direct source bullet
    # already carries the phrase; forcing a paraphrase creates fact-loss risk.
    plan.placement_actions = list(actions)
    return plan


def _apply_summary(plan: ResumePlan, links: list[EvidenceLink]) -> None:
    # A cert name can itself match a parent requirement (for example Power BI
    # in the PL-300 certificate). Four explicit actions plus that certification
    # reference stay within the five-term summary budget while still letting
    # the scorer surface the high-value certificate implications.
    links = links[:4]
    direct = _dedupe_text(
        [link.surface_to_use or link.requirement.surface for link in links if link.tier in {"A", "B", "variant"}]
    )[:5]
    certified = _dedupe_text(
        [link.surface_to_use or link.requirement.surface for link in links if link.tier == "cert"]
    )[:5]
    parts: list[str] = [plan.summary.strip()] if plan.summary.strip() else []
    if direct:
        missing = [term for term in direct if not contains_fact(plan.summary, term)]
        if missing:
            parts.append(f"Relevant work includes {_join(missing)}.")
    if certified:
        certificate = _certificate_reference(links)
        missing = [term for term in certified if not contains_fact(plan.summary, term)]
        if missing and not contains_fact(plan.summary, certificate):
            parts.append(f"{certificate} supports knowledge of {_join(missing)}.")
    plan.summary = _with_targeting(" ".join(parts), plan.jd_profile)


def _apply_skills(plan: ResumePlan, actions: list[PlacementAction], profile: Profile) -> None:
    # ``plan`` starts as the source-content projection, which may include a
    # conservative ``(Working Knowledge)`` annotation for a resolver-confirmed
    # Tier-C skill.  Start from that projection instead of resetting it to the
    # raw groups so later accepted actions never erase the qualification label.
    groups = deepcopy(plan.skill_groups) if plan.skill_groups else deepcopy(profile.source_skill_groups)
    if not groups:
        groups = [("Technical Skills", [])]
    append_count = 0
    for action in actions:
        if append_count >= 6:
            break
        link = action.link
        if link.tier not in {"A", "B", "C", "cert", "variant"}:
            continue
        surface = action.term
        existing = _find_equivalent_skill(groups, link)
        if existing is not None:
            group_index, item_index = existing
            prior_item = groups[group_index][1][item_index]
            groups[group_index][1][item_index] = (
                f"{surface} (Working Knowledge)"
                if link.tier == "C" and "working knowledge" in prior_item.casefold()
                else surface
            )
            continue
        target_index = _matching_skill_group(groups, link.requirement.category)
        groups[target_index][1].append(surface)
        append_count += 1
    plan.skill_groups = [(heading, _dedupe_text(items)) for heading, items in groups if items]


def _apply_headline(plan: ResumePlan, actions: list[PlacementAction]) -> None:
    existing = plan.headline.split("|", 1)
    prior_terms = (
        [item.strip() for item in re.split(r",| and ", existing[1]) if item.strip()] if len(existing) == 2 else []
    )
    terms = _dedupe_text([*prior_terms, *(action.term for action in actions)])[:3]
    plan.headline = f"{plan.role_identity} | {', '.join(terms)}" if terms else plan.role_identity


def _certificate_reference(links: list[EvidenceLink]) -> str:
    """Name the conservative source certificate without repeating tool names."""
    for link in links:
        if link.tier != "cert":
            continue
        code = re.search(r"\b[A-Z]{2,8}-\d{2,6}\b", link.resume_span)
        if code is not None:
            return f"Microsoft {code.group(0)} certification"
        if link.resume_span:
            return link.resume_span
    return "a listed certification"


def _source_role_summary(profile: Profile) -> str:
    return f"{profile.role_identities[0]}." if profile.role_identities else ""


def _with_targeting(summary: str, jd_profile: JDProfile) -> str:
    """Add the safe JD-owned target-role clause exactly once.

    A target role is job-description context, never candidate history.  It is
    therefore safe to retain even when every candidate-facing placement is
    rejected by the provenance/fidelity gates.  Keeping it in the source plan
    also preserves the established target-title quality signal for sparse or
    gap-heavy applications.
    """
    title = jd_profile.title.strip()
    if not title or title == "Target Role":
        return summary.strip()
    clean_title = title.replace("–", "-").replace("—", "-")
    clause = f"Targeting {clean_title} opportunities."
    normalized_summary = re.sub(r"\s+", " ", summary).casefold()
    if clause.casefold() in normalized_summary:
        return summary.strip()
    return " ".join(part for part in (summary.strip(), clause) if part)


def _v2_plan_decisions(
    prior: list[PlanDecision],
    plan: ResumePlan,
    profile: Profile,
    actions: list[PlacementAction],
) -> list[PlanDecision]:
    """Refresh reviewable decisions after source-preserving v2 optimization."""
    prior_by_location = {decision.location_id: decision for decision in prior}
    decisions: list[PlanDecision] = []
    source_summary = profile.source_summary
    if plan.summary.strip() != source_summary.strip():
        prior_summary = prior_by_location.get("resume::summary")
        summary_reason = (
            prior_summary.reason
            if prior_summary is not None
            else "Added only resolver-backed terms while preserving candidate-authored summary evidence."
        )
        decisions.append(
            PlanDecision(
                kind="summary",
                location_id="resume::summary",
                original_text=source_summary,
                tailored_text=plan.summary,
                operation="added" if not source_summary else "rewritten",
                reason=_reason_with_bridges(summary_reason, actions, target="summary"),
                matched_keywords=[action.term for action in actions if action.target == "summary"],
            )
        )

    if plan.headline.strip() != plan.role_identity.strip():
        decisions.append(
            PlanDecision(
                kind="headline",
                location_id="resume::headline",
                original_text=plan.role_identity,
                tailored_text=plan.headline,
                operation="rewritten",
                reason="Surfaced only direct or certification-backed terminology in the headline.",
                matched_keywords=[part.strip() for part in plan.headline.partition("|")[2].split(",") if part.strip()],
            )
        )

    for exp_index, source_experience in enumerate(profile.experiences):
        if exp_index >= len(plan.experience):
            continue
        for bullet_index, source_bullet in enumerate(source_experience.bullets):
            if bullet_index >= len(plan.experience[exp_index].bullets):
                continue
            tailored_bullet = plan.experience[exp_index].bullets[bullet_index]
            target = f"experience:{exp_index}:bullet:{bullet_index}"
            action_terms = [action.term for action in actions if action.target == target]
            if tailored_bullet.strip() == source_bullet.strip() and not action_terms:
                continue
            location_id = f"resume::exp{exp_index}::bullet{bullet_index}"
            prior_decision = prior_by_location.get(location_id)
            bullet_reason = (
                prior_decision.reason
                if prior_decision is not None
                else (
                    "Reworded the source bullet while retaining its protected facts and provenance."
                    if tailored_bullet.strip() != source_bullet.strip()
                    else "Retained the source bullet after verifying a resolver-backed placement."
                )
            )
            decisions.append(
                PlanDecision(
                    kind="bullet",
                    location_id=location_id,
                    original_text=source_bullet,
                    tailored_text=tailored_bullet,
                    operation="rewritten",
                    reason=_reason_with_bridges(bullet_reason, actions, target=target),
                    matched_keywords=(
                        list(prior_decision.matched_keywords) if prior_decision is not None else action_terms
                    ),
                )
            )

    if plan.skill_groups != profile.source_skill_groups:
        decisions.append(
            PlanDecision(
                kind="skill",
                location_id="resume::skills",
                original_text="\n".join(
                    f"{heading}: {', '.join(items)}" for heading, items in profile.source_skill_groups
                ),
                tailored_text="\n".join(f"{heading}: {', '.join(items)}" for heading, items in plan.skill_groups),
                operation="rewritten",
                reason=_reason_with_bridges(
                    "Grouped and surfaced only skills already supported by the resume evidence.",
                    actions,
                    target="skills",
                ),
                matched_keywords=[action.term for action in actions if action.target == "skills"],
            )
        )
    return decisions


def _reason_with_bridges(
    base: str,
    actions: list[PlacementAction],
    *,
    target: str,
) -> str:
    """Make every accepted curated bridge explicit in the reviewable ledger."""
    bridged = [action for action in actions if action.target == target and action.link.match_type == "bridged"]
    if not bridged:
        return base
    descriptions: list[str] = []
    for action in bridged:
        span_count = len(action.link.supporting_spans) or int(bool(action.link.resume_span))
        noun = "source span" if span_count == 1 else "source spans"
        descriptions.append(f"{action.term} ({span_count} candidate {noun})")
    return f"{base} Conservative evidence bridge: {_join(_dedupe_text(descriptions))}."


def _plan_bullet_location(target: str) -> tuple[int, int, str] | None:
    match = re.fullmatch(r"experience:(\d+):bullet:(\d+)", target)
    if match is None:
        return None
    exp_index, bullet_index = (int(value) for value in match.groups())
    return exp_index, bullet_index, f"resume::exp{exp_index}::bullet{bullet_index}"


def _find_equivalent_skill(groups: list[tuple[str, list[str]]], link: EvidenceLink) -> tuple[int, int] | None:
    accepted = {normalize_term(value) for value in (link.requirement.canonical, *link.requirement.aliases)}
    for group_index, (_heading, items) in enumerate(groups):
        for item_index, item in enumerate(items):
            source_item = re.sub(r"\s*\(working knowledge\)\s*$", "", item, flags=re.IGNORECASE)
            if normalize_term(source_item) in accepted:
                return group_index, item_index
    return None


def _annotate_tier_c_skills(
    groups: list[tuple[str, list[str]]],
    links: list[EvidenceLink],
) -> list[tuple[str, list[str]]]:
    """Label only resolver-confirmed listed-only skills without duplicating them.

    A Tier-C link means the term appears in the candidate's skills taxonomy but
    has no stronger experience or summary evidence.  Retaining it under its
    original heading is fact-preserving; adding the parenthetical makes the
    conservative classification visible without inventing a capability or
    placing the same requirement a second time in the skills section.
    """
    locations = {
        link.resume_location for link in links if link.tier == "C" and link.resume_location.startswith("skills:")
    }
    if not locations:
        return groups

    annotated: list[tuple[str, list[str]]] = []
    for group_index, (heading, items) in enumerate(groups):
        rendered_items: list[str] = []
        for item_index, item in enumerate(items):
            location = f"skills:{group_index}:{item_index}"
            if location in locations and "working knowledge" not in item.casefold():
                rendered_items.append(f"{item} (Working Knowledge)")
            else:
                rendered_items.append(item)
        annotated.append((heading, rendered_items))
    return annotated


def _matching_skill_group(groups: list[tuple[str, list[str]]], category: str) -> int:
    category_tokens = set(category.replace("_", " ").split())
    for index, (heading, _items) in enumerate(groups):
        if category_tokens & set(normalize_term(heading).split()):
            return index
    return 0


def _gate_errors(
    plan: ResumePlan,
    profile: Profile,
    requirements: list[RequirementTerm],
    actions: list[PlacementAction],
    source: str,
) -> list[str]:
    """Legacy test helper around the shared structured gate."""
    if not profile.raw_markdown:
        profile.raw_markdown = source
    context = build_resume_gate_context(profile, _source_content_plan(plan, profile, plan.evidence_links))
    return [
        finding.detail
        for finding in validate_resume_plan_findings(
            plan,
            profile,
            requirements,
            actions,
            context,
        )
        if finding.severity is not ValidationSeverity.WARN
    ]


def _optimization_blockers(
    findings: Iterable[ValidationFinding],
) -> tuple[ValidationFinding, ...]:
    return tuple(
        finding for finding in findings if finding.severity in {ValidationSeverity.FATAL, ValidationSeverity.DEGRADE}
    )


def _finding_reason(findings: Iterable[ValidationFinding]) -> str:
    values = list(findings)
    return "; ".join(f"{finding.code}: {finding.detail}" for finding in values[:2])


def _rejection(*, action: str, reason: str, code: GateCode) -> OptimizationRejection:
    """Create a legacy-compatible rejection with its stable structured code."""
    return OptimizationRejection(action=action, reason=reason, code=code)


def _gate_code_for_findings(findings: Iterable[ValidationFinding]) -> GateCode:
    """Classify actual validation findings without changing their gate behavior."""
    codes = {finding.code.casefold() for finding in findings}
    if any("stuff" in code for code in codes):
        return GateCode.STUFFING
    if any("natural" in code or "style" in code for code in codes):
        return GateCode.NATURALNESS_STYLE_REJECTION
    if any("missing" in code or "fidelity" in code or "preserv" in code for code in codes):
        return GateCode.PROTECTED_FACT_LOSS
    return GateCode.VALIDATION_FINDING


def _word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def _relevant_terms_per_100_words(text: str, requirements: list[RequirementTerm]) -> float:
    words = _word_count(text)
    if words == 0:
        return 0.0
    canonicals = {requirement.canonical for requirement in requirements if requirement.canonical}
    visible = sum(contains_fact(text, canonical) for canonical in canonicals)
    return visible / (words / 100)


def _finalize_diagnostics(
    trace: OptimizationTrace,
    recorder: _ProposalRecorder,
    source_plan: ResumePlan,
    delivered_plan: ResumePlan,
    requirements: list[RequirementTerm],
) -> None:
    """Persist one and only one terminal record for every planner action."""
    proposals = tuple(recorder.records.values())
    if len(proposals) != len(recorder.ids_by_label) or len({record.id for record in proposals}) != len(proposals):
        raise AssertionError("every planner-emitted action must have exactly one proposal record")
    if any(not isinstance(record.status, ProposalStatus) for record in proposals):
        raise AssertionError("every proposal must have a terminal status")

    source_text = generate_resume_text(source_plan)
    delivered_text = generate_resume_text(delivered_plan)
    statuses = {status.value: 0 for status in ProposalStatus}
    gates = {code.value: 0 for code in GateCode}
    operations: dict[str, int] = {}
    for record in proposals:
        statuses[record.status.value] += 1
        if record.status is ProposalStatus.REJECTED and record.gate_code is not None:
            gates[record.gate_code.value] += 1
        if record.status is ProposalStatus.ACCEPTED:
            operations[record.operation] = operations.get(record.operation, 0) + 1
    trace.diagnostics = RunDiagnostics(
        proposals=proposals,
        proposals_by_status={key: value for key, value in sorted(statuses.items()) if value},
        rejections_by_gate={key: value for key, value in sorted(gates.items()) if value},
        accepted_by_operation=dict(sorted(operations.items())),
        source_word_count=_word_count(source_text),
        delivered_word_count=_word_count(delivered_text),
        word_delta=_word_count(delivered_text) - _word_count(source_text),
        relevant_terms_per_100_words_before=_relevant_terms_per_100_words(source_text, requirements),
        relevant_terms_per_100_words_after=_relevant_terms_per_100_words(delivered_text, requirements),
        score_path=tuple(trace.score_path),
        iterations=trace.iterations,
        source_projection_sha256=hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
        delivered_sha256=hashlib.sha256(delivered_text.encode("utf-8")).hexdigest(),
    )


def _calibrated_codes(findings: Iterable[ValidationFinding]) -> list[str]:
    return sorted(
        {
            finding.original_code
            for finding in findings
            if finding.original_code and finding.severity is ValidationSeverity.WARN
        }
    )


def _dedupe_findings(findings: Iterable[ValidationFinding]) -> tuple[ValidationFinding, ...]:
    seen: set[tuple[str, str, str, str]] = set()
    result: list[ValidationFinding] = []
    for finding in findings:
        key = (
            finding.detector_code,
            finding.normalized_fact,
            finding.source_span,
            finding.detector_version,
        )
        if key not in seen:
            seen.add(key)
            result.append(finding)
    return tuple(result)


def _score_plan(
    plan: ResumePlan,
    source: str,
    requirements: list[RequirementTerm],
    links: list[EvidenceLink],
    actions: list[PlacementAction],
) -> AtsScoreV2:
    return score_resume_v2(
        generate_resume_text(plan),
        requirements,
        links,
        source_resume_text=source,
        tailored=True,
        placements=actions,
    )


def _dedupe_actions(actions: list[PlacementAction]) -> list[PlacementAction]:
    seen: set[tuple[str, str, str]] = set()
    result: list[PlacementAction] = []
    for action in actions:
        key = (normalize_term(action.term), action.target, action.operation)
        if key not in seen:
            seen.add(key)
            result.append(action)
    return result


def _dedupe_text(values: Iterable[object]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        key = normalize_term(text)
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def _join(values: list[str]) -> str:
    if len(values) <= 1:
        return values[0] if values else ""
    if len(values) == 2:
        return f"{values[0]} and {values[1]}"
    return f"{', '.join(values[:-1])}, and {values[-1]}"


def _action_label(action: PlacementAction) -> str:
    return f"{action.operation}:{action.target}:{action.term}"


__all__ = [
    "ResumeGateContext",
    "build_resume_gate_context",
    "optimize",
    "validate_resume_plan_findings",
]
