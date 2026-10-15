"""Security, payment-integrity and data-integrity regression tests.

Ye tests real HTTP routes (FastAPI TestClient) use karte hain, helper functions
ko seedha nahi. Har test ek audit finding (docs/SECURITY_AUDIT.md) se judaa hai.
External services (WhatsApp Graph API, Razorpay) kabhi call nahi hote — sab mock.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app import orchestrator, whatsapp
from app.config import settings
from app.models import Alert, Coupon, Customer, Message, Order, Payment, Reservation
from app.utils import clean_phone, today_ist_date

NEW_PHONE = "919111111111"


def say(db, phone, text, name=None):
    result = orchestrator.simulate_inbound(db, phone, text, profile_name=name)
    db.commit()
    return result

RZP_SECRET = "whsec_test_only"


@pytest.fixture()
def silent_whatsapp(monkeypatch):
    """Live WhatsApp send ko no-op karo (network call nahi)."""
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(whatsapp, "send_text", lambda to, text, **kw: sent.append((to, text)) or [])
    monkeypatch.setattr(whatsapp, "send_buttons", lambda to, body, buttons: sent.append((to, body)) or {})
    monkeypatch.setattr(whatsapp, "mark_read", lambda message_id: None)
    return sent


def _rzp_body(payment: Payment, order: Order, amount_paise: int | None = None, event: str = "payment_link.paid") -> bytes:
    body = {
        "event": event,
        "payload": {
            "payment_link": {
                "entity": {
                    "id": payment.provider_ref,
                    "amount": amount_paise if amount_paise is not None else int(round(order.total_amount * 100)),
                    "currency": "INR",
                    "status": "paid",
                    "reference_id": f"order_{order.order_no}",
                    "notes": {"order_no": order.order_no},
                }
            }
        },
    }
    return json.dumps(body).encode()


def _sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _live_razorpay(monkeypatch, secret: str = RZP_SECRET):
    """Live mode ON. Note: order pehle `_razorpay_order` se banao (live me provider API call hoti)."""
    monkeypatch.setattr(settings, "payment_mode", "live", raising=False)
    monkeypatch.setattr(settings, "razorpay_key_id", "rzp_test_key", raising=False)
    monkeypatch.setattr(settings, "razorpay_key_secret", "rzp_test_secret", raising=False)
    monkeypatch.setattr(settings, "razorpay_webhook_secret", secret, raising=False)


def _razorpay_order(db, monkeypatch) -> tuple[Order, Payment]:
    """Ek order banao (mock mode me — live me provider call hoti) aur use razorpay payment se jodo."""
    monkeypatch.setattr(settings, "payment_mode", "mock", raising=False)
    say(db, NEW_PHONE, "1 veg burger", name="Test Customer")
    order = db.scalar(select(Order).where(Order.customer_phone == clean_phone(NEW_PHONE)))
    payment = db.scalar(select(Payment).where(Payment.order_id == order.id))
    payment.provider = "razorpay"
    payment.provider_ref = "plink_TESTREF001"
    db.commit()
    return order, payment


# ---------------------------------------------------------------------------
# A. Dashboard / admin API authentication
# ---------------------------------------------------------------------------
def test_api_fails_closed_in_production_without_admin_token(client, monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production", raising=False)
    monkeypatch.setattr(settings, "admin_token", "")
    response = client.get("/api/summary")
    assert response.status_code in {401, 503}, "production me ADMIN_TOKEN khaali ho to API band honi chahiye"


def test_api_rejects_token_passed_in_query_string(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_token", "a-long-random-admin-token-123")
    response = client.get("/api/summary?token=a-long-random-admin-token-123")
    assert response.status_code == 401, "token URL query me accept nahi hona chahiye (logs/history me leak)"


def test_api_accepts_correct_header_token(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_token", "a-long-random-admin-token-123")
    assert client.get("/api/summary").status_code == 401
    ok = client.get("/api/summary", headers={"X-Admin-Token": "a-long-random-admin-token-123"})
    assert ok.status_code == 200
    bad = client.get("/api/summary", headers={"X-Admin-Token": "wrong"})
    assert bad.status_code == 401


# ---------------------------------------------------------------------------
# B. WhatsApp webhook authenticity and replay
# ---------------------------------------------------------------------------
def _wa_payload(message_id: str, text: str, phone: str = "919111111111") -> bytes:
    return json.dumps(
        {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messaging_product": "whatsapp",
                                "contacts": [{"wa_id": phone, "profile": {"name": "Tester"}}],
                                "messages": [
                                    {"from": phone, "id": message_id, "timestamp": "1700000000", "type": "text", "text": {"body": text}}
                                ],
                            }
                        }
                    ]
                }
            ]
        }
    ).encode()


def test_whatsapp_post_rejected_in_live_mode_without_app_secret(client, monkeypatch, silent_whatsapp):
    monkeypatch.setattr(settings, "whatsapp_mode", "live", raising=False)
    monkeypatch.setattr(settings, "whatsapp_token", "EAAtest", raising=False)
    monkeypatch.setattr(settings, "whatsapp_phone_number_id", "123456", raising=False)
    monkeypatch.setattr(settings, "whatsapp_app_secret", "", raising=False)
    response = client.post("/webhook", content=_wa_payload("wamid.LIVE1", "hello"), headers={"Content-Type": "application/json"})
    assert response.status_code in {401, 403, 503}, "live mode me app secret ke bina webhook accept nahi hona chahiye"


def test_whatsapp_post_rejects_bad_signature(client, monkeypatch, silent_whatsapp):
    monkeypatch.setattr(settings, "whatsapp_app_secret", "meta-app-secret", raising=False)
    body = _wa_payload("wamid.SIG1", "hello")
    response = client.post(
        "/webhook", content=body, headers={"Content-Type": "application/json", "X-Hub-Signature-256": "sha256=deadbeef"}
    )
    assert response.status_code == 403


def test_whatsapp_duplicate_delivery_is_processed_once(client, db, monkeypatch, silent_whatsapp):
    monkeypatch.setattr(settings, "whatsapp_app_secret", "", raising=False)
    body = _wa_payload("wamid.DUP123", "2 veg burger")
    headers = {"Content-Type": "application/json"}
    first = client.post("/webhook", content=body, headers=headers)
    second = client.post("/webhook", content=body, headers=headers)
    assert first.status_code == 200 and second.status_code == 200
    db.expire_all()
    inbound_rows = db.scalar(
        select(func.count(Message.id)).where(Message.customer_phone == "919111111111", Message.direction == "in")
    )
    assert inbound_rows == 1, "Meta retry se same message dobara process nahi hona chahiye"
    orders = db.scalar(select(func.count(Order.id)).where(Order.customer_phone == "919111111111"))
    assert orders == 1, "webhook retry se duplicate order nahi banna chahiye"


# ---------------------------------------------------------------------------
# C. Razorpay webhook / payment integrity
# ---------------------------------------------------------------------------
def test_razorpay_webhook_rejects_unsigned_in_live_mode_without_secret(client, db, monkeypatch, silent_whatsapp):
    order, payment = _razorpay_order(db, monkeypatch)
    _live_razorpay(monkeypatch, secret="")
    response = client.post(
        "/webhook/razorpay", content=_rzp_body(payment, order), headers={"Content-Type": "application/json"}
    )
    assert response.status_code in {401, 403, 503}, "live mode me webhook secret ke bina unsigned webhook se payment nahi maanna"
    db.expire_all()
    assert db.get(Order, order.id).payment_status == "pending"


def test_razorpay_webhook_rejects_forged_signature(client, db, monkeypatch, silent_whatsapp):
    order, payment = _razorpay_order(db, monkeypatch)
    _live_razorpay(monkeypatch)
    body = _rzp_body(payment, order)
    response = client.post(
        "/webhook/razorpay",
        content=body,
        headers={"Content-Type": "application/json", "X-Razorpay-Signature": _sign("wrong-secret", body)},
    )
    assert response.status_code == 403
    db.expire_all()
    assert db.get(Order, order.id).payment_status == "pending"


def test_razorpay_duplicate_webhook_has_single_side_effects(client, db, monkeypatch, silent_whatsapp):
    order, payment = _razorpay_order(db, monkeypatch)
    _live_razorpay(monkeypatch)
    body = _rzp_body(payment, order)
    headers = {"Content-Type": "application/json", "X-Razorpay-Signature": _sign(RZP_SECRET, body)}
    assert client.post("/webhook/razorpay", content=body, headers=headers).status_code == 200
    assert client.post("/webhook/razorpay", content=body, headers=headers).status_code == 200
    db.expire_all()
    order = db.get(Order, order.id)
    assert order.payment_status == "paid"
    payment_alerts = db.scalar(select(func.count(Alert.id)).where(Alert.kind == "payment", Alert.order_id == order.id))
    assert payment_alerts == 1, "duplicate webhook se payment alert/thanks dobara nahi jana chahiye"
    thanks = db.scalar(
        select(func.count(Coupon.id)).where(Coupon.source == "thanks", Coupon.customer_phone == clean_phone(NEW_PHONE))
    )
    assert thanks == 1, "duplicate webhook se naya thanks coupon nahi banna chahiye"


def test_razorpay_amount_mismatch_is_not_marked_paid(client, db, monkeypatch, silent_whatsapp):
    order, payment = _razorpay_order(db, monkeypatch)
    _live_razorpay(monkeypatch)
    body = _rzp_body(payment, order, amount_paise=100)  # ₹1 — bill se bahut kam
    headers = {"Content-Type": "application/json", "X-Razorpay-Signature": _sign(RZP_SECRET, body)}
    client.post("/webhook/razorpay", content=body, headers=headers)
    db.expire_all()
    assert db.get(Order, order.id).payment_status == "pending", "amount mismatch par order paid nahi hona chahiye"


def test_mock_payment_endpoints_blocked_in_live_mode(client, db, monkeypatch, silent_whatsapp):
    say(db, NEW_PHONE, "1 veg burger")
    order = db.scalar(select(Order).where(Order.customer_phone == clean_phone(NEW_PHONE)))
    payment = db.scalar(select(Payment).where(Payment.order_id == order.id))
    token = payment.provider_ref.replace("mock_", "")
    _live_razorpay(monkeypatch)
    assert client.post(f"/pay/{token}/confirm", follow_redirects=False).status_code in {403, 404, 409}
    assert client.post(f"/api/demo/simulate-payment/{order.order_no}", headers={}).status_code in {401, 403, 404, 409}
    db.expire_all()
    assert db.get(Order, order.id).payment_status == "pending"


def test_dashboard_cannot_mark_order_paid_manually_in_live_mode(client, db, monkeypatch, silent_whatsapp):
    monkeypatch.setattr(settings, "admin_token", "", raising=False)
    say(db, NEW_PHONE, "1 veg burger")
    _live_razorpay(monkeypatch)
    order = db.scalar(select(Order).where(Order.customer_phone == clean_phone(NEW_PHONE)))
    response = client.patch(f"/api/orders/{order.order_no}", json={"payment_status": "paid"})
    assert response.status_code in {403, 409}
    db.expire_all()
    assert db.get(Order, order.id).payment_status == "pending"


# ---------------------------------------------------------------------------
# D. Marketing consent
# ---------------------------------------------------------------------------
def test_birthday_wish_requires_marketing_consent(db, silent_whatsapp):
    from app import automations

    today = today_ist_date()
    customer = Customer(phone="919333333333", name="No Consent", birthday=today.strftime("%m-%d"), opt_in=False, opted_out=False)
    db.add(customer)
    db.commit()
    result = automations.send_birthday_wishes(db, force=True)
    db.commit()
    assert result["sent"] == 0, "birthday marketing bina opt-in ke nahi jana chahiye"
    assert not any(to == "919333333333" for to, _ in silent_whatsapp)


def test_broadcast_cannot_reach_non_opt_in_customers(client, db, monkeypatch, silent_whatsapp):
    monkeypatch.setattr(settings, "admin_token", "", raising=False)
    db.add(Customer(phone="919444444444", name="Silent", opt_in=False, opted_out=False))
    db.commit()
    response = client.post("/api/campaigns/broadcast", json={"message": "Aaj 20% off!", "only_opt_in": False})
    assert response.status_code in {400, 403, 422} or all(
        to != "919444444444" for to, _ in silent_whatsapp
    ), "broadcast kabhi bhi non-opt-in customer tak nahi pahunchna chahiye"
    assert all(to != "919444444444" for to, _ in silent_whatsapp)


# ---------------------------------------------------------------------------
# E. Order lifecycle and reservations
# ---------------------------------------------------------------------------
def test_invalid_order_status_transition_is_rejected(client, db, monkeypatch, silent_whatsapp):
    monkeypatch.setattr(settings, "admin_token", "", raising=False)
    say(db, NEW_PHONE, "1 veg burger")
    order = db.scalar(select(Order).where(Order.customer_phone == clean_phone(NEW_PHONE)))
    response = client.patch(f"/api/orders/{order.order_no}", json={"order_status": "delivered"})
    assert response.status_code == 409, "awaiting_payment order ko seedha delivered nahi kar sakte"
    db.expire_all()
    assert db.get(Order, order.id).order_status != "delivered"


def test_unknown_order_status_is_rejected(client, db, monkeypatch, silent_whatsapp):
    monkeypatch.setattr(settings, "admin_token", "", raising=False)
    say(db, NEW_PHONE, "1 veg burger")
    order = db.scalar(select(Order).where(Order.customer_phone == clean_phone(NEW_PHONE)))
    response = client.patch(f"/api/orders/{order.order_no}", json={"order_status": "hacked-status"})
    assert response.status_code in {400, 422}


def test_reservation_capacity_is_enforced_via_api(client, db, monkeypatch, silent_whatsapp):
    monkeypatch.setattr(settings, "admin_token", "", raising=False)
    day = (today_ist_date() + timedelta(days=3)).isoformat()
    first = client.post("/api/reservations", json={"name": "A", "phone": "919555555501", "date": day, "time": "19:00", "persons": 20})
    assert first.status_code == 200
    overlap = client.post("/api/reservations", json={"name": "B", "phone": "919555555502", "date": day, "time": "19:30", "persons": 10})
    assert overlap.status_code == 409, "overlapping slot me capacity se zyada booking nahi honi chahiye"
    db.expire_all()
    total = db.scalar(select(func.sum(Reservation.persons)).where(Reservation.status == "confirmed"))
    assert (total or 0) <= orchestrator.MAX_SEATS_PER_SLOT


def test_reservation_capacity_not_bypassed_by_past_or_invalid_date(client, db, monkeypatch, silent_whatsapp):
    monkeypatch.setattr(settings, "admin_token", "", raising=False)
    past = (today_ist_date() - timedelta(days=2)).isoformat()
    response = client.post("/api/reservations", json={"name": "Old", "phone": "919555555503", "date": past, "time": "19:00", "persons": 2})
    assert response.status_code == 400, "beeti hui date par booking nahi honi chahiye"


def test_log_redaction_masks_tokens_and_phones():
    """Logs me token/secret/phone redact hona chahiye (SEC logging)."""
    from app.logging_setup import redact_text

    line = "GET /api/summary?token=supersecret&x=1 phone 919876543210 Authorization: Bearer abc.def"
    out = redact_text(line)
    assert "supersecret" not in out
    assert "919876543210" not in out
    assert "abc.def" not in out
    assert "x=1" in out
    assert out.endswith("Bearer [redacted]")
