"""Billing engine unit tests — Decimal arithmetic, rounding, caps (docs/TESTING.md)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.config import settings
from app.pricing import build_bill
from app.utils import money, q2, rupees


@pytest.fixture()
def fixed_rates(monkeypatch):
    monkeypatch.setattr(settings, "gst_percent", 5.0)
    monkeypatch.setattr(settings, "max_discount_percent", 25.0)
    monkeypatch.setattr(settings, "packaging_charge", 0.0)
    monkeypatch.setattr(settings, "delivery_charge", 0.0)


def test_money_rounds_half_up_to_paise():
    assert money(0.285) == 0.29
    assert money(10.005) == 10.01
    assert money("19.99") == 19.99
    assert q2("0.1") + q2("0.2") == Decimal("0.30")  # float drift nahi


def test_line_totals_use_exact_decimal(db, fixed_rates):
    bill = build_bill(db, [{"name": "Chai", "qty": 3, "unit_price": 0.1}])
    assert bill.lines[0].line_total == 0.3
    assert bill.subtotal == 0.3
    assert bill.total == 0.32  # 0.30 + 5% GST = 0.315 -> 0.32 (HALF_UP)


def test_discount_gst_and_total_are_consistent(db, fixed_rates):
    # 33.33 x 3 = 99.99 ; 15% off = 14.9985 -> 15.00 ; taxable 84.99 ; GST 5% = 4.2495 -> 4.25 ; total 89.24
    bill = build_bill(db, [{"name": "Thali", "qty": 3, "unit_price": 33.33}], discount_percent=15)
    assert bill.subtotal == 99.99
    assert bill.discount_amount == 15.00
    assert bill.taxable == 84.99
    assert bill.gst_amount == 4.25
    assert bill.total == 89.24
    assert bill.total == float(q2(bill.taxable + bill.gst_amount))


def test_discount_is_capped_and_never_makes_total_negative(db, fixed_rates):
    bill = build_bill(db, [{"name": "Dal", "qty": 1, "unit_price": 100}], discount_percent=500)
    assert bill.discount_percent == 25.0  # MAX_DISCOUNT_PERCENT cap
    assert bill.discount_amount == 25.0
    assert bill.total > 0


def test_freebies_do_not_add_to_subtotal(db, fixed_rates):
    bill = build_bill(
        db,
        [
            {"name": "Dosa", "qty": 2, "unit_price": 80},
            {"name": "Gulab Jamun", "qty": 1, "unit_price": 40, "is_freebie": True},
        ],
        freebies=["Gulab Jamun"],
    )
    assert bill.subtotal == 160.0


def test_invalid_quantity_and_negative_price_rejected(db, fixed_rates):
    with pytest.raises(ValueError):
        build_bill(db, [{"name": "X", "qty": 0, "unit_price": 10}])
    with pytest.raises(ValueError):
        build_bill(db, [{"name": "X", "qty": 1, "unit_price": -10}])


def test_rupees_formatting():
    assert rupees(648) == "₹648"
    assert rupees(648.5) == "₹648.50"
    assert rupees(1234.0) == "₹1,234"


def test_reservation_reminder_only_inside_window(db, monkeypatch):
    """Reminder: window (60 min) me hi bheja jaye; beeti hui booking par nahi (regression)."""
    from datetime import timedelta as td

    from app import automations
    from app.models import Reservation
    from app.utils import now_ist, today_ist_date
    from app import whatsapp

    sent: list = []
    monkeypatch.setattr(whatsapp, "send_text", lambda to, text, **kw: sent.append(to) or [])
    now = now_ist()
    soon_time = (now + td(minutes=30)).strftime("%H:%M")
    past_time = (now - td(hours=3)).strftime("%H:%M")
    far_time = (now + td(hours=5)).strftime("%H:%M")
    if now.date() != today_ist_date():  # safety
        return
    db.add_all(
        [
            Reservation(customer_phone="919700000001", date=today_ist_date(), time=soon_time, persons=2, status="confirmed"),
            Reservation(customer_phone="919700000002", date=today_ist_date(), time=past_time, persons=2, status="confirmed"),
            Reservation(customer_phone="919700000003", date=today_ist_date(), time=far_time, persons=2, status="confirmed"),
        ]
    )
    db.commit()
    automations.send_reservation_reminders(db)
    db.commit()
    assert "919700000001" in sent
    assert "919700000002" not in sent, "beeti hui booking par reminder nahi jana chahiye"
    assert "919700000003" not in sent, "abhi bahut door booking par reminder abhi nahi"


def test_late_payment_success_does_not_regress_kitchen_status(db):
    """on_payment_success dobara chale (duplicate/late) to 'preparing' order 'confirmed' me wapas na jaye."""
    from app import orchestrator
    from app.models import Customer, Order
    from app.utils import now_ist

    customer = Customer(phone="919700000009", name="Kitchen Test", first_seen_at=now_ist(), last_seen_at=now_ist())
    db.add(customer)
    db.flush()
    order = Order(
        order_no="pending-test-kitchen",
        customer_id=customer.id,
        customer_phone=customer.phone,
        customer_name=customer.name,
        items=[],
        subtotal=0,
        discount_amount=0,
        freebies=[],
        packaging=0,
        delivery=0,
        taxable=0,
        gst_amount=0,
        total_amount=0,
        payment_status="paid",
        order_status="preparing",
        channel="whatsapp",
    )
    db.add(order)
    db.flush()
    order.order_no = "kitchen-test-1"
    db.flush()
    orchestrator.on_payment_success(db, order, via="test", deliver_replies=False)
    assert order.order_status == "preparing"
