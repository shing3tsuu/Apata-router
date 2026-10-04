"""Add logical identities for fan-out chat messages.

Revision ID: 20261004_01
Revises: 20261001_01
Create Date: 2026-10-04 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261004_01"
down_revision: str | Sequence[str] | None = "20261001_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("logical_message_id", sa.Uuid(), nullable=True),
    )
    op.execute("UPDATE messages SET logical_message_id = id")
    op.alter_column("messages", "logical_message_id", nullable=False)
    op.create_index(
        "ix_messages_logical_message_id",
        "messages",
        ["logical_message_id"],
    )
    op.create_index(
        "ix_messages_chat_logical_message",
        "messages",
        ["chat_id", "logical_message_id"],
    )
    op.create_unique_constraint(
        "uq_messages_logical_recipient",
        "messages",
        ["sender_id", "logical_message_id", "recipient_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_messages_logical_recipient",
        "messages",
        type_="unique",
    )
    op.drop_index("ix_messages_chat_logical_message", table_name="messages")
    op.drop_index("ix_messages_logical_message_id", table_name="messages")
    op.drop_column("messages", "logical_message_id")
