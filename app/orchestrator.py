"""Orchestrator — asli "dimaag". Har message yahan se guzarta hai.

Safar (report Section 6 wala diagram):
  WhatsApp -> webhook -> yahi file -> memory -> intent -> menu/bill/discount
  -> AI se andaaz -> WhatsApp reply -> database me sab save
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import date as date_cls

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import discounts, intent as intent_engine, llm, memory, menu as menu_engine, payments, reservations, whatsapp
from .security import audit
from .config import settings
from .models import Alert, Customer, Feedback, MenuItem, Message, Order, OrderItem, Payment, Reservation
from . import pricing
from .pricing import Bill, build_bill
from .utils import (
    clean_phone,
    detect_language,
    now_ist,
    rupees,
    today_ist_date,
    truncate,
    utcnow,
)

MAX_SEATS_PER_SLOT = 24  # legacy alias; asli limit settings.reservation_max_seats (RESERVATION_MAX_SEATS)

# Kitchen / order lifecycle — sirf ye transitions allowed hain. Payment settle hone par
# awaiting_payment -> confirmed automatically hota hai (payments.settle_payment).
ORDER_TRANSITIONS: dict[str, set[str]] = {
    "placed": {"confirmed", "cancelled"},
    "awaiting_payment": {"confirmed", "cancelled"},
    "confirmed": {"preparing", "cancelled"},
    "preparing": {"packed", "cancelled"},
    "packed": {"out_for_delivery", "served", "delivered"},
    "out_for_delivery": {"delivered"},
    "served": {"completed"},
    "delivered": {"completed"},
    "completed": set(),
    "cancelled": set(),
}
ORDER_STATUSES = set(ORDER_TRANSITIONS)


class OrderTransitionError(ValueError):
    """Order status change allowed nahi."""


def validate_order_transition(current: str, new: str) -> None:
    if new not in ORDER_STATUSES:
        raise OrderTransitionError(f"unknown status: {new}")
    if new == current:
        return
    if new not in ORDER_TRANSITIONS.get(current, set()):
        raise OrderTransitionError(f"{current} se {new} allowed nahi hai")


# --------------------------------------------------------------------------
@dataclass
class Reply:
    text: str = ""
    kind: str = "text"  # text | buttons | template | image | none
    buttons: list[dict] = field(default_factory=list)
    intent: str = "unknown"
    meta: dict = field(default_factory=dict)


@dataclass
class HandleResult:
    customer: Customer
    intent: str
    replies: list[Reply] = field(default_factory=list)
    meta: dict = field(default_factory=dict)


# --------------------------------------------------------------------------
# Chhote helpers
# --------------------------------------------------------------------------
def is_owner(phone: str) -> bool:
    return clean_phone(phone) == clean_phone(settings.owner_whatsapp)


def is_staff(phone: str) -> bool:
    phone = clean_phone(phone)
    return phone in {clean_phone(settings.owner_whatsapp), clean_phone(settings.staff_whatsapp)}


def create_alert(
    db: Session,
    kind: str,
    message: str,
    customer_phone: str | None = None,
    order_id: int | None = None,
    notify_owner: bool = True,
) -> Alert:
    """Owner/staff ko alert — database me save + WhatsApp par (agar owner number set ho)."""
    alert = Alert(kind=kind, message=message, customer_phone=customer_phone, order_id=order_id)
    db.add(alert)
    db.flush()
    if notify_owner and settings.owner_whatsapp:
        prefix = {"complaint": "🚨 COMPLAINT", "new_order": "🧾 NAYA ORDER", "payment": "💰 PAYMENT", "handover": "🙋 HANDOVER", "party": "🎉 PARTY BOOKING"}.get(kind, "🔔 ALERT")
        whatsapp.send_text(settings.owner_whatsapp, f"{prefix}\n{message}")
    return alert


def log_message(
    db: Session,
    phone: str,
    direction: str,
    text: str,
    message_type: str = "text",
    intent: str | None = None,
    channel: str = "whatsapp",
    meta: dict | None = None,
) -> Message:
    row = Message(
        customer_phone=clean_phone(phone),
        direction=direction,
        text=text or "",
        message_type=message_type,
        intent=intent,
        channel=channel,
        meta=meta,
    )
    db.add(row)
    db.flush()
    return row


def deliver(db: Session, customer: Customer, reply: Reply) -> None:
    """Reply ko WhatsApp par bhejo (aur database me log karo)."""
    if not reply or reply.kind == "none" or not reply.text:
        return
    phone = customer.phone
    if reply.kind == "buttons" and reply.buttons:
        whatsapp.send_buttons(phone, reply.text, reply.buttons)
    else:
        whatsapp.send_text(phone, reply.text)
    log_message(db, phone, "out", reply.text, message_type=reply.kind if reply.kind != "none" else "text", intent=reply.intent, meta=reply.meta)


def recent_history(db: Session, phone: str, limit: int = 10) -> list[dict]:
    rows = list(
        db.scalars(select(Message).where(Message.customer_phone == clean_phone(phone)).order_by(Message.id.desc()).limit(limit))
    )
    rows.reverse()
    return [{"role": "user" if row.direction == "in" else "assistant", "content": row.text} for row in rows if row.text]


def _gap_text(customer: Customer) -> str:
    days = memory.nights_since_last_visit(customer)
    if not days:
        return ""
    if days >= 20:
        return f"{days} din"
    return f"{days} din"


def _last_item_name(customer: Customer) -> str:
    items = customer.last_order_items or []
    if items and isinstance(items[0], dict):
        return items[0].get("name", "")
    return ""


# --------------------------------------------------------------------------
# Order banana
# --------------------------------------------------------------------------
def _order_no_from_id(order_id: int) -> str:
    """Order number DB ki primary key se banta hai (sequence-backed, reuse nahi hota, race-safe).

    Pehle count-based tha: do parallel orders ek hi number le sakte the (unique constraint fail).
    """
    return str(1000 + order_id)


def create_order(
    db: Session,
    customer: Customer,
    lines: list[dict],
    channel: str = "whatsapp",
    table_number: str | None = None,
    notes: str | None = None,
    discount_percent: float = 0.0,
    discount_code: str | None = None,
    discount_reason: str | None = None,
    freebies: list[str] | None = None,
    is_cod: bool = False,
) -> tuple[Order, Bill]:
    """Bill banao + order save karo. Price hamesha menu se, AI se nahi."""
    freebies = list(freebies or [])
    bill_lines: list[dict] = [dict(line) for line in lines]
    menu_items: dict[str, MenuItem] = {}
    for row in bill_lines:
        item = menu_engine.find_item(db, row.get("name", ""))
        if item:
            menu_items[item.name] = item
    for freebie_name in freebies:
        item = menu_engine.find_item(db, freebie_name)
        bill_lines.append(
            {
                "name": item.name if item else freebie_name,
                "qty": 1,
                "unit_price": item.price if item else 0.0,
                "is_freebie": True,
            }
        )

    bill = build_bill(
        db,
        bill_lines,
        discount_percent=discount_percent,
        discount_code=discount_code,
        discount_reason=discount_reason,
        freebies=freebies,
    )
    order = Order(
        order_no=f"pending-{uuid.uuid4().hex}",  # temporary unique value; flush ke baad asli number
        customer_id=customer.id,
        customer_phone=customer.phone,
        customer_name=customer.name,
        table_number=table_number,
        items=[
            {
                "name": line.name,
                "qty": line.qty,
                "price": line.unit_price,
                "line_total": line.line_total,
                "free": line.is_freebie,
            }
            for line in bill.lines
        ],
        subtotal=bill.subtotal,
        discount_amount=bill.discount_amount,
        discount_code=bill.discount_code,
        discount_reason=bill.discount_reason,
        freebies=bill.freebies,
        packaging=bill.packaging,
        delivery=bill.delivery,
        taxable=bill.taxable,
        gst_amount=bill.gst_amount,
        total_amount=bill.total,
        payment_status="cod" if is_cod else "pending",
        order_status="confirmed" if is_cod else "awaiting_payment",
        channel=channel,
        notes=notes,
    )
    db.add(order)
    db.flush()
    order.order_no = _order_no_from_id(order.id)
    db.flush()
    for line in bill.lines:
        item = menu_engine.find_item(db, line.name)
        db.add(
            OrderItem(
                order_id=order.id,
                menu_item_id=item.id if item else None,
                name=line.name,
                qty=line.qty,
                unit_price=line.unit_price,
                line_total=line.line_total,
                is_freebie=line.is_freebie,
            )
        )
    db.flush()
    return order, bill


def payment_message_for(db: Session, order: Order, bill: Bill, base_url: str | None = None) -> str:
    try:
        payment = payments.create_payment(db, order, base_url=base_url)
    except payments.PaymentProviderError as exc:
        # live provider down: fake link nahi, staff ko alert, customer ko honest message
        create_alert(db, "system", f"Payment link nahi bana — Order #{order.order_no}: {exc}", order_id=order.id)
        return (
            f"{bill.text()}\n\nAbhi payment link nahi ban paya 🙏 Staff aapko thodi der me sahi link bhejega "
            f"(ya counter par pay kar sakte hain)."
        )
    link = payment.link or ""
    box = ""
    if not settings.payment_live:
        box = "\n_(demo payment page — live me ye asli UPI link hoga)_"
    return (
        f"{bill.text()}\n\n"
        f"Payment ke liye ye raha link 👉 {link}\n"
        f"UPI se 10 second me ho jayega. Pay karte hi main thanks ke saath agla tohfa bhej dunga 🎁{box}"
    )


# --------------------------------------------------------------------------
# Intent handlers
# --------------------------------------------------------------------------
def _menu_facts(db: Session, customer: Customer) -> dict:
    specials = menu_engine.signature_items(db) or menu_engine.most_sold(db, 2)
    special = specials[0].name if specials else "Cold Coffee"
    return {
        "aaj_ka_special": special,
        "special_line": f"({settings.agent_name} ki guarantee: {special} aaj fresh bana hai!)",
        "signature": special,
        "pichla_item": _last_item_name(customer) or special,
        "gap_text": _gap_text(customer),
    }


def _handle_order(db: Session, customer: Customer, text: str, last_intent: str | None, base_url: str | None = None) -> list[Reply]:
    if menu_engine.wants_repeat(text) and customer.last_order_items:
        parsed = menu_engine.order_from_last(db, customer.last_order_items)
        repeat = True
    else:
        parsed = menu_engine.parse_order_text(db, text)
        repeat = False

    if not parsed.has_items:
        unmatched = ", ".join(parsed.unmatched[:3]) or truncate(text, 40)
        body = llm.demo_brain(text, {"customer": memory.customer_context(db, customer), "facts": _menu_facts(db, customer)}, intent="menu")
        reply_text = (
            f"{body}\n\nSir, *{unmatched}* hamare menu me nahi mila 🤔 "
            f"Menu se naam likh ke bhej dijiye — jaise *2 paneer butter masala, 4 butter naan*."
        )
        return [Reply(text=reply_text, intent="order_unclear")]

    subtotal = parsed.subtotal
    pending_count = db.scalar(
        select(func.count(Order.id)).where(
            Order.customer_phone == customer.phone, Order.payment_status.in_(["pending", "cod"])
        )
    ) or 0
    next_order_number = (customer.total_orders or 0) + int(pending_count) + 1
    decision = discounts.evaluate_for_order(db, customer, subtotal, order_number=next_order_number)

    # ---- coupon (customer ne code likha ho to) — validate + atomic claim ----
    percent = float(decision["percent"])
    code = decision["code"]
    reason = decision["reason"]
    freebies_for_order = list(decision["freebies"])
    coupon_note = ""
    claimed_coupon = None
    coupon, coupon_error = pricing.find_coupon_in_text(db, text, customer.phone, subtotal)
    if coupon and pricing.redeem_coupon(db, coupon):
        claimed_coupon = coupon
        coupon_percent = min(float(coupon.discount_percent or 0), settings.max_discount_percent)
        if coupon_percent > percent:  # sirf best single percent (stacking nahi)
            percent, code, reason = coupon_percent, coupon.code, f"Coupon {coupon.code} ({coupon.source or 'offer'})"
        if coupon.free_item_name and coupon.free_item_name not in freebies_for_order:
            freebies_for_order.append(coupon.free_item_name)
    elif coupon_error:
        coupon_note = f"{coupon_error}\n\n"

    lines = [
        {"name": line.name, "qty": line.qty, "unit_price": line.unit_price}
        for line in parsed.lines
        if line.matched
    ]

    is_cod = bool(re.search(r"\bcod\b|cash|counter|pay at|baad me paisa|offline pay", text, re.IGNORECASE))
    order, bill = create_order(
        db,
        customer,
        lines,
        discount_percent=percent,
        discount_code=code,
        discount_reason=reason,
        freebies=freebies_for_order,
        is_cod=is_cod,
        notes="repeat order" if repeat else None,
    )
    if claimed_coupon is not None:
        pricing.attach_coupon_to_order(db, claimed_coupon, order.id)
    if code:
        discounts.record_rule_use(db, code)

    order_items_text = menu_engine.order_summary_text(bill.lines)

    # veg/non-veg preference turant update (payment ka intezaar nahi)
    ordered_items = [menu_engine.find_item(db, line.name) for line in bill.lines if not line.is_freebie]
    ordered_items = [item for item in ordered_items if item]
    if ordered_items:
        customer.veg_pref = "veg" if all(item.is_veg for item in ordered_items) else "nonveg"

    create_alert(
        db,
        "new_order",
        f"Order #{order.order_no} — {customer.name or customer.phone}\n"
        f"{order_items_text}\nTotal: {rupees(order.total_amount)}"
        f"{' (COD)' if is_cod else ''} | Channel: {order.channel}",
        customer_phone=customer.phone,
        order_id=order.id,
    )

    context = memory.customer_context(db, customer)
    facts = _menu_facts(db, customer)
    facts.update(
        {
            "order_items": order_items_text,
            "bill_total": rupees(order.total_amount),
            "discount": f"{int(percent)}% ({code})" if code else "aaj koi discount nahi",
        }
    )
    opener = llm.demo_brain(text, {"customer": context, "facts": facts}, intent="order")
    if coupon_note:
        opener = f"{coupon_note}{opener}"

    if is_cod:
        body = (
            f"{opener}\n\n{bill.text()}\n\n"
            f"Order # {order.order_no} pakka ho gaya ✅ Counter/bill par paisa de dijiye, "
            f"kitchen me order chala gaya hai 👨‍🍳 25-30 min me taiyaar."
        )
        customer.flow_state = {**(customer.flow_state or {}), "active_order": order.order_no}
        return [Reply(text=body, intent="order_cod", meta={"order_no": order.order_no})]

    body = f"{opener}\n\n{payment_message_for(db, order, bill, base_url=base_url)}"
    return [Reply(text=body, intent="order_bill", meta={"order_no": order.order_no, "total": order.total_amount})]


def _handle_pending_payment(db: Session, customer: Customer, order: Order, base_url: str | None = None) -> list[Reply]:
    payment = db.scalar(select(Payment).where(Payment.order_id == order.id).order_by(Payment.id.desc()))
    if payment and payment.link and payment.status != "paid":
        return [
            Reply(
                text=f"Ji sir, aapka bill *{rupees(order.total_amount)}* aur payment link ye hai 👇\n{payment.link}\n"
                f"Pay karte hi order kitchen me chala jayega 😄",
                intent="payment_link",
            )
        ]
    bill = build_bill(
        db,
        [dict(name=row.get("name"), qty=row.get("qty", 1), unit_price=row.get("price", 0), is_freebie=row.get("free", False)) for row in (order.items or [])],
        discount_percent=0,
    )
    return [Reply(text=payment_message_for(db, order, bill, base_url=base_url), intent="payment_link")]


def _handle_menu(db: Session, customer: Customer, text: str) -> list[Reply]:
    facts = _menu_facts(db, customer)
    opener = llm.generate_reply(text, {"customer": memory.customer_context(db, customer), "facts": facts}, history=recent_history(db, customer.phone, 6), intent="menu")[0]
    menu_text = menu_engine.menu_text(db)
    body = f"{opener}\n\n{menu_text}"
    reply = Reply(text=body, intent="menu")
    if customer.opt_in is False and not customer.opted_out and customer.total_orders >= 1:
        return [
            reply,
            Reply(
                text="Waise, aapko time-time par offers/secret menu bhejta rahun? 😄 Haan likh dijiye to bhej dunga, warna bilkul nahi bhejunga (STOP likhne par band).",
                kind="buttons",
                buttons=[{"id": "optin_yes", "title": "Haan, bhej do"}, {"id": "optin_no", "title": "Nahi, rehne do"}],
                intent="optin_ask",
            ),
        ]
    return [reply]


def _handle_reservation(db: Session, customer: Customer, text: str, entities: dict) -> list[Reply]:
    state = dict(customer.flow_state or {})
    pending = dict(state.get("reservation") or {})
    for key in ("date", "time", "persons", "name"):
        if entities.get(key):
            pending[key] = entities[key]
    if not pending.get("name") and customer.name:
        pending["name"] = customer.name

    missing = [key for key in ("date", "time", "persons") if not pending.get(key)]
    if missing:
        state["reservation"] = pending
        customer.flow_state = state
        ask = {
            "date": "kis din aana hai (aaj/kal/parso ya date)",
            "time": "kitne baje (jaise 7 baje ya 19:30)",
            "persons": "kitne log aayenge",
        }[missing[0]]
        got = {k: v for k, v in pending.items() if k in {"date", "time", "persons"}}
        lead = "Perfect sir 👍 " if got else ""
        return [Reply(text=f"{lead}Table ki booking ho jayegi — bas bata dijiye {ask}?", intent="reservation_slot")]

    date_str, time_str = str(pending["date"]), str(pending["time"])
    try:
        booking_day = reservations.parse_date(date_str, today_ist_date())
        time_str = reservations.normalize_time(time_str)
        persons = reservations.parse_persons(pending["persons"])
    except reservations.ReservationError as exc:
        state.pop("reservation", None)
        customer.flow_state = state
        return [Reply(text=f"Sir booking me dikkat hai: {exc} 🤔 Dobara bata dijiye?", intent="reservation_date_bad")]
    try:
        reservation = reservations.create_reservation(
            db,
            phone=customer.phone,
            name=pending.get("name") or customer.name,
            day=booking_day,
            time_str=time_str,
            persons=persons,
            notes=pending.get("notes"),
        )
    except reservations.CapacityError:
        return [
            Reply(
                text=f"Sir us time par table bhara hua hai 😅 {time_str} se aadhe ghante aage-peeche ho jaye to? "
                f"Ya main manager se bol ke jugaad karwa dun?",
                intent="reservation_full",
                kind="buttons",
                buttons=[{"id": "res_alt_time", "title": "Doosra time"}, {"id": "res_manager", "title": "Manager se baat"}],
            )
        ]
    state.pop("reservation", None)
    customer.flow_state = state
    create_alert(
        db,
        "new_order",
        f"Table booking — {reservation.customer_name or customer.phone}\n{date_str} {time_str} | {persons} log",
        customer_phone=customer.phone,
    )
    pretty_date = _pretty_date(date_str)
    return [
        Reply(
            text=(
                f"Ho gaya sir! Table confirm ✅\n\n"
                f"📅 {pretty_date}\n⏰ {_pretty_time(time_str)}\n👥 {persons} log\n"
                f"{settings.restaurant_name}, {settings.restaurant_address}\n\n"
                f"Aane se 1 ghanta pehle main yaad dila dunga 😄"
            ),
            intent="reservation_confirmed",
            meta={"date": date_str, "time": time_str, "persons": persons},
        )
    ]


def _pretty_date(date_str: str) -> str:

    try:
        day = date_cls.fromisoformat(date_str)
    except ValueError:
        return date_str
    today = today_ist_date()
    delta = (day - today).days
    if delta == 0:
        return f"Aaj ({day.strftime('%d %b')})"
    if delta == 1:
        return f"Kal ({day.strftime('%d %b')})"
    return day.strftime("%d %b, %A")


def _pretty_time(time_str: str) -> str:
    try:
        hour, minute = time_str.split(":")
        hour_i = int(hour)
        suffix = "AM" if hour_i < 12 else "PM"
        display = hour_i % 12 or 12
        return f"{display}:{minute} {suffix}"
    except (ValueError, AttributeError):
        return time_str


def _handle_feedback(db: Session, customer: Customer, text: str, rating: int | None, comment: str | None = None) -> list[Reply]:
    last_order = db.scalar(select(Order).where(Order.customer_phone == customer.phone).order_by(Order.created_at.desc()).limit(1))
    row = Feedback(
        customer_phone=customer.phone,
        customer_name=customer.name,
        order_id=last_order.id if last_order else None,
        rating=int(rating or 0),
        comment=comment or text,
    )
    db.add(row)
    db.flush()
    state = dict(customer.flow_state or {})
    state.pop("awaiting_feedback", None)
    customer.flow_state = state

    if int(rating or 0) >= 4:
        review_line = (
            f"Google par bhi ek chhota sa review de dijiye na sir, 30 second ka kaam hai 🙏\n{settings.google_review_link}"
            if settings.google_review_link
            else "Aapka pyaar hi hamara 5 star hai 🙏"
        )
        coupon = discounts.thanks_coupon(db, customer)
        return [
            Reply(
                text=(
                    f"Wah {int(rating)} star! Dil khush kar diya sir 😄 {review_line}\n\n"
                    f"Aapke agle order ke liye chhota sa tohfa — code: *{coupon.code}* ({int(coupon.discount_percent)}% off) 🎁"
                ),
                intent="feedback_thanks",
            )
        ]

    create_alert(
        db,
        "complaint",
        f"😟 Kam rating ({rating}/5) — {customer.name or customer.phone}\n"
        f"Comment: {truncate(comment or text, 180)}\nPlease turant baat karein.",
        customer_phone=customer.phone,
        order_id=last_order.id if last_order else None,
    )
    return [
        Reply(
            text=(
                f"Sorry sir 🙏 {int(rating)} star milna hamare liye signal hai ki sudhar zaroori hai.\n"
                f"Main abhi manager sahab ko bhej raha hoon — wo aapko call karenge aur problem thik karenge. "
                f"Agli baar aapko aisa mauka nahi denge kabhi 😌"
            ),
            intent="feedback_negative",
        )
    ]


def _handle_complaint(db: Session, customer: Customer, text: str) -> list[Reply]:
    create_alert(
        db,
        "complaint",
        f"😟 Customer khush nahi — {customer.name or customer.phone}\nMessage: {truncate(text, 200)}\nTurant baat karein.",
        customer_phone=customer.phone,
    )
    coupon = discounts.issue_coupon(db, percent=0, source="complaint", customer_phone=customer.phone, free_item_name="Gulab Jamun", valid_days=30)
    context = memory.customer_context(db, customer)
    facts = {"freebie": "Gulab Jamun", "coupon": coupon.code}
    body = llm.generate_reply(
        text,
        {"customer": context, "facts": facts, "next_action": "Batao ki manager abhi baat karega aur agli baar dessert free milega (code ke saath)."},
        history=recent_history(db, customer.phone, 6),
        intent="complaint",
    )[0]
    return [Reply(text=body, intent="complaint_handled", meta={"coupon": coupon.code})]


def _handle_order_status(db: Session, customer: Customer) -> list[Reply]:
    order = db.scalar(select(Order).where(Order.customer_phone == customer.phone).order_by(Order.created_at.desc()).limit(1))
    if not order:
        return [Reply(text="Sir abhi koi chalu order nahi mila. Kuch order karna hai? Menu bhej dun? 😄", intent="order_status_none")]
    stages = {
        "awaiting_payment": "Payment ka intezaar hai sir 🙏 Link bhejun phir se?",
        "placed": "Order mil gaya, kitchen ne dekh liya 👨‍🍳",
        "confirmed": "Order confirm ho gaya, kitchen me ban raha hai 👨‍🍳",
        "preparing": "Ban raha hai sir — masala ekdum bhar raha hai 🍲",
        "packed": "Pack ho gaya 📦",
        "out_for_delivery": "Rider nikal gaya hai 🛵 Bas 10-15 min!",
        "delivered": "Pahunch gaya sir 😄 Khana kaisa laga?",
        "cancelled": "Ye order cancel tha sir.",
    }
    status_text = stages.get(order.order_status, order.order_status)
    return [
        Reply(
            text=(
                f"Order #{order.order_no} ka status: *{status_text}*\n"
                f"Items: {menu_engine.order_summary_text(order.items or [])}\n"
                f"Total: {rupees(order.total_amount)} ({order.payment_status})"
            ),
            intent="order_status",
        )
    ]


def _handle_price_query(db: Session, customer: Customer, text: str) -> list[Reply]:
    item = menu_engine.find_item(db, text)
    if item:
        veg = "🟢 Veg" if item.is_veg else "🔴 Non-Veg"
        return [
            Reply(
                text=(
                    f"*{item.name}* — {rupees(item.price)} ({veg})\n"
                    f"{item.description or 'Ekdum fresh banta hai sir 😋'}"
                ),
                intent="price_answer",
                meta={"item": item.name},
            )
        ]
    return [Reply(text=llm.demo_brain(text, {"customer": memory.customer_context(db, customer), "facts": _menu_facts(db, customer)}, intent="price_query"), intent="price_unknown")]


def _handle_specials(db: Session, customer: Customer, text: str) -> list[Reply]:
    specials = menu_engine.signature_items(db, 3)
    sold = menu_engine.most_sold(db, 3)
    lines = [f"*{item.name}* — {rupees(item.price)}" for item in specials]
    best = [f"{item.name} ({item.sold_count} baar bika)" for item in sold if item.sold_count]
    body = "Aaj ke special sir 👇\n" + "\n".join(lines)
    if best:
        body += "\n\nSabse zyada bikne wale: " + ", ".join(best)
    if customer.veg_pref == "veg":
        body += "\n\n(Aapke veg preference ke hisaab se hi bata raha hoon 😊)"
    body += "\n\nBataiye kaunsa laaun?"
    return [Reply(text=body, intent="special")]


def _handle_loyalty(db: Session, customer: Customer) -> list[Reply]:
    milestone = memory.next_loyalty_milestone(customer)
    if milestone["unlocked"]:
        _name = "Cold Coffee"
        return [Reply(text=f"Khushkhabri {customer.name or 'sir'}! Aapke {milestone['points']} points ho gaye hain — ek *{_name} bilkul FREE* ☕ Bolo order me jod dun?", intent="loyalty_reward")]
    body = (
        f"Aapke paas *{milestone['points']} points* hain sir 😄 "
        f"Bas {milestone['remaining']} points aur, phir ek Cold Coffee FREE ☕\n"
        f"(Har order par har ₹100 ke {settings.loyalty_points_per_100} points milte hain)"
    )
    return [Reply(text=body, intent="loyalty")]


def _handle_handover(db: Session, customer: Customer, text: str) -> list[Reply]:
    customer.human_mode = True
    create_alert(
        db,
        "handover",
        f"🙋 Human handover — {customer.name or customer.phone}\nAakhri message: {truncate(text, 160)}\nAb aap/ staff reply kar dein.",
        customer_phone=customer.phone,
        notify_owner=False,
    )
    if settings.staff_whatsapp:
        whatsapp.send_text(
            settings.staff_whatsapp,
            f"Customer {customer.name or customer.phone} ({customer.phone}) se baat karni hai. "
            f"Aakhri message: {truncate(text, 120)}",
        )
    return [
        Reply(
            text=(
                "Bilkul sir 🙏 Abhi hamare staff ko aapki chat de raha hoon — 1-2 minute me wo reply karenge.\n"
                "(Baaki kaam pehle jaise chalta rahega, aap be fikar rahiye 😄)"
            ),
            intent="handover",
        )
    ]


def _handle_owner_request(db: Session, customer: Customer, text: str) -> list[Reply]:
    if not is_staff(customer.phone):
        return [Reply(text="Sir ye report owner ke number par hi jaati hai 🙂 Aap order ya menu bataiye, main hazir hoon!", intent="owner_only")]
    from .reports import daily_report_text

    return [Reply(text=daily_report_text(db), intent="owner_report")]


def _handle_broadcast(db: Session, customer: Customer, text: str) -> list[Reply]:
    if not is_staff(customer.phone):
        return [Reply(text="Ye sirf owner dashboard se chalta hai 🙏", intent="broadcast_denied")]
    from .models import Campaign

    message = re.sub(r"^\s*(broadcast|campaign)\s*[:\-]?\s*", "", text, flags=re.IGNORECASE).strip()
    opt_in_list = memory.all_customers(db, only_opt_in=True)
    campaign = Campaign(
        name=f"Broadcast {now_ist().strftime('%d %b %H:%M')}",
        kind="broadcast",
        message=message or "Aaj ka special offer!",
        audience_count=len(opt_in_list),
        status="draft",
        details={"source": "whatsapp"},
    )
    db.add(campaign)
    db.flush()
    return [
        Reply(
            text=(
                f"Broadcast taiyaar hai sir ✅\nAudience: {len(opt_in_list)} opt-in customers\n"
                f"Message: {truncate(campaign.message, 160)}\n\n"
                f"Dashboard me 'Broadcast' tab khol ke *Send* daba dijiye — main ek-ek ko bhej dunga "
                f"(STOP wale apne aap skip ho jayenge)."
            ),
            intent="broadcast_draft",
        )
    ]


def _handle_party(db: Session, customer: Customer, text: str, entities: dict) -> list[Reply]:
    state = dict(customer.flow_state or {})
    party = dict(state.get("party") or {})
    if entities.get("date"):
        party["date"] = entities["date"]
    if entities.get("persons"):
        party["persons"] = entities["persons"]
    budget = re.search(r"(?:budget|₹|rs\.?)\s*(\d{3,6})", text, re.IGNORECASE)
    if budget:
        party["budget"] = int(budget.group(1))
    missing = [k for k in ("date", "persons", "budget") if not party.get(k)]
    if missing:
        state["party"] = party
        customer.flow_state = state
        ask = {"date": "kaunsi date", "persons": "kitne log", "budget": "approx budget kitna"}[missing[0]]
        return [Reply(text=f"Party/catering ka intezaam ho jayega sir 🎉 Bas {ask} bata dijiye?", intent="party_slot")]
    create_alert(
        db,
        "party",
        f"🎉 Party/Catering enquiry — {customer.name or customer.phone}\n"
        f"Date: {party['date']} | Log: {party['persons']} | Budget: ₹{party['budget']}\n"
        f"Pakka karne ke liye customer ko call karein.",
        customer_phone=customer.phone,
    )
    state.pop("party", None)
    customer.flow_state = state
    return [
        Reply(
            text=(
                f"Note kar liya sir ✅\n📅 {_pretty_date(str(party['date']))}\n👥 {party['persons']} log\n"
                f"💰 Budget ~₹{party['budget']}\n\n"
                f"Manager sahab aapko 10 minute me call karke menu aur rate bata denge 😄"
            ),
            intent="party_booked",
        )
    ]


def _handle_address(db: Session, customer: Customer) -> list[Reply]:
    map_link = f"https://maps.google.com/?q={settings.restaurant_address.replace(' ', '+')}"
    return [
        Reply(
            text=(
                f"{settings.restaurant_name} 📍\n{settings.restaurant_address}\n"
                f"⏰ {settings.restaurant_hours}\n📞 {settings.restaurant_phone}\n\n{map_link}"
            ),
            intent="address",
        )
    ]


# --------------------------------------------------------------------------
# Main entry
# --------------------------------------------------------------------------
def handle_inbound(db: Session, inbound: whatsapp.Inbound, deliver_replies: bool = True, base_url: str | None = None) -> HandleResult:
    """Poora pipeline — customer ka message, agent ka jawab."""
    phone = clean_phone(inbound.phone)
    if not phone:
        return HandleResult(customer=None, intent="invalid")  # type: ignore[arg-type]

    customer, is_new = memory.get_or_create_customer(db, phone, inbound.profile_name, channel=inbound.source)
    text = (inbound.effective_text or "").strip()

    # language auto-detect (F21 Multi-language)
    if text and not text.startswith("__"):
        customer.language = detect_language(text)

    log_message(db, phone, "in", text, message_type=inbound.type, channel=inbound.source)

    state = dict(customer.flow_state or {})
    pending_order = None
    if state.get("active_order"):
        pending_order = db.scalar(select(Order).where(Order.order_no == str(state["active_order"])).limit(1))
        if pending_order and pending_order.payment_status in {"paid", "cod"}:
            pending_order = None
            state.pop("active_order", None)
            customer.flow_state = state
    awaiting_feedback = bool(state.get("awaiting_feedback"))

    # ---------- special inbound types (voice / photo) ----------
    if text == "__VOICE_NOTE__":
        if inbound.media_id:
            blob, mime = whatsapp.download_media(inbound.media_id)
            transcript = whatsapp.transcribe_audio(blob, mime) if blob else None
            if transcript:
                text = transcript
        if text == "__VOICE_NOTE__":
            reply = Reply(
                text=(
                    "Voice note mil gaya sir 🎤 Lekin abhi main sun nahi pa raha (demo mode me voice off hai) — "
                    "type kar dijiye na, main turant kaam kar deta hoon 😄"
                ),
                intent="voice_unsupported",
            )
            if deliver_replies:
                deliver(db, customer, reply)
            return HandleResult(customer=customer, intent="voice_unsupported", replies=[reply])
    if text == "__IMAGE__":
        # Bill ki photo / dish ki photo — demo me simple acknowledgment
        reply = Reply(
            text=(
                "Photo dekh li sir 📸 Achhi lag rahi hai! Order karna hai to naam likh dijiye "
                "(jaise *2 paneer butter masala, 4 naan*), main note kar leta hoon."
            ),
            intent="image_received",
        )
        if deliver_replies:
            deliver(db, customer, reply)
        return HandleResult(customer=customer, intent="image_received", replies=[reply])
    if text == "__LOCATION__":
        replies = _handle_address(db, customer)
        for reply in replies:
            if deliver_replies:
                deliver(db, customer, reply)
        return HandleResult(customer=customer, intent="address", replies=replies)

    detected = intent_engine.detect(
        text,
        has_pending_bill=pending_order is not None,
        awaiting_feedback=awaiting_feedback,
        last_intent=state.get("last_intent"),
    )
    intent_name = detected.name

    # ---------- adhoori booking ho to wahi continue karo (slot filling) ----------
    pending_reservation = bool(state.get("reservation"))
    pending_party = bool(state.get("party"))
    slot_entities = any(detected.entities.get(key) not in (None, "") for key in ("date", "time", "persons"))
    if pending_reservation and slot_entities and intent_name not in {"opt_out", "opt_in", "handover", "complaint", "reservation_cancel"}:
        detected.name = intent_name = "reservation"
        detected.all_matches.append("reservation_state")
    elif pending_party and (slot_entities or detected.entities.get("budget")) and intent_name not in {"opt_out", "opt_in", "handover", "complaint"}:
        detected.name = intent_name = "party_booking"

    # ---------- STOP / START (report Section 22) ----------
    if intent_name == "opt_out":
        customer.opted_out = True
        customer.opt_in = False
        replies = [
            Reply(
                text=(
                    "Bilkul sir, samajh gaya 🙏 Aage se koi offer/promo message nahi bhejunga.\n"
                    "(Order, bill ya booking ke liye main hamesha hazir hoon — kabhi bhi message kar dijiye. "
                    "Wapas offers chahiye to *START* likh dena.)"
                ),
                intent="opt_out",
            )
        ]
        state["last_intent"] = intent_name
        customer.flow_state = state
        for reply in replies:
            if deliver_replies:
                deliver(db, customer, reply)
        return HandleResult(customer=customer, intent=intent_name, replies=replies)

    if inbound.interactive_id and inbound.interactive_id.startswith("optin"):
        wants = inbound.interactive_id.endswith("yes")
        customer.opt_in = wants
        customer.opted_out = not wants
        replies = [
            Reply(
                text="Ek number! 😄 Ab time-time par aapko offers bhejta rahunga. Kabhi mann bhar jaye to STOP likh dijiye."
                if wants
                else "Koi baat nahi sir, aapki marzi 🙏 Sirf order/bill ke liye message karunga.",
                intent="optin",
            )
        ]
        for reply in replies:
            if deliver_replies:
                deliver(db, customer, reply)
        return HandleResult(customer=customer, intent="optin", replies=replies)

    if intent_name == "opt_in":
        customer.opt_in = True
        customer.opted_out = False
        replies = [Reply(text="Welcome back sir! 😄 Ab offers phir se shuru — aur kuch chahiye to bas bata dijiye.", intent="opt_in")]
        for reply in replies:
            if deliver_replies:
                deliver(db, customer, reply)
        return HandleResult(customer=customer, intent=intent_name, replies=replies)

    # ---------- naam / birthday yaad rakhna ----------
    if detected.entities.get("name") and intent_name in {"name_provided", "greeting", "unknown"}:
        memory.remember_name(db, customer, detected.entities["name"])
    if detected.entities.get("birthday"):
        customer.birthday = detected.entities["birthday"]

    # ---------- human mode me sirf log karo + alert ----------
    if customer.human_mode and intent_name not in {"handover"}:
        create_alert(
            db,
            "handover",
            f"Human mode ON — {customer.name or customer.phone}: {truncate(text, 160)}",
            customer_phone=customer.phone,
            notify_owner=False,
        )
        state["last_intent"] = intent_name
        customer.flow_state = state
        return HandleResult(customer=customer, intent=intent_name, replies=[])

    # ---------- dispatch ----------
    replies: list[Reply] = []
    if intent_name in {"order", "confirm_order", "repeat_order"}:
        replies = _handle_order(db, customer, text, state.get("last_intent"), base_url=base_url)
    elif intent_name == "menu":
        replies = _handle_menu(db, customer, text)
    elif intent_name == "bill":
        if pending_order:
            replies = _handle_pending_payment(db, customer, pending_order, base_url=base_url)
        else:
            last_order = db.scalar(select(Order).where(Order.customer_phone == customer.phone).order_by(Order.created_at.desc()).limit(1))
            if last_order:
                bill = build_bill(
                    db,
                    [
                        dict(name=row.get("name"), qty=row.get("qty", 1), unit_price=row.get("price", 0), is_freebie=row.get("free", False))
                        for row in (last_order.items or [])
                    ],
                )
                replies = [Reply(text=bill.text(), intent="bill")]
            else:
                replies = [Reply(text="Sir abhi koi order hi nahi hua 😄 Pehle kuch order kar lijiye, phir bill bhejta hoon.", intent="bill_none")]
    elif intent_name == "pay":
        if pending_order:
            replies = _handle_pending_payment(db, customer, pending_order, base_url=base_url)
        else:
            replies = [Reply(text="Sir abhi koi pending bill nahi hai 🙏 Order bataiye, main bill bana ke link bhej deta hoon.", intent="pay_none")]
    elif intent_name == "price_query":
        replies = _handle_price_query(db, customer, text)
    elif intent_name == "special":
        replies = _handle_specials(db, customer, text)
    elif intent_name == "loyalty":
        replies = _handle_loyalty(db, customer)
    elif intent_name == "reservation":
        replies = _handle_reservation(db, customer, text, detected.entities)
    elif intent_name == "reservation_cancel":
        order_res = db.scalar(
            select(Reservation)
            .where(Reservation.customer_phone == customer.phone, Reservation.status == "confirmed")
            .order_by(Reservation.date.desc())
            .limit(1)
        )
        if order_res:
            order_res.status = "cancelled"
            replies = [Reply(text="Table booking cancel kar di sir ✅ Kabhi bhi dobara bata dijiye, table hazir hai 😄", intent="reservation_cancelled")]
        else:
            replies = [Reply(text="Sir aapki koi chalu booking nahi mili 🤔", intent="reservation_none")]
    elif intent_name == "order_status":
        replies = _handle_order_status(db, customer)
    elif intent_name == "feedback_rating":
        replies = _handle_feedback(db, customer, text, detected.entities.get("rating"))
    elif intent_name == "feedback_comment":
        replies = _handle_feedback(db, customer, text, detected.entities.get("rating") or 0, comment=text)
    elif intent_name == "feedback_positive" and awaiting_feedback:
        replies = _handle_feedback(db, customer, text, 5, comment=text)
    elif intent_name == "complaint":
        replies = _handle_complaint(db, customer, text)
    elif intent_name == "handover":
        replies = _handle_handover(db, customer, text)
    elif intent_name == "party_booking":
        replies = _handle_party(db, customer, text, detected.entities)
    elif intent_name == "address_hours":
        replies = _handle_address(db, customer)
    elif intent_name == "owner_report":
        replies = _handle_owner_request(db, customer, text)
    elif intent_name == "broadcast":
        replies = _handle_broadcast(db, customer, text)
    elif intent_name == "birthday_set":
        if customer.birthday:
            replies = [
                Reply(
                    text=(
                        f"Note kar liya sir! 🎂 {customer.birthday.split('-')[1]}/{customer.birthday.split('-')[0]} ko "
                        f"aapke liye special surprise rahega — dessert bilkul free 😄"
                    ),
                    intent="birthday_saved",
                )
            ]
        else:
            replies = [Reply(text="Birthday ka din aur mahina bata dijiye sir (jaise *15 March*) — main yaad rakhunga 🎂", intent="birthday_ask")]
    else:
        context = memory.customer_context(db, customer)
        facts = _menu_facts(db, customer)
        facts["loyalty_line"] = memory.next_loyalty_milestone(customer) and ""
        if memory.next_loyalty_milestone(customer)["remaining"] <= 100:
            facts["loyalty_line"] = f"Bas {memory.next_loyalty_milestone(customer)['remaining']} points aur, phir Cold Coffee FREE ☕"
        if memory.nights_since_last_visit(customer) and memory.nights_since_last_visit(customer) >= 20:
            facts["winback_line"] = "Aapko dekh ke aaj maza aa gaya, itne din baad aaye ho!"
        body, meta = llm.generate_reply(
            text,
            {"customer": context, "facts": facts},
            history=recent_history(db, customer.phone, 8),
            intent=intent_name,
        )
        replies = [Reply(text=body, intent=intent_name, meta=meta)]

    # ---------- memory + state update ----------
    state = dict(customer.flow_state or {})
    state["last_intent"] = intent_name
    customer.flow_state = state
    customer.last_seen_at = utcnow()
    if customer.total_orders == 0 and not is_new:
        pass
    db.flush()

    for reply in replies:
        reply.intent = reply.intent or intent_name
        if deliver_replies:
            deliver(db, customer, reply)
    return HandleResult(customer=customer, intent=intent_name, replies=replies, meta=detected.entities)


# --------------------------------------------------------------------------
# Payment success (webhook / mock page se)
# --------------------------------------------------------------------------
def on_payment_success(db: Session, order: Order, via: str = "webhook", deliver_replies: bool = True) -> list[Reply]:
    """Payment aa gaya -> memory update, points, thanks message, agla offer code."""
    customer = memory.get_customer(db, order.customer_phone)
    if not customer:
        customer, _ = memory.get_or_create_customer(db, order.customer_phone, order.customer_name)
    memory.apply_order_to_memory(db, customer, order)


    coupon = discounts.thanks_coupon(db, customer)
    milestone = memory.next_loyalty_milestone(customer)
    context = memory.customer_context(db, customer)
    facts = {
        "order_no": order.order_no,
        "total": rupees(order.total_amount),
        "points_earned": f"har ₹100 par {settings.loyalty_points_per_100} points",
        "loyalty_points": customer.loyalty_points,
        "new_code": coupon.code,
    }
    thanks = llm.demo_brain(
        "payment ho gaya",
        {
            "customer": context,
            "facts": facts,
            "next_action": (
                f"🎁 Aur haan — agle order ke liye aapka tohfa code: *{coupon.code}* "
                f"({int(coupon.discount_percent)}% off). Order karte waqt bas likh dena, main laga dunga!"
            ),
        },
        intent="thanks",
    )
    body = (
        f"{thanks}\n\n"
        f"🧾 Order #{order.order_no} | {rupees(order.total_amount)} — payment mil gaya ✅\n"
        f"Kitchen me order chala gaya, 25-30 min me taiyaar 👨‍🍳\n"
        f"⭐ Aapke {customer.loyalty_points} loyalty points ho gaye hain."
    )
    if milestone["unlocked"]:
        body += "\n☕ Aur haan — aap free coffee ke hakdaar ho gaye hain! Agli baar bol dena."
    replies = [Reply(text=body, intent="payment_thanks", meta={"order_no": order.order_no, "coupon": coupon.code})]

    if order.table_number:
        replies.append(
            Reply(
                text=f"Waise order table #{order.table_number} par serve hoga 😄 Waiter ko bhi bol diya hai.",
                intent="table_note",
            )
        )

    create_alert(
        db,
        "payment",
        f"Payment aa gaya ✅ Order #{order.order_no} — {rupees(order.total_amount)} ({via})\n{customer.name or customer.phone}",
        customer_phone=customer.phone,
        order_id=order.id,
    )
    # kitchen status ko sirf tab aage badhao jab order abhi payment ka intezaar kar raha tha.
    # Duplicate/late call kitchen ka 'preparing'/'ready' status wapas 'confirmed' nahi karega.
    if order.order_status in {"placed", "awaiting_payment"}:
        order.order_status = "confirmed"
    state = dict(customer.flow_state or {})
    state.pop("active_order", None)
    customer.flow_state = state
    db.flush()

    for reply in replies:
        if deliver_replies:
            deliver(db, customer, reply)
    return replies


def advance_order_status(db: Session, order: Order, status: str, deliver_reply: bool = True, actor: str = "system") -> Reply:
    """Order status badlo (validated transition) + audit + customer ko update."""
    previous = order.order_status
    validate_order_transition(previous, status)
    if status == previous:
        return Reply(text="", kind="none", intent=f"status_{status}")
    order.order_status = status
    if status == "cancelled":
        pricing.release_coupons_for_order(db, order.id)  # coupon wapas usable
    if status in {"delivered", "completed"}:
        order.delivered_at = order.delivered_at or utcnow()
    audit(db, actor=actor, action="order.status_changed", target=f"order:{order.order_no}", details={"from": previous, "to": status})
    customer = memory.get_customer(db, order.customer_phone)
    stages = {
        "confirmed": "Order confirm ho gaya sir ✅ Kitchen ne note kar liya.",
        "preparing": "Khana ban raha hai sir 👨‍🍳 Masala ekdum khushbu faila raha hai!",
        "packed": "Pack ho gaya sir 📦",
        "out_for_delivery": "Rider nikal gaya hai sir 🛵 Bas 10-15 minute!",
        "served": "Aapka order table par serve ho gaya hai sir 🍽️ Enjoy kijiye!",
        "delivered": "Order pahunch gaya sir 😄 Khana kaisa laga? 1 se 5 star dijiye — aapki raay se hum sudharte hain!",
        "completed": "Order complete ho gaya sir 🙏 Dobara zaroor aana!",
        "cancelled": "Order cancel kar diya gaya hai sir. Kuch aur chahiye to bataiye 🙏",
    }
    reply = Reply(text=stages.get(status, f"Order status: {status}"), intent=f"status_{status}")
    if status == "delivered" and customer:
        state = dict(customer.flow_state or {})
        state["awaiting_feedback"] = True
        customer.flow_state = state
        order.feedback_asked = True
    if deliver_reply and customer:
        deliver(db, customer, reply)
    db.flush()
    return reply


def simulate_inbound(
    db: Session,
    phone: str,
    text: str,
    profile_name: str | None = None,
    channel: str = "dashboard",
    base_url: str | None = None,
) -> HandleResult:
    """Dashboard ke Live Chat se message bhejna (asli WhatsApp jaisa hi pipeline)."""
    inbound = whatsapp.Inbound(phone=clean_phone(phone), profile_name=profile_name, type="text", text=text, source=channel)
    return handle_inbound(db, inbound, deliver_replies=True, base_url=base_url)
