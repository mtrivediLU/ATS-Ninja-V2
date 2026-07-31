"""One definition of the delivered document's layout.

Everything a candidate downloads -- DOCX, HTML, and the PDF rendered from that
HTML -- lays an entry out the same way, and this module is where that layout is
defined once. Before it existed, each renderer re-derived ``" · ".join(...)``
locally and expressed bullets in its own format-specific way, so there was no
single place that answered "what does the delivered document actually say".

That question matters because it is the text an ATS reads, and the text this
engine must score. See :func:`ats_engine.generation.document_render.
render_delivered_resume_text` for the text projection built on these helpers.

**Markers must be literal text.** A bullet drawn from DOCX numbering
definitions or a CSS ``list-style`` exists visually but not in the extracted
text layer. Every resume this engine delivered came back from PyMuPDF as
unmarked prose, which no parser -- ours or an external ATS -- can distinguish
from an employer header line.
"""

from __future__ import annotations

# The separator between an employer and its location, an institution and its
# location, and the fields of a certification line. Chosen to match the
# convention modern resume templates use; ``parsing/resume.py`` recognises it
# as an explicit column boundary when splitting a location tail.
FIELD_SEPARATOR = "·"

# Written into the text of every bullet, in every delivered format, so the
# marker survives text extraction.
BULLET_MARKER = "•"


def join_fields(*parts: str) -> str:
    """Join non-empty entry-heading fields with the delivered separator."""
    return f" {FIELD_SEPARATOR} ".join(part for part in parts if part)


def bullet_line(text: str) -> str:
    """Render one bullet with its literal marker."""
    return f"{BULLET_MARKER} {text}"


__all__ = ["BULLET_MARKER", "FIELD_SEPARATOR", "bullet_line", "join_fields"]
