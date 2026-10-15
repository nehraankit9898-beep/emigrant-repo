"""Regression tests — bugs jo live testing me mile the, dobara na aayein.

Har test pehle FAIL hota tha (fix se pehle wale code par):

1. `pay` pending order nahi dhoondh paata tha  -> "koi pending bill nahi hai"
2. `bill` discount chhod kar dobara banta tha -> customer ko asli se zyada total
3. `resend-link` bhi wahi galat amount bhejta tha (link par asli amount, message me galat)
4. `PUT /api/settings` DB me likhta tha par koi padhta nahi tha (GST change ka koi asar nahi)
"""

from __future__ import annotations

import re

import pytest
from sqlalchemy import select

from app import discounts, memory, menu as menu_engine, orchestrator, payments
from app.config import Settings
from app.models import AppSetting, Order
from app.pricing import bill_from_order

NEW_PHONE = "919333111111"
TOTAL_RE = re.compile(r"Total: ₹([\d.]+)")


@pytest.fixture(autouse=True)
def _restore_settings():
    """`settings` global object hai — koi test isse badal de to baaki tests kharaab ho jaate hain.

    Isliye har test ke baad overrideable fields ki asli value wapas kar dete hain.
    """
    from app.config import settings

    snapshot = {name: getattr(settings, name) for name in settings.OVERRIDE_FIELD.values()}
    yield
    for name, value in snapshot.items():
        setattr(settings, name, value)


def say(db, phone, text):
    result = orchestrator.simulate_inbound(db, phone, text)
    db.commit()
    return "\n".join(reply.text for reply in result.replies), result


def place_discounted_order(db, phone=NEW_PHONE, text="2 paneer butter masala, 4 butter naan"):
    """Pehla order -> WELCOME10 (10% off) lagta hai."""
    body, _ = say(db, phone, text)
    order = db.scalar(select(Order).where(Order.customer_phone == phone).order_by(Order.id.desc()))
    assert order is not None
    return order, body


# --------------------------------------------------------------------------
# Bug 1 — pending order track hona chahiye ("pay" / "bill" usi order ko dekhein)
# --------------------------------------------------------------------------
def test_pending_order_is_tracked_after_order(db):
    order, _ = place_discounted_order(db)
    # pehle ye sirf COD orders ke liye set hota tha
    assert (order.customer.flow_state or {}).get("active_order") == order.order_no


def test_pay_returns_link_for_unpaid_order(db):
    order, _ = place_discounted_order(db)
    body, result = say(db, NEW_PHONE, "pay")
    assert result.intent == "pay"
    assert "http" in body, f"payment link nahi mila: {body!r}"
    assert "koi pending bill nahi" not in body


def test_latest_unpaid_order_ignores_cancelled(db):
    """Cancel hue order ke liye payment link nahi bhejna chahiye."""
    order, _ = place_discounted_order(db)
    customer = memory.get_customer(db, NEW_PHONE)
    order.order_status = "cancelled"
    db.commit()
    assert orchestrator.latest_unpaid_order(db, customer) is None
    body, _ = say(db, NEW_PHONE, "pay")
    assert "koi pending bill nahi" in body


def test_pay_after_payment_says_nothing_pending(db):
    order, _ = place_discounted_order(db)
    payment = payments.create_payment(db, order)
    assert payments.settle_payment(db, payment, via="test")
    orchestrator.on_payment_success(db, order, via="test", deliver_replies=False)
    db.commit()
    body, _ = say(db, NEW_PHONE, "pay")
    assert "koi pending bill nahi" in body


# --------------------------------------------------------------------------
# Bug 2/3 — bill dobara banate waqt discount/GST hatna nahi chahiye
# --------------------------------------------------------------------------
def test_order_stores_applied_rates(db):
    order, _ = place_discounted_order(db)
    assert order.discount_percent == 10.0
    assert order.gst_percent == 5.0
    assert order.discount_amount == 76.0


def test_bill_after_payment_matches_original_total(db):
    """Fix se pehle yahan ₹798 aata tha (₹718.20 ki jagah) — discount hat jaata tha."""
    order, order_body = place_discounted_order(db)
    original_total = float(TOTAL_RE.search(order_body).group(1))

    payment = payments.create_payment(db, order)
    payments.settle_payment(db, payment, via="test")
    orchestrator.on_payment_success(db, order, via="test", deliver_replies=False)
    db.commit()

    body, _ = say(db, NEW_PHONE, "bill")
    shown = TOTAL_RE.search(body)
    assert shown is not None, f"bill me total nahi mila: {body!r}"
    assert float(shown.group(1)) == original_total, "bill ka total asli bill se alag hai"


def test_bill_from_order_reproduces_stored_total(db):
    order, _ = place_discounted_order(db)
    rebuilt = bill_from_order(db, order)
    assert abs(rebuilt.total - order.total_amount) < 0.01
    assert abs(rebuilt.discount_amount - order.discount_amount) < 0.01
    assert abs(rebuilt.gst_amount - order.gst_amount) < 0.01
    assert rebuilt.discount_code == order.discount_code


