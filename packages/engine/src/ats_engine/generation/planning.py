from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime
from typing import cast

from ats_engine.evidence.matrix import build_evidence_matrix, interview_probability
from ats_engine.generation.prompts import PROHIBITED_INVENTION_CLAUSE
from ats_engine.models import (
    AnswerPlan,
    ContactInfo,
    CoverLetterPlan,
    EvidenceItem,
    Experience,
    JDProfile,
    Profile,
    ResumePlan,
)
from ats_engine.parsing.resume import find_metrics, term_in_text
from ats_engine.providers.base import LLMProvider, generate_json, generate_text, run_concurrently
from ats_engine.validation.repair import soften_banned_style
from ats_engine.validation.style import validate_style

"""Plan construction: turn evidence + profile + JD into grounded resume/letter plans.

Every plan is built deterministically first. A provider, when supplied, only
rewrites prose (summary, bullets, letter body, open-ended answers), and every
rewrite is re-validated against the candidate's evidence — unsupported metrics
or newly-introduced tools cause the rewrite to be rejected in favor of the
untouched original. The provider is never trusted to add facts.
"""


def build_resume_plan(
    *,
    contacts: ContactInfo,
    jd_profile: JDProfile,
    profile: Profile,
    provider: LLMProvider | None = None,
    batch_provider: LLMProvider | None = None,
) -> ResumePlan:
    """Create a resume plan grounded entirely in the candidate's own profile.

    ``provider`` writes short prose (the summary); ``batch_provider`` handles the
    bulk JSON bullet rewrite, which benefits from a larger output budget. Pass
    the same provider for both if there is no need to distinguish them.
    """
    batch_provider = batch_provider if batch_provider is not None else provider
    evidence = build_evidence_matrix(jd_profile, profile)
    role_identity = choose_role_identity(jd_profile, profile)
    top_keywords = _top_keywords(evidence)
    years_span = _career_years(profile.experiences)
    working_knowledge = [item.real_evidence for item in evidence if item.evidence_tier == "C" and item.real_evidence]
    skill_groups = _build_skill_groups(evidence, profile, working_knowledge)

    # The summary and the bullet rewrite are independent provider calls; running
    # them concurrently instead of back-to-back roughly halves this part of the
    # pipeline's wall-clock time whenever a model is available.
    results = run_concurrently(
        {
            "summary": lambda: _build_summary(role_identity, top_keywords, jd_profile, profile, years_span, provider),
            "experience": lambda: _select_experience(profile, evidence, jd_profile, batch_provider),
        }
    )
    summary = cast(str, results["summary"])
    experience = cast("list[Experience]", results["experience"])
    residual_gap = _first_gap(evidence)
    probability = interview_probability(evidence)
    analysis = _analysis_lines(evidence, residual_gap, jd_profile)
    headline = _headline(jd_profile, role_identity, evidence)
    work_mode_line = _work_mode_line(jd_profile)

    return ResumePlan(
        contacts=contacts,
        jd_profile=jd_profile,
        evidence=evidence,
        role_identity=role_identity,
        headline=headline,
        work_mode_line=work_mode_line,
        summary=summary,
        skill_groups=skill_groups,
        experience=experience,
        education=profile.education,
        certifications=profile.certifications,
        working_knowledge=working_knowledge,
        residual_gap=residual_gap,
        interview_probability=probability,
        analysis=analysis,
    )


