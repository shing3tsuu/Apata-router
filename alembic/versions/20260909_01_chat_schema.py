"""Create chat, membership, and chat event tables.

Revision ID: 20260909_01
Revises: 20260905_01
Create Date: 2026-09-09 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260909_01"
down_revision: str | None = "20260905_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

chat_event_type_enum = postgresql.ENUM(
    "created",
    "member_added",
    "member_joined",
    "member_left",
    "member_removed",
    "name_changed",
    name="chateventtypeenum",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    chat_event_type_enum.create(bind, checkfirst=True)

    op.create_table(
        "chats",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_chats_nonempty_name"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chats_owner_id", "chats", ["owner_id"])

    op.create_table(
        "chat_participants",
        sa.Column("chat_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("chat_id", "user_id"),
    )
    op.create_index("ix_chat_participants_user_id", "chat_participants", ["user_id"])

    op.create_table(
        "chat_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("chat_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("target_user_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", chat_event_type_enum, nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chat_events_chat_timestamp",
        "chat_events",
        ["chat_id", "timestamp"],
    )


def downgrade() -> None:
    op.drop_index("ix_chat_events_chat_timestamp", table_name="chat_events")
    op.drop_table("chat_events")

    op.drop_index("ix_chat_participants_user_id", table_name="chat_participants")
    op.drop_table("chat_participants")

    op.drop_index("ix_chats_owner_id", table_name="chats")
    op.drop_table("chats")

    chat_event_type_enum.drop(op.get_bind(), checkfirst=True)
