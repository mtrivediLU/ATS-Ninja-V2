from __future__ import annotations

import re
import unicodedata

from ats_engine.kit.contract import (
    ArtifactKind,
    ArtifactStatus,
    ArtifactValidation,
    ClaimRecord,
    ConsistencyValidation,
    EvidenceRef,
    GenerationMetadata,
    JobFitArtifact,
    LinkedInOutreachArtifact,
    OutreachAudience,
    OutreachContext,
    OutreachContextKind,
    OutreachContextRef,
    OutreachDraft,
    OutreachFormat,
    OutreachIntent,
    RelationshipValidation,
    RequirementAssessment,
    RequirementClassification,
)
from ats_engine.kit.grounding import EvidenceContext, GroundingOutcome, ground_text
from ats_engine.linkedin_outreach.policy import STRATEGY_SUMMARY_LIMIT, character_limit
from ats_engine.linkedin_outreach.validation import (
    character_count,
    relationship_errors,
    validate_linkedin_outreach,
)
from ats_engine.models import JDProfile, Profile
from ats_engine.providers.base import LLMProvider, generate_text

_CONTEXT_EXCERPT_MAX = 160
_FIELD_LIMITS: dict[str, int] = {
    "recipient_name": 100,
    "recipient_title": 120,
    "recipient_company": 120,
    "application_date": 40,
    "application_status": 80,
    "referral_contact_name": 100,
    "shared_affiliation": 140,
    "mutual_connection": 100,
    "prior_meeting": 160,
    "prior_conversation": 160,
    "personalization_note": 300,
    "portfolio_url": 300,
}


def _clean_value(value: str, limit: int) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    cleaned = "".join(char for char in normalized if unicodedata.category(char) not in {"Cc", "Cf"})
    return re.sub(r"\s+", " ", cleaned).strip()[:limit].strip()


def _clean_context(context: OutreachContext | None) -> OutreachContext:
    source = context or OutreachContext()
    values = {field: _clean_value(getattr(source, field), limit) for field, limit in _FIELD_LIMITS.items()}
    portfolio = values["portfolio_url"]
    if portfolio and not re.fullmatch(r"https?://[^\s<>]+", portfolio, re.I):
        portfolio = ""
    values["portfolio_url"] = portfolio
    return OutreachContext(
        **values,
        audience=source.audience,
        requested_intent=source.requested_intent,
        has_applied=source.has_applied,
    )


def _bounded(value: str, limit: int = _CONTEXT_EXCERPT_MAX) -> str:
    return _clean_value(value, limit)


def _target_refs(jd_profile: JDProfile) -> list[OutreachContextRef]:
    refs: list[OutreachContextRef] = []
    if jd_profile.company:
        refs.append(OutreachContextRef(OutreachContextKind.TARGET_JOB, "company", _bounded(jd_profile.company)))
    if jd_profile.title:
        refs.append(OutreachContextRef(OutreachContextKind.TARGET_JOB, "role", _bounded(jd_profile.title)))
    return refs


def _context_ref(kind: OutreachContextKind, field: str, value: str) -> OutreachContextRef:
    return OutreachContextRef(kind, field, _bounded(value))


def _proven(job_fit: JobFitArtifact) -> list[RequirementAssessment]:
    return [
        item
        for item in job_fit.requirements
        if item.classification is RequirementClassification.PROVEN and item.evidence
    ]


