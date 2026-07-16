from __future__ import annotations

import hashlib
import json
import unicodedata

import pytest

from ats_engine import (
    Mode,
    OutreachAudience,
    OutreachContext,
    OutreachIntent,
    RequirementClassification,
    application_kit_from_dict,
    application_kit_to_dict,
    generate_application_kit,
)
from ats_engine.providers import LLMProvider

OUTREACH_RESUME = (
    "Morgan Lee\n"
    "PROFESSIONAL EXPERIENCE\n"
    "Harbor Data Toronto, ON\n"
    "Data Analyst 2021 - 2025\n"
    "- Built Python and SQL pipelines, reducing reporting time by 30%.\n"
    "- Supported Project Orion for client Redwood with a team of 5 and delivered Tableau dashboards.\n"
    "EDUCATION\n"
    "Metro University Ottawa, ON\n"
    "Bachelor of Computer Science 2015 - 2019\n"
    "TECHNICAL SKILLS\n"
    "Kubernetes\n"
    "CERTIFICATIONS\n"
    "Certified Data Foundations 2024\n"
)

OUTREACH_JD = (
    "Job Title: Director of Platform\n"
    "Company: Vantage Analytics\n"
    "Required qualifications:\n"
    "- Python\n- SQL\n- Power BI\n- Kubernetes\n- Rust\n"
    "Responsibilities:\n- Build analytics platforms and partner with stakeholders.\n"
    "The team uses Python, SQL, Power BI, Kubernetes, and Rust.\n"
)


class OutreachProvider(LLMProvider):
    def __init__(self, strategy: str) -> None:
        self.strategy = strategy
        self._identity = "outreach:" + hashlib.sha256(strategy.encode()).hexdigest()[:12]

    @property
    def identity(self) -> str:
        return self._identity

    def complete(self, prompt: str) -> str:
        return self.strategy if "LINKEDIN OUTREACH STRATEGY" in prompt else ""


def _kit(
    *,
    provider: LLMProvider | None = None,
    context: OutreachContext | None = None,
    include_job_fit: bool = True,
    include_interview_prep: bool = True,
    include_linkedin_outreach: bool = True,
) -> object:
    return generate_application_kit(
        resume_text=OUTREACH_RESUME,
        job_description=OUTREACH_JD,
        default_mode=Mode.RESUME,
        use_llm=provider is not None,
        prose_provider=provider,
        include_job_fit=include_job_fit,
        include_interview_prep=include_interview_prep,
        include_linkedin_outreach=include_linkedin_outreach,
        outreach_context=context,
    )


def _artifact_text(kit: object) -> str:
    artifact = kit.linkedin_outreach
    assert artifact is not None
    return "\n".join([artifact.strategy_summary] + [draft.text for draft in artifact.drafts]).casefold()


def test_provider_none_builds_complete_useful_outreach() -> None:
    artifact = _kit().linkedin_outreach
    assert artifact is not None
    assert artifact.strategy_summary
    assert {draft.id for draft in artifact.drafts} >= {
        "recruiter-connection",
        "hiring-manager-connection",
        "targeted-direct-message",
        "employee-informational",
    }
    assert {draft.audience for draft in artifact.drafts} >= {
        OutreachAudience.RECRUITER,
        OutreachAudience.HIRING_MANAGER,
        OutreachAudience.EMPLOYEE,
    }
    assert all(draft.text and draft.call_to_action in draft.text for draft in artifact.drafts)
    assert all(draft.character_count == len(draft.text) for draft in artifact.drafts)
    assert all(draft.character_count <= draft.character_limit for draft in artifact.drafts)
    assert artifact.validation.fatal is False
    assert artifact.consistency.passed
    assert artifact.relationship_validation.passed
    assert artifact.claims
    assert all(len(ref.excerpt) <= 160 for ref in artifact.evidence)


def test_outreach_is_independently_selectable() -> None:
    outreach_only = _kit(include_job_fit=False, include_interview_prep=False)
    disabled = _kit(include_linkedin_outreach=False)
    assert outreach_only.job_fit is None
    assert outreach_only.interview_prep is None
    assert outreach_only.linkedin_outreach is not None
    assert disabled.job_fit is not None
    assert disabled.interview_prep is not None
    assert disabled.linkedin_outreach is None


def test_v4_json_round_trip_preserves_typed_outreach() -> None:
    kit = _kit()
    raw = application_kit_to_dict(kit)
    assert raw["schema_version"] == "application-kit/v4"
    assert raw["linkedin_outreach"]["drafts"]
    restored = application_kit_from_dict(json.loads(json.dumps(raw)))
    assert restored.linkedin_outreach == kit.linkedin_outreach


