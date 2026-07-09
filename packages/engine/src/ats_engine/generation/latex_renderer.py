from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

"""Deterministic rendering of structured resume/cover-letter text into LaTeX.

This is pure string/templating work (Jinja2 over packaged ``.tex`` templates);
it produces the Overleaf-ready artifact the product delivers. Binary PDF
rasterization (a heavy native-dependency concern) is intentionally out of scope
for this layer — see the architecture docs.
"""

# Templates ship as package data alongside this module, so the renderer works
# from an installed wheel without any repository-relative path assumptions.
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


SECTION_ALIASES = {
    "candidate header": "header",
    "header": "header",
    "professional summary": "summary",
    "summary": "summary",
    "profile": "summary",
    "core skills": "skills",
    "skills": "skills",
    "technical skills": "skills",
    "professional experience": "experience",
    "experience": "experience",
    "work experience": "experience",
    "employment history": "experience",
    "education": "education",
    "certifications": "certifications",
    "certification": "certifications",
    "licenses": "certifications",
}

HEADER_FIELD_ALIASES = {
    "professional headline": "headline",
    "headline": "headline",
    "target headline": "headline",
    "target role": "headline",
    "location": "location",
    "linkedin": "linkedin",
    "linkedin url": "linkedin",
    "portfolio": "portfolio",
    "portfolio url": "portfolio",
    "website": "portfolio",
    "personal website": "portfolio",
    "work authorization": "work_authorization",
    "authorization": "work_authorization",
    "relocation": "relocation",
    "email": "email",
    "phone": "phone",
}

EXPERIENCE_FIELD_ALIASES = {
    "company": "company",
    "employer": "company",
    "organization": "company",
    "location": "location",
    "title": "title",
    "role": "title",
    "job title": "title",
    "dates": "dates",
    "date": "dates",
    "period": "dates",
}

EDUCATION_FIELD_ALIASES = {
    "institution": "institution",
    "school": "institution",
    "university": "institution",
    "location": "location",
    "degree": "degree",
    "program": "degree",
    "dates": "dates",
    "date": "dates",
    "period": "dates",
}

CERTIFICATION_FIELD_ALIASES = {
    "certification": "name",
    "certificate": "name",
    "name": "name",
    "issuer": "issuer",
    "date": "date",
    "year": "date",
    "link": "link",
    "url": "link",
    "verify": "link",
}


def resume_to_latex(resume_text: str, user_info: dict[str, str]) -> str:
    """Render structured resume text into a complete polished LaTeX document."""
    raw_context = build_resume_context(resume_text, user_info)
    context = _latex_resume_context(raw_context)
    environment = _template_environment()
    template = environment.get_template("resume_template.tex")
    return template.render(**context)


def cover_letter_to_latex(cover_letter_text: str, user_info: dict[str, str]) -> str:
    """Render cover letter text into a complete polished LaTeX document."""
    raw_context = build_cover_letter_context(cover_letter_text, user_info)
    context = _latex_cover_letter_context(raw_context)
    environment = _template_environment()
    template = environment.get_template("cover_letter_template.tex")
    return template.render(**context)


def build_resume_context(resume_text: str, user_info: dict[str, str] | None) -> dict[str, Any]:
    """Build raw template context for resume LaTeX renderers."""
    sections = parse_resume_sections(resume_text or "")
    merged_user_info = {
        **sections.get("header", {}),
        **{key: value for key, value in (user_info or {}).items() if value},
    }
    headline = _first_nonempty(
        merged_user_info.get("headline", ""),
        sections.get("headline", ""),
    )

    return {
        "name": _user_value(merged_user_info, "name", "Your Name"),
        "headline": headline,
        "contact_rows": _build_contact_rows(merged_user_info, sections.get("header", {})),
        "summary": sections["summary"],
        "skills": sections["skills"],
        "experience": sections["experience"],
        "education": sections["education"],
        "certifications": sections["certifications"],
    }


def build_cover_letter_context(
    cover_letter_text: str,
    user_info: dict[str, str] | None,
) -> dict[str, Any]:
    """Build raw template context for cover letter LaTeX renderers."""
    return {
        "name": _user_value(user_info, "name", "Your Name"),
        "headline": _user_value(user_info, "headline", ""),
        "date": _format_date(date.today()),
        "contact_rows": _build_contact_rows(user_info or {}, {}),
        "body": split_cover_letter_paragraphs(cover_letter_text, user_info),
    }


