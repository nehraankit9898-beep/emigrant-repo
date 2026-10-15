"""Add audit_logs and processed_events (webhook idempotency + admin audit trail).

Non-destructive: sirf naye tables banate hain. Existing customers/orders/payments ko nahi chhuta.
Idempotent: agar dev DB me `create_all` se ye tables pehle se hain to skip karta hai.

Revision ID: 0002_audit_events
Revises: 0001_baseline
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_audit_events"
down_revision: Union[str, None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    existing = _existing_tables()
    if "audit_logs" not in existing:
        op.create_table(
            "audit_logs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("actor", sa.String(length=80), nullable=False),
            sa.Column("action", sa.String(length=60), nullable=False),
            sa.Column("target", sa.String(length=120), nullable=True),
            sa.Column("details", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_audit_logs_actor", "audit_logs", ["actor"])
        op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
        op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])
    if "processed_events" not in existing:
        op.create_table(
            "processed_events",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("provider", sa.String(length=20), nullable=False),
            sa.Column("event_key", sa.String(length=160), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("provider", "event_key", name="uq_processed_event"),
        )


def downgrade() -> None:
    existing = _existing_tables()
    if "processed_events" in existing:
        op.drop_table("processed_events")
    if "audit_logs" in existing:
        op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
        op.drop_index("ix_audit_logs_action", table_name="audit_logs")
        op.drop_index("ix_audit_logs_actor", table_name="audit_logs")
        op.drop_table("audit_logs")
