"""Alembic migrations — fresh DB, existing DB ka data preserve, downgrade/upgrade round trip."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import sqlalchemy as sa

ROOT = Path(__file__).resolve().parent.parent


def _alembic(db_path: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{db_path.as_posix()}", "DEMO_SEED": "false"}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120
    )


def _tables(db_path: Path) -> set[str]:
    engine = sa.create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        return set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_fresh_database_upgrades_to_head(tmp_path):
    db = tmp_path / "fresh.db"
    result = _alembic(db, "upgrade", "head")
    assert result.returncode == 0, result.stderr
    tables = _tables(db)
    assert {"customers", "orders", "payments", "audit_logs", "processed_events"} <= tables


def test_existing_data_survives_upgrade_and_round_trip(tmp_path):
    db = tmp_path / "legacy.db"
    assert _alembic(db, "upgrade", "0001_baseline").returncode == 0
    engine = sa.create_engine(f"sqlite:///{db.as_posix()}")
    with engine.begin() as conn:
        # Timestamps ORM default se aate hain (DB server default nahi) — isliye raw insert me bhi dene padte hain
        conn.execute(
            sa.text(
                "INSERT INTO customers (phone, name, veg_pref, total_visits, total_orders, total_spent, loyalty_points, "
                "language, opt_in, opted_out, human_mode, blocked, first_seen_at, last_seen_at, created_at, updated_at) "
                "VALUES ('919123456789','Legacy','any',0,0,0,0,'hinglish',0,0,0,0,"
                "'2026-01-01 10:00:00','2026-01-01 10:00:00','2026-01-01 10:00:00','2026-01-01 10:00:00')"
            )
        )
    engine.dispose()

    assert _alembic(db, "upgrade", "head").returncode == 0
    assert _alembic(db, "downgrade", "0001_baseline").returncode == 0
    assert "audit_logs" not in _tables(db)
    assert _alembic(db, "upgrade", "head").returncode == 0

    engine = sa.create_engine(f"sqlite:///{db.as_posix()}")
    with engine.connect() as conn:
        names = [row[0] for row in conn.execute(sa.text("SELECT name FROM customers"))]
    engine.dispose()
    assert names == ["Legacy"], "migration ne existing customer data ko nuksan pahunchaya"


def test_bill_rate_columns_added_and_backfilled(tmp_path):
    """0003: purane orders ke liye rate hisaab se bhar jaana chahiye (bill galat na ho)."""
    db = tmp_path / "rates.db"
    assert _alembic(db, "upgrade", "0002_audit_events").returncode == 0

    engine = sa.create_engine(f"sqlite:///{db.as_posix()}")
    with engine.begin() as conn:
        # purana order: ₹560 ka bill, 10% discount (₹56), 5% GST on ₹504 = ₹25.20
        conn.execute(
            sa.text(
                "INSERT INTO orders (order_no, customer_phone, items, subtotal, discount_amount, "
                "discount_code, packaging, delivery, taxable, gst_amount, total_amount, "
                "payment_status, order_status, channel, feedback_asked, "
                "created_at, updated_at) VALUES "
                "('1001','919000000009','[]',560.0,56.0,'WELCOME10',0,0,504.0,25.2,529.2,"
                "'pending','awaiting_payment','whatsapp',0,"
                "'2026-10-01 10:00:00','2026-10-01 10:00:00')"
            )
        )
    engine.dispose()

    assert _alembic(db, "upgrade", "head").returncode == 0

    engine = sa.create_engine(f"sqlite:///{db.as_posix()}")
    with engine.connect() as conn:
        row = conn.execute(
            sa.text("SELECT discount_percent, gst_percent, total_amount FROM orders WHERE order_no='1001'")
        ).one()
    engine.dispose()
    assert abs(row[0] - 10.0) < 0.001, f"discount_percent backfill galat: {row[0]}"
    assert abs(row[1] - 5.0) < 0.001, f"gst_percent backfill galat: {row[1]}"
    assert abs(row[2] - 529.2) < 0.01, "migration se order ka total nahi badalna chahiye"


def test_bill_rate_columns_survive_downgrade_upgrade(tmp_path):
    db = tmp_path / "roundtrip.db"
    assert _alembic(db, "upgrade", "head").returncode == 0
    assert _alembic(db, "downgrade", "0002_audit_events").returncode == 0

    engine = sa.create_engine(f"sqlite:///{db.as_posix()}")
    columns = {column["name"] for column in sa.inspect(engine).get_columns("orders")}
    engine.dispose()
    assert "discount_percent" not in columns
    assert "gst_percent" not in columns

    # wapas upar jaane par column dobara ban jaane chahiye
    assert _alembic(db, "upgrade", "head").returncode == 0
    engine = sa.create_engine(f"sqlite:///{db.as_posix()}")
    columns = {column["name"] for column in sa.inspect(engine).get_columns("orders")}
    engine.dispose()
    assert {"discount_percent", "gst_percent"} <= columns
