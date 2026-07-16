from __future__ import annotations

import json
import re

from ats_engine.interview_prep.validation import validate_interview_prep
from ats_engine.kit.contract import (
    EVIDENCE_EXCERPT_MAX_CHARS,
    ArtifactKind,
    ArtifactStatus,
    ArtifactValidation,
    ClaimRecord,
    ConsistencyValidation,
    EvidenceRef,
    GapHandlingGuide,
    GenerationMetadata,
    InterviewAnswerGuide,
    InterviewerQuestion,
    InterviewFocusArea,
    InterviewPrepArtifact,
    InterviewPriority,
    InterviewQuestion,
    InterviewQuestionCategory,
    JobFitArtifact,
    PositioningRecommendation,
    RequirementAssessment,
    RequirementClassification,
    StarCompleteness,
    StarSourceType,
    StarStoryCandidate,
    TechnicalStudyTopic,
)
from ats_engine.kit.grounding import EvidenceContext, GroundingOutcome, ground_text
from ats_engine.models import JDProfile, Profile
from ats_engine.providers.base import LLMProvider, generate_text

_STAR_TAGS = re.compile(
    r"\bSituation\s*:\s*(?P<situation>.*?)\s+Task\s*:\s*(?P<task>.*?)\s+"
    r"Action\s*:\s*(?P<action>.*?)\s+Result\s*:\s*(?P<result>.+)$",
    re.I,
)


def _priority(item: RequirementAssessment) -> InterviewPriority:
    if item.must_have or item.importance == "required":
        return InterviewPriority.HIGH
    if item.classification is RequirementClassification.PROVEN:
        return InterviewPriority.MEDIUM
    return InterviewPriority.LOW


def _focus(item: RequirementAssessment) -> InterviewFocusArea:
    if item.classification is RequirementClassification.PROVEN:
        guidance = f"Prepare one evidence-backed example showing {item.requirement}."
    elif item.classification is RequirementClassification.ADJACENT:
        guidance = f"Position the real adjacent capability without claiming direct {item.requirement} experience."
    elif item.classification is RequirementClassification.WORKING_KNOWLEDGE:
        guidance = f"Keep {item.requirement} at working-knowledge level and prepare fundamentals."
    else:
        guidance = f"Prepare to acknowledge the {item.requirement} gap directly and explain a practical study plan."
    return InterviewFocusArea(item.id, item.requirement, item.classification, _priority(item), guidance, item.evidence)


def _answer_guide(item: RequirementAssessment) -> InterviewAnswerGuide:
    evidence_points = [ref.excerpt for ref in item.evidence if ref.excerpt]
    if item.classification is RequirementClassification.PROVEN:
        answer = f"My resume provides direct evidence for {item.requirement}."
        avoid = [
            f"Do not add projects, metrics, ownership, duration, or scale beyond the cited {item.requirement} evidence."
        ]
        gap = ""
    elif item.classification is RequirementClassification.ADJACENT:
        answer = f"I do not claim direct {item.requirement} experience; I can discuss the adjacent capability in my evidence."
        avoid = [f"Do not describe {item.requirement} as hands-on experience or expertise."]
        gap = f"State that {item.requirement} is adjacent, then name only the evidenced related capability."
    elif item.classification is RequirementClassification.WORKING_KNOWLEDGE:
        answer = f"My resume supports working knowledge of {item.requirement}"
        avoid = [f"Do not claim production use, expertise, or years of {item.requirement} experience."]
        gap = f"Describe {item.requirement} as working knowledge and discuss concepts you can review."
    else:
        answer = f"I do not have resume evidence for {item.requirement}; I would acknowledge that gap directly."
        avoid = [
            f"Do not imply hands-on {item.requirement} experience or say you are currently learning it without evidence."
        ]
        gap = f"Acknowledge the {item.requirement} gap and offer a concrete future learning plan without claiming current study."
    return InterviewAnswerGuide(evidence_points, avoid, answer, gap, item.evidence)


