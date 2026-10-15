"""Store the discount/GST rate that was applied on each order.

Non-destructive: sirf do naye (nullable) columns jodte hain, koi row delete/rewrite nahi hota.
Idempotent: dev DB me `create_all` se column pehle se hai to skip kar dete hain.

Kyun zaroori tha: bill dobara banate waqt (`bill` intent, `resend-link`, pending payment)
sirf `order.items` se `build_bill()` call ho raha tha — discount/gst hat jaate the, jisse
customer ko asli total se zyada amount dikhta tha (paid hone ke baad bhi).

Revision ID: 0003_order_bill_rates
Revises: 0002_audit_events
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_order_bill_rates"
down_revision: Union[str, None] = "0002_audit_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_COLUMNS = (
    ("discount_percent", 0.0),
    ("gst_percent", 0.0),
)


def _existing_columns() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if "orders" not in set(inspector.get_table_names()):
        return set()
    return {column["name"] for column in inspector.get_columns("orders")}


def upgrade() -> None:
    existing = _existing_columns()
    for name, _default in NEW_COLUMNS:
        if name in existing:
            continue
        # server_default ke saath add karte hain (existing rows ke liye), phir backfill,
        # phir server_default hata dete hain — schema model jaisa (NOT NULL) rahe.
        with op.batch_alter_table("orders", schema=None) as batch_op:
            batch_op.add_column(sa.Column(name, sa.Float(), nullable=False, server_default="0"))
        # purane orders ka rate hisaab se nikal kar bhar dete hain, warna unka bill
        # dobara banate waqt discount hat jaata (wahi bug jiske liye ye column hai).
        if name == "discount_percent":
            op.execute(
                sa.text(
                    "UPDATE orders SET discount_percent = "
                    "CASE WHEN subtotal > 0 AND discount_amount > 0 "
                    "     THEN ROUND(discount_amount / subtotal * 100, 4) ELSE 0 END"
                )
            )
        else:
            op.execute(
                sa.text(
                    "UPDATE orders SET gst_percent = "
                    "CASE WHEN taxable > 0 AND gst_amount > 0 "
                    "     THEN ROUND(gst_amount / taxable * 100, 4) ELSE 0 END"
                )
            )
        with op.batch_alter_table("orders", schema=None) as batch_op:
            batch_op.alter_column(name, server_default=None)


def downgrade() -> None:
    existing = _existing_columns()
    for name, _default in NEW_COLUMNS:
        if name not in existing:
            continue
        with op.batch_alter_table("orders", schema=None) as batch_op:
            batch_op.drop_column(name)
