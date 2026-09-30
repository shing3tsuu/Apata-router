"""Preserve chat membership history after a participant leaves.

Revision ID: 20260927_01
Revises: 20260925_01
Create Date: 2026-09-27 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260927_01"
down_revision: str | Sequence[str] | None = "20260925_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chat_participants",
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chat_participants", "left_at")
