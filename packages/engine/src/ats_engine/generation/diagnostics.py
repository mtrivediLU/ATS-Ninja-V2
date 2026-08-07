"""Structured, deterministic diagnostics for Tailoring Engine proposals.

``relevant_terms_per_100_words`` is a measurement only.  It is the number of
distinct requirement canonicals visibly expressed in a text divided by its word
count per 100 words; it is never an optimizer acceptance input.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType


def _word_count(text: str) -> int:
    """Count words consistently across proposal and run-level diagnostics."""
    return len(re.findall(r"\b\w+\b", text))


class ProposalStatus(StrEnum):
    """Terminal disposition of one planner-emitted placement proposal."""

    ACCEPTED = "accepted"
    # Evaluated, applied, and provably changed no delivered text. Distinct from
    # ACCEPTED so an operation that cannot alter the document is never counted
    # as a change to it (see WEAVE_BULLET_OPERATION in generation.optimizer).
    NO_OP = "no_op"
    REJECTED = "rejected"
    ROLLED_BACK = "rolled_back"
    SUPERSEDED = "superseded"
    NOT_EVALUATED = "not_evaluated"


class GateCode(StrEnum):
    """Stable codes for the rejection sites in ``generation.optimizer``."""

    SCORE_DID_NOT_STRICTLY_IMPROVE = "score_did_not_strictly_improve"
    PROTECTED_FACT_LOSS = "protected_fact_loss"
    VALIDATION_FINDING = "validation_finding"
    NATURALNESS_STYLE_REJECTION = "naturalness_style_rejection"
    STUFFING = "stuffing"
    FINAL_PLAN_SCORE_REGRESSION = "final_plan_score_regression"
    SOURCE_PROJECTION_FAILURE = "source_projection_failure"
    QUALITY_SCORE_REGRESSION = "quality_score_regression"
    TRUTH_GATE_REJECTION = "truth_gate_rejection"
    RUN_CONCLUDED_BEFORE_EVALUATION = "run_concluded_before_evaluation"
    # SURFACE_VARIANT's three fail-closed causes (rachana.operations).
    SURFACE_VARIANT_SUBSTRING_HAZARD = "surface_variant_substring_hazard"
    SURFACE_VARIANT_FACT_RISK = "surface_variant_fact_risk"
    SURFACE_VARIANT_TEXT_DRIFTED = "surface_variant_text_drifted"
    # PRUNE's fail-closed causes (rachana.pruning). One per distinct
    # protection, so the benchmark histogram names which one held.
    PRUNE_UNIQUE_EVIDENCE = "prune_unique_evidence"
    PRUNE_PROTECTED_FACT = "prune_protected_fact"
    PRUNE_UNEVIDENCED_ENTITY = "prune_unevidenced_entity"
    PRUNE_ROLE_FLOOR = "prune_role_floor"
    PRUNE_NO_DENSITY_GAIN = "prune_no_density_gain"
    PRUNE_COVERAGE_REGRESSION = "prune_coverage_regression"
    PRUNE_COMPLETENESS_VIOLATION = "prune_completeness_violation"
    # SUMMARY_REWRITE / BULLET_REWRITE (rachana.prose). One code per distinct
    # refusal so the histogram shows what the model proposed and what refused
    # it, rather than a single opaque "prose rejected" bucket. The first group
    # is the structured contract; the second is this engine's ordinary
    # document-level gates applied to a rewritten field.
    PROSE_PROVIDER_UNAVAILABLE = "prose_provider_unavailable"
    PROSE_MALFORMED_RESPONSE = "prose_malformed_response"
    PROSE_SCHEMA_VIOLATION = "prose_schema_violation"
    PROSE_UNKNOWN_EVIDENCE_NODE = "prose_unknown_evidence_node"
    PROSE_MISSING_CITATION = "prose_missing_citation"
    PROSE_UNSUPPORTED_CLAIM = "prose_unsupported_claim"
    PROSE_CROSS_EMPLOYER_EVIDENCE = "prose_cross_employer_evidence"
    PROSE_EVIDENCE_OUT_OF_SCOPE = "prose_evidence_out_of_scope"
    PROSE_NEW_FACTS_DECLARED = "prose_new_facts_declared"
    PROSE_FACT_LOSS = "prose_fact_loss"
    PROSE_WORD_GROWTH = "prose_word_growth"
    PROSE_TEXT_UNCHANGED = "prose_text_unchanged"
    PROSE_NO_OBJECTIVE_GAIN = "prose_no_objective_gain"
    PROSE_TRUTH_GATE_REJECTION = "prose_truth_gate_rejection"
    PROSE_VALIDATION_FINDING = "prose_validation_finding"
    PROSE_PROTECTED_FACT_LOSS = "prose_protected_fact_loss"
    PROSE_UNLEDGERED_REWRITE = "prose_unledgered_rewrite"
    PROSE_PRUNE_INDEX_SHIFT = "prose_prune_index_shift"


@dataclass(frozen=True, slots=True)
class ProposalRecord:
    """One deterministic proposal inventory item and its final disposition."""

    id: str
    operation: str
    target: str
    requirement_canonicals: tuple[str, ...]
    requirement_weight: float
    evidence_tier: str
    evidence_locations: tuple[str, ...]
    surface_to_use: str
    word_delta: int
    status: ProposalStatus
    gate_code: GateCode | None
    gate_detail: str
    score_before: float | None
    score_after: float | None
    score_delta: float | None
    batch_index: int
    iteration: int
    # Additive (Step 3): the pareto policy's own objective deltas for this
    # proposal, in ats_engine.rachana.objectives.ScoreVector units. Plain
    # floats rather than a ScoreVector -- that module imports _word_count
    # from here, so importing it back would be circular. None on every
    # proposal never evaluated under the pareto policy (legacy runs, or a
    # proposal a batch never reached), never a fabricated zero.
    coverage_delta: float | None = None
    adoption_delta: float | None = None
    density_delta: float | None = None
    # Additive (Step 3 follow-up): placement_reinforcement's own delta, kept
    # alongside the three above rather than folded in, for the same reason
    # they are three separate fields rather than one -- a reviewer auditing
    # why a proposal was accepted needs to see which objective actually moved.
    placement_delta: float | None = None


@dataclass(frozen=True, slots=True)
class RunDiagnostics:
    """Aggregate, persistable measurements for one optimizer run."""

    proposals: tuple[ProposalRecord, ...]
    proposals_by_status: Mapping[str, int]
    rejections_by_gate: Mapping[str, int]
    accepted_by_operation: Mapping[str, int]
    source_word_count: int
    delivered_word_count: int
    word_delta: int
    relevant_terms_per_100_words_before: float
    relevant_terms_per_100_words_after: float
    score_path: tuple[float, ...]
    iterations: int
    source_projection_sha256: str = ""
    delivered_sha256: str = ""
    # Additive (Step 3): run-level before/after for the pareto policy's other
    # two objectives (density's before/after already exists above as
    # relevant_terms_per_100_words_*). 0.0 on a legacy run or a persisted kit
    # from before this field existed -- indistinguishable from "measured and
    # flat," which is why these are reported alongside, not instead of, the
    # per-proposal deltas above.
    pramana_coverage_before: float = 0.0
    pramana_coverage_after: float = 0.0
    jd_surface_adoption_before: float = 0.0
    jd_surface_adoption_after: float = 0.0
    # Additive (Step 3 follow-up): run-level before/after for the fourth
    # pareto objective, placement_reinforcement (see ats_engine.rachana.objectives).
    placement_reinforcement_before: float = 0.0
    placement_reinforcement_after: float = 0.0
    # Additive (pruning step): every bullet an accepted PRUNE removed, as
    # (location, original_text) pairs. Kept verbatim rather than counted so a
    # reviewer can judge each removal on its merits without re-running the
    # engine, which is the whole basis on which subtraction is auditable.
    removals: tuple[tuple[str, str], ...] = ()

    @classmethod
    def empty(cls) -> RunDiagnostics:
        """Return the compatibility default for persisted pre-diagnostics kits."""
        empty: Mapping[str, int] = MappingProxyType({})
        return cls(
            proposals=(),
            proposals_by_status=empty,
            rejections_by_gate=empty,
            accepted_by_operation=empty,
            source_word_count=0,
            delivered_word_count=0,
            word_delta=0,
            relevant_terms_per_100_words_before=0.0,
            relevant_terms_per_100_words_after=0.0,
            score_path=(),
            iterations=0,
        )


__all__ = ["GateCode", "ProposalRecord", "ProposalStatus", "RunDiagnostics"]
