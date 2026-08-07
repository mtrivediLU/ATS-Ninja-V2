from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import datetime
from typing import cast

from ats_engine.evidence.matrix import build_evidence_matrix, interview_probability
from ats_engine.evidence.resolver import resolve_requirements
from ats_engine.generation.prompts import PROHIBITED_INVENTION_CLAUSE
from ats_engine.models import (
    AnswerPlan,
    ContactInfo,
    CoverLetterPlan,
    EvidenceItem,
    EvidenceLink,
    Experience,
    JDProfile,
    PlanDecision,
    Profile,
    ResumePlan,
)
from ats_engine.parsing.resume import find_metrics, term_in_text
from ats_engine.providers.base import LLMProvider, generate_json, generate_text, run_concurrently
from ats_engine.rachana.facts import extract_credential_ids, extract_team_facts
from ats_engine.validation.fidelity import bullet_fidelity_errors, extract_named_entities
from ats_engine.validation.naturalness import (
    bullet_safety_errors,
    normalized_bullet_key,
    select_summary_closing,
)
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
    evidence_links = (
        resolve_requirements(jd_profile.requirements, profile, profile.raw_markdown) if jd_profile.requirements else []
    )
    evidence = build_evidence_matrix(jd_profile, profile, links=evidence_links)
    role_identity = choose_role_identity(jd_profile, profile)
    top_keywords = _top_keywords(evidence)
    years_span = _career_years(profile.experiences)
    working_knowledge = [item.real_evidence for item in evidence if item.evidence_tier == "C" and item.real_evidence]
    skill_groups = _build_skill_groups(evidence, profile, working_knowledge)
    deterministic_headline = _headline(
        jd_profile,
        role_identity,
        evidence,
        evidence_links if jd_profile.requirements else None,
    )

    # Headline, summary, and bullet proposals are independent provider calls.
    # Run them concurrently and validate/fallback per field so one malformed
    # response cannot discard another usable section.
    results = run_concurrently(
        {
            "headline": lambda: _build_headline(
                deterministic_headline,
                role_identity,
                jd_profile,
                evidence_links,
                provider,
            ),
            "summary": lambda: _build_summary(
                role_identity,
                top_keywords,
                jd_profile,
                profile,
                years_span,
                evidence_links,
                provider,
            ),
            "experience": lambda: _select_experience(
                profile,
                evidence,
                evidence_links,
                jd_profile,
                batch_provider,
            ),
        }
    )
    headline = cast(str, results["headline"])
    summary = cast(str, results["summary"])
    experience, bullet_decisions = cast("tuple[list[Experience], list[PlanDecision]]", results["experience"])
    residual_gap = _first_gap(evidence)
    probability = interview_probability(evidence)
    analysis = _analysis_lines(evidence, residual_gap, jd_profile)
    work_mode_line = _work_mode_line(jd_profile)

    plan_decisions = _summary_decisions(summary, jd_profile) + _skill_decisions(skill_groups) + bullet_decisions

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
        plan_decisions=plan_decisions,
        requirements=list(jd_profile.requirements),
        evidence_links=evidence_links,
        remaining_sections=[(heading, list(lines)) for heading, lines in profile.remaining_sections],
    )


def split_targeting_clause(summary: str) -> tuple[str, str]:
    """Split a generated summary into (base, targeting clause).

    The targeting clause is the deterministic "Targeting {title} opportunities."
    sentence (never a claim of a held role). Returns ``("", "")`` gracefully when
    the summary is empty and an empty clause when no targeting sentence exists.
    """
    if not summary:
        return "", ""
    match = re.search(r"\bTargeting\s+.+?\bopportunities\.", summary)
    if not match:
        return summary.strip(), ""
    clause = match.group(0).strip()
    base = (summary[: match.start()] + summary[match.end() :]).strip()
    base = re.sub(r"\s{2,}", " ", base)
    return base, clause


def _summary_decisions(summary: str, jd_profile: JDProfile) -> list[PlanDecision]:
    base, targeting = split_targeting_clause(summary)
    decisions: list[PlanDecision] = []
    if base:
        decisions.append(
            PlanDecision(
                kind="summary",
                location_id="resume::summary",
                original_text="",
                tailored_text=base,
                operation="added",
                reason="Generated a tailored professional summary grounded in the candidate's own evidence.",
            )
        )
    if targeting:
        decisions.append(
            PlanDecision(
                kind="targeting_clause",
                location_id="resume::summary::targeting",
                original_text="",
                tailored_text=targeting,
                operation="added",
                reason=f"Named the target role ({jd_profile.title}) as a targeting statement, never as held experience.",
            )
        )
    return decisions


