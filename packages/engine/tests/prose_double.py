"""A deterministic fake prose provider for the evidence-cited rewrite operations.

``AGENTS.md`` §5 forbids a test that needs a running model server, so the prose
path is exercised with a scripted double. The double is deliberately *not* a
generic "return whatever the test wants" mock. It reads the target field out of
the prompt's own untrusted-data block and applies hand-authored concision edits
to *that text*, so what it proposes is derived from the real delivered document
rather than pinned to a literal string. That matters for more than tidiness: by
the time prose runs, the summary carries a targeting clause and accepted
``mention_summary`` terms, and several bullets carry ``surface_variant``
substitutions, so a content-keyed double would silently propose nothing on
exactly the fixtures where the interesting interactions live.

Every edit in :data:`CONCISION_EDITS` was authored to the same rules the prompt
gives a model, then checked against the real validator: shorter than its source,
every checkable token retained, one employer per claim, cited to the node that
actually holds the text. Nothing here is tuned to slip past a gate -- an edit that
failed validation was either corrected until it was *truthful* or dropped. Two
were dropped for genuine reasons worth recording:

* ``third-party vendor applications`` -> ``vendor applications`` removed a literal
  JD surface form and was refused for reducing ``jd_surface_adoption``;
* ``complex business logic`` -> ``business logic`` shortened a bullet that already
  carried three targeted placements and was refused by the per-bullet stuffing
  budget.

The identity follows the corrected test-double pattern (a fresh ``uuid4`` per
instance, never ``id(self)``): the disk cache is keyed on
``(provider.identity, prompt)``, and ``id()`` is unique only among *live*
objects, so a collected double's address can be handed to a later one and serve
it a stale cached reply.
"""

from __future__ import annotations

import json
import re
from uuid import uuid4

# The closing sentence of the fixture resume's own summary. Pure self-assessment:
# it states nothing an employer can check and no JD term the rest of the document
# does not already carry, which is why dropping it is a legitimate concision edit
# rather than content loss. Matched as a whole sentence so a partial match can
# never leave a fragment behind.
SUMMARY_FILLER_SENTENCE = (
    "Strong communicator across technical and non- technical audiences, with a track record of end-to-end "
    "ownership and shipping measurable business impact."
)

# Wordy phrasing -> the same proposition, said shorter. Applied in order, all
# matches, to whatever text the prompt supplies.
CONCISION_EDITS: tuple[tuple[str, str], ...] = (
    (
        " enabling non-technical stake-holders to query ",
        " so non-technical stake-holders query ",
    ),
    (
        "dashboards, reducing manual reporting overhead by ",
        "dashboards, cutting manual reporting overhead ",
    ),
    (
        "teams to translate business requirements",
        "teams, translating business requirements",
    ),
    (
        "aligned with SDLC best practices",
        "aligned with SDLC practices",
    ),
    (
        "Led a team of four engineers maintaining and evolving ",
        "Led a team of four engineers evolving ",
    ),
    (
        ", owning requirements, solution design, and backlog management",
        ", owning requirements, design, and backlog",
    ),
    (
        ", handling multi-language, multi-region, and transactional complexity",
        ", handling multi-language and transactional complexity",
    ),
    (
        "reporting, directly supporting community-safety operations",
        "reporting that supports community-safety operations",
    ),
    (
        "reporting systems to enhance safety",
        "reporting that raised safety",
    ),
    (
        ", unifying heterogeneous data sources into a single reliable analytics layer",
        " into one reliable analytics layer",
    ),
    (
        "through DevOps practices, maintaining ",
        "through DevOps, maintaining ",
    ),
    (
        "Auth Proxy, configuring secure communication between services",
        "Auth Proxy, configuring secure service communication",
    ),
)

# Claim type per operation. A bullet states what was done; a summary states who
# the candidate is. Both are in `prose.CLAIM_TYPES`.
_CLAIM_TYPES = {"summary_rewrite": "role_identity", "bullet_rewrite": "responsibility"}

