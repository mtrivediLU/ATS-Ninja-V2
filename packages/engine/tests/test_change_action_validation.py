from __future__ import annotations

import copy

from ats_engine.kit.change_actions import ChangeAction, apply_change_actions
from ats_engine.kit.contract import ChangeStatus, ChangeType
from ats_engine.kit.orchestrator import generate_application_kit
from conftest import SYNTHETIC_JD, SYNTHETIC_RESUME

"""Defect 4 & 5: change actions must run the same authoritative validation as
initial generation, and refuse (atomically, without mutation) any batch that
would leave an unusable or incomplete artifact.
"""


def _kit_with_cover():  # type: ignore[no-untyped-def]
    return generate_application_kit(
        resume_text=SYNTHETIC_RESUME,
        job_description=SYNTHETIC_JD,
        use_llm=False,
        include_resume=True,
        include_cover_letter=True,
    )


def _cover_paragraph_ids(kit) -> list[str]:  # type: ignore[no-untyped-def]
    return [
        r.id
        for r in kit.cover_letter.change_ledger
        if r.change_type is ChangeType.COVER_LETTER_PARAGRAPH and r.reversible
    ]


def test_rejecting_most_cover_paragraphs_is_refused_and_leaves_kit_unchanged() -> None:
    kit = _kit_with_cover()
    before = copy.deepcopy(kit)
    ids = _cover_paragraph_ids(kit)
    assert len(ids) >= 3
    # Reject all but one paragraph: the resulting letter is far too short to use.
    result = apply_change_actions(
        kit=kit,
        resume_text=SYNTHETIC_RESUME,
        job_description=SYNTHETIC_JD,
        actions=[ChangeAction(cid, "reject") for cid in ids[:-1]],
        expected_revision=0,
    )
    assert not result.ok
    assert result.errors
    # Atomic: nothing persisted. Revision, text, and ledger statuses unchanged.
    assert result.kit.revision == 0
    assert result.kit.cover_letter.text == before.cover_letter.text
    assert result.kit.cover_letter.document.body_paragraphs == before.cover_letter.document.body_paragraphs
    for record in result.kit.cover_letter.change_ledger:
        assert record.status is ChangeStatus.PROPOSED


def test_rejecting_every_cover_paragraph_is_refused() -> None:
    kit = _kit_with_cover()
    ids = _cover_paragraph_ids(kit)
    result = apply_change_actions(
        kit=kit,
        resume_text=SYNTHETIC_RESUME,
        job_description=SYNTHETIC_JD,
        actions=[ChangeAction(cid, "reject") for cid in ids],
        expected_revision=0,
    )
    assert not result.ok
    assert result.kit.revision == 0
    assert result.kit.cover_letter.validation.fatal is False  # original, untouched


def test_valid_smaller_cover_change_is_accepted() -> None:
    kit = _kit_with_cover()
    ids = _cover_paragraph_ids(kit)
    # Rejecting a single paragraph keeps the letter usable.
    result = apply_change_actions(
        kit=kit,
        resume_text=SYNTHETIC_RESUME,
        job_description=SYNTHETIC_JD,
        actions=[ChangeAction(ids[0], "reject")],
        expected_revision=0,
    )
    assert result.ok
    assert result.kit.revision == 1
    assert result.kit.cover_letter.validation.fatal is False
    body_words = sum(len(p.split()) for p in result.kit.cover_letter.document.body_paragraphs)
    assert body_words >= 100


def test_resume_completeness_holds_after_actions() -> None:
    kit = generate_application_kit(
        resume_text=SYNTHETIC_RESUME, job_description=SYNTHETIC_JD, use_llm=False, include_resume=True
    )
    # Reject a bullet: the candidate original is restored, so no fact is lost.
    bullet = next(r for r in kit.resume.change_ledger if r.change_type is ChangeType.BULLET and r.reversible)
    result = apply_change_actions(
        kit=kit,
        resume_text=SYNTHETIC_RESUME,
        job_description=SYNTHETIC_JD,
        actions=[ChangeAction(bullet.id, "reject")],
        expected_revision=0,
    )
    assert result.ok
    assert result.kit.resume.validation.fatal is False
    for error in result.kit.resume.validation.errors:
        assert "completeness" not in error.lower(), error


def test_failed_action_does_not_mutate_the_in_memory_kit() -> None:
    kit = _kit_with_cover()
    original_paragraphs = list(kit.cover_letter.document.body_paragraphs)
    original_text = kit.cover_letter.text
    ids = _cover_paragraph_ids(kit)
    result = apply_change_actions(
        kit=kit,
        resume_text=SYNTHETIC_RESUME,
        job_description=SYNTHETIC_JD,
        actions=[ChangeAction(cid, "reject") for cid in ids],
        expected_revision=0,
    )
    assert not result.ok
    # The very object passed in must be byte-for-byte unchanged.
    assert kit.cover_letter.document.body_paragraphs == original_paragraphs
    assert kit.cover_letter.text == original_text
    assert kit.revision == 0
    assert all(r.status is ChangeStatus.PROPOSED for r in kit.cover_letter.change_ledger)


def test_empty_action_batch_does_not_advance_the_revision() -> None:
    kit = generate_application_kit(
        resume_text=SYNTHETIC_RESUME, job_description=SYNTHETIC_JD, use_llm=False, include_resume=True
    )
    text_before = kit.resume.text
    result = apply_change_actions(
        kit=kit,
        resume_text=SYNTHETIC_RESUME,
        job_description=SYNTHETIC_JD,
        actions=[],
        expected_revision=0,
    )
    assert result.ok
    assert result.kit.revision == 0
    assert result.kit.resume.text == text_before


def test_duplicate_change_id_in_one_batch_is_refused() -> None:
    kit = generate_application_kit(
        resume_text=SYNTHETIC_RESUME, job_description=SYNTHETIC_JD, use_llm=False, include_resume=True
    )
    result = apply_change_actions(
        kit=kit,
        resume_text=SYNTHETIC_RESUME,
        job_description=SYNTHETIC_JD,
        actions=[ChangeAction("resume::summary", "accept"), ChangeAction("resume::summary", "reject")],
        expected_revision=0,
    )
    assert not result.ok
    assert any("Duplicate change id" in e for e in result.errors)
    assert result.kit.revision == 0


def test_claim_links_are_consistent_after_a_successful_action() -> None:
    kit = generate_application_kit(
        resume_text=SYNTHETIC_RESUME, job_description=SYNTHETIC_JD, use_llm=False, include_resume=True
    )
    result = apply_change_actions(
        kit=kit,
        resume_text=SYNTHETIC_RESUME,
        job_description=SYNTHETIC_JD,
        actions=[ChangeAction("resume::summary", "accept")],
        expected_revision=0,
    )
    assert result.ok
    resume = result.kit.resume
    claim_ids = {c.id for c in resume.claims}
    # No grounding-removal ledger record may point at a claim that no longer exists.
    for record in resume.change_ledger:
        for linked in record.linked_claim_ids:
            assert linked in claim_ids, f"dangling linked_claim_id {linked}"
