from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from sqlalchemy import String

from app.models import Kit


def _run_alembic(database_path: Path, *arguments: str) -> None:
    api_root = Path(__file__).parents[1]
    env = os.environ.copy()
    env["ATS_API_DATABASE_URL"] = f"sqlite+aiosqlite:///{database_path}"
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", *arguments],
        cwd=api_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, f"{completed.stdout}\n{completed.stderr}"


def _status_declared_type(database_path: Path) -> str:
    with sqlite3.connect(database_path) as connection:
        columns = connection.execute("PRAGMA table_info(kits)").fetchall()
    return next(str(column[2]) for column in columns if column[1] == "status")


def _statuses(database_path: Path) -> list[str]:
    with sqlite3.connect(database_path) as connection:
        rows = connection.execute("SELECT status FROM kits ORDER BY status").fetchall()
    return [str(row[0]) for row in rows]


def test_delivery_status_migration_runs_up_down_on_real_sqlite_and_preserves_rows(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "delivery-statuses.db"
    _run_alembic(database_path, "upgrade", "0006_kit_lineage_and_revision")
    assert _status_declared_type(database_path) == "VARCHAR(20)"

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "INSERT INTO kits (id, status, resume_text, job_description, requested_mode, questions_text) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("00000000000000000000000000000001", "completed", "synthetic", "synthetic", "", ""),
        )
        connection.commit()

    _run_alembic(database_path, "upgrade", "head")
    assert _status_declared_type(database_path) == "VARCHAR(32)"
    assert _statuses(database_path) == ["completed"]

    with sqlite3.connect(database_path) as connection:
        connection.executemany(
            "INSERT INTO kits (id, status, resume_text, job_description, requested_mode, questions_text) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    "00000000000000000000000000000002",
                    "needs_input_review",
                    "synthetic",
                    "synthetic",
                    "",
                    "",
                ),
                (
                    "00000000000000000000000000000003",
                    "partially_completed",
                    "synthetic",
                    "synthetic",
                    "",
                    "",
                ),
            ],
        )
        connection.commit()

    _run_alembic(database_path, "downgrade", "0006_kit_lineage_and_revision")
    assert _status_declared_type(database_path) == "VARCHAR(20)"
    assert _statuses(database_path) == ["completed", "needs_input_review", "partially_completed"]

    _run_alembic(database_path, "upgrade", "head")
    assert _status_declared_type(database_path) == "VARCHAR(32)"
    assert _statuses(database_path) == ["completed", "needs_input_review", "partially_completed"]


def test_delivery_status_model_uses_32_character_portable_string() -> None:
    status_type = Kit.__table__.c.status.type
    assert isinstance(status_type, String)
    assert status_type.length == 32
