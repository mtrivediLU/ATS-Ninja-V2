from __future__ import annotations

import re
from dataclasses import dataclass

from ats_engine.models import ContactInfo

"""Deterministic, syntax-only validation of resolved contact fields.

This never rewrites or guesses a replacement value — a resume's contact block
is truth-critical (it is how a recruiter actually reaches the candidate), so
when a field looks malformed the only safe action is to flag it and preserve
the reviewed text exactly as the candidate submitted it.
"""

_EMAIL_PATTERN = re.compile(r"^[\w.+-]+@[\w-]+(?:\.[\w-]+)+$")
_PHONE_DIGIT_RANGE = range(7, 16)
_URL_PATTERN = re.compile(r"^(?:https?://)?(?:www\.)?[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+(?:/\S*)?$")
_LINKEDIN_PATTERN = re.compile(r"^(?:https?://)?(?:www\.)?linkedin\.com/in/[A-Za-z0-9_-]+/?$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ContactIntegrityReport:
    """Syntactic validity of each populated contact field. Blank fields are
    always considered valid (nothing to validate, nothing to warn about)."""

    email_valid: bool
    phone_valid: bool
    linkedin_valid: bool
    website_valid: bool
    warnings: tuple[str, ...] = ()


def validate_contact_integrity(contact: ContactInfo) -> ContactIntegrityReport:
    """Check syntactic validity of resolved contact fields without altering them."""
    warnings: list[str] = []

    email_valid = not contact.email or bool(_EMAIL_PATTERN.match(contact.email))
    if not email_valid:
        warnings.append("email does not look syntactically valid")

    phone_digits = re.sub(r"\D", "", contact.phone)
    phone_valid = not contact.phone or len(phone_digits) in _PHONE_DIGIT_RANGE
    if not phone_valid:
        warnings.append("phone number does not look syntactically valid")

    linkedin_valid = not contact.linkedin or bool(_LINKEDIN_PATTERN.match(contact.linkedin))
    if not linkedin_valid:
        warnings.append("LinkedIn URL does not look syntactically valid")

    website_valid = not contact.website or bool(_URL_PATTERN.match(contact.website))
    if not website_valid:
        warnings.append("portfolio/website URL does not look syntactically valid")

    return ContactIntegrityReport(
        email_valid=email_valid,
        phone_valid=phone_valid,
        linkedin_valid=linkedin_valid,
        website_valid=website_valid,
        warnings=tuple(warnings),
    )
