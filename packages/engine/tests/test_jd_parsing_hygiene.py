"""Deterministic JD hygiene regressions using synthetic posting text only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ats_engine.models import JDProfile
from ats_engine.parsing.jd_requirements import extract_requirements, sanitize_jd_for_parsing
from ats_engine.parsing.job_description import parse_jd
from ats_engine.providers.base import LLMProvider


@pytest.mark.parametrize(
    "stop_heading",
    [
        "How to Apply:",
        "Human Resources:",
        "Salary Range: $90,000 to $110,000",
        "Duration: 12 months",
        "Equal Opportunity Employer",
    ],
)
def test_post_qualification_stop_sections_and_contact_lines_are_not_scored(stop_heading: str) -> None:
    jd = f"""Job Title: IT Specialist to support public programs and
Company: ClaimSecure
Required Qualifications:
- Experience with Python, SQL, and ClaimSecure Claims Platform.
{stop_heading}
Apply at jobs@claimsecure.example, https://claimsecure.example/careers, or 416-555-1234.
- Rust and Kubernetes are mentioned after the application closing section.
"""

    hygiene = sanitize_jd_for_parsing(jd)
    parsed = parse_jd(jd)
    requirements = {item.canonical for item in extract_requirements(jd)}
    keyword_text = " ".join(parsed.technical_keywords).casefold()

    assert parsed.title == "IT Specialist"
    assert parsed.company == "ClaimSecure"
    assert "python" in requirements and "sql" in requirements
    assert "rust" not in requirements and "kubernetes" not in requirements
    assert "claimsecure" not in " ".join(requirements)
    assert "claimsecure" not in keyword_text
    assert "rust" not in keyword_text and "kubernetes" not in keyword_text
    assert all("@" not in line and "http" not in line and "555" not in line for line in hygiene.scoring_lines)
    assert hygiene.application_domains == ("claimsecure.example",)


@pytest.mark.parametrize(
    ("jd", "expected"),
    [
        (
            """Job Title: Data Engineer
Company: Explicit Systems
About ClaimSecure
The Fallback Trust is seeking a Data Engineer.
Required Qualifications:
- Python
""",
            "Explicit Systems",
        ),
        (
            """Job Title: Data Engineer
About ClaimSecure
The Fallback Trust is seeking a Data Engineer.
Required Qualifications:
- Python
Apply at jobs@fallback.example
""",
            "ClaimSecure",
        ),
        (
            """Job Title: Data Engineer
Required Qualifications:
- Python
Apply at jobs@clearwater.example
The Fallback Trust is seeking a Data Engineer.
""",
            "Clearwater",
        ),
        (
            """Job Title: Data Engineer
The Meridian Trust is seeking a Data Engineer.
Required Qualifications:
- Python
""",
            "Meridian Trust",
        ),
    ],
)
def test_company_resolution_uses_deterministic_priority(jd: str, expected: str) -> None:
    assert parse_jd(jd).company == expected


def test_person_and_org_role_phrases_do_not_become_company_or_requirements() -> None:
    jd = """Job Title: Data Engineer
About Jane Smith
The Hiring Manager is seeking a Data Engineer.
Required Qualifications:
- Experience with Jane Smith, ClaimSecure Claims Platform, Python, and SQL.
"""

    parsed = parse_jd(jd)
    requirements = {item.canonical for item in extract_requirements(jd)}

    assert parsed.company == "Target Company"
    assert {"python", "sql"} <= requirements
    assert not any("jane" in item or "claimsecure" in item or "platform" in item for item in requirements)


class _NoisyJDProvider(LLMProvider):
    @property
    def identity(self) -> str:
        return "test-noisy-jd-hygiene-provider"

    def complete(self, _prompt: str) -> str:
        return json.dumps(
            {
                "title": "Director to lead fabricated programs",
                "company": "Hiring Manager",
                "required_qualification_lines": [5],
                "preferred_qualification_lines": [],
                "responsibility_lines": [],
                "technical_keywords": [
                    "Python",
                    "ClaimSecure Claims Platform",
                    "Jane Smith",
                    "https://claimsecure.example/careers",
                    "Rust",
                ],
                "work_mode": "unknown",
                "location": "",
                "domain": "",
                "ats_platform": "unknown",
            }
        )


def test_llm_merge_uses_the_same_hygiene_boundary() -> None:
    jd = """Job Title: Data Engineer
