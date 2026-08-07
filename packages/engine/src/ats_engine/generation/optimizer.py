"""Monotone deterministic optimization for Tailoring Engine v2."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass, field, replace

from ats_engine.caching.content_hash import ContentHashCache
from ats_engine.generation.diagnostics import GateCode, ProposalRecord, ProposalStatus, RunDiagnostics, _word_count
from ats_engine.generation.integration_planner import plan_placements, proposal_inventory
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
    RemovedContent,
    RequirementTerm,
    ResumePlan,
)
from ats_engine.parsing.vocab import normalize_term
from ats_engine.pramana.scoring import score_resume
from ats_engine.providers.base import LLMProvider
from ats_engine.rachana.facts import build_fact_set
from ats_engine.rachana.objectives import ScoreVector, relevant_terms_per_100_words, score_vector
from ats_engine.rachana.operations import (
    ProseOutcome,
    SurfaceVariantMatch,
    SurfaceVariantRejection,
    SurfaceVariantResult,
    find_surface_variant,
    propose_bullet_rewrite,
    propose_summary_rewrite,
    substitute_surface_variant,
)
from ats_engine.rachana.preservation import PreservationGuard, build_guard, count_occurrences
from ats_engine.rachana.prose import (
    BULLET_REWRITE,
    REJECT_CROSS_EMPLOYER,
    REJECT_EVIDENCE_OUT_OF_SCOPE,
    REJECT_FACT_LOSS,
    REJECT_MALFORMED,
    REJECT_MISSING_CITATION,
    REJECT_NEW_FACTS,
    REJECT_NO_PROVIDER,
    REJECT_SCHEMA,
    REJECT_TEXT_UNCHANGED,
    REJECT_UNKNOWN_NODE,
    REJECT_UNSUPPORTED_CLAIM,
    REJECT_WORD_GROWTH,
    SUMMARY_REWRITE,
    EvidenceNode,
    ProseRejection,
    build_evidence_nodes,
)
from ats_engine.rachana.pruning import (
    REJECT_PROTECTED_FACT,
    REJECT_ROLE_FLOOR,
    REJECT_UNEVIDENCED_ENTITY,
    REJECT_UNIQUE_EVIDENCE,
    PruneProposal,
    check_prune,
    check_role_floor,
    normalize_for_match,
    screen_bullet,
)
from ats_engine.rachana.reordering import is_permutation, reorder_skill_items
from ats_engine.scoring.ats_v2 import AtsScoreV2, project_ats_v2, score_resume_v2
from ats_engine.validation.calibration import (
    CalibrationProfile,
    apply_calibration,
    calibrate_identity,
)
from ats_engine.validation.completeness import resume_completeness_errors
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

# The operation whose apply step is, by construction, a no-op on the document.
WEAVE_BULLET_OPERATION = "weave_bullet"

_BATCH_SIZE = 8
_MAX_ITERATIONS = 4
# The legacy policy's plateau break (a PRAMANA-score stall) does not apply
# under pareto (see the loop below), so the iteration cap becomes the only
# remaining bound on how many actions get a chance to run. Doubled rather
# than left at the legacy value so that removing the plateau break does not
# quietly turn the cap into a new, tighter, unintended ceiling: at
# _BATCH_SIZE=8 this covers up to 64 planner-emitted actions instead of 32,
# comfortably above every real fixture measured for this change (21-27).
_PARETO_MAX_ITERATIONS = 8


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

    def reclassify_no_ops(self) -> None:
        """Demote accepted proposals that provably changed no delivered text.

        ``_apply_actions`` writes summary, skills, headline, and
        surface_variant changes into the plan and nothing else, so a
        ``weave_bullet`` cannot alter the document by construction -- its
        bullet already contains the term, which is precisely why the planner
        emitted it. Counting it as an accepted *change* inflated every
        accepted-action figure in the benchmark (7 of LatentView's 17, 3 of
        CGI's 17) and told a reviewer the engine had done work it had not.

        The proposal is still real and is still kept in the action list handed
        to PRAMANA: it is genuine placement *provenance*, and
        ``pramana.scoring._placement_bonus`` legitimately reads it to see that
        a term appears in both skills and a bullet. What changes here is only
        the honesty of the reporting -- provenance is recorded as provenance,
        not as an edit. Giving weave_bullet a real effect would mean
        paraphrasing a candidate-authored bullet, which is LLM-rewrite
        territory and explicitly out of scope for this step.
        """
        for key, record in self.records.items():
            if record.status is ProposalStatus.ACCEPTED and record.operation == WEAVE_BULLET_OPERATION:
                self.records[key] = replace(
                    record,
                    status=ProposalStatus.NO_OP,
                    gate_detail=("provenance only: the bullet already states this term, so no delivered text changed"),
                )

    def record_prose(
        self,
        *,
        operation: str,
        target: str,
        attempt: int,
        status: ProposalStatus,
        code: GateCode | None,
        detail: str,
        cited: tuple[str, ...],
        proposed_text: str,
        word_delta: int,
        score_before: float | None = None,
        score_after: float | None = None,
        objectives_before: ScoreVector | None = None,
        objectives_after: ScoreVector | None = None,
    ) -> None:
        """Register one prose attempt as a first-class proposal record.

        A prose rewrite is not a ``PlacementAction`` -- it changes wording rather
        than placing a term -- so it never enters the planner inventory and is
        registered here instead. It still lands in exactly the same
        ``RunDiagnostics.proposals`` tuple as every other proposal, with the
        same objective deltas, which is what puts a model's attempt in the
        benchmark histogram beside the deterministic operations rather than in a
        parallel report of its own.

        ``attempt`` is part of the id so the first proposal and its one repair
        are both retained: a reviewer needs to see what the model proposed *and*
        what it proposed after being told why that failed.

        ``evidence_locations`` carries the cited node ids, and ``surface_to_use``
        the proposed text, so the diagnostics record is self-contained enough to
        audit the claim without re-running the engine.
        """
        record_id = f"{operation}:{target}:attempt{attempt}"
        if record_id in self.records:
            raise AssertionError(f"duplicate prose proposal id: {record_id}")
        delta = score_after - score_before if score_before is not None and score_after is not None else None
        if objectives_before is not None and objectives_after is not None:
            coverage: float | None = objectives_after.pramana_coverage - objectives_before.pramana_coverage
            adoption: float | None = objectives_after.jd_surface_adoption - objectives_before.jd_surface_adoption
            density: float | None = objectives_after.density - objectives_before.density
            placement: float | None = (
                objectives_after.placement_reinforcement - objectives_before.placement_reinforcement
            )
        else:
            coverage = adoption = density = placement = None
        self.records[record_id] = ProposalRecord(
            id=record_id,
            operation=operation,
            target=target,
            requirement_canonicals=(),
            requirement_weight=0.0,
            evidence_tier="cited",
            evidence_locations=cited,
            surface_to_use=proposed_text,
            word_delta=word_delta,
            status=status,
            gate_code=code,
            gate_detail=detail,
            score_before=score_before,
            score_after=score_after,
            score_delta=delta,
            batch_index=-1,
            iteration=-1,
            coverage_delta=coverage,
            adoption_delta=adoption,
            density_delta=density,
            placement_delta=placement,
        )
        self.ids_by_label[record_id] = record_id

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
        objectives_before: ScoreVector | None = None,
        objectives_after: ScoreVector | None = None,
    ) -> None:
        self._set(
            action,
            ProposalStatus.REJECTED,
            code=code,
            detail=detail,
            score_before=score_before,
            score_after=score_after,
            iteration=iteration,
            objectives_before=objectives_before,
            objectives_after=objectives_after,
        )

    def accept(
        self,
        actions: Iterable[PlacementAction],
        *,
        score_before: float,
        score_after: float,
        iteration: int,
        objectives_before: ScoreVector | None = None,
        objectives_after: ScoreVector | None = None,
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
                objectives_before=objectives_before,
                objectives_after=objectives_after,
            )

    def schedule(self, actions: Iterable[PlacementAction], *, batch_index: int, iteration: int) -> None:
        """Record the actual optimizer batch that reached each proposal."""
        for action in actions:
            record_id = self.ids_by_label[_action_label(action)]
            record = self.records[record_id]
            self.records[record_id] = replace(record, batch_index=batch_index, iteration=iteration)

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

    def finalize_unevaluated(self) -> None:
        """Give every proposal no batch ever reached a real terminal status.

        A run can return before the evaluation loop starts (source-projection
        failure, source score regression) or stop the loop early (iteration
        cap, score plateau) while planner actions remain unscheduled. Both are
        legitimate outcomes, not evaluator bugs, but ``NOT_EVALUATED`` is not
        a terminal status -- it exists only to detect a proposal the recorder
        never reached. Finalize is the one place that closes it out.
        """
        for record_id, record in self.records.items():
            if record.status is ProposalStatus.NOT_EVALUATED:
                self.records[record_id] = replace(
                    record,
                    status=ProposalStatus.REJECTED,
                    gate_code=GateCode.RUN_CONCLUDED_BEFORE_EVALUATION,
                    gate_detail="optimize() returned before this proposal was scheduled into a batch",
                )

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
        objectives_before: ScoreVector | None = None,
        objectives_after: ScoreVector | None = None,
    ) -> None:
        record_id = self.ids_by_label[_action_label(action)]
        record = self.records[record_id]
        # A bisection may have already rejected this exact proposal.  Preserve
        # that specific finding instead of overwriting it with the enclosing
        # batch's generic score result.
        if record.status is not ProposalStatus.NOT_EVALUATED:
            return
        delta = score_after - score_before if score_before is not None and score_after is not None else None
        coverage_delta: float | None
        adoption_delta: float | None
        density_delta: float | None
        placement_delta: float | None
        if objectives_before is not None and objectives_after is not None:
            coverage_delta = objectives_after.pramana_coverage - objectives_before.pramana_coverage
            adoption_delta = objectives_after.jd_surface_adoption - objectives_before.jd_surface_adoption
            density_delta = objectives_after.density - objectives_before.density
            placement_delta = objectives_after.placement_reinforcement - objectives_before.placement_reinforcement
        else:
            coverage_delta = adoption_delta = density_delta = placement_delta = None
        self.records[record_id] = replace(
            record,
            status=status,
            gate_code=code,
            gate_detail=detail,
            score_before=score_before,
            score_after=score_after,
            score_delta=delta,
            iteration=iteration,
            coverage_delta=coverage_delta,
            adoption_delta=adoption_delta,
            density_delta=density_delta,
            placement_delta=placement_delta,
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
    optimizer_policy: str = "pareto",
    word_budget: int = 950,
    prose_provider: LLMProvider | None = None,
    prose_cache: ContentHashCache | None = None,
) -> tuple[ResumePlan, OptimizationTrace]:
    """Apply safe quality and score actions without ever regressing ATS v2.

    Candidate-authored content is the delivery floor. Quality-only changes
    (headline, summary, individually validated provider rewrites) may be
    accepted at an equal score regardless of policy -- quality proposals are
    about prose, not keyword placement, and are out of the pareto policy's
    scope. Keyword-placement actions are gated by ``optimizer_policy``:
    ``"pareto"`` (the default) accepts a proposal that improves PRAMANA
    coverage, JD-surface adoption, or density without regressing any of the
    three beyond tolerance (see ``_pareto_verdict``); ``"legacy"`` requires a
    strict PRAMANA score improvement, exactly as before this policy existed.
    Failed placement batches are bisected either way so one unsafe proposal
    cannot discard unrelated safe work.

    ``prose_provider`` enables the two evidence-cited prose operations
    (``rachana.prose``). They run last, after pruning and reordering, against the
    document the reader would otherwise receive, and are accepted through the
    same pareto policy and recorded in the same ledger as everything else. With
    ``prose_provider=None`` -- every test, every deterministic run, and every
    deployment without a reachable model -- nothing about this function's
    behavior changes at all.
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
    actions = _dedupe_actions(plan_placements(links, profile, jd_profile))
    inventory = proposal_inventory(actions)
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
    current_evaluation = _evaluate_plan(current_plan, source, requirements, links, accepted)
    current_score = current_evaluation.ats_score
    current_objectives = current_evaluation.objectives
    # A stable snapshot for _finalize_diagnostics: every rollback below
    # delivers source_plan, whose own objectives never change, regardless of
    # what current_objectives is reassigned to while the loop is exploring
    # (and later discarding) placement batches.
    initial_objectives = current_objectives
    # Tracked alongside current_objectives so pruning sees what the *final*
    # placed document earns credit for, not what the source projection did.
    current_credited = current_evaluation.credited
    source_score = current_score
    accepted_quality: list[str] = []
    pruned_labels: list[str] = []

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
        _finalize_diagnostics(
            trace,
            recorder,
            source_plan,
            source_plan,
            requirements,
            initial_objectives=initial_objectives,
            final_objectives=initial_objectives,
        )
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

    max_iterations = _PARETO_MAX_ITERATIONS if optimizer_policy == "pareto" else _MAX_ITERATIONS
    for offset in range(0, len(actions), _BATCH_SIZE):
        if trace.iterations >= max_iterations:
            break
        batch = actions[offset : offset + _BATCH_SIZE]
        trace.iterations += 1
        recorder.schedule(batch, batch_index=offset // _BATCH_SIZE, iteration=trace.iterations)
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
        # A bisected-out action never reaches the score/pareto comparison
        # below at all -- _accept_safe_actions already rejected it on hard-
        # gate grounds. Recording that here, unconditionally, is what stops
        # it from falling through to finalize_unevaluated() and being
        # mislabeled "run concluded before evaluation" whenever the *rest* of
        # the batch goes on to be accepted (see the crowdplat/CGI proof in
        # test_bisected_out_actions_are_never_mislabeled_as_unevaluated).
        bisected_out = {rejection.action: rejection for rejection in rejected}
        for action in batch:
            rejection = bisected_out.get(_action_label(action))
            if rejection is not None:
                recorder.reject(
                    action,
                    code=rejection.code or GateCode.VALIDATION_FINDING,
                    detail=rejection.reason,
                    score_before=current_score.score,
                    score_after=None,
                    iteration=trace.iterations,
                )
        survivors = candidate_actions[len(accepted) :]
        candidate_evaluation = _evaluate_plan(candidate_plan, source, requirements, links, candidate_actions)
        candidate_score = candidate_evaluation.ats_score
        if optimizer_policy == "pareto":
            accept_batch = _pareto_verdict(current_objectives, candidate_evaluation.objectives)
            reject_reason = "no objective (PRAMANA coverage, JD-surface adoption, density) improved beyond tolerance"
        else:
            accept_batch = candidate_score.score > current_score.score
            reject_reason = "score did not strictly improve"
        if accept_batch:
            recorder.accept(
                survivors,
                score_before=current_score.score,
                score_after=candidate_score.score,
                iteration=trace.iterations,
                objectives_before=current_objectives,
                objectives_after=candidate_evaluation.objectives,
            )
            current_plan = candidate_plan
            accepted = candidate_actions
            current_score = candidate_score
            current_objectives = candidate_evaluation.objectives
            current_credited = candidate_evaluation.credited
            trace.score_path.append(current_score.score)
            trace.accepted_actions.extend(_action_label(action) for action in survivors)
        else:
            for action in survivors:
                trace.rejected_actions.append(
                    _rejection(
                        action=_action_label(action),
                        reason=reject_reason,
                        code=GateCode.SCORE_DID_NOT_STRICTLY_IMPROVE,
                    )
                )
                recorder.reject(
                    action,
                    code=GateCode.SCORE_DID_NOT_STRICTLY_IMPROVE,
                    detail=reject_reason,
                    score_before=current_score.score,
                    score_after=candidate_score.score,
                    iteration=trace.iterations,
                    objectives_before=current_objectives,
                    objectives_after=candidate_evaluation.objectives,
                )
        # A PRAMANA plateau does not mean there is no work left under pareto:
        # a batch can legitimately move density or JD-surface adoption while
        # leaving PRAMANA's own score untouched (that is the point of
        # SURFACE_VARIANT). Only the legacy scalar policy treats a stalled
        # score as a reason to stop early.
        if (
            optimizer_policy == "legacy"
            and len(trace.score_path) >= 2
            and trace.score_path[-1] - trace.score_path[-2] < 0.5
        ):
            break

    # Pruning runs last, against the fully-placed document: density's numerator
    # is only settled once every accepted placement is in, and a removal must
    # be judged against what the reader will actually receive.
    #
    # Pareto only, deliberately. The legacy policy is documented as the
    # rollback switch that "retains the original strict-PRAMANA-score-
    # improvement rule exactly"; a removal never improves that scalar, so
    # running it there would either do nothing or quietly redefine what the
    # rollback reproduces. Concentration is the pareto policy's mandate.
    removals: list[RemovedContent] = []
    if optimizer_policy == "pareto":
        current_plan, current_objectives, removals, pruned_labels = _apply_pruning(
            current_plan,
            profile=profile,
            requirements=requirements,
            links=links,
            source=source,
            accepted=accepted,
            objectives=current_objectives,
            credited=current_credited,
            context=context,
            guard=guard,
            trace=trace,
            min_density_ratio=(
                _PRUNE_MIN_DENSITY_GAIN_RATIO
                if current_objectives.word_count > word_budget
                else _PRUNE_MIN_DENSITY_GAIN_RATIO * _AT_BUDGET_STRICTNESS
            ),
        )
        # After pruning, so ranking sees only content that survives.
        current_plan, reorder_labels = _apply_reordering(
            current_plan,
            profile=profile,
            requirements=requirements,
            accepted=accepted,
            context=context,
            guard=guard,
            trace=trace,
        )
        pruned_labels = [*pruned_labels, *reorder_labels]

        # Prose rewriting runs last, against the document the reader would
        # otherwise receive: expression quality is judged on the final placed,
        # pruned, reordered text, not on an intermediate nobody sees. Gated to
        # the pareto policy for the same reason pruning is -- the legacy policy
        # is documented as reproducing the original strict-PRAMANA rule exactly,
        # and admitting a new operation there would quietly redefine what the
        # rollback switch rolls back to.
        if prose_provider is not None:
            current_plan, current_objectives, prose_labels = _apply_prose_rewrites(
                current_plan,
                profile=profile,
                jd_profile=jd_profile,
                requirements=requirements,
                links=links,
                source=source,
                accepted=accepted,
                objectives=current_objectives,
                removals=removals,
                context=context,
                guard=guard,
                trace=trace,
                recorder=recorder,
                provider=prose_provider,
                cache=prose_cache,
            )
            pruned_labels = [*pruned_labels, *prose_labels]

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
        _finalize_diagnostics(
            trace,
            recorder,
            source_plan,
            source_plan,
            requirements,
            initial_objectives=initial_objectives,
            final_objectives=initial_objectives,
        )
        return source_plan, trace

    # A delivered document must never state a JD-relevant term less often than
    # the candidate's own source did.  This is checked once more at the end
    # because the summary and bullet rewrites above take a different path into
    # the plan than the batched placements do.
    current_plan_text = generate_resume_text(current_plan)
    final_regressions = guard.regressions(current_plan_text)
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
        _finalize_diagnostics(
            trace,
            recorder,
            source_plan,
            source_plan,
            requirements,
            initial_objectives=initial_objectives,
            final_objectives=initial_objectives,
        )
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
        _finalize_diagnostics(
            trace,
            recorder,
            source_plan,
            source_plan,
            requirements,
            initial_objectives=initial_objectives,
            final_objectives=initial_objectives,
        )
        return source_plan, trace

    # weave_bullet is provenance, not an edit (see reclassify_no_ops): it stays
    # in `accepted` for PRAMANA's placement bonus but must not be reported as a
    # change the reader would see.
    trace.accepted_actions = [
        *accepted_quality,
        *[_action_label(a) for a in accepted if a.operation != WEAVE_BULLET_OPERATION],
        *pruned_labels,
    ]
    if not trace.score_path or trace.score_path[-1] != final_score.score:
        trace.score_path.append(final_score.score)
    trace.calibration_suppressed = _calibrated_codes(final_findings)
    if trace.accepted_actions or final_score.score > original.score + 0.001:
        trace.delivery_state = DocumentState.GENERATED
        trace.fallback_reason = ""
    else:
        trace.delivery_state = DocumentState.GENERATED_WITH_FALLBACK
        trace.fallback_reason = "No safe evidence-backed improvement was accepted; delivered the source projection."
    _finalize_diagnostics(
        trace,
        recorder,
        source_plan,
        current_plan,
        requirements,
        precomputed_delivered_text=current_plan_text,
        initial_objectives=initial_objectives,
        final_objectives=current_objectives,
    )
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
    actions = _dedupe_actions(plan_placements(links, profile, jd_profile))
    inventory = proposal_inventory(actions)
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
        recorder.schedule(batch, batch_index=offset // _BATCH_SIZE, iteration=trace.iterations)
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
    # A ledgered removal must be excused here for the same reason it is excused
    # by completeness: this gate detects content *silently* lost, and pairing a
    # deliberately removed bullet against an empty candidate would report the
    # removal as exactly the fabrication-adjacent failure it is not. Only the
    # bullets the ledger names verbatim are skipped; see
    # ``validation.fidelity._raw_source_bullet_findings``.
    removed_texts = [item.original_text for item in plan.removed_content if item.kind == "bullet"]
    removed_keys = {normalize_for_match(text) for text in removed_texts if normalize_for_match(text)}
    bullet_pairs: list[BulletPair] = []
    experience_matches = match_experience_indices(profile.experiences, plan.experience)
    for source_experience_index, source_experience in enumerate(profile.experiences):
        candidate_experience_index = experience_matches[source_experience_index]
        candidate_bullets = (
            plan.experience[candidate_experience_index].bullets if candidate_experience_index is not None else []
        )
        bullet_matches = match_bullet_indices(source_experience.bullets, candidate_bullets)
        for source_bullet_index, source_bullet in enumerate(source_experience.bullets):
            if normalize_for_match(source_bullet) in removed_keys:
                continue
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
        removed_bullets=removed_texts,
    )
    stuffing = apply_calibration(
        validate_resume_stuffing_findings(
            actions=action_list,
            summary=_without_targeting(plan.summary, plan.jd_profile),
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
    candidate, surface_variant_failures = _apply_actions(plan, pending, profile)
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
    if not blockers and not regressions and not surface_variant_failures:
        return candidate, candidate_actions, []
    if len(pending) == 1:
        action = pending[0]
        if surface_variant_failures:
            failure = surface_variant_failures[0]
            return (
                plan,
                accepted,
                [
                    _rejection(
                        action=_action_label(action),
                        reason=failure.rejection.detail,
                        code=_surface_variant_gate_code(failure.rejection.reason),
                    )
                ],
            )
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


@dataclass(frozen=True, slots=True)
class _SurfaceVariantFailure:
    """One surface_variant action that failed closed while applying a batch."""

    action: PlacementAction
    rejection: SurfaceVariantRejection


def _apply_actions(
    base: ResumePlan, actions: list[PlacementAction], profile: Profile
) -> tuple[ResumePlan, list[_SurfaceVariantFailure]]:
    plan = deepcopy(base)
    summary_links = [action.link for action in actions if action.target == "summary"]
    _apply_summary(plan, summary_links)
    _apply_skills(plan, [action for action in actions if action.target == "skills"], profile)
    _apply_headline(plan, [action for action in actions if action.target == "headline"])
    # Bullet actions are source-order annotations only. A direct source bullet
    # already carries the phrase; forcing a paraphrase creates fact-loss risk.
    # surface_variant is the one exception: it substitutes only the
    # candidate's own already-present spelling, never a paraphrase.
    failures = _apply_surface_variants(plan, [action for action in actions if action.operation == "surface_variant"])
    plan.placement_actions = list(actions)
    return plan, failures


def _apply_surface_variants(plan: ResumePlan, actions: list[PlacementAction]) -> list[_SurfaceVariantFailure]:
    failures: list[_SurfaceVariantFailure] = []
    for action in actions:
        variant = find_surface_variant(action.link)
        if variant is None:
            # Eligibility was re-checked and no longer holds -- for example a
            # sibling action in this same batch already touched this exact
            # field. Nothing to substitute is not a hazard.
            continue
        outcome = _substitute_in_plan(plan, action.link.resume_location, variant)
        if isinstance(outcome, SurfaceVariantRejection):
            failures.append(_SurfaceVariantFailure(action=action, rejection=outcome))
    return failures


def _substitute_in_plan(
    plan: ResumePlan, location: str, variant: SurfaceVariantMatch
) -> SurfaceVariantResult | SurfaceVariantRejection | None:
    """Apply *variant* to whichever field *location* names, or None if unrecognized."""
    if location == "summary":
        outcome = substitute_surface_variant(plan.summary, variant)
        if isinstance(outcome, SurfaceVariantResult):
            plan.summary = outcome.text
        return outcome
    if location.startswith("skills"):
        return _substitute_in_skills(plan, variant)
    bullet_match = re.match(r"^experience:(\d+):bullet:(\d+)$", location)
    if bullet_match is not None:
        exp_index, bullet_index = int(bullet_match.group(1)), int(bullet_match.group(2))
        if exp_index < len(plan.experience) and bullet_index < len(plan.experience[exp_index].bullets):
            bullets = plan.experience[exp_index].bullets
            outcome = substitute_surface_variant(bullets[bullet_index], variant)
            if isinstance(outcome, SurfaceVariantResult):
                bullets[bullet_index] = outcome.text
            return outcome
    return None


def _substitute_in_skills(
    plan: ResumePlan, variant: SurfaceVariantMatch
) -> SurfaceVariantResult | SurfaceVariantRejection:
    for group_index, (heading, items) in enumerate(plan.skill_groups):
        for item_index, item in enumerate(items):
            outcome = substitute_surface_variant(item, variant)
            if isinstance(outcome, SurfaceVariantResult) and outcome.changed:
                new_items = list(items)
                new_items[item_index] = outcome.text
                plan.skill_groups[group_index] = (heading, new_items)
                return outcome
    # Nothing changed anywhere. Either some entry already states the JD
    # surface (idempotent success -- a sibling action, or a prior run,
    # already did this), or the candidate's own spelling is no longer
    # present anywhere in skills (fail closed).
    for _heading, items in plan.skill_groups:
        for item in items:
            if count_occurrences(item, variant.target_surface) > 0:
                return SurfaceVariantResult(text=item, changed=False)
    return SurfaceVariantRejection(
        reason="text_drifted",
        detail="the candidate's own spelling is no longer present in any skills entry",
    )


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


def _without_targeting(summary: str, jd_profile: JDProfile) -> str:
    """The candidate-authored summary text, for anti-stuffing measurement only.

    Inverse of ``_with_targeting``. That clause is JD title context the
    engine appends -- "never candidate history" per its own docstring -- so
    counting its terms toward the candidate's own keyword-stuffing budget is a
    category error, not a real repetition. Left unfixed, a JD title that
    repeats a term the candidate already uses near the stuffing ceiling (for
    example a title containing "Java" when the candidate's resume already
    states "Java" four times) pushes the *engine's own* text over the limit
    and then blocks every placement proposal because of it -- a defect that
    exists identically with zero proposals applied, since it is entirely a
    property of the source projection. The clause stays in the delivered and
    *scored* summary (that is its intended target-title signal); it is
    excluded only from the text this anti-stuffing measurement counts.
    """
    title = jd_profile.title.strip()
    if not title or title == "Target Role":
        return summary
    clean_title = title.replace("–", "-").replace("—", "-")
    clause = f"Targeting {clean_title} opportunities."
    stripped = summary.strip()
    if stripped.casefold().endswith(clause.casefold()):
        return stripped[: len(stripped) - len(clause)].strip()
    return stripped


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

    # Pruning breaks the positional source<->delivered correspondence this loop
    # used to assume, so bullets are matched by content and removals get their
    # own decision. Without the `omitted` record below a prune would be
    # unreviewable and irreversible: the change ledger is what lets a user
    # restore a removed bullet, and what `kit.change_actions` rebuilds from.
    removed_keys = {
        normalize_for_match(item.original_text)
        for item in plan.removed_content
        if item.kind == "bullet" and normalize_for_match(item.original_text)
    }
    for exp_index, source_experience in enumerate(profile.experiences):
        if exp_index >= len(plan.experience):
            continue
        delivered_bullets = plan.experience[exp_index].bullets
        matches = match_bullet_indices(source_experience.bullets, delivered_bullets)
        for bullet_index, source_bullet in enumerate(source_experience.bullets):
            location_id = f"resume::exp{exp_index}::bullet{bullet_index}"
            if normalize_for_match(source_bullet) in removed_keys:
                decisions.append(
                    PlanDecision(
                        kind="bullet",
                        location_id=location_id,
                        original_text=source_bullet,
                        tailored_text="",
                        operation="omitted",
                        reason=(
                            "Removed a bullet with no job-relevant term, no checkable fact, and no unique "
                            "evidence, to concentrate the resume. Restore it to put it back verbatim."
                        ),
                    )
                )
                continue
            delivered_index = matches[bullet_index]
            if delivered_index is None:
                continue
            tailored_bullet = delivered_bullets[delivered_index]
            target = f"experience:{exp_index}:bullet:{bullet_index}"
            action_terms = [action.term for action in actions if action.target == target]
            if tailored_bullet.strip() == source_bullet.strip() and not action_terms:
                continue
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

    # A pure reorder produces no per-bullet decision above -- the bullets are
    # matched by content and their text is unchanged -- so without this record
    # the move would be invisible and irreversible, which is precisely why
    # bullet sorting was removed from `_select_experience` in the first place.
    # The record names the order before and after; rejecting it restores the
    # candidate's own sequence (see `kit.change_actions._apply_bullet_order`).
    for exp_index, source_experience in enumerate(profile.experiences):
        if exp_index >= len(plan.experience):
            continue
        source_order = [bullet for bullet in source_experience.bullets if bullet.strip()]
        delivered_order = [bullet for bullet in plan.experience[exp_index].bullets if bullet.strip()]
        if sorted(source_order) == sorted(delivered_order) and source_order != delivered_order:
            decisions.append(
                PlanDecision(
                    kind="bullet",
                    location_id=f"resume::exp{exp_index}::order",
                    original_text="\n".join(source_order),
                    tailored_text="\n".join(delivered_order),
                    operation="reordered",
                    reason=(
                        "Ordered this role's bullets by job relevance so the most relevant work reads "
                        "first. No wording changed. Reject to restore your original order."
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


def _surface_variant_gate_code(reason: str) -> GateCode:
    return {
        "substring_hazard": GateCode.SURFACE_VARIANT_SUBSTRING_HAZARD,
        "fact_risk": GateCode.SURFACE_VARIANT_FACT_RISK,
        "text_drifted": GateCode.SURFACE_VARIANT_TEXT_DRIFTED,
    }[reason]


def _finalize_diagnostics(
    trace: OptimizationTrace,
    recorder: _ProposalRecorder,
    source_plan: ResumePlan,
    delivered_plan: ResumePlan,
    requirements: list[RequirementTerm],
    *,
    precomputed_delivered_text: str | None = None,
    initial_objectives: ScoreVector | None = None,
    final_objectives: ScoreVector | None = None,
) -> None:
    """Persist one and only one terminal record for every planner action.

    ``precomputed_delivered_text`` lets a caller that already rendered
    ``delivered_plan`` for an earlier check (for example the final
    preservation-guard pass) hand that text back in instead of paying for a
    second identical render. ``initial_objectives``/``final_objectives`` are
    None on every path that never evaluates the pareto policy's objectives at
    all (the legacy policy, ``_optimize_pr21_compat``, or a return before
    ``optimize()`` computes them) -- callers that have them pass them in
    rather than this function recomputing a third PRAMANA pass.
    """
    recorder.finalize_unevaluated()
    recorder.reclassify_no_ops()
    proposals = tuple(recorder.records.values())
    if len(proposals) != len(recorder.ids_by_label) or len({record.id for record in proposals}) != len(proposals):
        raise AssertionError("every planner-emitted action must have exactly one proposal record")
    if any(record.status is ProposalStatus.NOT_EVALUATED for record in proposals):
        raise AssertionError("every proposal must reach a terminal status before finalize")

    source_text = generate_resume_text(source_plan)
    if delivered_plan is source_plan:
        delivered_text = source_text
    elif precomputed_delivered_text is not None:
        delivered_text = precomputed_delivered_text
    else:
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
    # Removals are not PlacementActions and deliberately never enter the
    # planner inventory: `placements` is fed straight to PRAMANA's placement
    # bonus, and a synthetic action there would corrupt the score it is meant
    # to describe. They are counted here so the benchmark's operation
    # histogram still reports them alongside everything else.
    removals = tuple((item.location, item.original_text) for item in delivered_plan.removed_content)
    if removals:
        operations["prune"] = len(removals)
    trace.diagnostics = RunDiagnostics(
        proposals=proposals,
        proposals_by_status={key: value for key, value in sorted(statuses.items()) if value},
        rejections_by_gate={key: value for key, value in sorted(gates.items()) if value},
        accepted_by_operation=dict(sorted(operations.items())),
        source_word_count=_word_count(source_text),
        delivered_word_count=_word_count(delivered_text),
        word_delta=_word_count(delivered_text) - _word_count(source_text),
        relevant_terms_per_100_words_before=relevant_terms_per_100_words(source_text, requirements),
        relevant_terms_per_100_words_after=relevant_terms_per_100_words(delivered_text, requirements),
        score_path=tuple(trace.score_path),
        iterations=trace.iterations,
        source_projection_sha256=hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
        delivered_sha256=hashlib.sha256(delivered_text.encode("utf-8")).hexdigest(),
        pramana_coverage_before=initial_objectives.pramana_coverage if initial_objectives is not None else 0.0,
        pramana_coverage_after=final_objectives.pramana_coverage if final_objectives is not None else 0.0,
        jd_surface_adoption_before=(initial_objectives.jd_surface_adoption if initial_objectives is not None else 0.0),
        jd_surface_adoption_after=final_objectives.jd_surface_adoption if final_objectives is not None else 0.0,
        placement_reinforcement_before=(
            initial_objectives.placement_reinforcement if initial_objectives is not None else 0.0
        ),
        placement_reinforcement_after=(
            final_objectives.placement_reinforcement if final_objectives is not None else 0.0
        ),
        removals=removals,
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


@dataclass(frozen=True, slots=True)
class _PlanEvaluation:
    """One PRAMANA pass, projected two ways.

    ``ats_score`` is the legacy scalar gate every existing caller (quality
    proposals, the final floor checks, ``_optimize_pr21_compat``) still uses.
    ``objectives`` is the pareto policy's vector. Both are views of the same
    underlying ``PramanaScore``, computed once, so neither policy pays for a
    second PRAMANA pass over the same text.
    """

    ats_score: AtsScoreV2
    objectives: ScoreVector
    # The requirements this text actually earns credit for. Pruning needs it to
    # tell a bullet that is the sole support for something the resume is being
    # paid for from one supporting a requirement with no credit to lose.
    credited: frozenset[str] = frozenset()


def _evaluate_plan(
    plan: ResumePlan,
    source: str,
    requirements: list[RequirementTerm],
    links: list[EvidenceLink],
    actions: list[PlacementAction],
) -> _PlanEvaluation:
    text = generate_resume_text(plan)
    pramana = score_resume(
        text,
        requirements,
        links,
        source_resume_text=source,
        tailored=True,
        placements=actions,
    )
    return _PlanEvaluation(
        ats_score=project_ats_v2(pramana),
        objectives=score_vector(text, requirements, pramana),
        credited=frozenset(credit.requirement.canonical for credit in pramana.per_requirement if credit.credit > 0),
    )


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


# Per-objective tolerance for the pareto policy, each sized to that
# objective's own scale (ats_engine.rachana.objectives.ScoreVector):
# pramana_coverage and jd_surface_adoption are 0..1 fractions, so 0.01 is a
# real, integer-count-level change with headroom above floating-point noise.
# density is measured in relevant terms per 100 words; in a ~1000-word resume
# one additional distinct canonical becoming visible moves it by roughly 0.1,
# so 0.02 is well below a real single-term change but well above noise.
_COVERAGE_TOLERANCE = 0.01
_ADOPTION_TOLERANCE = 0.01
_DENSITY_TOLERANCE = 0.02
# placement_reinforcement is PRAMANA's own placement_bonus, a 0..4 integer
# count (see ScoreVector.placement_reinforcement). Its values are exact
# floats with no accumulated rounding, so 0.5 is simply "at least one whole
# reinforcement," not noise headroom.
_PLACEMENT_TOLERANCE = 0.5


def _pareto_verdict(before: ScoreVector, after: ScoreVector) -> bool:
    """Whether *after* is acceptable relative to *before* under the pareto policy.

    Order matches the brief: (1) hard gates are checked by the caller before
    this is ever consulted, and are not repeated here; (2) reject any
    regression beyond tolerance on any objective; (3) accept only if at least
    one objective improves beyond its own threshold.

    ``placement_reinforcement`` (see ``ScoreVector``) is a fourth objective
    alongside the brief's original three. Without it, pareto has no way to
    see the one thing PRAMANA's own ``_placement_bonus`` rewards -- a term
    reinforced in both skills and a bullet -- so it rejected every action
    legacy accepted on that basis alone, as a flat, zero-objective-movement
    candidate (see the CrowdPlat measurement in the PR description). That is
    a real, safe, useful signal a scalar acceptance rule can see and a
    three-objective vector structurally cannot; giving pareto its own view of
    it is the fix, not a reason to fall back to the scalar rule.

    Point 4 of the brief ("among non-dominated candidates, prefer...") is a
    tie-break for choosing among *several* alternative candidates for the
    same slot. The planner never proposes more than one action per
    requirement per location, so there is no such set to rank here -- this
    function only ever compares one candidate against its immediate
    predecessor, and there is nothing to break a tie between. An earlier
    version of this function used point 4's ordering to accept genuinely flat
    candidates (no regression, but nothing over threshold either); measured
    against the real fixtures, that let batches that added words without any
    real improvement accumulate across iterations until the summary tripped
    the stuffing budget and the whole run rolled back to the source
    projection -- worse than rejecting them outright. Flat candidates are
    rejected, matching point 3's threshold literally.
    """
    if (
        after.pramana_coverage < before.pramana_coverage - _COVERAGE_TOLERANCE
        or after.jd_surface_adoption < before.jd_surface_adoption - _ADOPTION_TOLERANCE
        or after.density < before.density - _DENSITY_TOLERANCE
        or after.placement_reinforcement < before.placement_reinforcement - _PLACEMENT_TOLERANCE
    ):
        return False
    return (
        after.pramana_coverage > before.pramana_coverage + _COVERAGE_TOLERANCE
        or after.jd_surface_adoption > before.jd_surface_adoption + _ADOPTION_TOLERANCE
        or after.density > before.density + _DENSITY_TOLERANCE
        or after.placement_reinforcement > before.placement_reinforcement + _PLACEMENT_TOLERANCE
    )


# A prune must *concentrate* the document, not merely shorten it. The
# threshold is relative rather than absolute because absolute density gain
# scales with the numerator: removing 17 words from a 1000-word resume raises
# density by 0.026 when 15 canonicals are visible but only 0.009 when 5 are,
# so any fixed cut-off would silently mean "only fixtures with dense JDs may
# be pruned". Relative gain is scale-free: removing k words with the numerator
# held constant is exactly a k/(N-k) improvement, so 0.5% also implies a
# materially sized cut (~5 words in a 1000-word document) and a prune that
# takes a canonical with it fails outright, since the numerator drops.
_PRUNE_MIN_DENSITY_GAIN_RATIO = 0.005
# How much harder a prune must work once the document is already inside
# EngineSettings.resume_word_budget. This is the whole mechanism by which the
# budget "prefers proposals moving the document toward it": over budget,
# concision is the binding need and the ordinary threshold applies; at or under
# it, length is no longer the problem, so a removal has to justify itself on
# concentration alone. Nothing is ever truncated to reach the budget.
_AT_BUDGET_STRICTNESS = 4.0


def _prune_gate_code(reason: str) -> GateCode:
    """Map a pruning rejection reason to its stable diagnostics code."""
    return {
        REJECT_UNIQUE_EVIDENCE: GateCode.PRUNE_UNIQUE_EVIDENCE,
        REJECT_PROTECTED_FACT: GateCode.PRUNE_PROTECTED_FACT,
        REJECT_UNEVIDENCED_ENTITY: GateCode.PRUNE_UNEVIDENCED_ENTITY,
        REJECT_ROLE_FLOOR: GateCode.PRUNE_ROLE_FLOOR,
    }[reason]


def _prune_verdict(before: ScoreVector, after: ScoreVector, *, min_density_ratio: float) -> str:
    """Whether a prune is acceptable. Returns "" to accept, or a reject reason.

    Pruning gets its own rule rather than reusing ``_pareto_verdict`` for one
    structural reason: that function's density threshold is *absolute*
    (``_DENSITY_TOLERANCE``), sized for an additive action that makes one more
    canonical visible and moves density by roughly 0.1. A removal moves density
    by a fraction of that -- correctly so, it adds no canonical -- and would be
    read as a flat candidate and rejected on every fixture. The rule below is
    strictly *more* conservative than pareto on every other objective:

    * ``pramana_coverage`` may not fall **at all**, not merely within
      tolerance. Coverage is what the resume is credited for; content earning
      it is content that must stay.
    * ``jd_surface_adoption`` and ``placement_reinforcement`` keep pareto's own
      regression tolerances, so a removal cannot quietly undo a placement.
    * ``density`` must rise by ``min_density_ratio``, and ``word_count`` must
      actually fall -- together, "cutting is not automatically good".
    """
    if after.pramana_coverage < before.pramana_coverage:
        return "prune would reduce PRAMANA coverage"
    if after.jd_surface_adoption < before.jd_surface_adoption - _ADOPTION_TOLERANCE:
        return "prune would reduce JD-surface adoption"
    if after.placement_reinforcement < before.placement_reinforcement - _PLACEMENT_TOLERANCE:
        return "prune would reduce placement reinforcement"
    if after.word_count >= before.word_count:
        return "prune did not shorten the document"
    if after.density < before.density * (1.0 + min_density_ratio):
        return (
            f"prune raised density by less than {min_density_ratio:.1%} ({before.density:.4f} -> {after.density:.4f})"
        )
    return ""


def _apply_pruning(
    plan: ResumePlan,
    *,
    profile: Profile,
    requirements: list[RequirementTerm],
    links: list[EvidenceLink],
    source: str,
    accepted: list[PlacementAction],
    objectives: ScoreVector,
    credited: frozenset[str],
    context: ResumeGateContext,
    guard: PreservationGuard,
    trace: OptimizationTrace,
    min_density_ratio: float,
) -> tuple[ResumePlan, ScoreVector, list[RemovedContent], list[str]]:
    """Remove provably-safe low-relevance bullets, one at a time.

    One at a time, each re-scored and each re-validated, because a batch would
    make it impossible to say which removal caused a regression -- and a
    regression here means deleted candidate content, the one failure this
    project treats as product-defining. Every rejection is recorded against
    the specific protection that fired.
    """
    fact_set = build_fact_set(profile)
    current = plan
    current_objectives = objectives
    removals: list[RemovedContent] = []
    # Returned rather than appended to the trace here: `optimize` rebuilds
    # `trace.accepted_actions` from scratch after the final gates, so a label
    # written now would be discarded.
    labels: list[str] = []

    # Oldest role first, then source order. Older content is the lowest-risk
    # place to cut, and a fixed order keeps the run reproducible.
    proposals: list[PruneProposal] = []
    document_text = generate_resume_text(current)
    for experience_index, entry in enumerate(current.experience):
        for bullet_index, bullet in enumerate(entry.bullets):
            proposal = screen_bullet(
                experience_index,
                bullet_index,
                bullet,
                requirements=requirements,
                document_text=document_text,
            )
            if proposal is not None:
                proposals.append(proposal)
    proposals.sort(key=lambda item: (-item.experience_index, item.bullet_index))

    for proposal in proposals:
        role = current.experience[proposal.experience_index]
        # The bullet may have shifted index after an earlier accepted removal
        # in the same role; match on text, which is what the ledger records.
        live_index = next(
            (
                index
                for index, bullet in enumerate(role.bullets)
                if normalize_for_match(bullet) == normalize_for_match(proposal.text)
            ),
            None,
        )
        if live_index is None:
            continue
        rejection = check_prune(
            proposal,
            role=role,
            links=links,
            fact_set=fact_set,
            credited_canonicals=credited,
        ) or check_role_floor(
            proposal.experience_index,
            # Emptied slots are removals already applied, not live content.
            sum(1 for bullet in role.bullets if bullet.strip()),
        )
        if rejection is not None:
            trace.rejected_actions.append(
                _rejection(
                    action=f"prune:{proposal.location}",
                    reason=rejection.detail,
                    code=_prune_gate_code(rejection.reason),
                )
            )
            continue

        candidate = deepcopy(current)
        # Emptied, not popped: popping would shift every later bullet's index,
        # and the change-ledger id (`resume::expN::bulletM`) plus
        # `kit.change_actions._set_bullet`'s restore-by-position are both keyed
        # on the *source* index. Blanking the slot keeps a rejected removal
        # restorable into exactly the place it came from. Neither renderer
        # emits an empty bullet, so the delivered document really is shorter.
        candidate.experience[proposal.experience_index].bullets[live_index] = ""
        candidate_removals = [
            *removals,
            RemovedContent(kind="bullet", location=proposal.location, original_text=proposal.text),
        ]
        candidate.removed_content = list(candidate_removals)

        evaluation = _evaluate_plan(candidate, source, requirements, links, accepted)
        reject_reason = _prune_verdict(current_objectives, evaluation.objectives, min_density_ratio=min_density_ratio)
        if reject_reason:
            code = GateCode.PRUNE_COVERAGE_REGRESSION if "coverage" in reject_reason else GateCode.PRUNE_NO_DENSITY_GAIN
            trace.rejected_actions.append(
                _rejection(action=f"prune:{proposal.location}", reason=reject_reason, code=code)
            )
            continue

        # The removal must survive exactly the gates a delivered document
        # faces: nothing job-relevant weakened, nothing unaccounted-for gone.
        candidate_text = generate_resume_text(candidate)
        regressions = guard.regressions(candidate_text)
        completeness = resume_completeness_errors(candidate_text, profile, candidate_removals)
        findings = _optimization_blockers(
            validate_resume_plan_findings(candidate, profile, requirements, accepted, context)
        )
        if regressions or completeness or findings:
            detail = (
                regressions[0].describe()
                if regressions
                else (completeness[0] if completeness else _finding_reason(findings))
            )
            trace.rejected_actions.append(
                _rejection(
                    action=f"prune:{proposal.location}",
                    reason=detail,
                    code=(
                        GateCode.PROTECTED_FACT_LOSS
                        if regressions
                        else (
                            GateCode.PRUNE_COMPLETENESS_VIOLATION if completeness else _gate_code_for_findings(findings)
                        )
                    ),
                )
            )
            continue

        current = candidate
        current_objectives = evaluation.objectives
        removals = candidate_removals
        labels.append(f"prune:{proposal.location}")

    current.removed_content = list(removals)
    return current, current_objectives, removals, labels


def _apply_reordering(
    plan: ResumePlan,
    *,
    profile: Profile,
    requirements: list[RequirementTerm],
    accepted: list[PlacementAction],
    context: ResumeGateContext,
    guard: PreservationGuard,
    trace: OptimizationTrace,
) -> tuple[ResumePlan, list[str]]:
    """Rank bullets and skill items by JD relevance, or change nothing.

    Applied as one candidate rather than per item: a reorder moves no words and
    adds no term, so there is no per-item score to compare and nothing a
    bisect could isolate. Either the whole reordering passes the delivered
    document's own gates or none of it is kept.

    Not routed through ``_pareto_verdict`` deliberately -- see
    ``rachana.reordering``. A permutation moves none of the four objectives by
    construction, so that rule would reject every reorder as flat. It is gated
    as a quality proposal, the class the optimizer already accepts at an equal
    score because it is about presentation rather than keyword placement, and
    it still faces the preservation guard and the full validation gate below.
    """
    candidate = deepcopy(plan)
    labels: list[str] = []

    for group_index, (heading, items) in enumerate(candidate.skill_groups):
        ranked = reorder_skill_items(list(items), requirements)
        if not is_permutation(list(items), ranked):
            raise AssertionError(f"SKILL_REORDER changed the item multiset in group {heading!r}")
        if ranked != list(items):
            candidate.skill_groups[group_index] = (heading, ranked)
            labels.append(f"skill_reorder:skills:{group_index}")

    # Bullet REORDER is implemented and unit-tested in rachana.reordering but is
    # deliberately NOT applied here. Measured, enabling it rolled CGI and
    # LatentView back to the source projection entirely (1002 -> 1002 words, all
    # 17 accepted actions lost). The cause is structural, not a tuning problem:
    # a PlacementAction addresses its evidence as `experience:<i>:bullet:<j>`,
    # and PRAMANA resolves that provenance positionally
    # (`pramana.scoring._experience_bullets`). Permuting bullets silently
    # invalidates every one of those targets, the placement bonus collapses,
    # the final score falls below the source floor, and the whole run is
    # discarded -- so the reorder would cost far more than the reading-order
    # benefit it buys.
    #
    # Reported rather than worked around, per the brief: making this safe needs
    # placement provenance to be content-addressed rather than index-addressed,
    # which is a change to the scorer's evidence resolution and belongs in its
    # own PR. Nothing here weakens a gate to get the reorder through.

    if not labels:
        return plan, []

    candidate_text = generate_resume_text(candidate)
    regressions = guard.regressions(candidate_text)
    findings = _optimization_blockers(
        validate_resume_plan_findings(candidate, profile, requirements, accepted, context)
    )
    if regressions or findings:
        detail = regressions[0].describe() if regressions else _finding_reason(findings)
        for label in labels:
            trace.rejected_actions.append(
                _rejection(
                    action=label,
                    reason=detail,
                    code=GateCode.PROTECTED_FACT_LOSS if regressions else _gate_code_for_findings(findings),
                )
            )
        return plan, []
    return candidate, labels


_PROSE_GATE_CODES: dict[str, GateCode] = {
    REJECT_NO_PROVIDER: GateCode.PROSE_PROVIDER_UNAVAILABLE,
    REJECT_MALFORMED: GateCode.PROSE_MALFORMED_RESPONSE,
    REJECT_SCHEMA: GateCode.PROSE_SCHEMA_VIOLATION,
    REJECT_UNKNOWN_NODE: GateCode.PROSE_UNKNOWN_EVIDENCE_NODE,
    REJECT_MISSING_CITATION: GateCode.PROSE_MISSING_CITATION,
    REJECT_UNSUPPORTED_CLAIM: GateCode.PROSE_UNSUPPORTED_CLAIM,
    REJECT_CROSS_EMPLOYER: GateCode.PROSE_CROSS_EMPLOYER_EVIDENCE,
    REJECT_EVIDENCE_OUT_OF_SCOPE: GateCode.PROSE_EVIDENCE_OUT_OF_SCOPE,
    REJECT_NEW_FACTS: GateCode.PROSE_NEW_FACTS_DECLARED,
    REJECT_FACT_LOSS: GateCode.PROSE_FACT_LOSS,
    REJECT_WORD_GROWTH: GateCode.PROSE_WORD_GROWTH,
    REJECT_TEXT_UNCHANGED: GateCode.PROSE_TEXT_UNCHANGED,
}


def _prose_gate_code(reason: str) -> GateCode:
    """Map a prose-contract rejection reason to its stable diagnostics code."""
    return _PROSE_GATE_CODES[reason]


# See `_PRUNE_MIN_DENSITY_GAIN_RATIO` for the derivation of this figure: a
# relative gain of 0.5% is scale-free across fixtures with different numerators
# and implies a materially sized change (~5 words in a 1000-word document).
# Applied to the prose pass as a whole rather than to each rewrite -- see
# `_prose_improvement`.
_PROSE_MIN_DENSITY_GAIN_RATIO = 0.005


def _prose_regression(before: ScoreVector, after: ScoreVector) -> str:
    """Why this one rewrite is unsafe, or "" if it costs nothing.

    Applied per rewrite, and *stricter* than ``_pareto_verdict`` where the two
    differ: ``pramana_coverage`` may not fall at all rather than merely within
    tolerance, because coverage is what the resume is credited for and a
    re-wording has no business costing any of it. The other three objectives keep
    pareto's own regression tolerances, so a rewrite cannot quietly undo a
    placement or dilute the document.

    This is only the *no-harm* half of acceptance. Whether the rewriting was
    worth doing at all is ``_prose_improvement``'s question.
    """
    if after.pramana_coverage < before.pramana_coverage:
        return "rewrite would reduce PRAMANA coverage"
    if after.jd_surface_adoption < before.jd_surface_adoption - _ADOPTION_TOLERANCE:
        return "rewrite would reduce JD-surface adoption"
    if after.placement_reinforcement < before.placement_reinforcement - _PLACEMENT_TOLERANCE:
        return "rewrite would reduce placement reinforcement"
    if after.density < before.density - _DENSITY_TOLERANCE:
        return "rewrite would reduce density"
    if (
        after.word_count < before.word_count
        or after.pramana_coverage > before.pramana_coverage + _COVERAGE_TOLERANCE
        or after.jd_surface_adoption > before.jd_surface_adoption + _ADOPTION_TOLERANCE
        or after.placement_reinforcement > before.placement_reinforcement + _PLACEMENT_TOLERANCE
    ):
        return ""
    return (
        "rewrite changed wording without shortening the document or raising any objective, so it is pure "
        f"churn ({before.word_count} -> {after.word_count} words, density {before.density:.4f} -> "
        f"{after.density:.4f})"
    )


def _prose_improvement(before: ScoreVector, after: ScoreVector) -> str:
    """Why the whole prose pass was not worth keeping, or "" if it was.

    Judged on the accumulated pass rather than on each rewrite, and the reason is
    arithmetic rather than convenience. ``_pareto_verdict``'s density threshold is
    *absolute* (``_DENSITY_TOLERANCE`` = 0.02), sized for an additive action that
    makes one more canonical visible and moves density by roughly 0.1. Re-wording
    one twenty-five-word bullet inside a ~950-word document cannot move density
    by that much: with fifteen visible canonicals, clearing 0.02 would require
    shedding about twelve words from that one bullet, which no honest
    proposition-preserving rewrite can do. Measured on the real fixtures, the
    strict truth and fidelity gates leave a good rewrite one to four words of
    slack each.

    So per-rewrite the threshold is unmeetable, while the pass as a whole moves a
    real amount -- the same distinction ``_apply_reordering`` already draws when
    it judges every skill reorder as one candidate. Individual *safety* is still
    per rewrite (``_prose_regression`` plus the truth, fidelity, preservation,
    completeness, and ledger gates); only the "was this worth doing" verdict is
    taken on the accumulated result, and if it fails, the entire pass is
    discarded and the candidate's own wording is delivered.

    A pass qualifies on an integer-level improvement to coverage, adoption, or
    placement reinforcement (pareto's own thresholds, unchanged), or on concision:
    the document is genuinely shorter and density rose by a relative
    ``_PROSE_MIN_DENSITY_GAIN_RATIO``. Anything else is churn -- it makes the diff
    noisy and the ledger untrustworthy while buying the candidate nothing.
    """
    if (
        after.pramana_coverage > before.pramana_coverage + _COVERAGE_TOLERANCE
        or after.jd_surface_adoption > before.jd_surface_adoption + _ADOPTION_TOLERANCE
        or after.placement_reinforcement > before.placement_reinforcement + _PLACEMENT_TOLERANCE
    ):
        return ""
    if after.word_count < before.word_count and after.density >= before.density * (1.0 + _PROSE_MIN_DENSITY_GAIN_RATIO):
        return ""
    return (
        "the prose pass improved nothing measurable: no objective rose beyond its threshold and the document "
        f"did not concentrate by {_PROSE_MIN_DENSITY_GAIN_RATIO:.1%} "
        f"({before.density:.4f} -> {after.density:.4f}, {before.word_count} -> {after.word_count} words)"
    )


@dataclass(frozen=True, slots=True)
class _ProseTarget:
    """One field a prose rewrite may be proposed for."""

    operation: str
    target: str
    location_id: str
    original_text: str
    role_index: int
    bullet_index: int


# How many bullets one run will ask a model to re-word. A bound, not a target:
# every provider call is latency and cost, a resume has twenty of them, and the
# reader's attention is on the most relevant few. Six covers more than the most
# relevant role on every real fixture (their roles hold 2-5 bullets each) while
# keeping a run to at most 1 + 6 targets and therefore at most 14 provider
# calls, counting each target's one bounded repair.
_PROSE_MAX_BULLET_TARGETS = 6


def _prose_targets(plan: ResumePlan, profile: Profile, requirements: list[RequirementTerm]) -> list[_ProseTarget]:
    """The summary plus the most JD-relevant live bullets, in reading order.

    Bullets are addressed by their *source* index, matching the change-ledger id
    (``resume::expN::bulletM``) and every other index-keyed mechanism in the
    engine. Emptied slots are skipped: an accepted PRUNE already removed that
    content, and rewriting a removal would be incoherent.

    Only bullets that already express a JD requirement are candidates, ranked by
    how many distinct requirements they express. That is the inverse of the
    pruning screen, and deliberately so: pruning removes bullets with *no*
    relevance, rewriting sharpens the ones that carry it. A bullet that is not
    selected is not a rejection and records no gate -- it is simply not the kind
    of content this operation improves, exactly as ``pruning.screen_bullet``
    returning None is not a rejection.
    """
    targets: list[_ProseTarget] = []
    if profile.source_summary.strip() and plan.summary.strip():
        targets.append(
            _ProseTarget(
                operation=SUMMARY_REWRITE,
                target="resume:summary",
                location_id="resume::summary",
                original_text=plan.summary,
                role_index=-1,
                bullet_index=-1,
            )
        )
    canonicals = {requirement.canonical for requirement in requirements if requirement.canonical}
    ranked: list[tuple[int, int, int, _ProseTarget]] = []
    for role_index, entry in enumerate(plan.experience):
        for bullet_index, bullet in enumerate(entry.bullets):
            if not bullet.strip():
                continue
            hits = sum(1 for canonical in canonicals if contains_fact(bullet, canonical))
            if not hits:
                continue
            ranked.append(
                (
                    -hits,
                    role_index,
                    bullet_index,
                    _ProseTarget(
                        operation=BULLET_REWRITE,
                        target=f"experience:{role_index}:bullet:{bullet_index}",
                        location_id=f"resume::exp{role_index}::bullet{bullet_index}",
                        original_text=bullet,
                        role_index=role_index,
                        bullet_index=bullet_index,
                    ),
                )
            )
    # Most relevant first for selection, then back into reading order so the run
    # is reproducible and the ledger reads top-to-bottom.
    ranked.sort(key=lambda item: item[:3])
    selected = sorted(ranked[:_PROSE_MAX_BULLET_TARGETS], key=lambda item: (item[1], item[2]))
    targets.extend(item[3] for item in selected)
    return targets


def _shifted_by_pruning(target: _ProseTarget, removals: list[RemovedContent]) -> str:
    """Why this bullet must not be rewritten alongside an accepted prune, or "".

    **The finding this guard exists for.** ``PlacementAction`` addresses evidence
    positionally as ``experience:<i>:bullet:<j>``, and PRAMANA resolves that
    against the *re-parsed rendered document*
    (``pramana.scoring._experience_bullets``). No renderer emits an emptied
    bullet, so an accepted PRUNE at index k shifts the rendered index of every
    later bullet in that role down by one while the action still carries the
    source index. Measured directly: with three bullets and index 1 pruned, an
    action targeting ``experience:0:bullet:2`` resolves to ``None`` instead of the
    bullet it names.

    Two things follow, and they are different:

    * The shift is **not caused by rewriting**. A rewrite changes text, not the
      bullet count, so it cannot move any index. The shift is PRUNE's, it exists
      on ``main`` today, and it is latent rather than active: measured across all
      three real fixtures, no accepted bullet-targeted placement currently sits
      after a removal in its own role. ``_prune_verdict`` also refuses any
      removal that costs PRAMANA coverage, which is what a lost provenance
      resolution costs, so a shift that *matters* is already rejected there.
    * What the shift can still do is resolve a placement against the wrong
      bullet. Rewriting a bullet in that region would mean the engine editing one
      bullet while a placement is credited against another under the same
      address.

    The brief requires choosing: fix the interaction, or refuse to co-apply.
    Fixing it correctly means content-addressed placement provenance, which is a
    change to PRUNE and to the scorer's evidence resolution -- both explicitly
    out of scope for this step, and the same prerequisite that keeps bullet
    REORDER disabled. So this **refuses to co-apply**: a bullet whose rendered
    index has shifted is not rewritten, and the refusal is recorded under its own
    gate code rather than being silently skipped.
    """
    if target.operation != BULLET_REWRITE:
        return ""
    for item in removals:
        match = re.fullmatch(r"experience:(\d+):bullet:(\d+)", item.location)
        if match is None:
            continue
        role_index, bullet_index = int(match.group(1)), int(match.group(2))
        if role_index == target.role_index and bullet_index < target.bullet_index:
            return (
                f"an accepted prune at experience:{role_index}:bullet:{bullet_index} shifted this bullet's "
                "rendered index, so positional placement provenance would no longer address it"
            )
    return ""


def _delivered_texts(plan: ResumePlan) -> dict[str, str]:
    """What each citable field currently holds, keyed by evidence-node id."""
    delivered = {"summary": plan.summary}
    for role_index, entry in enumerate(plan.experience):
        for bullet_index, bullet in enumerate(entry.bullets):
            delivered[f"exp{role_index}:bullet{bullet_index}"] = bullet
    return delivered


def _with_prose(plan: ResumePlan, target: _ProseTarget, text: str) -> ResumePlan:
    """A copy of *plan* with *target*'s field replaced by *text*."""
    candidate = deepcopy(plan)
    if target.operation == SUMMARY_REWRITE:
        candidate.summary = text
    else:
        candidate.experience[target.role_index].bullets[target.bullet_index] = text
    return candidate


def _candidate_authored_text(profile: Profile, target: _ProseTarget) -> str:
    """The candidate's own wording for the field *target* names."""
    if target.operation == SUMMARY_REWRITE:
        return profile.source_summary
    if 0 <= target.role_index < len(profile.experiences):
        bullets = profile.experiences[target.role_index].bullets
        if 0 <= target.bullet_index < len(bullets):
            return bullets[target.bullet_index]
    return ""


def _prose_is_ledgered(
    candidate: ResumePlan,
    profile: Profile,
    target: _ProseTarget,
    accepted: list[PlacementAction],
) -> bool:
    """Whether the change ledger records this rewrite reversibly and visibly.

    Checked rather than assumed. ``kit.change_ledger`` builds every user-facing
    change from ``ResumePlan.plan_decisions``, and ``kit.change_actions`` restores
    a rejected rewrite from that record's ``original_text`` -- so a rewrite with
    no decision would be an *invisible, irreversible* edit to candidate-authored
    prose. That is the exact failure that got bullet sorting removed from
    ``_select_experience``, and the reason a rewrite the ledger cannot express is
    refused here rather than delivered.

    Two properties are required, and the second is the load-bearing one:

    * a decision exists for this location, carrying the rewritten text as what was
      delivered -- so the change is *visible*; and
    * its ``original_text`` is the **candidate's own authored wording**, not any
      intermediate and emphatically not the model's -- so the change is
      *reversible to something the candidate actually wrote*.

    The second is checked against the profile rather than against the text this
    rewrite replaced, because the ledger's own semantics are "restore what the
    candidate wrote", not "undo the last edit". A summary that already carries a
    targeting clause and accepted placement terms still reverts to the
    candidate's source summary, which is the correct behavior and the reason an
    earlier version of this check misfired on every fixture.
    """
    authored = _candidate_authored_text(profile, target)
    delivered = candidate_text_for(candidate, target)
    if not authored.strip():
        return False
    decisions = _v2_plan_decisions(candidate.plan_decisions, candidate, profile, accepted)
    for decision in decisions:
        if decision.location_id != target.location_id:
            continue
        return (
            decision.operation in {"rewritten", "added"}
            and decision.tailored_text.strip() == delivered.strip()
            and decision.original_text.strip() == authored.strip()
        )
    return False


def candidate_text_for(plan: ResumePlan, target: _ProseTarget) -> str:
    """Read back whatever *plan* currently holds at *target*."""
    if target.operation == SUMMARY_REWRITE:
        return plan.summary
    return plan.experience[target.role_index].bullets[target.bullet_index]


def _apply_prose_rewrites(
    plan: ResumePlan,
    *,
    profile: Profile,
    jd_profile: JDProfile,
    requirements: list[RequirementTerm],
    links: list[EvidenceLink],
    source: str,
    accepted: list[PlacementAction],
    objectives: ScoreVector,
    removals: list[RemovedContent],
    context: ResumeGateContext,
    guard: PreservationGuard,
    trace: OptimizationTrace,
    recorder: _ProposalRecorder,
    provider: LLMProvider,
    cache: ContentHashCache | None,
) -> tuple[ResumePlan, ScoreVector, list[str]]:
    """Propose an evidence-cited rewrite for each field, accepting one at a time.

    Same shape as ``_apply_pruning``, and for the same reason: one candidate at a
    time, each independently re-scored and re-validated, so a rejected rewrite
    can never discard unrelated accepted work and every refusal names the gate
    that fired. Model prose is untrusted text (``AGENTS.md`` §2), so a proposal
    that has already satisfied the structured contract still has to survive:

    * the deterministic truth gate (``kit.grounding.ground_text``) -- and here
      *any* repair counts as a rejection, because repaired prose is prose the
      gate had to edit, and an edited rewrite is not the rewrite that was cited;
    * ``_prose_regression``, so no accepted rewrite costs coverage, adoption,
      placement reinforcement, or density;
    * the preservation guard, the removal-aware completeness gate, and the full
      plan validation gate, i.e. exactly what the delivered document faces;
    * the change ledger, which must be able to express the rewrite reversibly.

    Then, once, the accumulated pass faces ``_prose_improvement``: if the
    rewriting bought nothing measurable, the whole pass is discarded and the
    candidate's own wording is delivered. See that function for why materiality is
    judged on the pass and safety per rewrite.

    Nothing is repaired, softened, or partially applied. Every failure leaves the
    candidate's own wording in place.
    """
    current = plan
    current_objectives = objectives
    labels: list[str] = []
    fact_set = build_fact_set(profile)
    accepted_ids: list[str] = []

    for target in _prose_targets(current, profile, requirements):
        original_text = candidate_text_for(current, target)
        # Rebuilt per target rather than once, so a node reflects any rewrite
        # already accepted in this pass. A stale graph would let a later rewrite
        # cite text no longer on the page.
        nodes: tuple[EvidenceNode, ...] = build_evidence_nodes(profile, _delivered_texts(current))
        blocked = _shifted_by_pruning(target, removals)
        if blocked:
            trace.rejected_actions.append(
                _rejection(
                    action=f"{target.operation}:{target.target}",
                    reason=blocked,
                    code=GateCode.PROSE_PRUNE_INDEX_SHIFT,
                )
            )
            recorder.record_prose(
                operation=target.operation,
                target=target.target,
                attempt=0,
                status=ProposalStatus.REJECTED,
                code=GateCode.PROSE_PRUNE_INDEX_SHIFT,
                detail=blocked,
                cited=(),
                proposed_text="",
                word_delta=0,
            )
            continue

        if target.operation == SUMMARY_REWRITE:
            outcome = propose_summary_rewrite(
                provider,
                original_text=original_text,
                profile=profile,
                requirements=requirements,
                target_title=jd_profile.title,
                nodes=nodes,
                fact_set=fact_set,
                cache=cache,
            )
        else:
            outcome = propose_bullet_rewrite(
                provider,
                role_index=target.role_index,
                bullet_index=target.bullet_index,
                original_text=original_text,
                profile=profile,
                requirements=requirements,
                nodes=nodes,
                fact_set=fact_set,
                cache=cache,
            )
        _record_prose_attempts(recorder, target, outcome)
        proposal = outcome.proposal
        if proposal is None:
            _reject_prose(trace, target, outcome.rejection)
            continue

        candidate = _with_prose(current, target, proposal.proposed_text)
        verdict = _prose_document_verdict(
            candidate,
            current=current,
            profile=profile,
            requirements=requirements,
            links=links,
            source=source,
            accepted=accepted,
            objectives=current_objectives,
            removals=removals,
            context=context,
            guard=guard,
            target=target,
        )
        cited = proposal.cited_node_ids()
        word_delta = _word_count(proposal.proposed_text) - _word_count(original_text)
        if verdict.code is not None:
            trace.rejected_actions.append(
                _rejection(
                    action=f"{target.operation}:{target.target}",
                    reason=verdict.detail,
                    code=verdict.code,
                )
            )
            recorder.record_prose(
                operation=target.operation,
                target=target.target,
                attempt=len(outcome.attempts),
                status=ProposalStatus.REJECTED,
                code=verdict.code,
                detail=verdict.detail,
                cited=cited,
                proposed_text=proposal.proposed_text,
                word_delta=word_delta,
                objectives_before=current_objectives,
                objectives_after=verdict.objectives,
            )
            continue

        recorder.record_prose(
            operation=target.operation,
            target=target.target,
            attempt=len(outcome.attempts),
            status=ProposalStatus.ACCEPTED,
            code=None,
            detail=f"cited {', '.join(cited)}",
            cited=cited,
            proposed_text=proposal.proposed_text,
            word_delta=word_delta,
            objectives_before=current_objectives,
            objectives_after=verdict.objectives,
        )
        accepted_ids.append(f"{target.operation}:{target.target}:attempt{len(outcome.attempts)}")
        current = candidate
        if verdict.objectives is not None:
            current_objectives = verdict.objectives
        labels.append(f"{target.operation}:{target.target}")

    if not labels:
        return plan, objectives, []
    churn = _prose_improvement(objectives, current_objectives)
    if churn:
        # The pass bought nothing. Discard all of it and demote every record from
        # ACCEPTED so the diagnostics never claim a change the reader will not
        # see -- the same honesty rule `reclassify_no_ops` enforces for
        # weave_bullet.
        for label in labels:
            trace.rejected_actions.append(_rejection(action=label, reason=churn, code=GateCode.PROSE_NO_OBJECTIVE_GAIN))
        for record_id in accepted_ids:
            recorder.records[record_id] = replace(
                recorder.records[record_id],
                status=ProposalStatus.REJECTED,
                gate_code=GateCode.PROSE_NO_OBJECTIVE_GAIN,
                gate_detail=churn,
            )
        return plan, objectives, []
    return current, current_objectives, labels


def _record_prose_attempts(recorder: _ProposalRecorder, target: _ProseTarget, outcome: ProseOutcome) -> None:
    """Record every *failed* contract attempt, so a refused model proposal is visible.

    The accepted (or document-gate-rejected) attempt is recorded by the caller
    with its objective deltas attached, so it is skipped here to keep exactly one
    terminal record per attempt.
    """
    for attempt in outcome.attempts:
        if attempt.rejection is None:
            continue
        recorder.record_prose(
            operation=target.operation,
            target=target.target,
            attempt=attempt.index,
            status=ProposalStatus.REJECTED,
            code=_prose_gate_code(attempt.rejection.reason),
            detail=attempt.rejection.detail,
            cited=(),
            proposed_text=attempt.proposed_text,
            word_delta=0,
        )


def _reject_prose(trace: OptimizationTrace, target: _ProseTarget, rejection: ProseRejection | None) -> None:
    if rejection is None:
        return
    trace.rejected_actions.append(
        _rejection(
            action=f"{target.operation}:{target.target}",
            reason=rejection.detail,
            code=_prose_gate_code(rejection.reason),
        )
    )


@dataclass(frozen=True, slots=True)
class _ProseVerdict:
    """The document-level outcome for one contract-valid prose proposal."""

    code: GateCode | None
    detail: str
    objectives: ScoreVector | None


def _prose_document_verdict(
    candidate: ResumePlan,
    *,
    current: ResumePlan,
    profile: Profile,
    requirements: list[RequirementTerm],
    links: list[EvidenceLink],
    source: str,
    accepted: list[PlacementAction],
    objectives: ScoreVector,
    removals: list[RemovedContent],
    context: ResumeGateContext,
    guard: PreservationGuard,
    target: _ProseTarget,
) -> _ProseVerdict:
    """Run every delivered-document gate against a rewritten candidate."""
    proposed = candidate_text_for(candidate, target)
    grounding = ground_text(
        proposed,
        artifact=ArtifactKind.RESUME,
        context=build_evidence_context(profile, candidate.jd_profile),
        id_prefix=f"prose-{target.operation}",
        granularity="prose" if target.operation == SUMMARY_REWRITE else "span",
    )
    if grounding.fatal or grounding.repaired or grounding.rejected:
        return _ProseVerdict(
            code=GateCode.PROSE_TRUTH_GATE_REJECTION,
            detail="truth gate found an unsupported candidate-specific claim in the rewritten text",
            objectives=None,
        )

    evaluation = _evaluate_plan(candidate, source, requirements, links, accepted)
    regression = _prose_regression(objectives, evaluation.objectives)
    if regression:
        return _ProseVerdict(code=GateCode.PROSE_NO_OBJECTIVE_GAIN, detail=regression, objectives=evaluation.objectives)

    candidate_text = generate_resume_text(candidate)
    regressions = guard.regressions(candidate_text)
    if regressions:
        return _ProseVerdict(
            code=GateCode.PROSE_PROTECTED_FACT_LOSS,
            detail=regressions[0].describe(),
            objectives=evaluation.objectives,
        )
    completeness = resume_completeness_errors(candidate_text, profile, removals)
    if completeness:
        return _ProseVerdict(
            code=GateCode.PROSE_VALIDATION_FINDING, detail=completeness[0], objectives=evaluation.objectives
        )
    findings = _optimization_blockers(
        validate_resume_plan_findings(candidate, profile, requirements, accepted, context)
    )
    if findings:
        return _ProseVerdict(
            code=GateCode.PROSE_VALIDATION_FINDING,
            detail=_finding_reason(findings),
            objectives=evaluation.objectives,
        )
    if not _prose_is_ledgered(candidate, profile, target, accepted):
        return _ProseVerdict(
            code=GateCode.PROSE_UNLEDGERED_REWRITE,
            detail=(
                f"the change ledger cannot express this rewrite reversibly at {target.location_id}, "
                "so it would be an invisible edit to candidate-authored prose"
            ),
            objectives=evaluation.objectives,
        )
    if generate_resume_text(current) == candidate_text:
        return _ProseVerdict(
            code=GateCode.PROSE_TEXT_UNCHANGED,
            detail="rewrite produced an identical delivered document",
            objectives=evaluation.objectives,
        )
    return _ProseVerdict(code=None, detail="", objectives=evaluation.objectives)


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