def _candidate_phrases(profile: Profile, job_fit: JobFitArtifact) -> tuple[str, str, str, list[EvidenceRef]]:
    proven = _proven(job_fit)
    skills = [item.requirement for item in proven[:2]]
    refs = [ref for item in proven[:2] for ref in item.evidence]
    skill_phrase = ""
    if len(skills) >= 2:
        skill_phrase = f"My experience includes {skills[0]} and {skills[1]}."
    elif skills:
        skill_phrase = f"My experience includes {skills[0]}."

    identity_phrase = ""
    if profile.experiences:
        experience = profile.experiences[0]
        identity_phrase = f"I worked as {experience.title} at {experience.company}."
        refs.append(
            EvidenceRef("candidate-resume", "experience:0", _bounded(f"{experience.title} at {experience.company}"))
        )

    result_phrase = ""
    if profile.supported_metrics:
        metric = profile.supported_metrics[0]
        result_phrase = f"One supported result in my background is {metric}."
        refs.append(EvidenceRef("candidate-resume", "supported_metric", _bounded(metric)))
    elif profile.certifications:
        certification = profile.certifications[0].name
        result_phrase = f"I hold {certification}."
        refs.append(EvidenceRef("candidate-resume", "certification:0", _bounded(certification)))
    elif profile.education:
        education = profile.education[0]
        result_phrase = f"My background includes {education.degree} from {education.institution}."
        refs.append(
            EvidenceRef(
                "candidate-resume",
                "education:0",
                _bounded(f"{education.degree} from {education.institution}"),
            )
        )

    if not skill_phrase and job_fit.working_knowledge:
        topic = job_fit.working_knowledge[0]
        skill_phrase = f"I have working knowledge of {topic}, not production expertise."
    elif not skill_phrase and job_fit.adjacent_capabilities:
        topic = job_fit.adjacent_capabilities[0]
        skill_phrase = f"My background is adjacent to {topic}, rather than direct expertise."
    return skill_phrase, identity_phrase, result_phrase, refs


def _greeting(context: OutreachContext) -> tuple[str, list[str], list[OutreachContextRef]]:
    if not context.recipient_name:
        return "Hello", [], []
    return (
        f"Hello {context.recipient_name}",
        ["recipient_name"],
        [_context_ref(OutreachContextKind.RECIPIENT, "recipient_name", context.recipient_name)],
    )


def _relationship_opening(context: OutreachContext) -> tuple[str, list[str], list[OutreachContextRef]]:
    if context.prior_conversation:
        return (
            f"I appreciated our conversation about {context.prior_conversation}.",
            ["prior_conversation"],
            [_context_ref(OutreachContextKind.RELATIONSHIP, "prior_conversation", context.prior_conversation)],
        )
    if context.prior_meeting:
        return (
            f"It was good meeting you at {context.prior_meeting}.",
            ["prior_meeting"],
            [_context_ref(OutreachContextKind.RELATIONSHIP, "prior_meeting", context.prior_meeting)],
        )
    if context.referral_contact_name:
        return (
            f"{context.referral_contact_name} recommended I contact you.",
            ["referral_contact_name"],
            [_context_ref(OutreachContextKind.RELATIONSHIP, "referral_contact_name", context.referral_contact_name)],
        )
    if context.mutual_connection:
        return (
            f"We share {context.mutual_connection} as a mutual connection.",
            ["mutual_connection"],
            [_context_ref(OutreachContextKind.RELATIONSHIP, "mutual_connection", context.mutual_connection)],
        )
    if context.shared_affiliation:
        return (
            f"We share {context.shared_affiliation} as an affiliation.",
            ["shared_affiliation"],
            [_context_ref(OutreachContextKind.RELATIONSHIP, "shared_affiliation", context.shared_affiliation)],
        )
    return "", [], []


def _recipient_rationale(context: OutreachContext) -> tuple[str, list[str], list[OutreachContextRef]]:
    fields: list[str] = []
    refs: list[OutreachContextRef] = []
    if context.recipient_title:
        fields.append("recipient_title")
        refs.append(_context_ref(OutreachContextKind.RECIPIENT, "recipient_title", context.recipient_title))
    if context.recipient_company:
        fields.append("recipient_company")
        refs.append(_context_ref(OutreachContextKind.RECIPIENT, "recipient_company", context.recipient_company))
    if context.recipient_title and context.recipient_company:
        return (
            f"Given your role as {context.recipient_title} at {context.recipient_company}, I’d value your perspective.",
            fields,
            refs,
        )
    if context.recipient_title:
        return f"Given your role as {context.recipient_title}, I’d value your perspective.", fields, refs
    if context.recipient_company:
        return f"Given your work at {context.recipient_company}, I’d value your perspective.", fields, refs
    return "", fields, refs