def _questions(job_fit: JobFitArtifact) -> list[InterviewQuestion]:
    questions = [
        InterviewQuestion(
            id="question-000",
            category=InterviewQuestionCategory.MOTIVATION,
            question="What interests you about this target role and its stated responsibilities?",
            rationale="A role-motivation topic is useful preparation; this is not a prediction of an exact question.",
            related_requirement_ids=[],
            priority=InterviewPriority.MEDIUM,
            answer_guide=InterviewAnswerGuide(
                key_points=["Connect only resume-supported strengths to responsibilities stated in the JD."],
                statements_to_avoid=["Do not invent company facts, internal initiatives, or prior employment there."],
                suggested_answer="I would connect my supported experience to the responsibilities stated in the job description.",
            ),
        )
    ]
    for index, item in enumerate(job_fit.requirements, start=1):
        if item.classification is RequirementClassification.PROVEN:
            category = InterviewQuestionCategory.TECHNICAL
            text = f"What resume-supported example best demonstrates your experience with {item.requirement}?"
        elif item.classification is RequirementClassification.GENUINE_GAP:
            category = InterviewQuestionCategory.GAP_CLARIFICATION
            text = f"How would you discuss the current evidence gap for {item.requirement} honestly?"
        else:
            category = InterviewQuestionCategory.ROLE_SPECIFIC
            text = f"How would you accurately position your current evidence level for {item.requirement}?"
        questions.append(
            InterviewQuestion(
                id=f"question-{index:03d}",
                category=category,
                question=text,
                rationale=f"{item.requirement} is a {item.importance} JD requirement and a likely topic to prepare for.",
                related_requirement_ids=[item.id],
                priority=_priority(item),
                answer_guide=_answer_guide(item),
                evidence=item.evidence,
                gap_relevance=(
                    item.classification.value if item.classification is not RequirementClassification.PROVEN else ""
                ),
            )
        )
    if job_fit.requirements:
        first = job_fit.requirements[0]
        questions.append(
            InterviewQuestion(
                id=f"question-{len(questions):03d}",
                category=InterviewQuestionCategory.ROLE_SPECIFIC,
                question=f"How would you approach the role's stated responsibility involving {first.requirement}?",
                rationale="A role-specific responsibility topic is useful preparation, without claiming certainty.",
                related_requirement_ids=[first.id],
                priority=_priority(first),
                answer_guide=_answer_guide(first),
                evidence=first.evidence,
                gap_relevance=(
                    first.classification.value if first.classification is not RequirementClassification.PROVEN else ""
                ),
            )
        )
    return questions


def _story_from_bullet(
    *,
    index: int,
    source_type: StarSourceType,
    organization: str,
    role: str,
    bullet: str,
    locator: str,
) -> StarStoryCandidate:
    tagged = _STAR_TAGS.search(bullet)
    if tagged:
        situation, task, action, result = (
            tagged.group(name).strip(" .") for name in ("situation", "task", "action", "result")
        )
        missing: list[str] = []
    else:
        situation = f"Context: {organization} — {role}."
        task = ""
        result_match = re.search(
            r"\b((?:reducing|increasing|improving|achieving|maintaining|saving)\b.*(?:\d|percent|hours?|minutes?|users?|customers?).*)$",
            bullet,
            re.I,
        )
        if result_match:
            result = result_match.group(1).strip(" ,.")
            action = bullet[: result_match.start()].strip(" ,.")
            missing = ["task"]
        else:
            action = bullet
            result = ""
            missing = ["task", "result"]
    completeness = StarCompleteness.COMPLETE if not missing else StarCompleteness.INCOMPLETE
    evidence = [
        EvidenceRef(
            source="candidate_resume",
            locator=f"{locator}:bullet",
            excerpt=bullet[:EVIDENCE_EXCERPT_MAX_CHARS],
        )
    ]
    guidance = (
        "All STAR components are present in this single source bullet; preserve its wording and context."
        if completeness is StarCompleteness.COMPLETE
        else "Use this as an incomplete outline. Add missing facts only from personal recollection after verifying them; do not invent a result or metric."
    )
    return StarStoryCandidate(
        id=f"star-{index:03d}",
        source_type=source_type,
        employer_or_institution=organization,
        title_or_degree=role,
        situation=situation,
        task=task,
        action=action,
        result=result,
        completeness=completeness,
        missing_components=missing,
        safe_usage_guidance=guidance,
        evidence=evidence,
    )


