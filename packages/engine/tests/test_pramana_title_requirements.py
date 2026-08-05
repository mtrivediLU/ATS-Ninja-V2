"""Title requirement mining is explicit and isolated from body announcements."""

from ats_engine.pramana.requirements import extract_requirements


def _by_canonical(text: str):
    return {requirement.canonical: requirement for requirement in extract_requirements(text)}


def test_title_mines_known_technologies_but_not_role_or_seniority_tokens() -> None:
    jd = """Applications Development Technology Lead Analyst – React/Python AVP

Required Qualifications:
Experience designing distributed applications.
"""

    requirements = _by_canonical(jd)

    assert {"react", "python"} <= requirements.keys()
    assert {"avp", "lead", "analyst"}.isdisjoint(requirements)
    assert requirements["react"].provenance == ("title",)
    assert requirements["python"].surface == "Python"


def test_inline_title_announcement_is_not_a_title_mining_source() -> None:
    jd = """Job Title: Platform Engineer

Responsibilities:
We are seeking a Python Developer to coordinate delivery.
"""

    assert "python" not in _by_canonical(jd)


def test_title_and_body_provenance_are_merged_without_losing_body_priority() -> None:
    jd = """Python Engineer

Required Qualifications:
Strong experience with Python.
"""

    requirement = _by_canonical(jd)["python"]

    assert requirement.section == "required"
    assert requirement.provenance == ("title", "body")


def test_unknown_product_shaped_title_term_requires_body_corroboration() -> None:
    corroborated = """QuuxDB Engineer

Required Qualifications:
Experience with QuuxDB in production.
"""
    uncorroborated = """QuuxDB Engineer

Required Qualifications:
Experience with distributed databases.
"""

    assert "quuxdb" in _by_canonical(corroborated)
    assert "quuxdb" not in _by_canonical(uncorroborated)
