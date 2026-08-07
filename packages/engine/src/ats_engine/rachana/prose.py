"""The evidence-cited prose contract: what a model may propose, and what proves it.

Every earlier RACHANA operation is deterministic. This one lets a language model
author candidate-facing prose, which makes it the highest-risk operation in the
engine. ``AGENTS.md`` §2 is explicit that inventing an employer, metric, skill,
or title to score better is a product-defining failure. Zero fabrication is
therefore not one objective among several here -- it is the precondition, and
this module is where it is *proved* rather than requested.

Three ideas do the work.

**1. Node-addressed evidence.** The engine issues a closed set of evidence nodes
(:func:`build_evidence_nodes`) with stable ids, each carrying its own text and
its own employer. The model may only cite ids from that set; a citation the
engine did not issue is a rejection. This is what makes "cite your evidence"
checkable instead of decorative -- an instruction smuggled into a job posting
has no node to point at.

**2. Transitive token coverage.** Per-clause citation would be theatre if a
model could return one trivially-cited claim plus arbitrary uncited prose
alongside it, so two containments are checked, and together they ground the
whole proposal:

* every checkable token in each *claim* must appear in the union of that
  claim's own cited nodes -- so a claim cannot say more than its evidence, and
* every checkable token in the *proposed text* must appear in some claim -- so
  the proposal cannot say more than its claims.

"Checkable token" is deliberately the same notion the rest of the engine uses
(:mod:`ats_engine.rachana.facts`, :mod:`ats_engine.parsing.vocab`): vocabulary
canonicals, metrics, team sizes, credential ids, the candidate's own immutable
facts, and mid-sentence proper nouns. Nothing here is a similarity score.

**3. Fail closed to the source text.** Every function below returns a
:class:`ProseRejection` rather than a repaired guess. Repair is removal, per
``AGENTS.md`` §2, and for a whole-field rewrite removal means restoring the
candidate's own wording exactly. There is no partial acceptance.

Cross-employer blending is impossible by the same mechanism rather than by
review: a claim's cited nodes must all carry the same employer, so two
individually true facts from two different jobs cannot be combined into one
statement. A ``BULLET_REWRITE`` is additionally confined to nodes inside its own
role, which is how the same-bullet restriction is relaxed to same-role without
relaxing anything else.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ats_engine.generation.prompts import (
    PROHIBITED_INVENTION_CLAUSE,
    UNTRUSTED_DATA_CLAUSE,
    untrusted_block,
)
from ats_engine.models import Profile, RequirementTerm
from ats_engine.parsing.vocab import VOCAB_VERSION, find_vocabulary_matches
from ats_engine.rachana.facts import (
    ImmutableFactSet,
    build_fact_set,
    extract_credential_ids,
    extract_metrics,
    extract_proper_nouns,
    extract_team_facts,
)
from ats_engine.validation.fidelity import (
    FIDELITY_DETECTOR_VERSION,
    bullet_fidelity_errors,
    contains_fact,
)
from ats_engine.validation.stuffing import STUFFING_DETECTOR_VERSION

# --------------------------------------------------------------------------- #
# Versions that participate in the cache key (see `prose_cache_identity`)
# --------------------------------------------------------------------------- #
# The shape of the prompt and of the JSON the model must return.
PROMPT_CONTRACT_VERSION = "prose-contract/1"
# How `build_evidence_nodes` derives node ids and node scope. A cached rewrite
# citing `exp3:bullet1` is meaningless if that id later names other content.
EVIDENCE_GRAPH_VERSION = "prose-evidence-graph/1"
# The requirement model the JD side of the prompt is built from.
REQUIREMENT_MODEL_VERSION = VOCAB_VERSION
# Every validator whose verdict a cached proposal was admitted under. Composed
# from the detectors' own published versions plus this module's rule set, so
# tightening any one of them invalidates previously cached proposals.
VALIDATOR_POLICY_VERSION = f"prose-validators/1+{FIDELITY_DETECTOR_VERSION}+{STUFFING_DETECTOR_VERSION}"

SUMMARY_REWRITE = "summary_rewrite"
BULLET_REWRITE = "bullet_rewrite"

# The claim types a model may declare. A closed set, because an open one lets a
# model label a fabrication into a category no gate happens to check.
CLAIM_TYPES: frozenset[str] = frozenset(
    {
        "skill",
        "responsibility",
        "outcome",
        "scope",
        "role_identity",
        "domain",
        "tenure",
    }
)

# Rejection reasons. Each maps 1:1 to a GateCode in generation.diagnostics so a
# reviewer reading the benchmark histogram can see exactly what refused a model
# proposal, and what the model had proposed when it did.
REJECT_NO_PROVIDER = "prose_provider_unavailable"
REJECT_MALFORMED = "prose_malformed_response"
REJECT_SCHEMA = "prose_schema_violation"
REJECT_UNKNOWN_NODE = "prose_unknown_evidence_node"
REJECT_MISSING_CITATION = "prose_missing_citation"
REJECT_UNSUPPORTED_CLAIM = "prose_unsupported_claim"
REJECT_CROSS_EMPLOYER = "prose_cross_employer_evidence"
REJECT_EVIDENCE_OUT_OF_SCOPE = "prose_evidence_out_of_scope"
REJECT_NEW_FACTS = "prose_new_facts_declared"
REJECT_FACT_LOSS = "prose_fact_loss"
REJECT_WORD_GROWTH = "prose_word_growth"
REJECT_TEXT_UNCHANGED = "prose_text_unchanged"

# A summary rewrite has to stay a summary. Bounds sized from the real fixtures,
# whose source summary is 103 words: below the floor the rewrite has dropped
# substance rather than re-expressed it, and the ceiling is the source's own
# length (see `_word_budget`), never more.
MIN_SUMMARY_WORDS = 30

# Employer-neutral nodes (skills, certifications, the summary itself) carry no
# role, so they can never conflict with another node's employer.
NEUTRAL_ROLE_INDEX = -1


@dataclass(frozen=True, slots=True)
class EvidenceNode:
    """One citable unit of candidate evidence with a stable id.

    ``employer`` is ``""`` and ``role_index`` is ``NEUTRAL_ROLE_INDEX`` for
    evidence that belongs to the candidate rather than to one job (a listed
    skill, a certification, the summary). Everything else carries the employer
    it belongs to, which is the whole mechanism preventing cross-employer
    blending.
    """

    node_id: str
    kind: str  # "bullet" | "summary" | "skill" | "certification"
    text: str
    employer: str = ""
    role_index: int = NEUTRAL_ROLE_INDEX
    tier: str = ""  # "A" | "B" | "C" for skill nodes, "" otherwise


@dataclass(frozen=True, slots=True)
class ProseClaim:
    """One claim the model makes, and the node ids it says support it."""

    text: str
    claim_type: str
    evidence_node_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProseProposal:
    """A well-formed, fully-cited rewrite proposal for one field."""

    operation: str
    target_id: str
    proposed_text: str
    claims: tuple[ProseClaim, ...]
    preserved_facts: tuple[str, ...]
    new_facts: tuple[str, ...]

    def cited_node_ids(self) -> tuple[str, ...]:
        """Every node id cited anywhere in this proposal, de-duplicated in order."""
        seen: list[str] = []
        for claim in self.claims:
            for node_id in claim.evidence_node_ids:
                if node_id not in seen:
                    seen.append(node_id)
        return tuple(seen)


@dataclass(frozen=True, slots=True)
class ProseRejection:
    """A proposal that failed closed, with the reason a caller maps to a gate code."""

    reason: str
    detail: str

    def as_feedback(self) -> Mapping[str, str]:
        """Machine-readable form for the single bounded repair request."""
        return {"failure": self.reason, "detail": self.detail}


# --------------------------------------------------------------------------- #
# The evidence graph
# --------------------------------------------------------------------------- #
def build_evidence_nodes(
    profile: Profile,
    delivered: Mapping[str, str] | None = None,
) -> tuple[EvidenceNode, ...]:
    """Issue the closed set of citable evidence nodes for *profile*.

    Ids are derived from the candidate's own structure, not from a counter, so
    the same resume always yields the same ids and a cached proposal citing
    ``exp3:bullet1`` still means the bullet it meant when it was cached (which
    is why ``EVIDENCE_GRAPH_VERSION`` participates in the cache key).

    ``delivered`` maps a node id to the text that field currently holds in the
    plan being rewritten, and it is what makes a rewrite citable at all. By the
    time prose runs, the summary carries a targeting clause and any accepted
    ``mention_summary`` terms, and a bullet may carry a ``surface_variant``
    substitution -- content the source profile does not contain. Every one of
    those additions was already admitted by the placement provenance gate and
    ``validate_resume_plan_findings`` before it reached the plan, so it *is*
    approved evidence; without it a rewrite could never cite the very text it is
    re-expressing, and every proposal would be refused for asserting terms its
    own field already states. Measured on the CGI fixture, that is exactly what
    happened: the rewrite was refused for "Angular", a term the delivered summary
    already stated.

    Nothing widens here. The set of citable *ids* is unchanged, and a rewrite
    still cannot introduce anything absent from every node.

    Tier-C ("working knowledge only") skills are issued as nodes but marked, so
    :func:`validate_proposal` can refuse to let one become claimed substance --
    the same rule the deterministic summary path has always applied.
    """
    current = dict(delivered or {})
    nodes: list[EvidenceNode] = []
    summary_text = (current.get("summary") or profile.source_summary).strip()
    if summary_text:
        nodes.append(EvidenceNode(node_id="summary", kind="summary", text=summary_text))
    for role_index, experience in enumerate(profile.experiences):
        for bullet_index, bullet in enumerate(experience.bullets):
            node_id = f"exp{role_index}:bullet{bullet_index}"
            text = (current.get(node_id) or bullet).strip()
            if not text:
                continue
            nodes.append(
                EvidenceNode(
                    node_id=node_id,
                    kind="bullet",
                    text=text,
                    employer=experience.company.strip(),
                    role_index=role_index,
                )
            )
    for tier, mapping in (("A", profile.tier_a), ("B", profile.tier_b), ("C", profile.tier_c)):
        for canonical, display in sorted(mapping.items()):
            label = (display or canonical).strip()
            if not label:
                continue
            nodes.append(
                EvidenceNode(node_id=f"skill:{canonical}", kind="skill", text=label, tier=tier),
            )
    for index, certification in enumerate(profile.certifications):
        if certification.name.strip():
            nodes.append(
                EvidenceNode(node_id=f"cert:{index}", kind="certification", text=certification.name.strip()),
            )
    return tuple(nodes)


def nodes_by_id(nodes: Sequence[EvidenceNode]) -> Mapping[str, EvidenceNode]:
    """Index *nodes* for citation resolution."""
    return {node.node_id: node for node in nodes}


def role_nodes(nodes: Sequence[EvidenceNode], role_index: int) -> tuple[EvidenceNode, ...]:
    """The bundle a ``BULLET_REWRITE`` in *role_index* may cite.

    Bullets of that one role and nothing else. Employer-neutral nodes are
    excluded deliberately: a listed skill says the candidate has it *somewhere*,
    and letting a bullet cite it would let the rewrite assert the skill was used
    at that employer, which is precisely the claim the evidence does not make.
    """
    return tuple(node for node in nodes if node.kind == "bullet" and node.role_index == role_index)


# --------------------------------------------------------------------------- #
# Checkable tokens: the unit both containments are measured in
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class CheckableTokens:
    """Everything in a piece of text that an employer could verify.

    Split by kind rather than merged into one set because the comparisons
    differ: metrics, team sizes, and credential ids are compared as *normalized
    strings* (exact, no near-miss), while vocabulary canonicals, proper nouns,
    and immutable facts are looked for *in* the evidence text so alias identity
    and wording differences resolve the way the rest of the engine resolves
    them.
    """

    metrics: frozenset[str]
    team_facts: frozenset[str]
    credential_ids: frozenset[str]
    canonicals: frozenset[str]
    proper_nouns: tuple[str, ...]
    immutable_facts: tuple[str, ...]

    def is_empty(self) -> bool:
        return not (
            self.metrics
            or self.team_facts
            or self.credential_ids
            or self.canonicals
            or self.proper_nouns
            or self.immutable_facts
        )


def _vocab_canonicals(text: str) -> frozenset[str]:
    """Vocabulary-registered canonicals present in *text*.

    Alias-aware by construction: the candidate's "ReactJS" and a JD's "React"
    both resolve to the same canonical, so comparing canonical sets neither
    rewards nor punishes a spelling difference. This is the same resolution
    ``rachana.operations`` uses for SURFACE_VARIANT.
    """
    return frozenset(match.entry.canonical for match in find_vocabulary_matches(text or ""))


def checkable_tokens(text: str, fact_set: ImmutableFactSet | None = None) -> CheckableTokens:
    """Everything verifiable that *text* asserts."""
    body = text or ""
    immutable: tuple[str, ...] = ()
    if fact_set is not None:
        checked = (
            fact_set.employers
            | fact_set.titles
            | fact_set.date_ranges
            | fact_set.job_locations
            | fact_set.degrees
            | fact_set.institutions
            | fact_set.graduation_dates
            | fact_set.certification_names
            | fact_set.credential_ids
        )
        immutable = tuple(sorted(value for value in checked if value and contains_fact(body, value)))
    return CheckableTokens(
        metrics=extract_metrics(body),
        team_facts=frozenset(fact.casefold() for fact in extract_team_facts(body)),
        credential_ids=extract_credential_ids(body),
        canonicals=_vocab_canonicals(body),
        proper_nouns=tuple(extract_proper_nouns(body)),
        immutable_facts=immutable,
    )


def unsupported_tokens(claim_text: str, evidence_text: str, fact_set: ImmutableFactSet | None = None) -> list[str]:
    """Every checkable token *claim_text* asserts that *evidence_text* does not.

    An empty result is the only thing that admits a claim. Note the asymmetry:
    evidence may say more than the claim (that is the normal case), but a claim
    may never say more than its evidence.
    """
    claim = checkable_tokens(claim_text, fact_set)
    evidence = checkable_tokens(evidence_text, fact_set)
    missing: list[str] = []
    missing.extend(f"metric {value!r}" for value in sorted(claim.metrics - evidence.metrics))
    missing.extend(f"team size {value!r}" for value in sorted(claim.team_facts - evidence.team_facts))
    missing.extend(f"credential id {value!r}" for value in sorted(claim.credential_ids - evidence.credential_ids))
    missing.extend(f"term {value!r}" for value in sorted(claim.canonicals - evidence.canonicals))
    seen: set[str] = set()
    for noun in claim.proper_nouns:
        key = noun.casefold()
        if key in seen:
            continue
        seen.add(key)
        if contains_fact(evidence_text, noun):
            continue
        # A capitalized token that resolves to a vocabulary entry the evidence
        # also expresses is already covered by the canonical comparison above
        # ("Azure" against evidence saying "azure").
        if _vocab_canonicals(noun) and _vocab_canonicals(noun) <= evidence.canonicals:
            continue
        missing.append(f"name {noun!r}")
    for value in claim.immutable_facts:
        if not contains_fact(evidence_text, value):
            missing.append(f"fact {value!r}")
    return missing


def lost_immutable_facts(original_text: str, proposed_text: str, fact_set: ImmutableFactSet | None = None) -> list[str]:
    """Every *employer-checkable* fact in *original_text* the rewrite drops.

    Deliberately narrower than :func:`unsupported_tokens`: metrics, team sizes,
    credential ids, and the candidate's own immutable facts only -- not
    vocabulary canonicals and not names. That narrowing is what makes a
    ``SUMMARY_REWRITE`` possible at all, and it is a principled line rather than
    a convenience.

    A summary's job is *selection*: the fixtures' source summary names twenty-six
    distinct requirement canonicals in a hundred and three words, so a rule that
    forbade dropping any of them would forbid every rewrite, including the ones
    that concentrate the summary on the role being applied for. Which JD-relevant
    terms the *document* may stop stating is not this gate's question anyway --
    :class:`~ats_engine.rachana.preservation.PreservationGuard` already answers it
    authoritatively across the whole delivered document, so a term dropped from
    the summary and stated nowhere else is caught there regardless.

    What may never be dropped, wherever it appears, is something an employer can
    verify with one call: "8+ years", "team of four engineers", a credential id,
    an employer, a title, a date range, a degree. Those are checked here.

    A ``BULLET_REWRITE`` is held to the stricter rule instead (see
    :func:`validate_proposal`): a bullet is one specific claim about one piece of
    work, so dropping a tool from it changes the claim rather than re-prioritising
    a list.
    """
    original = checkable_tokens(original_text, fact_set)
    proposed = checkable_tokens(proposed_text, fact_set)
    lost: list[str] = []
    lost.extend(f"metric {value!r}" for value in sorted(original.metrics - proposed.metrics))
    lost.extend(f"team size {value!r}" for value in sorted(original.team_facts - proposed.team_facts))
    lost.extend(f"credential id {value!r}" for value in sorted(original.credential_ids - proposed.credential_ids))
    lost.extend(f"fact {value!r}" for value in original.immutable_facts if not contains_fact(proposed_text, value))
    return lost


# --------------------------------------------------------------------------- #
# Parsing the model's reply
# --------------------------------------------------------------------------- #
def parse_proposal(payload: Any, *, operation: str, target_id: str) -> ProseProposal | ProseRejection:
    """Parse an untrusted provider reply into a proposal, or reject it.

    Strict on purpose. A missing field, a wrong operation, a claim without a
    citation list, or a non-empty ``new_facts`` is a rejection, never a
    best-effort reconstruction: reconstructing a malformed reply would mean the
    engine, not the model, deciding what the model meant to claim.
    """
    if payload is None:
        return ProseRejection(reason=REJECT_MALFORMED, detail="provider returned no parseable JSON")
    if not isinstance(payload, dict):
        return ProseRejection(reason=REJECT_SCHEMA, detail=f"expected a JSON object, got {type(payload).__name__}")
    if str(payload.get("operation", "")) != operation:
        return ProseRejection(
            reason=REJECT_SCHEMA,
            detail=f"operation must be {operation!r}, got {payload.get('operation')!r}",
        )
    if str(payload.get("target_id", "")) != target_id:
        return ProseRejection(
            reason=REJECT_SCHEMA,
            detail=f"target_id must be {target_id!r}, got {payload.get('target_id')!r}",
        )
    proposed = _one_line(str(payload.get("proposed_text", "")))
    if not proposed:
        return ProseRejection(reason=REJECT_SCHEMA, detail="proposed_text is empty")

    new_facts = payload.get("new_facts", None)
    if not isinstance(new_facts, list):
        return ProseRejection(reason=REJECT_SCHEMA, detail="new_facts must be present and an array")
    declared_new = tuple(str(value).strip() for value in new_facts if str(value).strip())
    if declared_new:
        return ProseRejection(
            reason=REJECT_NEW_FACTS,
            detail=f"declared new fact(s) {', '.join(repr(value) for value in declared_new)}",
        )

    raw_claims = payload.get("claims", None)
    if not isinstance(raw_claims, list) or not raw_claims:
        return ProseRejection(reason=REJECT_SCHEMA, detail="claims must be a non-empty array")
    claims: list[ProseClaim] = []
    for index, raw in enumerate(raw_claims):
        if not isinstance(raw, dict):
            return ProseRejection(reason=REJECT_SCHEMA, detail=f"claims[{index}] is not an object")
        text = _one_line(str(raw.get("text", "")))
        if not text:
            return ProseRejection(reason=REJECT_SCHEMA, detail=f"claims[{index}].text is empty")
        claim_type = str(raw.get("claim_type", "")).strip().casefold()
        if claim_type not in CLAIM_TYPES:
            return ProseRejection(
                reason=REJECT_SCHEMA,
                detail=f"claims[{index}].claim_type {claim_type!r} is not one of {sorted(CLAIM_TYPES)}",
            )
        raw_ids = raw.get("evidence_node_ids", None)
        if not isinstance(raw_ids, list):
            return ProseRejection(reason=REJECT_SCHEMA, detail=f"claims[{index}].evidence_node_ids must be an array")
        node_ids = tuple(str(value).strip() for value in raw_ids if str(value).strip())
        if not node_ids:
            return ProseRejection(
                reason=REJECT_MISSING_CITATION,
                detail=f"claims[{index}] ({text[:60]!r}) cites no evidence",
            )
        claims.append(ProseClaim(text=text, claim_type=claim_type, evidence_node_ids=node_ids))

    raw_preserved = payload.get("preserved_facts", [])
    preserved = (
        tuple(str(value).strip() for value in raw_preserved if str(value).strip())
        if isinstance(raw_preserved, list)
        else ()
    )
    return ProseProposal(
        operation=operation,
        target_id=target_id,
        proposed_text=proposed,
        claims=tuple(claims),
        preserved_facts=preserved,
        new_facts=(),
    )


def _one_line(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


# --------------------------------------------------------------------------- #
# Validating the proposal against the evidence graph
# --------------------------------------------------------------------------- #
def validate_proposal(
    proposal: ProseProposal,
    *,
    original_text: str,
    allowed: Sequence[EvidenceNode],
    profile: Profile,
    fact_set: ImmutableFactSet | None = None,
    allow_neutral_nodes: bool = True,
) -> ProseRejection | None:
    """Prove the proposal is admissible, or say exactly why it is not.

    ``allowed`` is the bundle this operation may cite -- the whole graph for a
    summary, one role's bullets for a bullet. A citation outside it is refused
    rather than silently ignored, because "ignored" would leave the claim it
    was meant to support standing on nothing.

    The gates are ordered so the *most specific* cause is reported: an unknown
    node id before an unsupported claim, and an unsupported claim before the
    whole-text coverage check, so a reviewer reading the histogram sees what
    actually went wrong instead of a downstream symptom.
    """
    facts = fact_set if fact_set is not None else build_fact_set(profile)
    permitted = nodes_by_id(allowed)

    if proposal.proposed_text.strip() == (original_text or "").strip():
        return ProseRejection(
            reason=REJECT_TEXT_UNCHANGED,
            detail="proposed text is identical to the source text, so there is nothing to accept",
        )

    budget = _word_budget(original_text)
    proposed_words = len(proposal.proposed_text.split())
    if proposed_words > budget:
        return ProseRejection(
            reason=REJECT_WORD_GROWTH,
            detail=f"proposed text is {proposed_words} words, over the {budget}-word budget for this field",
        )

    # 1. Every citation must resolve inside the permitted bundle.
    for claim in proposal.claims:
        for node_id in claim.evidence_node_ids:
            node = permitted.get(node_id)
            if node is None:
                reason = REJECT_EVIDENCE_OUT_OF_SCOPE if _looks_like_node_id(node_id) else REJECT_UNKNOWN_NODE
                return ProseRejection(
                    reason=reason,
                    detail=f"claim {claim.text[:60]!r} cites {node_id!r}, which is not citable here",
                )
            if not allow_neutral_nodes and node.role_index == NEUTRAL_ROLE_INDEX:
                return ProseRejection(
                    reason=REJECT_EVIDENCE_OUT_OF_SCOPE,
                    detail=f"claim {claim.text[:60]!r} cites employer-neutral node {node_id!r}",
                )
            if node.kind == "skill" and node.tier == "C":
                return ProseRejection(
                    reason=REJECT_EVIDENCE_OUT_OF_SCOPE,
                    detail=(
                        f"claim {claim.text[:60]!r} cites working-knowledge-only skill {node.text!r}, "
                        "which may never be claimed as substance"
                    ),
                )

    # 2. No claim may blend employers. Checked per claim, not per proposal: a
    #    career summary legitimately spans jobs across its several sentences,
    #    but one *statement* combining two employers' facts is a fabrication
    #    even though both halves are individually true.
    for claim in proposal.claims:
        employers = sorted(
            {permitted[node_id].employer for node_id in claim.evidence_node_ids if permitted[node_id].employer}
        )
        if len(employers) > 1:
            return ProseRejection(
                reason=REJECT_CROSS_EMPLOYER,
                detail=(
                    f"claim {claim.text[:60]!r} cites evidence from {len(employers)} employers "
                    f"({', '.join(repr(name) for name in employers)}); one statement may never blend them"
                ),
            )

    # 3. Each claim must say no more than its own cited evidence.
    for claim in proposal.claims:
        evidence_text = "\n".join(permitted[node_id].text for node_id in claim.evidence_node_ids)
        missing = unsupported_tokens(claim.text, evidence_text, facts)
        if missing:
            return ProseRejection(
                reason=REJECT_UNSUPPORTED_CLAIM,
                detail=(
                    f"claim {claim.text[:60]!r} asserts {', '.join(missing)} "
                    f"absent from its cited evidence ({', '.join(claim.evidence_node_ids)})"
                ),
            )

    # 4. The proposal must say no more than its claims. Without this, per-clause
    #    citation would be satisfiable by one cited claim beside any amount of
    #    uncited prose -- which is exactly the shape a prompt-injected assertion
    #    takes.
    claim_corpus = "\n".join(claim.text for claim in proposal.claims)
    uncovered = unsupported_tokens(proposal.proposed_text, claim_corpus, facts)
    if uncovered:
        return ProseRejection(
            reason=REJECT_MISSING_CITATION,
            detail=f"proposed text asserts {', '.join(uncovered)} that no claim covers",
        )

    # 5. Nothing checkable in the source field may disappear. Gates 1-4 all run
    #    in the "may not say more" direction; loss is the direction they cannot
    #    see, so it is checked explicitly here. A bullet is held to the strict
    #    rule (every term and name), a summary only to employer-checkable facts
    #    -- see `lost_immutable_facts` for why the two differ.
    if proposal.operation == BULLET_REWRITE:
        lost = unsupported_tokens(original_text, proposal.proposed_text, facts)
    else:
        lost = lost_immutable_facts(original_text, proposal.proposed_text, facts)
    if lost:
        return ProseRejection(
            reason=REJECT_FACT_LOSS,
            detail=f"proposed text drops {', '.join(lost)} stated by the source text",
        )
    if proposal.operation == SUMMARY_REWRITE and proposed_words < MIN_SUMMARY_WORDS:
        # Checked after the citation gates, not beside the word budget above, so
        # a fabricated or uncited claim is reported as such: a rewrite that is
        # merely too short is the least specific thing that can be wrong with
        # it, and the histogram should name the real cause.
        return ProseRejection(
            reason=REJECT_FACT_LOSS,
            detail=(
                f"proposed summary is {proposed_words} words, below the {MIN_SUMMARY_WORDS}-word floor, "
                "so it has dropped substance rather than re-expressed it"
            ),
        )

    # 6. A bullet rewrite additionally faces the authoritative shared bullet
    #    fidelity gate -- the same one `generation.planning._bullet_is_valid`
    #    and the final rendered-document check use. Reused rather than
    #    reimplemented so "did this rewrite preserve the proposition" has one
    #    answer in this codebase, not a prose-specific second opinion.
    if proposal.operation == BULLET_REWRITE:
        errors = bullet_fidelity_errors(
            original_text,
            proposal.proposed_text,
            source_text=profile.raw_markdown,
        )
        if errors:
            return ProseRejection(
                reason=REJECT_FACT_LOSS,
                detail=f"bullet fidelity gate: {errors[0]}",
            )
    return None


def _looks_like_node_id(value: str) -> bool:
    """Whether *value* has the shape of an issued id (so "out of scope" fits)."""
    return bool(re.fullmatch(r"(summary|exp\d+:bullet\d+|skill:.+|cert:\d+)", value))


def _word_budget(original_text: str) -> int:
    """The most words a rewrite of *original_text* may use.

    The source's own length, never more. Length growth is the one change that
    reliably dilutes ``relevant_terms_per_100_words``, the metric this whole
    workstream exists to move, and the pareto policy's density objective is not
    a sufficient guard on its own -- a rewrite can raise coverage while diluting
    density and still be accepted on the coverage improvement alone. Capping
    length here makes "word count does not grow" true by construction rather
    than by hoping the objectives trade off favourably.
    """
    return max(1, len((original_text or "").split()))


# --------------------------------------------------------------------------- #
# Cache identity
# --------------------------------------------------------------------------- #
def prose_cache_identity(
    *,
    operation: str,
    target_id: str,
    original_text: str,
    node_ids: Sequence[str],
) -> str:
    """The versioned identity a prose proposal is cached under.

    This string is embedded verbatim in every prose prompt, and
    ``providers.base.generate_json`` keys its content-hash cache on
    ``(provider.identity, prompt)``. The cache key for a prose proposal is
    therefore the full tuple the brief requires -- model identity from the
    provider, and prompt-contract, evidence-graph, requirement-model, target
    source hash, and validator-policy versions from here -- with no way for one
    of them to be forgotten at a call site, because the prompt cannot be built
    without it.

    Step 3 produced a cache-identity bug in this codebase by deriving a key
    from ``id()``, which is unique only among *live* objects. Nothing here is
    derived from object identity, address, iteration order, or wall-clock time:
    every component is a declared version or a content hash.
    """
    payload = {
        "contract": PROMPT_CONTRACT_VERSION,
        "evidence_graph": EVIDENCE_GRAPH_VERSION,
        "requirement_model": REQUIREMENT_MODEL_VERSION,
        "validator_policy": VALIDATOR_POLICY_VERSION,
        "operation": operation,
        "target_id": target_id,
        "target_sha256": hashlib.sha256((original_text or "").encode("utf-8")).hexdigest(),
        # Sorted, so a caller that assembles the same bundle in a different
        # order does not split the cache; the bundle's *membership* is what
        # changes what the model may cite.
        "evidence_nodes_sha256": hashlib.sha256("\n".join(sorted(node_ids)).encode("utf-8")).hexdigest(),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


# --------------------------------------------------------------------------- #
# Prompts
# --------------------------------------------------------------------------- #
_SCHEMA_CLAUSE = (
    "Return ONLY one JSON object, with no markdown fence and no commentary, in exactly this shape:\n"
    '{"operation":"<operation>","target_id":"<target_id>","proposed_text":"...",'
    '"claims":[{"text":"...","claim_type":"<one of ' + ", ".join(sorted(CLAIM_TYPES)) + '>",'
    '"evidence_node_ids":["..."]}],'
    '"preserved_facts":["..."],"new_facts":[]}\n'
    "Rules that are enforced deterministically after you reply, so a violation is "
    "discarded rather than repaired:\n"
    "- Every claim must cite at least one evidence_node_id from the CITABLE EVIDENCE "
    "list below. An id you were not given is a rejection.\n"
    "- A claim may not state any tool, technology, metric, number, percentage, "
    "dollar value, team size, credential, employer, title, date, institution, "
    "certification, client, or project that its own cited nodes do not state.\n"
    "- The proposed_text may not state anything that none of your claims covers.\n"
    "- new_facts must be an empty array. If you cannot make a claim without adding "
    "a fact, omit the claim.\n"
    "- All nodes cited by any single claim must belong to the same employer.\n"
    "- Do not drop any tool, number, name, or other checkable detail the source "
    "text already states.\n"
    "- no em dashes, en dashes, or double hyphens; no first person; no cliche "
    "resume filler (results-driven, proven track record, spearheaded, leveraged, "
    "architected, orchestrated, streamlined, seamless, robust)."
)


def _evidence_listing(nodes: Sequence[EvidenceNode]) -> str:
    """The citable bundle, as node id plus untrusted node text."""
    lines: list[str] = []
    for node in nodes:
        scope = f" employer={node.employer!r}" if node.employer else ""
        tier = f" tier={node.tier}" if node.tier else ""
        lines.append(f"[{node.node_id}] kind={node.kind}{scope}{tier}: {node.text}")
    return "\n".join(lines)


def _requirement_listing(requirements: Sequence[RequirementTerm], limit: int = 12) -> str:
    ranked = sorted(requirements, key=lambda item: (-item.weight, item.canonical))
    return json.dumps([item.surface or item.canonical for item in ranked[:limit]])


def summary_rewrite_prompt(
    *,
    original_text: str,
    nodes: Sequence[EvidenceNode],
    requirements: Sequence[RequirementTerm],
    target_title: str,
) -> str:
    """Build the SUMMARY_REWRITE request.

    Everything derived from the job posting or the uploaded resume is fenced as
    untrusted data (see ``generation.prompts.untrusted_block``): a posting is
    attacker-controlled text, and an uploaded resume can be adversarial too.
    """
    identity = prose_cache_identity(
        operation=SUMMARY_REWRITE,
        target_id="resume:summary",
        original_text=original_text,
        node_ids=[node.node_id for node in nodes],
    )
    return "\n\n".join(
        [
            f"CONTRACT: {identity}",
            UNTRUSTED_DATA_CLAUSE,
            (
                "Task: re-express the candidate's professional summary so their existing, "
                "true accomplishments read as relevant to the target role. Synthesise only "
                "claims you can cite. Do not add anything. Do not make any claim larger. "
                f"Keep it to at most {_word_budget(original_text)} words."
            ),
            untrusted_block("TARGET_ROLE", target_title),
            untrusted_block("PRIORITISED_JD_REQUIREMENTS", _requirement_listing(requirements)),
            untrusted_block("SOURCE_SUMMARY", original_text),
            untrusted_block("CITABLE_EVIDENCE", _evidence_listing(nodes)),
            PROHIBITED_INVENTION_CLAUSE,
            _SCHEMA_CLAUSE.replace("<operation>", SUMMARY_REWRITE).replace("<target_id>", "resume:summary"),
        ]
    )


def bullet_rewrite_prompt(
    *,
    target_id: str,
    original_text: str,
    nodes: Sequence[EvidenceNode],
    requirements: Sequence[RequirementTerm],
    employer: str,
    title: str,
) -> str:
    """Build the BULLET_REWRITE request for one bullet in one role."""
    identity = prose_cache_identity(
        operation=BULLET_REWRITE,
        target_id=target_id,
        original_text=original_text,
        node_ids=[node.node_id for node in nodes],
    )
    return "\n\n".join(
        [
            f"CONTRACT: {identity}",
            UNTRUSTED_DATA_CLAUSE,
            (
                "Task: re-word one resume bullet so it reads as relevant to the target role. "
                "Preserve the proposition exactly: same actor, same action, same object, same "
                "scope, same tense, same metric, same outcome. Clearer wording only, never a "
                "new or larger claim. Evidence from elsewhere in this same role may be cited, "
                "but only if the bullet's own action and object stay the same. Keep it to one "
                f"line of at most {_word_budget(original_text)} words."
            ),
            untrusted_block("ROLE", f"{title} at {employer}"),
            untrusted_block("PRIORITISED_JD_REQUIREMENTS", _requirement_listing(requirements)),
            untrusted_block("SOURCE_BULLET", original_text),
            untrusted_block("CITABLE_EVIDENCE", _evidence_listing(nodes)),
            PROHIBITED_INVENTION_CLAUSE,
            _SCHEMA_CLAUSE.replace("<operation>", BULLET_REWRITE).replace("<target_id>", target_id),
        ]
    )


def repair_prompt(original_prompt: str, rejection: ProseRejection) -> str:
    """The one bounded repair request, carrying machine-readable failure detail.

    Exactly one is ever sent (see ``rachana.operations.request_rewrite``). The
    validator's own reason code and detail are handed back verbatim so the model
    is repairing the actual failure rather than guessing, and the next reply is
    validated by the same gates with no further attempt available.
    """
    feedback = json.dumps(dict(rejection.as_feedback()), sort_keys=True)
    return (
        f"{original_prompt}\n\n"
        "Your previous reply was rejected by the deterministic validator. "
        f"VALIDATOR_FAILURE: {feedback}\n"
        "This is your only retry. Return one corrected JSON object in the same shape. "
        "If you cannot satisfy the validator without adding or strengthening a claim, "
        "return your proposal with fewer claims and shorter proposed_text instead."
    )


__all__ = [
    "BULLET_REWRITE",
    "CLAIM_TYPES",
    "EVIDENCE_GRAPH_VERSION",
    "MIN_SUMMARY_WORDS",
    "NEUTRAL_ROLE_INDEX",
    "PROMPT_CONTRACT_VERSION",
    "REJECT_CROSS_EMPLOYER",
    "REJECT_EVIDENCE_OUT_OF_SCOPE",
    "REJECT_FACT_LOSS",
    "REJECT_MALFORMED",
    "REJECT_MISSING_CITATION",
    "REJECT_NEW_FACTS",
    "REJECT_NO_PROVIDER",
    "REJECT_SCHEMA",
    "REJECT_TEXT_UNCHANGED",
    "REJECT_UNKNOWN_NODE",
    "REJECT_UNSUPPORTED_CLAIM",
    "REJECT_WORD_GROWTH",
    "REQUIREMENT_MODEL_VERSION",
    "SUMMARY_REWRITE",
    "VALIDATOR_POLICY_VERSION",
    "CheckableTokens",
    "EvidenceNode",
    "ProseClaim",
    "ProseProposal",
    "ProseRejection",
    "build_evidence_nodes",
    "bullet_rewrite_prompt",
    "checkable_tokens",
    "lost_immutable_facts",
    "nodes_by_id",
    "parse_proposal",
    "prose_cache_identity",
    "repair_prompt",
    "role_nodes",
    "summary_rewrite_prompt",
    "unsupported_tokens",
    "validate_proposal",
]