def build_cover_letter_plan(
    resume_plan: ResumePlan,
    profile: Profile,
    provider: LLMProvider | None = None,
) -> CoverLetterPlan:
    """Create a cover-letter plan with mandatory logistics and fast-ramp logic."""
    jd = resume_plan.jd_profile
    company = jd.company or "your team"
    title = jd.title or resume_plan.role_identity
    domain_hook = jd.domain or "your team's"
    proof_points = _cover_proof_points(resume_plan)
    fast_ramp_items = [
        item.keyword
        for item in resume_plan.evidence
        if item.evidence_tier in {"C", "adjacency", "missing"} and item.required_or_preferred == "required"
    ]
    needs_fast_ramp = bool(fast_ramp_items)
    angle = f"{resume_plan.role_identity} fit for {title} at {company}"
    body = _build_cover_letter_body(
        title=title,
        company=company,
        domain_hook=domain_hook,
        proof_points=proof_points,
        plan=resume_plan,
        profile=profile,
        needs_fast_ramp=needs_fast_ramp,
        fast_ramp_items=fast_ramp_items,
        provider=provider,
    )
    word_count = _body_word_count(body)
    return CoverLetterPlan(
        contacts=resume_plan.contacts,
        jd_profile=jd,
        angle=angle,
        body_paragraphs=body,
        word_count=word_count,
        needs_fast_ramp=needs_fast_ramp,
    )


def build_answer_plan(
    *,
    questions: list[str],
    resume_plan: ResumePlan,
    provider: LLMProvider | None = None,
) -> AnswerPlan:
    """Create paste-ready answers for application and screening questions.

    Logistics questions (salary, start date, sponsorship, work mode) are answered
    instantly from resolved contact facts, no provider needed. Any remaining
    open-ended questions each need one provider call; those calls are independent
    of each other, so they run concurrently rather than one question at a time.
    """
    answers: list[str | None] = [None] * len(questions)
    placeholders: list[str] = []
    open_questions: dict[int, str] = {}

    for index, question in enumerate(questions):
        lowered = question.lower()
        if "salary" in lowered or "compensation" in lowered:
            answers[index] = (
                "My target range is [YOUR RANGE], depending on total compensation, role scope, and work mode."
            )
            placeholders.append("[YOUR RANGE]")
        elif "start" in lowered or "available" in lowered:
            location_clause = (
                f" I am based in {resume_plan.contacts.location}." if resume_plan.contacts.location else ""
            )
            answers[index] = (
                f"I can start on [YOUR START DATE].{location_clause} I can align with the role's work mode."
            )
            placeholders.append("[YOUR START DATE]")
        elif "sponsor" in lowered or "legally" in lowered or "work in" in lowered:
            answers[index] = (
                resume_plan.contacts.work_authorization
                or "I am legally eligible to work in this location without sponsorship."
            )
        elif "relocat" in lowered or "remote" in lowered or "hybrid" in lowered:
            base = f"I am based in {resume_plan.contacts.location}." if resume_plan.contacts.location else ""
            answers[index] = (
                f"{base} I am open to the role's work mode and open to relocation for the right opportunity.".strip()
            )
        else:
            open_questions[index] = question

    if open_questions:

        def answer_task(q: str) -> Callable[[], str]:
            return lambda: _long_answer(q, resume_plan, provider)

        tasks: dict[str, Callable[[], str]] = {
            str(index): answer_task(question) for index, question in open_questions.items()
        }
        computed = run_concurrently(tasks, max_workers=min(6, len(tasks)))
        for index in open_questions:
            answers[index] = computed[str(index)]

    return AnswerPlan(
        questions=questions,
        answers=[answer or "" for answer in answers],
        placeholders=_dedupe(placeholders),
    )


def choose_role_identity(jd_profile: JDProfile, profile: Profile) -> str:
    """Choose the candidate's own closest real job title to the JD's title."""
    target = f"{jd_profile.title} {' '.join(jd_profile.technical_keywords)}".lower()
    for role in profile.role_identities:
        role_tokens = [token for token in role.lower().split() if len(token) > 2]
        if any(token in target for token in role_tokens):
            return role
    if profile.role_identities:
        return profile.role_identities[0]
    return "Professional"


def _headline(jd_profile: JDProfile, role_identity: str, evidence: list[EvidenceItem]) -> str:
    # A target job title is never a substitute for the candidate's supported identity.
    title = role_identity
    keywords = _dedupe(
        [
            item.real_evidence if item.evidence_tier == "adjacency" and item.real_evidence else item.keyword
            for item in evidence
            if item.evidence_tier in {"A", "B", "adjacency"} and len(item.keyword) > 2
        ]
    )[:3]
    suffix = ", ".join(keywords)
    return f"{title} | {suffix}" if suffix else title


