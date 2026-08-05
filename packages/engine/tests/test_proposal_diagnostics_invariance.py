"""Step 3 behavioral goldens for the real extraction fixtures.

These values deliberately supersede the Step 2 baseline. ``optimizer_policy``
now defaults to ``"pareto"`` (see ``config.py``), so this change is expected
to change scores and delivered text on this branch -- that is the point of
Step 3, not a regression (``test_optimizer_policy_legacy_reproduction.py``
proves ``optimizer_policy="legacy"`` still reproduces the Step 2 baseline
exactly, label rename aside; see below).

* CGI: unchanged. ``accepted_actions``, score (42.33), and the delivered hash
  are identical to Step 2. Every proposal here -- including the two new
  surface_variant candidates this step adds -- is rejected by a pre-existing
  hard gate before pareto's own accept/reject rule is ever consulted:
  ``_source_content_plan``'s targeting sentence restates the JD title
  ("... Java + Angular ...") in the summary, pushing "java" from the
  candidate's own baseline of 4 occurrences to 5 and tripping
  ``STUFF_TERM_OCCURRENCES`` (a DEGRADE finding on the untouched source
  projection, non-fatal there, but fatal at the final, unfiltered blocker
  check) -- present on `main` before any of Step 2 or Step 3, confirmed by
  directly probing ``validate_resume_plan_findings`` on the plan with zero
  actions applied. Not fixed here: it is a source-projection/stuffing-detector
  interaction, unrelated to placement acceptance policy either way.
* CrowdPlat: score changes from 16.83 to 15.3; the delivered hash changes;
  ``accepted_actions`` drops from 8 entries to 1 (``quality:headline``,
  unaffected by policy). Measured directly, not assumed: the 6 placement
  actions pareto now rejects (``mention_summary``/``append_skill``/
  ``headline_mention`` for apis/python/communication) each show a positive
  scalar ``score_delta`` in diagnostics but a zero delta on all three pareto
  objectives. Traced to ``pramana.scoring._placement_bonus``: it awards up to
  +4 scalar points for a term appearing in *both* skills and a bullet,
  independent of whether the term was already fully credited -- these six
  terms already were, from other sections, before the action ran. Pareto's
  three objectives (coverage/adoption/density) deliberately exclude that
  bonus, since it measures readability distribution, not new JD-relevant
  content; legacy's strict-improvement rule does not distinguish the two.
  Considered and rejected: adding a flat-candidate tie-break so pareto also
  accepts these (matching legacy's count) -- measured directly against CGI,
  where it let iterations of no-real-improvement batches accumulate summary
  mentions past the stuffing budget and roll the whole run back to the source
  projection. Rejecting flat candidates outright is worse by this count, but
  strictly safer, and is what shipped.
* LatentView: score (50.67) and delivered hash are unchanged from Step 2 --
  this fixture's 9 accepted actions each move at least one pareto objective
  (a genuinely new canonical becoming visible moves coverage, adoption, and
  density together), so pareto and legacy agree on every one of them, by
  coincidence of this fixture's specific proposals rather than by
  construction. The one difference is the disclosed headline_mention rename
  below, applied to the 3 affected entries.

All three: the operation this step adds, ``SURFACE_VARIANT`` (a literal
search-and-replace of the candidate's own vocabulary-registered spelling for
the employer's exact one, `integration_planner.py`/`rachana/operations.py`),
proposes real candidates on CGI and LatentView but is accepted on none of
the three real fixtures -- see test_surface_variant_integration.py's
xfail(strict=True) for the disclosed reason (a pre-existing, unrelated named-
entity fidelity check does not yet recognize vocabulary-alias equivalence).

Also disclosed here, not a behavior change: the pre-existing ``surface_variant``
label on headline actions was a mislabeled append-to-headline mechanism (see
``integration_planner.py``'s history) -- renamed to ``headline_mention`` in
this same change so ``SURFACE_VARIANT`` unambiguously means the new literal
substitution operation everywhere it appears in diagnostics. Every accepted
action below with that label reflects the rename only; the mechanism, its
inputs, and its effect on the delivered text are byte-for-byte unchanged
(proven in ``test_optimizer_policy_legacy_reproduction.py``).

Each golden was captured from this branch via a disposable measurement script
(not copied from any brief), then cross-checked against
``python -m ats_engine.bench --json``.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ats_engine.generation.pipeline import run_pipeline
from ats_engine.models import Mode

FIXTURES = Path(__file__).parent / "fixtures" / "real_extraction"

# Captured from this branch after Step 3 (optimizer_policy defaults to "pareto").
GOLDENS = {
    "cgi_fullstack_java_angular": {
        "actions": [],
        "score": 42.33,
        "sha256": "a6d990fb152082c5c2356921aadd9c152b8a4e1286b56ede0d721db33e578d95",
    },
    "crowdplat_web_scraper": {
        "actions": [
            "quality:headline",
        ],
        "score": 15.3,
        "sha256": "6d19c4b46fa7d562c097a7ed5566c505a940412aab7f1e4e7171bb3b8725c31b",
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
        ],
        "score": 50.67,
        "sha256": "6701e19a687f522c9231f9f353d4999ff642ed31d5563ffe8c0b00b232056051",
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
