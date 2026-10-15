"""Reports — owner ko roz raat ka WhatsApp report (F19) + dashboard numbers."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .models import Alert, Campaign, Customer, Feedback, Message, Order, Reservation
from .utils import ist_day_bounds_utc, money, now_ist, rupees, today_ist_date, utcnow


def orders_between(db: Session, start: datetime, end: datetime) -> list[Order]:
    return list(
        db.scalars(
            select(Order)
            .where(Order.created_at >= start, Order.created_at < end, Order.order_status != "cancelled")
            .order_by(Order.created_at)
        )
    )


def daily_report(db: Session, day: date | None = None) -> dict:
    """Ek din ka poora hisaab (IST ke hisaab se)."""
    start, end = ist_day_bounds_utc(day)
    orders = orders_between(db, start, end)
    paid = [o for o in orders if o.payment_status == "paid"]
    sale = money(sum(float(o.total_amount or 0) for o in paid))
    billed = money(sum(float(o.total_amount or 0) for o in orders))
    discount_given = money(sum(float(o.discount_amount or 0) for o in orders))
    pending = money(sum(float(o.total_amount or 0) for o in orders if o.payment_status == "pending"))

    item_counts: dict[str, int] = {}
    for order in orders:
        for row in order.items or []:
            if not isinstance(row, dict):
                continue
            name = row.get("name", "")
            item_counts[name] = item_counts.get(name, 0) + int(row.get("qty", 1))
    top_items = sorted(item_counts.items(), key=lambda kv: kv[1], reverse=True)[:5]

    new_customers = list(
        db.scalars(select(Customer).where(Customer.first_seen_at >= start, Customer.first_seen_at < end))
    )
    repeat_customers = len({o.customer_phone for o in orders if (o.customer_name or o.customer_phone)})
    reservations = list(
        db.scalars(select(Reservation).where(Reservation.created_at >= start, Reservation.created_at < end))
    )
    feedback = list(db.scalars(select(Feedback).where(Feedback.created_at >= start, Feedback.created_at < end)))
    alerts = list(db.scalars(select(Alert).where(Alert.created_at >= start, Alert.created_at < end)))
    messages_in = db.scalar(select(func.count(Message.id)).where(Message.created_at >= start, Message.created_at < end, Message.direction == "in")) or 0
    campaigns = list(db.scalars(select(Campaign).where(Campaign.sent_at >= start, Campaign.sent_at < end)))

    avg_rating = round(sum(f.rating for f in feedback) / len(feedback), 1) if feedback else 0
    return {
        "date": str(day or today_ist_date()),
        "sales": sale,
        "billed": billed,
        "orders": len(orders),
        "paid_orders": len(paid),
        "avg_order_value": money(sale / len(paid)) if paid else 0,
        "discount_given": discount_given,
        "pending_amount": pending,
        "top_items": top_items,
        "new_customers": len(new_customers),
        "repeat_customers": repeat_customers,
        "reservations": len(reservations),
        "feedback_count": len(feedback),
        "avg_rating": avg_rating,
        "complaints": len([a for a in alerts if a.kind == "complaint"]),
        "messages_in": messages_in,
        "campaigns_sent": len(campaigns),
        "hourly": _hourly_orders(orders),
    }


def _hourly_orders(orders: list[Order]) -> list[dict]:
    buckets = {hour: 0 for hour in range(9, 24)}
    for order in orders:
        if not order.created_at:
            continue
        ist_hour = (order.created_at + timedelta(hours=5, minutes=30)).hour
        if ist_hour in buckets:
            buckets[ist_hour] += 1
    return [{"hour": hour, "orders": count} for hour, count in buckets.items()]


def daily_report_text(db: Session, day: date | None = None) -> str:
    """Owner ke WhatsApp par jaane wala message (F19)."""
    report = daily_report(db, day)
    top = report["top_items"][0][0] if report["top_items"] else "—"
    lines = [
        f"*{settings.restaurant_name} — Aaj ki Report* 📊",
        f"📅 {report['date']}",
        "",
        f"💰 Sale: {rupees(report['sales'])} ({report['paid_orders']} paid orders)",
        f"🧾 Kul order: {report['orders']} | Avg bill: {rupees(report['avg_order_value'])}",
        f"🎁 Discount diya: {rupees(report['discount_given'])}",
        f"⏳ Payment pending: {rupees(report['pending_amount'])}",
        f"🏆 Sabse zyada bika: {top}",
        f"🆕 Naye customer: {report['new_customers']} | Repeat: {report['repeat_customers']}",
        f"📅 Table booking: {report['reservations']}",
        f"⭐ Rating: {report['avg_rating'] or '—'}/5 ({report['feedback_count']} feedback)",
    ]
    if report["complaints"]:
        lines.append(f"🚨 Complaint: {report['complaints']} — dashboard me dekhiye!")
    lines.append("")
    lines.append("Kal bhi aise hi chalta rahe, aap tension na lo 😄 — " + settings.agent_name)
    return "\n".join(lines)


def send_owner_report(db: Session, day: date | None = None) -> dict:
    """Owner ko report bhejo aur Campaign me record rakho."""
    from . import whatsapp

    text = daily_report_text(db, day)
    campaign = Campaign(
        name=f"Daily report {day or today_ist_date()}",
        kind="report",
        message=text,
        audience_count=1,
        sent_count=0,
        status="sent",
        sent_at=utcnow(),
    )
    db.add(campaign)
    if settings.owner_whatsapp:
        result = whatsapp.send_text(settings.owner_whatsapp, text)
        campaign.sent_count = 1 if result and result[0].get("ok") else 0
    db.flush()
    return {"sent": True, "text": text, "campaign_id": campaign.id}


def weekly_summary(db: Session) -> dict:
    days = [(today_ist_date() - timedelta(days=offset)) for offset in range(6, -1, -1)]
    rows = [daily_report(db, day) for day in days]
    return {
        "days": rows,
        "sales": money(sum(row["sales"] for row in rows)),
        "orders": sum(row["orders"] for row in rows),
        "new_customers": sum(row["new_customers"] for row in rows),
        "avg_rating": round(sum(row["avg_rating"] for row in rows if row["avg_rating"]) / max(1, len([r for r in rows if r["avg_rating"]])), 1),
    }


def dashboard_summary(db: Session) -> dict:
    """Dashboard ke top cards."""
    today = daily_report(db)
    week = weekly_summary(db)
    total_customers = db.scalar(select(func.count(Customer.id))) or 0
    pending_orders = db.scalar(select(func.count(Order.id)).where(Order.payment_status == "pending")) or 0
    open_alerts = db.scalar(select(func.count(Alert.id)).where(Alert.is_read.is_(False))) or 0
    upcoming = db.scalar(
        select(func.count(Reservation.id)).where(Reservation.date >= today_ist_date(), Reservation.status == "confirmed")
    ) or 0
    return {
        "today": today,
        "week": week,
        "customers": total_customers,
        "pending_orders": pending_orders,
        "open_alerts": open_alerts,
        "upcoming_reservations": upcoming,
        "generated_at": now_ist().strftime("%d %b %Y, %H:%M IST"),
        "modes": settings.mode_report(),
    }