_FENCE = r"<<<UNTRUSTED:{label}>>>\n(.*?)\n<<<UNTRUSTED:END:{label}>>>"


def untrusted_field(prompt: str, label: str) -> str:
    """Read one fenced untrusted block back out of a prose prompt."""
    match = re.search(_FENCE.format(label=label), prompt, re.DOTALL)
    return match.group(1) if match else ""


def contract_of(prompt: str) -> dict[str, str]:
    """The versioned contract line the prompt carries (also its cache identity)."""
    if "CONTRACT: " not in prompt:
        return {}
    parsed = json.loads(prompt.split("CONTRACT: ", 1)[1].split("\n", 1)[0])
    return {str(key): str(value) for key, value in parsed.items()}


def node_id_for(target_id: str) -> str:
    """The evidence node that holds the field a target names."""
    match = re.fullmatch(r"experience:(\d+):bullet:(\d+)", target_id)
    if match is not None:
        return f"exp{match.group(1)}:bullet{match.group(2)}"
    return "summary"


def condense(text: str, *, is_summary: bool) -> str:
    """Apply every applicable concision edit, or return "" if none apply."""
    result = text
    if is_summary and SUMMARY_FILLER_SENTENCE in result:
        result = re.sub(r"\s*" + re.escape(SUMMARY_FILLER_SENTENCE), "", result).strip()
    for wordy, tighter in CONCISION_EDITS:
        result = result.replace(wordy, tighter)
    result = re.sub(r"\s+", " ", result).strip()
    return "" if result == re.sub(r"\s+", " ", text).strip() else result


class ScriptedProseProvider:
    """Proposes a concision rewrite of whatever field the prompt names."""

    def __init__(self, *, response_for: dict[str, str] | None = None) -> None:
        # `response_for` overrides the reply for one target id, so a test can
        # script an adversarial or malformed proposal for a specific field while
        # every other field keeps behaving normally.
        self.response_for = dict(response_for or {})
        self._identity = f"scripted-prose:{uuid4().hex}"
        self.calls = 0
        self.prompts: list[str] = []

    @property
    def identity(self) -> str:
        return self._identity

    def complete(self, prompt: str) -> str:
        self.calls += 1
        self.prompts.append(prompt)
        contract = contract_of(prompt)
        if not contract:
            # Not a prose prompt. The legacy summary/bullet generation path also
            # runs when a provider is present; returning "" keeps it deterministic.
            return ""
        operation, target = contract["operation"], contract["target_id"]
        if target in self.response_for:
            return self.response_for[target]
        is_summary = operation == "summary_rewrite"
        source = untrusted_field(prompt, "SOURCE_SUMMARY" if is_summary else "SOURCE_BULLET")
        text = condense(source, is_summary=is_summary)
        if not text:
            return ""
        return proposal_json(
            operation=operation,
            target=target,
            text=text,
            claim_type=_CLAIM_TYPES[operation],
            cites=[node_id_for(target)],
        )


def proposal_json(
    *,
    operation: str,
    target: str,
    text: str,
    claim_type: str,
    cites: list[str],
    claim_text: str | None = None,
    new_facts: list[str] | None = None,
) -> str:
    """Build one contract-shaped reply, for the double and for adversarial tests."""
    return json.dumps(
        {
            "operation": operation,
            "target_id": target,
            "proposed_text": text,
            "claims": [
                {
                    "text": claim_text if claim_text is not None else text,
                    "claim_type": claim_type,
                    "evidence_node_ids": cites,
                }
            ],
            "preserved_facts": [],
            "new_facts": list(new_facts or []),
        }
    )


__all__ = [
    "CONCISION_EDITS",
    "SUMMARY_FILLER_SENTENCE",
    "ScriptedProseProvider",
    "condense",
    "contract_of",
    "node_id_for",
    "proposal_json",
    "untrusted_field",
]
