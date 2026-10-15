"""Shared security helpers — token compare, audit log, webhook idempotency.

Sab sensitive cheezein (token, secret, phone) yahin se handle hoti hain taaki
kahin aur galti na ho.
"""

from __future__ import annotations

import hmac
import re

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import AuditLog, ProcessedEvent

_SECRET_KEYS = re.compile(r"(token|secret|password|key|signature|authorization)", re.IGNORECASE)


def constant_time_equals(provided: str | None, expected: str | None) -> bool:
    """Timing attack se bachne ke liye token compare. Khaali expected = hamesha False."""
    if not provided or not expected:
        return False
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


def redact(details: dict | None) -> dict | None:
    """Audit/log details se secret-like keys hata do."""
    if not details:
        return details
    return {k: ("[redacted]" if _SECRET_KEYS.search(str(k)) else v) for k, v in details.items()}


def audit(db: Session, actor: str, action: str, target: str | None = None, details: dict | None = None) -> AuditLog:
    """Sensitive action ka record. Same transaction me save hota hai (action ke saath hi)."""
    row = AuditLog(actor=actor[:80], action=action[:60], target=(target or None) and str(target)[:120], details=redact(details))
    db.add(row)
    db.flush()
    return row


def claim_event(db: Session, provider: str, event_key: str) -> bool:
    """True = ye event pehli baar aaya (process karo). False = duplicate (skip karo).

    Unique constraint ki wajah se concurrent duplicates bhi safe hain: doosra insert fail hota hai.
    """
    if not event_key:
        return True  # id nahi hai to dedupe possible nahi — caller ko decide karne do
    exists = db.scalar(
        select(ProcessedEvent.id).where(ProcessedEvent.provider == provider, ProcessedEvent.event_key == event_key)
    )
    if exists:
        return False
    try:
        with db.begin_nested():
            db.add(ProcessedEvent(provider=provider, event_key=event_key[:160]))
            db.flush()
    except IntegrityError:
        return False
    return True
