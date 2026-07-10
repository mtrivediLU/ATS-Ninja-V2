from __future__ import annotations

from ats_engine.generation.pipeline import mode_from_text
from ats_engine.models import Mode
from ats_engine.parsing.input import extract_contacts, resolve_contacts
from ats_engine.parsing.pdf import clean_extracted_text
from ats_engine.parsing.resume import extract_profile
from ats_engine.providers.base import LLMProvider
from conftest import SYNTHETIC_RESUME, WRAPPED_RESUME_TEXT, sample_profile


def test_contact_override_precedence() -> None:
    extracted = extract_contacts("Jordan Rivera\n555-201-9876\nold@example.com")
    contacts = resolve_contacts(overrides={"email": "new@example.com"}, extracted=extracted)
    assert contacts.email == "new@example.com"
    assert contacts.source["email"] == "override"


def test_extracted_resume_contact_used_when_no_override_exists() -> None:
    extracted = extract_contacts("Jordan Rivera\n705-555-1111\nresume@example.com")
    contacts = resolve_contacts(overrides={}, extracted=extracted)
    assert contacts.email == "resume@example.com"
    assert contacts.phone == "705-555-1111"


def test_no_default_identity_when_nothing_provided() -> None:
    contacts = resolve_contacts(overrides={}, extracted=extract_contacts(""))
    assert contacts.email == ""
    assert contacts.name == ""


def test_retired_profile_email_is_rejected() -> None:
    contacts = resolve_contacts(
        overrides={},
        extracted=extract_contacts("Jordan Rivera\nold@example.com"),
        profile=sample_profile(),
    )
    assert contacts.email == ""


def test_email_from_uploaded_resume_is_kept_not_blocked() -> None:
    contacts = extract_contacts(WRAPPED_RESUME_TEXT)
    resolved = resolve_contacts(overrides={}, extracted=contacts)
    assert resolved.email == "jordan.rivera@oldschool.edu"


def test_wrapped_pdf_lines_do_not_become_garbage_employers() -> None:
    profile = extract_profile(WRAPPED_RESUME_TEXT)
    companies = [experience.company for experience in profile.experiences]
    assert any("Acme Analytics" in company for company in companies)
    assert any("Beta Retail" in company for company in companies)
    for company in companies:
        assert "unified source of truth" not in company.lower()
        assert "millions of users" not in company.lower()
    first = profile.experiences[0]
    assert first.title == "Senior Data Engineer"
    assert any("millions of users" in bullet for bullet in first.bullets)


def test_pdf_extractor_merges_wrapped_continuation_lines() -> None:
    text = clean_extracted_text(
        "- Reduced engineer reporting\ntime from 5 hours to minutes and simplified workflows.\nEDUCATION"
    )
    lines = text.splitlines()
    assert lines[0].endswith("simplified workflows.")
    assert lines[1] == "EDUCATION"


def test_heuristic_extract_keeps_complete_synthetic_profile() -> None:
    profile = extract_profile(SYNTHETIC_RESUME)
    assert len(profile.experiences) == 6
    assert len(profile.education) == 2
    assert len(profile.certifications) == 4
    assert "power bi" in profile.tier_a or "power bi" in profile.tier_b or "power bi" in profile.tier_c


def test_near_empty_llm_resume_parse_falls_back_to_complete_heuristic() -> None:
    class NearEmptyProvider(LLMProvider):
        @property
        def identity(self) -> str:
            return "near-empty"

        def complete(self, prompt: str) -> str:
            return (
                '{"contact": {}, "experiences": [], "education": [], '
                '"certifications": [], "skills_listed": ["AWS"], "summary_text": ""}'
            )

    profile = extract_profile(SYNTHETIC_RESUME, provider=NearEmptyProvider())
    # The near-empty LLM parse must be rejected in favor of the complete heuristic.
    assert len(profile.experiences) == 6
    assert len(profile.education) == 2
    assert len(profile.certifications) == 4


def test_mode_detection() -> None:
    assert mode_from_text("", job_description="Python engineer role") == Mode.RESUME
    assert mode_from_text("please write a cover letter", job_description="JD") == Mode.COVER_LETTER
    assert mode_from_text("CV", job_description="JD") == Mode.COVER_LETTER
    assert mode_from_text("resume and cover letter", job_description="JD") == Mode.RESUME_AND_COVER
    assert mode_from_text("", questions=["Are you eligible to work in Canada?"]) == Mode.QUESTIONS
    assert mode_from_text("", job_description="JD", questions=["Why this role?"]) == Mode.RESUME_AND_QUESTIONS