def _work_mode_line(jd_profile: JDProfile) -> str:
    if jd_profile.work_mode == "unknown":
        return "Open to the role's work mode"
    if jd_profile.location:
        return f"Open to {jd_profile.work_mode} work in {jd_profile.location}"
    return f"Open to {jd_profile.work_mode} work"


def _top_keywords(evidence: list[EvidenceItem]) -> list[str]:
    useful = [
        item.real_evidence if item.evidence_tier == "adjacency" and item.real_evidence else item.keyword
        for item in evidence
        if item.evidence_tier in {"A", "B", "adjacency"} and item.required_or_preferred == "required"
    ]
    useful.extend(item.keyword for item in evidence if item.evidence_tier in {"A", "B"})
    return _dedupe(useful)[:5]


def _career_years(experiences: list[Experience]) -> int | None:
    years: list[int] = []
    is_current = False
    for experience in experiences:
        found = re.findall(r"(?:19|20)\d{2}", experience.dates)
        years.extend(int(year) for year in found)
        if re.search(r"present|current", experience.dates, flags=re.IGNORECASE):
            is_current = True
    if not years:
        return None
    end = datetime.now().year if is_current else max(years)
    span = end - min(years)
    return span if span > 0 else None


def _experience_highlights(profile: Profile, limit: int = 6) -> str:
    lines: list[str] = []
    for experience in profile.experiences:
        for bullet in experience.bullets[:2]:
            lines.append(f"- ({experience.company}, {experience.title}) {bullet}")
            if len(lines) >= limit:
                return "\n".join(lines)
    return "\n".join(lines) or "No detailed bullets were found in the resume."


def _build_summary(
    role_identity: str,
    top_keywords: list[str],
    jd_profile: JDProfile,
    profile: Profile,
    years_span: int | None,
    provider: LLMProvider | None,
) -> str:
    fallback = _fallback_summary(role_identity, top_keywords, jd_profile, years_span)
    if provider is None:
        return fallback

    years_line = (
        f"The candidate has roughly {years_span} years of career experience based on their earliest role; you may state this."
        if years_span
        else "Years of experience cannot be reliably determined; do not state a specific number of years."
    )
    prompt = (
        "Write a 3 to 4 sentence professional resume summary tailored to the target role below. "
        "Ground every claim only in the candidate facts provided; never invent employers, tools, or numbers.\n\n"
        f"Role identity to use: {role_identity}\n"
        f"Target job title: {jd_profile.title}\n"
        f"Target company: {jd_profile.company}\n"
        f"Domain: {jd_profile.domain or 'not specified'}\n"
        f"Keywords to mirror where truthful: {', '.join(top_keywords) or 'none specific'}\n"
        f"{years_line}\n\n"
        f"Candidate's real experience highlights:\n{_experience_highlights(profile)}\n\n"
        "Rules: no em dashes, en dashes, or double hyphens. Do not state any number, percentage, or metric "
        "that is not already given above. Avoid cliche resume filler (results-driven, detail-oriented, "
        "passionate about, proven track record, dynamic, innovative, seamless, robust, leveraged, spearheaded, "
        "architected, orchestrated, streamlined).\n\n"
        f"{PROHIBITED_INVENTION_CLAUSE}\n\n"
        "Return ONLY the summary text, no headers, no quotes."
    )

    def validate(candidate: str) -> bool:
        if not (30 <= len(candidate.split()) <= 140):
            return False
        if not _style_ok(candidate):
            return False
        allowed = {metric.lower() for metric in profile.supported_metrics}
        if years_span:
            allowed.update({f"{years_span}+ years", f"{years_span} years"})
        found = {metric.lower() for metric in find_metrics(candidate)}
        if not found.issubset(allowed):
            return False
        return not _mentions_tier_c(candidate, profile)

    return _llm_generate(provider, prompt, validate, fallback)


