from __future__ import annotations

from ats_engine.validation.naturalness import (
    SUMMARY_CLOSINGS,
    bullet_safety_errors,
    dedupe_bullets,
    detect_jd_echo,
    detect_keyword_stuffing,
    jd_appended_to_resume,
    safe_bullet,
    select_summary_closing,
)


def test_overall_keyword_density_threshold() -> None:
    text = "python " * 6  # 6 occurrences, word_count 6 -> limit max(2, ceil(6/150))=2
    warnings = detect_keyword_stuffing(text, [], ["python"])
    assert any("overall" in w for w in warnings)


def test_same_keyword_twice_in_one_bullet() -> None:
    warnings = detect_keyword_stuffing(
        "Built python services with python tooling", ["Built python services with python tooling"], ["python"]
    )
    assert any("single bullet" in w for w in warnings)


def test_keyword_in_more_than_half_of_bullets() -> None:
    bullets = ["used sql here", "used sql there", "did something else"]
    warnings = detect_keyword_stuffing(" ".join(bullets), bullets, ["sql"])
    assert any("of 3 bullets" in w for w in warnings)


def test_near_duplicate_bullets_flagged_and_deduped() -> None:
    bullets = ["Built data pipelines", "built data pipelines", "Wrote reports"]
    warnings = detect_keyword_stuffing(" ".join(bullets), bullets, [])
    assert any("duplicates" in w for w in warnings)
    assert dedupe_bullets(bullets) == ["Built data pipelines", "Wrote reports"]


def test_eight_word_jd_echo_detected() -> None:
    jd = "we are looking for someone to build reliable systems for our customers every day"
    resume = "The candidate will build reliable systems for our customers every day at scale"
    warnings = detect_jd_echo(resume, jd, keyword_phrases=[], window=8)
    assert warnings


def test_short_keyword_phrase_is_not_echo() -> None:
    jd = "python and sql required"
    resume = "python and sql experience"
    # a legitimate 2-3 word keyword overlap must not be flagged at window 8
    assert detect_jd_echo(resume, jd, keyword_phrases=["python", "sql"], window=8) == []


def test_jd_appended_to_resume_detected() -> None:
    jd = " ".join(f"word{i}" for i in range(40))
    resume = "Real resume content here " + jd
    assert jd_appended_to_resume(resume, jd, window=20) is True
    assert jd_appended_to_resume("Unrelated resume content entirely", jd, window=20) is False


def test_summary_closing_is_deterministic_and_varies() -> None:
    assert select_summary_closing("seed-a") == select_summary_closing("seed-a")
    spread = {select_summary_closing(f"seed-{i}") for i in range(20)}
    assert len(spread) >= 2
    assert len(SUMMARY_CLOSINGS) >= 6


def test_bullet_first_person_rejected() -> None:
    errors = bullet_safety_errors("I built the data pipeline", "Built the data pipeline", [])
    assert any("first person" in e for e in errors)


def test_bullet_ownership_escalation_rejected() -> None:
    errors = bullet_safety_errors("Led the migration effort", "Contributed to the migration effort", [])
    assert any("ownership" in e for e in errors)


def test_bullet_length_ratio_rejected() -> None:
    errors = bullet_safety_errors("Built systems that scale well " * 4, "Built systems", [])
    assert any("length ratio" in e for e in errors)


def test_bullet_new_tool_and_metric_rejected() -> None:
    assert any(
        "tool" in e for e in bullet_safety_errors("Built pipelines using Kubernetes", "Built pipelines", ["kubernetes"])
    )
    assert any("metric" in e for e in bullet_safety_errors("Reduced load by 90%", "Reduced load noticeably", []))


def test_safe_bullet_falls_back_to_original() -> None:
    assert safe_bullet("I spearheaded 500 deployments", "Helped with deployments", []) == "Helped with deployments"
    good = "Optimized the reporting pipeline for the finance team"
    assert safe_bullet(good, "Built the reporting pipeline for finance", []) == good
