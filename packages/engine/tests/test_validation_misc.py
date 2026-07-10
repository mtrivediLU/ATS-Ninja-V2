from __future__ import annotations

from ats_engine.models import Mode
from ats_engine.validation.latex import validate_latex
from ats_engine.validation.output_format import validate_cover_letter_word_count, validate_output_format
from ats_engine.validation.repair import soften_banned_style
from ats_engine.validation.severity import is_fatal_validation_error, partition_validation_errors
from ats_engine.validation.style import validate_style


def test_no_em_dash_en_dash_or_double_hyphen() -> None:
    errors = validate_style("AI engineer — data engineer – software -- resume")
    assert "em dash is not allowed" in errors
    assert "en dash is not allowed" in errors
    assert "double hyphen is not allowed" in errors


def test_banned_words_are_caught() -> None:
    assert any("banned style phrase" in error for error in validate_style("I am excited to apply."))


def test_style_validator_flags_reported_generic_filler() -> None:
    noisy = "Dedicated professional ready to drive data-driven decision making in a fast-paced environment with tailored solutions."
    errors = validate_style(noisy)
    assert any("dedicated professional" in error for error in errors)
    assert any("drive data-driven decision making" in error for error in errors)
    assert any("fast-paced environment" in error for error in errors)
    assert any("tailored solutions" in error for error in errors)


def test_soften_banned_style_output_passes_style_validator() -> None:
    noisy = (
        "Architected and spearheaded a robust, seamless, mission-critical platform. "
        "Leveraged cutting-edge tools and streamlined end-to-end workflows. "
        "Results-driven and detail-oriented professional passionate about innovative solutions."
    )
    softened = soften_banned_style(noisy)
    assert not validate_style(softened)
    assert "Designed" in softened


def test_latex_ends_with_end_document() -> None:
    assert "missing \\end{document}" in validate_latex("\\documentclass{article}\n\\begin{document}\nHi")


def test_resume_subheading_has_exactly_4_arguments() -> None:
    good = "\\documentclass{article}\\begin{document}\\resumeSubheading{A}{B}{C}{D}\\end{document}"
    bad = "\\documentclass{article}\\begin{document}\\resumeSubheading{A}{B}{C}\\end{document}"
    assert not any("resumeSubheading" in error for error in validate_latex(good))
    assert any("resumeSubheading" in error for error in validate_latex(bad))


def test_resume_item_has_exactly_1_argument() -> None:
    good = "\\documentclass{article}\\begin{document}\\resumeItem{A}\\end{document}"
    bad = "\\documentclass{article}\\begin{document}\\resumeItem{A}{B}\\end{document}"
    assert not any("resumeItem" in error for error in validate_latex(good))
    assert any("resumeItem" in error for error in validate_latex(bad))


def test_output_format_validator_catches_text_after_final_code_block() -> None:
    text = "**Role:** Test\n**Interview Call Probability:** 80%\n**Analysis:** Good\n```latex\nx\n```\nextra"
    assert any("text after final code block" in error for error in validate_output_format(text, Mode.RESUME))


def test_cover_letter_word_count_bounds() -> None:
    assert validate_cover_letter_word_count("word " * 100)  # too short -> flagged
    assert not validate_cover_letter_word_count("word " * 300)  # within 280-320


def test_fatal_validation_error_classification() -> None:
    # Truth-critical / structural failures block delivery.
    assert is_fatal_validation_error("resume: invented or unsupported employer: fake labs")
    assert is_fatal_validation_error("resume: unsupported metric: 300%")
    assert is_fatal_validation_error("completeness: resume has 1 experience entries, source has 6")
    assert is_fatal_validation_error("resume: missing \\end{document}")
    # Cosmetic failures are warnings, not blockers.
    assert not is_fatal_validation_error("resume: banned style phrase: robust")
    assert not is_fatal_validation_error("cover letter word count 250 outside 280 to 320")


def test_partition_validation_errors_splits_fatal_and_warnings() -> None:
    errors = [
        "resume: invented or unsupported employer: fake labs",
        "resume: banned style phrase: robust",
    ]
    fatal, warnings = partition_validation_errors(errors)
    assert fatal == ["resume: invented or unsupported employer: fake labs"]
    assert warnings == ["resume: banned style phrase: robust"]
