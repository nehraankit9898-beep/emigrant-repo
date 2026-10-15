"""Dashboard + Admin API — owner ke liye sab kuch ek jagah.

Saare routes /api ke andar. Agar .env me ADMIN_TOKEN set ho to har request me
`X-Admin-Token` header ya `?token=` chahiye hoga.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import automations, discounts, memory, menu as menu_engine, orchestrator, reports, seed, whatsapp
from .config import settings
from .database import get_db
from .llm import build_system_prompt
from .models import (
    Alert,
    AppSetting,
    Campaign,
    Coupon,
    Customer,
    DiscountRule,
    Feedback,
    MenuItem,
    Message,
    Order,
    Payment,
    Reservation,
)
from .utils import clean_phone, money, now_ist, rupees, title_name, today_ist_date, truncate, utcnow

router = APIRouter(prefix="/api", tags=["dashboard"])


# --------------------------------------------------------------------------
# Auth (demo me optional)
# --------------------------------------------------------------------------
def require_admin(request: Request, x_admin_token: str | None = Header(default=None)) -> None:
    if not settings.admin_token:
        return
    token = x_admin_token or request.query_params.get("token") or request.cookies.get("admin_token")
    if token != settings.admin_token:
        raise HTTPException(status_code=401, detail="Admin token galat hai (X-Admin-Token header bhejiye)")


def _request_base(request: Request | None) -> str | None:
    """Jis host se request aayi (preview/live), usi se payment link banao."""
    if settings.public_base_url:
        return settings.public_base_url
    if request is None:
        return None
    host = request.headers.get("host")
    if not host:
        return None
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme or "http"
    return f"{proto}://{host}"


def _d(value: datetime | None) -> str | None:
    if not value:
        return None
    return (value + timedelta(hours=5, minutes=30)).strftime("%d %b, %I:%M %p")  # IST me dikhao


# --------------------------------------------------------------------------
# Overview
# --------------------------------------------------------------------------
@router.get("/summary", dependencies=[Depends(require_admin)])
def summary(db: Session = Depends(get_db)):
    data = reports.dashboard_summary(db)
    data["restaurant"] = settings.restaurant_name
    data["agent"] = settings.agent_name
    data["tagline"] = settings.restaurant_tagline
    data["recent_alerts"] = [
        {"id": a.id, "kind": a.kind, "message": a.message, "at": _d(a.created_at), "is_read": a.is_read}
        for a in db.scalars(select(Alert).order_by(Alert.id.desc()).limit(6))
    ]
    data["recent_orders"] = [_order_row(o) for o in db.scalars(select(Order).order_by(Order.id.desc()).limit(8))]
    data["automation"] = automations.stats_overview(db)
    return data


@router.get("/health", dependencies=[Depends(require_admin)])
def api_health(db: Session = Depends(get_db)):
    return {
        "modes": settings.mode_report(),
        "customers": db.scalar(select(func.count(Customer.id))) or 0,
        "menu_items": db.scalar(select(func.count(MenuItem.id))) or 0,
        "orders": db.scalar(select(func.count(Order.id))) or 0,
        "messages": db.scalar(select(func.count(Message.id))) or 0,
        "now_ist": now_ist().strftime("%d %b %Y, %I:%M %p"),
    }


# --------------------------------------------------------------------------
# Live chat simulator
# --------------------------------------------------------------------------
@router.get("/messages/{phone}", dependencies=[Depends(require_admin)])
def chat_history(phone: str, limit: int = 100, db: Session = Depends(get_db)):
    phone = clean_phone(phone)
    rows = list(
        db.scalars(select(Message).where(Message.customer_phone == phone).order_by(Message.id.desc()).limit(limit))
    )
    rows.reverse()
    customer = memory.get_customer(db, phone)
    return {
        "phone": phone,
        "name": customer.name if customer else None,
        "human_mode": bool(customer.human_mode) if customer else False,
        "messages": [
            {
                "id": row.id,
                "direction": row.direction,
                "text": row.text,
                "type": row.message_type,
                "intent": row.intent,
                "at": _d(row.created_at),
            }
            for row in rows
        ],
    }


@router.post("/simulate", dependencies=[Depends(require_admin)])
def simulate(payload: dict = Body(...), request: Request = None, db: Session = Depends(get_db)):
    """Live Chat se message bhejo — poora agent pipeline chalega (jaise WhatsApp par)."""
    text = (payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text khaali hai")
    phone = clean_phone(payload.get("phone") or "919876543210")
    name = payload.get("name")
    base_url = str(payload.get("base_url") or "").rstrip("/") or _request_base(request)
    result = orchestrator.simulate_inbound(db, phone, text, profile_name=name, channel="dashboard", base_url=base_url)
    db.commit()
    return {
        "intent": result.intent,
        "replies": [{"text": r.text, "kind": r.kind, "intent": r.intent, "buttons": r.buttons} for r in result.replies],
        "customer": memory.customer_context(db, result.customer) if result.customer else None,
    }


@router.get("/conversations", dependencies=[Depends(require_admin)])
def conversations(db: Session = Depends(get_db)):
    """Jin se baat hui hai unki list (latest pehle)."""
    subq = (
        select(Message.customer_phone, func.max(Message.id).label("last_id"))
        .group_by(Message.customer_phone)
        .subquery()
    )
    rows = db.execute(
        select(Message).join(subq, Message.id == subq.c.last_id).order_by(Message.id.desc()).limit(50)
    ).scalars()
    out: list[dict] = []
    for row in rows:
        customer = memory.get_customer(db, row.customer_phone)
        out.append(
            {
                "phone": row.customer_phone,
                "name": customer.name if customer else None,
                "last_message": truncate(row.text, 60),
                "direction": row.direction,
                "at": _d(row.created_at),
                "human_mode": bool(customer.human_mode) if customer else False,
            }
        )
    return out


@router.get("/outbox", dependencies=[Depends(require_admin)])
def outbox(limit: int = 30):
    """Mock mode me bheje gaye messages (asli WhatsApp ki jagah)."""
    return whatsapp.outbox_tail(limit)


# --------------------------------------------------------------------------
# Orders
# --------------------------------------------------------------------------
def _order_row(order: Order) -> dict:
    return {
        "order_no": order.order_no,
        "phone": order.customer_phone,
        "name": order.customer_name,
        "items": order.items or [],
        "items_text": menu_engine.order_summary_text(order.items or []),
        "subtotal": order.subtotal,
        "discount_amount": order.discount_amount,
        "discount_code": order.discount_code,
        "freebies": order.freebies or [],
        "total": order.total_amount,
        "payment_status": order.payment_status,
        "order_status": order.order_status,
        "channel": order.channel,
        "table": order.table_number,
        "payment_link": order.payment_link,
        "at": _d(order.created_at),
        "created_at": order.created_at.isoformat() if order.created_at else None,
    }


@router.get("/orders", dependencies=[Depends(require_admin)])
def list_orders(
    status: str | None = None,
    payment: str | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    stmt = select(Order).order_by(Order.id.desc()).limit(min(limit, 500))
    if status:
        stmt = stmt.where(Order.order_status == status)
    if payment:
        stmt = stmt.where(Order.payment_status == payment)
    return [_order_row(o) for o in db.scalars(stmt)]


@router.post("/orders", dependencies=[Depends(require_admin)])
def create_manual_order(payload: dict = Body(...), request: Request = None, db: Session = Depends(get_db)):
    """Walk-in / phone order dashboard se daalna (QR/table order bhi)."""
    phone = clean_phone(payload.get("phone") or "")
    name = payload.get("name")
    items_text = payload.get("items_text") or ""
    if not phone and not name:
        raise HTTPException(status_code=400, detail="phone ya naam chahiye")
    if not phone:
        phone = "9199999" + str(abs(hash(name)) % 100000)
    customer, _ = memory.get_or_create_customer(db, phone, name)
    if name:
        memory.remember_name(db, customer, name)

    table = payload.get("table")
    parsed = menu_engine.parse_order_text(db, items_text)
    lines = [{"name": l.name, "qty": l.qty, "unit_price": l.unit_price} for l in parsed.lines if l.matched]
    if not lines and payload.get("items"):
        for row in payload["items"]:
            item = menu_engine.find_item(db, row.get("name", ""))
            if item:
                lines.append({"name": item.name, "qty": int(row.get("qty", 1)), "unit_price": item.price})
    if not lines:
        raise HTTPException(status_code=400, detail=f"koi item match nahi hua. Unmatched: {parsed.unmatched}")

    subtotal = money(sum(line["qty"] * line["unit_price"] for line in lines))
    decision = discounts.evaluate_for_order(db, customer, subtotal)
    is_cod = bool(payload.get("cod"))
    if payload.get("discount_percent") is not None:
        decision["percent"] = float(payload["discount_percent"])
        decision["code"] = payload.get("discount_code") or decision["code"]
        decision["reason"] = "Manual (owner)"
    percent = min(float(decision["percent"] or 0), settings.max_discount_percent)
    order, bill = orchestrator.create_order(
        db,
        customer,
        lines,
        channel=payload.get("channel") or ("qr" if table else "dashboard"),
        table_number=str(table) if table else None,
        discount_percent=percent,
        discount_code=decision.get("code"),
        discount_reason=decision.get("reason"),
        freebies=decision.get("freebies") or [],
        is_cod=is_cod,
        notes=payload.get("notes"),
    )
    message = None
    if not is_cod and payload.get("send_link", True):
        message = orchestrator.payment_message_for(db, order, bill, base_url=_request_base(request))
        whatsapp.send_text(customer.phone, message)
        orchestrator.log_message(db, customer.phone, "out", message, intent="order_bill")
    elif is_cod:
        message = f"Order pakka ho gaya ✅\n\n{bill.text()}"
        whatsapp.send_text(customer.phone, message)
        orchestrator.log_message(db, customer.phone, "out", message, intent="order_cod")
    orchestrator.create_alert(db, "new_order", f"Dashboard order #{order.order_no} — {rupees(order.total_amount)}", order_id=order.id)
    db.commit()
    return {"order": _order_row(order), "bill": bill.text(), "sent_message": message}


@router.patch("/orders/{order_no}", dependencies=[Depends(require_admin)])
def update_order(order_no: str, payload: dict = Body(...), db: Session = Depends(get_db)):
    order = db.scalar(select(Order).where(Order.order_no == str(order_no)))
    if not order:
        raise HTTPException(status_code=404, detail="order nahi mila")
    if payload.get("order_status"):
        orchestrator.advance_order_status(db, order, payload["order_status"], deliver_reply=bool(payload.get("notify", True)))
    if payload.get("payment_status") == "paid" or payload.get("mark_paid"):
        payment = db.scalar(select(Payment).where(Payment.order_id == order.id).order_by(Payment.id.desc()))
        if payment:
            from . import payments as pay_engine

            pay_engine.mark_paid(db, payment, via="dashboard")
            orchestrator.on_payment_success(db, order, via="dashboard")
        else:
            order.payment_status = "paid"
            order.paid_at = utcnow()
            memory.apply_order_to_memory(db, memory.get_or_create_customer(db, order.customer_phone)[0], order)
    db.commit()
    return _order_row(order)


@router.post("/orders/{order_no}/resend-link", dependencies=[Depends(require_admin)])
def resend_link(order_no: str, request: Request = None, db: Session = Depends(get_db)):
    order = db.scalar(select(Order).where(Order.order_no == str(order_no)))
    if not order:
        raise HTTPException(status_code=404, detail="order nahi mila")
    customer = memory.get_or_create_customer(db, order.customer_phone)[0]
    bill = orchestrator.build_bill(
        db,
        [
            dict(name=row.get("name"), qty=row.get("qty", 1), unit_price=row.get("price", 0), is_freebie=row.get("free", False))
            for row in (order.items or [])
        ],
    )
    message = orchestrator.payment_message_for(db, order, bill, base_url=_request_base(request))
    whatsapp.send_text(customer.phone, message)
    orchestrator.log_message(db, customer.phone, "out", message, intent="payment_link")
    db.commit()
    return {"sent": True, "message": message, "link": order.payment_link}


# --------------------------------------------------------------------------
# Menu
# --------------------------------------------------------------------------
@router.get("/menu", dependencies=[Depends(require_admin)])
def get_menu(db: Session = Depends(get_db)):
    items = list(db.scalars(select(MenuItem).order_by(MenuItem.category, MenuItem.name)))
    return [
        {
            "id": i.id,
            "name": i.name,
            "price": i.price,
            "category": i.category,
            "is_veg": i.is_veg,
            "is_available": i.is_available,
            "is_signature": i.is_signature,
            "description": i.description,
            "aliases": i.aliases or [],
            "sold_count": i.sold_count,
        }
        for i in items
    ]


@router.post("/menu", dependencies=[Depends(require_admin)])
def add_menu_item(payload: dict = Body(...), db: Session = Depends(get_db)):
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="item ka naam chahiye")
    if db.scalar(select(MenuItem).where(func.lower(MenuItem.name) == name.lower())):
        raise HTTPException(status_code=400, detail="ye item pehle se menu me hai")
    item = MenuItem(
        name=name,
        price=float(payload.get("price") or 0),
        category=payload.get("category") or "Other",
        is_veg=bool(payload.get("is_veg", True)),
        is_available=bool(payload.get("is_available", True)),
        is_signature=bool(payload.get("is_signature", False)),
        description=payload.get("description"),
        aliases=payload.get("aliases") or [],
    )
    db.add(item)
    db.commit()
    return {"id": item.id, "name": item.name, "price": item.price}


@router.patch("/menu/{item_id}", dependencies=[Depends(require_admin)])
def update_menu_item(item_id: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    item = db.get(MenuItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="item nahi mila")
    for field in ("name", "category", "description"):
        if payload.get(field) is not None:
            setattr(item, field, payload[field])
    for field in ("price", "is_veg", "is_available", "is_signature", "sold_count"):
        if payload.get(field) is not None:
            setattr(item, field, payload[field] if field != "price" else float(payload[field]))
    if payload.get("aliases") is not None:
        item.aliases = payload["aliases"]
    db.commit()
    return {"id": item.id, "updated": True, "is_available": item.is_available}


@router.delete("/menu/{item_id}", dependencies=[Depends(require_admin)])
def delete_menu_item(item_id: int, db: Session = Depends(get_db)):
    item = db.get(MenuItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="item nahi mila")
    item.is_available = False  # delete ki jagah hide (purana order hisaab na bigde)
    db.commit()
    return {"id": item_id, "hidden": True}


@router.get("/menu/preview", dependencies=[Depends(require_admin)])
def menu_preview(db: Session = Depends(get_db)):
    """WhatsApp par jo menu jayega, wahi text."""
    return {"text": menu_engine.menu_text(db), "categories": menu_engine.menu_categories(db)}


# --------------------------------------------------------------------------
# Discount rules
# --------------------------------------------------------------------------
@router.get("/rules", dependencies=[Depends(require_admin)])
def get_rules(db: Session = Depends(get_db)):
    rules = list(db.scalars(select(DiscountRule).order_by(DiscountRule.priority)))
    return [
        {
            "id": r.id,
            "code": r.code,
            "name": r.name,
            "trigger": r.trigger,
            "condition": r.condition,
            "reward": r.reward,
            "message": r.message,
            "is_active": r.is_active,
            "priority": r.priority,
            "used_count": r.used_count,
        }
        for r in rules
    ]


@router.post("/rules", dependencies=[Depends(require_admin)])
def create_rule(payload: dict = Body(...), db: Session = Depends(get_db)):
    rule = DiscountRule(
        code=(payload.get("code") or None),
        name=payload.get("name") or "Naya rule",
        trigger=payload.get("trigger") or "manual",
        condition=payload.get("condition") or {},
        reward=payload.get("reward") or {"type": "percent", "value": 5},
        message=payload.get("message"),
        is_active=bool(payload.get("is_active", True)),
        priority=int(payload.get("priority") or 100),
    )
    db.add(rule)
    db.commit()
    return {"id": rule.id, "name": rule.name}


@router.patch("/rules/{rule_id}", dependencies=[Depends(require_admin)])
def update_rule(rule_id: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    rule = db.get(DiscountRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="rule nahi mila")
    for field in ("code", "name", "trigger", "condition", "reward", "message", "is_active", "priority"):
        if payload.get(field) is not None:
            setattr(rule, field, payload[field])
    db.commit()
    return {"id": rule.id, "updated": True, "is_active": rule.is_active}


@router.delete("/rules/{rule_id}", dependencies=[Depends(require_admin)])
def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    rule = db.get(DiscountRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="rule nahi mila")
    db.delete(rule)
    db.commit()
    return {"deleted": True}


# --------------------------------------------------------------------------
# Coupons
# --------------------------------------------------------------------------
@router.get("/coupons", dependencies=[Depends(require_admin)])
def list_coupons(db: Session = Depends(get_db)):
    rows = db.scalars(select(Coupon).order_by(Coupon.id.desc()).limit(100))
    return [
        {
            "code": c.code,
            "percent": c.discount_percent,
            "free_item": c.free_item_name,
            "phone": c.customer_phone,
            "source": c.source,
            "is_used": c.is_used,
            "expiry": _d(c.expiry_date),
            "at": _d(c.created_at),
        }
        for c in rows
    ]


@router.post("/coupons", dependencies=[Depends(require_admin)])
def make_coupon(payload: dict = Body(...), db: Session = Depends(get_db)):
    coupon = discounts.issue_coupon(
        db,
        percent=float(payload.get("percent") or 0),
        source=payload.get("source") or "manual",
        customer_phone=clean_phone(payload["phone"]) if payload.get("phone") else None,
        code=(payload.get("code") or None),
        free_item_name=payload.get("free_item"),
        valid_days=int(payload.get("valid_days") or 30),
        min_bill_amount=float(payload.get("min_bill_amount") or 0),
    )
    db.commit()
    return {"code": coupon.code, "percent": coupon.discount_percent, "free_item": coupon.free_item_name}


# --------------------------------------------------------------------------
# Customers / memory
# --------------------------------------------------------------------------
@router.get("/customers", dependencies=[Depends(require_admin)])
def list_customers(q: str | None = None, segment: str | None = None, db: Session = Depends(get_db)):
    if q:
        rows = memory.find_by_name(db, q)
    elif segment == "winback":
        rows = memory.winback_candidates(db)
    elif segment == "birthday":
        rows = memory.upcoming_birthdays(db, within_days=7)
    elif segment == "optin":
        rows = memory.all_customers(db, only_opt_in=True)
    else:
        rows = memory.all_customers(db)
    return [
        {
            **memory.customer_context(db, c),
            "last_seen": _d(c.last_seen_at),
            "opt_in": c.opt_in,
            "opted_out": c.opted_out,
            "blocked": c.blocked,
            "favourite": (c.favourite_items or [{}])[0].get("name") if c.favourite_items else None,
        }
        for c in rows[:200]
    ]


@router.get("/customers/{phone}", dependencies=[Depends(require_admin)])
def customer_detail(phone: str, db: Session = Depends(get_db)):
    customer = memory.get_customer(db, phone)
    if not customer:
        raise HTTPException(status_code=404, detail="customer nahi mila")
    return memory.customer_profile(db, customer)


@router.patch("/customers/{phone}", dependencies=[Depends(require_admin)])
def update_customer(phone: str, payload: dict = Body(...), db: Session = Depends(get_db)):
    customer = memory.get_customer(db, phone)
    if not customer:
        raise HTTPException(status_code=404, detail="customer nahi mila")
    if payload.get("name"):
        memory.remember_name(db, customer, title_name(payload["name"]) or "")
    if payload.get("birthday"):
        customer.birthday = payload["birthday"]
    if payload.get("note"):
        memory.remember_note(customer, payload["note"])
    if payload.get("human_mode") is not None:
        customer.human_mode = bool(payload["human_mode"])
    if payload.get("opt_in") is not None:
        customer.opt_in = bool(payload["opt_in"])
        customer.opted_out = not bool(payload["opt_in"])
    if payload.get("blocked") is not None:
        customer.blocked = bool(payload["blocked"])
    if payload.get("add_points"):
        customer.loyalty_points = int(customer.loyalty_points or 0) + int(payload["add_points"])
    db.commit()
    return memory.customer_context(db, customer)


# --------------------------------------------------------------------------
# Reservations
# --------------------------------------------------------------------------
@router.get("/reservations", dependencies=[Depends(require_admin)])
def list_reservations(upcoming: bool = False, db: Session = Depends(get_db)):
    stmt = select(Reservation).order_by(Reservation.date.desc(), Reservation.time).limit(200)
    if upcoming:
        stmt = stmt.where(Reservation.date >= today_ist_date(), Reservation.status == "confirmed")
    return [
        {
            "id": r.id,
            "name": r.customer_name,
            "phone": r.customer_phone,
            "date": str(r.date),
            "time": r.time,
            "persons": r.persons,
            "status": r.status,
            "notes": r.notes,
            "reminder_sent": r.reminder_sent,
        }
        for r in db.scalars(stmt)
    ]


@router.post("/reservations", dependencies=[Depends(require_admin)])
def create_reservation(payload: dict = Body(...), db: Session = Depends(get_db)):
    """Owner/staff khud booking daal sake (phone call par aayi booking)."""
    phone = clean_phone(payload.get("phone") or "")
    name = payload.get("name")
    if not phone:
        if not name:
            raise HTTPException(status_code=400, detail="phone ya naam chahiye")
        phone = "9199998" + str(abs(hash(name)) % 100000)
    customer, _ = memory.get_or_create_customer(db, phone, name)
    if name:
        memory.remember_name(db, customer, title_name(name) or "")
    try:
        day = date.fromisoformat(payload.get("date") or str(today_ist_date()))
    except ValueError:
        raise HTTPException(status_code=400, detail="date format YYYY-MM-DD hona chahiye")
    reservation = Reservation(
        customer_phone=phone,
        customer_name=customer.name,
        date=day,
        time=payload.get("time") or "19:00",
        persons=int(payload.get("persons") or 2),
        status="confirmed",
        notes=payload.get("notes"),
    )
    db.add(reservation)
    db.commit()
    return {"id": reservation.id, "date": str(reservation.date), "time": reservation.time}


@router.patch("/reservations/{reservation_id}", dependencies=[Depends(require_admin)])
def update_reservation(reservation_id: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    reservation = db.get(Reservation, reservation_id)
    if not reservation:
        raise HTTPException(status_code=404, detail="booking nahi mili")
    if payload.get("status"):
        reservation.status = payload["status"]
    if payload.get("notify"):
        text = {
            "cancelled": "Sir aapki table booking cancel kar di gayi hai. Koi baat nahi, agli baar 😄",
            "confirmed": f"Table confirm ✅ {reservation.date} {reservation.time} — {reservation.persons} log",
        }.get(reservation.status)
        if text:
            whatsapp.send_text(reservation.customer_phone, text)
            orchestrator.log_message(db, reservation.customer_phone, "out", text, intent="reservation_update")
    db.commit()
    return {"id": reservation.id, "status": reservation.status}


# --------------------------------------------------------------------------
# Feedback & alerts
# --------------------------------------------------------------------------
@router.get("/feedback", dependencies=[Depends(require_admin)])
def list_feedback(db: Session = Depends(get_db)):
    rows = db.scalars(select(Feedback).order_by(Feedback.id.desc()).limit(100))
    return [
        {
            "id": f.id,
            "name": f.customer_name,
            "phone": f.customer_phone,
            "rating": f.rating,
            "comment": f.comment,
            "at": _d(f.created_at),
        }
        for f in rows
    ]


@router.get("/alerts", dependencies=[Depends(require_admin)])
def list_alerts(unread_only: bool = False, db: Session = Depends(get_db)):
    stmt = select(Alert).order_by(Alert.id.desc()).limit(100)
    if unread_only:
        stmt = stmt.where(Alert.is_read.is_(False))
    return [
        {"id": a.id, "kind": a.kind, "message": a.message, "phone": a.customer_phone, "at": _d(a.created_at), "is_read": a.is_read}
        for a in db.scalars(stmt)
    ]


@router.post("/alerts/{alert_id}/read", dependencies=[Depends(require_admin)])
def read_alert(alert_id: int, db: Session = Depends(get_db)):
    alert = db.get(Alert, alert_id)
    if alert:
        alert.is_read = True
        db.commit()
    return {"ok": True}


@router.post("/alerts/read-all", dependencies=[Depends(require_admin)])
def read_all_alerts(db: Session = Depends(get_db)):
    for alert in db.scalars(select(Alert).where(Alert.is_read.is_(False))):
        alert.is_read = True
    db.commit()
    return {"ok": True}


# --------------------------------------------------------------------------
# Campaigns (birthday / winback / broadcast)
# --------------------------------------------------------------------------
@router.get("/campaigns", dependencies=[Depends(require_admin)])
def list_campaigns(db: Session = Depends(get_db)):
    rows = db.scalars(select(Campaign).order_by(Campaign.id.desc()).limit(50))
    return [
        {
            "id": c.id,
            "name": c.name,
            "kind": c.kind,
            "message": c.message,
            "audience": c.audience_count,
            "sent": c.sent_count,
            "skipped": c.skipped_count,
            "status": c.status,
            "at": _d(c.created_at),
            "sent_at": _d(c.sent_at),
        }
        for c in rows
    ]


@router.post("/campaigns/birthday", dependencies=[Depends(require_admin)])
def run_birthday(db: Session = Depends(get_db)):
    result = automations.send_birthday_wishes(db)
    db.commit()
    return result


@router.post("/campaigns/winback", dependencies=[Depends(require_admin)])
def run_winback(force: bool = False, db: Session = Depends(get_db)):
    result = automations.send_winback_offers(db, force=force)
    db.commit()
    return result


@router.post("/campaigns/broadcast", dependencies=[Depends(require_admin)])
def run_broadcast(payload: dict = Body(...), db: Session = Depends(get_db)):
    message = (payload.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message khaali hai")
    result = automations.send_broadcast(db, message, only_opt_in=bool(payload.get("only_opt_in", True)))
    db.commit()
    return result


@router.get("/campaigns/preview", dependencies=[Depends(require_admin)])
def campaign_preview(db: Session = Depends(get_db)):
    """Bhejne se pehle audience ka hisaab — kitne opt-in, kitne skip honge."""
    all_c = memory.all_customers(db)
    optin = [c for c in all_c if c.opt_in and not c.opted_out]
    return {
        "total": len(all_c),
        "opt_in": len(optin),
        "opted_out": len([c for c in all_c if c.opted_out]),
        "winback_count": len(memory.winback_candidates(db)),
        "birthday_today": len(memory.upcoming_birthdays(db, 0)),
        "birthday_week": len(memory.upcoming_birthdays(db, 6)),
        "limit_per_day": settings.max_proactive_per_day,
    }


# --------------------------------------------------------------------------
# Automation & reports
# --------------------------------------------------------------------------
@router.post("/automations/run", dependencies=[Depends(require_admin)])
def run_automation(force: bool = True, db: Session = Depends(get_db)):
    result = automations.run_due_tasks(db, force=force)
    return result


@router.get("/automations/status", dependencies=[Depends(require_admin)])
def automation_status(db: Session = Depends(get_db)):
    return {
        **automations.stats_overview(db),
        "scheduler_interval_seconds": int(__import__("os").getenv("SCHEDULER_INTERVAL_SECONDS", "45")),
        "pipeline": automations.STATUS_FLOW,
    }


@router.get("/reports/daily", dependencies=[Depends(require_admin)])
def daily_report(day: str | None = None, db: Session = Depends(get_db)):
    parsed = None
    if day:
        try:
            parsed = date.fromisoformat(day)
        except ValueError:
            raise HTTPException(status_code=400, detail="date format YYYY-MM-DD")
    data = reports.daily_report(db, parsed)
    data["text"] = reports.daily_report_text(db, parsed)
    return data


@router.get("/reports/weekly", dependencies=[Depends(require_admin)])
def weekly_report(db: Session = Depends(get_db)):
    return reports.weekly_summary(db)


@router.post("/reports/send", dependencies=[Depends(require_admin)])
def send_report(db: Session = Depends(get_db)):
    result = reports.send_owner_report(db)
    db.commit()
    return {"sent": result["sent"], "text": result["text"]}


# --------------------------------------------------------------------------
# Settings & system prompt
# --------------------------------------------------------------------------
@router.get("/settings", dependencies=[Depends(require_admin)])
def get_settings(db: Session = Depends(get_db)):
    overrides = {row.key: row.value for row in db.scalars(select(AppSetting))}
    return {
        "restaurant": {
            "name": settings.restaurant_name,
            "city": settings.restaurant_city,
            "address": settings.restaurant_address,
            "phone": settings.restaurant_phone,
            "hours": settings.restaurant_hours,
            "tagline": settings.restaurant_tagline,
            "google_review_link": settings.google_review_link,
        },
        "agent": {"name": settings.agent_name, "persona_extra": settings.agent_persona_extra},
        "money": {
            "gst_percent": settings.gst_percent,
            "max_discount_percent": settings.max_discount_percent,
            "loyalty_points_per_100": settings.loyalty_points_per_100,
            "free_coffee_points": settings.free_coffee_points,
        },
        "automation": {
            "enabled": settings.automation_enabled,
            "owner_report_time": settings.owner_report_time,
            "birthday_time": settings.birthday_time,
            "winback_days": settings.winback_days,
            "max_proactive_per_day": settings.max_proactive_per_day,
        },
        "modes": settings.mode_report(),
        "overrides": overrides,
        "prompt": build_system_prompt(),
    }


@router.put("/settings", dependencies=[Depends(require_admin)])
def update_settings(payload: dict = Body(...), db: Session = Depends(get_db)):
    """Runtime settings — DB me save (server restart ke bina)."""
    allowed = {"restaurant", "agent", "money", "automation", "templates"}
    saved: dict[str, Any] = {}
    for key, value in payload.items():
        if key not in allowed:
            continue
        row = db.get(AppSetting, key)
        if row:
            row.value = {**(row.value or {}), **(value or {})}
        else:
            db.add(AppSetting(key=key, value=value or {}))
        saved[key] = value

    # kuch cheezein live settings par bhi apply karo (persona + profile)
    if "agent" in payload and payload["agent"]:
        settings.agent_persona_extra = payload["agent"].get("persona_extra", settings.agent_persona_extra)
    if "restaurant" in payload and payload["restaurant"]:
        settings.google_review_link = payload["restaurant"].get("google_review_link", settings.google_review_link)
        settings.restaurant_hours = payload["restaurant"].get("hours", settings.restaurant_hours)
    db.commit()
    return {"saved": saved}


@router.get("/prompt", dependencies=[Depends(require_admin)])
def get_prompt():
    return {"prompt": build_system_prompt()}


# --------------------------------------------------------------------------
# Demo / system
# --------------------------------------------------------------------------
@router.post("/demo/reset", dependencies=[Depends(require_admin)])
def demo_reset(db: Session = Depends(get_db)):
    result = seed.reset_demo(db)
    return {"reset": True, "result": result}


@router.post("/demo/simulate-payment/{order_no}", dependencies=[Depends(require_admin)])
def simulate_payment(order_no: str, db: Session = Depends(get_db)):
    order = db.scalar(select(Order).where(Order.order_no == str(order_no)))
    if not order:
        raise HTTPException(status_code=404, detail="order nahi mila")
    from . import payments as pay_engine

    payment = db.scalar(select(Payment).where(Payment.order_id == order.id).order_by(Payment.id.desc()))
    if not payment:
        bill = orchestrator.build_bill(
            db,
            [dict(name=row.get("name"), qty=row.get("qty", 1), unit_price=row.get("price", 0)) for row in (order.items or [])],
        )
        payment = pay_engine.create_payment(db, order, base_url=None)
    pay_engine.mark_paid(db, payment, via="dashboard_simulate")
    replies = orchestrator.on_payment_success(db, order, via="dashboard_simulate")
    db.commit()
    return {"paid": True, "replies": [r.text for r in replies]}


@router.get("/demo/whatsapp-payload", dependencies=[Depends(require_admin)])
def whatsapp_payload_preview(phone: str = "919876543210"):
    """Report me dikhaya gaya asli Graph API request body (seekhne ke liye)."""
    return {"payload": whatsapp.graph_payload_preview(phone, "Namaste! Menu ye raha...")}
