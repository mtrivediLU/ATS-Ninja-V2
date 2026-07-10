from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from celery.exceptions import Retry
from sqlalchemy.exc import InterfaceError, OperationalError

import app.tasks as tasks
from app.queue import CeleryJobQueue, QueueUnavailableError

"""Celery-backed queue + task tests.

These verify the transport swap in isolation (no Postgres/Redis): the dispatcher
sends only the kit id, and the task body classifies failures and retries
correctly. The real worker→engine happy path (process_kit → the real
deterministic ats_engine) is covered unmocked in test_kits.py.
"""


# --------------------------------------------------------------------------
# Dispatcher: CeleryJobQueue sends only the kit id, by task name.
# --------------------------------------------------------------------------


async def test_celery_queue_dispatches_only_kit_id() -> None:
    fake_celery = MagicMock()
    queue = CeleryJobQueue(fake_celery)
    kit_id = uuid.uuid4()

    await queue.enqueue_kit(kit_id)

    fake_celery.send_task.assert_called_once_with("generate_kit", args=[str(kit_id)])
    # The payload is exactly one positional arg: the stringified kit id. No
    # resume text, JD text, bytes, or result payload crosses the broker.
    _name, kwargs = fake_celery.send_task.call_args
    assert kwargs["args"] == [str(kit_id)]
    assert all(str(kit_id) == a for a in kwargs["args"])


async def test_celery_queue_raises_queue_unavailable_on_broker_error() -> None:
    fake_celery = MagicMock()
    fake_celery.send_task.side_effect = ConnectionError("redis down")
    queue = CeleryJobQueue(fake_celery)

    with pytest.raises(QueueUnavailableError):
        await queue.enqueue_kit(uuid.uuid4())


# --------------------------------------------------------------------------
# Failure classification and backoff (pure functions).
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc",
    [
        OperationalError("SELECT 1", None, Exception("db down")),
        InterfaceError("SELECT 1", None, Exception("bad conn")),
        ConnectionError("broker down"),
        TimeoutError("timed out"),
        OSError("socket error"),
    ],
)
def test_transient_errors_are_classified_transient(exc: BaseException) -> None:
    assert tasks.is_transient_error(exc) is True


@pytest.mark.parametrize(
    "exc",
    [
        ValueError("invalid input"),
        TypeError("bad type"),
        KeyError("missing"),
        RuntimeError("permanent engine failure"),
    ],
)
def test_non_transient_errors_are_not_retried(exc: BaseException) -> None:
    assert tasks.is_transient_error(exc) is False


def test_retry_backoff_is_bounded_and_increasing() -> None:
    values = [tasks.retry_countdown(i) for i in range(8)]
    assert values[:4] == [10, 20, 40, 80]
    assert all(a <= b for a, b in zip(values, values[1:], strict=False))
    assert max(values) <= 300  # capped


# --------------------------------------------------------------------------
# Task body orchestration: success / transient-retry / exhausted / permanent.
# --------------------------------------------------------------------------


def _fake_task(retries: int = 0, max_retries: int = 3) -> SimpleNamespace:
    def retry(*, exc: BaseException, countdown: int) -> Retry:
        raise Retry(exc=exc, when=countdown)

    return SimpleNamespace(request=SimpleNamespace(retries=retries), max_retries=max_retries, retry=retry)


def test_task_body_success_does_not_fail_or_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    process = MagicMock()
    fail = MagicMock()
    monkeypatch.setattr(tasks, "_process", process)
    monkeypatch.setattr(tasks, "_fail", fail)

    kit_id = uuid.uuid4()
    tasks._generate_kit_body(_fake_task(), str(kit_id))

    process.assert_called_once_with(kit_id)
    fail.assert_not_called()


def test_task_body_retries_transient_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tasks, "_process", MagicMock(side_effect=OperationalError("s", None, Exception("db"))))
    fail = MagicMock()
    monkeypatch.setattr(tasks, "_fail", fail)

    # Retries remaining -> the task requests a retry (raises Retry) and does NOT fail the kit.
    with pytest.raises(Retry):
        tasks._generate_kit_body(_fake_task(retries=0, max_retries=3), str(uuid.uuid4()))
    fail.assert_not_called()


def test_task_body_fails_kit_when_transient_retries_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tasks, "_process", MagicMock(side_effect=OperationalError("s", None, Exception("db"))))
    fail = MagicMock()
    monkeypatch.setattr(tasks, "_fail", fail)

    kit_id = uuid.uuid4()
    # retries == max_retries -> no more retries; the kit is marked failed instead.
    tasks._generate_kit_body(_fake_task(retries=3, max_retries=3), str(kit_id))

    fail.assert_called_once()
    assert fail.call_args.args[0] == kit_id


def test_task_body_does_not_retry_permanent_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tasks, "_process", MagicMock(side_effect=ValueError("invalid input")))
    fail = MagicMock()
    monkeypatch.setattr(tasks, "_fail", fail)

    kit_id = uuid.uuid4()
    # Non-transient failure: mark failed, never retry.
    tasks._generate_kit_body(_fake_task(retries=0, max_retries=3), str(kit_id))

    fail.assert_called_once()
    assert fail.call_args.args[0] == kit_id
