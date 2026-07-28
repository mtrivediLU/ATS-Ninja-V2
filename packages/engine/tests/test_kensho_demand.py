"""KENSHO Demand Model: recall, precision, and label hygiene on real postings.

A requirement that never enters the demand model cannot be prioritised,
resolved, placed, or scored -- so every downstream number is capped by this
module's recall. Equally, a *junk* requirement is not merely noise: the product
renders it to the candidate as a gap, which is how a real user was told he
lacked "modern low-code" and "BI Frameworks".

Ground truth lives in `hand_labels.toml` beside each job description. Those
labels were written and committed before any extractor change (see the fixture
commit); measuring against labels derived from the extractor's own output would
make these thresholds self-certifying.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from ats_engine.kensho.requirements import extract_requirements
from ats_engine.parsing.vocab import normalize_term

FIXTURES = Path(__file__).parent / "fixtures" / "real_extraction"
CASES = ("crowdplat_web_scraper", "latentview_bi_ai")

# The work order's thresholds.
MIN_RECALL = 0.85
MIN_PRECISION = 0.90


def _norm(value: str) -> str:
    return normalize_term(value) or value.casefold().strip()


def _labels(case: str) -> dict:
    return tomllib.loads((FIXTURES / case / "hand_labels.toml").read_text())


def _extracted(case: str) -> set[str]:
    text = (FIXTURES / case / "job_description.txt").read_text()
    return {_norm(requirement.canonical) for requirement in extract_requirements(text)}


@pytest.mark.parametrize("case", CASES)
def test_demand_recall_meets_threshold(case: str) -> None:
    truth = {_norm(item["canonical"]) for item in _labels(case)["requirements"]}
    found = _extracted(case) & truth
    recall = len(found) / len(truth)
    assert recall >= MIN_RECALL, f"{case}: recall {recall:.3f}, missing {sorted(truth - found)}"


@pytest.mark.parametrize("case", CASES)
def test_demand_precision_meets_threshold(case: str) -> None:
    truth = {_norm(item["canonical"]) for item in _labels(case)["requirements"]}
    extracted = _extracted(case)
    precision = len(extracted & truth) / len(extracted)
    assert precision >= MIN_PRECISION, f"{case}: precision {precision:.3f}, extra {sorted(extracted - truth)}"


@pytest.mark.parametrize("case", CASES)
def test_no_section_label_is_ever_a_requirement(case: str) -> None:
    """A formatting label is presentation. Its CONTENT is the requirement."""
    labels = _labels(case)["not_requirements"]
    forbidden = {_norm(value) for value in (*labels["labels"], *labels["non_skills"])}
    leaked = _extracted(case) & forbidden
    assert not leaked, f"{case}: label-shaped terms leaked into requirements: {sorted(leaked)}"


# The specific terms the work order calls out by name. These are regression
# anchors: each one was verifiably absent from the extractor's output on `main`.
@pytest.mark.parametrize(
    "term",
    ["json", "section 508", "wcag 2.1", "beautifulsoup", "scrapy", "csv", "python", "selenium", "playwright"],
)
def test_named_crowdplat_requirements_are_extracted(term: str) -> None:
    assert _norm(term) in _extracted("crowdplat_web_scraper")


@pytest.mark.parametrize(
    "term",
    [
        "llms",
        "chatgpt",
        "claude",
        "microsoft copilot",
        "data cleaning",
        "automated report generation",
        "agile",
        "data analytics",
        "narrative generation",
        "coding assistance",
        "looker",
        "sql",
    ],
)
def test_named_latentview_requirements_are_extracted(term: str) -> None:
    assert _norm(term) in _extracted("latentview_bi_ai")


def test_the_four_reported_junk_requirements_are_gone() -> None:
    """`BI Frameworks`, `AI Tooling Platforms`, `Analytical BI`, `modern low-code`.

    All four were rendered to a real user as skills he lacked.
    """
    extracted = _extracted("latentview_bi_ai")
    for junk in ("bi frameworks", "ai tooling platforms", "analytical bi", "modern low code"):
        assert _norm(junk) not in extracted


def test_a_label_that_names_a_real_skill_still_contributes_it() -> None:
    """`Advanced SQL:` is a label, but SQL is genuinely required.

    Dropping the whole label would lose the skill, so labels contribute their
    curated-vocabulary matches even though they are never mined for free text.
    """
    assert "sql" in _extracted("latentview_bi_ai")


def test_parenthetical_enumeration_expands_to_every_member() -> None:
    """`Python (BeautifulSoup, Scrapy, Selenium, or Playwright)` names five tools."""
    extracted = _extracted("crowdplat_web_scraper")
    for term in ("python", "beautifulsoup", "scrapy", "selenium", "playwright"):
        assert _norm(term) in extracted, f"{term} missing from parenthetical expansion"


def test_a_versioned_standard_does_not_also_appear_bare() -> None:
    """`WCAG 2.1` and `WCAG` are one requirement, not two."""
    extracted = _extracted("crowdplat_web_scraper")
    assert _norm("wcag 2.1") in extracted
    assert "wcag" not in extracted


def test_the_ideal_candidate_sentence_is_not_treated_as_company_boilerplate() -> None:
    """ "The ideal candidate is ..." states requirements, not company context.

    The employer-context filter is case-insensitive, so it used to swallow this
    sentence whole and discard every requirement in it.
    """
    assert _norm("data storytelling") in _extracted("latentview_bi_ai")


@pytest.mark.parametrize("case", CASES)
def test_extraction_is_deterministic(case: str) -> None:
    assert _extracted(case) == _extracted(case)


@pytest.mark.parametrize("case", CASES)
def test_extraction_never_seeds_from_a_candidate_profile(case: str) -> None:
    """The demand model takes JD text only -- no profile argument exists."""
    text = (FIXTURES / case / "job_description.txt").read_text()
    for requirement in extract_requirements(text):
        assert requirement.jd_evidence_line, "every requirement must cite the JD line it came from"
