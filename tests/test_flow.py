"""A to Z flow tests — report ke Section 20 (Testing checklist) ke hisaab se."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app import discounts, memory, menu as menu_engine, orchestrator, payments, whatsapp
from app.models import Alert, Coupon, Customer, Feedback, Order, Payment, Reservation
from app.pricing import build_bill, validate_coupon
from app.utils import clean_phone, now_ist, today_ist_date, utcnow

NEW_PHONE = "919111111111"
KNOWN_PHONE = "919222222222"


def say(db, phone, text, name=None):
    """Customer ka message bhejo (dashboard/WhatsApp jaisa hi pipeline)."""
    result = orchestrator.simulate_inbound(db, phone, text, profile_name=name)
    db.commit()
    return result


def last_reply_text(result) -> str:
    return "\n".join(reply.text for reply in result.replies)


def walk_to_delivered(db, order):
    """Kitchen ka valid raasta: confirmed -> preparing -> packed -> out_for_delivery -> delivered."""
    for status in ("preparing", "packed", "out_for_delivery", "delivered"):
        orchestrator.advance_order_status(db, order, status)


# --------------------------------------------------------------------------
# Menu & order parsing
# --------------------------------------------------------------------------
def test_menu_loads(db):
    items = menu_engine.available_items(db)
    assert len(items) >= 40
    assert menu_engine.find_item(db, "pbm").name == "Paneer Butter Masala"
    assert menu_engine.find_item(db, "cold coffee").price == 180
    assert "Paneer Butter Masala" in menu_engine.menu_text(db)


def test_order_text_parsing(db):
    parsed = menu_engine.parse_order_text(db, "2 paneer butter masala, 4 butter naan aur ek cold coffee")
    names = {line.name: line.qty for line in parsed.lines}
    assert names["Paneer Butter Masala"] == 2
    assert names["Butter Naan"] == 4
    assert names["Cold Coffee"] == 1
    assert parsed.unmatched == []


def test_order_hindi_words(db):
    parsed = menu_engine.parse_order_text(db, "do masala dosa, teen filter coffee")
    names = {line.name: line.qty for line in parsed.lines}
    assert names["Masala Dosa"] == 2
    assert names["Filter Coffee"] == 3


# --------------------------------------------------------------------------
# Memory + welcome + discount
# --------------------------------------------------------------------------
def test_new_customer_gets_welcome_discount(db):
    result = say(db, NEW_PHONE, "hi", name="Rahul Sharma")
    assert result.customer is not None
    assert result.customer.name == "Rahul Sharma"
    greeting = last_reply_text(result).lower()
    assert any(word in greeting for word in ("swagat", "namaste", "welcome", "bablu"))

    result = say(db, NEW_PHONE, "2 paneer butter masala, 4 butter naan")
    order = db.scalar(select(Order).where(Order.customer_phone == clean_phone(NEW_PHONE)))
    assert order is not None
    assert order.subtotal == 280 * 2 + 50 * 4  # 760
    assert order.discount_code == "WELCOME10"
    assert order.discount_amount == 76.0
    assert order.total_amount == round((760 - 76) * 1.05, 2)
    assert "WELCOME10" in last_reply_text(result)
    assert order.payment_link  # payment link bhi gaya


def test_known_customer_memory(db):
    say(db, KNOWN_PHONE, "mera naam Amit hai", name="Amit")
    say(db, KNOWN_PHONE, "1 butter chicken, 4 butter naan")
    # pehla order pay karke memory banao
    order = db.scalar(select(Order).where(Order.customer_phone == clean_phone(KNOWN_PHONE)))
    payment = db.scalar(select(Payment).where(Payment.order_id == order.id))
    payments.mark_paid(db, payment, via="test")
    orchestrator.on_payment_success(db, order, via="test")
    db.commit()

    result = say(db, KNOWN_PHONE, "hi")
    text = last_reply_text(result)
    assert "Amit" in text
    customer = memory.get_customer(db, KNOWN_PHONE)
    assert customer.total_orders == 1
    assert customer.last_order_items[0]["name"] == "Butter Chicken"
    assert "Butter Chicken" in (customer.last_order_summary or "")


def test_repeat_last_order(db):
    say(db, KNOWN_PHONE, "mera naam Amit hai")
    say(db, KNOWN_PHONE, "1 butter chicken, 2 garlic naan")
    order = db.scalar(select(Order).where(Order.customer_phone == clean_phone(KNOWN_PHONE)))
    payment = db.scalar(select(Payment).where(Payment.order_id == order.id))
    payments.mark_paid(db, payment, via="test")
    orchestrator.on_payment_success(db, order, via="test")
    db.commit()

    result = say(db, KNOWN_PHONE, "wahi wala kar do")
    new_order = db.scalars(select(Order).where(Order.customer_phone == clean_phone(KNOWN_PHONE)).order_by(Order.id.desc())).first()
    assert new_order.id != order.id
    assert "Butter Chicken" in last_reply_text(result)


# --------------------------------------------------------------------------
# Coupons — ek code ek hi baar
# --------------------------------------------------------------------------
def test_coupon_single_use(db):
    coupon = discounts.issue_coupon(db, percent=15, source="manual", customer_phone=clean_phone(NEW_PHONE))
    db.commit()
    found, error = validate_coupon(db, coupon.code, clean_phone(NEW_PHONE), 500)
    assert found is not None and error == ""
    discounts.mark_used(db, coupon, order_id=None)
    db.commit()
    found, error = validate_coupon(db, coupon.code, clean_phone(NEW_PHONE), 500)
    assert found is None and "pehle use" in error.lower()


def test_coupon_wrong_customer(db):
    coupon = discounts.issue_coupon(db, percent=20, source="winback", customer_phone=clean_phone(KNOWN_PHONE))
    db.commit()
    found, error = validate_coupon(db, coupon.code, clean_phone(NEW_PHONE), 500)
    assert found is None and "kisi aur" in error.lower()


def test_discount_cap_is_safe(db):
    bill = build_bill(db, [{"name": "Paneer Tikka", "qty": 2, "unit_price": 260}], discount_percent=90)
    # MAX_DISCOUNT_PERCENT default 25 — AI/rule 90 maange to bhi 25 se zyada nahi
    assert bill.discount_percent <= 25
    assert bill.discount_amount == round(520 * min(25, 90) / 100, 2)


def test_bill_maths(db):
    bill = build_bill(db, [{"name": "Paneer Butter Masala", "qty": 2, "unit_price": 280}], discount_percent=10)
    assert bill.subtotal == 560
    assert bill.discount_amount == 56
    assert bill.gst_amount == round((560 - 56) * 0.05, 2)
    assert bill.total == round(504 * 1.05, 2)


# --------------------------------------------------------------------------
# Payment -> thanks -> loyalty
# --------------------------------------------------------------------------
def test_payment_success_sends_thanks_and_points(db):
    say(db, NEW_PHONE, "mera naam Rahul hai")
    say(db, NEW_PHONE, "1 butter chicken, 4 butter naan")
    order = db.scalar(select(Order).where(Order.customer_phone == clean_phone(NEW_PHONE)))
    payment = db.scalar(select(Payment).where(Payment.order_id == order.id))
    assert payment is not None and payment.link

    payments.mark_paid(db, payment, via="test")
    replies = orchestrator.on_payment_success(db, order, via="test")
    db.commit()

    order = db.get(Order, order.id)
    assert order.payment_status == "paid"
    text = "\n".join(r.text for r in replies)
    assert "payment mil gaya" in text.lower()
    customer = memory.get_customer(db, NEW_PHONE)
    assert customer.loyalty_points > 0
    assert customer.total_orders == 1
    thanks_coupon = db.scalar(select(Coupon).where(Coupon.source == "thanks", Coupon.customer_phone == clean_phone(NEW_PHONE)))
    assert thanks_coupon is not None


def test_payment_is_idempotent(db):
    say(db, NEW_PHONE, "1 veg burger")
    order = db.scalar(select(Order).where(Order.customer_phone == clean_phone(NEW_PHONE)))
    payment = db.scalar(select(Payment).where(Payment.order_id == order.id))
    payments.mark_paid(db, payment, via="test")
    orchestrator.on_payment_success(db, order, via="test")
    db.commit()
    first = memory.get_customer(db, NEW_PHONE).total_orders

    # webhook dobara aa gaya (Meta/Razorpay retry) — double count nahi hona chahiye
    payments.mark_paid(db, payment, via="test-retry")
    db.commit()
    assert memory.get_customer(db, NEW_PHONE).total_orders == first


# --------------------------------------------------------------------------
# Complaints, handover, STOP
# --------------------------------------------------------------------------
def test_complaint_creates_alert_and_coupon(db):
    result = say(db, KNOWN_PHONE, "khana bahut thanda tha, bilkul bakwaas")
    alerts = list(db.scalars(select(Alert).where(Alert.kind == "complaint")))
    assert alerts and clean_phone(KNOWN_PHONE) in (alerts[-1].customer_phone or "")
    text = last_reply_text(result).lower()
    assert "maafi" in text or "sorry" in text
    coupon = db.scalar(select(Coupon).where(Coupon.source == "complaint"))
    assert coupon is not None  # dessert free coupon


def test_human_handover(db):
    result = say(db, KNOWN_PHONE, "mujhe insaan se baat karni hai")
    customer = memory.get_customer(db, KNOWN_PHONE)
    assert customer.human_mode is True
    assert "staff" in last_reply_text(result).lower()
    alert = db.scalar(select(Alert).where(Alert.kind == "handover"))
    assert alert is not None

    # human mode me agent chup ho jata hai
    before = db.scalar(select(Order).where(Order.customer_phone == clean_phone(KNOWN_PHONE)))
    result = say(db, KNOWN_PHONE, "2 paneer tikka")
    assert result.replies == []
    after = db.scalar(select(Order).where(Order.customer_phone == clean_phone(KNOWN_PHONE)))
    assert (after is None) == (before is None)


def test_stop_and_start(db):
    say(db, KNOWN_PHONE, "hi")
    say(db, KNOWN_PHONE, "STOP")
    customer = memory.get_customer(db, KNOWN_PHONE)
    assert customer.opted_out is True and customer.opt_in is False

    say(db, KNOWN_PHONE, "start")
    customer = memory.get_customer(db, KNOWN_PHONE)
    assert customer.opt_in is True and customer.opted_out is False


# --------------------------------------------------------------------------
# Reservation (F9)
# --------------------------------------------------------------------------
def test_reservation_flow(db):
    say(db, KNOWN_PHONE, "mera naam Priya hai")
    result = say(db, KNOWN_PHONE, "table book karni hai")
    assert "kitne baje" in last_reply_text(result).lower() or "kis din" in last_reply_text(result).lower()

    result = say(db, KNOWN_PHONE, "kal 7 baje 4 log")
    text = last_reply_text(result).lower()
    assert "confirm" in text
    booking = db.scalar(select(Reservation).where(Reservation.customer_phone == clean_phone(KNOWN_PHONE)))
    assert booking is not None
    assert booking.persons == 4
    assert booking.date == today_ist_date() + timedelta(days=1)


def test_reservation_cancel(db):
    say(db, KNOWN_PHONE, "aaj 8 baje 2 log ki table book karo")
    say(db, KNOWN_PHONE, "table booking cancel kar do")
    booking = db.scalar(select(Reservation).where(Reservation.customer_phone == clean_phone(KNOWN_PHONE)))
    assert booking.status == "cancelled"


# --------------------------------------------------------------------------
# Feedback (F14)
# --------------------------------------------------------------------------
def test_good_feedback_google_review_and_coupon(db):
    say(db, KNOWN_PHONE, "mera naam Amit hai")
    say(db, KNOWN_PHONE, "1 cold coffee")
    order = db.scalar(select(Order).where(Order.customer_phone == clean_phone(KNOWN_PHONE)))
    payload = db.scalar(select(Payment).where(Payment.order_id == order.id))
    payments.mark_paid(db, payload, via="test")
    orchestrator.on_payment_success(db, order, via="test")
    db.commit()

    # delivery + feedback ka intezaar
    walk_to_delivered(db, order)
    db.commit()

    result = say(db, KNOWN_PHONE, "5")
    text = last_reply_text(result)
    assert "review" in text.lower()
    feedback = db.scalar(select(Feedback).where(Feedback.customer_phone == clean_phone(KNOWN_PHONE)))
    assert feedback.rating == 5


def test_bad_feedback_alerts_owner(db):
    say(db, KNOWN_PHONE, "1 paneer tikka")
    order = db.scalar(select(Order).where(Order.customer_phone == clean_phone(KNOWN_PHONE)))
    payload = db.scalar(select(Payment).where(Payment.order_id == order.id))
    payments.mark_paid(db, payload, via="test")
    orchestrator.on_payment_success(db, order, via="test")
    walk_to_delivered(db, order)
    db.commit()

    say(db, KNOWN_PHONE, "2")
    feedback = db.scalar(select(Feedback).where(Feedback.customer_phone == clean_phone(KNOWN_PHONE)))
    assert feedback.rating == 2
    alert = db.scalar(select(Alert).where(Alert.kind == "complaint"))
    assert alert is not None


# --------------------------------------------------------------------------
# Owner report + automation
# --------------------------------------------------------------------------
def test_owner_report_and_birthday_once(db):
    from app import automations, reports

    # birthday aaj wala customer banao
    customer = Customer(phone="919333333333", name="Birthday Boy", birthday=now_ist().strftime("%m-%d"), opt_in=True)
    db.add(customer)
    db.commit()

    first = automations.send_birthday_wishes(db)
    second = automations.send_birthday_wishes(db)  # dobara nahi bhejna chahiye
    db.commit()
    assert first["sent"] == 1
    assert second["sent"] == 0

    text = reports.daily_report_text(db)
    assert "Aaj ki Report" in text
    assert "sale" in text.lower()


def test_winback_only_optin(db):
    from app import automations

    opted_in = Customer(phone="919444444444", name="Optin Guy", opt_in=True, total_orders=2,
                        last_visit_at=utcnow() - timedelta(days=40), last_order_summary="Cold Coffee")
    opted_out = Customer(phone="919555555555", name="No Permission", opt_in=False, total_orders=3,
                         last_visit_at=utcnow() - timedelta(days=45), last_order_summary="Pizza")
    db.add_all([opted_in, opted_out])
    db.commit()

    result = automations.send_winback_offers(db)
    db.commit()
    phones = [row["phone"] for row in result["details"]]
    assert "919444444444" in phones
    assert "919555555555" not in phones  # bina permission spam nahi
    assert result["skipped"] >= 1


def test_stop_is_never_overridden_even_with_force(db):
    """STOP karne wale ko force se bhi message nahi jaana chahiye."""
    from app import automations

    stopped = Customer(
        phone="919666666666", name="Stop Guy", opt_in=False, opted_out=True, total_orders=4,
        last_visit_at=utcnow() - timedelta(days=50), birthday=now_ist().strftime("%m-%d"),
    )
    allowed = Customer(
        phone="919777777777", name="Allowed Guy", opt_in=True, opted_out=False, total_orders=4,
        last_visit_at=utcnow() - timedelta(days=50), birthday=now_ist().strftime("%m-%d"),
    )
    db.add_all([stopped, allowed])
    db.commit()

    winback = automations.send_winback_offers(db, force=True)
    birthday = automations.send_birthday_wishes(db, force=True)
    db.commit()

    touched = {row["phone"] for row in winback["details"]} | {row["phone"] for row in birthday["details"]}
    assert "919666666666" not in touched
    assert "919777777777" in touched
    assert winback["skipped"] >= 1 and birthday["skipped"] >= 1


# --------------------------------------------------------------------------
# Intent engine
# --------------------------------------------------------------------------
def test_intent_detection():
    from app import intent as intent_engine

    assert intent_engine.detect("hi").name == "greeting"
    assert intent_engine.detect("menu bhejo").name == "menu"
    assert intent_engine.detect("khana bahut kharab tha").name == "complaint"
    assert intent_engine.detect("stop").name == "opt_out"
    assert intent_engine.detect("insaan se baat karni hai").name == "handover"
    assert intent_engine.detect("2 paneer butter masala, 4 naan").name == "order"

    reservation = intent_engine.detect("kal 7 baje 4 log ki table book karni hai")
    assert reservation.name == "reservation"
    assert reservation.entities["persons"] == 4
    assert reservation.entities["time"] == "19:00"

    named = intent_engine.detect("mera naam Rahul Sharma hai")
    assert named.entities["name"].lower().startswith("rahul")

    birthday = intent_engine.detect("mera birthday 15 March hai")
    assert birthday.entities["birthday"] == "03-15"


def test_language_detection():
    from app.utils import detect_language

    assert detect_language("namaste sir kya haal hai") == "hinglish"
    assert detect_language("नमस्ते सर, मेनू भेजिए") == "hi"
    assert detect_language("hello please share the menu") == "en"


# --------------------------------------------------------------------------
# WhatsApp parsing (webhook)
# --------------------------------------------------------------------------
def test_webhook_parsing():
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "contacts": [{"wa_id": "919812345678", "profile": {"name": "Rahul Sharma"}}],
                            "messages": [
                                {"from": "919812345678", "id": "wamid.X", "timestamp": "1700000000", "type": "text",
                                 "text": {"body": "2 pizza kar do"}}
                            ],
                        }
                    }
                ]
            }
        ]
    }
    inbound = whatsapp.parse_webhook(payload)
    assert len(inbound) == 1
    assert inbound[0].phone == "919812345678"
    assert inbound[0].profile_name == "Rahul Sharma"
    assert inbound[0].text == "2 pizza kar do"


def test_system_prompt_has_safety_rules():
    from app.llm import build_system_prompt

    prompt = build_system_prompt()
    assert "price" in prompt.lower()
    assert "discount" in prompt.lower()
    assert "Hinglish" in prompt