def parse_resume_sections(resume_text: str) -> dict[str, Any]:
    """Parse generated resume text into recruiter-grade structured sections."""
    sections: dict[str, Any] = {
        "header": {},
        "headline": "",
        "summary": "",
        "skills": [],
        "experience": [],
        "education": [],
        "certifications": [],
    }
    if not resume_text or not resume_text.strip():
        return sections

    current_section = "header"
    summary_lines: list[str] = []
    current_experience: dict[str, Any] | None = None
    current_education: dict[str, Any] | None = None

    def flush_experience() -> None:
        nonlocal current_experience
        if current_experience and _entry_has_content(current_experience):
            current_experience["bullets"] = _dedupe(current_experience.get("bullets", []))
            sections["experience"].append(current_experience)
        current_experience = None

    def flush_education() -> None:
        nonlocal current_education
        if current_education and _entry_has_content(current_education):
            current_education["bullets"] = _dedupe(current_education.get("bullets", []))
            sections["education"].append(current_education)
        current_education = None

    def switch_section(section: str) -> None:
        nonlocal current_section
        if current_section == "experience":
            flush_experience()
        if current_section == "education":
            flush_education()
        current_section = section

    for raw_line in resume_text.splitlines():
        line = _strip_markdown(raw_line)
        if not line:
            continue

        detected_section, remainder = _detect_section(line)
        if detected_section:
            switch_section(detected_section)
            line = remainder
            if not line:
                continue

        if current_section == "header":
            if not _apply_header_line(sections, line):
                summary_lines.append(_clean_content_line(line))
            continue

        if current_section == "summary":
            summary_lines.append(_clean_content_line(line))
            continue

        if current_section == "skills":
            _add_skill_line(sections, line)
            continue

        if current_section == "experience":
            current_experience = _handle_entry_line(
                line=line,
                current_entry=current_experience,
                entries=sections["experience"],
                aliases=EXPERIENCE_FIELD_ALIASES,
                defaults={"company": "", "location": "", "title": "", "dates": "", "bullets": []},
                primary_field="company",
                secondary_field="title",
            )
            continue

        if current_section == "education":
            current_education = _handle_entry_line(
                line=line,
                current_entry=current_education,
                entries=sections["education"],
                aliases=EDUCATION_FIELD_ALIASES,
                defaults={"institution": "", "location": "", "degree": "", "dates": "", "bullets": []},
                primary_field="institution",
                secondary_field="degree",
            )
            continue

        if current_section == "certifications":
            certification = _parse_certification_line(line)
            if certification:
                sections["certifications"].append(certification)

    if current_section == "experience":
        flush_experience()
    if current_section == "education":
        flush_education()

    sections["summary"] = _collapse_sentences(summary_lines)
    sections["skills"] = _dedupe_skill_groups(sections["skills"])
    sections["certifications"] = _dedupe_certifications(sections["certifications"])

    if not sections["experience"] and summary_lines:
        sections["experience"] = [
            {
                "company": "Selected Experience",
                "location": "",
                "title": "",
                "dates": "",
                "bullets": _dedupe(summary_lines),
            }
        ]

    return sections


def split_cover_letter_paragraphs(
    cover_letter_text: str,
    user_info: dict[str, str] | None = None,
) -> list[str]:
    """Split a cover letter into clean paragraphs, removing duplicate contact headers."""
    text = _strip_cover_letter_header((cover_letter_text or "").strip(), user_info)
    if not text:
        return []

    text = re.sub(r"^\s*(cover letter|body)\s*:?\s*", "", text, flags=re.IGNORECASE)
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    if len(paragraphs) == 1:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return lines if len(lines) > 1 else paragraphs
    return paragraphs


def latex_escape(value: str) -> str:
    """Escape text for safe inclusion in simple LaTeX templates."""
    if value is None:
        return ""

    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(char, char) for char in str(value))


