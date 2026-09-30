"""Expand messages for chat delivery and encrypted files.

Revision ID: 20260911_01
Revises: 20260909_02
Create Date: 2026-09-11 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260911_01"
down_revision: str | None = "20260909_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

message_content_type_enum = postgresql.ENUM(
    "text",
    "image",
    "video",
    "audio",
    "document",
    "archive",
    "code",
    "other",
    name="messagecontenttypeenum",
    create_type=False,
)

message_content_mime_type_enum = postgresql.ENUM(
    ".txt",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".svg",
    ".bmp",
    ".tiff",
    ".avif",
    ".heic",
    ".mp4",
    ".webm",
    ".avi",
    ".mov",
    ".mkv",
    ".mpeg",
    ".ogv",
    ".mp3",
    ".wav",
    ".ogg",
    ".aac",
    ".m4a",
    ".opus",
    ".flac",
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".zip",
    ".rar",
    ".tar",
    ".gz",
    ".7z",
    ".json",
    ".xml",
    ".py",
    ".js",
    ".html",
    ".css",
    ".bin",
    ".md",
    ".csv",
    name="messagecontentmimetypeenum",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    message_content_type_enum.create(bind, checkfirst=True)
    message_content_mime_type_enum.create(bind, checkfirst=True)

    op.add_column("messages", sa.Column("chat_id", sa.Uuid(), nullable=True))
    op.add_column("messages", sa.Column("reply_to_id", sa.Uuid(), nullable=True))
    op.add_column("messages", sa.Column("content", sa.Text(), nullable=True))
    op.add_column("messages", sa.Column("file_name", sa.String(length=255)))
    op.add_column("messages", sa.Column("file_content", sa.LargeBinary()))
    op.add_column("messages", sa.Column("file_size", sa.Integer()))
    op.add_column(
        "messages",
        sa.Column(
            "file_mime_type",
            message_content_mime_type_enum,
            nullable=False,
            server_default=sa.text("'.txt'::messagecontentmimetypeenum"),
        ),
    )

    op.execute("UPDATE messages SET content = message")
    op.alter_column(
        "messages",
        "content_type",
        existing_type=sa.String(),
        type_=message_content_type_enum,
        nullable=False,
        server_default=sa.text("'text'::messagecontenttypeenum"),
        postgresql_using=(
            "CASE WHEN content_type IN "
            "('text', 'image', 'video', 'audio', 'document', 'archive', "
            "'code', 'other') THEN content_type::messagecontenttypeenum "
            "ELSE 'text'::messagecontenttypeenum END"
        ),
    )
    op.alter_column(
        "messages",
        "timestamp",
        existing_type=sa.DateTime(),
        type_=sa.DateTime(timezone=True),
        postgresql_using="\"timestamp\" AT TIME ZONE 'UTC'",
    )
    op.drop_column("messages", "message")

    op.create_foreign_key(
        "fk_messages_chat_id_chats",
        "messages",
        "chats",
        ["chat_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_messages_reply_to_id_messages",
        "messages",
        "messages",
        ["reply_to_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_messages_chat_timestamp", "messages", ["chat_id", "timestamp"])
    op.create_check_constraint(
        "ck_messages_single_payload",
        "messages",
        "(content IS NOT NULL) <> (file_content IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_messages_nonnegative_file_size",
        "messages",
        "file_size IS NULL OR file_size >= 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_messages_nonnegative_file_size", "messages", type_="check")
    op.drop_constraint("ck_messages_single_payload", "messages", type_="check")
    op.drop_index("ix_messages_chat_timestamp", table_name="messages")
    op.drop_constraint(
        "fk_messages_reply_to_id_messages", "messages", type_="foreignkey"
    )
    op.drop_constraint("fk_messages_chat_id_chats", "messages", type_="foreignkey")

    op.add_column("messages", sa.Column("message", sa.String(), nullable=True))
    op.execute("UPDATE messages SET message = COALESCE(content, '')")
    op.alter_column("messages", "message", nullable=False)
    op.alter_column(
        "messages",
        "content_type",
        existing_type=message_content_type_enum,
        type_=sa.String(),
        nullable=True,
        server_default=None,
        postgresql_using="content_type::text",
    )
    op.alter_column(
        "messages",
        "timestamp",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.DateTime(),
        postgresql_using="\"timestamp\" AT TIME ZONE 'UTC'",
    )
    op.drop_column("messages", "file_mime_type")
    op.drop_column("messages", "file_size")
    op.drop_column("messages", "file_content")
    op.drop_column("messages", "file_name")
    op.drop_column("messages", "content")
    op.drop_column("messages", "reply_to_id")
    op.drop_column("messages", "chat_id")

    bind = op.get_bind()
    message_content_mime_type_enum.drop(bind, checkfirst=True)
    message_content_type_enum.drop(bind, checkfirst=True)
