"""§6 items 4-5: preposition fragments never become requirements, and an
employer's own name is never mined as one.

The fragment shape is real and live: `_parenthetical_items` splits
"(including EKS, S3, and Lambda)" on commas, and only strips a leading
"and"/"or" from later members -- the FIRST member keeps its leading
preposition ("including EKS") unless something rejects it downstream. Proven
here against an unlisted term so the fix is not just riding on the term
already being a vocabulary match (which would mask a broken guard).
"""

from __future__ import annotations

from ats_engine.pramana.requirements import extract_requirements


def test_a_parenthetical_enumerations_first_member_drops_its_preposition() -> None:
    jd = (
        "Required Qualifications\n"
        "- Build and deploy applications using modern platforms "
        "(including Quantum Analytics, Zephyr Reporting).\n"
    )
    canonicals = {r.canonical for r in extract_requirements(jd)}

    assert "quantum analytics" in canonicals
    assert "including quantum analytics" not in canonicals
    assert not any(c.startswith("including ") for c in canonicals)


def test_such_as_using_and_with_prefixes_are_all_rejected() -> None:
    jd = (
        "Required Qualifications\n"
        "- Familiar with modern platforms (such as Quantum Analytics, using Zephyr Reporting, "
        "with Nimbus Dashboards).\n"
    )
    canonicals = {r.canonical for r in extract_requirements(jd)}

    for prefix in ("such as ", "such ", "using ", "with "):
        assert not any(c.startswith(prefix) for c in canonicals), (
            f"a candidate kept the {prefix!r} prefix: {canonicals}"
        )


def test_real_cgi_eks_s3_lambda_extract_without_the_leading_preposition() -> None:
    """The exact §4 shape, against the real posting."""
    from pathlib import Path

    jd = (
        Path(__file__).parent / "fixtures" / "real_extraction" / "cgi_fullstack_java_angular" / "job_description.txt"
    ).read_text()
    requirements = extract_requirements(jd)
    canonicals = {r.canonical for r in requirements}
    surfaces = {r.surface for r in requirements}

    assert not any(c.startswith(("including ", "such as ", "using ", "with ")) for c in canonicals)
    assert not any(s.lower().startswith(("including ", "such as ", "using ", "with ")) for s in surfaces)
    assert "eks" in canonicals
    assert "s3" in canonicals


def test_the_extracted_employer_name_is_never_mined_as_a_requirement() -> None:
    """CGI itself must never appear as a requirement (§4's documented defect)."""
    from pathlib import Path

    jd = (
        Path(__file__).parent / "fixtures" / "real_extraction" / "cgi_fullstack_java_angular" / "job_description.txt"
    ).read_text()
    canonicals = {r.canonical for r in extract_requirements(jd)}

    assert "cgi" not in canonicals
