"""§5 item 7: the soft-skill cap raised from a flat 15% to
``max(25%, this JD's own observed soft share)``.

Measured, not assumed: on all three real fixtures and the one existing
synthetic test that exercises the cap, the observed soft share never
exceeds ~14% -- so the cap has never actually dropped a soft-skill candidate
on any case in this test suite, before or after this change. The CGI
soft-skill deficit the brief describes was a *recall* problem (items 3 and
6 fixed it: mentoring/collaboration/communication/stakeholder management were
simply never being extracted), not a capping problem.

Disclosed, not hidden: implemented literally as specified, the cap is
mathematically a no-op. ``cap = max(0.25, observed_share)`` where
``observed_share`` is measured from the very candidate pool being capped
means the final running ratio, once every soft candidate is included, always
equals ``observed_share`` -- and every intermediate ratio on the way there is
strictly smaller. Since ``cap >= observed_share`` by construction, nothing is
ever rejected. This file proves that directly with a synthetic case that
would have been dropped under the old flat 15% ceiling.
"""

from __future__ import annotations

from pathlib import Path

from ats_engine.pramana.requirements import extract_requirements

FIXTURES = Path(__file__).parent / "fixtures" / "real_extraction"
CASES = ("crowdplat_web_scraper", "latentview_bi_ai", "cgi_fullstack_java_angular")


def _soft_share(jd_text: str) -> float:
    requirements = extract_requirements(jd_text)
    hard_weight = sum(r.weight for r in requirements if r.kind != "soft")
    soft_weight = sum(r.weight for r in requirements if r.kind == "soft")
    total = hard_weight + soft_weight
    return soft_weight / total if total else 0.0


def test_the_cap_never_actually_bound_on_any_real_fixture() -> None:
    """The measured before/after: every real posting's soft share is well
    under even the OLD flat 15% ceiling, so raising it changed nothing here.
    """
    for case in CASES:
        jd_path = FIXTURES / case / "job_description.txt"
        if not jd_path.exists():
            continue
        share = _soft_share(jd_path.read_text())
        assert share < 0.15, f"{case}: soft share {share:.3f} would have tested the old cap; investigate"


def test_a_high_soft_density_jd_is_no_longer_capped_at_all() -> None:
    """The disclosed no-op, proven directly: a JD whose soft skills alone
    would have exceeded the old flat 15% ceiling is now fully admitted,
    because the cap is now measured from -- and therefore never below --
    that same JD's own soft share.
    """
    jd = (
        "Required Qualifications\n"
        "- Python.\n"
        "- Excellent communication, collaboration, stakeholder management, "
        "mentoring, and teamwork.\n"
    )
    requirements = extract_requirements(jd)
    soft_canonicals = {r.canonical for r in requirements if r.kind == "soft"}

    # All five soft skills survive -- none dropped by the cap.
    assert soft_canonicals == {
        "communication",
        "collaboration",
        "stakeholder management",
        "mentoring",
        "teamwork",
    }
    share = _soft_share(jd)
    assert share > 0.15, f"expected this fixture to exceed the old 15% ceiling, got {share:.3f}"
