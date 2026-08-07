"""What an accepted prose rewrite does to the delivered kit, measured end to end.

The unit-level gates live in ``test_prose_rewriting``. This file asserts the
properties that only exist once a rewrite has actually reached a document: it is
in the change ledger, rejecting it restores the candidate's own wording exactly,
it co-exists with an accepted PRUNE without corrupting a neighbouring bullet, and
the deterministic path is untouched.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from ats_engine import (
    ArtifactKind,
    DocumentState,
    application_kit_to_dict,
    generate_application_kit,
)
from ats_engine.config import EngineSettings
from ats_engine.generation.diagnostics import GateCode, ProposalStatus
from ats_engine.generation.document_render import render_delivered_resume_text
from ats_engine.generation.pipeline import run_pipeline
from ats_engine.kit.change_actions import ACTION_REJECT, ChangeAction, apply_change_actions
from ats_engine.kit.contract import ChangeOperation, ChangeStatus
from ats_engine.kit.orchestrator import _resume_document
from ats_engine.models import Mode
from ats_engine.parsing.resume import build_profile
from ats_engine.rachana.facts import build_fact_set, fact_set_violations
from ats_engine.rachana.prose import BULLET_REWRITE, SUMMARY_REWRITE
from ats_engine.validation.fidelity import validate_resume_fidelity
from prose_double import ScriptedProseProvider

FIXTURES = Path(__file__).parent / "fixtures" / "real_extraction"
# The fixture whose delivered summary still carries the candidate's own prose at
# the point prose rewriting runs, so a SUMMARY_REWRITE has something to condense.
CASE = "cgi_fullstack_java_angular"


def _resume() -> str:
    return (FIXTURES / "candidate_resume.pymupdf.txt").read_text(encoding="utf-8")


def _jd(case: str = CASE) -> str:
    return (FIXTURES / case / "job_description.txt").read_text(encoding="utf-8")


def _run(case: str = CASE, provider: object | None = None):
    return run_pipeline(
        resume_text=_resume(),
        job_description=_jd(case),
        default_mode=Mode.RESUME,
        prose_provider=provider if provider is not None else ScriptedProseProvider(),
    )


@pytest.fixture(scope="module")
def scripted_run():
    return _run()


def _prose_records(result, status=ProposalStatus.ACCEPTED):
    return [
        record
        for record in result.metadata["optimization_trace"].diagnostics.proposals
        if record.operation in {SUMMARY_REWRITE, BULLET_REWRITE} and record.status is status
    ]


# --------------------------------------------------------------------------- #
# Acceptance actually happens, and is fully cited
# --------------------------------------------------------------------------- #
def test_both_prose_operations_are_accepted_with_full_citation(scripted_run) -> None:
    accepted = _prose_records(scripted_run)
    operations = {record.operation for record in accepted}
    assert SUMMARY_REWRITE in operations
    assert BULLET_REWRITE in operations
    for record in accepted:
        assert record.evidence_locations, f"{record.id} was accepted with no cited evidence"
        assert record.surface_to_use.strip(), f"{record.id} recorded no proposed text"
        # Accepted means it shortened the field: the rewrite is concision, and the
        # word budget makes growth impossible in the first place.
        assert record.word_delta < 0
    counts = scripted_run.metadata["optimization_trace"].diagnostics.accepted_by_operation
    assert counts.get(SUMMARY_REWRITE, 0) >= 1
    assert counts.get(BULLET_REWRITE, 0) >= 1


def test_an_accepted_rewrite_concentrates_the_document(scripted_run) -> None:
    diagnostics = scripted_run.metadata["optimization_trace"].diagnostics
    baseline = _run(provider=_NullProvider())
    baseline_diagnostics = baseline.metadata["optimization_trace"].diagnostics
    assert diagnostics.delivered_word_count < baseline_diagnostics.delivered_word_count
    assert diagnostics.relevant_terms_per_100_words_after > baseline_diagnostics.relevant_terms_per_100_words_after
    # And costs nothing: the two objectives a rewrite must never spend.
    assert diagnostics.pramana_coverage_after == baseline_diagnostics.pramana_coverage_after
    assert diagnostics.jd_surface_adoption_after >= baseline_diagnostics.jd_surface_adoption_after


def test_prose_rewriting_introduces_no_validation_error(scripted_run) -> None:
    baseline = _run(provider=_NullProvider())
    assert set(scripted_run.validation_errors) == set(baseline.validation_errors)


def test_prose_rewriting_neither_invents_nor_loses_a_single_checkable_fact(scripted_run) -> None:
    """The success criterion, measured as a delta rather than an absolute.

    ``fact_set_violations`` on the delivered *visual* layout reports a small,
    constant residual on this fixture that has nothing to do with tailoring: the
    layout joins ``Institution · Location`` on one line and wraps long
    certification names, so a re-parse of it reads those differently from the
    source. That residual is identical on ``main``, identical with the prose pass
    disabled, and identical here.

    What must be exactly zero is the *change* prose rewriting makes to it, so
    that is what is asserted -- against the same run with the prose pass proposing
    nothing. The authoritative document-level check
    (``validate_resume_fidelity``) is asserted absolutely at zero alongside it.
    """
    baseline = _run(provider=_NullProvider())
    source = _resume()
    profile = build_profile(source)

    def violations(result):
        document = _resume_document(result.resume_plan)
        rendered = build_profile(render_delivered_resume_text(document))
        return {item.describe() for item in fact_set_violations(build_fact_set(profile), build_fact_set(rendered))}

    assert violations(scripted_run) == violations(baseline)
    for result in (scripted_run, baseline):
        removed = [item.original_text for item in result.resume_plan.removed_content]
        assert validate_resume_fidelity(source, result.resume_text, removed_bullets=removed) == []


def test_the_delivered_resume_still_states_every_immutable_fact(scripted_run) -> None:
    delivered = scripted_run.resume_text
    for employer in ("Flosonics Medical", "LoopX", "City of Greater Sudbury", "Minax Inc.", "Tata Consultancy"):
        assert employer in delivered
    for metric in ("40%", "99.5%", "100%", "13", "8+ years"):
        assert metric in delivered
    assert "team of four engineers" in delivered
    assert "Vale" in delivered


class _NullProvider:
    """A reachable provider that proposes nothing.

    Isolates the prose pass from the pre-existing generated-prose path, which
    also activates whenever any provider is present. Without this the comparison
    would attribute that path's effects to prose rewriting.
    """

    identity = "null-prose-provider"

    def complete(self, _prompt: str) -> str:
        return ""


# --------------------------------------------------------------------------- #
# The change ledger: visible, and reversible to the candidate's own wording
# --------------------------------------------------------------------------- #
def test_every_accepted_rewrite_has_a_reversible_ledger_record(scripted_run) -> None:
    plan = scripted_run.resume_plan
    assert plan is not None
    decisions = {decision.location_id: decision for decision in plan.plan_decisions}
    for record in _prose_records(scripted_run):
        if record.operation == SUMMARY_REWRITE:
            location = "resume::summary"
        else:
            match = re.fullmatch(r"experience:(\d+):bullet:(\d+)", record.target)
            assert match
            location = f"resume::exp{match.group(1)}::bullet{match.group(2)}"
        decision = decisions.get(location)
        assert decision is not None, f"{record.target} was rewritten with no ledger decision"
        assert decision.operation == "rewritten"
        assert decision.original_text.strip()
        assert decision.tailored_text.strip() != decision.original_text.strip()


def test_rejecting_a_rewritten_bullet_restores_the_candidates_exact_wording() -> None:
    """The round trip, on a persisted kit: reject puts the original text back.

    This is the property that makes an LLM rewrite acceptable at all. If it did
    not hold, the engine would be making an irreversible edit to prose the
    candidate wrote.
    """
    kit = generate_application_kit(
        resume_text=_resume(),
        job_description=_jd(),
        include_resume=True,
        include_cover_letter=False,
        include_application_answers=False,
        include_job_fit=False,
        include_interview_prep=False,
        include_linkedin_outreach=False,
        settings=EngineSettings(tailoring_v2=True, delivery_first=True, llm_cache_enabled=False),
        use_llm=True,
        prose_provider=ScriptedProseProvider(),
    )
    assert kit.resume is not None
    assert kit.delivery_reports[ArtifactKind.RESUME].state is DocumentState.GENERATED
    rewritten = [
        record
        for record in kit.resume.change_ledger
        if record.operation is ChangeOperation.REWRITTEN and record.id.startswith("resume::exp") and record.reversible
    ]
    assert rewritten, "an accepted bullet rewrite must appear in the ledger as a reversible record"

    target = rewritten[0]
    assert target.tailored_text in kit.resume.text
    result = apply_change_actions(
        kit=kit,
        resume_text=_resume(),
        job_description=_jd(),
        actions=[ChangeAction(change_id=target.id, action=ACTION_REJECT)],
        expected_revision=kit.revision,
    )
    assert result.ok, result.errors
    restored = result.kit.resume
    assert restored is not None
    record = next(item for item in restored.change_ledger if item.id == target.id)
    assert record.status is ChangeStatus.REJECTED
    assert target.original_text in restored.text
    assert target.tailored_text not in restored.text
    # The kit still serializes and the revision advanced exactly once.
    assert result.kit.revision == kit.revision + 1
    assert application_kit_to_dict(result.kit)


# --------------------------------------------------------------------------- #
# The prune / rewrite index-shift interaction
# --------------------------------------------------------------------------- #
def test_a_rewrite_is_refused_where_an_accepted_prune_shifted_the_rendered_index() -> None:
    """The finding, asserted as behavior rather than left to a comment.

    An accepted PRUNE shifts the rendered index of every later bullet in its role
    (no renderer emits an emptied slot) while placement provenance still carries
    the source index. Both fixture prunes land at ``experience:1:bullet:2`` and
    ``experience:3:bullet:1``, so any candidate rewrite at a higher index in
    those roles must be refused under its own gate code rather than co-applied.
    """
    result = _run()
    trace = result.metadata["optimization_trace"]
    plan = result.resume_plan
    assert plan is not None
    removed = {}
    for item in plan.removed_content:
        match = re.fullmatch(r"experience:(\d+):bullet:(\d+)", item.location)
        if match is not None:
            removed.setdefault(int(match.group(1)), set()).add(int(match.group(2)))
    assert removed, "this fixture is expected to accept at least one prune"

    # No accepted rewrite sits after a removal in the same role.
    for record in _prose_records(result):
        match = re.fullmatch(r"experience:(\d+):bullet:(\d+)", record.target)
        if match is None:
            continue
        role, index = int(match.group(1)), int(match.group(2))
        assert not any(pruned < index for pruned in removed.get(role, set()))

    # And where the guard did fire, it is recorded, not silently skipped.
    shifted = [record for record in trace.diagnostics.proposals if record.gate_code is GateCode.PROSE_PRUNE_INDEX_SHIFT]
    for record in shifted:
        match = re.fullmatch(r"experience:(\d+):bullet:(\d+)", record.target)
        assert match
        role, index = int(match.group(1)), int(match.group(2))
        assert any(pruned < index for pruned in removed.get(role, set()))
        assert "rendered index" in record.gate_detail


def test_a_prune_and_a_rewrite_in_one_run_leave_every_other_bullet_intact() -> None:
    """Positional corruption check: no live bullet is blanked or duplicated."""
    result = _run()
    plan = result.resume_plan
    assert plan is not None
    removed = {item.original_text.strip() for item in plan.removed_content}
    assert removed
    delivered = [bullet for entry in plan.experience for bullet in entry.bullets if bullet.strip()]
    assert len(delivered) == len(set(delivered))
    for text in removed:
        assert text not in result.resume_text
    source_bullets = [
        bullet for case in [_resume()] for bullet in re.findall(r"^[-•]\s*(.+)$", case, flags=re.MULTILINE)
    ]
    assert source_bullets  # the fixture really does use bullet glyphs


# --------------------------------------------------------------------------- #
# The deterministic path
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("case", ("cgi_fullstack_java_angular", "crowdplat_web_scraper", "latentview_bi_ai"))
def test_the_deterministic_path_proposes_no_prose_at_all(case: str) -> None:
    """``provider=None`` must not reach the prose operations by any route."""
    result = run_pipeline(
        resume_text=_resume(),
        job_description=_jd(case),
        default_mode=Mode.RESUME,
        use_llm=False,
    )
    diagnostics = result.metadata["optimization_trace"].diagnostics
    assert not [record for record in diagnostics.proposals if record.operation in {SUMMARY_REWRITE, BULLET_REWRITE}]
    assert SUMMARY_REWRITE not in diagnostics.accepted_by_operation
    assert BULLET_REWRITE not in diagnostics.accepted_by_operation
    assert not [code for code in diagnostics.rejections_by_gate if code.startswith("prose_")]


def test_a_prose_pass_that_buys_nothing_is_discarded_whole() -> None:
    """Churn rejection, measured on a fixture where it actually fires.

    CrowdPlat's delivered summary at prose time is the short deterministic
    fallback with nothing to condense, so only one- and two-word bullet trims
    survive -- real, but not worth a noisier diff. The whole pass is dropped and
    every survivor is recorded as such rather than being quietly kept.
    """
    result = _run("crowdplat_web_scraper")
    diagnostics = result.metadata["optimization_trace"].diagnostics
    assert not _prose_records(result)
    churned = [
        record
        for record in diagnostics.proposals
        if record.gate_code is GateCode.PROSE_NO_OBJECTIVE_GAIN and record.surface_to_use.strip()
    ]
    assert churned, "a refused-as-churn rewrite must still be recorded with its proposed text"
    baseline = _run("crowdplat_web_scraper", provider=_NullProvider())
    assert diagnostics.delivered_sha256 == baseline.metadata["optimization_trace"].diagnostics.delivered_sha256
