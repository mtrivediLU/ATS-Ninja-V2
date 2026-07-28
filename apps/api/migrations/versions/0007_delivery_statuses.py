"""Widen the portable kit status column for delivery-first lifecycle states.

Revision ID: 0007_delivery_statuses
Revises: 0006_kit_lineage_and_revision
Create Date: 2026-07-26

``Kit.status`` deliberately remains a portable string rather than a
PostgreSQL-only enum. The application enum gains ``partially_completed`` and
``needs_input_review``; this additive migration widens the existing column so
future lifecycle labels retain headroom on both PostgreSQL and SQLite.
Historical rows and values are not rewritten.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0007_delivery_statuses"
down_revision: str | None = "0006_kit_lineage_and_revision"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # ``batch_alter_table`` emits a normal ALTER COLUMN on PostgreSQL and the
    # portable table-copy sequence SQLite requires. A bare ``op.alter_column``
    # produces ``ALTER TABLE ... ALTER COLUMN ... TYPE`` on SQLite, which its
    # grammar does not support.
    with op.batch_alter_table("kits") as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=sa.String(length=20),
            type_=sa.String(length=32),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("kits") as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=sa.String(length=32),
            type_=sa.String(length=20),
            existing_nullable=False,
        )
