"""Chhote-chhote helper functions — phone, paisa, time, text."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))


# ------------------------------------------------------------------ phone
def clean_phone(raw: str, default_country: str = "91") -> str:
    """'98XXXXXXXX', '+91 98XXX XXXXX', 'whatsapp:+9198...' -> '9198XXXXXXXX'."""
    if not raw:
        return ""
    digits = re.sub(r"\D", "", str(raw))
    if not digits:
        return ""
    if len(digits) == 10:  # bina country code
        return default_country + digits
    if digits.startswith("0") and len(digits) == 11:
        return default_country + digits[1:]
    return digits


def pretty_phone(phone: str) -> str:
    """'919876543210' -> '+91 98765 43210'."""
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 12 and digits.startswith("91"):
        return f"+91 {digits[2:7]} {digits[7:]}"
    return f"+{digits}" if digits else ""


# ------------------------------------------------------------------ money
def rupees(amount: float, with_symbol: bool = True) -> str:
    """Rs. 648 (no decimals when round, warna 2 decimal)."""
    amount = float(amount or 0)
    if abs(amount - round(amount)) < 0.005:
        text = f"{int(round(amount)):,}"
    else:
        text = f"{amount:,.2f}"
    return f"₹{text}" if with_symbol else text


def money(amount: float) -> float:
    """2 decimal par round (float jhamela se bacho)."""
    return round(float(amount or 0) + 1e-9, 2)


# ------------------------------------------------------------------ time
def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def now_ist() -> datetime:
    return datetime.now(IST).replace(tzinfo=None)


def to_iso_utc(dt: datetime | None) -> str | None:
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def today_ist_date() -> date:
    return now_ist().date()


def days_between(a: datetime | None, b: datetime | None) -> int:
    if not a or not b:
        return 0
    return abs((b.date() - a.date()).days)


def ist_day_bounds_utc(day: date | None = None) -> tuple[datetime, datetime]:
    """IST ka ek din -> UTC ki range (report/analytics ke liye)."""
    day = day or today_ist_date()
    start_ist = datetime.combine(day, datetime.min.time())
    end_ist = start_ist + timedelta(days=1)
    start_utc = (start_ist - timedelta(hours=5, minutes=30))
    end_utc = (end_ist - timedelta(hours=5, minutes=30))
    return start_utc, end_utc


# ------------------------------------------------------------------ text
_HINGLISH_WORDS = {
    "kya", "kaise", "kaisa", "hai", "haan", "nahi", "nahin", "bhai", "bhaiya", "ji", "menu",
    "karo", "kar", "do", "dena", "dijiye", "chahiye", "acha", "achha", "theek", "thik", "kitna",
    "kitne", "paise", "paisa", "bhejo", "bhej", "aaj", "kal", "abhi", "mai", "main", "mera",
    "meri", "aap", "aapka", "namaste", "swagat", "order", "bill", "table", "baje", "bajay",
    "log", "banda", "khana", "khaana", "pani", "paani", "swad", "swaad", "garam", "thanda",
    "maza", "mazaa", "kuch", "koi", "wala", "wali", "yeh", "ye", "wo", "woh", "acha", "bhook",
    "bhuk", "khao", "khila", "milna", "milta", "lagega", "lagta", "lagi", "raha", "rahi",
    "gaya", "gayi", "hoga", "hogi", "krna", "karna", "de", "deejiye", "le", "lo", "lena",
    "batao", "bataye", "dikhao", "dikha", "sunao", "kr", "krdo", "kardo", "ho", "na",
    "bhi", "to", "toh", "se", "ko", "ka", "ki", "ke", "me", "mein", "par", "pe", "ek", "dusra",
    "kitni", "jyada", "zyada", "kam", "special", "aajka", "offer", "shukriya", "dhanyavad",
}
_ENGLISH_WORDS = {
    "hi", "hello", "hey", "menu", "order", "bill", "table", "book", "reserve", "thanks",
    "thank", "you", "please", "price", "cost", "how", "much", "what", "when", "yes", "no",
    "ok", "okay", "delivery", "address", "today", "tomorrow", "available", "veg", "non",
    "food", "review", "points", "loyalty", "stop", "start", "pay", "payment",
}
_DEVANAGARI = re.compile(r"[\u0900-\u097F]")


def detect_language(text: str) -> str:
    """hi (Devanagari) | hinglish (Hindi words latin me) | en | hinglish default."""
    if not text:
        return "hinglish"
    if _DEVANAGARI.search(text):
        return "hi"
    words = set(re.findall(r"[a-z]+", text.lower()))
    shared = {"menu", "order", "bill", "table", "price", "special", "offer", "offers", "points", "review", "today", "tomorrow"}
    hinglish_hits = len((words - shared) & _HINGLISH_WORDS)
    english_hits = len((words - shared) & _ENGLISH_WORDS)
    if hinglish_hits >= 2 or (hinglish_hits >= 1 and english_hits == 0 and len(words) <= 6):
        return "hinglish"
    if english_hits >= 2 and hinglish_hits == 0:
        return "en"
    return "hinglish"


def title_name(raw: str | None) -> str | None:
    """'rahul sharma' -> 'Rahul Sharma' (naam sundar karo)."""
    if not raw:
        return None
    cleaned = re.sub(r"\s+", " ", str(raw)).strip()
    if not cleaned or len(cleaned) > 60:
        return None
    if _DEVANAGARI.search(cleaned):
        return cleaned
    return " ".join(part[:1].upper() + part[1:] for part in cleaned.split(" "))


def truncate(text: str, size: int = 120) -> str:
    text = (text or "").strip()
    return text if len(text) <= size else text[: size - 1].rstrip() + "…"


def mask_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    return f"{digits[:2]}XXXX{digits[-3:]}" if len(digits) > 6 else digits
