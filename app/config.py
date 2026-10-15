"""Config — saari settings ek jagah (.env se aati hain).

Report ka Section 18 yaad rakho: *Access Token ko code me likh ke GitHub par
mat daalo* — isliye har key yahan env se read hoti hai, code me kabhi nahi.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _s(key: str, default: str = "") -> str:
    value = os.getenv(key)
    return default if value is None or value == "" else value.strip().strip('"')


def _b(key: str, default: bool = False) -> bool:
    raw = os.getenv(key)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "haan", "y", "on"}


def _i(key: str, default: int) -> int:
    try:
        return int(float(_s(key, str(default))))
    except ValueError:
        return default


def _f(key: str, default: float) -> float:
    try:
        return float(_s(key, str(default)))
    except ValueError:
        return default


@dataclass
class Settings:
    # ---- restaurant ----
    restaurant_name: str = field(default_factory=lambda: _s("RESTAURANT_NAME", "Sharma Cafe"))
    restaurant_city: str = field(default_factory=lambda: _s("RESTAURANT_CITY", "Jaipur"))
    restaurant_tagline: str = field(default_factory=lambda: _s("RESTAURANT_TAGLINE", "Ghar jaisa swaad, dost jaisa andaaz"))
    restaurant_address: str = field(default_factory=lambda: _s("RESTAURANT_ADDRESS", "12, MI Road, Jaipur"))
    restaurant_phone: str = field(default_factory=lambda: _s("RESTAURANT_PHONE", "+919876543210"))
    restaurant_email: str = field(default_factory=lambda: _s("RESTAURANT_EMAIL", "hello@sharmacafe.in"))
    restaurant_hours: str = field(default_factory=lambda: _s("RESTAURANT_HOURS", "11:00 AM - 11:00 PM (Daily)"))
    google_review_link: str = field(default_factory=lambda: _s("GOOGLE_REVIEW_LINK", ""))
    owner_whatsapp: str = field(default_factory=lambda: _s("OWNER_WHATSAPP", "919876543210"))
    staff_whatsapp: str = field(default_factory=lambda: _s("STAFF_WHATSAPP", "919876543211"))

    # ---- agent ----
    agent_name: str = field(default_factory=lambda: _s("AGENT_NAME", "Bablu"))
    agent_persona_extra: str = field(default_factory=lambda: _s("AGENT_PERSONA_EXTRA", ""))

    # ---- money ----
    gst_percent: float = field(default_factory=lambda: _f("GST_PERCENT", 5.0))
    packaging_charge: float = field(default_factory=lambda: _f("PACKAGING_CHARGE", 0.0))
    delivery_charge: float = field(default_factory=lambda: _f("DELIVERY_CHARGE", 0.0))
    currency: str = field(default_factory=lambda: _s("CURRENCY", "INR"))
    max_discount_percent: float = field(default_factory=lambda: _f("MAX_DISCOUNT_PERCENT", 25.0))
    loyalty_points_per_100: int = field(default_factory=lambda: _i("LOYALTY_POINTS_PER_100", 10))
    free_coffee_points: int = field(default_factory=lambda: _i("FREE_COFFEE_POINTS", 500))

    # ---- whatsapp ----
    whatsapp_mode: str = field(default_factory=lambda: _s("WHATSAPP_MODE", "mock").lower())
    whatsapp_phone_number_id: str = field(default_factory=lambda: _s("WHATSAPP_PHONE_NUMBER_ID"))
    whatsapp_token: str = field(default_factory=lambda: _s("WHATSAPP_TOKEN"))
    whatsapp_verify_token: str = field(default_factory=lambda: _s("WHATSAPP_VERIFY_TOKEN", "sharma-cafe-verify-2026"))
    whatsapp_app_secret: str = field(default_factory=lambda: _s("WHATSAPP_APP_SECRET"))
    whatsapp_api_version: str = field(default_factory=lambda: _s("WHATSAPP_API_VERSION", "v21.0"))

    # ---- llm ----
    llm_mode: str = field(default_factory=lambda: _s("LLM_MODE", "demo").lower())
    llm_provider: str = field(default_factory=lambda: _s("LLM_PROVIDER", "openai").lower())
    llm_api_key: str = field(default_factory=lambda: _s("LLM_API_KEY"))
    llm_model: str = field(default_factory=lambda: _s("LLM_MODEL", "gpt-4o-mini"))
    llm_base_url: str = field(default_factory=lambda: _s("LLM_BASE_URL"))
    llm_temperature: float = field(default_factory=lambda: _f("LLM_TEMPERATURE", 0.7))
    llm_max_tokens: int = field(default_factory=lambda: _i("LLM_MAX_TOKENS", 350))

    # ---- payment ----
    payment_mode: str = field(default_factory=lambda: _s("PAYMENT_MODE", "mock").lower())
    razorpay_key_id: str = field(default_factory=lambda: _s("RAZORPAY_KEY_ID"))
    razorpay_key_secret: str = field(default_factory=lambda: _s("RAZORPAY_KEY_SECRET"))
    razorpay_webhook_secret: str = field(default_factory=lambda: _s("RAZORPAY_WEBHOOK_SECRET"))
    upi_id: str = field(default_factory=lambda: _s("UPI_ID", "sharmacafe@upi"))

    # ---- infra ----
    database_url: str = field(default_factory=lambda: _s("DATABASE_URL", "sqlite:///./data/sharma_cafe.db"))
    automation_enabled: bool = field(default_factory=lambda: _b("AUTOMATION_ENABLED", True))
    owner_report_time: str = field(default_factory=lambda: _s("OWNER_REPORT_TIME", "23:00"))
    birthday_time: str = field(default_factory=lambda: _s("BIRTHDAY_TIME", "09:00"))
    winback_days: int = field(default_factory=lambda: _i("WINBACK_DAYS", 30))
    reservation_reminder_minutes: int = field(default_factory=lambda: _i("RESERVATION_REMINDER_MINUTES", 60))
    max_proactive_per_day: int = field(default_factory=lambda: _i("MAX_PROACTIVE_PER_DAY", 200))
    admin_token: str = field(default_factory=lambda: _s("ADMIN_TOKEN", ""))
    public_base_url: str = field(default_factory=lambda: _s("PUBLIC_BASE_URL", "").rstrip("/"))
    port: int = field(default_factory=lambda: _i("PORT", 8000))
    demo_seed: bool = field(default_factory=lambda: _b("DEMO_SEED", True))

    # ---- derived helpers ----
    @property
    def whatsapp_live(self) -> bool:
        return self.whatsapp_mode == "live" and bool(self.whatsapp_token and self.whatsapp_phone_number_id)

    @property
    def payment_live(self) -> bool:
        return self.payment_mode == "live" and bool(self.razorpay_key_id and self.razorpay_key_secret)

    @property
    def llm_live(self) -> bool:
        if self.llm_mode != "auth":
            return False
        if self.llm_provider == "ollama":
            return True
        return bool(self.llm_api_key)

    @property
    def llm_endpoint(self) -> str:
        if self.llm_base_url:
            return self.llm_base_url.rstrip("/")
        return {
            "openai": "https://api.openai.com/v1",
            "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
            "groq": "https://api.groq.com/openai/v1",
            "ollama": "http://localhost:11434/v1",
        }.get(self.llm_provider, "https://api.openai.com/v1")

    def mode_report(self) -> dict:
        """Dashboard banner ke liye — kya asli hai, kya demo hai."""
        return {
            "whatsapp": self.whatsapp_mode if self.whatsapp_live else "mock",
            "whatsapp_live": self.whatsapp_live,
            "llm": "live" if self.llm_live else "demo",
            "llm_live": self.llm_live,
            "llm_model": self.llm_model if self.llm_live else "built-in Hinglish brain",
            "payment": "live" if self.payment_live else "mock",
            "payment_live": self.payment_live,
            "database": self.database_url.split("://", 1)[0],
            "gst_percent": self.gst_percent,
            "automation_enabled": self.automation_enabled,
        }


settings = Settings()