def _fallback_summary(
    role_identity: str,
    top_keywords: list[str],
    jd_profile: JDProfile,
    years_span: int | None,
) -> str:
    first = top_keywords[0] if top_keywords else "core tools"
    second = top_keywords[1] if len(top_keywords) > 1 else "day-to-day delivery"
    domain = jd_profile.domain or "a range of environments"
    years_clause = f" with {years_span}+ years of experience" if years_span else ""
    return (
        f"{role_identity}{years_clause}, working across {first} and {second}. "
        f"Brings direct delivery experience aligned with {domain} needs. "
        f"Focused on shipping reliable, well-scoped work and communicating clearly with stakeholders."
    )


def _build_skill_groups(
    evidence: list[EvidenceItem],
    profile: Profile,
    working_knowledge: list[str],
) -> list[tuple[str, list[str]]]:
    relevant = _dedupe(
        [
            item.real_evidence or item.keyword
            for item in evidence
            if item.evidence_tier in {"A", "B", "adjacency"} and item.real_evidence
        ]
    )
    all_tier_a = list(profile.tier_a.values())
    all_tier_b = list(profile.tier_b.values())

    core = _dedupe(relevant + all_tier_a)
    additional = [skill for skill in _dedupe(all_tier_b) if skill.lower() not in {item.lower() for item in core}]
    working = [
        skill
        for skill in _dedupe(list(profile.tier_c.values()) + working_knowledge)
        if skill.lower() not in {item.lower() for item in core + additional}
    ]

    groups: list[tuple[str, list[str]]] = []
    if core:
        groups.append(("Core Skills", core))
    if additional:
        groups.append(("Additional Skills", additional))
    if working:
        groups.append(("Working Knowledge", working))
    return groups


def _select_experience(
    profile: Profile,
    evidence: list[EvidenceItem],
    jd_profile: JDProfile,
    provider: LLMProvider | None,
) -> list[Experience]:
    keywords = [item.keyword.lower() for item in evidence if item.evidence_tier != "missing"]
    entries: list[tuple[Experience, list[str]]] = []

    for experience in profile.experiences:
        scored_bullets = sorted(
            experience.bullets,
            key=lambda bullet: _bullet_score(bullet, keywords),
            reverse=True,
        )
        chosen: list[str] = []
        for bullet in scored_bullets:
            chosen.append(soften_banned_style(bullet))
        if chosen:
            entries.append((experience, chosen))

    all_originals = [bullet for _, chosen in entries for bullet in chosen]
    # Bullets already carrying two or more JD keywords are targeted as-is;
    # rewriting them spends tokens for little gain and risks quality drift.
    # Only the under-aligned bullets go to the model.
    needs_rewrite = [index for index, bullet in enumerate(all_originals) if _keyword_hits(bullet, keywords) < 2]
    rewritten_flat = list(all_originals)
    if provider is not None and needs_rewrite:
        batch = [all_originals[index] for index in needs_rewrite]
        rewritten_batch = _rewrite_bullets_batch(batch, jd_profile, keywords, profile, provider)
        for position, index in enumerate(needs_rewrite):
            rewritten_flat[index] = rewritten_batch[position]

    selected: list[Experience] = []
    cursor = 0
    for experience, chosen in entries:
        count = len(chosen)
        final_bullets = rewritten_flat[cursor : cursor + count]
        cursor += count
        selected.append(
            Experience(
                company=experience.company,
                title=experience.title,
                location=experience.location,
                dates=experience.dates,
                bullets=final_bullets,
            )
        )
    return selected


