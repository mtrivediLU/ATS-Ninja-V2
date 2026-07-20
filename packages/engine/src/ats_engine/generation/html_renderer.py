from __future__ import annotations

import re
from html import escape

from ats_engine.kit.contract import CoverLetterDocument, ResumeDocument

"""Deterministic rendering of structured Resume/Cover Letter documents into
single-column, ATS-safe HTML for local PDF rasterization.

This mirrors ``generation/latex_renderer.py``: pure string/markup work, no
binary rendering. Binary PDF rasterization (a heavy native-dependency, output
-format concern) stays out of the engine — see ADR-0004 and ADR-0018 — and is
performed by ``apps/api`` from the HTML this module returns.

The markup intentionally has no tables, images, icons, columns, or hidden
text: every element here is either a heading, a paragraph, or a list, so any
PDF text extractor reads it in the same order a human does.
"""

_ACCENT = "#2f6f4f"
_INK_CLASSIC = "#111111"
_INK_MODERN = "#1a1a1a"

_BASE_CSS = f"""
@page {{ size: Letter; margin: 0.65in 0.7in; }}
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; padding: 0; }}
body {{ color: {_INK_CLASSIC}; }}
.doc {{ font-size: 10pt; line-height: 1.4; }}
.doc.classic {{ font-family: Georgia, "Times New Roman", "Liberation Serif", serif; font-size: 10.5pt; line-height: 1.32; color: {_INK_CLASSIC}; }}
.doc.modern {{ font-family: "DejaVu Sans", Arial, "Liberation Sans", sans-serif; font-size: 10pt; line-height: 1.45; color: {_INK_MODERN}; }}
.doc-header {{ margin-bottom: 12px; }}
.classic .doc-header {{ text-align: center; }}
.modern .doc-header {{ border-bottom: 2px solid {_ACCENT}; padding-bottom: 14px; }}
.doc-name {{ margin: 0; font-size: 17pt; font-weight: 700; letter-spacing: .02em; }}
.classic .doc-name {{ text-transform: uppercase; }}
.modern .doc-name {{ font-size: 19pt; letter-spacing: -.01em; }}
.doc-headline {{ margin: 3px 0 0; font-size: 10.5pt; font-weight: 600; }}
.doc-contact {{ margin: 2px 0 0; font-size: 9.5pt; overflow-wrap: anywhere; }}
.section {{ margin-top: 12px; break-inside: avoid; page-break-inside: avoid; }}
.modern .section {{ margin-top: 15px; }}
.section > h2 {{ margin: 0 0 5px; border-bottom: 1.4px solid {_INK_CLASSIC}; padding-bottom: 2px; font-size: 9.5pt; font-weight: 700; letter-spacing: .07em; text-transform: uppercase; break-after: avoid; }}
.modern .section > h2 {{ margin-bottom: 7px; border: 0; color: {_ACCENT}; font-size: 8.5pt; letter-spacing: .12em; }}
.section-body p {{ margin: 0 0 4px; white-space: pre-wrap; overflow-wrap: anywhere; }}
.entry {{ margin-top: 9px; break-inside: avoid; }}
.entry-heading {{ display: flex; justify-content: space-between; gap: 16px; }}
.entry-heading .entry-employer {{ font-weight: 700; }}
.entry-heading .entry-dates {{ flex: 0 0 auto; text-align: right; white-space: nowrap; }}
.entry-title {{ margin: 2px 0 4px; font-style: italic; }}
.entry ul {{ margin: 4px 0 0; padding-left: 18px; }}
.entry li {{ margin-bottom: 3px; }}
.skill-groups p {{ margin: 0 0 4px; }}
.letter-sender {{ border-bottom: 2px solid {_ACCENT}; margin-bottom: 18px; padding-bottom: 10px; }}
.classic .letter-sender {{ border-bottom-color: {_INK_CLASSIC}; text-align: center; }}
.letter-date, .letter-greeting, .letter-closing, .letter-signature {{ margin: 16px 0 0; }}
.letter-recipient {{ display: flex; flex-direction: column; margin-top: 16px; }}
.letter-role {{ margin-top: 16px; font-weight: 600; }}
.letter-body p {{ margin: 12px 0 0; white-space: pre-wrap; }}
.verbatim {{ white-space: pre-wrap; overflow-wrap: anywhere; }}
"""