def test_bill_from_order_keeps_freebies(db):
    """BIGBILL (>=₹999) par free Gulab Jamun milta hai — wo bhi repeat hona chahiye."""
    phone = "919333222222"
    say(db, phone, "4 butter chicken, 2 mutton rogan josh")
    order = db.scalar(select(Order).where(Order.customer_phone == phone))
    assert order.freebies
    rebuilt = bill_from_order(db, order)
    assert rebuilt.freebies == order.freebies
    assert abs(rebuilt.total - order.total_amount) < 0.01


def test_bill_from_order_derives_rate_for_legacy_rows(db):
    """Purane orders (rate columns aane se pehle ke) ka discount bhi hatna nahi chahiye."""
    order, _ = place_discounted_order(db)
    order.discount_percent = 0.0
    order.gst_percent = 0.0
    db.commit()
    rebuilt = bill_from_order(db, order)
    assert abs(rebuilt.total - order.total_amount) < 0.01, "legacy order ka total badal gaya"


def test_bill_from_order_ignores_later_config_change(db):
    """Config badalne se purane order ka amount nahi badalna chahiye."""
    from app.config import settings

    order, _ = place_discounted_order(db)
    original = order.total_amount
    original_rate = settings.gst_percent
    try:
        settings.gst_percent = 18.0
        rebuilt = bill_from_order(db, order)
    finally:
        settings.gst_percent = original_rate
    assert abs(rebuilt.total - original) < 0.01


@pytest.mark.parametrize("phone", ["919333333331"])  # client fixture ke liye alag number
def test_resend_link_quotes_order_total(client, db, phone):
    """Dashboard 'resend link' par message me wahi amount hona chahiye jo link charge karega."""
    say(db, phone, "2 paneer butter masala, 4 butter naan")
    order = db.scalar(select(Order).where(Order.customer_phone == phone))
    response = client.post(f"/api/orders/{order.order_no}/resend-link")
    assert response.status_code == 200
    message = response.json()["message"]
    shown = float(TOTAL_RE.search(message).group(1))
    assert shown == order.total_amount, f"message me ₹{shown}, order ka ₹{order.total_amount}"


# --------------------------------------------------------------------------
# Bug 4 — settings overrides actually apply honi chahiye
# --------------------------------------------------------------------------
def test_settings_override_applies_to_settings_object():
    s = Settings()
    result = s.apply_overrides({"money": {"gst_percent": 18}})
    assert result["applied"]["money"]["gst_percent"] == 18.0
    assert s.gst_percent == 18.0


def test_settings_override_rejects_out_of_range():
    s = Settings()
    before = s.gst_percent
    result = s.apply_overrides({"money": {"gst_percent": 500}})
    assert result["rejected"].get("money.gst_percent")
    assert s.gst_percent == before, "galat value apply nahi honi chahiye"


def test_settings_override_rejects_bad_time_and_unknown_keys():
    s = Settings()
    result = s.apply_overrides(
        {"automation": {"owner_report_time": "99:99"}, "money": {"evil": 1}, "bogus": {"x": 1}}
    )
    assert result["rejected"].get("automation.owner_report_time")
    assert result["rejected"].get("money.evil")
    assert result["applied"] == {}


def test_settings_put_applies_gst_to_next_bill(client, db):
    """Settings tab me GST badalne se agle bill me wahi GST lagna chahiye."""
    from app.config import settings

    original = settings.gst_percent
    phone = "919333444444"
    try:
        response = client.put("/api/settings", json={"money": {"gst_percent": 18}})
        assert response.status_code == 200
        assert response.json()["saved"]["money"]["gst_percent"] == 18.0
        assert settings.gst_percent == 18.0

        say(db, phone, "2 masala dosa")
        order = db.scalar(select(Order).where(Order.customer_phone == phone))
        assert order.gst_percent == 18.0
    finally:
        settings.apply_overrides({"money": {"gst_percent": original}})
        db.execute(AppSetting.__table__.delete())
        db.commit()


def test_settings_are_read_back_from_db():
    """Restart-safe: DB me save hui setting dobara load hone par apply ho."""
    from app.database import SessionLocal
    from app.main import load_settings_overrides

    db = SessionLocal()
    try:
        db.add(AppSetting(key="money", value={"gst_percent": 12}))
        db.commit()
        result = load_settings_overrides(db)
        assert result["applied"]["money"]["gst_percent"] == 12.0
    finally:
        from app.config import settings

        settings.apply_overrides({"money": {"gst_percent": settings.gst_percent}})
        db.execute(AppSetting.__table__.delete())
        db.commit()
        db.close()


def test_menu_and_rules_still_seeded(db):
    """Sanity: fixtures ke baad bhi menu/rules maujood (upar ke tests inhi par chale)."""
    assert menu_engine.available_items(db)
    assert discounts.active_rules(db)
