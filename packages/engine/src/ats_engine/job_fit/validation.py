from __future__ import annotations

import re
import unicodedata

from ats_engine.kit.contract import FitBand, RequirementAssessment, RequirementClassification
from ats_engine.models import JDProfile

_STRENGTH_WORDS = re.compile(
    r"\b(?:strength|proven|expert|expertise|mastery|highly\s+skilled|hands.on|experience|"
    r"ready.made|transferable)\b",
    re.I,
)
_GAP_WORDS = re.compile(r"\b(?:gap|missing|lacks?|not\s+demonstrated|no\s+evidence)\b", re.I)
_ADJACENT_UPGRADE = re.compile(
    r"\b(?:expert|expertise|led|owned|architected|mastery|professional\s+experience|\d+\s*years?)\b", re.I
)
_WORKING_UPGRADE = re.compile(r"\b(?:production|expert|expertise|professional\s+experience|\d+\s*years?)\b", re.I)
_NO_GAPS = re.compile(r"\b(?:no|without)\s+(?:meaningful\s+|material\s+)?gaps?\b", re.I)
_SCORE = re.compile(r"requirement\s+coverage\s*(?::|is)?\s*(\d+(?:\.\d+)?)\s*%", re.I)
_BAND = re.compile(r"fit\s+band\s*(?::|is)?\s*(low|partial|competitive|strong)\b", re.I)


def _normalized(text: str) -> str:
    value = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"[^\w+#.%]+", " ", value)


def _contexts(text: str, keyword: str) -> list[str]:
    term = _normalized(keyword).strip()
    # Split only at a terminator immediately followed by whitespace (a real
    # sentence boundary), not at every literal ".": a keyword spelled with an
    # internal period (".NET Framework") would otherwise self-fragment,
    # stripping the leading "." that the term match below requires.
    clauses = re.split(r"(?<=[.!?;])\s+", unicodedata.normalize("NFKC", text))
    return [normalized for clause in clauses if term in (normalized := _normalized(clause))]


def _scrub_terms(context: str, terms: list[str]) -> str:
    """Remove every requirement's own name from a context before scanning it
    for strength/gap/upgrade language.

    Requirements sharing one clause (a "Genuine gaps: X, Y, Z." sentence) each
    see the *whole* clause as their context — including their neighbors'
    names. A keyword named "user experience" contains the generic trigger
    word "experience", so without this, honestly naming it as a gap would
    also falsely flag every *other* gap listed in the same sentence (e.g.
    ".NET" or "C#") as "presented as a strength". Scrubbing every listed
    requirement's own name (not just the one being checked) leaves only the
    surrounding prose to be scanned for actual strength/gap claims.
    """
    scrubbed = context
    for term in terms:
        if term:
            scrubbed = scrubbed.replace(term, " ")
    return scrubbed


def validate_job_fit_narrative(
    narrative: str,
    *,
    score: float,
    band: FitBand,
    requirements: list[RequirementAssessment],
    jd_profile: JDProfile,
) -> list[str]:
    """Return explicit contradictions between prose and authoritative structure."""
    errors: list[str] = []
    normalized = _normalized(narrative)

    score_matches = [float(value) for value in _SCORE.findall(narrative)]
    if not score_matches:
        errors.append("Narrative omitted the deterministic requirement coverage score.")
    elif any(abs(value - score) > 0.001 for value in score_matches):
        errors.append("Narrative requirement coverage score contradicts the deterministic score.")

    named_bands = [FitBand(value.casefold()) for value in _BAND.findall(narrative)]
    if not named_bands or any(candidate is not band for candidate in named_bands):
        errors.append("Narrative fit band contradicts or omits the deterministic fit band.")

    gaps = [item for item in requirements if item.classification is RequirementClassification.GENUINE_GAP]
    if gaps and _NO_GAPS.search(normalized):
        errors.append("Narrative claims there are no gaps while structured gaps exist.")

    all_terms = [_normalized(other.requirement).strip() for other in requirements]
    for item in requirements:
        contexts = _contexts(narrative, item.requirement)
        if not contexts:
            if item.must_have and item.classification is RequirementClassification.GENUINE_GAP:
                errors.append(f"Narrative omitted must-have gap: {item.requirement}.")
            continue
        scrubbed = [_scrub_terms(context, all_terms) for context in contexts]
        if item.classification is RequirementClassification.GENUINE_GAP and any(
            _STRENGTH_WORDS.search(context) for context in scrubbed
        ):
            errors.append(f"Genuine gap presented as a strength: {item.requirement}.")
        elif item.classification is RequirementClassification.PROVEN and any(
            _GAP_WORDS.search(context) for context in scrubbed
        ):
            errors.append(f"Proven requirement presented as a gap: {item.requirement}.")
        elif item.classification is RequirementClassification.ADJACENT and any(
            _ADJACENT_UPGRADE.search(context) for context in scrubbed
        ):
            errors.append(f"Adjacent capability upgraded to experience/expertise: {item.requirement}.")
        elif item.classification is RequirementClassification.WORKING_KNOWLEDGE and any(
            _WORKING_UPGRADE.search(context) for context in scrubbed
        ):
            errors.append(f"Working knowledge upgraded to production experience: {item.requirement}.")

    company = _normalized(jd_profile.company).strip()
    if company and company != "target company":
        employment = re.compile(rf"\b(?:worked|employed|served|joined)\s+(?:at|for)\s+{re.escape(company)}\b")
        if employment.search(normalized):
            errors.append("Target company was presented as candidate employment history.")

    title = _normalized(jd_profile.title).strip()
    if title and title != "target role":
        prior_title = re.compile(
            rf"\b(?:worked|served)\s+as\s+(?:an?\s+|the\s+)?{re.escape(title)}\b|"
            rf"\b(?:former|previous|prior)\s+{re.escape(title)}\b"
        )
        if prior_title.search(normalized):
            errors.append("Target role was presented as a prior candidate title.")

    return list(dict.fromkeys(errors))
