"""Align contact requests with the contact domain model.

Revision ID: 20260905_01
Revises: 20260903_01
Create Date: 2026-09-05 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260905_01"
down_revision: str | None = "20260903_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

contact_status_enum = postgresql.ENUM(
    "blank",
    "pending",
    "accepted",
    "blacklist",
    name="contactstatusenum",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    contact_status_enum.create(bind, checkfirst=True)

    op.execute(
        """
        UPDATE contact_requests
        SET status = 'pending'
        WHERE status IN ('pending(incoming)', 'pending(outgoing)')
        """
    )
    op.alter_column(
        "contact_requests",
        "status",
        existing_type=sa.String(),
        type_=contact_status_enum,
        postgresql_using="status::text::contactstatusenum",
        existing_nullable=False,
    )
    op.alter_column(
        "contact_requests",
        "status",
        server_default=sa.text("'blank'::contactstatusenum"),
    )
    op.alter_column(
        "contact_requests",
        "created_at",
        existing_type=sa.DateTime(),
        type_=sa.DateTime(timezone=True),
        postgresql_using="created_at AT TIME ZONE 'UTC'",
        existing_nullable=False,
    )
    op.create_check_constraint(
        "ck_contact_requests_different_users",
        "contact_requests",
        "sender_id <> receiver_id",
    )
    op.drop_index("ix_unique_request", table_name="contact_requests")
    op.create_index(
        "uq_contact_requests_pair",
        "contact_requests",
        [
            sa.text("LEAST(sender_id, receiver_id)"),
            sa.text("GREATEST(sender_id, receiver_id)"),
        ],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_contact_requests_pair", table_name="contact_requests")
    op.create_index(
        "ix_unique_request",
        "contact_requests",
        ["sender_id", "receiver_id"],
        unique=True,
    )
    op.drop_constraint(
        "ck_contact_requests_different_users",
        "contact_requests",
        type_="check",
    )
    op.alter_column(
        "contact_requests",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.DateTime(),
        postgresql_using="created_at AT TIME ZONE 'UTC'",
        existing_nullable=False,
    )
    op.alter_column("contact_requests", "status", server_default=None)
    op.alter_column(
        "contact_requests",
        "status",
        existing_type=contact_status_enum,
        type_=sa.String(),
        postgresql_using="status::text",
        existing_nullable=False,
    )
    contact_status_enum.drop(op.get_bind(), checkfirst=True)