def _wrap_html(title: str, body: str) -> str:
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        f"<title>{escape(title)}</title><style>{_BASE_CSS}</style></head>"
        f"<body>{body}</body></html>"
    )


def _e(value: str) -> str:
    return escape(value or "", quote=True)


def render_resume_html(document: ResumeDocument, template: str) -> str:
    """Render a grounded, structured ``ResumeDocument`` into standalone HTML."""
    cls = "modern" if template == "modern" else "classic"
    parts: list[str] = [f'<article class="doc {cls}">']

    header_bits = []
    if document.candidate_name:
        header_bits.append(f'<h1 class="doc-name">{_e(document.candidate_name)}</h1>')
    if document.professional_headline:
        header_bits.append(f'<p class="doc-headline">{_e(document.professional_headline)}</p>')
    if document.contact_lines:
        header_bits.append(f'<p class="doc-contact">{_e(" · ".join(document.contact_lines))}</p>')
    if header_bits:
        parts.append(f'<header class="doc-header">{"".join(header_bits)}</header>')

    if document.summary:
        parts.append(_section("Professional Summary", f"<p>{_e(document.summary)}</p>"))

    if document.skill_groups:
        rows = []
        for group in document.skill_groups:
            items = ", ".join(item for item in group.items if item)
            if not items:
                continue
            label = f"<strong>{_e(group.label)}: </strong>" if group.label else ""
            rows.append(f"<p>{label}{_e(items)}</p>")
        if rows:
            parts.append(_section("Technical Skills", f'<div class="skill-groups">{"".join(rows)}</div>'))

    if document.experience:
        entries = []
        for entry in document.experience:
            heading_left = _e(" · ".join(part for part in (entry.employer, entry.location) if part))
            bullets = "".join(f"<li>{_e(bullet)}</li>" for bullet in entry.bullets if bullet)
            title_html = f'<p class="entry-title">{_e(entry.title)}</p>' if entry.title else ""
            entries.append(
                '<div class="entry">'
                f'<div class="entry-heading"><span class="entry-employer">{heading_left}</span>'
                f'<span class="entry-dates">{_e(entry.date_range)}</span></div>'
                f"{title_html}"
                f"{f'<ul>{bullets}</ul>' if bullets else ''}"
                "</div>"
            )
        parts.append(_section("Professional Experience", "".join(entries)))

    if document.education:
        education_entries = []
        for edu_entry in document.education:
            heading_left = _e(" · ".join(part for part in (edu_entry.institution, edu_entry.location) if part))
            degree_html = f'<p class="entry-title">{_e(edu_entry.degree)}</p>' if edu_entry.degree else ""
            details = "".join(f"<p>{_e(detail)}</p>" for detail in edu_entry.details if detail)
            education_entries.append(
                '<div class="entry">'
                f'<div class="entry-heading"><span class="entry-employer">{heading_left}</span>'
                f'<span class="entry-dates">{_e(edu_entry.date_range)}</span></div>'
                f"{degree_html}{details}"
                "</div>"
            )
        parts.append(_section("Education", "".join(education_entries)))

    if document.certifications:
        items = "".join(
            f"<li>{_e(' · '.join(part for part in (item.name, item.date, item.link) if part))}</li>"
            for item in document.certifications
            if item.name
        )
        if items:
            parts.append(_section("Certifications", f"<ul>{items}</ul>"))

    for heading, lines in document.remaining_sections:
        body = "".join(f"<p>{_e(line)}</p>" for line in lines if line)
        if body:
            parts.append(_section(heading or "Additional Information", body))

    parts.append("</article>")
    return _wrap_html(document.candidate_name or "Resume", "".join(parts))


