"""Step 3 follow-up behavioral goldens for the real extraction fixtures.

These values supersede the first Step 3 baseline (which itself superseded
Step 2 -- see git history for that rationale). This round fixes three
defects the first Step 3 pass shipped around rather than through, so all
three fixtures move:

* CGI: 0 -> 17 accepted actions (1 quality + 16 placement), score 42.33 ->
  43.44. Root cause fixed: ``_source_content_plan``'s engine-authored
  targeting clause echoes the JD title ("... Java + Angular ...") into the
  candidate's summary -- context the engine adds, never a candidate claim --
  and the anti-stuffing measurement was counting its terms toward the
  candidate's own repetition budget. That pushed "java" over its ceiling with
  zero placements applied, and then blocked every placement proposal because
  of a repetition the candidate never created. This held CGI at zero accepted
  actions across three consecutive engine steps. Fixed by excluding that
  clause from the anti-stuffing *measurement* only (``optimizer._without_targeting``);
  it is unchanged in the delivered and scored summary, where it is a
  deliberate target-title signal. See
  ``test_cgi_targeting_clause_no_longer_self_inflicts_a_stuffing_block``.
* CrowdPlat: 1 -> 8 accepted actions (2 quality + 6 placement), score 15.3 ->
  16.83 -- recovering Step 2's original count of 8. Root cause fixed:
  PRAMANA's own ``_placement_bonus`` rewards a term reinforced in both skills
  and a bullet, but that bonus never reaches ``keyword_score`` and therefore
  never reaches ``pramana_coverage`` -- pareto's original three objectives
  structurally could not see it, so they rejected every action legacy
  accepted on that basis alone as a flat, zero-objective-movement candidate.
  Fixed by giving pareto a fourth objective, ``ScoreVector.placement_reinforcement``
  (reused directly from ``PramanaScore.placement_bonus``, not recomputed).
  Considered and rejected instead: fixing the "double-award" inside
  ``_placement_bonus`` itself -- that only changes what the *legacy* scalar
  policy accepts, since ``_placement_bonus`` is excluded from
  ``pramana_coverage`` by construction; it cannot, by itself, change anything
  pareto (the default policy) accepts. See
  ``test_crowdplat_placement_reinforcement_recovers_step2_accepted_action_count``.
* LatentView: 9 -> 17 accepted actions, score unchanged at 50.67. Two
  independent, narrower defects fixed, both discovered while making
  SURFACE_VARIANT's own acceptance criterion pass for real (see below):
  ``validation/fidelity.py``'s unsupported-named-entity check is now
  vocabulary-alias-aware (``_vocabulary_alias_canonicals``), and
  ``rachana/preservation.py``'s term-preservation guard now floors a
  vocabulary-backed requirement on its alias-merged canonical presence
  (``_canonical_occurrence_counts``) rather than one dominant literal
  spelling. A third, independent bug was found in the process:
  ``pramana/scoring.py::_placement_target_text`` did not recognize the
  granular ``skills:<group>:<item>`` target a skills-tier SURFACE_VARIANT
  action carries, so its provenance check silently failed and zeroed that
  requirement's credit regardless of the substitution's own correctness.
  4 SURFACE_VARIANT actions are now genuinely accepted here (see the
  ``surface_variant:`` entries below) -- the first fixture on which this
  operation is accepted anywhere. The delivered PRAMANA score does not move,
  by design: a literal-surface substitution is defined to add no new claim
  and no new coverage, and the additional 4 ``weave_bullet`` actions
  unlocked alongside it are also scalar-neutral (each shows a 0.0 legacy
  score delta) -- they were rejected before this round purely because
  nothing in the pre-follow-up 3-objective vector could see their real
  ``jd_surface_adoption`` gain.

All three: the operation this step added, ``SURFACE_VARIANT`` (a literal
search-and-replace of the candidate's own vocabulary-registered spelling for
the employer's exact one, `integration_planner.py`/`rachana/operations.py`),
is now genuinely accepted on a real fixture (LatentView, 4 actions) with zero
fact loss -- see ``test_surface_variant_integration.py``, whose
``xfail(strict=True)`` for the two fidelity/preservation defects above is
removed.

Also unchanged from the first Step 3 baseline, restated for continuity: the
pre-existing ``surface_variant`` label on headline actions was a mislabeled
append-to-headline mechanism, renamed to ``headline_mention``. Every accepted
action below with that label reflects the rename only.

Each golden was captured from this branch via a disposable measurement
script (not copied from any brief), then cross-checked against
``python -m ats_engine.bench --json``.

``delivered_word_count``/``relevant_terms_per_100_words`` golden addendum:
the latter is this codebase's "density" -- see ``RunDiagnostics`` and
``rachana.objectives.ScoreVector.density``, the same function
(``relevant_terms_per_100_words``) applied to the same requirement set: the
count of distinct requirement canonicals visibly expressed, per 100 words.
Both were captured from ``trace.diagnostics`` on this branch, then compared
against the same two fixture files run through ``origin/main`` (commit
``4800900``, predating Step 1 through this follow-up entirely -- the state
before any of the tailoring-engine work in this docstring existed) via a
disposable ``git worktree`` with ``PYTHONPATH`` pointed at its own
``packages/engine/src``, mirroring the method already used to verify the CGI
golden hash. The override was confirmed genuine rather than a stale cache by
checking that ``ats_engine.__file__`` resolves inside the worktree, that
``ats_engine.rachana.operations`` (SURFACE_VARIANT's module) cannot import
there at all, and that the two runs' ``accepted_actions`` differ materially
rather than coincidentally matching:

* CGI: main delivers 1002 words at density 1.497006 (0 accepted actions on
  main -- the stuffing-block bug held it at zero even there, so delivered
  text equals source verbatim) versus this branch's 1004 words at density
  1.494024. **Density fell, -0.0030.** The distinct-canonical count behind
  the ratio is unchanged at 15 in both runs (15/1002*100 == 15/1004*100 up to
  the word-count difference); the fall is denominator dilution from this
  branch's own +2 net delivered words -- the footprint of 17 now-accepted,
  gate-passed actions where main accepted none -- not a coverage loss.
  Flagged rather than resolved, per instruction: no engine code changed to
  produce or address this number.
* CrowdPlat: main delivers 997 words at density 0.501505 (8 actions: a
  pre-rename ``surface_variant:headline:*`` -- today's ``headline_mention`` --
  plus mostly the same APIs/Python/communication placements as this branch's
  own golden above) versus this branch's 999 words at density 0.500501.
  **Density fell, -0.0010.** Same root cause: the distinct-canonical count
  is unchanged at 5 in both runs; main's 8 actions and this branch's 8 cover
  materially the same requirements through a slightly different operation
  mix (a ``quality:summary`` rewrite here versus an extra ``mention_summary``
  there), and this branch's version is 2 words longer. Flagged, not
  baselined, for the same reason as CGI.
* LatentView: main delivers 1003 words at density 0.997009 (9 actions)
  versus this branch's 1003 words at density 0.997009. **Unchanged.** Main's
  9 actions are a strict subset of this branch's 17 (the same 3 headline
  mentions and the same 3 ``weave_bullet`` insertions, pre-rename); this
  branch's 4 additional ``weave_bullet`` insertions and 4 SURFACE_VARIANT
  substitutions net to exactly zero combined word delta on this fixture.

CGI and CrowdPlat's falls are reported, not adjudicated: nothing above should
be read as "the regression is fine," only as "this is what was measured, and
why, without changing engine code to move it." See the PR discussion for the
disposition.
"""

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
            "weave_bullet:experience:5:bullet:3:CI/CD",
            "weave_bullet:experience:1:bullet:0:front-end",
            "weave_bullet:experience:5:bullet:1:Java",
        ],
        "score": 43.44,
        "sha256": "516de792a643e5c43f5e9e3e5d7cc23a6ea0cc30ae565eef537557764e217cc0",
        "delivered_word_count": 1004,
        "relevant_terms_per_100_words": 1.4940239043824703,
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
        ],
        "score": 16.83,
        "sha256": "401a0be48b943f1f09213234a94c34100a9db1bf686a64dc5d36f5b687c13c33",
        "delivered_word_count": 999,
        "relevant_terms_per_100_words": 0.5005005005005005,
    },
    "latentview_bi_ai": {
        "actions": [
            "quality:headline",
            "append_skill:skills:SQL",
            "append_skill:skills:AI assistants",
            "headline_mention:headline:ChatGPT",
            "headline_mention:headline:Claude",
            "headline_mention:headline:GenAI",
            "weave_bullet:experience:0:bullet:2:GenAI",
            "weave_bullet:experience:2:bullet:0:SQL",
            "weave_bullet:experience:0:bullet:2:AI assistants",
            "weave_bullet:experience:1:bullet:1:automated report generation",
            "weave_bullet:experience:2:bullet:2:business intelligence",
            "weave_bullet:experience:0:bullet:3:dashboards",
            "weave_bullet:experience:2:bullet:0:communication",
            "surface_variant:experience:0:bullet:2:GenAI",
            "surface_variant:skills:6:1:LLMs",
            "surface_variant:experience:0:bullet:2:AI assistants",
            "surface_variant:experience:1:bullet:1:automated report generation",
        ],
        "score": 50.67,
        "sha256": "928f9005effaf547b7878802469afbdda0c919a48ebbc10922f45c8ed4e5a7de",
        "delivered_word_count": 1003,
        "relevant_terms_per_100_words": 0.9970089730807578,
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