def _star_stories(profile: Profile) -> list[StarStoryCandidate]:
    stories: list[StarStoryCandidate] = []
    index = 1
    for exp_index, exp in enumerate(profile.experiences):
        for bullet_index, bullet in enumerate(exp.bullets[:2]):
            stories.append(
                _story_from_bullet(
                    index=index,
                    source_type=StarSourceType.PROFESSIONAL,
                    organization=exp.company,
                    role=exp.title,
                    bullet=bullet,
                    locator=f"experience:{exp_index}:{exp.company}:{exp.title}:{bullet_index}",
                )
            )
            index += 1
    for edu_index, edu in enumerate(profile.education):
        for bullet_index, bullet in enumerate(edu.bullets[:1]):
            stories.append(
                _story_from_bullet(
                    index=index,
                    source_type=StarSourceType.EDUCATION,
                    organization=edu.institution,
                    role=edu.degree,
                    bullet=bullet,
                    locator=f"education:{edu_index}:{edu.institution}:{edu.degree}:{bullet_index}",
                )
            )
            index += 1
    return stories


def _story_questions(stories: list[StarStoryCandidate]) -> list[InterviewQuestion]:
    questions: list[InterviewQuestion] = []
    for index, story in enumerate(stories[:3], start=1):
        points = [ref.excerpt for ref in story.evidence if ref.excerpt]
        questions.append(
            InterviewQuestion(
                id=f"behavior-{index:03d}",
                category=InterviewQuestionCategory.BEHAVIORAL,
                question="Tell me about a resume-supported example of delivery or problem solving.",
                rationale="Behavioral delivery is a useful topic to prepare; use only this one source context.",
                related_requirement_ids=[],
                priority=InterviewPriority.MEDIUM,
                answer_guide=InterviewAnswerGuide(
                    key_points=points,
                    statements_to_avoid=["Do not merge another role or invent a missing STAR component."],
                    suggested_answer=(
                        f"At {story.employer_or_institution} as {story.title_or_degree}, I can discuss only the supported action: {story.action}"
                    ),
                    evidence=story.evidence,
                ),
                evidence=story.evidence,
            )
        )
    if stories:
        story = stories[0]
        questions.append(
            InterviewQuestion(
                id="problem-001",
                category=InterviewQuestionCategory.PROBLEM_SOLVING,
                question="How did you approach a problem described in your resume evidence?",
                rationale="Problem-solving is a useful preparation topic grounded in one resume bullet.",
                related_requirement_ids=[],
                priority=InterviewPriority.MEDIUM,
                answer_guide=InterviewAnswerGuide(
                    key_points=[ref.excerpt for ref in story.evidence if ref.excerpt],
                    statements_to_avoid=["Do not add an unevidenced problem, action, or outcome."],
                    suggested_answer=f"I can discuss this supported action without adding a result: {story.action}",
                    evidence=story.evidence,
                ),
                evidence=story.evidence,
            )
        )
    return questions


