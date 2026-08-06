"""``optimizer_policy="legacy"`` keeps its own decision rule unchanged.

Planning now also emits surface_variant proposals regardless of policy (see
generation/integration_planner.py), so this is not a no-op claim: the legacy
loop genuinely considers them too, just under the original strict-PRAMANA-
score-improvement rule (plus its own plateau-break, unique to legacy -- see
``optimizer.py``'s main loop). Proven here against the delivered-text
sha256 -- a byte-for-byte proof, not just a same-actions claim, since the
delivered text is a deterministic function of exactly which actions were
applied and how.

These goldens changed once already, in the Step 3 follow-up round, and the
reason is worth recording precisely because it is not a policy change: the
follow-up fixed several validation-gate defects legacy and pareto both
depend on --the CGI stuffing-measurement counting the engine's own targeting
clause (``optimizer._without_targeting``) and a delivered-layout
experience-index bug in the shared provenance scorer
(``pramana/scoring.py::_experience_bullets``) chief among them. Those are
gate corrections, not acceptance-rule changes, so legacy's own goldens moved
too, alongside pareto's -- the claim this test makes is narrower than "legacy
never changes": it is "legacy's own strict-improvement rule and plateau-break
are unaffected by anything *this* branch does to the pareto policy itself."
Measured directly for this round: CGI's legacy goldens now differ (the
stuffing block no longer masks its plateau-break stopping at zero placement
actions, and the surviving quality-only headline rewrite changes the
delivered sha256); CrowdPlat's now match its own pareto golden exactly
(``test_proposal_diagnostics_invariance.py``) -- Step 3's placement_reinforcement
objective closed the gap between the two policies for this fixture
specifically; LatentView's are completely unchanged from the original
Step 2/pre-Step-3 baseline, confirming legacy's plateau-break still stops it
at the same point regardless of anything pareto now accepts beyond it.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ats_engine.config import EngineSettings
from ats_engine.generation.pipeline import run_pipeline
from ats_engine.models import Mode

FIXTURES = Path(__file__).parent / "fixtures" / "real_extraction"

# Measured on this branch with optimizer_policy="legacy" via a disposable
# script, after the Step 3 follow-up's shared validation-gate fixes.
LEGACY_GOLDENS = {
    "cgi_fullstack_java_angular": {
        # The stuffing-measurement fix (optimizer._without_targeting) removed
        # the false STUFF_TERM_OCCURRENCES block, but legacy's own, unrelated
        # plateau-break (score_path[-1] - score_path[-2] < 0.5) now stops the
        # batch loop at zero accepted placements on its own -- a real,
        # unmasked outcome of legacy's decision rule, not a re-introduction of
        # the bug just fixed. Only the quality-only headline rewrite survives,
        # changing the delivered sha256 from the pre-fix (source-rolled-back)
        # value even though the score rounds to the same 42.33.
        "accepted_actions": ["quality:headline"],
        "score": 42.33,
        "sha256": "e42c8389cedfba2f63541e199602cdec26be03e90e7b11a09ccc572b284b839a",
    },
    "crowdplat_web_scraper": {
        # Now identical to this fixture's pareto golden
        # (test_proposal_diagnostics_invariance.py): Step 3's
        # placement_reinforcement objective closed the gap between the two
        # policies here, so optimizer_policy no longer changes this fixture's
        # outcome at all. "communication" survives via append_skill only, not
        # mention_summary too (a stuffing bisection detail, not this test's
        # concern); quality:summary is now accepted where it previously was
        # not, restoring a genuine Step 2 quality proposal.
        "accepted_actions": [
            "quality:headline",
            "quality:summary",
            "mention_summary:summary:APIs",
            "mention_summary:summary:Python",
            "append_skill:skills:Python",
            "append_skill:skills:communication",
            "headline_mention:headline:APIs",
            "headline_mention:headline:Python",
        ],
        "score": 16.83,
        "sha256": "401a0be48b943f1f09213234a94c34100a9db1bf686a64dc5d36f5b687c13c33",
    },
    "latentview_bi_ai": {
        "accepted_actions": [
            "quality:headline",
            "append_skill:skills:SQL",
            "append_skill:skills:AI assistants",
            "headline_mention:headline:ChatGPT",
            "headline_mention:headline:Claude",
            "headline_mention:headline:GenAI",
            "weave_bullet:experience:0:bullet:2:GenAI",
            "weave_bullet:experience:2:bullet:0:SQL",
            "weave_bullet:experience:0:bullet:2:AI assistants",
        ],
        "score": 50.67,
        "sha256": "6701e19a687f522c9231f9f353d4999ff642ed31d5563ffe8c0b00b232056051",
    },
}


@pytest.mark.parametrize("case", sorted(LEGACY_GOLDENS))
def test_legacy_policy_reproduces_pre_step3_behavior_exactly(case: str) -> None:
    settings = EngineSettings(optimizer_policy="legacy", llm_cache_enabled=False)
    result = run_pipeline(
        resume_text=(FIXTURES / "candidate_resume.pymupdf.txt").read_text(encoding="utf-8"),
        job_description=(FIXTURES / case / "job_description.txt").read_text(encoding="utf-8"),
        default_mode=Mode.RESUME,
        use_llm=False,
        settings=settings,
    )
    trace = result.metadata["optimization_trace"]
    golden = LEGACY_GOLDENS[case]

    assert trace.accepted_actions == golden["accepted_actions"]
    assert trace.score_path[-1] == pytest.approx(golden["score"])
    assert hashlib.sha256(result.resume_text.encode("utf-8")).hexdigest() == golden["sha256"]
