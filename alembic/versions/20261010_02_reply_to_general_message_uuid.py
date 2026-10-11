"""Persist the logical target of chat replies.

Revision ID: 20261010_02
Revises: 20261010_01
Create Date: 2026-10-10 00:00:01
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261010_02"
down_revision: str | Sequence[str] | None = "20261010_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("reply_to_general_message_uuid", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "ix_messages_reply_to_general_message_uuid",
        "messages",
        ["reply_to_general_message_uuid"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_messages_reply_to_general_message_uuid",
        table_name="messages",
    )
    op.drop_column("messages", "reply_to_general_message_uuid")
