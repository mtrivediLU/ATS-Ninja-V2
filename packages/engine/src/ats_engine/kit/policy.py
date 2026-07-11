from __future__ import annotations

from ats_engine.kit.contract import ClaimType

"""Repair-vs-rejection policy for unsupported generated claims (Phase 2A).

This module is the single, explicit statement of what happens to a candidate
claim that generated prose asserts but the candidate's evidence does not
support. The guiding rule (see AGENTS.md and ADR-0011):

    The safest product behavior wins over ATS keyword gain. A fabricated
    identity/history fact is never softened into acceptance merely because the
    wording changed — it is removed from the artifact or the artifact is
    withheld.

Two mechanisms exist, both deterministic and both bounded (no LLM
"retry-until-it-looks-right" loop):

- **Repair (removal).** The offending claim is deterministically excised from the
  artifact so the fabricated value is *absent* from the final output. This is the
  default for every unsupported candidate-specific claim: removal cannot make a
  fabrication survive, so it is always safe.
- **Rejection.** If removal cannot eliminate the fabricated value (e.g. it is
  entangled such that a single pass still leaves it detectable), the artifact is
  withheld and the kit is marked fatally invalid.

Style-only defects (cliche wording) are handled earlier and separately by the
deterministic style softener; they are not fabrications and never gate delivery.

Bounded regeneration: grounding performs a single deterministic repair pass and
then re-verifies. There is no unbounded regeneration cycle.
"""

# Every candidate-specific claim category is fabrication-sensitive: an
# unsupported instance is removed from the artifact (and, if it cannot be
# removed cleanly, the artifact is rejected). None of these may be "softened"
# into acceptance. This set is exhaustive over ClaimType by design — adding a new
# ClaimType without listing it here is a policy gap the tests guard against.
REMOVE_OR_REJECT: frozenset[ClaimType] = frozenset(
    {
        ClaimType.EMPLOYER,
        ClaimType.TITLE,
        ClaimType.SKILL,
        ClaimType.METRIC,
        ClaimType.MONETARY,
        ClaimType.TEAM_SIZE,
        ClaimType.MANAGEMENT,
        ClaimType.TENURE,
        ClaimType.CERTIFICATION,
        ClaimType.EDUCATION,
    }
)

# A single deterministic repair pass. Grounding removes offending content once,
# then re-verifies; anything still detectable escalates to rejection.
MAX_REPAIR_PASSES = 1

# If repairing a required prose artifact removes so much that what remains is not
# a usable artifact, it is treated as rejected rather than shipped as a husk.
MIN_COVER_LETTER_WORDS = 40


def is_fabrication_sensitive(claim_type: ClaimType) -> bool:
    """True when an unsupported claim of this type must be removed or rejected."""
    return claim_type in REMOVE_OR_REJECT