def _rewrite_bullets_batch(
    bullets: list[str],
    jd_profile: JDProfile,
    keywords: list[str],
    profile: Profile,
    provider: LLMProvider,
) -> list[str]:
    """Rewrite every selected bullet in a single provider call instead of one per bullet.

    This is the single biggest latency lever in the pipeline: a resume with 20
    selected bullets used to mean 20+ sequential round trips. Batching cuts that
    to one call, with the same per-bullet groundedness checks applied to each
    item in the response, falling back to that item's untouched original on any
    failure.
    """
    top_keywords = ", ".join(keywords[:6]) or "none specific"
    numbered = "\n".join(f"{index + 1}. {bullet}" for index, bullet in enumerate(bullets))
    prompt = (
        "Rewrite each of the following resume bullets so it foregrounds the target job's priorities, "
        "while staying 100% factually identical to its own original: same system, same tools, same scope, "
        "same numbers. Do not invent or drop any metric, tool, or outcome for any bullet, and do not name "
        "a tool that is not already in that bullet's original text. Keep each rewrite to one line, under "
        "34 words. Vary sentence openings across the set so consecutive bullets do not start the same way.\n\n"
        f"Target job title: {jd_profile.title}\n"
        f"Keywords to emphasize where truthful: {top_keywords}\n\n"
        f"Original bullets:\n{numbered}\n\n"
        "Rules: no em dashes, en dashes, or double hyphens. Avoid cliche resume verbs (leveraged, "
        "spearheaded, architected, orchestrated, streamlined, championed, synergized, facilitated).\n\n"
        f"{PROHIBITED_INVENTION_CLAUSE}\n\n"
        f"Return ONLY a JSON array of exactly {len(bullets)} strings, one rewritten bullet per input bullet, "
        "in the same order. No bullet numbers inside the strings, no commentary, no markdown fences."
    )

    data = generate_json(provider, prompt, retries=1)
    if not isinstance(data, list) or len(data) != len(bullets):
        return bullets

    known_skills = list(profile.tier_a) + list(profile.tier_b) + list(profile.tier_c)
    rewritten: list[str] = []
    for original, candidate in zip(bullets, data, strict=False):
        candidate_text = _clean_llm_line(str(candidate)) if candidate is not None else ""
        rewritten.append(candidate_text if _bullet_is_valid(candidate_text, original, known_skills) else original)
    return rewritten


def _bullet_is_valid(candidate: str, original: str, known_skills: list[str]) -> bool:
    if not candidate or len(candidate.split()) > 45:
        return False
    if not _style_ok(candidate):
        return False
    allowed = {metric.lower() for metric in find_metrics(original)}
    found = {metric.lower() for metric in find_metrics(candidate)}
    if not found.issubset(allowed):
        return False
    return not _introduces_new_skill(candidate, original, known_skills)


def _introduces_new_skill(rewritten: str, original: str, known_skills: list[str]) -> bool:
    """True when the rewrite names a known tool/skill that the original bullet did not."""
    original_lower = original.lower()
    rewritten_lower = rewritten.lower()
    for skill in known_skills:
        if term_in_text(skill, rewritten_lower) and not term_in_text(skill, original_lower):
            return True
    return False


def _mentions_tier_c(text: str, profile: Profile) -> bool:
    """Tier C ('working knowledge only') skills must never be claimed as summary/letter substance."""
    lowered = text.lower()
    return any(term_in_text(skill, lowered) for skill in profile.tier_c)


def _bullet_score(bullet: str, keywords: list[str]) -> int:
    lowered = bullet.lower()
    return sum(2 for keyword in keywords if keyword in lowered) + len(find_metrics(bullet))


def _keyword_hits(bullet: str, keywords: list[str]) -> int:
    lowered = bullet.lower()
    return sum(1 for keyword in keywords if keyword in lowered)


def _first_gap(evidence: list[EvidenceItem]) -> str:
    for item in evidence:
        if item.evidence_tier == "missing":
            return item.keyword
    for item in evidence:
        if item.evidence_tier == "C":
            return item.keyword
    return ""


