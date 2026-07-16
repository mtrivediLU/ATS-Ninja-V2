"""Add reproducible LinkedIn outreach request options.

Revision ID: 0004_linkedin_outreach
Revises: 0003_add_include_interview_prep
Create Date: 2026-07-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0004_linkedin_outreach"
down_revision: str | None = "0003_add_include_interview_prep"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "kits",
        sa.Column("include_linkedin_outreach", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.add_column("kits", sa.Column("outreach_context", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("kits", "outreach_context")
    op.drop_column("kits", "include_linkedin_outreach")