def _credential_questions(profile: Profile) -> list[InterviewQuestion]:
    questions: list[InterviewQuestion] = []
    for index, certification in enumerate(profile.certifications[:2], start=1):
        excerpt = " ".join(part for part in (certification.name, certification.date) if part)
        evidence = [
            EvidenceRef(
                source="candidate_resume",
                locator=f"certification:{index - 1}",
                excerpt=excerpt[:EVIDENCE_EXCERPT_MAX_CHARS],
            )
        ]
        questions.append(
            InterviewQuestion(
                id=f"credential-{index:03d}",
                category=InterviewQuestionCategory.ROLE_SPECIFIC,
                question="Which resume-listed certification is relevant to discuss for this role?",
                rationale="A verified credential may be useful context when relevant; do not add unlisted credentials.",
                related_requirement_ids=[],
                priority=InterviewPriority.LOW,
                answer_guide=InterviewAnswerGuide(
                    key_points=[excerpt],
                    statements_to_avoid=["Do not claim a credential, issuer, scope, or date absent from the resume."],
                    suggested_answer=f"My resume lists {certification.name}",
                    evidence=evidence,
                ),
                evidence=evidence,
            )
        )
    return questions


def _study_topics(job_fit: JobFitArtifact) -> list[TechnicalStudyTopic]:
    return [
        TechnicalStudyTopic(
            requirement_id=item.id,
            topic=item.requirement,
            reason=f"Review this {item.importance} JD topic because the evidence classification is {item.classification.value}.",
            boundary="Study recommendation only; not candidate experience and not evidence of current learning.",
            priority=_priority(item),
        )
        for item in job_fit.requirements
        if item.classification is not RequirementClassification.PROVEN
    ]


def _gap_guides(job_fit: JobFitArtifact) -> list[GapHandlingGuide]:
    return [
        GapHandlingGuide(
            requirement_id=item.id,
            requirement=item.requirement,
            classification=item.classification,
            must_have=item.must_have,
            guidance=_answer_guide(item).honest_gap_language,
            what_to_avoid=_answer_guide(item).statements_to_avoid,
            evidence=item.evidence,
        )
        for item in job_fit.requirements
        if item.classification is not RequirementClassification.PROVEN
    ]


def _interviewer_questions(jd_profile: JDProfile) -> list[InterviewerQuestion]:
    result = [
        InterviewerQuestion(
            "ask-001",
            "What outcomes would define success in the first 90 days?",
            "Clarifies success expectations absent from most JDs.",
            "missing_role_detail",
        ),
        InterviewerQuestion(
            "ask-002",
            "What are the most important current challenges for this role to address?",
            "Invites the interviewer to supply current context without assuming company facts.",
            "missing_role_detail",
        ),
    ]
    if jd_profile.responsibilities:
        result.append(
            InterviewerQuestion(
                "ask-003",
                f"How does the team approach this stated responsibility: {jd_profile.responsibilities[0][:120]}?",
                "Derived directly from a responsibility in the supplied JD.",
                "job_description_responsibility",
            )
        )
    if jd_profile.technical_keywords:
        result.append(
            InterviewerQuestion(
                "ask-004",
                f"How is {jd_profile.technical_keywords[0]} used in the work described for this role?",
                "Derived directly from a technology named in the supplied JD.",
                "job_description_technology",
            )
        )
    return result


def _fallback_summary(job_fit: JobFitArtifact) -> str:
    parts = [
        "Prepare evidence-backed examples for the proven requirements and keep every answer within one resume context."
    ]
    if job_fit.adjacent_capabilities:
        parts.append(
            "Present adjacent capabilities as related experience only: "
            + ", ".join(job_fit.adjacent_capabilities)
            + "."
        )
    if job_fit.working_knowledge:
        parts.append(
            "Keep working knowledge distinct from production experience: " + ", ".join(job_fit.working_knowledge) + "."
        )
    if job_fit.genuine_gaps:
        parts.append("Acknowledge genuine gaps directly: " + ", ".join(job_fit.genuine_gaps) + ".")
    if job_fit.must_have_gaps:
        parts.append("Prioritize honest preparation for must-have gaps: " + ", ".join(job_fit.must_have_gaps) + ".")
    return " ".join(parts)


