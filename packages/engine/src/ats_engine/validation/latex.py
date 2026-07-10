from __future__ import annotations

import re


def validate_latex(latex_code: str) -> list[str]:
    """Validate common LaTeX structural errors before output."""
    errors: list[str] = []
    if "\\end{document}" not in latex_code:
        errors.append("missing \\end{document}")
    if not _balanced_braces(latex_code):
        errors.append("unbalanced braces")
    if latex_code.count("\\begin{itemize}") != latex_code.count("\\end{itemize}"):
        errors.append("unmatched itemize starts and ends")

    for position in _command_positions(latex_code, "\\resumeSubheading"):
        count = _count_command_args(latex_code, position + len("\\resumeSubheading"))
        if count != 4:
            errors.append("\\resumeSubheading must have exactly 4 arguments")
            break
    for position in _command_positions(latex_code, "\\resumeItem"):
        count = _count_command_args(latex_code, position + len("\\resumeItem"))
        if count != 1:
            errors.append("\\resumeItem must have exactly 1 argument")
            break

    if _has_stray_macro_argument(latex_code):
        errors.append("stray macro argument outside newcommand body")
    if "```" in latex_code:
        errors.append("malformed LaTeX code fence inside LaTeX")
    if _has_visible_unescaped_symbol(latex_code):
        errors.append("visible &, %, or $ must be escaped")
    return errors


def _balanced_braces(text: str) -> bool:
    depth = 0
    escaped = False
    for char in text:
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _command_positions(text: str, command: str) -> list[int]:
    positions: list[int] = []
    pattern = re.compile(rf"{re.escape(command)}(?![A-Za-z])")
    for match in pattern.finditer(text):
        index = match.start()
        if "\\newcommand" not in text[max(0, index - 24) : index]:
            positions.append(index)
    return positions


def _count_command_args(text: str, start: int) -> int:
    index = start
    count = 0
    while index < len(text):
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text) or text[index] != "{":
            break
        end = _matching_brace(text, index)
        if end == -1:
            return -1
        count += 1
        index = end + 1
    return count


def _matching_brace(text: str, start: int) -> int:
    depth = 0
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _has_stray_macro_argument(text: str) -> bool:
    in_newcommand = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("\\newcommand"):
            in_newcommand = True
        if re.search(r"#[1-4]", line) and not in_newcommand:
            return True
        if in_newcommand and stripped == "}":
            in_newcommand = False
    return False


def _has_visible_unescaped_symbol(text: str) -> bool:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("\\") or "&" in stripped and "tabular" in stripped:
            continue
        if re.search(r"(?<!\\)[%&$]", stripped):
            if "$|$" in stripped or "\\textcolor" in stripped or "\\begin{tabular" in stripped:
                continue
            return True
    return False
