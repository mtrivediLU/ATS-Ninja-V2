from __future__ import annotations

import hashlib
import math
import re

from ats_engine.parsing.resume import find_metrics, term_in_text
from ats_engine.scoring.ats import keyword_in_text

"""Deterministic naturalness and anti-stuffing checks (ApplicationKit v5).

Truth grounding removes *fabricated* claims; this module protects against the
*other* way a tailored document degrades — mechanical keyword stuffing, verbatim
job-description echo, template monotony, and bullet rewrites that quietly escalate
ownership or invent scope. Every check is deterministic and content-agnostic
(it never rewards or penalizes a candidate's identity), and repair is a single
bounded pass that only ever removes the lowest-value duplicate placement, never
edits truthful evidence into something new.

Naturalness findings are surfaced as warnings. They become fatal only when they
also trip an existing truth-critical rule (a fabricated metric/tool/employer),
which is enforced by the grounding gate, not here.
"""

_WORD_RE = re.compile(r"[a-z0-9][a-z0-9+#.\-/]*")
_FIRST_PERSON_RE = re.compile(r"\b(i|we|my|our|me|us|i'm|i've|we've)\b", re.IGNORECASE)

# Ownership / seniority verbs. A rewrite may use one only if the *original*
# bullet already did — tailoring must never upgrade "contributed to" into "led".
_OWNERSHIP_VERBS = frozenset(
    {
        "led",
        "managed",
        "owned",
        "directed",
        "oversaw",
        "headed",
        "spearheaded",
        "founded",
        "established",
        "orchestrated",
        "commanded",
        "supervised",
        "governed",
    }
)

MAX_BULLET_WORDS = 30
MIN_LENGTH_RATIO = 0.5
MAX_LENGTH_RATIO = 1.6

# A deterministic pool of natural closing sentences for the fallback summary.
# At least six so different candidates do not all receive identical filler; the
# same input always resolves to the same closing (see :func:`select_summary_closing`).
SUMMARY_CLOSINGS: tuple[str, ...] = (
    "The focus is on the requirements this role actually names.",
    "Every point above is drawn directly from the candidate's own resume.",
    "The emphasis stays on demonstrated, resume-backed experience.",
    "Priority goes to the skills this posting calls out most clearly.",
    "The summary keeps to what the candidate's history genuinely supports.",
    "It centers on the capabilities the role treats as essential.",
    "The framing follows the posting's stated priorities without overreaching.",
)


def _normalize_words(text: str) -> list[str]:
    return _WORD_RE.findall((text or "").lower())


def _stable_index(seed: str, count: int) -> int:
    if count <= 0:
        return 0
    return int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16) % count


def select_summary_closing(seed: str) -> str:
    """Deterministically pick a natural closing sentence from the pool."""
    return SUMMARY_CLOSINGS[_stable_index(seed, len(SUMMARY_CLOSINGS))]


# --------------------------------------------------------------------------- #
# 1. Keyword repetition / stuffing
# --------------------------------------------------------------------------- #
def _overall_repeat_limit(word_count: int) -> int:
    """Allowed total occurrences of any one keyword across the whole document."""
    return max(2, math.ceil(word_count / 150))


def detect_keyword_stuffing(text: str, bullets: list[str], keywords: list[str]) -> list[str]:
    """Flag mechanical over-repetition of unified keywords.

    Detects a keyword used more than ``max(2, ceil(word_count / 150))`` times
    overall, twice in one bullet, or in more than half of all bullets, plus
    obvious near-duplicate bullets.
    """
    warnings: list[str] = []
    # Near-duplicate bullets are a stuffing signal independent of the unified
    # keyword set, so this check runs even when no keywords are supplied.
    warnings.extend(_near_duplicate_bullet_warnings(bullets))
    if not keywords:
        return warnings

    word_count = len(_normalize_words(text))
    limit = _overall_repeat_limit(word_count)
    bullet_count = len(bullets)

    for keyword in keywords:
        total = _count_occurrences(text, keyword)
        if total > limit:
            warnings.append(f"keyword '{keyword}' appears {total} times overall (limit {limit})")
        per_bullet_hits = 0
        for bullet in bullets:
            occurrences = _count_occurrences(bullet, keyword)
            if occurrences >= 2:
                warnings.append(f"keyword '{keyword}' appears {occurrences} times in a single bullet")
            if occurrences >= 1:
                per_bullet_hits += 1
        if bullet_count >= 2 and per_bullet_hits * 2 > bullet_count:
            warnings.append(f"keyword '{keyword}' appears in {per_bullet_hits} of {bullet_count} bullets")

    return warnings


