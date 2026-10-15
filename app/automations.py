"""Automations — woh kaam jo agent khud karta hai (report F11-F15, F19).

Roz ke kaam:
  1. Subah 9 baje  -> birthday wish + free dessert (F11)
  2. Har 30 min    -> order status aage badhana (kitchen -> rider -> delivered) (F10)
  3. Delivery ke 1 ghante baad -> feedback maangna (F14)
  4. Booking se 1 ghanta pehle -> reminder
  5. Raat 11 baje  -> owner ko daily report (F19)
  6. Roz ek baar   -> 30 din se gayab customers ko winback offer (F12) — sirf opt-in
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import discounts, memory, orchestrator, reports, whatsapp
from .config import settings
from .models import Campaign, Customer, Message, Order, Reservation
from .utils import now_ist, today_ist_date, utcnow

# order kanha se kanha jayega (minute = order confirm hone ke kitne minute baad)
STATUS_FLOW: list[tuple[str, int]] = [
    ("preparing", 2),
    ("packed", 8),
    ("out_for_delivery", 11),
    ("delivered", 18),
]


def _already_today(db: Session, phone: str, intent: str) -> bool:
    start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    # IST ke hisaab se din ka start (UTC me)
    start = datetime.combine(today_ist_date(), datetime.min.time()) - timedelta(hours=5, minutes=30)
    row = db.scalar(
        select(Message.id)
        .where(Message.customer_phone == phone, Message.intent == intent, Message.direction == "out", Message.created_at >= start)
        .limit(1)
    )
    return row is not None


def can_receive_marketing(customer: Customer) -> bool:
    """Marketing (birthday offer, winback, broadcast) ke liye SEND-TIME check.

    Opt-in zaroori hai; STOP (opted_out) ya block hone par kabhi nahi. Force flag isse override nahi karta.
    """
    return bool(customer.opt_in) and not customer.opted_out and not customer.blocked


def _sent_today_count(db: Session, kind: str) -> int:
    start = datetime.combine(today_ist_date(), datetime.min.time()) - timedelta(hours=5, minutes=30)
    rows = list(db.scalars(select(Campaign).where(Campaign.kind == kind, Campaign.created_at >= start)))
    return sum(int(row.sent_count or 0) for row in rows)


# --------------------------------------------------------------------------
def send_birthday_wishes(db: Session, force: bool = False) -> dict:
    """Aaj birthday wale customers — wish + free dessert coupon (F11)."""
    customers = memory.upcoming_birthdays(db, within_days=0)
    sent, skipped = [], []
    for customer in customers:
        if not can_receive_marketing(customer):
            skipped.append(customer.phone)  # consent nahi / STOP — force se bhi nahi bhejte
            continue
        if not force and _already_today(db, customer.phone, "birthday_wish"):
            skipped.append(customer.phone)
            continue
        rule_coupon = discounts.issue_coupon(
            db, percent=0, source="birthday", customer_phone=customer.phone, free_item_name="Choco Lava Cake", valid_days=7
        )
        text = discounts.birthday_message(customer, rule_coupon.free_item_name)
        text += f"\n\nCoupon: *{rule_coupon.code}* (7 din tak valid, aaj hi aa jaiye 😄)"
        whatsapp.send_text(customer.phone, text)
        orchestrator.log_message(db, customer.phone, "out", text, message_type="text", intent="birthday_wish")
        sent.append({"phone": customer.phone, "name": customer.name})
    campaign = Campaign(
        name=f"Birthday wishes {today_ist_date()}",
        kind="birthday",
        message="Happy Birthday + free dessert coupon",
        audience_count=len(customers),
        sent_count=len(sent),
        skipped_count=len(skipped),
        status="sent" if sent else "draft",
        details={"sent": sent, "skipped": skipped},
        sent_at=utcnow() if sent else None,
    )
    db.add(campaign)
    db.flush()
    return {"sent": len(sent), "skipped": len(skipped), "details": sent, "campaign_id": campaign.id}


def send_winback_offers(db: Session, limit: int | None = None, force: bool = False) -> dict:
    """20-30 din se gayab customers ko 20% OFF (F12). Sirf opt-in / force se."""
    limit = limit or settings.max_proactive_per_day
    candidates = memory.winback_candidates(db)
    sent, skipped = [], []
    for customer in candidates:
        if len(sent) >= limit:
            break
        if not can_receive_marketing(customer):
            skipped.append(customer.phone)  # bina permission / STOP ke spam nahi (Section 17, 22)
            continue
        if not force and _already_today(db, customer.phone, "winback"):
            skipped.append(customer.phone)
            continue
        coupon = discounts.issue_coupon(db, percent=20, source="winback", customer_phone=customer.phone, valid_days=15)
        text = discounts.winback_message(customer, coupon)
        whatsapp.send_text(customer.phone, text)
        orchestrator.log_message(db, customer.phone, "out", text, message_type="text", intent="winback")
        sent.append({"phone": customer.phone, "name": customer.name, "days_gone": memory.lapsed_days(customer)})
    campaign = Campaign(
        name=f"Winback {today_ist_date()}",
        kind="winback",
        message="20% OFF for lapsed customers",
        audience_count=len(candidates),
        sent_count=len(sent),
        skipped_count=len(skipped),
        status="sent" if sent else "draft",
        details={"sent": sent, "skipped": skipped},
        sent_at=utcnow() if sent else None,
    )
    db.add(campaign)
    db.flush()
    return {"sent": len(sent), "skipped": len(skipped), "details": sent, "campaign_id": campaign.id}


def send_broadcast(db: Session, message: str, only_opt_in: bool = True, limit: int | None = None) -> dict:
    """Offer broadcast (F15) — HAMESHA sirf opt-in customers ko. `only_opt_in=False` ignore hota hai (consent non-negotiable)."""
    limit = limit or settings.max_proactive_per_day
    audience = memory.all_customers(db, only_opt_in=True)
    sent, skipped = [], []
    for customer in audience:
        if len(sent) >= limit:
            break
        if not can_receive_marketing(customer):
            skipped.append(customer.phone)
            continue
        if _already_today(db, customer.phone, "broadcast"):
            skipped.append(customer.phone)
            continue
        name = (customer.name or "").split()[0]
        text = message.replace("{name}", name) if name else message.replace("{name}", "ji")
        if "stop" not in text.lower():
            text += "\n\n(Offers band karne ke liye STOP likh dijiye)"
        whatsapp.send_text(customer.phone, text)
        orchestrator.log_message(db, customer.phone, "out", text, message_type="text", intent="broadcast")
        sent.append(customer.phone)
    campaign = Campaign(
        name=f"Broadcast {now_ist().strftime('%d %b %H:%M')}",
        kind="broadcast",
        message=message,
        audience_count=len(audience),
        sent_count=len(sent),
        skipped_count=len(skipped),
        status="sent" if sent else "draft",
        details={"phones": sent[:100], "skipped": skipped[:100]},
        sent_at=utcnow() if sent else None,
    )
    db.add(campaign)
    db.flush()
    return {"sent": len(sent), "skipped": len(skipped), "audience": len(audience), "campaign_id": campaign.id}


def progress_orders(db: Session, force: bool = False) -> list[dict]:
    """Cooking pipeline aage badhao + customer ko update bhejo (F10)."""
    open_orders = list(
        db.scalars(
            select(Order).where(
                Order.order_status.in_(["confirmed", "preparing", "packed", "out_for_delivery"]),
                Order.payment_status.in_(["paid", "cod"]),
            )
        )
    )
    moved: list[dict] = []
    for order in open_orders:
        base = order.updated_at or order.created_at or utcnow()
        minutes = (utcnow() - base).total_seconds() / 60
        stage_index = [stage for stage, _ in STATUS_FLOW].index(order.order_status) if order.order_status in [s for s, _ in STATUS_FLOW] else -1
        for idx, (status, after) in enumerate(STATUS_FLOW):
            if idx <= stage_index:
                continue
            if minutes >= after or force:
                orchestrator.advance_order_status(db, order, status, actor="automation")
                moved.append({"order_no": order.order_no, "status": status})
                break
    return moved


def send_feedback_requests(db: Session) -> list[dict]:
    """Delivered order ke 1 ghante baad feedback maango (F14)."""
    cutoff = utcnow() - timedelta(hours=1)
    orders = list(
        db.scalars(
            select(Order).where(
                Order.order_status == "delivered",
                Order.feedback_asked.is_(False),
                Order.delivered_at.is_not(None),
                Order.delivered_at <= cutoff,
            )
        )
    )
    sent = []
    for order in orders:
        customer = memory.get_customer(db, order.customer_phone)
        if not customer:
            continue
        text = (
            f"{customer.name or 'Sir'} ji, khana kaisa laga? 😄\n"
            f"1 se 5 star dijiye — sirf ek number likh dena (jaise *5*).\n"
            f"Aapki raay se hi hum sudhrte hain 🙏"
        )
        whatsapp.send_text(customer.phone, text)
        orchestrator.log_message(db, customer.phone, "out", text, message_type="text", intent="feedback_ask")
        state = dict(customer.flow_state or {})
        state["awaiting_feedback"] = True
        customer.flow_state = state
        order.feedback_asked = True
        sent.append({"phone": customer.phone, "order_no": order.order_no})
    db.flush()
    return sent


def send_reservation_reminders(db: Session) -> list[dict]:
    """Booking se 1 ghanta pehle yaad dilana (F9)."""
    rows = list(
        db.scalars(
            select(Reservation).where(
                Reservation.status == "confirmed",
                Reservation.reminder_sent.is_(False),
                Reservation.date == today_ist_date(),
            )
        )
    )
    sent = []
    for reservation in rows:
        try:
            hour, minute = (reservation.time or "00:00").split(":")
            slot = datetime.combine(reservation.date, datetime.min.time()).replace(hour=int(hour), minute=int(minute))
        except (ValueError, AttributeError):
            continue
        until = slot - now_ist()
        if until > timedelta(minutes=settings.reservation_reminder_minutes):
            continue  # abhi bahut door hai — window me aane par bhejenge
        if until < timedelta(minutes=-5):
            reservation.reminder_sent = True  # slot nikal chuka — purani booking ka reminder nahi bhejte
            continue
        text = (
            f"Reminder sir! 🍽️ Aapki table {reservation.persons} log ke liye aaj "
            f"{reservation.time} par book hai — {settings.restaurant_name}.\n"
            f"Table taiyaar rahegi, bas aa jaiye 😄"
        )
        whatsapp.send_text(reservation.customer_phone, text)
        orchestrator.log_message(db, reservation.customer_phone, "out", text, message_type="text", intent="reservation_reminder")
        reservation.reminder_sent = True
        sent.append({"phone": reservation.customer_phone, "time": reservation.time})
    db.flush()
    return sent


def send_owner_report_if_due(db: Session) -> dict | None:
    """Raat ke set time par owner ko report (F19)."""
    now = now_ist()
    target_hour, target_minute = _parse_time(settings.owner_report_time)
    if now.hour < target_hour or (now.hour == target_hour and now.minute < target_minute):
        return None
    if _sent_today_count(db, "report") > 0:
        return None
    result = reports.send_owner_report(db)
    return {"sent": True, "campaign_id": result["campaign_id"]}


def _parse_time(value: str, default: tuple[int, int] = (23, 0)) -> tuple[int, int]:
    try:
        hour, minute = value.split(":")
        return int(hour), int(minute)
    except (ValueError, AttributeError):
        return default


def run_due_tasks(db: Session, force: bool = False) -> dict:
    """Scheduler ek baar chalao — jo due hai wo karo.

    `force=True` (dashboard ka "abhi chalao" button) sirf *time/dedupe* check hataata hai —
    customer ki permission (opt-in) aur STOP kabhi override nahi hote.
    """
    result: dict = {"at": now_ist().isoformat(), "tasks": {}}
    if not settings.automation_enabled and not force:
        result["skipped"] = "automation disabled"
        return result

    result["tasks"]["orders_progressed"] = progress_orders(db, force=force)
    result["tasks"]["feedback_requests"] = send_feedback_requests(db)
    result["tasks"]["reservation_reminders"] = send_reservation_reminders(db)

    if force or _time_reached(settings.birthday_time):
        result["tasks"]["birthdays"] = send_birthday_wishes(db, force=force)

    if force or _time_reached("20:00"):
        result["tasks"]["winback"] = send_winback_offers(db, force=force)

    report = send_owner_report_if_due(db)
    if report:
        result["tasks"]["owner_report"] = report
    db.commit()
    return result


def _time_reached(value: str) -> bool:
    now = now_ist()
    hour, minute = _parse_time(value)
    return (now.hour, now.minute) >= (hour, minute)


def stats_overview(db: Session) -> dict:
    """Automation ki health — dashboard me dikhta hai."""
    from sqlalchemy import func

    campaigns = db.scalar(select(func.count(Campaign.id))) or 0
    return {
        "automation_enabled": settings.automation_enabled,
        "owner_report_time": settings.owner_report_time,
        "birthday_time": settings.birthday_time,
        "winback_days": settings.winback_days,
        "campaigns": campaigns,
        "proactive_limit_per_day": settings.max_proactive_per_day,
    }
