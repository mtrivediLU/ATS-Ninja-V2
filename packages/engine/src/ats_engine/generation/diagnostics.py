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