def _choose(variants: list[str], format_: OutreachFormat) -> str:
    limit = character_limit(format_)
    for variant in variants:
        cleaned = re.sub(r"\s+", " ", variant).strip()
        if character_count(cleaned) <= limit and cleaned.endswith((".", "?", "!")):
            return cleaned
    return "I’m interested in this opportunity. Would you be open to connecting?"


def _draft(
    *,
    id_: str,
    audience: OutreachAudience,
    intent: OutreachIntent,
    format_: OutreachFormat,
    variants: list[str],
    target_company: str,
    target_role: str,
    personalization_fields: list[str],
    call_to_action: str,
    evidence: list[EvidenceRef],
    target_context: list[OutreachContextRef],
    relationship_context: list[OutreachContextRef],
) -> OutreachDraft:
    text = _choose(variants, format_)
    return OutreachDraft(
        id=id_,
        audience=audience,
        intent=intent,
        format=format_,
        text=text,
        character_count=character_count(text),
        character_limit=character_limit(format_),
        target_company=target_company,
        target_role=target_role,
        personalization_fields=list(dict.fromkeys(personalization_fields)),
        call_to_action=call_to_action,
        evidence=evidence,
        target_context=target_context,
        relationship_context=relationship_context,
    )


def _build_drafts(
    profile: Profile,
    jd_profile: JDProfile,
    job_fit: JobFitArtifact,
    context: OutreachContext,
) -> list[OutreachDraft]:
    company = _bounded(jd_profile.company, 80) or "the target company"
    role = _bounded(jd_profile.title, 80) or "the target role"
    target_refs = _target_refs(jd_profile)
    greeting, greeting_fields, greeting_refs = _greeting(context)
    relationship, relationship_fields, relationship_refs = _relationship_opening(context)
    recipient_rationale, recipient_fields, recipient_refs = _recipient_rationale(context)
    skill, identity, result, evidence = _candidate_phrases(profile, job_fit)
    highlight = skill or identity or "My background includes relevant transferable experience."
    compact_highlight = skill or "My background is relevant to the role."

    connect_cta = "Would you be open to connecting?"
    recruiter = _draft(
        id_="recruiter-connection",
        audience=OutreachAudience.RECRUITER,
        intent=OutreachIntent.CONNECT,
        format_=OutreachFormat.CONNECTION_NOTE,
        variants=[
            f"{greeting}, I’m interested in the {role} role at {company}. {compact_highlight} {connect_cta}",
            f"{greeting}, I’m interested in the {role} role at {company}. {connect_cta}",
            f"I’m interested in the {role} role at {company}. {connect_cta}",
        ],
        target_company=company,
        target_role=role,
        personalization_fields=greeting_fields,
        call_to_action=connect_cta,
        evidence=evidence,
        target_context=target_refs,
        relationship_context=greeting_refs,
    )

    manager_cta = "Would you be open to connecting for a brief conversation?"
    manager = _draft(
        id_="hiring-manager-connection",
        audience=OutreachAudience.HIRING_MANAGER,
        intent=OutreachIntent.CONNECT,
        format_=OutreachFormat.CONNECTION_NOTE,
        variants=[
            f"{greeting}, I’m exploring the {role} role at {company}. {highlight} {manager_cta}",
            f"I’m exploring the {role} role at {company}. {manager_cta}",
        ],
        target_company=company,
        target_role=role,
        personalization_fields=greeting_fields,
        call_to_action=manager_cta,
        evidence=evidence,
        target_context=target_refs,
        relationship_context=greeting_refs,
    )

    direct_cta = "Would you be open to a short conversation about what the role needs most?"
    direct_parts = [part for part in (relationship, identity, skill, result, recipient_rationale) if part]
    direct = _draft(
        id_="targeted-direct-message",
        audience=context.audience or OutreachAudience.RECRUITER,
        intent=context.requested_intent or OutreachIntent.DIRECT_MESSAGE,
        format_=OutreachFormat.DIRECT_MESSAGE,
        variants=[
            f"{greeting}. {' '.join(direct_parts)} I’m interested in the {role} role at {company}. {direct_cta}",
            f"{greeting}. {highlight} I’m interested in the {role} role at {company}. {direct_cta}",
        ],
        target_company=company,
        target_role=role,
        personalization_fields=greeting_fields + relationship_fields + recipient_fields,
        call_to_action=direct_cta,
        evidence=evidence,
        target_context=target_refs,
        relationship_context=greeting_refs + relationship_refs + recipient_refs,
    )

    info_cta = "Would you be open to sharing what success in the role looks like?"
    informational = _draft(
        id_="employee-informational",
        audience=OutreachAudience.EMPLOYEE,
        intent=OutreachIntent.INFORMATIONAL,
        format_=OutreachFormat.DIRECT_MESSAGE,
        variants=[
            f"{greeting}. I’m considering the {role} role at {company}. {highlight} {info_cta}",
            f"I’m considering the {role} role at {company}. {info_cta}",
        ],
        target_company=company,
        target_role=role,
        personalization_fields=greeting_fields,
        call_to_action=info_cta,
        evidence=evidence,
        target_context=target_refs,
        relationship_context=greeting_refs,
    )
    drafts = [recruiter, manager, direct, informational]

    if context.has_applied is True:
        application_detail = f" on {context.application_date}" if context.application_date else ""
        status_detail = (
            f" My supplied application status is {context.application_status}." if context.application_status else ""
        )
        applied_cta = "Would you be open to sharing the next appropriate step?"
        application_refs = [
            _context_ref(OutreachContextKind.RELATIONSHIP, "has_applied", "true"),
            *(
                [_context_ref(OutreachContextKind.RELATIONSHIP, "application_date", context.application_date)]
                if context.application_date
                else []
            ),
            *(
                [_context_ref(OutreachContextKind.RELATIONSHIP, "application_status", context.application_status)]
                if context.application_status
                else []
            ),
        ]
        drafts.append(
            _draft(
                id_="post-application-follow-up",
                audience=context.audience or OutreachAudience.RECRUITER,
                intent=OutreachIntent.FOLLOW_UP,
                format_=OutreachFormat.FOLLOW_UP,
                variants=[
                    f"{greeting}. I applied for the {role} role at {company}{application_detail}.{status_detail} {highlight} {applied_cta}",
                    f"I applied for the {role} role at {company}{application_detail}. {applied_cta}",
                ],
                target_company=company,
                target_role=role,
                personalization_fields=greeting_fields + [ref.field for ref in application_refs],
                call_to_action=applied_cta,
                evidence=evidence,
                target_context=target_refs,
                relationship_context=greeting_refs + application_refs,
            )
        )

    if context.requested_intent is OutreachIntent.REFERRAL_REQUEST or context.referral_contact_name:
        referral_cta = "Would you be comfortable considering a referral if my background seems relevant?"
        drafts.append(
            _draft(
                id_="referral-request",
                audience=context.audience or OutreachAudience.EMPLOYEE,
                intent=OutreachIntent.REFERRAL_REQUEST,
                format_=OutreachFormat.REFERRAL_REQUEST,
                variants=[
                    f"{greeting}. {relationship} I’m interested in the {role} role at {company}. {highlight} {referral_cta}",
                    f"I’m interested in the {role} role at {company}. {referral_cta}",
                ],
                target_company=company,
                target_role=role,
                personalization_fields=greeting_fields + relationship_fields,
                call_to_action=referral_cta,
                evidence=evidence,
                target_context=target_refs,
                relationship_context=greeting_refs + relationship_refs,
            )
        )

    if context.shared_affiliation:
        affiliation_cta = "Would you be open to connecting and sharing your perspective on the role?"
        affiliation_ref = _context_ref(
            OutreachContextKind.RELATIONSHIP, "shared_affiliation", context.shared_affiliation
        )
        drafts.append(
            _draft(
                id_="shared-affiliation-outreach",
                audience=OutreachAudience.ALUMNI,
                intent=OutreachIntent.SHARED_AFFILIATION,
                format_=OutreachFormat.DIRECT_MESSAGE,
                variants=[
                    f"{greeting}. As fellow members of {context.shared_affiliation}, I wanted to reach out. I’m interested in the {role} role at {company}. {affiliation_cta}",
                    f"We share {context.shared_affiliation}. I’m interested in the {role} role at {company}. {affiliation_cta}",
                ],
                target_company=company,
                target_role=role,
                personalization_fields=greeting_fields + ["shared_affiliation"],
                call_to_action=affiliation_cta,
                evidence=evidence,
                target_context=target_refs,
                relationship_context=greeting_refs + [affiliation_ref],
            )
        )

    if context.portfolio_url:
        draft = drafts[2]
        portfolio_sentence = f"My supplied portfolio is {context.portfolio_url}."
        prefix = draft.text.removesuffix(draft.call_to_action).rstrip()
        candidate = f"{prefix} {portfolio_sentence} {draft.call_to_action}"
        if character_count(candidate) <= draft.character_limit:
            draft.text = candidate
            draft.character_count = character_count(candidate)
            draft.personalization_fields.append("portfolio_url")
            draft.relationship_context.append(
                _context_ref(OutreachContextKind.RELATIONSHIP, "portfolio_url", context.portfolio_url)
            )
    return drafts