def _skill_decisions(skill_groups: list[tuple[str, list[str]]]) -> list[PlanDecision]:
    decisions: list[PlanDecision] = []
    for group_index, (label, items) in enumerate(skill_groups):
        if not items:
            continue
        decisions.append(
            PlanDecision(
                kind="skill",
                location_id=f"resume::skills::group{group_index}",
                original_text="",
                tailored_text=f"{label}: {', '.join(items)}",
                operation="added",
                reason="Surfaced evidence-backed skills into a job-relevant group.",
                matched_keywords=list(items),
            )
        )
    return decisions


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


def _headline(
    jd_profile: JDProfile,
    role_identity: str,
    evidence: list[EvidenceItem],
    links: list[EvidenceLink] | None = None,
) -> str:
    """Build a concise, evidence-backed headline without JD context noise.

    A headline is a candidate identity, not a miniature job description.  Only
    direct-experience or certification-backed multi-word tools/methodologies
    may follow the candidate's verified role.  ``evidence`` remains in the
    signature for legacy callers; typed links carry the tier and vocabulary
    kind required for the stricter v2 policy.
    """
    del jd_profile
    if links is None:
        # Retain the historical, pre-v2 projection for legacy callers that
        # have no typed requirement links at all. V2 callers always pass a
        # list (possibly empty), so their headline remains subject to the
        # stricter source-tier and vocabulary-kind policy below.
        legacy_keywords = _dedupe(
            [
                item.real_evidence if item.evidence_tier == "adjacency" and item.real_evidence else item.keyword
                for item in evidence
                if item.evidence_tier in {"A", "B", "adjacency"} and len(item.keyword) > 2
            ]
        )[:3]
        legacy_suffix = ", ".join(legacy_keywords)
        return f"{role_identity} | {legacy_suffix}" if legacy_suffix else role_identity
    if not links:
        return role_identity

    ranked = _headline_credited_links(links)
    phrases = _dedupe(
        [link.surface_to_use or link.requirement.surface or link.requirement.canonical for link in ranked]
    )[:3]
    suffix = ", ".join(phrases)
    return f"{role_identity} | {suffix}" if suffix else role_identity


def _headline_credited_links(links: list[EvidenceLink]) -> list[EvidenceLink]:
    """Return the only resolver links allowed to appear in a headline."""
    ranked = [
        link
        for link in links
        if link.tier in {"A", "cert"}
        and link.requirement.kind in {"tool", "methodology"}
        # Multi-word terminology conveys a precise, source-backed capability;
        # bare terms like SQL or Git belong in the skills section instead.
        and link.requirement.ngram >= 2
        and bool(link.resume_span.strip())
    ]
    ranked.sort(
        key=lambda link: (
            0 if link.tier == "A" else 1,
            -link.requirement.weight,
            -link.requirement.ngram,
            link.requirement.canonical,
        )
    )
    return ranked


def _build_headline(
    fallback: str,
    role_identity: str,
    jd_profile: JDProfile,
    links: list[EvidenceLink],
    provider: LLMProvider | None,
) -> str:
    """Accept one source-mapped structured headline or return the deterministic one.

    The model may select and order already-credited phrases; it cannot coin a
    synonym, change the candidate's role identity, or introduce a term without
    a resolver evidence span. This keeps the proposal useful for wording/layout
    judgment while deterministic provenance remains authoritative.
    """
    credited = _headline_credited_links(links)
    allowed_terms = _dedupe(
        [link.surface_to_use or link.requirement.surface or link.requirement.canonical for link in credited]
    )
    if provider is None or not allowed_terms:
        return fallback

    evidence = [
        {
            "term": link.surface_to_use or link.requirement.surface or link.requirement.canonical,
            "kind": link.requirement.kind,
            "tier": link.tier,
            "source_span": link.resume_span,
            "source_location": link.resume_location,
        }
        for link in credited
    ]
    prompt = (
        "Propose one structured ATS-safe resume headline using only the exact credited terms below. "
        "The candidate role identity is immutable. Select up to three precise terms that best align "
        "with the target role; never add synonyms, soft skills, context terms, seniority, employers, "
        "metrics, or responsibilities.\n\n"
        f"Target job title: {jd_profile.title}\n"
        f"Target company: {jd_profile.company}\n"
        f"Prioritized JD requirements: {json.dumps(_dedupe([link.requirement.surface for link in credited])[:8])}\n"
        f"Exact source evidence: {json.dumps(evidence)}\n"
        f"Explicit allowed terminology: {json.dumps(allowed_terms)}\n"
        f"Protected facts that cannot be removed or modified: {json.dumps([role_identity])}\n"
        'Output constraints: one line, at most three credited terms, format "<role identity> | '
        '<term 1>, <term 2>, <term 3>", no em dash, en dash, or double hyphen.\n\n'
        f"{PROHIBITED_INVENTION_CLAUSE}\n\n"
        "Return ONLY one JSON object with exactly this shape: "
        '{"source_span":"resume:headline","action":"rewrite_headline",'
        '"terms":["exact credited term"],"text":"..."}.'
    )
    data = generate_json(provider, prompt, retries=1)
    if not isinstance(data, dict):
        return fallback
    if data.get("source_span") != "resume:headline" or data.get("action") != "rewrite_headline":
        return fallback
    raw_terms = data.get("terms")
    if not isinstance(raw_terms, list) or not 1 <= len(raw_terms) <= 3:
        return fallback
    terms = [str(term).strip() for term in raw_terms]
    allowed_by_key = {term.casefold(): term for term in allowed_terms}
    if any(not term or term.casefold() not in allowed_by_key for term in terms) or len(
        {term.casefold() for term in terms}
    ) != len(terms):
        return fallback
    selected = [allowed_by_key[term.casefold()] for term in terms]
    expected = f"{role_identity} | {', '.join(selected)}"
    candidate = _clean_llm_line(str(data.get("text", "")))
    if candidate != expected or not _style_ok(candidate) or len(candidate.split()) > 24:
        return fallback
    return candidate


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