def _prompt(job_fit: JobFitArtifact, fallback: str) -> str:
    brief = [
        {
            "requirement": item.requirement,
            "importance": item.importance,
            "classification": item.classification.value,
            "permitted_positioning": item.permitted_positioning,
            "evidence": [ref.excerpt for ref in item.evidence],
        }
        for item in job_fit.requirements
    ]
    return (
        "Rewrite only the INTERVIEW STRATEGY SUMMARY from this bounded authoritative brief. "
        "Do not invent candidate employers, titles, projects, clients, actions, metrics, team sizes, dates, credentials, education, or experience. "
        "Do not merge roles, alter classifications, hide gaps, claim current learning, create company facts, or claim certainty about interview questions. "
        "Adjacent is not expertise; working knowledge is not production experience. Include every must-have gap. "
        f"Brief: {json.dumps(brief, ensure_ascii=False)}\nSafe fallback: {fallback}"
    )


def _ground_summary(
    text: str,
    *,
    job_fit: JobFitArtifact,
    context: EvidenceContext,
    id_prefix: str,
) -> GroundingOutcome:
    replacements: dict[str, str] = {}
    masked = text
    for index, item in enumerate(job_fit.requirements):
        if item.classification is RequirementClassification.PROVEN:
            continue
        token = f"INTERVIEW_REQUIREMENT_{index:03d}"
        masked = masked.replace(item.requirement, token)
        replacements[token] = item.requirement
    outcome = ground_text(masked, artifact=ArtifactKind.INTERVIEW_PREP, context=context, id_prefix=id_prefix)
    for token, value in replacements.items():
        outcome.clean_text = outcome.clean_text.replace(token, value)
    return outcome


def _ground_structured_prose(
    *,
    questions: list[InterviewQuestion],
    stories: list[StarStoryCandidate],
    job_fit: JobFitArtifact,
    context: EvidenceContext,
) -> tuple[list[ClaimRecord], int, int, bool]:
    claims: list[ClaimRecord] = []
    repaired = 0
    rejected = 0
    fatal = False

    def apply(outcome: GroundingOutcome) -> str:
        nonlocal repaired, rejected, fatal
        claims.extend(outcome.claims)
        repaired += outcome.repaired
        rejected += outcome.rejected
        fatal = fatal or outcome.fatal
        return outcome.clean_text

    assessments = {item.id: item for item in job_fit.requirements}
    for question in questions:
        related = [assessments[item_id] for item_id in question.related_requirement_ids if item_id in assessments]
        # Non-proven answer guides are authoritative boundary statements (for
        # example "working knowledge", "adjacent", or "no resume evidence"),
        # not affirmative candidate-experience claims. Running the generic
        # skill extractor over their negated wording would erase the safety
        # boundary itself. Proven and source-event answers still pass through
        # the candidate-claim grounder below.
        if not related or all(item.classification is RequirementClassification.PROVEN for item in related):
            question.answer_guide.suggested_answer = apply(
                _ground_summary(
                    question.answer_guide.suggested_answer,
                    job_fit=job_fit,
                    context=context,
                    id_prefix=f"{question.id}-answer",
                )
            )
        question.answer_guide.key_points = [
            apply(
                ground_text(
                    point,
                    artifact=ArtifactKind.INTERVIEW_PREP,
                    context=context,
                    id_prefix=f"{question.id}-point-{index}",
                )
            )
            for index, point in enumerate(question.answer_guide.key_points)
        ]
    for story in stories:
        for field_name in ("situation", "task", "action", "result"):
            value = getattr(story, field_name)
            if not value:
                continue
            setattr(
                story,
                field_name,
                apply(
                    ground_text(
                        value,
                        artifact=ArtifactKind.INTERVIEW_PREP,
                        context=context,
                        id_prefix=f"{story.id}-{field_name}",
                    )
                ),
            )
    return claims, repaired, rejected, fatal