def _fallback_summary(job_fit: JobFitArtifact, jd_profile: JDProfile) -> str:
    strengths = ", ".join(job_fit.strongest_matches[:2]) or "supported experience"
    boundary = ""
    if job_fit.must_have_gaps:
        boundary = " Avoid complete-alignment claims because the fit assessment contains must-have gaps."
    return (
        f"Use concise outreach for the {jd_profile.title} target at {jd_profile.company}, lead with {strengths}, "
        f"and ask for one reasonable next step.{boundary}"
    )


def _prompt(job_fit: JobFitArtifact, jd_profile: JDProfile, fallback: str) -> str:
    strengths = ", ".join(job_fit.strongest_matches[:3]) or "none"
    adjacent = ", ".join(job_fit.adjacent_capabilities[:2]) or "none"
    working = ", ".join(job_fit.working_knowledge[:2]) or "none"
    gaps = ", ".join(job_fit.genuine_gaps[:3]) or "none"
    return f"""LINKEDIN OUTREACH STRATEGY
Rewrite only the outreach strategy sentence below. Return one concise sentence, no draft message and no greeting.

Authoritative target role: {jd_profile.title}
Authoritative target company: {jd_profile.company}
Fit band: {job_fit.fit_band.value}
Proven strengths: {strengths}
Adjacent only: {adjacent}
Working knowledge only: {working}
Genuine gaps: {gaps}

Rules: do not invent candidate, recipient, relationship, application, company, link, attachment, or referral facts. Do not claim perfect alignment. Do not change classifications. Do not mention a meeting, post, conversation, referral, mutual connection, application, resume, or recipient identity. Stay under {STRATEGY_SUMMARY_LIMIT} characters.

Sentence to improve: {fallback}
"""


