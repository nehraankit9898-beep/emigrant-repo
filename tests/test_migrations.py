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
