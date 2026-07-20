from __future__ import annotations

import re
import unicodedata

from ats_engine.kit.contract import (
    GapHandlingGuide,
    InterviewerQuestion,
    InterviewFocusArea,
    InterviewQuestion,
    JobFitArtifact,
    RequirementClassification,
    StarCompleteness,
    StarStoryCandidate,
    TechnicalStudyTopic,
)
from ats_engine.models import JDProfile, Profile

_UPGRADE = re.compile(
    r"\b(?:expert(?:ise)?|mastery|professional experience|production experience|"
    r"hands.on experience|led|owned|architected|\d+\s*years?)\b",
    re.I,
)
_PRODUCTION_UPGRADE = re.compile(r"\b(?:production|professional experience|expert(?:ise)?|\d+\s*years?)\b", re.I)
_STRENGTH = re.compile(r"\b(?:strength|proven|experience|expert(?:ise)?|hands.on|production)\b", re.I)
_DISHONEST_GAP = re.compile(r"\b(?:hide|conceal|deny|minimi[sz]e|pretend|misrepresent)\b.{0,45}\bgap\b", re.I)
_COMPANY_FACT = re.compile(
    r"\b(?:your|the company.s)\s+(?:initiative|architecture|strategy|revenue|customers?|culture)\b",
    re.I,
)
_PROJECT_OR_CLIENT = re.compile(r"\b(?:project|client)\s+[\w-]+(?:\s+[\w-]+){0,2}", re.I)
_SELF_UPGRADE = re.compile(r"\bI\s+(?:led|owned|architected|managed|directed)\b", re.I)
_RESULT_ASSERTION = re.compile(r"\b(?:the\s+)?result(?:ed)?\s+(?:was|in)\b", re.I)


def normalized_text(text: str) -> str:
    """Normalize compatibility characters and remove format controls."""
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return "".join(char for char in normalized if unicodedata.category(char) != "Cf")


def _contexts(text: str, term: str) -> list[str]:
    normalized_term = normalized_text(term).strip()
    # Split only at a terminator immediately followed by whitespace: a term
    # spelled with an internal period (".NET Framework") would otherwise
    # self-fragment at that period, stripping the leading "." the match below
    # requires and silently losing surrounding context (e.g. "acknowledge").
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


def _asserts(context: str, pattern: re.Pattern[str]) -> bool:
    """True for an affirmative upgrade, not explicit boundary language."""
    if not pattern.search(context):
        return False
    return not re.search(
        r"\b(?:not|no|never|avoid|do not|without|adjacent|working knowledge|gap|acknowledge|"
        r"current evidence level|distinct from)\b",
        context,
        re.I,
    )