def _template_environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(disabled_extensions=("tex",), default_for_string=False),
        comment_start_string="((*",
        comment_end_string="*))",
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _apply_header_line(sections: dict[str, Any], line: str) -> bool:
    values = _parse_key_value_segments(line, HEADER_FIELD_ALIASES)
    if not values:
        return False

    sections["header"].update(values)
    if "headline" in values:
        sections["headline"] = values["headline"]
    return True


def _add_skill_line(sections: dict[str, Any], line: str) -> None:
    cleaned = _clean_content_line(line)
    if not cleaned:
        return

    category = "Core Skills"
    items_text = cleaned
    if ":" in cleaned:
        possible_category, possible_items = cleaned.split(":", 1)
        if 2 <= len(possible_category.strip()) <= 42:
            category = possible_category.strip()
            items_text = possible_items.strip()

    items = _split_skill_items(items_text)
    if items:
        sections["skills"].append(
            {
                "category": category,
                "items": items,
                "items_text": ", ".join(items),
            }
        )


def _handle_entry_line(
    line: str,
    current_entry: dict[str, Any] | None,
    entries: list[dict[str, Any]],
    aliases: dict[str, str],
    defaults: dict[str, Any],
    primary_field: str,
    secondary_field: str,
) -> dict[str, Any]:
    values = _parse_key_value_segments(line, aliases)
    if values:
        if primary_field in values and current_entry and _entry_has_content(current_entry):
            current_entry["bullets"] = _dedupe(current_entry.get("bullets", []))
            entries.append(current_entry)
            current_entry = None
        current_entry = current_entry or _new_entry(defaults)
        current_entry.update(values)
        return current_entry

    current_entry = current_entry or _new_entry(defaults)
    if _is_bullet_line(line):
        current_entry["bullets"].append(_clean_content_line(line))
        return current_entry

    cleaned = _clean_content_line(line)
    if not cleaned:
        return current_entry

    if current_entry.get("bullets"):
        current_entry["bullets"] = _dedupe(current_entry.get("bullets", []))
        entries.append(current_entry)
        current_entry = _new_entry(defaults)

    if not current_entry.get(primary_field):
        current_entry[primary_field] = cleaned
    elif not current_entry.get(secondary_field):
        current_entry[secondary_field] = cleaned
    else:
        current_entry["bullets"].append(cleaned)

    return current_entry


def _parse_certification_line(line: str) -> dict[str, str] | None:
    values = _parse_key_value_segments(line, CERTIFICATION_FIELD_ALIASES)
    if values:
        name = values.get("name") or values.get("issuer", "")
        if not name:
            return None
        return {
            "name": name,
            "issuer": values.get("issuer", ""),
            "date": values.get("date", ""),
            "link": values.get("link", ""),
            "link_label": _display_url(values.get("link", "")) or "Verify",
        }

    cleaned = _clean_content_line(line)
    if not cleaned:
        return None

    parts = [part.strip() for part in re.split(r"\s+\|\s+|\s+-\s+", cleaned) if part.strip()]
    date_value = ""
    link = ""
    name_parts: list[str] = []
    for part in parts or [cleaned]:
        if not date_value and re.fullmatch(r"(19|20)\d{2}", part):
            date_value = part
        elif not link and _looks_like_url(part):
            link = part
        else:
            name_parts.append(part)

    return {
        "name": " - ".join(name_parts).strip() or cleaned,
        "issuer": "",
        "date": date_value,
        "link": link,
        "link_label": _display_url(link) or "Verify",
    }


def _parse_key_value_segments(line: str, aliases: dict[str, str]) -> dict[str, str]:
    values: dict[str, str] = {}
    segments = [segment.strip() for segment in line.split("|") if segment.strip()]
    last_field = ""
    for segment in segments:
        match = re.match(r"^([A-Za-z][A-Za-z\s/&.-]{1,32})\s*:\s*(.+)$", segment)
        if not match:
            if last_field:
                values[last_field] = f"{values[last_field]} | {segment}"
            continue
        key = _normalize_heading(match.group(1))
        value = match.group(2).strip()
        field = aliases.get(key)
        if field and value:
            values[field] = value
            last_field = field
    return values