def _ground_drafts(
    drafts: list[OutreachDraft],
    evidence_context: EvidenceContext,
    outreach_context: OutreachContext,
) -> tuple[list[ClaimRecord], int, int, bool, list[str]]:
    claims: list[ClaimRecord] = []
    repaired = 0
    rejected = 0
    fatal = False
    relationship_repairs: list[str] = []
    for index, draft in enumerate(drafts):
        protected_text, protected_values = _protect_context_values(draft.text, draft, outreach_context)
        outcome = ground_text(
            protected_text,
            artifact=ArtifactKind.LINKEDIN_OUTREACH,
            context=evidence_context,
            id_prefix=f"outreach-draft-{index}",
        )
        claims.extend(outcome.claims)
        repaired += outcome.repaired
        rejected += outcome.rejected
        fatal = fatal or outcome.fatal
        draft.text = _restore_context_values(outcome.clean_text, protected_values)
        draft.character_count = character_count(draft.text)
        rel_errors = relationship_errors(draft.text, outreach_context)
        relationship_repairs.extend(rel_errors)
        draft_fatal = outcome.fatal or bool(rel_errors) or not draft.text or draft.call_to_action not in draft.text
        draft.validation = ArtifactValidation(
            status=(
                ArtifactStatus.REJECTED
                if draft_fatal
                else (ArtifactStatus.REPAIRED if outcome.repaired else ArtifactStatus.GENERATED)
            ),
            fatal=draft_fatal,
            errors=rel_errors,
            repaired_claims=outcome.repaired,
            rejected_claims=outcome.rejected,
        )
        fatal = fatal or draft_fatal
    return claims, repaired, rejected, fatal, list(dict.fromkeys(relationship_repairs))


