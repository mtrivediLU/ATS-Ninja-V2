"""Single-entry-point guard: every ATS score traces to exactly one formula.

Rather than a fragile source-text grep, this proves delegation behaviorally.
``ats_v2.py``'s ``score_resume_v2``, ``match_report.py``'s ``score_resume``,
and ``ats.py``'s structured-JD path all eventually call the same module-level
name, ``ats_engine.scoring.ats_v2.score_resume`` (a direct import of
``pramana.scoring.score_resume``) -- and because Python functions resolve
globals from their *defining* module regardless of caller, patching that one
name intercepts every one of them. Each test below sets it to return a
distinctive sentinel score and asserts the sentinel survives, completely
unmodified, out the other end. If any wrapper computed even a partial
independent contribution to the score, the sentinel would not survive.

``ats.py``'s narrow legacy-frequency fallback (used only when the JD has no
requirement-section structure at all, so the evidence resolver has nothing to
attribute evidence to regardless of formula -- see that function's docstring)
is a documented, disclosed exception, not a second formula for ordinary
input. It is asserted here to stay gated behind that narrow condition and to
keep announcing itself with a ``DeprecationWarning``.
"""

from __future__ import annotations

import pytest

from ats_engine.kit.contract import WeightedKeyword
from ats_engine.parsing.resume import build_profile
from ats_engine.pramana.contract import PramanaScore
from ats_engine.scoring import ats as ats_module
from ats_engine.scoring import ats_v2 as ats_v2_module
from ats_engine.scoring import match_report as match_report_module

_SENTINEL_SCORE = 13.37


def _sentinel_pramana_score() -> PramanaScore:
    return PramanaScore(
        score=_SENTINEL_SCORE,
        keyword_score=_SENTINEL_SCORE,
        title_alignment=0.0,
        placement_bonus=0.0,
        stuffing_penalty=0.0,
        confidence="high",
        required_coverage=1.0,
        preferred_coverage=1.0,
    )


def test_ats_v2_score_resume_v2_is_pure_delegation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ats_v2_module, "score_resume", lambda *args, **kwargs: _sentinel_pramana_score())

    result = ats_v2_module.score_resume_v2("some resume text", [], [])

    assert result.score == _SENTINEL_SCORE
    assert result.base_score == _SENTINEL_SCORE


def test_match_report_score_resume_is_pure_delegation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ats_v2_module, "score_resume", lambda *args, **kwargs: _sentinel_pramana_score())
    profile = build_profile("")
    keyword = WeightedKeyword(term="python", weight=2.0, source="required", required=True)

    result = match_report_module.score_resume("some resume text", [keyword], profile, {"python": "A"})

    assert result.score == _SENTINEL_SCORE


def test_calculate_ats_score_structured_path_is_pure_delegation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ats_v2_module, "score_resume", lambda *args, **kwargs: _sentinel_pramana_score())
    jd_text = "Required Qualifications\n- Python\n"

    result = ats_module.calculate_ats_score("I have used Python for five years.", jd_text)

    assert result["score"] == _SENTINEL_SCORE


def test_calculate_ats_score_legacy_fallback_stays_gated_and_deprecated() -> None:
    with pytest.warns(DeprecationWarning, match="legacy frequency scoring"):
        ats_module.calculate_ats_score("Python developer", "short unstructured text, no headings")
