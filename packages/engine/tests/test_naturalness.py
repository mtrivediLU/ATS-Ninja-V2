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
    # 12 occurrences in a 12-word text -> limit max(6, ceil(12/90))=6; 12 > 6 flags.
    text = "python " * 12
    warnings = detect_keyword_stuffing(text, [], ["python"])
    assert any("overall" in w for w in warnings)


def test_core_skill_recurrence_is_not_flagged_as_stuffing() -> None:
    # A core skill that legitimately appears a handful of times across a normal
    # resume must not be flagged (the pre-wiring floor of 2 did this wrongly).
    text = (
        "Python developer. Skills: Python, SQL. Built Python services. Maintained Python data jobs. "
    ) * 1 + " ".join(["word"] * 120)
    warnings = detect_keyword_stuffing(text, [], ["python"])
    assert not any("overall" in w for w in warnings)


def test_same_keyword_three_times_in_one_bullet() -> None:
    bullet = "Built python services with python tooling and python scripts"
    warnings = detect_keyword_stuffing(bullet, [bullet], ["python"])
    assert any("single bullet" in w for w in warnings)


def test_same_keyword_twice_in_one_bullet_is_not_flagged() -> None:
    # Two legitimate mentions ("SQL Server ... SQL warehouse") are not stuffing.
    bullet = "Migrated SQL Server databases to a new SQL warehouse"
    warnings = detect_keyword_stuffing(bullet, [bullet], ["sql"])
    assert not any("single bullet" in w for w in warnings)


def test_keyword_in_almost_every_bullet_is_flagged() -> None:
    # A keyword mechanically pasted into 5 of 6 bullets is stuffing.
    bullets = [
        "used sql a",
        "used sql b",
        "used sql c",
        "used sql d",
        "used sql e",
        "did something else",
    ]
    warnings = detect_keyword_stuffing(" ".join(bullets), bullets, ["sql"])
    assert any("of 6 bullets" in w for w in warnings)


def test_core_skill_in_a_couple_of_bullets_is_not_flagged() -> None:
    # Two of three bullets naming a core skill is normal expertise, not stuffing.
    bullets = ["used sql here", "used sql there", "did something else"]
    warnings = detect_keyword_stuffing(" ".join(bullets), bullets, ["sql"])
    assert not any("bullets" in w for w in warnings)


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


def test_fallback_summary_uses_varied_pool_closing() -> None:
    # The deterministic fallback summary must end with a closing drawn from the
    # naturalness pool (wired into generation), not the old fixed sentence.
    import sys

    sys.path.insert(0, "packages/engine/tests")
    from ats_engine.generation.planning import build_resume_plan
    from ats_engine.parsing.job_description import parse_jd
    from ats_engine.parsing.resume import build_profile

    resume = (
        "Alex Morgan\nProfessional Experience\nCompany: Acme\nTitle: Engineer\nDates: 2019 - 2024\n"
        "- Built Python services and SQL reports\nSkills\nPython, SQL\n"
    )
    profile = build_profile(resume)
    jd = parse_jd("Engineer at TechCo. Required: Python, SQL.")
    plan = build_resume_plan(contacts=profile.contact, jd_profile=jd, profile=profile, provider=None)
    assert any(plan.summary.rstrip().endswith(closing) for closing in SUMMARY_CLOSINGS)
    assert "Focused on shipping reliable, well-scoped work" not in plan.summary


def test_bullet_validation_is_wired_to_reject_escalation_and_first_person() -> None:
    from ats_engine.generation.planning import _bullet_is_valid

    # ownership escalation and first person must be rejected by the wired gate.
    assert (
        _bullet_is_valid(
            "Optimized the reporting pipeline for the finance team", "Built the reporting pipeline for finance", []
        )
        is True
    )
    assert (
        _bullet_is_valid(
            "I led the reporting pipeline for the finance team", "Built the reporting pipeline for finance", []
        )
        is False
    )
    assert (
        _bullet_is_valid(
            "Led the reporting pipeline for the finance department team",
            "Contributed to the reporting pipeline for finance",
            [],
        )
        is False
    )


def test_bullet_rewrite_path_still_rejects_a_fabricated_technology() -> None:
    from ats_engine.generation.planning import _bullet_is_valid

    # The shared fidelity gate (validation/fidelity.py) is now alias-aware for
    # a candidate's own spelling of a term the source already proves. That
    # must not weaken this LLM-rewrite path: a technology with no source
    # occurrence and no registered vocabulary alias to anything the candidate
    # actually wrote is still a hard rejection.
    assert (
        _bullet_is_valid(
            "Built pipelines using MongoDB for the data platform team",
            "Built pipelines for the data platform team",
            [],
        )
        is False
    )
