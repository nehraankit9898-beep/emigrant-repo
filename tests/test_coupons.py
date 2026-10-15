"""Coupon redemption — single use, expiry, ownership, release on cancel (docs/FEATURE_STATUS.md)."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app import orchestrator, pricing
from app.models import Coupon, Order
from app.utils import clean_phone, utcnow



def say(db, phone, text, name=None):
    result = orchestrator.simulate_inbound(db, phone, text, profile_name=name)
    db.commit()
    return result

PHONE_A = "919611111111"
PHONE_B = "919622222222"


def _coupon(db, code="SAVE20X", percent=20, phone=None, expiry_days=10):
    coupon = Coupon(
        code=code,
        discount_percent=percent,
        customer_phone=phone,
        source="manual",
        expiry_date=utcnow() + timedelta(days=expiry_days),
    )
    db.add(coupon)
    db.commit()
    return coupon


def _last_order(db, phone):
    return db.scalar(select(Order).where(Order.customer_phone == clean_phone(phone)).order_by(Order.id.desc()).limit(1))


def test_coupon_applies_once_then_is_rejected_for_others(db):
    _coupon(db, code="ONCE20", percent=20)
    say(db, PHONE_A, "ONCE20 ke saath 1 veg burger")
    order_a = _last_order(db, PHONE_A)
    assert order_a.discount_code == "ONCE20"
    assert order_a.discount_amount > 0

    say(db, PHONE_B, "ONCE20 ke saath 1 veg burger")
    order_b = _last_order(db, PHONE_B)
    assert order_b.discount_code != "ONCE20", "single-use coupon dobara nahi chalna chahiye"
    db.expire_all()
    coupon = db.scalar(select(Coupon).where(Coupon.code == "ONCE20"))
    assert coupon.is_used is True
    assert coupon.used_on_order_id == order_a.id


def test_coupon_bound_to_another_customer_is_rejected(db):
    _coupon(db, code="ONLYA20", percent=20, phone=clean_phone(PHONE_A))
    say(db, PHONE_B, "ONLYA20 ke saath 1 veg burger")
    assert _last_order(db, PHONE_B).discount_code != "ONLYA20"
    db.expire_all()
    assert db.scalar(select(Coupon).where(Coupon.code == "ONLYA20")).is_used is False


def test_expired_coupon_is_rejected_with_message(db):
    _coupon(db, code="OLD20", percent=20, expiry_days=-1)
    result = say(db, PHONE_A, "OLD20 ke saath 1 veg burger")
    assert _last_order(db, PHONE_A).discount_code != "OLD20"
    assert "date nikal gayi" in "\n".join(r.text for r in result.replies)


def test_cancelling_order_releases_coupon(db):
    _coupon(db, code="REL20", percent=20)
    say(db, PHONE_A, "REL20 ke saath 1 veg burger")
    order = _last_order(db, PHONE_A)
    orchestrator.advance_order_status(db, order, "cancelled", deliver_reply=False, actor="test")
    db.commit()
    db.expire_all()
    coupon = db.scalar(select(Coupon).where(Coupon.code == "REL20"))
    assert coupon.is_used is False
    assert coupon.used_on_order_id is None


def test_second_redemption_of_same_coupon_loses(db):
    coupon = _coupon(db, code="RACE20", percent=20)
    first = pricing.redeem_coupon(db, coupon)
    second = pricing.redeem_coupon(db, coupon)
    assert first is True and second is False
