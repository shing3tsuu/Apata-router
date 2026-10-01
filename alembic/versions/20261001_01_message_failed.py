"""Track recipient-side message decryption failures.

Revision ID: 20261001_01
Revises: 20260927_01
Create Date: 2026-10-01 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261001_01"
down_revision: str | Sequence[str] | None = "20260927_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("failed", sa.Boolean(), nullable=True),
    )
    op.create_check_constraint(
        "ck_messages_failed_requires_delivery",
        "messages",
        "failed IS NULL OR is_delivered",
    )
    op.create_index(
        "ix_messages_sender_failed",
        "messages",
        ["sender_id", "failed"],
    )


def downgrade() -> None:
    op.drop_index("ix_messages_sender_failed", table_name="messages")
    op.drop_constraint(
        "ck_messages_failed_requires_delivery",
        "messages",
        type_="check",
    )
    op.drop_column("messages", "failed")
