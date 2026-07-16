"""persist interview-preparation request option

Revision ID: 0003_add_include_interview_prep
Revises: 0002_add_include_job_fit
Create Date: 2026-07-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_add_include_interview_prep"
down_revision: str | None = "0002_add_include_job_fit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "kits",
        sa.Column("include_interview_prep", sa.Boolean(), server_default=sa.true(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("kits", "include_interview_prep")
