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
from app.models import AppSetting, DiscountRule, Order
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


# --------------------------------------------------------------------------
# Bug 5 — quantity 1..MAX_ORDER_QTY ke bahar (chat + dashboard dono)
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text",
    ["50000 paneer tikka", "101 masala dosa", "999999 masala dosa", "2 masala dosa aur 999999 dosa"],
)
def test_huge_quantity_does_not_crash_chat(db, text):
    """Fix se pehle build_bill ValueError uthata tha -> HTTP 500, customer ko koi jawab nahi.

    WhatsApp failed delivery par dobara bhejta hai, to customer ko baar baar khamoshi milti thi.
    """
    body, result = say(db, "919333666666", text)
    assert result.intent != "order_invalid"
    assert body.strip()


def test_huge_quantity_does_not_crash_api(client, db):
    response = client.post(
        "/api/orders",
        json={"phone": "919333777777", "name": "Bulk", "items_text": "999999 masala dosa"},
    )
    assert response.status_code == 400, response.text


@pytest.mark.parametrize("qty", [0, -3, 999999])
def test_out_of_range_quantity_returns_400(client, db, qty):
    response = client.post(
        "/api/orders",
        json={"phone": "919333888888", "name": "Q", "items": [{"name": "Masala Dosa", "qty": qty}]},
    )
    assert response.status_code == 400, response.text


def test_non_numeric_quantity_returns_400(client, db):
    response = client.post(
        "/api/orders",
        json={"phone": "919333888889", "name": "Q", "items": [{"name": "Masala Dosa", "qty": "abc"}]},
    )
    assert response.status_code == 400, response.text


def test_quantity_cap_is_shared_by_parser_and_bill(db):
    """Parser ki clamp aur build_bill ki validation ek hi limit maanein — alag hone par 500 aata tha."""
    from app.config import settings
    from app.pricing import build_bill

    parsed = menu_engine.parse_order_text(db, "999999 masala dosa")
    assert parsed.quantity_out_of_range is True
    assert parsed.max_qty == int(settings.max_order_qty)
    assert parsed.lines, "koi item match nahi hua"
    assert all(1 <= line.qty <= parsed.max_qty for line in parsed.lines)
    bill = build_bill(
        db,
        [{"name": l.name, "qty": l.qty, "unit_price": l.unit_price} for l in parsed.lines],
    )
    assert bill.total > 0


def test_webhook_path_survives_huge_quantity(client, db):
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {"from": "919333999999", "type": "text",
                                 "text": {"body": "999999 masala dosa"}}
                            ]
                        }
                    }
                ]
            }
        ],
    }
    response = client.post("/webhook", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "EVENT_RECEIVED"


# --------------------------------------------------------------------------
# Bug 6 — menu price non-numeric (add + edit)
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "bad_price", ["abc", [1], {"a": 1}, True, "NaN", "Infinity", "-Infinity", "1e999"]
)
def test_menu_bad_price_returns_400_not_500(client, db, bad_price):
    """float("abc") -> 500 tha. NaN/Infinity har range check pass karke DB insert crash karate the."""
    response = client.post("/api/menu", json={"name": "BadPrice", "price": bad_price})
    assert response.status_code == 400, response.text


def test_menu_negative_price_rejected(client, db):
    assert client.post("/api/menu", json={"name": "NegPrice", "price": -100}).status_code == 400
    item = menu_engine.find_item(db, "Masala Dosa")
    assert item is not None
    assert client.patch(f"/api/menu/{item.id}", json={"price": "abc"}).status_code == 400
    assert client.patch(f"/api/menu/{item.id}", json={"price": -10}).status_code == 400


# --------------------------------------------------------------------------
# Bug 7 — rule priority non-numeric
# --------------------------------------------------------------------------
def test_rule_bad_priority_returns_400(client, db):
    response = client.post(
        "/api/rules",
        json={"name": "BadPriority", "trigger": "first_order",
              "priority": "abc", "reward": {"type": "percent", "value": 5}},
    )
    assert response.status_code == 400, response.text


# --------------------------------------------------------------------------
# Bug 8 — malformed rule poora ordering band na kare
# --------------------------------------------------------------------------
def test_rule_bad_reward_value_rejected_on_create(client, db):
    """Validation pehle sirf PATCH par thi, POST par nahi — isliye "abc" seedha DB me jata tha."""
    response = client.post(
        "/api/rules",
        json={"name": "BadReward", "trigger": "first_order",
              "reward": {"type": "percent", "value": "abc"}},
    )
    assert response.status_code == 400, response.text
    assert db.scalar(select(DiscountRule).where(DiscountRule.name == "BadReward")) is None


def test_malformed_rule_cannot_break_ordering(db):
    """DB me kharaab rule ho to bhi order lagna chahiye — engine kabhi raise nahi karega.

    Ye sabse bura wala tha: ek galat rule se HAR order 500 ho jata tha, har customer
    ke liye, jab tak koi DB me ja kar rule na hataye.
    """
    db.add(
        DiscountRule(
            code="BROKEN", name="broken rule", trigger="first_order",
            condition={}, reward={"type": "percent", "value": "abc"},
            priority=1, is_active=True, message="broken",
        )
    )
    db.commit()
    body, result = say(db, "919333555555", "2 masala dosa")
    assert result.intent != "order_invalid"
    order = db.scalar(select(Order).where(Order.customer_phone == "919333555555"))
    assert order is not None
    assert order.total_amount > 0


@pytest.mark.parametrize("bad", ["abc", None, [], {}, True, "NaN", "Infinity"])
def test_discount_engine_helpers_never_raise(bad):
    """Engine total hona chahiye — bura data aaye to skip kare, crash nahi."""
    from app.discounts import _as_float, _as_int, reward_percent

    assert _as_float(bad, 7.0) == 7.0
    assert _as_int(bad, 3) == 3

    class FakeRule:
        def __init__(self, reward):
            self.reward = reward

    assert reward_percent(FakeRule({"type": "percent", "value": bad})) == 0.0


# --------------------------------------------------------------------------
# Settings — text field length cap
# --------------------------------------------------------------------------
def test_settings_text_too_long_rejected():
    from app.config import MAX_SETTING_TEXT, Settings

    s = Settings()
    result = s.apply_overrides({"restaurant": {"name": "x" * (MAX_SETTING_TEXT + 1)}})
    assert result["rejected"].get("restaurant.name"), "500-char naam accept nahi hona chahiye"