def _protect_context_values(
    text: str,
    draft: OutreachDraft,
    context: OutreachContext,
) -> tuple[str, dict[str, str]]:
    """Shield non-candidate evidence classes from the candidate claim gate.

    Target, recipient, and relationship values have their own deterministic
    validators. Shielding only exact typed values prevents the candidate
    grounder from deleting legitimate targeting language while still exposing
    every other candidate-specific phrase to normal claim extraction.
    """
    values = [draft.target_company, draft.target_role]
    values.extend(
        str(getattr(context, field))
        for field in _FIELD_LIMITS
        if field != "personalization_note" and getattr(context, field)
    )
    return _protect_raw_values(text, values)


def _protect_raw_values(text: str, values: list[str]) -> tuple[str, dict[str, str]]:
    protected = text
    replacements: dict[str, str] = {}
    for index, value in enumerate(sorted(set(values), key=len, reverse=True)):
        token = f"contextboundarytoken{index}"
        if value and value in protected:
            protected = protected.replace(value, token)
            replacements[token] = value
    return protected, replacements


def _restore_context_values(text: str, replacements: dict[str, str]) -> str:
    restored = text
    for token, value in replacements.items():
        restored = restored.replace(token, value)
    return restored


def _ground_strategy(
    text: str,
    *,
    id_prefix: str,
    evidence_context: EvidenceContext,
    jd_profile: JDProfile,
    outreach_context: OutreachContext,
) -> GroundingOutcome:
    values = [jd_profile.company, jd_profile.title]
    values.extend(
        str(getattr(outreach_context, field))
        for field in _FIELD_LIMITS
        if field != "personalization_note" and getattr(outreach_context, field)
    )
    protected, replacements = _protect_raw_values(text, values)
    outcome = ground_text(
        protected,
        artifact=ArtifactKind.LINKEDIN_OUTREACH,
        context=evidence_context,
        id_prefix=id_prefix,
    )
    outcome.clean_text = _restore_context_values(outcome.clean_text, replacements)
    return outcome


