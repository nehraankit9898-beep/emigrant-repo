"""Production configuration guardrails; no network or real secrets are used."""

from app.config import Settings


def _set_valid_production_env(monkeypatch):
    values = {
        "APP_ENV": "production",
        "DEMO_SEED": "false",
        "ADMIN_TOKEN": "x" * 32,
        "DATABASE_URL": "postgresql+psycopg://user:pass@db.example.invalid/app?sslmode=require",
        "WHATSAPP_MODE": "live",
        "WHATSAPP_TOKEN": "test-whatsapp-token",
        "WHATSAPP_PHONE_NUMBER_ID": "test-phone-number-id",
        "WHATSAPP_APP_SECRET": "test-app-secret",
        "WHATSAPP_VERIFY_TOKEN": "v" * 32,
        "PAYMENT_MODE": "live",
        "RAZORPAY_KEY_ID": "test-key-id",
        "RAZORPAY_KEY_SECRET": "test-key-secret",
        "RAZORPAY_WEBHOOK_SECRET": "test-webhook-secret",
        "PUBLIC_BASE_URL": "https://example.invalid",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def test_postgres_connection_uri_selects_installed_psycopg_driver(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://user:pass@ep-example-pooler.neon.tech/app?sslmode=require",
    )
    assert Settings().database_url == (
        "postgresql+psycopg://user:pass@ep-example-pooler.neon.tech/app?sslmode=require"
    )


def test_demo_seed_defaults_off_in_production_but_on_in_development(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("DEMO_SEED", raising=False)
    assert Settings().demo_seed is False

    monkeypatch.setenv("APP_ENV", "development")
    assert Settings().demo_seed is True


def test_complete_production_configuration_passes_without_connecting(monkeypatch):
    _set_valid_production_env(monkeypatch)
    assert Settings().production_problems() == []


def test_production_rejects_demo_seeding_and_incomplete_live_credentials(monkeypatch):
    _set_valid_production_env(monkeypatch)
    monkeypatch.setenv("DEMO_SEED", "true")
    problems = Settings().production_problems()
    assert any("DEMO_SEED=false" in problem for problem in problems)

    monkeypatch.setenv("DEMO_SEED", "false")
    monkeypatch.delenv("RAZORPAY_KEY_SECRET")
    problems = Settings().production_problems()
    assert any(
        "RAZORPAY_KEY_ID" in problem and "RAZORPAY_KEY_SECRET" in problem
        for problem in problems
    )
