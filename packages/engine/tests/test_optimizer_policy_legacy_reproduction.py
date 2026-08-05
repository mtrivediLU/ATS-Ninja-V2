"""``optimizer_policy="legacy"`` must reproduce main's exact pre-Step-3 behavior.

Planning now also emits surface_variant proposals regardless of policy (see
generation/integration_planner.py), so this is not a no-op claim: the legacy
loop genuinely considers them too, just under the original strict-PRAMANA-
score-improvement rule. Proven here against the delivered-text sha256 -- a
byte-for-byte proof, not just a same-actions claim, since the delivered text
is a deterministic function of exactly which actions were applied and how.

Measured directly on this branch with a disposable script before writing
this test (not copied from the brief): identical score and delivered sha256
to the true pre-Step-2/Step-3 baseline on all three fixtures. The sole
disclosed difference is the accepted-action label itself for the headline
operation, renamed ``surface_variant`` -> ``headline_mention`` in this same
change (see test_proposal_diagnostics_invariance.py's module docstring for
why): a label rename, not a behavior change, and independently proven so by
the unchanged score and sha256 alongside it.
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
# script, then cross-checked against the true pre-Step-2/Step-3 baseline
# (main before this workstream) run the same way -- identical on both.
LEGACY_GOLDENS = {
    "cgi_fullstack_java_angular": {
        "accepted_actions": [],
        "score": 42.33,
        "sha256": "a6d990fb152082c5c2356921aadd9c152b8a4e1286b56ede0d721db33e578d95",
    },
    "crowdplat_web_scraper": {
        "accepted_actions": [
            "quality:headline",
            "mention_summary:summary:APIs",
            "mention_summary:summary:Python",
            "mention_summary:summary:communication",
            "append_skill:skills:Python",
            "append_skill:skills:communication",
            "headline_mention:headline:APIs",
            "headline_mention:headline:Python",
        ],
        "score": 16.83,
        "sha256": "a18046eea6c3a109172a4ac1cde2bbe7f45fca83aa060ac902394b2478f8ef52",
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