def build_linkedin_outreach_artifact(
    *,
    profile: Profile,
    jd_profile: JDProfile,
    job_fit: JobFitArtifact,
    evidence_context: EvidenceContext,
    outreach_context: OutreachContext | None = None,
    provider: LLMProvider | None = None,
) -> LinkedInOutreachArtifact:
    """Build useful deterministic drafts and optionally improve strategy wording."""
    context = _clean_context(outreach_context)
    drafts = _build_drafts(profile, jd_profile, job_fit, context)
    draft_claims, draft_repaired, draft_rejected, draft_fatal, draft_relationship_repairs = _ground_drafts(
        drafts, evidence_context, context
    )

    fallback = _fallback_summary(job_fit, jd_profile)
    candidate = generate_text(provider, _prompt(job_fit, jd_profile, fallback))
    initial_summary = candidate or fallback
    grounded = _ground_strategy(
        initial_summary,
        id_prefix="outreach-strategy",
        evidence_context=evidence_context,
        jd_profile=jd_profile,
        outreach_context=context,
    )
    summary = grounded.clean_text
    initial_errors = validate_linkedin_outreach(
        strategy_summary=summary,
        drafts=drafts,
        context=context,
        job_fit=job_fit,
        profile=profile,
        jd_profile=jd_profile,
    )
    if character_count(summary) > STRATEGY_SUMMARY_LIMIT:
        initial_errors.append("Provider strategy exceeded the configured strategy length limit.")
    relationship_initial = relationship_errors(summary, context) + draft_relationship_repairs

    fallback_grounded: GroundingOutcome | None = None
    if initial_errors or grounded.fatal:
        fallback_grounded = _ground_strategy(
            fallback,
            id_prefix="outreach-fallback",
            evidence_context=evidence_context,
            jd_profile=jd_profile,
            outreach_context=context,
        )
        summary = fallback_grounded.clean_text

    final_errors = validate_linkedin_outreach(
        strategy_summary=summary,
        drafts=drafts,
        context=context,
        job_fit=job_fit,
        profile=profile,
        jd_profile=jd_profile,
    )
    if character_count(summary) > STRATEGY_SUMMARY_LIMIT:
        final_errors.append("Final strategy exceeds the configured strategy length limit.")
    final_relationship_errors = relationship_errors(summary, context) + draft_relationship_repairs
    final_relationship_errors = list(dict.fromkeys(final_relationship_errors))
    fatal = (
        draft_fatal
        or bool(final_errors)
        or bool(final_relationship_errors)
        or bool(fallback_grounded and fallback_grounded.fatal)
    )
    repaired_violations = list(dict.fromkeys(initial_errors))
    repaired = (
        draft_repaired
        + grounded.repaired
        + len(repaired_violations)
        + (fallback_grounded.repaired if fallback_grounded else 0)
    )
    rejected = draft_rejected + grounded.rejected + (fallback_grounded.rejected if fallback_grounded else 0)
    warnings = [f"LinkedIn outreach repaired: {error}" for error in repaired_violations]
    if candidate and grounded.repaired:
        warnings.append("Unsupported candidate claims were removed from provider outreach strategy prose.")
    if context.personalization_note:
        warnings.append("Free-form personalization note was not promoted to candidate or relationship evidence.")
    status = ArtifactStatus.REJECTED if fatal else (ArtifactStatus.REPAIRED if repaired else ArtifactStatus.GENERATED)
    claims = draft_claims + grounded.claims + (fallback_grounded.claims if fallback_grounded else [])
    evidence = [ref for draft in drafts for ref in draft.evidence]
    target_refs = _target_refs(jd_profile)
    relationship_refs = [ref for draft in drafts for ref in draft.relationship_context]
    return LinkedInOutreachArtifact(
        strategy_summary="" if fatal else summary,
        drafts=[] if fatal else drafts,
        validation=ArtifactValidation(
            status=status,
            fatal=fatal,
            errors=list(dict.fromkeys(final_errors + final_relationship_errors)),
            warnings=warnings,
            repaired_claims=repaired,
            rejected_claims=rejected,
        ),
        consistency=ConsistencyValidation(not final_errors, list(dict.fromkeys(final_errors)), repaired_violations),
        relationship_validation=RelationshipValidation(
            not final_relationship_errors,
            final_relationship_errors,
            list(dict.fromkeys(relationship_initial)),
        ),
        generation=GenerationMetadata(generation_mode="deterministic", llm_available=False),
        claims=claims,
        evidence=evidence,
        target_context=target_refs,
        relationship_context=relationship_refs,
        warnings=warnings,
        withheld=fatal,
    )