def test_explicit_context_authorizes_only_supplied_relationships() -> None:
    context = OutreachContext(
        recipient_name="Avery Chen",
        recipient_title="Engineering Manager",
        recipient_company="Vantage Analytics",
        audience=OutreachAudience.HIRING_MANAGER,
        requested_intent=OutreachIntent.REFERRAL_REQUEST,
        has_applied=True,
        application_date="2026-07-16",
        application_status="submitted",
        referral_contact_name="Taylor Morgan",
        shared_affiliation="Metro University alumni network",
        portfolio_url="https://portfolio.example/morgan",
    )
    artifact = _kit(context=context).linkedin_outreach
    assert artifact is not None
    text = "\n".join(draft.text for draft in artifact.drafts)
    for supported in (
        "Avery Chen",
        "Engineering Manager",
        "Taylor Morgan recommended I contact you",
        "I applied for the Director of Platform role",
        "2026-07-16",
        "Metro University alumni network",
        "https://portfolio.example/morgan",
    ):
        assert supported in text
    assert artifact.relationship_validation.passed
    assert {ref.field for ref in artifact.relationship_context} >= {
        "recipient_name",
        "recipient_title",
        "recipient_company",
        "has_applied",
        "application_date",
        "referral_contact_name",
        "shared_affiliation",
        "portfolio_url",
    }


def test_false_application_and_unsupplied_relationships_are_not_in_drafts() -> None:
    context = OutreachContext(
        audience=OutreachAudience.EMPLOYEE,
        requested_intent=OutreachIntent.REFERRAL_REQUEST,
        has_applied=False,
    )
    artifact = _kit(context=context).linkedin_outreach
    assert artifact is not None
    text = "\n".join(draft.text for draft in artifact.drafts).casefold()
    assert "i applied" not in text
    assert "referred me" not in text
    assert "mutual connection" not in text
    assert "we met" not in text
    referral = next(draft for draft in artifact.drafts if draft.id == "referral-request")
    assert "considering a referral" in referral.text.casefold()


@pytest.mark.parametrize(
    ("context", "expected", "trace_field"),
    [
        (OutreachContext(mutual_connection="Casey Park"), "mutual connection", "mutual_connection"),
        (OutreachContext(prior_meeting="Metro Data Forum"), "meeting you at Metro Data Forum", "prior_meeting"),
        (
            OutreachContext(prior_conversation="platform reliability"),
            "our conversation about platform reliability",
            "prior_conversation",
        ),
    ],
)
def test_real_mutual_meeting_and_conversation_context_survives(
    context: OutreachContext,
    expected: str,
    trace_field: str,
) -> None:
    artifact = _kit(context=context).linkedin_outreach
    assert artifact is not None
    assert expected.casefold() in "\n".join(draft.text for draft in artifact.drafts).casefold()
    assert trace_field in {ref.field for ref in artifact.relationship_context}
    assert artifact.relationship_validation.passed


@pytest.mark.parametrize(
    ("resume", "expected"),
    [
        (
            "Taylor Kim\nPROFESSIONAL EXPERIENCE\nAcme Corp\nAnalyst 2023 - 2024\n"
            "- Built Python reports.\nCERTIFICATIONS\nCertified Data Foundations 2024\n",
            "certified data foundations",
        ),
        (
            "Taylor Kim\nPROFESSIONAL EXPERIENCE\nAcme Corp\nAnalyst 2023 - 2024\n"
            "- Prepared stakeholder reports.\nEDUCATION\nMetro University\nBachelor of Data Science 2019 - 2023\n",
            "bachelor of data science from metro university",
        ),
    ],
)
def test_supported_credential_and_education_can_be_selected_as_highlights(resume: str, expected: str) -> None:
    kit = generate_application_kit(
        resume_text=resume,
        job_description=OUTREACH_JD,
        default_mode=Mode.RESUME,
        use_llm=False,
        include_interview_prep=False,
    )
    artifact = kit.linkedin_outreach
    assert artifact is not None
    assert expected in "\n".join(draft.text for draft in artifact.drafts).casefold()


