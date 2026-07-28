from __future__ import annotations

import json

import pytest

from ats_engine import application_kit_to_dict, generate_application_kit
from ats_engine.models import Mode
from ats_engine.parsing.resume import extract_profile
from ats_engine.providers.base import LLMProvider

RESUME = """\
Avery Doe
avery@example.com | linkedin.com/in/averydoe | Toronto, ON

PROFESSIONAL EXPERIENCE
Cedar Labs | Toronto, ON
Analyst | 2020 - 2024
- Built Python dashboards for operations teams.
- Reduced reporting time by 20%.

Birch Systems | Ottawa, ON
Data Engineer | 2018 - 2020
- Built SQL pipelines for finance reporting.

EDUCATION
Lakeview University | Toronto, ON
Bachelor of Commerce | 2014 - 2018

CERTIFICATIONS
Microsoft Power BI Data Analyst (PL-300) | 2024 | Credential ID: SOURCE-123
"""

JD = """\
Data Analyst
Northwind Services
Required: Python, SQL, dashboards, and stakeholder reporting.
"""


class _FabricatingExtractionProvider(LLMProvider):
    def __init__(self, identity_suffix: str) -> None:
        self._identity_suffix = identity_suffix
        self.calls: list[str] = []

    @property
    def identity(self) -> str:
        return f"fabricating-resume-extractor:provider-floor-v1:{self._identity_suffix}"

    def complete(self, prompt: str) -> str:
        self.calls.append(prompt)
        if "Numbered resume lines:" not in prompt:
            return "{}"
        return json.dumps(
            {
                "contact": {
                    "name": "Mallory Example",
                    "email": "attacker@example.net",
                    "phone": "555-555-0199",
                    "linkedin": "linkedin.com/in/mallory",
                    "website": "https://fabricated.example",
                    "location": "Moon Base",
                },
                "experiences": [
                    {
                        "company": "Cedar Labs",
                        # This title and one bullet occur in the raw resume, but
                        # only under a different role. They must not be moved.
                        "title": "Data Engineer",
                        "location": "Moon Base",
                        "dates": "1900 - 2099",
                        "bullets": [
                            "Built Python dashboards for operations teams.",
                            "Built SQL pipelines for finance reporting.",
                            "Managed 500 engineers.",
                        ],
                    },
                    {
                        "company": "Birch Systems",
                        "title": "Chief AI Officer",
                        "location": "Mars",
                        "dates": "2099 - Present",
                        "bullets": ["Built SQL pipelines for finance reporting."],
                    },
                ],
                "education": [
                    {
                        "institution": "Lakeview University",
                        "degree": "PhD in Artificial Intelligence",
                        "location": "Cambridge, MA",
                        "dates": "2015 - 2019",
                        "bullets": ["Published 50 research papers."],
                    },
                    {
                        "institution": "Harvard University",
                        "degree": "MBA",
                        "location": "Boston, MA",
                        "dates": "2020 - 2022",
                        "bullets": [],
                    },
                ],
                "certifications": [
                    {
                        "name": "Microsoft Power BI Data Analyst (PL-300)",
                        "date": "2025",
                        "link": "https://fabricated.example/certificate",
                        "credential_id": "FABRICATED-999",
                    },
                    {
                        "name": "AWS Certified Solutions Architect",
                        "date": "2025",
                        "link": "https://fabricated.example/aws",
                        "credential_id": "AWS-FAKE",
                    },
                ],
                "skills_listed": ["Python", "Kubernetes", "Rust"],
                "summary_text": "Chief AI Officer with 20 years of experience.",
            }
        )


def test_provider_resume_parse_cannot_create_or_misattribute_candidate_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATS_ENGINE_LLM_CACHE", "0")
    provider = _FabricatingExtractionProvider("parse")
    profile = extract_profile(RESUME, provider=provider)

    assert any("Numbered resume lines:" in prompt for prompt in provider.calls)
    assert profile.contact.name == "Avery Doe"
    assert profile.contact.email == "avery@example.com"
    assert profile.role_identities == ["Analyst", "Data Engineer"]

    assert [(entry.company, entry.title, entry.location, entry.dates) for entry in profile.experiences] == [
        ("Cedar Labs", "Analyst", "Toronto, ON", "2020 - 2024"),
        ("Birch Systems", "Data Engineer", "Ottawa, ON", "2018 - 2020"),
    ]
    assert profile.experiences[0].bullets == [
        "Built Python dashboards for operations teams.",
        "Reduced reporting time by 20%.",
    ]
    assert profile.experiences[1].bullets == ["Built SQL pipelines for finance reporting."]

    assert len(profile.education) == 1
    assert profile.education[0].institution == "Lakeview University"
    assert profile.education[0].degree == "Bachelor of Commerce"
    assert len(profile.certifications) == 1
    assert profile.certifications[0].name == "Microsoft Power BI Data Analyst (PL-300)"
    assert profile.certifications[0].date == "2024"
    assert profile.certifications[0].credential_id == "SOURCE-123"
    assert profile.certifications[0].link == ""

    all_skills = profile.tier_a | profile.tier_b | profile.tier_c
    assert all_skills["python"] == "Python"
    assert "kubernetes" not in all_skills
    assert "rust" not in all_skills

    rendered = repr(profile).lower()
    for fabrication in (
        "mallory",
        "moon base",
        "chief ai officer",
        "managed 500",
        "phd",
        "harvard",
        "aws certified",
        "fabricated-999",
    ):
        assert fabrication not in rendered


def test_fabricated_extraction_fields_never_reach_the_application_kit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATS_ENGINE_LLM_CACHE", "0")
    provider = _FabricatingExtractionProvider("kit")
    kit = generate_application_kit(
        resume_text=RESUME,
        job_description=JD,
        default_mode=Mode.RESUME,
        include_resume=True,
        include_cover_letter=False,
        include_application_answers=False,
        include_job_fit=False,
        include_interview_prep=False,
        include_linkedin_outreach=False,
        use_llm=True,
        extraction_provider=provider,
    )

    assert any("Numbered resume lines:" in prompt for prompt in provider.calls)
    assert kit.resume is not None
    assert not kit.validation.fatal
    assert kit.resume.validation.rejected_claims == 0
    assert "Cedar Labs" in kit.resume.text
    assert "Analyst" in kit.resume.text
    assert "Python" in kit.resume.text
    assert "20%" in kit.resume.text
    assert "Bachelor of Commerce" in kit.resume.text
    assert "SOURCE-123" in kit.resume.text

    delivered = json.dumps(application_kit_to_dict(kit)).lower()
    for fabrication in (
        "mallory",
        "attacker@example.net",
        "moon base",
        "chief ai officer",
        "managed 500",
        "phd in artificial intelligence",
        "harvard university",
        "aws certified solutions architect",
        "kubernetes",
        "rust",
        "fabricated-999",
        "https://fabricated.example",
    ):
        assert fabrication not in delivered
