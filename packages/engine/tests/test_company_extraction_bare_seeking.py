"""§5: bare "X is seeking" / "X is looking for" / "Join X" company forms.

Before this, only "The X is seeking" resolved deterministically. The real
CGI posting says "CGI is seeking..." -- no leading "The" -- and fell through
to the weakest of the five company-resolution mechanisms (a repeated-
proper-noun heuristic that would mis-fire on any other frequently-repeated
capitalized word in the posting). It happened to still land on the right
answer for CGI specifically, but not because the JD's explicit statement was
recognised.
"""

from __future__ import annotations

from pathlib import Path

from ats_engine.parsing.job_description import parse_jd

_REQUIRED_TAIL = "\nRequired Qualifications\n- Python\n"


def test_real_cgi_posting_resolves_via_the_bare_is_seeking_statement() -> None:
    jd = (
        Path(__file__).parent / "fixtures" / "real_extraction" / "cgi_fullstack_java_angular" / "job_description.txt"
    ).read_text()
    assert parse_jd(jd).company == "CGI"


def test_bare_is_seeking_without_a_leading_the() -> None:
    jd = "Nimbus Systems is seeking a Backend Developer." + _REQUIRED_TAIL
    assert parse_jd(jd).company == "Nimbus Systems"


def test_bare_is_looking_for() -> None:
    jd = "CloudWorks Inc is looking for a Backend Developer to join our team." + _REQUIRED_TAIL
    assert parse_jd(jd).company == "CloudWorks Inc"


def test_join_x_form() -> None:
    jd = "Join Bright Analytics as a Backend Developer today!" + _REQUIRED_TAIL
    assert parse_jd(jd).company == "Bright Analytics"


def test_generic_join_our_team_is_never_mistaken_for_a_company_name() -> None:
    """ "Join X" must not fire on generic invitational prose with no real name."""
    jd = "Join our team to build the future of fintech." + _REQUIRED_TAIL
    assert parse_jd(jd).company == "Target Company"


def test_join_us_is_never_mistaken_for_a_company_name() -> None:
    """Regression for a real bug hit while building this: under
    ``re.IGNORECASE``, ``[A-Z]`` in the capture group matches a lowercase
    letter too, which let an earlier version of this pattern capture "us" out
    of "Join us in building the future." as if it were a company name."""
    jd = "Join us in building the future." + _REQUIRED_TAIL
    assert parse_jd(jd).company == "Target Company"