def _detect_section(line: str) -> tuple[str | None, str]:
    normalized = _normalize_heading(line)
    if normalized in SECTION_ALIASES:
        return SECTION_ALIASES[normalized], ""

    if ":" in line:
        possible_heading, remainder = line.split(":", 1)
        normalized_heading = _normalize_heading(possible_heading)
        if normalized_heading in SECTION_ALIASES:
            return SECTION_ALIASES[normalized_heading], remainder.strip()

    return None, line


def _latex_resume_context(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": latex_escape(context.get("name", "")),
        "headline": latex_escape(context.get("headline", "")),
        "contact_rows": [
            [
                {
                    "label": latex_escape(item["label"]),
                    "href": latex_escape(item.get("href", "")),
                }
                for item in row
            ]
            for row in context.get("contact_rows", [])
        ],
        "summary": latex_escape(context.get("summary", "")),
        "skills": [
            {
                "category": latex_escape(group.get("category", "")),
                "items_text": latex_escape(group.get("items_text", "")),
            }
            for group in context.get("skills", [])
        ],
        "experience": [
            {
                "company": latex_escape(entry.get("company", "")),
                "location": latex_escape(entry.get("location", "")),
                "title": latex_escape(entry.get("title", "")),
                "dates": latex_escape(entry.get("dates", "")),
                "bullets": [latex_escape(bullet) for bullet in entry.get("bullets", [])],
            }
            for entry in context.get("experience", [])
        ],
        "education": [
            {
                "institution": latex_escape(entry.get("institution", "")),
                "location": latex_escape(entry.get("location", "")),
                "degree": latex_escape(entry.get("degree", "")),
                "dates": latex_escape(entry.get("dates", "")),
                "bullets": [latex_escape(bullet) for bullet in entry.get("bullets", [])],
            }
            for entry in context.get("education", [])
        ],
        "certifications": [
            {
                "name": latex_escape(item.get("name", "")),
                "issuer": latex_escape(item.get("issuer", "")),
                "date": latex_escape(item.get("date", "")),
                "link": latex_escape(item.get("link", "")),
                "link_label": latex_escape(item.get("link_label", "Verify")),
            }
            for item in context.get("certifications", [])
        ],
    }


def _latex_cover_letter_context(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": latex_escape(context.get("name", "")),
        "headline": latex_escape(context.get("headline", "")),
        "date": latex_escape(context.get("date", "")),
        "contact_rows": [
            [
                {
                    "label": latex_escape(item["label"]),
                    "href": latex_escape(item.get("href", "")),
                }
                for item in row
            ]
            for row in context.get("contact_rows", [])
        ],
        "body": [latex_escape(paragraph) for paragraph in context.get("body", [])],
    }


def _build_contact_rows(
    user_info: dict[str, str],
    parsed_header: dict[str, str],
) -> list[list[dict[str, str]]]:
    info = {**parsed_header, **{key: value for key, value in user_info.items() if value}}
    primary: list[dict[str, str]] = []
    secondary: list[dict[str, str]] = []

    phone = _clean_optional(info.get("phone", ""))
    email = _clean_optional(info.get("email", ""))
    linkedin = _clean_optional(info.get("linkedin", ""))
    portfolio = _clean_optional(info.get("portfolio", ""))
    location = _clean_optional(info.get("location", ""))
    work_authorization = _clean_optional(info.get("work_authorization", ""))
    relocation = _clean_optional(info.get("relocation", ""))

    if phone:
        primary.append({"label": phone, "href": ""})
    if email:
        primary.append({"label": email, "href": f"mailto:{email}"})
    if linkedin:
        primary.append({"label": _display_url(linkedin), "href": _normalize_url(linkedin)})
    if portfolio:
        primary.append({"label": _display_url(portfolio), "href": _normalize_url(portfolio)})
    if location:
        secondary.append({"label": location, "href": ""})
    if work_authorization:
        secondary.append({"label": work_authorization, "href": ""})
    if relocation:
        secondary.append({"label": relocation, "href": ""})

    return [row for row in [primary, secondary] if row]


def _strip_markdown(line: str) -> str:
    stripped = line.strip()
    stripped = re.sub(r"^#{1,6}\s*", "", stripped)
    stripped = stripped.strip("*_` ")
    return stripped.strip()


