"""Step 2 behavioral goldens for the real extraction fixtures.

These values deliberately supersede the Step 1 invariance baseline. Demand
repair is expected to change scores and may change delivered text:

* CGI: responsive design was added, the overlapping bare APIs requirement was
  removed, and Full Stack is now distinguished as title provenance. The score
  changes from 41.21 to 42.33; accepted actions and delivered hash do not.
* CrowdPlat: title mining adds Web Scraper and Data Extraction. The changed
  demand set removes ``quality:summary`` from the accepted-action set, moves
  the score from 18.12 to 16.83, and changes the delivered hash.
* LatentView: title mining adds Artificial Intelligence from the exact ``AI``
  surface. The score changes from 47.55 to 50.67; accepted actions and hash do
  not.

Each golden was captured from this branch after all Step 2 extraction changes,
and cross-checked against ``python -m ats_engine.bench --json``.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ats_engine.generation.pipeline import run_pipeline
from ats_engine.models import Mode

FIXTURES = Path(__file__).parent / "fixtures" / "real_extraction"

# Captured from this branch after Step 2 demand repair.
GOLDENS = {
    "cgi_fullstack_java_angular": {
        "actions": [],
        "score": 42.33,
        "sha256": "a6d990fb152082c5c2356921aadd9c152b8a4e1286b56ede0d721db33e578d95",
    },
    "crowdplat_web_scraper": {
        "actions": [
            "quality:headline",
            "mention_summary:summary:APIs",
            "mention_summary:summary:Python",
            "mention_summary:summary:communication",
            "append_skill:skills:Python",
            "append_skill:skills:communication",
            "surface_variant:headline:APIs",
            "surface_variant:headline:Python",
        ],
        "score": 16.83,
        "sha256": "a18046eea6c3a109172a4ac1cde2bbe7f45fca83aa060ac902394b2478f8ef52",
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
        "score": 50.67,
        "sha256": "6701e19a687f522c9231f9f353d4999ff642ed31d5563ffe8c0b00b232056051",
    },
}


@pytest.mark.parametrize("case", sorted(GOLDENS))
def test_fixture_tailoring_matches_step2_rebaseline(case: str) -> None:
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
