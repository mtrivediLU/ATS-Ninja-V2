"""PRAMANA entity extraction: who is hiring, and for what.

Both facts were wrong on real postings before this change. CrowdPlat's
employer came out as `APIs and JSON` -- a fragment of a requirements bullet --
on a posting whose first lines read `Client Name: CrowdPlat`. LatentView's came
out as `Generative AI`, with the title reduced to the placeholder
`Target Role`, even though the posting opens "We are seeking a forward-thinking
Analytical BI & AI to lead" and closes "At LatentView Analytics, we value...".

A wrong company is not cosmetic: it is written into the cover letter, the
outreach draft, and the filename the candidate sends to a recruiter.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ats_engine.parsing.job_description import parse_jd
from ats_engine.parsing.resume import build_profile
from ats_engine.pramana.entities import _extract_company, _is_valid_company_candidate

FIXTURES = Path(__file__).parent / "fixtures" / "real_extraction"

EXPECTED = {
    "crowdplat_web_scraper": ("CrowdPlat", "Web Scraper / Data Extraction Specialist"),
    "latentview_bi_ai": ("LatentView Analytics", "Analytical BI & AI"),
}


@pytest.fixture(scope="module")
def profile():
    return build_profile((FIXTURES / "candidate_resume.pymupdf.txt").read_text())


def _jd(case: str, profile):
    return parse_jd((FIXTURES / case / "job_description.txt").read_text(), profile)


@pytest.mark.parametrize("case", sorted(EXPECTED))
def test_company_is_the_real_employer(case: str, profile) -> None:
    assert _jd(case, profile).company == EXPECTED[case][0]


@pytest.mark.parametrize("case", sorted(EXPECTED))
def test_title_is_the_real_role(case: str, profile) -> None:
    assert _jd(case, profile).title == EXPECTED[case][1]


def test_client_name_label_is_honoured(profile) -> None:
    """Staffing postings name the end client with a `Client Name:` label."""
    assert _jd("crowdplat_web_scraper", profile).company == "CrowdPlat"


def test_a_bracketed_engagement_note_is_not_part_of_the_company_name(profile) -> None:
    """The source line reads `Client Name: CrowdPlat (Internal Role)`."""
    company = _jd("crowdplat_web_scraper", profile).company
    assert "Internal Role" not in company
    assert company == "CrowdPlat"


def test_equal_opportunity_paragraph_names_the_employer(profile) -> None:
    """JD hygiene strips the EEO paragraph, but it names the company.

    Stripping it for scoring is correct; losing the employer with it is not.
    """
    assert _jd("latentview_bi_ai", profile).company == "LatentView Analytics"


def test_an_announced_title_without_a_role_noun_is_still_recovered(profile) -> None:
    """`Analytical BI & AI` contains no engineer/analyst/manager token.

    A title stated outright by the posting is the title regardless, and
    rejecting it produced the `Target Role` placeholder.
    """
    title = _jd("latentview_bi_ai", profile).title
    assert title == "Analytical BI & AI"
    assert title != "Target Role"


# Values observed being accepted as employers before this change, plus the
# generic shapes the work order requires be rejected.
@pytest.mark.parametrize(
    "candidate",
    [
        "APIs and JSON",
        "Generative AI",
        "Remote",
        "Hybrid",
        "On-site",
        "Full-time",
        "Part-Time",
        "Contract",
        "Python and SQL",
        "Toronto, ON",
    ],
)
def test_negative_corpus_is_never_a_company(candidate: str) -> None:
    assert not _is_valid_company_candidate(candidate, "Data Engineer")


def test_company_extraction_prefers_an_explicit_label_over_a_guess() -> None:
    """Priority order matters: a label beats a repeated proper noun."""
    text = "Client Name: Northwind Robotics\nWe build Kubernetes tooling. Kubernetes is central to Kubernetes work.\n"
    company = _extract_company(text, text.splitlines(), "Data Engineer", _hygiene(text), source_text=text)
    assert company == "Northwind Robotics"


def _hygiene(text: str):
    from ats_engine.pramana.requirements import sanitize_jd_for_parsing

    return sanitize_jd_for_parsing(text)


@pytest.mark.parametrize("case", sorted(EXPECTED))
def test_entity_extraction_is_deterministic(case: str, profile) -> None:
    assert (_jd(case, profile).company, _jd(case, profile).title) == EXPECTED[case]
