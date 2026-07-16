from __future__ import annotations

from ats_engine.kit.contract import OutreachFormat

"""Central product policy for concise outreach drafts.

These are ATS-Ninja product limits, not claims about LinkedIn's current
platform limits. Keeping them here prevents format limits from becoming
scattered magic numbers.
"""

OUTREACH_LENGTH_LIMITS: dict[OutreachFormat, int] = {
    OutreachFormat.CONNECTION_NOTE: 300,
    OutreachFormat.DIRECT_MESSAGE: 700,
    OutreachFormat.FOLLOW_UP: 600,
    OutreachFormat.REFERRAL_REQUEST: 600,
}

STRATEGY_SUMMARY_LIMIT = 420


def character_limit(format_: OutreachFormat) -> int:
    """Return the configured product limit for a draft format."""
    return OUTREACH_LENGTH_LIMITS[format_]
