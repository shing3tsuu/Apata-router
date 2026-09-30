"""Store who invited each active chat participant.

Revision ID: 20260909_02
Revises: 20260909_01
Create Date: 2026-09-09 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260909_02"
down_revision: str | None = "20260909_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chat_participants",
        sa.Column("invited_by_user_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_chat_participants_invited_by_user_id_users",
        "chat_participants",
        "users",
        ["invited_by_user_id"],
        ["id"],
    )
    op.create_index(
        "ix_chat_participants_invited_by_user_id",
        "chat_participants",
        ["invited_by_user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_chat_participants_invited_by_user_id",
        table_name="chat_participants",
    )
    op.drop_constraint(
        "fk_chat_participants_invited_by_user_id_users",
        "chat_participants",
        type_="foreignkey",
    )
    op.drop_column("chat_participants", "invited_by_user_id")
