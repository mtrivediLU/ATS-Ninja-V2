from __future__ import annotations

from ats_engine.generation.document_normalization import normalize_generated_prose, strip_banned_dashes
from ats_engine.generation.latex_renderer import cover_letter_to_latex
from ats_engine.models import CoverLetterPlan
from ats_engine.validation.repair import soften_banned_style


def generate_cover_letter_text(plan: CoverLetterPlan) -> str:
    """Render cover-letter body text from a structured plan."""
    return normalize_generated_prose(soften_banned_style("\n\n".join(plan.body_paragraphs).strip()))


def generate_cover_letter_latex(plan: CoverLetterPlan) -> str:
    """Produce a complete standalone Overleaf-ready cover letter."""
    contact = plan.contacts
    user_info = {
        "name": contact.name,
        "email": contact.email,
        "phone": contact.phone,
        "headline": "",
        "location": contact.location,
        "linkedin": contact.linkedin,
        "portfolio": contact.website,
    }
    return strip_banned_dashes(cover_letter_to_latex(generate_cover_letter_text(plan), user_info)).strip()


def format_cover_letter_output(plan: CoverLetterPlan, latex_code: str) -> str:
    """Format Mode C output exactly."""
    return f"**Letter angle:** {plan.angle}\n**Word count:** {plan.word_count}\n```latex\n{latex_code.strip()}\n```"