@pytest.mark.parametrize(
    ("case", "attack", "forbidden"),
    [
        ("google-employment", "I worked at Google as an engineer.", "google"),
        ("target-employment", "I worked at Vantage Analytics before.", "worked at vantage analytics"),
        ("target-title", "I served as Director of Platform.", "served as director of platform"),
        ("invented-metric", "I delivered a 47% improvement.", "47%"),
        ("invented-team", "I led 20 engineers.", "20 engineers"),
        ("invented-cert", "I hold an AWS Certified Solutions Architect certification.", "aws certified"),
        ("rust-upgrade", "I have deep Rust expertise.", "rust expertise"),
        ("kubernetes-upgrade", "I have five years of production Kubernetes experience.", "production kubernetes"),
        ("perfect-fit", "I am a perfect fit and meet every requirement.", "perfect fit"),
        ("invented-referral", "You referred me for this role.", "you referred me"),
        ("invented-mutual", "We share a mutual connection.", "mutual connection"),
        ("invented-alumni", "We are fellow alumni.", "fellow alumni"),
        ("invented-meeting", "It was great when we met last week.", "we met"),
        ("invented-conversation", "I appreciated our conversation yesterday.", "our conversation"),
        ("false-post", "I saw your recent post.", "saw your recent post"),
        ("false-following", "I have been following your work.", "following your work"),
        ("false-applied", "I recently applied for this role.", "i recently applied"),
        ("false-attachment", "I attached my resume.", "attached my resume"),
        ("invented-link", "My portfolio is https://fake.example/phoenix.", "fake.example"),
        (
            "invented-recipient",
            "The recipient is the CTO at Globex Corporation.",
            "globex corporation",
        ),
        (
            "invented-company-fact",
            "Your company's Project Atlas architecture initiative is impressive.",
            "project atlas",
        ),
        (
            "mixed",
            "My Python experience is relevant, and I led 20 engineers at Google.",
            "20 engineers",
        ),
        ("unicode", "I have production experience with R\u200bｕｓｔ.", "production experience with rust"),
        ("length-overflow", "Useful strategy. " + "pressure " * 200, "pressure pressure"),
        (
            "qualifier-truncation",
            "Power BI is adjacent rather than expertise. " + "x" * 500 + " I am a Power BI expert.",
            "power bi expert",
        ),
        (
            "false-existing-referral",
            "A referral already exists and you referred me.",
            "referral already exists",
        ),
        (
            "confidential-team-knowledge",
            "I know confidential team architecture details.",
            "confidential team architecture",
        ),
        (
            "split-contradictions",
            "Rust is a gap. I use Rust professionally. We have not met. We met last week.",
            "use rust professionally",
        ),
    ],
)
def test_adversarial_provider_content_never_survives_final_artifact(
    case: str,
    attack: str,
    forbidden: str,
) -> None:
    del case
    kit = _kit(provider=OutreachProvider(attack))
    artifact = kit.linkedin_outreach
    assert artifact is not None
    final = _artifact_text(kit)
    normalized = "".join(char for char in unicodedata.normalize("NFKC", final) if unicodedata.category(char) != "Cf")
    assert forbidden.casefold() not in normalized
    assert artifact.consistency.passed
    assert artifact.relationship_validation.passed
    assert not artifact.withheld
    assert artifact.validation.status.value == "repaired"
    assert artifact.validation.warnings or any(claim.status.value == "repaired" for claim in artifact.claims)
    assert all(draft.character_count <= draft.character_limit for draft in artifact.drafts)
    assert not any(
        claim.status.value == "supported" and forbidden.casefold() in claim.text.casefold() for claim in artifact.claims
    )
    assert "python" in final


def test_supported_content_survives_without_generic_collapse() -> None:
    artifact = _kit().linkedin_outreach
    assert artifact is not None
    final = json.dumps(application_kit_to_dict(_kit())["linkedin_outreach"], ensure_ascii=False).casefold()
    for supported in (
        "harbor data",
        "data analyst",
        "python",
        "sql",
        "30%",
        "vantage analytics",
        "director of platform",
    ):
        assert supported in final
    assert all(len(draft.text.split()) >= 12 for draft in artifact.drafts)


@pytest.mark.parametrize(
    ("resume", "classification", "phrase"),
    [
        (
            "Taylor Kim\nPROFESSIONAL EXPERIENCE\nAcme Corp\nAnalyst 2023 - 2024\n- Built Tableau dashboards.\n",
            RequirementClassification.ADJACENT,
            "adjacent to power bi",
        ),
        (
            "Taylor Kim\nTECHNICAL SKILLS\nKubernetes\n",
            RequirementClassification.WORKING_KNOWLEDGE,
            "working knowledge of kubernetes",
        ),
    ],
)
def test_honest_adjacency_and_working_knowledge_survive(
    resume: str,
    classification: RequirementClassification,
    phrase: str,
) -> None:
    kit = generate_application_kit(
        resume_text=resume,
        job_description=OUTREACH_JD,
        default_mode=Mode.RESUME,
        use_llm=False,
        include_interview_prep=False,
    )
    artifact = kit.linkedin_outreach
    assert artifact is not None
    assert phrase in "\n".join(draft.text for draft in artifact.drafts).casefold()
    assert any(item.classification is classification for item in kit.job_fit.requirements)
