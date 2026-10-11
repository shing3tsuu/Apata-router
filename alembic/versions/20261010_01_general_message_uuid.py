"""Rename the shared fan-out message identity.

Revision ID: 20261010_01
Revises: 20261004_01
Create Date: 2026-10-10 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261010_01"
down_revision: str | Sequence[str] | None = "20261004_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_messages_logical_recipient",
        "messages",
        type_="unique",
    )
    op.drop_index("ix_messages_chat_logical_message", table_name="messages")
    op.drop_index("ix_messages_logical_message_id", table_name="messages")
    op.alter_column(
        "messages",
        "logical_message_id",
        new_column_name="general_message_uuid",
        existing_type=sa.Uuid(),
        nullable=True,
    )
    op.execute("UPDATE messages SET general_message_uuid = NULL WHERE chat_id IS NULL")
    op.create_check_constraint(
        "ck_messages_general_uuid_matches_chat",
        "messages",
        "(chat_id IS NULL) = (general_message_uuid IS NULL)",
    )
    op.create_index(
        "ix_messages_general_message_uuid",
        "messages",
        ["general_message_uuid"],
    )
    op.create_index(
        "ix_messages_chat_general_message",
        "messages",
        ["chat_id", "general_message_uuid"],
    )
    op.create_unique_constraint(
        "uq_messages_general_recipient",
        "messages",
        ["recipient_id", "chat_id", "general_message_uuid"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_messages_general_recipient",
        "messages",
        type_="unique",
    )
    op.drop_index("ix_messages_chat_general_message", table_name="messages")
    op.drop_index("ix_messages_general_message_uuid", table_name="messages")
    op.drop_constraint(
        "ck_messages_general_uuid_matches_chat",
        "messages",
        type_="check",
    )
    op.execute(
        "UPDATE messages SET general_message_uuid = id "
        "WHERE general_message_uuid IS NULL"
    )
    op.alter_column(
        "messages",
        "general_message_uuid",
        new_column_name="logical_message_id",
        existing_type=sa.Uuid(),
        nullable=False,
    )
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