def _count_occurrences(text: str, keyword: str) -> int:
    if not text or not keyword:
        return 0
    pattern = rf"(?<![\w+#.\-/]){re.escape(keyword.lower())}(?![\w+#.\-/])"
    return len(re.findall(pattern, text.lower()))


def _near_duplicate_bullet_warnings(bullets: list[str]) -> list[str]:
    warnings: list[str] = []
    normalized = [" ".join(_normalize_words(bullet)) for bullet in bullets]
    seen: dict[str, int] = {}
    for index, norm in enumerate(normalized):
        if not norm:
            continue
        if norm in seen:
            warnings.append(f"bullet {index} duplicates bullet {seen[norm]}")
        else:
            seen[norm] = index
    return warnings


def dedupe_bullets(bullets: list[str]) -> list[str]:
    """One bounded, conservative repair: drop exact near-duplicate bullets.

    Only removes a later bullet whose normalized text exactly repeats an earlier
    one (the lowest-value repeated placement), preserving the first, strongest
    occurrence. Never edits the words inside a truthful bullet.
    """
    kept: list[str] = []
    seen: set[str] = set()
    for bullet in bullets:
        norm = " ".join(_normalize_words(bullet))
        if norm and norm in seen:
            continue
        seen.add(norm)
        kept.append(bullet)
    return kept


# --------------------------------------------------------------------------- #
# 2. Job-description echo
# --------------------------------------------------------------------------- #
def detect_jd_echo(text: str, job_description: str, keyword_phrases: list[str], window: int = 8) -> list[str]:
    """Flag verbatim sequences of ``window`` or more words copied from the JD.

    Uses a deterministic sliding window over normalized words. A window that is
    entirely contained within a legitimate keyword phrase is excluded (keyword
    phrases are short, so an eight-word window is essentially always an echo).
    """
    text_words = _normalize_words(text)
    jd_words = _normalize_words(job_description)
    if len(text_words) < window or len(jd_words) < window:
        return []

    jd_grams = {" ".join(jd_words[i : i + window]) for i in range(len(jd_words) - window + 1)}
    phrase_set = {" ".join(_normalize_words(phrase)) for phrase in keyword_phrases}

    warnings: list[str] = []
    flagged: set[str] = set()
    for i in range(len(text_words) - window + 1):
        gram = " ".join(text_words[i : i + window])
        if gram in jd_grams and gram not in flagged and not _within_phrase(gram, phrase_set):
            flagged.add(gram)
            warnings.append(f"verbatim job-description echo: '{gram}'")
    return warnings


def _within_phrase(gram: str, phrase_set: set[str]) -> bool:
    return any(gram in phrase or phrase in gram for phrase in phrase_set if phrase)


def jd_appended_to_resume(resume_text: str, job_description: str, window: int = 20) -> bool:
    """True when a long contiguous run of the JD appears verbatim in the resume.

    Catches the crude score-manipulation attempt of pasting the whole job
    description into the resume; such text must never earn evidence credit.
    """
    return bool(detect_jd_echo(resume_text, job_description, keyword_phrases=[], window=window))


