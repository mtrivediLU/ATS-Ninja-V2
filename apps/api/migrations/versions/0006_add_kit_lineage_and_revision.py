"""Add kit lineage and revision for ApplicationKit v5 change actions.

Revision ID: 0006_kit_lineage_and_revision
Revises: 0005_primary_artifact_selection
Create Date: 2026-07-24

Additive only. ``revision`` is the optimistic-concurrency counter for change
actions (default 0); ``parent_kit_id`` links a regenerated kit to its source.
Both use portable SQLAlchemy types so the same migration runs on PostgreSQL and
on the SQLite used by tests. No existing data is rewritten.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0006_kit_lineage_and_revision"
down_revision: str | None = "0005_primary_artifact_selection"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "kits",
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "kits",
        sa.Column("parent_kit_id", sa.Uuid(), nullable=True),
    )
    op.create_index("ix_kits_parent_kit_id", "kits", ["parent_kit_id"])


def downgrade() -> None:
    op.drop_index("ix_kits_parent_kit_id", table_name="kits")
    op.drop_column("kits", "parent_kit_id")
    op.drop_column("kits", "revision")