Company: ClaimSecure
Required Qualifications:
- Experience with Python and SQL.
How to Apply:
Email jobs@claimsecure.example or visit https://claimsecure.example/careers.
"""

    parsed = parse_jd(jd, provider=_NoisyJDProvider())
    keyword_text = " ".join(parsed.technical_keywords).casefold()

    assert parsed.title == "Data Engineer"
    assert parsed.company == "ClaimSecure"
    assert "python" in keyword_text and "sql" in keyword_text
    assert not any(value in keyword_text for value in ("claimsecure", "jane", "rust", "http"))
    assert all("apply" not in value.casefold() for value in parsed.required_qualifications)


def test_coo_target_identity_and_parse_confidence_are_exact_and_additive() -> None:
    jd = (Path(__file__).parent / "fixtures" / "coo_it_specialist" / "job_description.txt").read_text(encoding="utf-8")

    parsed = parse_jd(jd)

    assert parsed.title == "IT Specialist – Economic Development"
    assert parsed.company == "Chiefs of Ontario"
    assert parsed.parse_confidence == 1.0
    assert "Chiefs of Ontario is seeking" in " ".join(parsed.organizational_boilerplate)
    assert JDProfile().parse_confidence == 0.0


def test_contact_role_heading_does_not_outrank_the_actual_standalone_title() -> None:
    parsed = parse_jd(
        """Hiring Manager
IT Administrator
Required Qualifications:
- Windows Server
"""
    )

    assert parsed.title == "IT Administrator"


def test_explicit_hiring_manager_job_title_remains_supported() -> None:
    parsed = parse_jd(
        """Job Title: Hiring Manager
Company: Example People Co.
Required Qualifications:
- Recruiting operations
"""
    )

    assert parsed.title == "Hiring Manager"


def test_post_application_tail_cannot_supply_a_target_company() -> None:
    parsed = parse_jd(
        """Job Title: Data Engineer
Required Qualifications:
- Python and SQL
How to Apply:
The TalentForge Group is seeking excellent applicants.
"""
    )

    assert parsed.company == "Target Company"


def test_post_responsibility_application_tail_cannot_supply_a_target_company() -> None:
    parsed = parse_jd(
        """Job Title: Data Engineer
Responsibilities:
- Build Python data pipelines.
How to Apply:
Company: TalentForge Group
"""
    )

    assert parsed.company == "Target Company"
    assert not any("talentforge" in item.casefold() for item in parsed.technical_keywords)


def test_key_responsibilities_keeps_cue_less_typed_requirements_in_section() -> None:
    requirements = extract_requirements(
        """Job Title: Systems Analyst
Key Responsibilities:
- Root-cause analysis and technical documentation for production incidents.
How to Apply:
- Rust experience is helpful for the recruiting portal.
"""
    )
    by_canonical = {requirement.canonical: requirement for requirement in requirements}

    assert by_canonical["root cause analysis"].section == "responsibility"
    assert by_canonical["technical documentation"].section == "responsibility"
    assert "rust" not in by_canonical


def test_contact_bearing_stop_line_still_closes_the_target_and_scoring_views() -> None:
    parsed = parse_jd(
        """Job Title: Data Engineer
Required Qualifications:
- Python and SQL
Send a resume to jobs@talentforge.example.
The TalentForge Group is seeking excellent applicants.
"""
    )

    assert parsed.company == "Talentforge"
    assert not any("talentforge group" in item.casefold() for item in parsed.technical_keywords)