def render_cover_letter_html(document: CoverLetterDocument, template: str) -> str:
    """Render a grounded, structured ``CoverLetterDocument`` into standalone HTML."""
    cls = "modern" if template == "modern" else "classic"
    parts: list[str] = [f'<article class="doc {cls}">']

    sender_bits = []
    if document.sender_name:
        sender_bits.append(f'<h1 class="doc-name">{_e(document.sender_name)}</h1>')
    if document.sender_contact_lines:
        sender_bits.append(f'<p class="doc-contact">{_e(" · ".join(document.sender_contact_lines))}</p>')
    if sender_bits:
        parts.append(f'<header class="letter-sender">{"".join(sender_bits)}</header>')

    if document.date:
        parts.append(f'<p class="letter-date">{_e(document.date)}</p>')

    recipient = [
        line
        for line in (
            document.recipient_name,
            document.recipient_title,
            document.recipient_company,
            *document.recipient_address,
        )
        if line
    ]
    if recipient:
        spans = "".join(f"<span>{_e(line)}</span>" for line in recipient)
        parts.append(f'<address class="letter-recipient">{spans}</address>')

    if document.target_role:
        parts.append(f'<p class="letter-role">Re: {_e(document.target_role)}</p>')
    if document.greeting:
        parts.append(f'<p class="letter-greeting">{_e(document.greeting)}</p>')

    body = "".join(f"<p>{_e(paragraph)}</p>" for paragraph in document.body_paragraphs if paragraph)
    parts.append(f'<div class="letter-body">{body}</div>')

    if document.closing:
        parts.append(f'<p class="letter-closing">{_e(document.closing)}</p>')
    if document.signature_name:
        parts.append(f'<p class="letter-signature">{_e(document.signature_name)}</p>')

    parts.append("</article>")
    return _wrap_html(document.sender_name or "Cover Letter", "".join(parts))


def _section(heading: str, body_html: str) -> str:
    return f'<div class="section"><h2>{_e(heading)}</h2><div class="section-body">{body_html}</div></div>'


_RECOGNIZED_HEADINGS = {
    "summary": "generic",
    "professional summary": "generic",
    "objective": "generic",
    "experience": "generic",
    "work experience": "generic",
    "professional experience": "generic",
    "employment": "generic",
    "education": "generic",
    "skills": "skills",
    "technical skills": "skills",
    "core skills": "skills",
    "certifications": "generic",
    "licenses & certifications": "generic",
    "projects": "generic",
    "awards": "generic",
    "publications": "generic",
    "volunteer": "generic",
    "languages": "generic",
}

_BULLET_LINE = re.compile(r"^[\-*•]\s+")


def render_plain_text_html(text: str, *, template: str) -> str:
    """Render freeform text (a local edit with no structured document) as HTML.

    Ported from the frontend's ``document-model.ts`` heading recognition so a
    locally-edited Resume/Cover Letter still downloads with real section
    headings and bullets when the edited text still uses recognizable
    headings; anything else falls back to a single verbatim, single-column,
    selectable-text block rather than guessing at structure.
    """
    cls = "modern" if template == "modern" else "classic"
    lines = (text or "").splitlines()

    sections: list[tuple[str, list[str]]] = []
    header_lines: list[str] = []
    current: tuple[str, list[str]] | None = None
    for line in lines:
        heading = _recognized_heading(line)
        if heading is not None:
            current = (line.strip().rstrip(":"), [])
            sections.append(current)
        elif current is not None:
            current[1].append(line)
        else:
            header_lines.append(line)

    if not sections:
        parts = [f'<article class="doc {cls}"><div class="verbatim">']
        parts.append(_e(text or ""))
        parts.append("</div></article>")
        return _wrap_html("Document", "".join(parts))

    body_parts = [f'<article class="doc {cls}">']
    header_text = "\n".join(line for line in header_lines if line.strip())
    if header_text:
        body_parts.append(f'<header class="doc-header"><p class="doc-contact">{_e(header_text)}</p></header>')
    for heading, section_lines in sections:
        body_parts.append(_section(heading, _render_freeform_lines(section_lines)))
    body_parts.append("</article>")
    return _wrap_html("Document", "".join(body_parts))


def _render_freeform_lines(lines: list[str]) -> str:
    html_lines: list[str] = []
    open_list = False
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if _BULLET_LINE.match(line):
            if not open_list:
                html_lines.append("<ul>")
                open_list = True
            html_lines.append(f"<li>{_e(_BULLET_LINE.sub('', line))}</li>")
        else:
            if open_list:
                html_lines.append("</ul>")
                open_list = False
            html_lines.append(f"<p>{_e(line)}</p>")
    if open_list:
        html_lines.append("</ul>")
    return "".join(html_lines)


def _recognized_heading(line: str) -> str | None:
    stripped = line.strip()
    if not stripped or stripped != line:
        return None
    normalized = stripped.rstrip(":").lower()
    return _RECOGNIZED_HEADINGS.get(normalized)
