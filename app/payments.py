"""Payment engine — Razorpay (live) ya local mock page (demo).

Report ka Section 16 wala poora safar:
  order confirm -> bill -> payment link -> customer UPI se pay -> webhook
  -> thank you message + agla offer code.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import Order, Payment
from .utils import money, rupees, utcnow

RAZORPAY_API = "https://api.razorpay.com/v1"


def _base_url() -> str:
    """Payment link ka adhaar. Live me PUBLIC_BASE_URL (.env) set karo — jaise https://agent.sharmacafe.in"""
    if settings.public_base_url:
        return settings.public_base_url
    return f"http://localhost:{settings.port}"


def create_payment(db: Session, order: Order, base_url: str | None = None) -> Payment:
    """Order ke liye payment banayo. Live: Razorpay link. Demo: local page."""
    base_url = (base_url or _base_url()).rstrip("/")
    if settings.payment_live:
        link, ref = _razorpay_create_link(order)
        provider = "razorpay"
    else:
        token = secrets.token_urlsafe(12)
        link = f"{base_url}/pay/{token}"
        ref = f"mock_{token}"
        provider = "mock"

    payment = Payment(
        order_id=order.id,
        amount=order.total_amount,
        provider=provider,
        provider_ref=ref,
        link=link,
        status="created",
    )
    db.add(payment)
    order.payment_link = link
    order.payment_ref = ref
    db.flush()
    return payment


def _razorpay_create_link(order: Order) -> tuple[str, str]:
    """POST https://api.razorpay.com/v1/payment_links — amount paise me (₹640 = 64000)."""
    payload = {
        "amount": int(round(float(order.total_amount) * 100)),
        "currency": "INR",
        "accept_partial": False,
        "description": f"{settings.restaurant_name} Order #{order.order_no}",
        "reference_id": f"order_{order.order_no}",
        "customer": {"name": order.customer_name or "Customer", "contact": f"+{order.customer_phone}"},
        "notify": {"sms": False, "email": False},
        "reminder_enable": True,
        "notes": {"order_no": order.order_no, "source": "whatsapp_agent"},
        "callback_url": f"{_base_url()}/webhook/razorpay",
        "callback_method": "get",
    }
    try:
        with httpx.Client(timeout=25) as client:
            response = client.post(
                f"{RAZORPAY_API}/payment_links",
                json=payload,
                auth=(settings.razorpay_key_id, settings.razorpay_key_secret),
            )
            response.raise_for_status()
            data = response.json()
        return data.get("short_url") or data.get("id", ""), data.get("id", "")
    except Exception as exc:
        # Razorpay down / key galat — mock page par gir jao taaki kaam ruke nahi
        token = secrets.token_urlsafe(12)
        return f"{_base_url()}/pay/{token}", f"fallback_{token} ({str(exc)[:80]})"


def payment_by_token(db: Session, token: str) -> tuple[Payment | None, Order | None]:
    """Mock payment page ke liye token se payment dhundo."""
    if not token:
        return None, None
    payments = db.scalars(select(Payment).where(Payment.provider == "mock").order_by(Payment.id.desc()).limit(200))
    for payment in payments:
        if (payment.provider_ref or "").endswith(token) or (payment.link or "").endswith(token):
            order = db.get(Order, payment.order_id)
            return payment, order
    return None, None


def mark_paid(db: Session, payment: Payment, ref: str | None = None, via: str = "webhook") -> Order | None:
    """Payment success — idempotent (ek hi baar asar karega)."""
    if payment.status == "paid":
        return db.get(Order, payment.order_id)
    payment.status = "paid"
    payment.paid_at = utcnow()
    if ref:
        payment.provider_ref = ref
    order = db.get(Order, payment.order_id)
    if order:
        order.payment_status = "paid"
        order.paid_at = utcnow()
        if order.order_status in {"placed", "awaiting_payment"}:
            order.order_status = "confirmed"
        order.payment_ref = payment.provider_ref
    db.flush()
    return order


def find_payment(db: Session, provider_ref: str | None = None, order_no: str | None = None) -> Payment | None:
    if provider_ref:
        payment = db.scalar(select(Payment).where(Payment.provider_ref == provider_ref))
        if payment:
            return payment
    if order_no:
        order = db.scalar(select(Order).where(Order.order_no == order_no))
        if order:
            return db.scalar(select(Payment).where(Payment.order_id == order.id).order_by(Payment.id.desc()))
    return None


