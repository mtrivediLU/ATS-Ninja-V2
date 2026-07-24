from __future__ import annotations

from ats_engine.generation.pipeline import run_pipeline, validate_pipeline_result
from ats_engine.validation.naturalness import production_naturalness_warnings
from conftest import SYNTHETIC_JD, SYNTHETIC_RESUME

"""Defect 5: the authoritative naturalness / anti-stuffing / JD-echo gate is
actually wired into the production validation path, not merely exercised by
isolated helper tests.
"""


def test_production_gate_flags_stuffing_and_jd_echo() -> None:
    job_description = "we need someone to build reliable data pipelines for our customers every single day"
    text = "python " * 12 + "\n\n" + "build reliable data pipelines for our customers every single day"
    warnings = production_naturalness_warnings(
        text=text,
        units=["python " * 12, "build reliable data pipelines for our customers every single day"],
        keywords=["python"],
        job_description=job_description,
    )
    assert any("stuffing" in w for w in warnings)
    assert any("jd-echo" in w for w in warnings)


def test_production_gate_is_silent_on_clean_prose() -> None:
    warnings = production_naturalness_warnings(
        text="Built Python services and REST APIs for a analytics platform.",
        units=["Built Python services and REST APIs for a analytics platform."],
        keywords=["python", "rest apis"],
        job_description="We are hiring a backend engineer to build services.",
    )
    assert warnings == []


def test_real_generated_kit_has_no_spurious_stuffing_warnings() -> None:
    # A legitimately generated resume/cover letter must not trip the gate.
    result = run_pipeline(
        resume_text=SYNTHETIC_RESUME,
        job_description=SYNTHETIC_JD,
        requested_mode="resume and cover letter",
        use_llm=False,
    )
    stuffing = [e for e in result.validation_errors if "stuffing" in e or "jd-echo" in e]
    assert stuffing == [], stuffing


def test_pipeline_validation_detects_a_verbatim_jd_echo() -> None:
    # Wire check: an injected verbatim run of the JD in the delivered resume text
    # is caught by the pipeline's validation (the gate runs in production).
    result = run_pipeline(
        resume_text=SYNTHETIC_RESUME,
        job_description=SYNTHETIC_JD,
        requested_mode="resume",
        use_llm=False,
    )
    echo = " ".join(SYNTHETIC_JD.split()[:12])
    result.resume_text = f"{result.resume_text}\n{echo}"
    errors = validate_pipeline_result(result)
    assert any("jd-echo" in e for e in errors), errors
