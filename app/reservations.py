"""Table reservations — time parsing, overlap-aware capacity check.

Rule: kisi bhi `reservation_window_minutes` (default 90) ki window me confirmed bookings ke
seats ka jod `reservation_max_seats` (default 24) se zyada nahi hona chahiye. Window ka
matlab: do booking ka time gap window se kam ho to dono ek hi "slot" me maani jaati hain.

Postgres par capacity check se pehle advisory lock lagta hai (concurrent bookings serialize).
SQLite me single-writer lock already ye kaam karta hai (local/dev).
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .config import settings
from .models import Reservation
from .utils import today_ist_date

_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
MAX_PARTY_SIZE = 40


class ReservationError(ValueError):
    """Booking valid nahi (date/time/persons)."""


class CapacityError(ReservationError):
    """Us time window me seats nahi bache."""


def normalize_time(value: str | None) -> str:
    raw = (value or "").strip()
    match = _TIME_RE.match(raw)
    if not match:
        raise ReservationError("time HH:MM format me hona chahiye (jaise 19:30)")
    return f"{int(match.group(1)):02d}:{match.group(2)}"


def parse_date(value: str | None, today: date) -> date:
    try:
        day = date.fromisoformat(value or str(today))
    except ValueError as exc:
        raise ReservationError("date YYYY-MM-DD format me hona chahiye") from exc
    if day < today:
        raise ReservationError("beeti hui date par booking nahi ho sakti")
    if day > today + timedelta(days=365):
        raise ReservationError("365 din se zyada aage ki booking allowed nahi hai")
    return day


def parse_persons(value, default: int = 2) -> int:
    try:
        persons = int(value if value not in (None, "") else default)
    except (TypeError, ValueError) as exc:
        raise ReservationError("persons number hona chahiye") from exc
    if not 1 <= persons <= MAX_PARTY_SIZE:
        raise ReservationError(f"persons 1 se {MAX_PARTY_SIZE} ke beech hone chahiye")
    return persons


def _minutes(hhmm: str) -> int:
    hour, minute = hhmm.split(":")
    return int(hour) * 60 + int(minute)


def _lock_day(db: Session, day: date) -> None:
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": day.toordinal()})


def seats_in_window(db: Session, day: date, time_str: str, window_minutes: int | None = None) -> int:
    window = window_minutes if window_minutes is not None else settings.reservation_window_minutes
    target = _minutes(time_str)
    rows = db.scalars(select(Reservation).where(Reservation.date == day, Reservation.status == "confirmed"))
    total = 0
    for row in rows:
        try:
            if abs(_minutes(row.time) - target) < window:
                total += int(row.persons or 0)
        except (ValueError, AttributeError):
            continue
    return total


def check_capacity(db: Session, day: date, time_str: str, persons: int) -> None:
    """Raise CapacityError agar booking se capacity cross hoti hai. Commit se pehle call karo."""
    _lock_day(db, day)
    taken = seats_in_window(db, day, time_str)
    if taken + persons > settings.reservation_max_seats:
        raise CapacityError(
            f"{time_str} ke aas-paas table bhara hua hai (bache seats: {max(0, settings.reservation_max_seats - taken)})"
        )


def create_reservation(
    db: Session,
    *,
    phone: str,
    name: str | None,
    day: date,
    time_str: str,
    persons: int,
    notes: str | None = None,
    today: date | None = None,
) -> Reservation:
    """Validate + capacity check + insert. Sirf tab confirmed jab DB me save ho jaye."""
    today = today or today_ist_date()
    if day < today:
        raise ReservationError("beeti hui date par booking nahi ho sakti")
    time_str = normalize_time(time_str)
    persons = parse_persons(persons)
    check_capacity(db, day, time_str, persons)
    reservation = Reservation(
        customer_phone=phone,
        customer_name=name,
        date=day,
        time=time_str,
        persons=persons,
        status="confirmed",
        notes=notes,
    )
    db.add(reservation)
    db.flush()
    return reservation


RESERVATION_STATUSES = {"confirmed", "cancelled", "done", "no_show"}