def _analysis_lines(evidence: list[EvidenceItem], residual_gap: str, jd_profile: JDProfile) -> list[str]:
    strong = len([item for item in evidence if item.strength == "strong"])
    medium = len([item for item in evidence if item.strength == "medium"])
    missing = len([item for item in evidence if item.strength == "missing"])
    lines = [
        f"Coverage shows {strong} strong matches and {medium} medium matches against the role's required and preferred signals.",
    ]
    if residual_gap:
        lines.append(f"One honest residual gap is {residual_gap}; it is not claimed as direct experience.")
    elif jd_profile.work_mode != "unknown":
        lines.append(f"Logistics are aligned with {jd_profile.work_mode} work.")
    if missing >= 2:
        lines.append("Two or more required signals are missing, so the probability is intentionally conservative.")
    return lines[:4]


def _cover_proof_points(plan: ResumePlan) -> list[str]:
    points: list[str] = []
    for experience in plan.experience:
        points.extend(experience.bullets[:2])
    return points[:3]


def _build_cover_letter_body(
    *,
    title: str,
    company: str,
    domain_hook: str,
    proof_points: list[str],
    plan: ResumePlan,
    profile: Profile,
    needs_fast_ramp: bool,
    fast_ramp_items: list[str],
    provider: LLMProvider | None,
) -> list[str]:
    fallback = _fallback_cover_letter_body(
        title=title,
        company=company,
        domain_hook=domain_hook,
        proof_points=proof_points,
        plan=plan,
        needs_fast_ramp=needs_fast_ramp,
        fast_ramp_items=fast_ramp_items,
    )
    if provider is None:
        return fallback

    proof_text = (
        "\n".join(f"- {point}" for point in proof_points)
        or "- No specific bullets were available; speak generally about the candidate's background."
    )
    ramp_line = (
        f"The JD asks for {', '.join(_dedupe(fast_ramp_items)[:3])}, which the candidate has not used in production. "
        "P3 should honestly frame this as a fast-ramp story: name the closest real system they have delivered, "
        "and state they close tool gaps quickly, without claiming production experience with the missing tool."
        if needs_fast_ramp
        else "No major tool gap needs addressing; P3 can cover breadth or a third proof point instead."
    )
    work_mode_text = plan.jd_profile.work_mode if plan.jd_profile.work_mode != "unknown" else "the role's"
    logistics_line = _logistics_sentence(plan.contacts, work_mode_text)

    prompt = (
        "Write a cover letter body of exactly 4 paragraphs (P1 to P4), 280 to 320 words total, for the job "
        f"below. Ground every claim only in the proof points given; never invent employers, tools, or numbers.\n\n"
        f"Job title: {title}\n"
        f"Company: {company}\n"
        f"Domain/hook context: {domain_hook}\n\n"
        f"Candidate's real proof points (use only these facts):\n{proof_text}\n\n"
        f"P1 (50-65 words): the role applied for, who the candidate is in one clause, one concrete company hook, top two matching strengths.\n"
        f"P2 (80-100 words): proof, two condensed accomplishments mapped to the job's priorities, name real systems and tools, one metric max.\n"
        f"P3 (60-80 words): the differentiator. {ramp_line}\n"
        f"P4 (50-65 words): logistics and close. Must include, in the candidate's own words: {logistics_line}\n\n"
        "Rules: no em dashes, en dashes, or double hyphens. No flattery phrases like 'I am excited to apply', "
        "'esteemed organization', 'perfect fit', 'I would welcome the opportunity'. Do not state any number or "
        "percentage that is not already given above.\n\n"
        f"{PROHIBITED_INVENTION_CLAUSE}\n\n"
        "Return ONLY the four paragraphs separated by a blank line, no salutation, no signature, no headers."
    )

    def validate(candidate: str) -> bool:
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", candidate.strip()) if p.strip()]
        if len(paragraphs) < 3:
            return False
        if not _style_ok(candidate):
            return False
        allowed = {metric.lower() for metric in profile.supported_metrics}
        found = {metric.lower() for metric in find_metrics(candidate)}
        if not found.issubset(allowed):
            return False
        words = len(candidate.split())
        return 220 <= words <= 380

    raw = _llm_generate(provider, prompt, validate, "")
    if not raw:
        return fallback

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", raw.strip()) if p.strip()]
    return _fit_cover_letter_word_count(paragraphs)


