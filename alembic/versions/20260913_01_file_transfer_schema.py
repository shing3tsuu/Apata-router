"""Create opaque resumable file transfer storage.

Revision ID: 20260913_01
Revises: 20260911_01
Create Date: 2026-09-13 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260913_01"
down_revision: str | Sequence[str] | None = "20260911_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

file_transfer_status_enum = postgresql.ENUM(
    "uploading",
    "completed",
    "delivered",
    name="filetransferstatusenum",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    file_transfer_status_enum.create(bind, checkfirst=True)

    op.create_table(
        "file_transfers",
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("upload_id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("sender_id", sa.Uuid(), nullable=False),
        sa.Column("recipient_id", sa.Uuid(), nullable=False),
        sa.Column("chat_id", sa.Uuid(), nullable=True),
        sa.Column("total_size", sa.Integer(), nullable=False),
        sa.Column("chunk_size", sa.Integer(), nullable=False),
        sa.Column("offset", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("encrypted_metadata", sa.Text(), nullable=False),
        sa.Column("ephemeral_public_key", sa.Text(), nullable=False),
        sa.Column("ephemeral_signature", sa.Text(), nullable=False),
        sa.Column(
            "status",
            file_transfer_status_enum,
            nullable=False,
            server_default="uploading",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "total_size >= 0", name="ck_file_transfers_nonnegative_size"
        ),
        sa.CheckConstraint(
            "chunk_size > 0", name="ck_file_transfers_positive_chunk_size"
        ),
        sa.CheckConstraint(
            '"offset" >= 0 AND "offset" <= total_size',
            name="ck_file_transfers_valid_offset",
        ),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recipient_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["sender_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("file_id"),
        sa.UniqueConstraint("message_id"),
        sa.UniqueConstraint("upload_id"),
    )
    op.create_index("ix_file_transfers_upload_id", "file_transfers", ["upload_id"])
    op.create_index("ix_file_transfers_message_id", "file_transfers", ["message_id"])
    op.create_index("ix_file_transfers_sender_id", "file_transfers", ["sender_id"])
    op.create_index(
        "ix_file_transfers_recipient_id", "file_transfers", ["recipient_id"]
    )
    op.create_index("ix_file_transfers_chat_id", "file_transfers", ["chat_id"])
    op.create_index(
        "ix_file_transfers_recipient_status_completed",
        "file_transfers",
        ["recipient_id", "status", "completed_at"],
    )

    op.create_table(
        "file_chunks",
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.CheckConstraint("chunk_index >= 0", name="ck_file_chunks_nonnegative_index"),
        sa.ForeignKeyConstraint(
            ["file_id"], ["file_transfers.file_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("file_id", "chunk_index"),
    )


def downgrade() -> None:
    op.drop_table("file_chunks")
    op.drop_index(
        "ix_file_transfers_recipient_status_completed",
        table_name="file_transfers",
    )
    op.drop_index("ix_file_transfers_chat_id", table_name="file_transfers")
    op.drop_index("ix_file_transfers_recipient_id", table_name="file_transfers")
    op.drop_index("ix_file_transfers_sender_id", table_name="file_transfers")
    op.drop_index("ix_file_transfers_message_id", table_name="file_transfers")
    op.drop_index("ix_file_transfers_upload_id", table_name="file_transfers")
    op.drop_table("file_transfers")
    file_transfer_status_enum.drop(op.get_bind(), checkfirst=True)
