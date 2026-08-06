"""Safety regressions for Tailoring Engine v2 source-content fallbacks."""

from __future__ import annotations

import json

import ats_engine.generation.optimizer as optimizer_module
from ats_engine.config import EngineSettings
from ats_engine.evidence.resolver import resolve_requirements
from ats_engine.generation.optimizer import optimize
from ats_engine.generation.pipeline import run_pipeline, validate_pipeline_result
from ats_engine.generation.planning import build_resume_plan
from ats_engine.kit.contract import DocumentState
from ats_engine.models import Mode, PlanDecision
from ats_engine.parsing.job_description import parse_jd
from ats_engine.parsing.resume import build_profile
from ats_engine.pramana.contract import PramanaScore

_ZERO_REQUIREMENT_RESUME = """Avery Doe
PROFESSIONAL EXPERIENCE
Cedar Labs
Analyst 2020 - 2024
- Built reporting automation for finance users, reducing monthly manual work by 30%.
"""

_ZERO_REQUIREMENT_JD = """Job Title: Generalist
Company: Example
We value curiosity.
"""


class _BulletRewritingProvider:
    """Attempts a factually equivalent-but-non-source bullet rewrite."""

    @property
    def identity(self) -> str:
        return "test-tailoring-v2-zero-requirements-bullet-rewriter"

    def complete(self, prompt: str) -> str:
        if "Rewrite each of the following resume bullets" in prompt:
            return json.dumps(["Created reporting automation for finance users, reducing monthly manual work by 30%."])
        return ""


def test_zero_requirement_v2_restores_source_bullet_and_runs_raw_fidelity_gate() -> None:
    """A no-op optimizer still protects source wording and raw source facts."""
    provider = _BulletRewritingProvider()
    result = run_pipeline(
        resume_text=_ZERO_REQUIREMENT_RESUME,
        job_description=_ZERO_REQUIREMENT_JD,
        default_mode=Mode.RESUME,
        settings=EngineSettings(tailoring_v2=True, llm_cache_enabled=False),
        use_llm=True,
        extraction_provider=provider,
        prose_provider=None,
    )

    assert result.resume_plan is not None
    assert result.resume_plan.requirements == []
    assert result.resume_plan.experience[0].bullets == [
        "Built reporting automation for finance users, reducing monthly manual work by 30%."
    ]
    assert "Created reporting automation" not in result.resume_text
    assert "Built reporting automation" in result.resume_text
    assert result.validation_errors == []

    # The final rendered-resume gate must still run when no requirements were
    # extracted.  Mutating the delivered text here isolates dispatch from the
    # optimizer and proves the raw source metric is protected on that path.
    result.resume_text = result.resume_text.replace("30%", "20%")
    errors = validate_pipeline_result(result, build_profile(_ZERO_REQUIREMENT_RESUME))

    assert "resume: fidelity: missing source metric: 30%" in errors
    assert "resume: fidelity: unsupported metric introduced: 20" in errors


def test_low_score_projection_requires_review_without_reexposing_unsafe_plan(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """An internally regressive floor is withheld honestly, never mislabeled."""
    resume_text = """Avery Doe
TECHNICAL SKILLS
Python
PROFESSIONAL EXPERIENCE
Cedar Labs
Analyst 2020 - 2024
- Built Python reports for finance users.
"""
    job_description = """Job Title: Python Analyst
Company: Example
Required qualifications:
- Python
"""
    profile = build_profile(resume_text)
    jd_profile = parse_jd(job_description, profile=profile, tailoring_v2=True)
    requirements = jd_profile.requirements
    links = resolve_requirements(requirements, profile, resume_text)
    unsafe_base_plan = build_resume_plan(
        contacts=profile.contact,
        jd_profile=jd_profile,
        profile=profile,
        provider=None,
    )
    unsafe_base_plan.summary = "Invented 10 years of Rust leadership."
    unsafe_base_plan.experience[0].bullets = ["Invented Rust reporting for a new employer."]
    unsafe_base_plan.plan_decisions = [
        PlanDecision(
            kind="bullet",
            location_id="resume::exp0::bullet0",
            original_text="Built Python reports for finance users.",
            tailored_text="Invented Rust reporting for a new employer.",
            operation="rewritten",
            reason="Unsafe provider proposal.",
            matched_keywords=["Rust"],
        )
    ]

    # optimize()'s own current_score now goes through _evaluate_plan, which
    # calls PRAMANA's score_resume directly (Step 3, so it can also derive
    # the pareto objective vector from the same pass) rather than through the
    # score_resume_v2 shim this used to patch. original is still computed via
    # score_resume_v2, which holds its own separate score_resume reference in
    # scoring/ats_v2.py and is deliberately left genuine: a real resume/JD
    # pair's real score is comfortably above the single low value forced here.
    low_score = PramanaScore(
        score=1.0,
        keyword_score=1.0,
        title_alignment=0.0,
        placement_bonus=0.0,
        stuffing_penalty=0.0,
        confidence="high",
        required_coverage=1.0,
        preferred_coverage=1.0,
    )
    monkeypatch.setattr(optimizer_module, "score_resume", lambda *args, **kwargs: low_score)

    plan, trace = optimize(profile, jd_profile, requirements, links, unsafe_base_plan)

    assert plan is not unsafe_base_plan
    assert plan.experience[0].bullets == ["Built Python reports for finance users."]
    assert "Invented" not in plan.summary
    assert all("Invented" not in decision.tailored_text for decision in plan.plan_decisions)
    assert trace.rejected_actions
    assert trace.rejected_actions[0].action == "source_content_plan"
    assert "requires review" in trace.rejected_actions[0].reason
    assert trace.delivery_state is DocumentState.NEEDS_INPUT_REVIEW
    assert "did not preserve the original ATS score" in trace.fallback_reason


def test_delivery_first_kill_switch_uses_pr21_score_only_path(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The rollout flag skips calibration and quality proposals, not just metadata."""
    resume_text = """Avery Doe
TECHNICAL SKILLS
Python
PROFESSIONAL EXPERIENCE
Cedar Labs
Analyst 2020 - 2024
- Built Python reports for finance users.
"""
    job_description = """Job Title: Python Analyst
Company: Example
Required qualifications:
- Python
"""
    profile = build_profile(resume_text)
    jd_profile = parse_jd(job_description, profile=profile, tailoring_v2=True)
    links = resolve_requirements(jd_profile.requirements, profile, resume_text)
    base_plan = build_resume_plan(
        contacts=profile.contact,
        jd_profile=jd_profile,
        profile=profile,
        provider=None,
    )

    def fail_quality_stage(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("quality stage ran")

    monkeypatch.setattr(optimizer_module, "rewrite_summary", fail_quality_stage)

    _plan, trace = optimize(
        profile,
        jd_profile,
        jd_profile.requirements,
        links,
        base_plan,
        delivery_first=False,
    )

    assert all(not action.startswith(("quality:", "ai:")) for action in trace.accepted_actions)
    assert trace.calibration_suppressed == []