def _logistics_sentence(contacts: ContactInfo, work_mode_text: str) -> str:
    parts = []
    if contacts.location:
        parts.append(f"based in {contacts.location}")
    if contacts.work_authorization:
        parts.append(contacts.work_authorization.lower())
    parts.append(f"open to {work_mode_text} work")
    if contacts.relocation:
        parts.append(contacts.relocation.lower())
    return ", ".join(parts) if parts else "open to the role's work mode"


def _fallback_cover_letter_body(
    *,
    title: str,
    company: str,
    domain_hook: str,
    proof_points: list[str],
    plan: ResumePlan,
    needs_fast_ramp: bool,
    fast_ramp_items: list[str],
) -> list[str]:
    first_proof = (
        proof_points[0] if proof_points else "The candidate has built software and data systems across multiple roles."
    )
    second_proof = (
        proof_points[1]
        if len(proof_points) > 1
        else "The candidate has combined technical delivery with stakeholder-facing work across roles."
    )
    third_proof = (
        proof_points[2]
        if len(proof_points) > 2
        else "The candidate's background spans multiple environments and team sizes."
    )
    ramp = ""
    if needs_fast_ramp:
        missing = ", ".join(_dedupe(fast_ramp_items)[:3])
        ramp = (
            f" Where the role calls for {missing}, the approach would be direct: map the tool to the closest "
            "systems already delivered, validate assumptions quickly, and describe the resulting work accurately."
        )
    work_mode_text = plan.jd_profile.work_mode if plan.jd_profile.work_mode != "unknown" else "the role's"
    contact = plan.contacts

    paragraphs = [
        (
            f"I am interested in the {title} role at {company} because it connects closely with my background in {domain_hook}. "
            f"I bring direct delivery experience with a practical record of turning operational needs into reliable tools."
        ),
        (
            f"My closest proof point is this: {_ensure_sentence(first_proof)} Another relevant proof point is this: {_ensure_sentence(second_proof)} "
            "That combination matters for this role because it shows I can work across systems, stakeholders, and delivery constraints without stretching beyond the facts."
        ),
        (
            f"Earlier work adds another signal: {_ensure_sentence(third_proof)} These experiences give me a useful base for the responsibilities in the posting.{ramp}"
        ),
        (
            f"{_sentence_case(_logistics_sentence(contact, work_mode_text))}. "
            f"I would be glad to discuss how my background can support {company}'s priorities."
        ),
    ]
    return _fit_cover_letter_word_count(paragraphs)


def _sentence_case(text: str) -> str:
    return f"{text[0].upper()}{text[1:]}" if text else text


def _ensure_sentence(text: str) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        return ""
    return cleaned if cleaned.endswith((".", "!", "?")) else f"{cleaned}."


_FILLER_SENTENCES = [
    "I work best where the problem is concrete, the users are close enough to learn from, and the output has to be useful in production or operations.",
    "I like being able to see the effect of my work quickly, whether that is a stakeholder saving time or a system running more reliably.",
    "I try to keep scope honest, shipping the smallest useful version first and building on what actually gets used.",
    "I care about clear documentation and handoffs, since a change nobody can maintain is not really finished.",
    "I would rather ask a clarifying question early than guess at a requirement and rework it later.",
    "I am comfortable moving between hands-on delivery and stakeholder conversations, since most useful work touches both.",
    "I pay attention to the details that break in production, not just the ones that look good in a demo.",
    "I try to leave a system, and the people who own it, in a better position than I found them.",
]


