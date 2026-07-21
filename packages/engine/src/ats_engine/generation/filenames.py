from __future__ import annotations

import re
import unicodedata

"""Standardized, filesystem-safe filenames for downloaded documents.

Single source of truth for the ``ApplicantName_JobTitle_CompanyName_<Artifact>[_<Template>].pdf``
convention. Deliberately conservative: it only ever reshapes text the caller
already trusts (candidate name, target title, target company — never resume
body content), and it never guesses a missing value. A blank/unknown component
is omitted rather than invented; only the candidate-name slot falls back to the
literal placeholder word ``"Applicant"`` so a filename is always produced.
"""

_MAX_COMPONENT_LENGTH = 60
_MAX_BASE_LENGTH = 150
_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9\s-]")
_WHITESPACE_RUN = re.compile(r"[\s_-]+")


def sanitize_filename_component(value: str, *, max_length: int = _MAX_COMPONENT_LENGTH) -> str:
    """Reduce one piece of untrusted text to a safe, underscore-joined token.

    Unicode is folded to its closest ASCII form (accents dropped, letters
    kept), anything that is not a letter/digit/space/hyphen (path separators,
    quotes, ampersands, punctuation) is treated as a word boundary rather than
    silently deleted — so ``"R&D"`` becomes ``"R_D"``, not the misleading
    ``"RD"`` — and repeated separators collapse to a single underscore.
    """
    if not value:
        return ""
    folded = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    spaced = _UNSAFE_CHARS.sub(" ", folded)
    collapsed = _WHITESPACE_RUN.sub("_", spaced).strip("_")
    return collapsed[:max_length].strip("_")


def build_export_filename(
    *,
    candidate_name: str,
    job_title: str,
    company_name: str,
    artifact_type: str,
    template_id: str = "",
    kit_id: str = "",
) -> str:
    """Build the standardized download filename for a Resume or Cover Letter PDF.

    ``artifact_type`` is ``"resume"`` or ``"cover_letter"``; any other value is
    treated as ``"resume"``. ``template_id`` of ``"classic"``/``"modern"``
    appends the matching suffix before the extension; anything else appends
    nothing. ``kit_id`` is only ever used as the last-resort disambiguator, and
    only when candidate name, job title, and company are all unavailable.
    """
    name = sanitize_filename_component(candidate_name)
    title = sanitize_filename_component(job_title)
    company = sanitize_filename_component(company_name)

    artifact_label = "Cover_Letter" if artifact_type == "cover_letter" else "Resume"
    template_suffix = {"classic": "_Classic", "modern": "_Modern"}.get(template_id.strip().lower(), "")

    # The candidate-name slot is the only one that ever falls back to a fixed
    # placeholder ("Applicant") rather than being omitted — job title and
    # company are simply left out when unknown, never guessed.
    parts = [name or "Applicant"] + [part for part in (title, company) if part]
    base = "_".join(parts)
    if base == "Applicant":
        short_id = sanitize_filename_component(kit_id, max_length=8)
        if short_id:
            base = f"{base}_{short_id}"

    base = base[:_MAX_BASE_LENGTH].strip("_") or "Applicant"
    return f"{base}_{artifact_label}{template_suffix}.pdf"
