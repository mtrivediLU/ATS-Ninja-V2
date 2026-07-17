"""Add independently persisted primary artifact selection.

Revision ID: 0005_primary_artifact_selection
Revises: 0004_linkedin_outreach
Create Date: 2026-07-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0005_primary_artifact_selection"
down_revision: str | None = "0004_linkedin_outreach"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "kits",
        sa.Column("include_resume", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.add_column(
        "kits",
        sa.Column("include_cover_letter", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "kits",
        sa.Column("include_application_answers", sa.Boolean(), server_default=sa.false(), nullable=False),
    )

    # Preserve the legacy mode behavior for existing rows. Questions took
    # precedence over requested prose in the old detector; with the API's
    # required JD, a non-empty questions field meant resume + answers.
    op.execute(sa.text("UPDATE kits SET include_application_answers = true WHERE length(trim(questions_text)) > 0"))
    op.execute(
        sa.text(
            "UPDATE kits SET include_cover_letter = true "
            "WHERE length(trim(questions_text)) = 0 AND ("
            "lower(requested_mode) LIKE '%cover%' OR lower(requested_mode) = 'cv' OR "
            "lower(requested_mode) LIKE 'cv %' OR lower(requested_mode) LIKE '% cv' OR "
            "lower(requested_mode) LIKE '%both%')"
        )
    )
    op.execute(
        sa.text(
            "UPDATE kits SET include_resume = false "
            "WHERE length(trim(questions_text)) = 0 "
            "AND include_cover_letter = true "
            "AND lower(requested_mode) NOT LIKE '%resume%' "
            "AND lower(requested_mode) NOT LIKE '%both%'"
        )
    )


def downgrade() -> None:
    op.drop_column("kits", "include_application_answers")
    op.drop_column("kits", "include_cover_letter")
    op.drop_column("kits", "include_resume")