def _fit_cover_letter_word_count(paragraphs: list[str]) -> list[str]:
    """Stretch or trim the body toward 280-320 words using distinct filler sentences, never repeating one."""
    base = list(paragraphs)
    used = 0
    while _body_word_count(base) < 280 and used < len(_FILLER_SENTENCES):
        base[-2] = f"{base[-2]} {_FILLER_SENTENCES[used]}"
        used += 1
    while _body_word_count(base) > 320 and used > 0:
        used -= 1
        base = list(paragraphs)
        for index in range(used):
            base[-2] = f"{base[-2]} {_FILLER_SENTENCES[index]}"
    return base


def _body_word_count(paragraphs: list[str]) -> int:
    body = " ".join(paragraph for paragraph in paragraphs if not paragraph.lower().startswith("dear "))
    return len(body.split())


def _long_answer(question: str, resume_plan: ResumePlan, provider: LLMProvider | None) -> str:
    fallback = _fallback_long_answer(question, resume_plan)
    if provider is None:
        return fallback

    proof = (
        resume_plan.experience[0].bullets[0]
        if resume_plan.experience and resume_plan.experience[0].bullets
        else resume_plan.summary
    )
    prompt = (
        "Answer this application question in first person, plain text, 90 to 140 words, ready to paste. "
        "Ground the answer only in the facts given; never invent employers, tools, or numbers.\n\n"
        f"Question: {question}\n\n"
        f"Candidate's real proof point to draw from: {proof}\n"
        f"Candidate's summary: {resume_plan.summary}\n\n"
        "Rules: no em dashes, en dashes, or double hyphens. No cliche phrases (I am confident that, I would "
        "welcome the opportunity, resonates with me, aligns perfectly, as an experienced professional).\n\n"
        f"{PROHIBITED_INVENTION_CLAUSE}\n\n"
        "Do not start with 'I am writing to'. Return ONLY the answer text."
    )

    def validate(candidate: str) -> bool:
        if not (40 <= len(candidate.split()) <= 170):
            return False
        return _style_ok(candidate)

    return _llm_generate(provider, prompt, validate, fallback)


def _fallback_long_answer(question: str, resume_plan: ResumePlan) -> str:
    proof = (
        resume_plan.experience[0].bullets[0]
        if resume_plan.experience and resume_plan.experience[0].bullets
        else resume_plan.summary
    )
    answer = (
        "I would point to the pattern that runs through my recent work: translating ambiguous needs into shipped "
        f"systems. {proof} For this question, my strongest answer is that I bring practical engineering judgment, "
        "clear communication, and truthful scope control to the role."
    )
    words = answer.split()
    if len(words) > 140:
        return " ".join(words[:140]).rstrip(".") + "."
    return answer


def _style_ok(text: str) -> bool:
    return not validate_style(text)


def _llm_generate(
    provider: LLMProvider,
    prompt: str,
    validate: Callable[[str], bool],
    fallback: str,
    retries: int = 1,
) -> str:
    """Call the provider, validate the result, retry once with feedback, else fall back."""
    candidate = _clean_llm_line(generate_text(provider, prompt))
    attempt = 0
    while (not candidate or not validate(candidate)) and attempt < retries:
        candidate = _clean_llm_line(
            generate_text(
                provider,
                prompt + "\n\nYour previous answer broke one of the rules above (banned words/punctuation, an "
                "unsupported number, or wrong length). Try again and follow every rule exactly.",
            )
        )
        attempt += 1
    if candidate and validate(candidate):
        return candidate
    return fallback


def _clean_llm_line(text: str) -> str:
    cleaned = (text or "").strip()
    cleaned = re.sub(r"^```(?:text|markdown)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    cleaned = cleaned.strip("\"'")
    cleaned = cleaned.replace("—", ",").replace("–", " to ").replace("--", "-")
    # Repair cliche wording deterministically rather than burning a retry round
    # trip on a style-validation failure.
    return soften_banned_style(cleaned.strip())


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.lower()
        if key and key not in seen:
            out.append(item)
            seen.add(key)
    return out
