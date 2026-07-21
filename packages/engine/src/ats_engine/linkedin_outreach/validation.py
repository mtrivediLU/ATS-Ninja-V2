from __future__ import annotations

import re
import unicodedata

from ats_engine.kit.contract import (
    JobFitArtifact,
    OutreachContext,
    OutreachDraft,
    RequirementClassification,
)
from ats_engine.models import JDProfile, Profile

_PERFECT_FIT = re.compile(
    r"\b(?:perfect|ideal|complete(?:ly)?)\s+(?:fit|match|alignment)|"
    r"\b(?:meet|match|cover)\s+(?:all|every)\s+(?:the\s+)?requirements?\b",
    re.I,
)
_EXPERTISE = re.compile(r"\b(?:expert(?:ise)?|mastery|deep expertise|production experience|\d+\s*years?)\b", re.I)
_PRODUCTION = re.compile(r"\b(?:production|professional experience|expert(?:ise)?|\d+\s*years?)\b", re.I)
_STRENGTH = re.compile(r"\b(?:strength|proven|experienced|expert(?:ise)?|hands.on|production)\b", re.I)
_TARGET_HISTORY = re.compile(r"\b(?:worked|employed|served|joined)\s+(?:at|for)\s+", re.I)
_TITLE_HISTORY = re.compile(r"\b(?:worked|served)\s+as\s+(?:an?\s+|the\s+)?", re.I)
_COMPANY_FACT = re.compile(
    r"\b(?:the company|your company|your team|their company)(?:'s|s)?.{0,50}"
    r"\b(?:initiative|architecture|strategy|revenue|customers?|culture|growth|roadmap|product)\b",
    re.I,
)
_RECIPIENT_FACT = re.compile(
    r"\b(?:the\s+)?(?:recipient|recruiter|hiring manager|contact)\b.{0,70}"
    r"\b(?:works? at|from|is (?:the |an? )?|serves? as)\b",
    re.I,
)
_PRESSURE = re.compile(
    r"\b(?:urgent(?:ly)?|immediate response|required to reply|owe me|must respond|confidential information|"
    r"confidential (?:team|architecture|roadmap|plans?|details?)|inside information|guaranteed hire|desperate)\b",
    re.I,
)
_FLATTERY = re.compile(r"\b(?:legendary|world[- ]class genius|best leader ever|unmatched visionary)\b", re.I)

_MEETING = re.compile(r"\b(?:we met|meeting you|after our meeting|when we met)\b", re.I)
_CONVERSATION = re.compile(r"\b(?:we spoke|our conversation|speaking with you|we discussed)\b", re.I)
_REFERRAL = re.compile(
    r"\b(?:referred me|recommended (?:that )?i contact|suggested (?:that )?i contact|introduced me|"
    r"you referred me)\b",
    re.I,
)
_MUTUAL = re.compile(r"\b(?:mutual connection|shared colleague|we both know)\b", re.I)
_AFFILIATION = re.compile(r"\b(?:fellow alumni|we both attended|shared affiliation|fellow member)\b", re.I)
_POST = re.compile(r"\b(?:i saw|i read|saw|read) your (?:recent )?(?:post|article)\b", re.I)
_FOLLOWING = re.compile(r"\b(?:i(?:'ve| have)? been following|i follow) your work\b", re.I)
_APPLIED = re.compile(r"\b(?:i(?:'ve| have)? (?:recently )?applied|i submitted my application)\b", re.I)
_RESUME_ACTION = re.compile(r"\b(?:i(?:'ve| have)? (?:attached|sent|submitted) my resume|resume is attached)\b", re.I)
_INTERVIEW_ACTION = re.compile(r"\b(?:interview invitation|you invited me to interview|our interview)\b", re.I)
_INTRODUCTION = re.compile(r"\b(?:thanks for the introduction|introduced us|previous follow-up)\b", re.I)
_URL = re.compile(r"https?://[^\s<>]+", re.I)


def normalized_text(text: str) -> str:
    """NFKC-normalize text and remove zero-width/format controls."""
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return "".join(char for char in normalized if unicodedata.category(char) != "Cf")


def character_count(text: str) -> int:
    """Count the normalized deliverable characters used by product policy."""
    return len("".join(char for char in unicodedata.normalize("NFKC", text) if unicodedata.category(char) != "Cf"))


def relationship_errors(text: str, context: OutreachContext) -> list[str]:
    """Return unsupported relationship/action claims in deliverable prose."""
    normalized = normalized_text(text)
    errors: list[str] = []
    checks = (
        (_MEETING, bool(context.prior_meeting), "Unsupported prior-meeting claim."),
        (_CONVERSATION, bool(context.prior_conversation), "Unsupported prior-conversation claim."),
        (_REFERRAL, bool(context.referral_contact_name), "Unsupported referral or introduction claim."),
        (_MUTUAL, bool(context.mutual_connection), "Unsupported mutual-connection claim."),
        (_AFFILIATION, bool(context.shared_affiliation), "Unsupported shared-affiliation claim."),
        (_APPLIED, context.has_applied is True, "Unsupported application-status claim."),
    )
    for pattern, supported, message in checks:
        if pattern.search(normalized) and not supported:
            errors.append(message)
    if _POST.search(normalized):
        errors.append("Unsupported claim about a recipient post or article.")
    if _FOLLOWING.search(normalized):
        errors.append("Unsupported claim about following the recipient's work.")
    if _RESUME_ACTION.search(normalized):
        errors.append("Unsupported claim that a resume was sent or attached.")
    if _INTERVIEW_ACTION.search(normalized):
        errors.append("Unsupported interview-action claim.")
    if _INTRODUCTION.search(normalized) and not context.referral_contact_name:
        errors.append("Unsupported introduction or previous-follow-up claim.")
    urls = _URL.findall(text)
    if urls and not context.portfolio_url:
        errors.append("Unsupported portfolio or profile link.")
    elif context.portfolio_url and any(url.rstrip(".,)") != context.portfolio_url for url in urls):
        errors.append("Draft contains a link other than the explicitly supplied portfolio link.")
    return list(dict.fromkeys(errors))


