"""Backfill blank contacts for existing message participants.

Revision ID: 20260925_01
Revises: 20260913_01
Create Date: 2026-09-25 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260925_01"
down_revision: str | Sequence[str] | None = "20260913_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            WITH missing_pairs AS (
                SELECT DISTINCT ON (
                    LEAST(message.sender_id, message.recipient_id),
                    GREATEST(message.sender_id, message.recipient_id)
                )
                    message.sender_id,
                    message.recipient_id,
                    message.timestamp
                FROM messages AS message
                WHERE message.sender_id <> message.recipient_id
                  AND NOT EXISTS (
                      SELECT 1
                      FROM contact_requests AS contact
                      WHERE (
                          contact.sender_id = message.sender_id
                          AND contact.receiver_id = message.recipient_id
                      ) OR (
                          contact.sender_id = message.recipient_id
                          AND contact.receiver_id = message.sender_id
                      )
                  )
                ORDER BY
                    LEAST(message.sender_id, message.recipient_id),
                    GREATEST(message.sender_id, message.recipient_id),
                    message.timestamp,
                    message.id
            )
            INSERT INTO contact_requests (
                id,
                sender_id,
                receiver_id,
                status,
                created_at
            )
            SELECT
                gen_random_uuid(),
                missing_pair.sender_id,
                missing_pair.recipient_id,
                'blank'::contactstatusenum,
                missing_pair.timestamp
            FROM missing_pairs AS missing_pair
            ON CONFLICT DO NOTHING
            """
        )
    )


def downgrade() -> None:
    # Backfilled contacts are indistinguishable from contacts created by the
    # application, so removing them during downgrade would destroy user data.
    pass
