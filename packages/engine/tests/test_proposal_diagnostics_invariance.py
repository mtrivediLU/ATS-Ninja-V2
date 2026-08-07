"""Step 4 behavioral goldens for the real extraction fixtures.

Re-baselined from the Step 3 values because this step changes output by
design. Every constant below was recaptured from this branch, and each moved
for a stated reason:

* ``delivered_word_count`` falls on all three (CGI 1004 -> 959, CrowdPlat 999
  -> 954, LatentView 1003 -> 958). Cause: PRUNE removes the same two bullets on
  each fixture -- a "Production Deployment & UAT" bullet and a "UI/UX
  Optimization" bullet, both with zero requirement relevance, no metric, team
  size, credential id or immutable fact, and no unique evidence.
* ``relevant_terms_per_100_words`` rises on all three (CGI 1.4940 -> 1.5641,
  CrowdPlat 0.5005 -> 0.5241, LatentView 0.9970 -> 1.0438), and no longer
  *falls* on CGI and CrowdPlat as it did in Step 3. The numerator is unchanged
  (15 / 5 / 10 distinct canonicals); the whole gain is denominator.
* ``sha256`` changes on all three: the delivered text is genuinely shorter and
  skill groups are ranked by JD weight.
* ``actions`` gains ``prune:*`` and ``skill_reorder:*`` entries, and loses
  every ``weave_bullet:*`` entry. The latter is a reporting correction, not a
  behavior change: ``_apply_actions`` never modified bullet text, so those were
  no-ops counted as accepted changes (7 of LatentView's 17, 3 of CGI's 17).
  They are now recorded as ``ProposalStatus.NO_OP`` and still handed to PRAMANA
  as placement provenance -- see ``_ProposalRecorder.reclassify_no_ops``.
* ``score`` is unchanged on all three (43.44 / 16.83 / 50.67). Pruning is
  designed to leave PRAMANA alone: it removes only content earning no credit,
  and the acceptance rule rejects outright any removal that would lower
  coverage.

Bullet REORDER is implemented (``rachana.reordering``) but not applied; see
``generation.optimizer._apply_reordering`` for the measured reason.


from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ats_engine.generation.pipeline import run_pipeline
from ats_engine.models import Mode

FIXTURES = Path(__file__).parent / "fixtures" / "real_extraction"

# Captured from this branch after the Step 3 follow-up (CGI stuffing fix,
# CrowdPlat placement_reinforcement objective, fidelity/preservation/provenance
# alias-awareness fixes).
GOLDENS = {
    "cgi_fullstack_java_angular": {
        "actions": [
            "quality:headline",
            "mention_summary:summary:Angular",
            "mention_summary:summary:AWS",
            "mention_summary:summary:CI/CD",
            "mention_summary:summary:Docker",
            "append_skill:skills:Angular",
            "append_skill:skills:AWS",
            "append_skill:skills:CI/CD",
            "append_skill:skills:Docker",
            "append_skill:skills:front-end",
            "append_skill:skills:Hibernate",
            "headline_mention:headline:Angular",
            "headline_mention:headline:AWS",
            "headline_mention:headline:CI/CD",
            "prune:experience:3:bullet:1",
            "prune:experience:1:bullet:2",
            "skill_reorder:skills:0",
            "skill_reorder:skills:1",
            "skill_reorder:skills:2",
            "skill_reorder:skills:5",
        ],
        "score": 43.44,
        "sha256": "7b72ff873eb63da297cbe5876e28419fe9f132f24009c2a055498de5045dae24",
        "delivered_word_count": 959,
        "relevant_terms_per_100_words": 1.5641293013555788,
    },
    "crowdplat_web_scraper": {
        "actions": [
            "quality:headline",
            "quality:summary",
            "mention_summary:summary:APIs",
            "mention_summary:summary:Python",
            "append_skill:skills:Python",
            "append_skill:skills:communication",
            "headline_mention:headline:APIs",
            "headline_mention:headline:Python",
            "prune:experience:3:bullet:1",
            "prune:experience:1:bullet:2",
            "skill_reorder:skills:0",
            "skill_reorder:skills:2",
        ],
        "score": 16.83,
        "sha256": "e509dab770db394a60ef636fe85f2e5910e2ff9ebb024afcc5ba8cbe6f8ef044",
        "delivered_word_count": 954,
        "relevant_terms_per_100_words": 0.5241090146750524,
    },
    "latentview_bi_ai": {
        "actions": [
            "quality:headline",
            "append_skill:skills:SQL",
            "append_skill:skills:AI assistants",
            "headline_mention:headline:ChatGPT",
            "headline_mention:headline:Claude",
            "headline_mention:headline:GenAI",
            "surface_variant:experience:0:bullet:2:GenAI",
            "surface_variant:skills:6:1:LLMs",
            "surface_variant:experience:0:bullet:2:AI assistants",
            "surface_variant:experience:1:bullet:1:automated report generation",
            "prune:experience:3:bullet:1",
            "prune:experience:1:bullet:2",
            "skill_reorder:skills:0",
            "skill_reorder:skills:6",
        ],
        "score": 50.67,
        "sha256": "ab65f47aa79a80fcd675ed54e96bd6b60e043254089a5a9811afec535d230bc3",
        "delivered_word_count": 958,
        "relevant_terms_per_100_words": 1.0438413361169103,
    },
}


@pytest.mark.parametrize("case", sorted(GOLDENS))
def test_fixture_tailoring_matches_step3_rebaseline(case: str) -> None:
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
    assert trace.diagnostics.delivered_word_count == golden["delivered_word_count"]
    assert trace.diagnostics.relevant_terms_per_100_words_after == pytest.approx(golden["relevant_terms_per_100_words"])