def _contexts(text: str, term: str) -> list[str]:
    normalized_term = normalized_text(term).strip()
    # Split only at a terminator immediately followed by whitespace: a term
    # spelled with an internal period (".NET Framework") would otherwise
    # self-fragment at that period, stripping the leading "." the match below
    # requires.
    return [
        clause
        for clause in re.split(r"(?<=[.!?;])\s+|\n+", normalized_text(text))
        if normalized_term and normalized_term in clause
    ]


def _scrub_terms(context: str, terms: list[str]) -> str:
    scrubbed = context
    for term in terms:
        if term:
            scrubbed = scrubbed.replace(term, " ")
    return scrubbed


def _affirmative_upgrade(clause: str, pattern: re.Pattern[str]) -> bool:
    if not pattern.search(clause):
        return False
    return not re.search(
        r"\b(?:not|no|never|avoid|without|adjacent|working knowledge|limited exposure|gap|rather than)\b",
        clause,
        re.I,
    )


def validate_linkedin_outreach(
    *,
    strategy_summary: str,
    drafts: list[OutreachDraft],
    context: OutreachContext,
    job_fit: JobFitArtifact,
    profile: Profile,
    jd_profile: JDProfile,
) -> list[str]:
    """Validate final drafts against evidence, fit, relationship, and format policy."""
    errors: list[str] = []
    combined = "\n".join([strategy_summary] + [draft.text for draft in drafts])
    normalized = normalized_text(combined)

    if job_fit.must_have_gaps or job_fit.genuine_gaps:
        if _PERFECT_FIT.search(normalized):
            errors.append("Outreach claims complete alignment despite genuine gaps.")

    all_terms = [normalized_text(other.requirement).strip() for other in job_fit.requirements]
    for item in job_fit.requirements:
        contexts = _contexts(combined, item.requirement)
        # Requirements sharing one clause each see the whole clause as their
        # context, including neighboring requirement names; scrub every
        # listed requirement's own name (not just this one's) so one gap's
        # name containing a generic trigger word never falsely flags another.
        scrubbed = [_scrub_terms(clause, all_terms) for clause in contexts]
        if item.classification is RequirementClassification.ADJACENT and any(
            _affirmative_upgrade(clause, _EXPERTISE) for clause in scrubbed
        ):
            errors.append(f"Adjacent capability upgraded to expertise: {item.requirement}.")
        if item.classification is RequirementClassification.WORKING_KNOWLEDGE and any(
            _affirmative_upgrade(clause, _PRODUCTION) for clause in scrubbed
        ):
            errors.append(f"Working knowledge upgraded to production experience: {item.requirement}.")
        if item.classification is RequirementClassification.GENUINE_GAP and any(
            _affirmative_upgrade(clause, _STRENGTH) for clause in scrubbed
        ):
            errors.append(f"Genuine gap presented as a strength: {item.requirement}.")

    target_company = normalized_text(jd_profile.company).strip()
    target_role = normalized_text(jd_profile.title).strip()
    candidate_companies = {normalized_text(item.company).strip() for item in profile.experiences}
    candidate_titles = {normalized_text(item.title).strip() for item in profile.experiences}
    if target_company and target_company not in candidate_companies:
        for match in _TARGET_HISTORY.finditer(normalized):
            if normalized[match.end() :].lstrip().startswith(target_company):
                errors.append("Target company was presented as candidate employment history.")
    if target_role and target_role not in candidate_titles:
        for match in _TITLE_HISTORY.finditer(normalized):
            if normalized[match.end() :].lstrip().startswith(target_role):
                errors.append("Target role was presented as prior candidate history.")

    if _COMPANY_FACT.search(normalized):
        errors.append("Outreach asserts an unverified company fact.")
    if _RECIPIENT_FACT.search(normalized):
        errors.append("Provider strategy asserts a recipient title or company fact.")
    if _PRESSURE.search(normalized):
        errors.append("Outreach contains pressure, confidential-information requests, or deceptive urgency.")
    if _FLATTERY.search(normalized):
        errors.append("Outreach contains unsupported excessive flattery.")

    errors.extend(relationship_errors(combined, context))
    for draft in drafts:
        actual_count = character_count(draft.text)
        if draft.character_count != actual_count:
            errors.append(f"Draft character count is incorrect: {draft.id}.")
        if actual_count > draft.character_limit:
            errors.append(f"Draft exceeds its configured character limit: {draft.id}.")
        if not draft.text.strip() or not draft.text.rstrip().endswith((".", "?", "!")):
            errors.append(f"Draft is empty or ends with a broken sentence: {draft.id}.")
        if not draft.call_to_action or draft.call_to_action not in draft.text:
            errors.append(f"Draft lacks its declared call to action: {draft.id}.")
        if draft.text.count(draft.call_to_action) != 1:
            errors.append(f"Draft repeats its call to action: {draft.id}.")

    return list(dict.fromkeys(errors))
