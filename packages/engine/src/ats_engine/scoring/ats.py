from __future__ import annotations

import re
from collections import Counter

"""Deterministic ATS keyword scoring.

Ranks a job description's most salient keywords and measures how many of them a
resume covers. Keyword ranking is frequency-based over a single document: this
is intentionally *not* backed by scikit-learn's TF-IDF, because on a single
document IDF is constant for every term, so a TF-IDF ranking reduces exactly to
a term-frequency ranking. Implementing it directly removes a heavy scientific
Python dependency (numpy/scipy/scikit-learn) from the engine with no behavioral
loss, in line with the engine's low-cost, portable posture.
"""

# A compact, self-contained English stopword list (plus recruiting boilerplate)
# so keyword extraction needs no third-party vocabulary.
_ENGLISH_STOP_WORDS = frozenset(
    """
    a about above after again against all am an and any are aren't as at be because been before being
    below between both but by can cannot could couldn't did didn't do does doesn't doing don't down during
    each few for from further had hadn't has hasn't have haven't having he her here hers herself him himself
    his how i if in into is isn't it its itself let's me more most must my myself nor not of off on once only
    or other ought our ours ourselves out over own same she should shouldn't so some such than that the their
    theirs them themselves then there these they this those through to too under until up very was wasn't we
    were weren't what when where which while who whom why with would you your yours yourself yourselves also
    across among within without upon via etc using use used
    """.split()
)

_CUSTOM_STOP_WORDS = frozenset(
    {
        "applicant",
        "candidate",
        "description",
        "job",
        "need",
        "needed",
        "needs",
        "position",
        "preferred",
        "require",
        "required",
        "requirement",
        "requirements",
        "responsibilities",
        "role",
        "team",
        "work",
    }
)

STOP_WORDS = _ENGLISH_STOP_WORDS | _CUSTOM_STOP_WORDS

# Same token shape the legacy TF-IDF vectorizer used: starts with a letter,
# followed by two or more word/tech characters (so a minimum length of three).
_TOKEN_PATTERN = re.compile(r"\b[a-zA-Z][a-zA-Z0-9+#.-]{2,}\b")


def extract_keywords(text: str, limit: int = 30) -> list[str]:
    """Extract the top ``limit`` relevant keywords from text by frequency.

    Ties are broken alphabetically for stable, deterministic output.
    """
    if not text or not text.strip():
        return []

    counts: Counter[str] = Counter()
    for match in _TOKEN_PATTERN.finditer(text.lower()):
        token = match.group(0)
        if token in STOP_WORDS or not _is_valid_keyword(token):
            continue
        counts[token] += 1

    if not counts:
        return []

    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [term for term, _count in ranked[:limit]]


def calculate_ats_score(resume_text: str, job_description: str) -> dict[str, float | int | list[str]]:
    """Calculate an ATS keyword match score for a resume against a job description."""
    keywords = extract_keywords(job_description or "")
    if not keywords:
        return {
            "score": 0.0,
            "matched_keywords": [],
            "missing_keywords": [],
            "total_keywords": 0,
            "keyword_density": 0.0,
        }

    resume = resume_text or ""
    frequencies = {keyword: _keyword_frequency(resume, keyword) for keyword in keywords}
    matched_keywords = [keyword for keyword, count in frequencies.items() if count > 0]
    missing_keywords = [keyword for keyword, count in frequencies.items() if count == 0]

    score = (len(matched_keywords) / len(keywords)) * 100
    keyword_density = (
        sum(frequencies[keyword] for keyword in matched_keywords) / len(matched_keywords) if matched_keywords else 0.0
    )

    return {
        "score": round(score, 2),
        "matched_keywords": matched_keywords,
        "missing_keywords": missing_keywords,
        "total_keywords": len(keywords),
        "keyword_density": round(keyword_density, 2),
    }


def compare_scores(
    before: dict[str, float | int | list[str]],
    after: dict[str, float | int | list[str]],
) -> dict[str, float]:
    """Compare two ATS score dictionaries."""
    before_score = _as_float(before.get("score", 0.0))
    after_score = _as_float(after.get("score", 0.0))
    improvement = after_score - before_score
    improvement_pct = (improvement / before_score) * 100 if before_score else (100.0 if after_score else 0.0)

    return {
        "before_score": round(before_score, 2),
        "after_score": round(after_score, 2),
        "improvement": round(improvement, 2),
        "improvement_pct": round(improvement_pct, 2),
    }


def keyword_in_text(text: str, keyword: str) -> bool:
    """Return True when a keyword or phrase appears in text, case-insensitively."""
    return _keyword_frequency(text, keyword) > 0


def _as_float(value: object) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def _is_valid_keyword(keyword: str) -> bool:
    tokens = keyword.split()
    if not tokens:
        return False
    return all(len(token) >= 3 and not token.isdigit() for token in tokens)


def _keyword_frequency(text: str, keyword: str) -> int:
    if not text or not keyword:
        return 0

    normalized_text = text.lower()
    normalized_keyword = keyword.lower()
    pattern = rf"(?<![\w+#.-]){re.escape(normalized_keyword)}(?![\w+#.-])"
    return len(re.findall(pattern, normalized_text))
