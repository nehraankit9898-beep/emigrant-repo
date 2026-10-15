"""Database — SQLite default, Postgres bhi chal jayega (DATABASE_URL badal do)."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import BASE_DIR, settings


class Base(DeclarativeBase):
    pass


def _engine_kwargs() -> dict:
    url = settings.database_url
    if url.startswith("sqlite"):
        # sqlite file ka folder pehle bana do
        path = url.split("///", 1)[-1]
        if path and path != ":memory:":
            db_path = Path(path)
            if not db_path.is_absolute():
                db_path = BASE_DIR / path
            db_path.parent.mkdir(parents=True, exist_ok=True)
        return {"connect_args": {"check_same_thread": False}}
    return {"pool_pre_ping": True}


engine = create_engine(settings.database_url, future=True, **_engine_kwargs())
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


@contextmanager
def session_scope() -> Iterator[Session]:
    """`with session_scope() as db:` — commit/rollback apne aap."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _column_default_sql(column) -> str:
    """Model ke Python default ko SQL DEFAULT me badlo (purani rows ke liye)."""
    default = column.default
    if default is None or not getattr(default, "is_scalar", False):
        return ""
    value = default.arg
    if isinstance(value, bool):
        return " DEFAULT 1" if value else " DEFAULT 0"
    if isinstance(value, (int, float)):
        return f" DEFAULT {value}"
    if isinstance(value, str):
        return " DEFAULT '" + value.replace("'", "''") + "'"
    return ""


def add_missing_columns() -> list[str]:
    """Sirf *naye* columns add karo jo model me hain par DB me nahi (dev/demo convenience).

    Kyun: `create_all()` naye columns ko existing table me add nahi karta. Is wajah se
    schema change ke baad purani dev DB turant "no such column" se crash ho jaati thi.
    Ye **sirf add** karta hai — koi column drop/rename/retype nahi hota (wo migrations ka kaam).

    Production me nahi chalta (schema ka maalik wahan sirf `alembic upgrade head` hai).
    """
    import sqlalchemy as sa

    inspector = sa.inspect(engine)
    existing_tables = set(inspector.get_table_names())
    added: list[str] = []
    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        db_columns = {column["name"] for column in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in db_columns:
                continue
            col_type = column.type.compile(engine.dialect)
            sql = f'ALTER TABLE {table.name} ADD COLUMN {column.name} {col_type}{_column_default_sql(column)}'
            with engine.begin() as conn:
                conn.execute(sa.text(sql))
            added.append(f"{table.name}.{column.name}")
    return added


def init_db() -> None:
    """Development/demo: schema ready karo (tables + naye columns).

    Production: schema sirf Alembic migrations se banta/badalta hai (`alembic upgrade head`).
    Yahan kuch bhi production me nahi chalta, taaki schema drift na ho.
    """
    from . import models  # noqa: F401  (models register karne ke liye)
    from .config import settings

    if settings.is_production:
        return
    Base.metadata.create_all(engine)
    added = add_missing_columns()
    if added:
        # purane orders ke liye rate derive kar lo (migration 0003 wala hi hisaab)
        _backfill_bill_rates()
        print(f"[db] naye column add hue: {', '.join(added)}")


def _backfill_bill_rates() -> None:
    """Purane orders me discount/gst rate bharo (naye column ke liye, dev DB par).

    Migration 0003 yahi kaam production me karta hai; yahan tab chalta hai jab
    `create_all` wali dev DB ko bina migrate hue upgrade kiya gaya ho.
    """
    import sqlalchemy as sa

    statements = (
        "UPDATE orders SET discount_percent = CASE WHEN subtotal > 0 AND discount_amount > 0 "
        "THEN ROUND(discount_amount / subtotal * 100, 4) ELSE 0 END "
        "WHERE discount_percent IS NULL OR discount_percent = 0",
        "UPDATE orders SET gst_percent = CASE WHEN taxable > 0 AND gst_amount > 0 "
        "THEN ROUND(gst_amount / taxable * 100, 4) ELSE 0 END "
        "WHERE gst_percent IS NULL OR gst_percent = 0",
    )
    with engine.begin() as conn:
        columns = {column["name"] for column in sa.inspect(conn).get_columns("orders")}
        if "discount_percent" not in columns:
            return
        for statement in statements:
            conn.execute(sa.text(statement))