def verify_razorpay_signature(body: bytes, signature: str | None) -> bool:
    """Razorpay webhook signature check (X-Razorpay-Signature)."""
    secret = settings.razorpay_webhook_secret or settings.razorpay_key_secret
    if not secret:
        return True  # demo mode
    if not signature:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def parse_razorpay_event(body: bytes) -> dict:
    """Webhook body -> aasan dict (payment_link.paid / payment.captured dono handle)."""
    try:
        data = json.loads(body or b"{}")
    except json.JSONDecodeError:
        return {}
    event = data.get("event", "")
    entity = (((data.get("payload") or {}).get("payment_link") or {}).get("entity") or {})
    if not entity:
        entity = (((data.get("payload") or {}).get("payment") or {}).get("entity") or {})
    notes = entity.get("notes") or {}
    return {
        "event": event,
        "provider_ref": entity.get("id"),
        "reference_id": entity.get("reference_id"),
        "order_no": notes.get("order_no") or (entity.get("reference_id") or "").replace("order_", ""),
        "amount": (entity.get("amount") or entity.get("amount_paid") or 0) / 100,
        "status": entity.get("status"),
        "paid": bool(entity.get("status") in {"paid", "captured"} or event in {"payment_link.paid", "payment.captured"}),
    }


def mock_pay_page_html(payment: Payment, order: Order | None, restaurant: str) -> str:
    """Demo payment page (asli UPI ki jagah) — button dabao, payment success."""
    amount = rupees(payment.amount)
    upi = settings.upi_id
    order_no = order.order_no if order else "-"
    items_html = ""
    if order and order.items:
        rows = "".join(
            f"<tr><td>{row.get('name')}</td><td style='text-align:center'>{row.get('qty')}</td>"
            f"<td style='text-align:right'>{rupees(float(row.get('line_total', 0)))}</td></tr>"
            for row in order.items
        )
        items_html = f"""
        <table class="items">
          <thead><tr><th>Item</th><th>Qty</th><th style="text-align:right">Amount</th></tr></thead>
          <tbody>{rows}</tbody>
        </table>"""
    return f"""<!doctype html>
<html lang="hi"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{restaurant} — Payment</title>
<style>
  :root {{ color-scheme: light dark; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; font-family: -apple-system, "Segoe UI", Roboto, sans-serif; background:#f6f7fb;
         display:flex; align-items:center; justify-content:center; min-height:100vh; padding:16px; }}
  .card {{ background:#fff; max-width:420px; width:100%; border-radius:18px; padding:26px;
           box-shadow:0 18px 50px rgba(15,23,42,.12); }}
  h1 {{ font-size:19px; margin:0 0 4px; }}
  .sub {{ color:#64748b; font-size:13px; margin-bottom:18px; }}
  .amount {{ font-size:34px; font-weight:700; margin:10px 0 4px; }}
  .items {{ width:100%; border-collapse:collapse; margin:14px 0 18px; font-size:14px; }}
  .items th {{ text-align:left; color:#64748b; font-weight:600; font-size:12px;
               border-bottom:1px solid #e2e8f0; padding-bottom:6px; }}
  .items td {{ padding:6px 0; border-bottom:1px dashed #eef2f7; }}
  .upi {{ background:#f8fafc; border:1px dashed #cbd5e1; border-radius:12px; padding:12px;
          font-size:13px; color:#475569; margin-bottom:16px; }}
  button {{ width:100%; border:0; border-radius:12px; padding:15px; font-size:16px; font-weight:600;
            color:#fff; background:linear-gradient(135deg,#22c55e,#15803d); cursor:pointer; }}
  button:active {{ transform:scale(.99); }}
  .badge {{ display:inline-block; background:#ecfdf5; color:#15803d; font-size:12px;
            padding:4px 10px; border-radius:999px; margin-bottom:8px; }}
  .foot {{ font-size:12px; color:#94a3b8; margin-top:14px; text-align:center; }}
</style></head>
<body><div class="card">
  <span class="badge">🧪 Demo Payment (mock mode)</span>
  <h1>{restaurant}</h1>
  <div class="sub">Order #{order_no} — UPI se pay kijiye</div>
  <div class="amount">{amount}</div>
  <div class="sub">Razorpay live mode me asli UPI link yahan khulega.</div>
  {items_html}
  <div class="upi">UPI ID: <b>{upi}</b><br>Amount: <b>{amount}</b></div>
  <form method="post" action="/pay/{payment.provider_ref or ''}/confirm">
    <button type="submit">Pay {amount} karo ✅</button>
  </form>
  <div class="foot">Payment hone par WhatsApp par thanks message chala jayega.</div>
</div></body></html>"""


def payment_success_footer(order: Order) -> str:
    return f"Payment mil gaya ✅ Order #{order.order_no} — {rupees(order.total_amount)}"


def expiry_time(days: int = 1) -> datetime:
    return utcnow() + timedelta(days=days)


def safe_amount(value: float) -> float:
    return money(value)