def build_interview_prep_artifact(
    *,
    profile: Profile,
    jd_profile: JDProfile,
    job_fit: JobFitArtifact,
    context: EvidenceContext,
    provider: LLMProvider | None,
) -> InterviewPrepArtifact:
    """Build complete interview preparation; deterministic structure is authoritative."""
    focus_areas = [_focus(item) for item in job_fit.requirements]
    stories = _star_stories(profile)
    questions = _questions(job_fit) + _story_questions(stories) + _credential_questions(profile)
    study_topics = _study_topics(job_fit)
    gap_handling = _gap_guides(job_fit)
    interviewer_questions = _interviewer_questions(jd_profile)
    recommendations = [
        PositioningRecommendation(item.requirement_id, item.text) for item in job_fit.positioning_recommendations
    ]
    fallback = _fallback_summary(job_fit)
    candidate = generate_text(provider, _prompt(job_fit, fallback))
    grounded = _ground_summary(candidate or fallback, job_fit=job_fit, context=context, id_prefix="interview-strategy")
    structured_claims, structured_repaired, structured_rejected, structured_fatal = _ground_structured_prose(
        questions=questions,
        stories=stories,
        job_fit=job_fit,
        context=context,
    )
    summary = grounded.clean_text
    errors = validate_interview_prep(
        strategy_summary=summary,
        focus_areas=focus_areas,
        questions=questions,
        star_stories=stories,
        study_topics=study_topics,
        gap_handling=gap_handling,
        interviewer_questions=interviewer_questions,
        job_fit=job_fit,
        profile=profile,
        jd_profile=jd_profile,
    )
    repaired_violations = list(errors)
    fallback_grounded: GroundingOutcome | None = None
    if errors or grounded.fatal:
        fallback_grounded = _ground_summary(fallback, job_fit=job_fit, context=context, id_prefix="interview-fallback")
        summary = fallback_grounded.clean_text
    final_errors = validate_interview_prep(
        strategy_summary=summary,
        focus_areas=focus_areas,
        questions=questions,
        star_stories=stories,
        study_topics=study_topics,
        gap_handling=gap_handling,
        interviewer_questions=interviewer_questions,
        job_fit=job_fit,
        profile=profile,
        jd_profile=jd_profile,
    )
    fatal = structured_fatal or bool(final_errors) or bool(fallback_grounded and fallback_grounded.fatal)
    repaired = (
        grounded.repaired
        + structured_repaired
        + len(repaired_violations)
        + (fallback_grounded.repaired if fallback_grounded else 0)
    )
    warnings = [f"Interview preparation repaired: {error}" for error in repaired_violations]
    if candidate and grounded.repaired:
        warnings.append("Unsupported candidate claims were removed from provider interview strategy prose.")
    status = ArtifactStatus.REJECTED if fatal else (ArtifactStatus.REPAIRED if repaired else ArtifactStatus.GENERATED)
    claims: list[ClaimRecord] = (
        grounded.claims + structured_claims + (fallback_grounded.claims if fallback_grounded else [])
    )
    evidence = [ref for item in focus_areas for ref in item.evidence]
    return InterviewPrepArtifact(
        strategy_summary="" if fatal else summary,
        focus_areas=focus_areas,
        questions=questions,
        star_stories=stories,
        technical_study_topics=study_topics,
        gap_handling=gap_handling,
        positioning_recommendations=recommendations,
        interviewer_questions=interviewer_questions,
        validation=ArtifactValidation(
            status=status,
            fatal=fatal,
            errors=final_errors,
            warnings=warnings,
            repaired_claims=repaired,
            rejected_claims=(
                grounded.rejected + structured_rejected + (fallback_grounded.rejected if fallback_grounded else 0)
            ),
        ),
        consistency=ConsistencyValidation(not final_errors, final_errors, repaired_violations),
        generation=GenerationMetadata(generation_mode="deterministic", llm_available=False),
        claims=claims,
        evidence=evidence,
        warnings=warnings,
        withheld=fatal,
    )
