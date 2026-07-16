"""persist job-fit request option

Revision ID: 0002_add_include_job_fit
Revises: 0001_create_kits
Create Date: 2026-07-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_add_include_job_fit"
down_revision: str | None = "0001_create_kits"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "kits",
        sa.Column("include_job_fit", sa.Boolean(), server_default=sa.true(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("kits", "include_job_fit")
