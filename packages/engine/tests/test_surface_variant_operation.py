"""§Task 2: the SURFACE_VARIANT primitives in ``rachana/operations.py``.

Unit-level, deliberately below the optimizer: proves the substitution
mechanics -- hazard avoidance, fact safety, idempotence, reversibility --
hold against hand-built ``EvidenceLink``/text inputs before anything wires
this into planning or acceptance.
"""

from __future__ import annotations

from ats_engine.models import EvidenceLink, RequirementTerm
from ats_engine.rachana.operations import (
    SurfaceVariantMatch,
    SurfaceVariantRejection,
    SurfaceVariantResult,
    find_surface_variant,
    substitute_surface_variant,
)


def _requirement(canonical: str, surface: str, **kwargs: object) -> RequirementTerm:
    defaults: dict[str, object] = {
        "aliases": (),
        "kind": "tool",
        "section": "required",
        "weight": 2.0,
        "ngram": 1,
        "category": "framework",
        "jd_evidence_line": surface,
    }
    defaults.update(kwargs)
    return RequirementTerm(canonical=canonical, surface=surface, **defaults)  # type: ignore[arg-type]


def _link(
    requirement: RequirementTerm, span: str, *, tier: str = "A", location: str = "experience:0:bullet:0"
) -> EvidenceLink:
    return EvidenceLink(requirement=requirement, tier=tier, resume_span=span, resume_location=location)


def test_a_registered_alias_is_found_and_substituted() -> None:
    requirement = _requirement("react", "ReactJS")
    link = _link(requirement, "Built dashboards using React and Redux.")
    variant = find_surface_variant(link)
    assert variant is not None
    assert variant.original == "React"
    assert variant.target_surface == "ReactJS"

    result = substitute_surface_variant("Built dashboards using React and Redux.", variant)
    assert isinstance(result, SurfaceVariantResult)
    assert result.changed
    assert result.text == "Built dashboards using ReactJS and Redux."


def test_no_variant_when_the_candidate_already_uses_the_jd_surface() -> None:
    requirement = _requirement("react", "ReactJS")
    link = _link(requirement, "Built dashboards using ReactJS and Redux.")
    assert find_surface_variant(link) is None


def test_no_variant_when_the_requirement_is_not_vocabulary_backed() -> None:
    requirement = _requirement("bespoke-internal-tool-xyz", "BespokeInternalToolXYZ")
    link = _link(requirement, "Operated BespokeTool daily.")
    assert find_surface_variant(link) is None


def test_react_is_never_rewritten_inside_react_native() -> None:
    """The exact hazard named in the brief: React must never rewrite inside React Native."""
    requirement = _requirement("react", "ReactJS")
    link = _link(requirement, "Shipped mobile features in React Native.")
    assert find_surface_variant(link) is None


def test_sql_is_never_rewritten_inside_postgresql_or_nosql() -> None:
    requirement = _requirement("sql", "Structured Query Language")
    for span in ("Tuned PostgreSQL queries for latency.", "Migrated a NoSQL store to a relational one."):
        link = _link(requirement, span)
        assert find_surface_variant(link) is None


def test_substitution_never_alters_a_metric_in_the_same_text() -> None:
    variant = SurfaceVariantMatch(canonical="react", original="React", target_surface="ReactJS")
    result = substitute_surface_variant("Reduced React load time by 40%.", variant)
    assert isinstance(result, SurfaceVariantResult)
    assert result.text == "Reduced ReactJS load time by 40%."


def test_a_contrived_metric_shaped_target_fails_closed_on_fact_risk() -> None:
    """Unit-level proof the fact-risk gate itself works, using a target surface
    engineered to be metric-shaped -- real vocabulary aliases never are, so
    this is tested directly against the function rather than through discovery."""
    variant = SurfaceVariantMatch(canonical="react", original="React", target_surface="40%")
    result = substitute_surface_variant("Built dashboards using React and Redux.", variant)
    assert isinstance(result, SurfaceVariantRejection)
    assert result.reason == "fact_risk"


def test_applying_twice_is_a_no_op_the_second_time() -> None:
    variant = SurfaceVariantMatch(canonical="react", original="React", target_surface="ReactJS")
    first = substitute_surface_variant("Built dashboards using React and Redux.", variant)
    assert isinstance(first, SurfaceVariantResult) and first.changed
    second = substitute_surface_variant(first.text, variant)
    assert isinstance(second, SurfaceVariantResult)
    assert not second.changed
    assert second.text == first.text


def test_swapping_original_and_target_exactly_reverses_a_substitution() -> None:
    variant = SurfaceVariantMatch(canonical="react", original="React", target_surface="ReactJS")
    forward = substitute_surface_variant("Built dashboards using React and Redux.", variant)
    assert isinstance(forward, SurfaceVariantResult)

    inverse = SurfaceVariantMatch(canonical="react", original="ReactJS", target_surface="React")
    backward = substitute_surface_variant(forward.text, inverse)
    assert isinstance(backward, SurfaceVariantResult)
    assert backward.text == "Built dashboards using React and Redux."


def test_text_drifted_since_planning_fails_closed_instead_of_guessing() -> None:
    """If the field no longer contains what was matched at plan time -- for
    example a different accepted action already rewrote it -- substitution
    must refuse rather than silently touch the wrong span."""
    variant = SurfaceVariantMatch(canonical="react", original="React", target_surface="ReactJS")
    result = substitute_surface_variant("Built dashboards using Vue and Redux.", variant)
    assert isinstance(result, SurfaceVariantRejection)
    assert result.reason == "text_drifted"


def test_tier_c_skills_list_evidence_is_eligible() -> None:
    requirement = _requirement("kubernetes", "Kubernetes")
    link = _link(requirement, "K8s", tier="C", location="skills:0:2")
    variant = find_surface_variant(link)
    assert variant is not None
    assert variant.original == "K8s"
    assert variant.target_surface == "Kubernetes"


def test_certificate_and_adjacency_tiers_are_never_eligible() -> None:
    requirement = _requirement("react", "ReactJS")
    for tier in ("cert", "adjacency", "missing"):
        link = _link(requirement, "React", tier=tier, location="certification")
        assert find_surface_variant(link) is None
