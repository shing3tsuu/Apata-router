"""Create the initial router schema.

Revision ID: 20260903_01
Revises:
Create Date: 2026-09-03 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260903_01"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.String(length=50), nullable=False),
        sa.Column("ed_public_key", sa.Text(), nullable=True),
        sa.Column("ecdh_public_key", sa.Text(), nullable=True),
        sa.Column("ecdh_signature", sa.Text(), nullable=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("online", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)

    op.create_table(
        "contact_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sender_id", sa.Uuid(), nullable=False),
        sa.Column("receiver_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["receiver_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["sender_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_unique_request",
        "contact_requests",
        ["sender_id", "receiver_id"],
        unique=True,
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sender_id", sa.Uuid(), nullable=False),
        sa.Column("recipient_id", sa.Uuid(), nullable=False),
        sa.Column("message", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=True),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("is_delivered", sa.Boolean(), nullable=False),
        sa.Column("ephemeral_public_key", sa.String(), nullable=False),
        sa.Column("ephemeral_signature", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["recipient_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["sender_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_messages_timestamp", "messages", ["timestamp"])
    op.create_index("ix_messages_is_delivered", "messages", ["is_delivered"])
    op.create_index(
        "ix_messages_recipient_delivered",
        "messages",
        ["recipient_id", "is_delivered"],
    )
    op.create_index(
        "ix_messages_sender_timestamp", "messages", ["sender_id", "timestamp"]
    )
    op.create_index(
        "ix_messages_recipient_timestamp", "messages", ["recipient_id", "timestamp"]
    )


def downgrade() -> None:
    op.drop_index("ix_messages_recipient_timestamp", table_name="messages")
    op.drop_index("ix_messages_sender_timestamp", table_name="messages")
    op.drop_index("ix_messages_recipient_delivered", table_name="messages")
    op.drop_index("ix_messages_is_delivered", table_name="messages")
    op.drop_index("ix_messages_timestamp", table_name="messages")
    op.drop_table("messages")

    op.drop_index("ix_unique_request", table_name="contact_requests")
    op.drop_table("contact_requests")

    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")
