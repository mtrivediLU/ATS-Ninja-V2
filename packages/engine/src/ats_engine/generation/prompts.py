from __future__ import annotations

"""Evidence-bound prompt contract (Phase 2A, Step 10).

Prompts are a *generation constraint*, not the enforcement mechanism — the
deterministic grounding gate (:mod:`ats_engine.kit.grounding`) is what actually
guarantees no fabricated claim reaches the final ApplicationKit. Still, telling
the model the exact evidence boundary and the exact prohibited inventions makes
it produce clean prose far more often, so fewer artifacts need repair.

This module centralizes that boundary text so every prose prompt states the same
contract, and so it can be asserted structurally in tests rather than snapshotted
as one giant string. It intentionally lives under ``generation`` (a leaf with no
engine dependencies) so the generation layer never imports the ``kit`` package.
"""

# The categories the model must never invent. This mirrors, one-to-one, the
# fabrication-sensitive claim types the grounding gate enforces
# (ats_engine.kit.policy.REMOVE_OR_REJECT), so the prompt promises exactly what
# the validator enforces.
PROHIBITED_INVENTIONS: tuple[str, ...] = (
    "employers or companies",
    "job titles or seniority levels",
    "projects or clients",
    "skills or tools not in the candidate evidence",
    "metrics, percentages, or counts",
    "dollar values",
    "team sizes or headcount managed",
    "dates or length of tenure",
    "certifications",
    "degrees or education",
    "awards",
)

PROHIBITED_INVENTION_CLAUSE = (
    "Ground every candidate-specific claim strictly in the provided evidence. "
    "Do NOT invent any of the following unless they are already present in the "
    "candidate evidence (or explicitly permitted by the adjacency policy): "
    + "; ".join(PROHIBITED_INVENTIONS)
    + ". If the evidence does not support a claim, omit it rather than inventing it."
)


def evidence_boundary_clause() -> str:
    """Return the shared prohibited-invention clause for prose prompts."""
    return PROHIBITED_INVENTION_CLAUSE
