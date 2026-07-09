from __future__ import annotations

from ats_engine.scoring.ats import calculate_ats_score, compare_scores, extract_keywords, keyword_in_text
from ats_engine.scoring.keyword_analysis import analyze_keyword_coverage


def test_extract_keywords_ranks_by_frequency_and_filters_stopwords() -> None:
    text = "Python python Python SQL sql tableau the the the and for role position"
    keywords = extract_keywords(text)
    # Most frequent real tokens first; stopwords ("the", "and", "for") and
    # recruiting boilerplate ("role", "position") removed.
    assert keywords[0] == "python"
    assert "sql" in keywords
    assert "the" not in keywords
    assert "role" not in keywords
    assert "position" not in keywords


def test_extract_keywords_is_deterministic_with_alphabetical_tiebreak() -> None:
    text = "alpha beta gamma alpha beta gamma"  # all tie at count 2
    assert extract_keywords(text) == ["alpha", "beta", "gamma"]


def test_extract_keywords_empty_text() -> None:
    assert extract_keywords("") == []


def test_calculate_ats_score_matches_and_misses() -> None:
    jd = "We need Python and SQL and Tableau experience with dashboards."
    resume = "I use Python and Tableau daily to build dashboards."
    result = calculate_ats_score(resume, jd)
    assert isinstance(result["score"], float)
    assert "python" in result["matched_keywords"]
    assert "sql" in result["missing_keywords"]
    assert result["total_keywords"] > 0


def test_calculate_ats_score_no_keywords() -> None:
    result = calculate_ats_score("resume", "")
    assert result["score"] == 0.0
    assert result["total_keywords"] == 0


def test_compare_scores_reports_improvement() -> None:
    before = {"score": 40.0}
    after = {"score": 80.0}
    comparison = compare_scores(before, after)
    assert comparison["improvement"] == 40.0
    assert comparison["improvement_pct"] == 100.0


def test_keyword_in_text_word_boundaries() -> None:
    assert keyword_in_text("I know SQL well", "sql")
    assert not keyword_in_text("nosql only here", "sql")


def test_analyze_keyword_coverage_partitions_keywords() -> None:
    analysis = analyze_keyword_coverage(
        base_resume_text="Python developer",
        tailored_resume="Python and SQL developer",
        job_keywords=["python", "sql", "rust"],
    )
    assert analysis["matched_original"] == ["python"]
    assert analysis["added_by_tailoring"] == ["sql"]
    assert analysis["still_missing"] == ["rust"]