_MONTH_NUMBERS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

_MONTH_YEAR = re.compile(
    r"\b(?:(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+)?((?:19|20)\d{2})\b",
    flags=re.IGNORECASE,
)


def _parse_month_years(dates_text: str) -> list[tuple[int, int | None]]:
    """Return every ``(year, month_or_None)`` point found in a dates string, in order."""
    points: list[tuple[int, int | None]] = []
    for match in _MONTH_YEAR.finditer(dates_text):
        month_token = match.group(1)
        month = _MONTH_NUMBERS.get(month_token[:3].lower()) if month_token else None
        points.append((int(match.group(2)), month))
    return points


def _career_years(experiences: list[Experience]) -> int | None:
    """Total career span in whole years: earliest start to latest end (or now).

    Month-aware whenever a month is present in the source dates, so a start
    month later in the calendar year than the end month is not rounded up to
    a full extra year — "Nov 2017" to "Apr 2026" is 8 years and change, not 9,
    even though the bare year difference is 9. Falls back to year-only
    subtraction when no month is available anywhere, which is the best
    approximation year-only dates support. This is a total span (candidates
    routinely describe "N years of experience" as first-role-to-now), not a
    sum of individual role durations, so concurrent/overlapping roles are
    never double-counted.
    """
    points: list[tuple[int, int | None]] = []
    is_current = False
    for experience in experiences:
        points.extend(_parse_month_years(experience.dates))
        if re.search(r"present|current", experience.dates, flags=re.IGNORECASE):
            is_current = True
    if not points:
        return None

    start_year, start_month = min(points, key=lambda point: (point[0], point[1] if point[1] is not None else 1))
    end_year: int
    end_month: int | None
    if is_current:
        now = datetime.now()
        end_year, end_month = now.year, now.month
    else:
        end_year, end_month = max(points, key=lambda point: (point[0], point[1] if point[1] is not None else 12))

    if start_month is not None and end_month is not None:
        span = ((end_year * 12 + end_month) - (start_year * 12 + start_month)) // 12
    else:
        span = end_year - start_year
    return span if span > 0 else None


def _experience_highlights(profile: Profile, limit: int = 6) -> str:
    lines: list[str] = []
    for experience in profile.experiences:
        for bullet in experience.bullets[:2]:
            lines.append(f"- ({experience.company}, {experience.title}) {bullet}")
            if len(lines) >= limit:
                return "\n".join(lines)
    return "\n".join(lines) or "No detailed bullets were found in the resume."


def _target_title_instruction(target_title: str) -> str:
    if not _is_real_target_title(target_title):
        return "No target job title was reliably identified; do not name one."
    return (
        f'You may include a brief, clearly-framed "targeting" clause naming the exact target title '
        f'"{target_title}" (for example, "Targeting {target_title} opportunities"). '
        "Never phrase it as a title the candidate has held or currently holds."
    )


