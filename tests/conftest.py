"""Test setup — alag test DB, mock WhatsApp, demo brain, automation off."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# app import se PEHLE env set karna zaroori hai (config isi ko padhta hai)
os.environ["DATABASE_URL"] = "sqlite:///./data/test_agent.db"
os.environ["DEMO_SEED"] = "false"
os.environ["WHATSAPP_MODE"] = "mock"
os.environ["LLM_MODE"] = "demo"
os.environ["PAYMENT_MODE"] = "mock"
os.environ["AUTOMATION_ENABLED"] = "false"
os.environ["OWNER_WHATSAPP"] = "919000000001"
os.environ["STAFF_WHATSAPP"] = "919000000002"
os.environ["GOOGLE_REVIEW_LINK"] = "https://g.page/r/test/review"

import pytest  # noqa: E402

from app import discounts, menu as menu_engine  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402


@pytest.fixture()
def db():
    """Har test ko saaf database mile."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session = SessionLocal()
    menu_engine.ensure_menu(session)
    discounts.seed_rules(session)
    session.commit()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db):
    """FastAPI TestClient — same DB par (fixture ka order zaroori hai)."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
