"""Customer Memory — report ka Section 4 (sabse kamaal wala hissa).

Pehchan = WhatsApp number. Har message par pehle yahi poocha jata hai:
"Ye number pehle aaya hai kya?" Agar haan, to naam, pasand, last order,
birthday, points — sab yaad rehta hai. Kabhi bhoolta nahi.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from . import menu as menu_engine
from .models import Customer, Feedback, Order, Reservation
from .utils import clean_phone, days_between, detect_language, now_ist, title_name, utcnow


def get_customer(db: Session, phone: str) -> Customer | None:
    phone = clean_phone(phone)
    return db.scalar(select(Customer).where(Customer.phone == phone))


def get_or_create_customer(db: Session, phone: str, profile_name: str | None = None, channel: str = "whatsapp") -> tuple[Customer, bool]:
    """Return (customer, is_new). Naya customer banate waqt WhatsApp profile naam use karo."""
    phone = clean_phone(phone)
    customer = get_customer(db, phone)
    if customer:
        if profile_name and not customer.name:
            customer.name = title_name(profile_name)
        customer.last_seen_at = utcnow()
        if not customer.favourite_items:
            customer.favourite_items = []
        if not customer.notes:
            customer.notes = []
        if not customer.tags:
            customer.tags = []
        return customer, False

    customer = Customer(
        phone=phone,
        name=title_name(profile_name),
        language="hinglish",
        favourite_items=[],
        notes=[],
        tags=["new"],
        last_order_items=[],
        flow_state={},
        first_seen_at=utcnow(),
        last_seen_at=utcnow(),
    )
    db.add(customer)
    db.flush()
    return customer, True


def remember_name(db: Session, customer: Customer, name: str) -> bool:
    """Customer "mera naam Rahul hai" bole to naam yaad rakho."""
    cleaned = title_name(name)
    if not cleaned:
        return False
    customer.name = cleaned
    if "named" not in (customer.tags or []):
        customer.tags = list(customer.tags or []) + ["named"]
    db.flush()
    return True


def customer_context(db: Session, customer: Customer) -> dict:
    """AI ko dene wala memory packet — 'yaad-dasht' ka asli jadoo."""
    last = db.scalar(
        select(Order).where(Order.customer_phone == customer.phone).order_by(Order.created_at.desc()).limit(1)
    )
    visits = customer.total_orders or 0
    days_since = days_between(customer.last_visit_at, utcnow()) if customer.last_visit_at else None
    tags = customer.tags or []
    return {
        "phone": customer.phone,
        "name": customer.name,
        # profile naam se "purana customer" nahi ban jaata — visit ya apna bataya naam chahiye
        "is_known": visits > 0 or "named" in tags,
        "is_first_timer": visits == 0,
        "visits": visits,
        "total_spent": round(customer.total_spent or 0),
        "loyalty_points": customer.loyalty_points or 0,
        "likes": (customer.favourite_items or [])[:5],
        "notes": (customer.notes or [])[:5],
        "tags": customer.tags or [],
        "veg_pref": customer.veg_pref,
        "birthday": customer.birthday,
        "last_order_summary": customer.last_order_summary,
        "last_order_at": last.created_at.isoformat() if last else None,
        "days_since_last_visit": days_since,
        "language": customer.language,
        "human_mode": customer.human_mode,
    }


def apply_order_to_memory(db: Session, customer: Customer, order: Order) -> None:
    """Order hone ke baad customer ki file update karo (visits, pasand, points)."""
    customer.total_visits = (customer.total_visits or 0) + 1
    customer.total_orders = (customer.total_orders or 0) + 1
    customer.total_spent = round(float(customer.total_spent or 0) + float(order.total_amount or 0), 2)
    customer.last_visit_at = order.created_at or utcnow()
    customer.last_order_summary = menu_engine.order_summary_text(order.items or [])
    customer.last_order_items = [
        {"name": row.get("name"), "qty": row.get("qty", 1)} for row in (order.items or []) if isinstance(row, dict)
    ]
    for row in order.items or []:
        if isinstance(row, dict):
            _bump_favourite(customer, row.get("name", ""))
    for row in order.items or []:
        if isinstance(row, dict):
            item = menu_engine.find_item(db, row.get("name", ""))
            if item:
                item.sold_count = (item.sold_count or 0) + int(row.get("qty", 1))
    if order.payment_status == "paid":
        earn_loyalty_points(customer, order.total_amount)
    tags = set(customer.tags or [])
    tags.discard("new")
    if customer.total_orders >= 5:
        tags.add("regular")
    if customer.total_orders >= 10:
        tags.add("vip")
    cust_veg = all(
        (menu_engine.find_item(db, row.get("name", "")) is None or menu_engine.find_item(db, row.get("name", "")).is_veg)
        for row in (order.items or [])
        if isinstance(row, dict)
    ) and bool(order.items)
    if cust_veg:
        customer.veg_pref = "veg"
    elif not customer.veg_pref or customer.veg_pref == "any":
        customer.veg_pref = "nonveg"
    customer.tags = sorted(tags)
    db.flush()


def _bump_favourite(customer: Customer, item_name: str) -> None:
    if not item_name:
        return
    favs = list(customer.favourite_items or [])
    for row in favs:
        if isinstance(row, dict) and row.get("name") == item_name:
            row["count"] = int(row.get("count", 1)) + 1
            favs.sort(key=lambda r: -int(r.get("count", 1)))
            customer.favourite_items = favs
            return
    favs.append({"name": item_name, "count": 1})
    favs.sort(key=lambda r: -int(r.get("count", 1)))
    customer.favourite_items = favs[:10]


def remember_note(customer: Customer, note: str) -> None:
    """'kam mirchi', 'no onion' jaisi baat hamesha yaad rakho."""
    note = (note or "").strip()[:80]
    if not note:
        return
    notes = list(customer.notes or [])
    if note.lower() not in [n.lower() for n in notes]:
        notes.append(note)
    customer.notes = notes[-10:]


def earn_loyalty_points(customer: Customer, amount: float) -> int:
    """Har ₹100 par points (config: LOYALTY_POINTS_PER_100)."""
    from .config import settings

    earned = int(float(amount or 0) / 100 * settings.loyalty_points_per_100)
    customer.loyalty_points = int(customer.loyalty_points or 0) + earned
    return earned


def nights_since_last_visit(customer: Customer) -> int | None:
    if not customer.last_visit_at:
        return None
    return days_between(customer.last_visit_at, utcnow())


def next_loyalty_milestone(customer: Customer) -> dict:
    """'Sirf 20 points aur, phir free coffee!' wala hisaab."""
    from .config import settings

    target = settings.free_coffee_points
    points = int(customer.loyalty_points or 0)
    remaining = max(0, target - points)
    return {"target": target, "points": points, "remaining": remaining, "unlocked": remaining == 0}


# --------------------------------------------------------------------------
# Segments — broadcast/winback/birthday ke liye list
# --------------------------------------------------------------------------
def all_customers(db: Session, only_opt_in: bool = False) -> list[Customer]:
    stmt = select(Customer).where(Customer.blocked.is_(False))
    if only_opt_in:
        stmt = stmt.where(Customer.opt_in.is_(True), Customer.opted_out.is_(False))
    return list(db.scalars(stmt.order_by(Customer.last_seen_at.desc())))


def upcoming_birthdays(db: Session, within_days: int = 0) -> list[Customer]:
    """Aaj (ya aane wale N din me) birthday wale customers. birthday 'MM-DD' me save hai."""
    today = now_ist().date()
    targets = {(today + timedelta(days=offset)).strftime("%m-%d") for offset in range(0, within_days + 1)}
    rows = db.scalars(select(Customer).where(Customer.birthday.is_not(None), Customer.blocked.is_(False)))
    return [c for c in rows if (c.birthday or "") in targets]


def winback_candidates(db: Session, days: int | None = None) -> list[Customer]:
    """Jo customer 20-30 din se nahi aaya — use wapas bulana hai."""
    from .config import settings

    days = days or settings.winback_days
    cutoff = utcnow() - timedelta(days=days)
    rows = db.scalars(
        select(Customer)
        .where(Customer.blocked.is_(False), Customer.total_orders >= 1, Customer.last_visit_at.is_not(None))
        .where(Customer.last_visit_at <= cutoff)
        .order_by(Customer.total_spent.desc())
    )
    return list(rows)


def lapsed_days(customer: Customer) -> int:
    return days_between(customer.last_visit_at, utcnow()) if customer.last_visit_at else 0


def find_by_name(db: Session, name: str) -> list[Customer]:
    """Dashboard search — naam ya number se."""
    name = (name or "").strip()
    digits = "".join(ch for ch in name if ch.isdigit())
    stmt = select(Customer)
    if digits:
        stmt = stmt.where(or_(Customer.phone.like(f"%{digits}%"), func.lower(Customer.name).like(f"%{name.lower()}%")))
    elif name:
        stmt = stmt.where(func.lower(Customer.name).like(f"%{name.lower()}%"))
    return list(db.scalars(stmt.limit(20)))


def customer_profile(db: Session, customer: Customer) -> dict:
    """Dashboard detail panel ke liye poora profile."""
    orders = list(
        db.scalars(select(Order).where(Order.customer_phone == customer.phone).order_by(Order.created_at.desc()).limit(10))
    )
    reservations = list(
        db.scalars(select(Reservation).where(Reservation.customer_phone == customer.phone).order_by(Reservation.created_at.desc()).limit(5))
    )
    feedback = list(
        db.scalars(select(Feedback).where(Feedback.customer_phone == customer.phone).order_by(Feedback.created_at.desc()).limit(5))
    )
    return {
        "customer": customer_context(db, customer),
        "orders": [
            {
                "order_no": o.order_no,
                "items": o.items,
                "total": o.total_amount,
                "status": o.order_status,
                "payment_status": o.payment_status,
                "created_at": o.created_at.isoformat() if o.created_at else None,
            }
            for o in orders
        ],
        "reservations": [
            {"date": str(r.date), "time": r.time, "persons": r.persons, "status": r.status} for r in reservations
        ],
        "feedback": [
            {"rating": f.rating, "comment": f.comment, "created_at": f.created_at.isoformat() if f.created_at else None}
            for f in feedback
        ],
        "language_detected": detect_language(customer.last_order_summary or ""),
    }