def _build_summary(
    role_identity: str,
    top_keywords: list[str],
    jd_profile: JDProfile,
    profile: Profile,
    years_span: int | None,
    links: list[EvidenceLink],
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
    allowed_terminology = _dedupe(
        [
            link.surface_to_use or link.requirement.surface or link.requirement.canonical
            for link in links
            if link.tier in {"A", "B", "cert"}
        ]
    )
    prioritized_requirements = _dedupe(
        [
            link.requirement.surface or link.requirement.canonical
            for link in sorted(
                links,
                key=lambda item: (-item.requirement.weight, item.requirement.canonical),
            )
        ]
    )[:8]
    protected_facts = _protected_facts(profile.source_summary)
    prompt = (
        "Propose one structured professional-summary rewrite. Ground every claim only in the exact source "
        "evidence below; never invent employers, tools, responsibilities, or numbers.\n\n"
        f"Role identity to use: {role_identity}\n"
        f"Target job title: {jd_profile.title}\n"
        f"Target company: {jd_profile.company}\n"
        f"Domain: {jd_profile.domain or 'not specified'}\n"
        f"Prioritized JD requirements: {json.dumps(prioritized_requirements)}\n"
        f"Explicit allowed terminology: {json.dumps(allowed_terminology or top_keywords)}\n"
        f"{years_line}\n\n"
        f"Source span: resume:summary\n"
        f"Exact source summary evidence: {json.dumps(profile.source_summary)}\n"
        f"Exact supporting experience evidence:\n{_experience_highlights(profile)}\n"
        f"Protected facts that cannot be removed or modified: {json.dumps(protected_facts)}\n\n"
        "Rules: no em dashes, en dashes, or double hyphens. Do not state any number, percentage, or metric "
        "that is not already given above. Avoid cliche resume filler (results-driven, detail-oriented, "
        "passionate about, proven track record, dynamic, innovative, seamless, robust, leveraged, spearheaded, "
        "architected, orchestrated, streamlined). Avoid vague content-free filler like 'core tools' or "
        "'day-to-day delivery' with nothing specific behind it.\n\n"
        f"{_target_title_instruction(jd_profile.title)}\n\n"
        f"{PROHIBITED_INVENTION_CLAUSE}\n\n"
        "Return ONLY one JSON object with exactly this shape: "
        '{"source_span":"resume:summary","action":"rewrite_summary","text":"..."}.'
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
        if _mentions_tier_c(candidate, profile):
            return False
        return not (
            profile.source_summary
            and bullet_fidelity_errors(
                profile.source_summary,
                candidate,
                source_text=profile.raw_markdown,
            )
        )

    data = generate_json(provider, prompt, retries=1)
    if not isinstance(data, dict):
        return fallback
    if data.get("source_span") != "resume:summary" or data.get("action") != "rewrite_summary":
        return fallback
    candidate = _clean_llm_line(str(data.get("text", "")))
    return candidate if validate(candidate) else fallback


def _fallback_summary(
    role_identity: str,
    top_keywords: list[str],
    jd_profile: JDProfile,
    years_span: int | None,
) -> str:
    years_clause = f" with {years_span}+ years of experience" if years_span else ""
    # Only claim a skills clause when there is real evidence to name; "core
    # tools and day-to-day delivery" as a placeholder for zero matched
    # keywords reads as content-free filler, which the summary must avoid.
    if top_keywords:
        skills = ", ".join(top_keywords[:2])
        skills_clause = f", with hands-on work in {skills}"
    else:
        skills_clause = ""
    domain_clause = f" Experience spans {jd_profile.domain} work." if jd_profile.domain else ""
    # A target title is never claimed as held experience — it is framed only
    # as what the candidate is targeting, in its own clearly separate clause.
    target_clause = f" Targeting {jd_profile.title} opportunities." if _is_real_target_title(jd_profile.title) else ""
    # Deterministic bounded variation of the closing sentence (>= 6-entry pool),
    # keyed by a stable candidate/JD seed, so different candidates do not all get
    # the identical filler while the same input is always reproducible.
    closing = select_summary_closing(f"{role_identity}|{jd_profile.title}|{jd_profile.company}|{skills_clause}")
    return f"{role_identity}{years_clause}{skills_clause}.{domain_clause}{target_clause} {closing}"


def rewrite_summary(
    role_identity: str,
    profile: Profile,
    jd_profile: JDProfile,
    links: list[EvidenceLink] | None = None,
    *,
    years_span: int | None = None,
) -> str:
    """Create a deterministic, source-preserving summary rewrite candidate.

    This is intentionally a planning primitive rather than an automatic
    pipeline mutation.  An optimizer or delivery workflow can propose the
    returned text as a reviewable ``summary`` action, then apply its usual
    scoring and calibrated validation gates.  The helper itself never invents
    a candidate fact: it preserves the complete source summary when present,
    adds only tier-A evidence phrases, and names certification codes only from
    resolver-backed certificate spans.
    """
    source_summary = _summary_sentence(profile.source_summary)
    lead = source_summary or _summary_lead(role_identity, years_span)
    phrases = _summary_evidence_phrases(links or [])
    cert_callouts = _summary_certificate_callouts(links or [])
    parts = [lead]
    if phrases:
        parts.append(f"Relevant work includes {_summary_join(phrases)}.")
    if cert_callouts:
        parts.append(f"{_summary_join(cert_callouts)}.")
    if _is_real_target_title(jd_profile.title):
        parts.append(f"Targeting {jd_profile.title} opportunities.")
    return _summary_clean(" ".join(part for part in parts if part))


def _summary_lead(role_identity: str, years_span: int | None) -> str:
    if years_span is not None and years_span > 0:
        return f"{role_identity} with {years_span}+ years of experience."
    return f"{role_identity}."


def _summary_sentence(text: str) -> str:
    """Retain source wording while making it safe to append deterministic prose."""
    source = (text or "").strip()
    if not source:
        return ""
    if source[-1:] not in {".", "!", "?"}:
        source = f"{source}."
    return source


def _summary_evidence_phrases(links: list[EvidenceLink]) -> list[str]:
    """Select up to three direct, non-soft phrases from distinct categories."""
    ranked = sorted(
        (link for link in links if link.tier == "A" and link.requirement.kind != "soft"),
        key=lambda link: (-link.requirement.weight, -link.requirement.ngram, link.requirement.canonical),
    )
    phrases: list[str] = []
    categories: set[str] = set()
    for link in ranked:
        category = link.requirement.category or "other"
        if category in categories:
            continue
        phrase = (link.surface_to_use or link.requirement.surface or link.requirement.canonical).strip()
        if not phrase:
            continue
        categories.add(category)
        phrases.append(phrase)
        if len(phrases) == 3:
            break
    return _dedupe(phrases)


def _summary_certificate_callouts(links: list[EvidenceLink]) -> list[str]:
    """Render stable, certificate-backed callouts without claiming production use."""
    callouts: list[str] = []
    seen_codes: set[str] = set()
    for link in sorted(
        (item for item in links if item.tier == "cert" and item.resume_span.strip()),
        key=lambda item: (item.requirement.canonical, item.resume_span.casefold()),
    ):
        code = _certificate_code(link.resume_span)
        if not code or code in seen_codes:
            continue
        seen_codes.add(code)
        prefix = "Microsoft " if "microsoft" in link.resume_span.casefold() else ""
        callouts.append(f"{prefix}{code} certified")
    return callouts[:2]


def _certificate_code(span: str) -> str:
    match = re.search(r"\b(?:PL|AZ)-\d{3}\b", span or "", flags=re.IGNORECASE)
    return match.group(0).upper() if match is not None else ""


def _summary_clean(text: str) -> str:
    """Avoid machine-style dash punctuation without deleting source facts."""
    cleaned = (text or "").replace("—", ",").replace("–", "-").replace("--", "-")
    return re.sub(r"\s+", " ", cleaned).strip()


def _summary_join(values: list[str]) -> str:
    if len(values) < 2:
        return values[0] if values else ""
    if len(values) == 2:
        return f"{values[0]} and {values[1]}"
    return f"{', '.join(values[:-1])}, and {values[-1]}"


def _is_real_target_title(title: str) -> bool:
    return bool(title) and title.strip().lower() != "target role"


# Fixed display priority for the Phase-3 requirement categories (see
# evidence.matrix.classify_requirement_category): role-defining categories
# first (platform/web/integration/cloud/database), general engineering
# categories next, "soft" categories last. A category with no evidence-backed
# skill for this candidate simply never produces a group — this is not a
# hardcoded "Power Platform resume" layout, it is the same ordering rule
# applied to whatever categories this JD and candidate actually produced.
_CATEGORY_ORDER = [
    "bi_analytics",
    "data_engineering",
    "geospatial",
    "security_governance",
    "platform",
    "web development",
    "web_development",
    "integration",
    "cloud",
    "database",
    "framework",
    "programming language",
    "source control",
    "business analysis",
    "operations and support",
    "documentation",
    "communication",
    "productivity",
    "domain",
    "testing_quality",
    "operations_support",
    "business_analysis",
    "source_control",
]
_CATEGORY_LABELS = {
    "bi_analytics": "Business Intelligence & Analytics",
    "data_engineering": "Data Engineering",
    "geospatial": "Geospatial & Mapping",
    "security_governance": "Security & Data Governance",
    "platform": "Platform & Automation",
    "web development": "Web Development",
    "web_development": "Web Development",
    "integration": "APIs & Integrations",
    "cloud": "Cloud & DevOps",
    "database": "Databases & Data",
    "framework": "Frameworks",
    "programming language": "Programming Languages",
    "source control": "Source Control",
    "business analysis": "Business Analysis",
    "operations and support": "Operations & Support",
    "documentation": "Documentation",
    "communication": "Communication",
    "productivity": "Productivity & Collaboration",
    "domain": "Domain Knowledge",
    "testing_quality": "Testing & Quality",
    "operations_support": "Operations & Support",
    "business_analysis": "Business Analysis",
    "source_control": "Source Control",
}


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

    # Evidence order already puts required-tier matches before preferred-tier
    # matches (build_evidence_matrix appends required keywords first), so
    # bucketing by category while preserving that order keeps mandatory
    # supported requirements ahead of preferred ones within each group too.
    category_by_skill = {
        (item.real_evidence or item.keyword).lower(): item.category
        for item in evidence
        if item.evidence_tier in {"A", "B", "adjacency"}
    }
    buckets: dict[str, list[str]] = {}
    uncategorized: list[str] = []
    for skill in core:
        category = category_by_skill.get(skill.lower(), "other")
        if category in _CATEGORY_LABELS:
            buckets.setdefault(category, []).append(skill)
        else:
            uncategorized.append(skill)

    groups: list[tuple[str, list[str]]] = []
    for category in _CATEGORY_ORDER:
        if buckets.get(category):
            groups.append((_CATEGORY_LABELS[category], buckets[category]))

    trailing_additional = uncategorized + additional
    if trailing_additional:
        groups.append(("Additional Skills", trailing_additional))
    if working:
        groups.append(("Working Knowledge", working))
    return groups


def _select_experience(
    profile: Profile,
    evidence: list[EvidenceItem],
    links: list[EvidenceLink],
    jd_profile: JDProfile,
    provider: LLMProvider | None,
) -> tuple[list[Experience], list[PlanDecision]]:
    keywords = [item.keyword.lower() for item in evidence if item.evidence_tier != "missing"]
    entries: list[tuple[Experience, list[str], list[str]]] = []

    for experience in profile.experiences:
        # Preserve the candidate's own bullets and their source order. Two earlier
        # behaviors are deliberately removed here:
        #   * Sorting bullets by keyword relevance silently reordered candidate-
        #     facing content without any ledger record. Presence-based ATS scoring
        #     is unaffected by order, so the safe, honest default is source order.
        #   * `dedupe_bullets` dropped exact-duplicate *candidate* bullets before
        #     the ledger existed, which then failed completeness (source bullet
        #     count > rendered count) and withheld the whole resume. Candidate-
        #     authored duplicates are the candidate's own content; keeping them
        #     loses no fact and keeps completeness intact. Generated duplicate
        #     prose is handled separately, after rewriting, without ever reducing
        #     the source bullet count (see `_reject_generated_duplicates`).
        source_bullets = list(experience.bullets)
        # Candidate-authored bullets are evidence, not generated prose.  Their
        # wording must survive exactly unless an explicit, ledgered rewrite is
        # accepted after fact-retention validation.
        chosen: list[str] = list(source_bullets)
        # Keep the entry even with zero bullets (company/title/dates only):
        # dropping it here would silently discard a verified source-profile entry
        # that `validate_completeness` still counts. `source_bullets` are the raw
        # candidate bullets (style softening happens in `chosen`); the raw form is
        # what the change ledger records as `original_text` so a rejected bullet
        # restores the candidate's own wording, not a softened variant.
        entries.append((experience, chosen, source_bullets))

    all_originals = [bullet for _, chosen, _ in entries for bullet in chosen]
    source_spans = [
        f"resume::exp{exp_index}::bullet{bullet_index}"
        for exp_index, (_experience, chosen, _raw_bullets) in enumerate(entries)
        for bullet_index, _bullet in enumerate(chosen)
    ]
    # Bullets already carrying two or more JD keywords are targeted as-is;
    # rewriting them spends tokens for little gain and risks quality drift.
    # Only the under-aligned bullets go to the model.
    needs_rewrite = [index for index, bullet in enumerate(all_originals) if _keyword_hits(bullet, keywords) < 2]
    rewritten_flat = list(all_originals)
    if provider is not None and needs_rewrite:
        batch = [all_originals[index] for index in needs_rewrite]
        rewritten_batch = _rewrite_bullets_batch(
            batch,
            jd_profile,
            keywords,
            profile,
            provider,
            source_spans=[source_spans[index] for index in needs_rewrite],
            links=links,
        )
        for position, index in enumerate(needs_rewrite):
            rewritten_flat[index] = rewritten_batch[position]
    # Repair *generated* duplication without ever dropping a candidate bullet: if a
    # rewrite collapses two distinct source bullets into identical prose, restore
    # the later one's original wording. Genuine candidate-source duplicates are
    # untouched (they are the candidate's own content and preserve completeness).
    rewritten_flat = _reject_generated_duplicates(all_originals, rewritten_flat)

    selected: list[Experience] = []
    decisions: list[PlanDecision] = []
    cursor = 0
    for exp_index, (experience, chosen, raw_bullets) in enumerate(entries):
        count = len(chosen)
        final_bullets = rewritten_flat[cursor : cursor + count]
        cursor += count
        for bullet_index, (raw_bullet, final_bullet) in enumerate(zip(raw_bullets, final_bullets, strict=False)):
            # Record against the RAW candidate bullet (before style softening) so
            # a rejected bullet restores the candidate's own wording exactly.
            if raw_bullet.strip() == final_bullet.strip():
                continue
            decisions.append(
                PlanDecision(
                    kind="bullet",
                    location_id=f"resume::exp{exp_index}::bullet{bullet_index}",
                    original_text=raw_bullet,
                    tailored_text=final_bullet,
                    operation="rewritten",
                    reason=(
                        "Rewrote the bullet to surface job-relevant keywords while keeping the "
                        "original facts, scope, and seniority."
                    ),
                    matched_keywords=[keyword for keyword in keywords if _keyword_hits(final_bullet, [keyword])],
                )
            )
        selected.append(
            Experience(
                company=experience.company,
                title=experience.title,
                location=experience.location,
                dates=experience.dates,
                bullets=final_bullets,
            )
        )
    return selected, decisions


def _reject_generated_duplicates(originals: list[str], rewritten: list[str]) -> list[str]:
    """Revert any rewrite that introduces a NEW duplicate not present in the source.

    A model rewrite can collapse two genuinely distinct bullets into identical
    prose, a subtle stuffing artifact. When a rewritten bullet's normalized text
    collides with an earlier kept bullet but its own original did *not* collide
    with that bullet's original, the duplication was introduced by generation, so
    the later bullet is restored to its candidate original. Duplicates that already
    exist between the *source* bullets are preserved untouched — they are the
    candidate's own content and dropping them would break completeness.
    """
    source_keys = [normalized_bullet_key(text) for text in originals]
    result = list(rewritten)
    seen: dict[str, int] = {}
    for index, text in enumerate(result):
        key = normalized_bullet_key(text)
        if not key:
            continue
        prior = seen.get(key)
        if prior is not None and source_keys[index] != source_keys[prior]:
            # Generated collision between two distinct source bullets: undo it.
            result[index] = originals[index]
            key = source_keys[index]
        seen.setdefault(key, index)
    return result


def _rewrite_bullets_batch(
    bullets: list[str],
    jd_profile: JDProfile,
    keywords: list[str],
    profile: Profile,
    provider: LLMProvider,
    *,
    source_spans: list[str] | None = None,
    links: list[EvidenceLink] | None = None,
) -> list[str]:
    """Rewrite every selected bullet in a single provider call instead of one per bullet.

    This is the single biggest latency lever in the pipeline: a resume with 20
    selected bullets used to mean 20+ sequential round trips. Batching cuts that
    to one call, with the same per-bullet groundedness checks applied to each
    item in the response, falling back to that item's untouched original on any
    failure.
    """
    spans = source_spans or [f"resume::bullet{index}" for index in range(len(bullets))]
    if len(spans) != len(bullets):
        return bullets
    prioritized_requirements = _dedupe(
        [
            link.requirement.surface or link.requirement.canonical
            for link in sorted(
                links or [],
                key=lambda item: (-item.requirement.weight, item.requirement.canonical),
            )
        ]
    )[:8]
    items = [
        {
            "source_span": source_span,
            "action": "rewrite_bullet",
            "source_evidence": bullet,
            "allowed_terminology": [keyword for keyword in keywords if _keyword_hits(bullet, [keyword])],
            "protected_facts": _protected_facts(bullet),
            "constraints": {"max_words": 34, "single_line": True},
        }
        for source_span, bullet in zip(spans, bullets, strict=True)
    ]
    prompt = (
        "Propose a structured rewrite for each resume bullet so it foregrounds the target job's priorities, "
        "while staying 100% factually identical to its own original: same system, same tools, same scope, "
        "same numbers. Do not invent or drop any metric, tool, or outcome for any bullet, and do not name "
        "a tool that is not already in that bullet's original text. Keep each rewrite to one line, under "
        "34 words. Vary sentence openings across the set so consecutive bullets do not start the same way.\n\n"
        f"Target job title: {jd_profile.title}\n"
        f"Target company: {jd_profile.company}\n"
        f"Prioritized JD requirements: {json.dumps(prioritized_requirements)}\n"
        f"Structured source inputs: {json.dumps(items)}\n\n"
        "Rules: no em dashes, en dashes, or double hyphens. Avoid cliche resume verbs (leveraged, "
        "spearheaded, architected, orchestrated, streamlined, championed, synergized, facilitated).\n\n"
        f"{PROHIBITED_INVENTION_CLAUSE}\n\n"
        f"Return ONLY a JSON array of exactly {len(bullets)} objects. Each object must contain the unchanged "
        'source_span, action="rewrite_bullet", and text. Do not return commentary or markdown fences.'
    )

    data = generate_json(provider, prompt, retries=1)
    if not isinstance(data, list):
        return bullets

    known_skills = list(profile.tier_a) + list(profile.tier_b) + list(profile.tier_c)
    proposals = {
        str(item.get("source_span")): item
        for item in data
        if isinstance(item, dict)
        and item.get("action") == "rewrite_bullet"
        and isinstance(item.get("source_span"), str)
    }
    rewritten: list[str] = []
    for source_span, original in zip(spans, bullets, strict=True):
        candidate = proposals.get(source_span)
        candidate_text = _clean_llm_line(str(candidate.get("text", ""))) if candidate is not None else ""
        rewritten.append(candidate_text if _bullet_is_valid(candidate_text, original, known_skills) else original)
    return rewritten


def _protected_facts(text: str) -> list[str]:
    """Return exact high-risk facts an AI proposal must retain.

    The team-size and credential-id patterns moved to ``rachana.facts`` so
    "what counts as a checkable fact" has one definition shared with the
    pruning gate, which must refuse to remove the same things a rewrite must
    refuse to drop. Behavior here is unchanged.
    """
    return _dedupe(
        [
            *find_metrics(text),
            *extract_named_entities(text),
            *sorted(extract_team_facts(text)),
            *sorted(extract_credential_ids(text)),
        ]
    )


def _bullet_is_valid(
    candidate: str,
    original: str,
    known_skills: list[str],
    allowed_new_skills: list[str] | None = None,
) -> bool:
    if not candidate or len(candidate.split()) > 45:
        return False
    if not _style_ok(candidate):
        return False
    allowed = {metric.lower() for metric in find_metrics(original)}
    found = {metric.lower() for metric in find_metrics(candidate)}
    if not found.issubset(allowed):
        return False
    # Fact retention is deliberately bidirectional.  The older one-way check
    # blocked invented metrics but still allowed a rewrite to discard "team of
    # four engineers" or "100% uptime".  Reuse the shared fidelity gate so
    # named entities, team facts, and explicitly delimited outcome clauses use
    # the same semantics here as the final rendered-resume validation.
    if not allowed.issubset(found):
        return False
    if bullet_fidelity_errors(original, candidate):
        return False
    if _introduces_new_skill(candidate, original, known_skills, allowed_new_skills):
        return False
    # Deterministic naturalness/anti-stuffing gate: rejects first-person, ownership
    # or seniority escalation, awkward length, and new tools/metrics not in the
    # original bullet. On any failure the caller keeps the candidate-original
    # bullet, so this can only preserve truthful wording, never fabricate.
    return not bullet_safety_errors(candidate, original, known_skills)


def _introduces_new_skill(
    rewritten: str,
    original: str,
    known_skills: list[str],
    allowed_new_skills: list[str] | None = None,
) -> bool:
    """True when a rewrite names an unsupported skill absent from its source.

    V2 placement actions may introduce a term into another bullet only when a
    resolver link provides tier-A provenance and the planner passed it in
    ``allowed_new_skills``.  The default remains conservative for all legacy
    callers.
    """
    original_lower = original.lower()
    rewritten_lower = rewritten.lower()
    allowed = {skill.casefold().strip() for skill in allowed_new_skills or []}
    for skill in known_skills:
        if (
            term_in_text(skill, rewritten_lower)
            and not term_in_text(skill, original_lower)
            and skill.casefold().strip() not in allowed
        ):
            return True
    return False


def _mentions_tier_c(text: str, profile: Profile) -> bool:
    """Tier C ('working knowledge only') skills must never be claimed as summary/letter substance."""
    lowered = text.lower()
    return any(term_in_text(skill, lowered) for skill in profile.tier_c)


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
