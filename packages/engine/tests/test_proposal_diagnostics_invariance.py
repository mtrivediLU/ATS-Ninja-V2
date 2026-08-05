"""Golden assertions proving Phase 0 instrumentation does not tailor differently.

The ``cgi_fullstack_java_angular`` sha256 below was corrected after CI run
30712253680 failed on it. Diagnosis: ``accepted_actions`` and ``score`` both
matched their golden values; only the text hash did not. Checked directly
against ``main`` (commit f60558b, this branch's actual merge-base) via a
disposable ``git worktree`` plus a ``PYTHONPATH`` override -- no code from
this branch involved -- main's own ``run_pipeline`` output for this exact
fixture hashes to ``a6d990fb...``, not the ``290d8f4a...`` this test asserted.
Repeated across two fresh interpreter processes to rule out hash-seed
non-determinism; both instrumented and un-instrumented code agree. The other
two goldens (``crowdplat_web_scraper``, ``latentview_bi_ai``) were verified
the same way and were already correct. This was a mis-captured constant in
the original Phase 0 commit, not a behavioral change introduced there.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ats_engine.generation.pipeline import run_pipeline
from ats_engine.models import Mode

FIXTURES = Path(__file__).parent / "fixtures" / "real_extraction"

# Captured from ``main`` immediately before Phase 0 instrumentation.
GOLDENS = {
    "cgi_fullstack_java_angular": {
        "actions": [],
        "score": 41.21,
        "sha256": "a6d990fb152082c5c2356921aadd9c152b8a4e1286b56ede0d721db33e578d95",
    },
    "crowdplat_web_scraper": {
        "actions": [
            "quality:headline",
            "quality:summary",
            "mention_summary:summary:APIs",
            "mention_summary:summary:Python",
            "mention_summary:summary:communication",
            "append_skill:skills:Python",
            "append_skill:skills:communication",
            "surface_variant:headline:APIs",
            "surface_variant:headline:Python",
        ],
        "score": 18.12,
        "sha256": "11f3b30c143b0ca300c8bc2992aab5b38b1b2a6976f28dce03c6cc879dc13d23",
    },
    "latentview_bi_ai": {
        "actions": [
            "quality:headline",
            "append_skill:skills:SQL",
            "append_skill:skills:AI assistants",
            "surface_variant:headline:ChatGPT",
            "surface_variant:headline:Claude",
            "surface_variant:headline:GenAI",
            "weave_bullet:experience:0:bullet:2:GenAI",
            "weave_bullet:experience:2:bullet:0:SQL",
            "weave_bullet:experience:0:bullet:2:AI assistants",
        ],
        "score": 47.55,
        "sha256": "6701e19a687f522c9231f9f353d4999ff642ed31d5563ffe8c0b00b232056051",
    },
}


@pytest.mark.parametrize("case", sorted(GOLDENS))
def test_fixture_tailoring_is_identical_to_main_baseline(case: str) -> None:
    result = run_pipeline(
        resume_text=(FIXTURES / "candidate_resume.pymupdf.txt").read_text(encoding="utf-8"),
        job_description=(FIXTURES / case / "job_description.txt").read_text(encoding="utf-8"),
        default_mode=Mode.RESUME,
        use_llm=False,
    )
    trace = result.metadata["optimization_trace"]
    golden = GOLDENS[case]

    assert trace.accepted_actions == golden["actions"]
    assert trace.score_path[-1] == pytest.approx(golden["score"])
    assert hashlib.sha256(result.resume_text.encode("utf-8")).hexdigest() == golden["sha256"]
