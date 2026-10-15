"""Regression tests for reservation date extraction."""

from __future__ import annotations

from datetime import date

import pytest

from app import intent, reservations, utils


@pytest.mark.parametrize(
    "text",
    ["15 Nov 2027", "15/11/2027", "15-11-27"],
)
def test_explicit_year_is_preserved(monkeypatch, text):
    today = date(2026, 10, 15)
    monkeypatch.setattr(utils, "today_ist_date", lambda: today)

    assert intent._find_date(text) == "2027-11-15"


def test_explicit_out_of_range_year_is_rejected_instead_of_rebooking_earlier(monkeypatch):
    today = date(2026, 10, 15)
    monkeypatch.setattr(utils, "today_ist_date", lambda: today)

    parsed = intent.detect("reserve a table for 4 people on 15 Nov 2027 at 7 pm")
    assert parsed.entities["date"] == "2027-11-15"
    with pytest.raises(reservations.ReservationError, match="365 din"):
        reservations.parse_date(parsed.entities["date"], today)


def test_year_is_inferred_when_customer_does_not_provide_one(monkeypatch):
    monkeypatch.setattr(utils, "today_ist_date", lambda: date(2026, 12, 20))

    assert intent._find_date("15 Jan") == "2027-01-15"


def test_invalid_calendar_date_is_not_extracted(monkeypatch):
    monkeypatch.setattr(utils, "today_ist_date", lambda: date(2026, 1, 1))

    assert intent._find_date("31/02/2027") is None
