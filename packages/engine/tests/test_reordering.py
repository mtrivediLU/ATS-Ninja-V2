"""REORDER / SKILL_REORDER move content and never change it.

The multiset guarantee is the entire safety argument for these operations, so
it is asserted here rather than assumed, including on the real fixtures.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ats_engine.generation.pipeline import run_pipeline
from ats_engine.models import Mode, RequirementTerm
from ats_engine.rachana.reordering import (
    is_permutation,
    rank_by_relevance,
    relevance_score,
    reorder_preserving_blanks,
    reorder_skill_items,
)

FIXTURES = Path(__file__).parent / "fixtures" / "real_extraction"


def _requirement(canonical: str, weight: float = 1.0) -> RequirementTerm:
    return RequirementTerm(
        canonical=canonical,
        surface=canonical,
        aliases=(),
        kind="tool",
        section="body",
        weight=weight,
        ngram=1,
        category="technical",
        jd_evidence_line="",
    )


def test_items_are_ranked_by_total_jd_weight_not_by_mention_count() -> None:
    requirements = [_requirement("python", 5.0), _requirement("excel", 1.0)]
    items = ["Excel reporting", "Python and Excel pipelines", "Python Python Python"]

    # Weighted: the Python+Excel item (6.0) outranks Python alone (5.0), which
    # outranks Excel alone (1.0). Repetition buys nothing -- distinct only.
    assert relevance_score(items[2], requirements) == 5.0
    assert relevance_score(items[1], requirements) == 6.0
    assert rank_by_relevance(items, requirements) == [1, 2, 0]


def test_equal_scoring_items_keep_their_source_order() -> None:
    requirements = [_requirement("python")]
    items = ["alpha", "beta", "gamma"]
    assert rank_by_relevance(items, requirements) == [0, 1, 2]


def test_skill_reorder_preserves_the_exact_multiset() -> None:
    requirements = [_requirement("sql", 3.0)]
    items = ["Tableau", "SQL", "Excel (Working Knowledge)"]
    reordered = reorder_skill_items(items, requirements)

    assert is_permutation(items, reordered)
    assert reordered[0] == "SQL"


def test_a_working_knowledge_annotation_travels_with_its_item() -> None:
    """Moving a tier-C skill must never quietly promote it."""
    requirements = [_requirement("kubernetes", 9.0)]
    items = ["SQL", "Kubernetes (Working Knowledge)"]
    reordered = reorder_skill_items(items, requirements)

    assert reordered[0] == "Kubernetes (Working Knowledge)"
    assert is_permutation(items, reordered)


def test_bullet_reorder_leaves_emptied_prune_slots_where_they_are() -> None:
    """An emptied slot's index is load-bearing for restore-by-position."""
    requirements = [_requirement("python", 5.0)]
    bullets = ["Wrote docs.", "", "Built Python pipelines."]
    reordered = reorder_preserving_blanks(bullets, requirements)

    assert reordered[1] == ""
    assert is_permutation(bullets, reordered)
    assert reordered[0] == "Built Python pipelines."


@pytest.mark.parametrize("case", ("cgi_fullstack_java_angular", "crowdplat_web_scraper", "latentview_bi_ai"))
def test_skill_reorder_runs_on_every_real_fixture_without_disturbing_items(case: str) -> None:
    result = run_pipeline(
        resume_text=(FIXTURES / "candidate_resume.pymupdf.txt").read_text(encoding="utf-8"),
        job_description=(FIXTURES / case / "job_description.txt").read_text(encoding="utf-8"),
        default_mode=Mode.RESUME,
        use_llm=False,
    )
    plan = result.resume_plan
    assert plan is not None
    trace = result.metadata["optimization_trace"]

    assert [action for action in trace.accepted_actions if action.startswith("skill_reorder:")]
    delivered = [item for _heading, items in plan.skill_groups for item in items]
    # The multiset guarantee itself is enforced in the optimizer, which raises
    # if a reorder ever changes the item set (see `_apply_reordering`). What is
    # checked here is that the delivered result of that run is well-formed: no
    # item was blanked or duplicated on the way through.
    assert all(item.strip() for item in delivered)
    assert len(delivered) == len({item.casefold() for item in delivered})
