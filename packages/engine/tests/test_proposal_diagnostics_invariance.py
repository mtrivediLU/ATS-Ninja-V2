"""Golden assertions proving Phase 0 instrumentation does not tailor differently."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ats_engine.generation.pipeline import run_pipeline
from ats_engine.models import Mode

FIXTURES = Path(__file__).parent / "fixtures" / "real_extraction"

# Captured from ``main`` immediately before Phase 0 instrumentation.  The CGI
# fixture retains an empty action expectation only because its deterministic
# output already has dedicated delivery regression coverage; the score and
# hash still pin the complete delivered artifact once recorded below.
GOLDENS = {
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