def _normalize_heading(line: str) -> str:
    heading = line.strip().strip(":").strip()
    heading = re.sub(r"^[#*\-\s]+", "", heading)
    heading = re.sub(r"[*_]+$", "", heading)
    heading = heading.strip().strip(":").lower()
    return re.sub(r"\s+", " ", heading)


def _clean_content_line(line: str) -> str:
    cleaned = re.sub(r"^[\-*•]\s*", "", line.strip())
    return cleaned.strip()


def _is_bullet_line(line: str) -> bool:
    return bool(re.match(r"^\s*[\-*•]\s+", line))


def _split_skill_items(text: str) -> list[str]:
    parts = re.split(r"[,;|]|\s{2,}", text)
    return _dedupe([part.strip() for part in parts if part.strip()])


def _collapse_sentences(lines: list[str]) -> str:
    cleaned = [line for line in lines if line and not _looks_like_contact_noise(line)]
    return " ".join(cleaned).strip()


def _looks_like_contact_noise(line: str) -> bool:
    normalized = line.lower()
    return "@" in normalized or normalized.startswith(("phone:", "email:", "linkedin:", "portfolio:"))


def _entry_has_content(entry: dict[str, Any]) -> bool:
    return any(entry.get(key) for key in entry if key != "bullets") or bool(entry.get("bullets"))


def _new_entry(defaults: dict[str, Any]) -> dict[str, Any]:
    entry: dict[str, Any] = {}
    for key, value in defaults.items():
        entry[key] = list(value) if isinstance(value, list) else value
    return entry


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        key = item.lower().strip()
        if key and key not in seen:
            deduped.append(item.strip())
            seen.add(key)
    return deduped


def _dedupe_skill_groups(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, list[str]] = {}
    for group in groups:
        category = group.get("category", "Core Skills").strip() or "Core Skills"
        merged.setdefault(category, [])
        merged[category].extend(group.get("items", []))

    return [
        {
            "category": category,
            "items": _dedupe(items),
            "items_text": ", ".join(_dedupe(items)),
        }
        for category, items in merged.items()
        if _dedupe(items)
    ]


def _dedupe_certifications(items: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    deduped: list[dict[str, str]] = []
    for item in items:
        key = item.get("name", "").lower().strip()
        if key and key not in seen:
            deduped.append(item)
            seen.add(key)
    return deduped


def _strip_cover_letter_header(text: str, user_info: dict[str, str] | None) -> str:
    if not text or not user_info:
        return text

    values = [
        _user_value(user_info, "name", "").lower(),
        _user_value(user_info, "email", "").lower(),
        _user_value(user_info, "phone", "").lower(),
    ]
    lines = text.splitlines()
    first_body_index = 0

    for index, line in enumerate(lines[:8]):
        normalized = line.strip().lower()
        if not normalized:
            first_body_index = index + 1
            continue
        is_header_line = (
            any(value and value in normalized for value in values)
            or "@" in normalized
            or normalized.startswith(("phone:", "email:", "linkedin:", "portfolio:"))
        )
        if is_header_line:
            first_body_index = index + 1
            continue
        break

    return "\n".join(lines[first_body_index:]).strip()


def _user_value(user_info: dict[str, str] | None, key: str, default: str) -> str:
    value = (user_info or {}).get(key, default)
    return str(value or default).strip()


def _first_nonempty(*values: str) -> str:
    for value in values:
        if value and str(value).strip():
            return str(value).strip()
    return ""


def _clean_optional(value: str) -> str:
    cleaned = str(value or "").strip()
    if cleaned.lower() in {"your phone", "your.email@example.com", "your name"}:
        return ""
    return cleaned


def _looks_like_url(value: str) -> bool:
    lowered = value.lower()
    return lowered.startswith(("http://", "https://")) or "." in lowered and " " not in lowered


def _normalize_url(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        return ""
    if cleaned.startswith(("http://", "https://", "mailto:")):
        return cleaned
    return f"https://{cleaned}"


def _display_url(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        return ""
    cleaned = re.sub(r"^https?://", "", cleaned)
    cleaned = re.sub(r"^mailto:", "", cleaned)
    return cleaned.rstrip("/")


def _format_date(value: Any) -> str:
    return f"{value.strftime('%B')} {value.day}, {value.year}"