# --------------------------------------------------------------------------- #
# 3. Bullet safety
# --------------------------------------------------------------------------- #
def bullet_safety_errors(candidate: str, original: str, known_skills: list[str]) -> list[str]:
    """Deterministic safety checks on a rewritten bullet versus its original.

    On any failure the caller keeps the original bullet rather than blocking the
    whole kit. Checks: length, verb-first accomplishment shape, no first person,
    no ownership/seniority escalation, length ratio, no new metric, no new tool.
    """
    errors: list[str] = []
    candidate_words = candidate.split()
    original_words = original.split()
    if not candidate_words:
        return ["empty rewrite"]

    if len(candidate_words) > MAX_BULLET_WORDS:
        errors.append(f"rewrite exceeds {MAX_BULLET_WORDS} words")

    if _FIRST_PERSON_RE.search(candidate):
        errors.append("rewrite uses first person")

    if original_words:
        ratio = len(candidate_words) / len(original_words)
        if ratio < MIN_LENGTH_RATIO or ratio > MAX_LENGTH_RATIO:
            errors.append(f"rewrite length ratio {ratio:.2f} outside [{MIN_LENGTH_RATIO}, {MAX_LENGTH_RATIO}]")

    escalated = _escalated_ownership(candidate, original)
    if escalated:
        errors.append(f"rewrite escalates ownership with '{escalated}' not in the original bullet")

    new_metric = _introduces_new_metric(candidate, original)
    if new_metric:
        errors.append(f"rewrite introduces a metric not in the original: '{new_metric}'")

    new_skill = _introduces_new_skill(candidate, original, known_skills)
    if new_skill:
        errors.append(f"rewrite introduces a tool not in the original: '{new_skill}'")

    return errors


def _escalated_ownership(candidate: str, original: str) -> str:
    candidate_lower = candidate.lower()
    original_lower = original.lower()
    for verb in _OWNERSHIP_VERBS:
        if term_in_text(verb, candidate_lower) and not term_in_text(verb, original_lower):
            return verb
    return ""


def _introduces_new_metric(candidate: str, original: str) -> str:
    allowed = {metric.lower() for metric in find_metrics(original)}
    for metric in find_metrics(candidate):
        if metric.lower() not in allowed:
            return metric
    return ""


def _introduces_new_skill(candidate: str, original: str, known_skills: list[str]) -> str:
    candidate_lower = candidate.lower()
    original_lower = original.lower()
    for skill in known_skills:
        if term_in_text(skill, candidate_lower) and not term_in_text(skill, original_lower):
            return skill
    return ""


def safe_bullet(candidate: str, original: str, known_skills: list[str]) -> str:
    """Return the rewrite if it is safe, otherwise fall back to the original bullet."""
    return candidate if not bullet_safety_errors(candidate, original, known_skills) else original


# --------------------------------------------------------------------------- #
# 4. Top-level prose naturalness (non-fatal warnings)
# --------------------------------------------------------------------------- #
def validate_naturalness(text: str, keywords: list[str]) -> list[str]:
    """Naturalness warnings for a single piece of generated prose.

    Not truth-critical on its own; a caller escalates only when an existing
    truth rule also fires.
    """
    warnings: list[str] = []
    if not text.strip():
        return warnings
    word_count = len(_normalize_words(text))
    limit = _overall_repeat_limit(word_count)
    for keyword in keywords:
        occurrences = _count_occurrences(text, keyword)
        if occurrences > limit:
            warnings.append(f"keyword '{keyword}' repeated {occurrences} times in generated prose (limit {limit})")
    return warnings


def keyword_present(text: str, keyword: str) -> bool:
    """Presence-only membership test (re-exported for callers that score by presence)."""
    return keyword_in_text(text, keyword)


__all__ = [
    "MAX_BULLET_WORDS",
    "SUMMARY_CLOSINGS",
    "bullet_safety_errors",
    "dedupe_bullets",
    "detect_jd_echo",
    "detect_keyword_stuffing",
    "jd_appended_to_resume",
    "keyword_present",
    "safe_bullet",
    "select_summary_closing",
    "validate_naturalness",
]