def validate_interview_prep(
    *,
    strategy_summary: str,
    focus_areas: list[InterviewFocusArea],
    questions: list[InterviewQuestion],
    star_stories: list[StarStoryCandidate],
    study_topics: list[TechnicalStudyTopic],
    gap_handling: list[GapHandlingGuide],
    interviewer_questions: list[InterviewerQuestion],
    job_fit: JobFitArtifact,
    profile: Profile,
    jd_profile: JDProfile,
) -> list[str]:
    """Return contradictions between interview content and authoritative evidence."""
    errors: list[str] = []
    combined = "\n".join(
        [strategy_summary]
        + [question.answer_guide.suggested_answer for question in questions]
        + [guide.guidance for guide in gap_handling]
    )
    assessments = {item.id: item for item in job_fit.requirements}

    for focus in focus_areas:
        expected = assessments.get(focus.requirement_id)
        if expected is None or expected.classification is not focus.classification:
            errors.append(f"Focus classification contradicts JobFit: {focus.topic}.")

    all_terms = [normalized_text(other.requirement).strip() for other in job_fit.requirements]
    for item in job_fit.requirements:
        contexts = _contexts(combined, item.requirement)
        # Requirements sharing one clause (e.g. a "Genuine gaps: X, Y, Z."
        # sentence) each see the whole clause as their context, including
        # neighboring requirement names. A name like "user experience"
        # contains the generic trigger word "experience", so without
        # scrubbing every listed requirement's own name (not just this one's),
        # honestly naming it would also falsely flag its neighbors in the
        # same sentence.
        scrubbed = [_scrub_terms(c, all_terms) for c in contexts]
        if item.classification is RequirementClassification.ADJACENT and any(_asserts(c, _UPGRADE) for c in scrubbed):
            errors.append(f"Adjacent capability upgraded to expertise: {item.requirement}.")
        if item.classification is RequirementClassification.WORKING_KNOWLEDGE and any(
            _asserts(c, _PRODUCTION_UPGRADE) for c in scrubbed
        ):
            errors.append(f"Working knowledge upgraded to production experience: {item.requirement}.")
        if item.classification is RequirementClassification.GENUINE_GAP and any(
            _asserts(c, _STRENGTH) for c in scrubbed
        ):
            errors.append(f"Genuine gap presented as candidate experience: {item.requirement}.")

    handled = {item.requirement_id for item in gap_handling}
    questioned = {requirement_id for question in questions for requirement_id in question.related_requirement_ids}
    for item in job_fit.requirements:
        if item.must_have and item.classification is RequirementClassification.GENUINE_GAP:
            if item.id not in handled or item.id not in questioned:
                errors.append(f"Must-have gap omitted from preparation: {item.requirement}.")
            if normalized_text(item.requirement) not in normalized_text(strategy_summary):
                errors.append(f"Strategy summary omitted must-have gap: {item.requirement}.")

    if _DISHONEST_GAP.search(normalized_text(combined)):
        errors.append("Gap guidance advises concealment or misrepresentation.")

    for topic in study_topics:
        if "not candidate experience" not in normalized_text(topic.boundary):
            errors.append(f"Study topic lacks an explicit experience boundary: {topic.topic}.")

    allowed_contexts = {
        (normalized_text(exp.company), normalized_text(exp.title), "professional") for exp in profile.experiences
    } | {(normalized_text(edu.institution), normalized_text(edu.degree), "education") for edu in profile.education}
    target_company = normalized_text(jd_profile.company).strip()
    target_title = normalized_text(jd_profile.title).strip()

    raw_resume = normalized_text(profile.raw_markdown)
    for match in _PROJECT_OR_CLIENT.finditer(combined):
        if normalized_text(match.group(0)) not in raw_resume:
            errors.append(f"Unsupported project/client assertion: {match.group(0)}.")
    for match in _SELF_UPGRADE.finditer(combined):
        if normalized_text(match.group(0)) not in raw_resume:
            errors.append(f"Unsupported action or ownership upgrade: {match.group(0)}.")
    result_assertion = _RESULT_ASSERTION.search(combined)
    if result_assertion and normalized_text(result_assertion.group(0)) not in raw_resume:
        errors.append("Unsupported result assertion in interview prose.")

    if target_company and target_company not in {normalized_text(exp.company) for exp in profile.experiences}:
        if re.search(
            rf"\b(?:worked|employed|served|joined)\s+(?:at|for)\s+{re.escape(target_company)}\b",
            normalized_text(combined),
        ):
            errors.append("Target company was presented as candidate employment history.")
    if target_title and target_title not in {normalized_text(exp.title) for exp in profile.experiences}:
        if re.search(
            rf"\b(?:worked|served)\s+as\s+(?:an?\s+|the\s+)?{re.escape(target_title)}\b", normalized_text(combined)
        ):
            errors.append("Target role was presented as prior candidate title.")

    for clause in re.split(r"[.!?;\n]+", normalized_text(combined)):
        named_contexts = [exp for exp in profile.experiences if normalized_text(exp.company).strip() in clause]
        if len(named_contexts) > 1 and re.search(r"\b(?:I|my)\b", clause, re.I):
            errors.append("Interview prose blends multiple employer contexts.")

    for story in star_stories:
        key = (
            normalized_text(story.employer_or_institution),
            normalized_text(story.title_or_degree),
            story.source_type.value,
        )
        if key not in allowed_contexts:
            errors.append(f"STAR story source is not a single candidate context: {story.id}.")
        if target_company and target_company == key[0] and all(target_company != item[0] for item in allowed_contexts):
            errors.append(f"Target company recast as STAR employer: {story.id}.")
        if target_title and target_title == key[1] and all(target_title != item[1] for item in allowed_contexts):
            errors.append(f"Target role recast as prior STAR title: {story.id}.")
        fields = (story.situation, story.task, story.action, story.result)
        if story.completeness is StarCompleteness.COMPLETE and (not all(fields) or story.missing_components):
            errors.append(f"Complete STAR story has missing material evidence: {story.id}.")
        locators = {ref.locator.rsplit(":bullet", 1)[0] for ref in story.evidence}
        if len(locators) > 1:
            errors.append(f"STAR story blends multiple source contexts: {story.id}.")

    for interviewer_question in interviewer_questions:
        if _COMPANY_FACT.search(normalized_text(interviewer_question.question)):
            errors.append(f"Interviewer question asserts an unverified company fact: {interviewer_question.id}.")

    return list(dict.fromkeys(errors))
