"""Demo data — Sharma Cafe ka pura 1 mahine ka hisaab, taaki dashboard khaali na lage.

`python -m app.seed` chalao ya dashboard ka "Reset Demo Data" button dabao.
"""

from __future__ import annotations

import random
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import discounts, memory, menu as menu_engine
from .config import settings
from .models import Coupon, Customer, Feedback, MenuItem, Order, OrderItem, Payment, Reservation
from .pricing import build_bill
from .utils import clean_phone, money, now_ist, today_ist_date, utcnow

DEMO_CUSTOMERS: list[dict] = [
    dict(
        name="Rahul Sharma", phone="919876543210", veg="veg", days_ago_first=95,
        history=[
            (72, [("Paneer Butter Masala", 1), ("Butter Naan", 4), ("Sweet Lassi", 2)]),
            (54, [("Cold Coffee", 2), ("Veg Spring Roll", 1)]),
            (33, [("Dal Makhani", 1), ("Tandoori Roti", 6)]),
            (18, [("Paneer Butter Masala", 2), ("Garlic Naan", 4), ("Gulab Jamun", 2)]),
            (11, [("Margherita Pizza", 1), ("Cold Coffee", 2)]),
            (6, [("Chole Bhature", 2), ("Masala Chai", 2)]),
            (0, [("Cold Coffee", 2), ("Paneer Tikka", 1)]),
        ],
        notes=["kam mirchi", "naan extra butter"], birthday_offset=0, opt_in=True,
    ),
    dict(
        name="Priya Verma", phone="919876543211", veg="veg", days_ago_first=180,
        history=[
            (120, [("Masala Dosa", 2), ("Filter Coffee", 2)]),
            (95, [("Veg Hakka Noodles", 1), ("Chilli Paneer", 1)]),
            (64, [("Kadhai Paneer", 1), ("Laccha Paratha", 4)]),
            (41, [("Cold Coffee", 2), ("Choco Lava Cake", 1)]),
        ],
        notes=["no onion"], birthday_offset=76, opt_in=True,  # 30+ din se gayab -> winback candidate
    ),
    dict(
        name="Amit Kumar", phone="919876543212", veg="nonveg", days_ago_first=140,
        history=[
            (60, [("Butter Chicken", 1), ("Butter Naan", 4)]),
            (45, [("Chicken Biryani", 1), ("Sweet Lassi", 1)]),
            (30, [("Chicken Tikka", 1), ("Jeera Rice", 1)]),
            (22, [("Mutton Rogan Josh", 1), ("Tandoori Roti", 4)]),
            (9, [("Butter Chicken", 2), ("Garlic Naan", 6)]),
            (4, [("Chicken Fried Rice", 1), ("Chicken Burger", 1)]),
            (2, [("Meal for 2 (Dal Makhani + PBM + 4 Naan + 2 Lassi)", 1)]),
            (0, [("Butter Chicken", 1), ("Garlic Naan", 4), ("Cold Coffee", 1)]),
        ],
        notes=["spicy pasand hai"], birthday_offset=18, opt_in=True,
    ),
    dict(
        name="Sneha Joshi", phone="919876543213", veg="veg", days_ago_first=70,
        history=[
            (50, [("Farmhouse Pizza", 1), ("French Fries", 1), ("Cold Coffee", 1)]),
            (35, [("Chocolate Shake", 1), ("Veg Burger", 1)]),
            (20, [("Uttapam", 1), ("Fresh Lime Soda", 1)]),
            (13, [("Paneer Tikka", 1), ("Masala Papad", 1)]),
        ],
        notes=["dessert lover"], birthday_offset=2, opt_in=True,  # 2 din me birthday
    ),
    dict(
        name="Vikram Singh", phone="919876543214", veg="nonveg", days_ago_first=5,
        history=[(5, [("Egg Curry", 1), ("Tandoori Roti", 4)])],
        notes=[], birthday_offset=210, opt_in=False,  # naya, permission nahi li
    ),
    dict(
        name="Neha Gupta", phone="919876543215", veg="veg", days_ago_first=150,
        history=[
            (140, [("Veg Biryani", 1), ("Sweet Lassi", 1)]),
            (110, [("Dal Tadka", 1), ("Jeera Rice", 1)]),
            (85, [("Masala Dosa", 2)]),
        ],
        notes=["table window side pasand"], birthday_offset=140, opt_in=False, opted_out=True,
    ),
    dict(
        name="Karan Mehta", phone="919876543216", veg="veg", days_ago_first=60,
        history=[
            (44, [("Cold Coffee", 2), ("Veg Burger", 2)]),
            (28, [("Mix Veg", 1), ("Butter Naan", 4)]),
            (16, [("Rasmalai", 2), ("Masala Chai", 2)]),
            (7, [("Paneer Butter Masala", 1), ("Laccha Paratha", 2)]),
        ],
        notes=["regular customer"], birthday_offset=120, opt_in=True,
    ),
]

DEMO_FEEDBACK = [
    ("Rahul Sharma", 5, "Paneer butter masala ekdum lajawaab tha!"),
    ("Priya Verma", 5, "Cold coffee best hai yahan ki"),
    ("Vikram Singh", 2, "Roti thodi thandi thi aur order late aaya"),
    ("Sneha Joshi", 4, "Pizza achha tha, thoda cheese aur hota to maza aata"),
]

DEMO_COUPONS = [
    ("WELCOME10", 10, "welcome", "919876543214", False),
    ("MISSYOU20", 20, "winback", "919876543211", False),
    ("THANKS5", 5, "thanks", "919876543210", False),
    ("CARE777", 15, "manual", "919876543214", True),
]


def _demo_order(db: Session, customer: Customer, items: list[tuple[str, int]], days_ago: int, paid: bool = True) -> Order:
    lines: list[dict] = []
    for name, qty in items:
        item = menu_engine.find_item(db, name)
        if not item:
            continue
        lines.append({"name": item.name, "qty": qty, "unit_price": item.price})
    if not lines:
        return None  # type: ignore[return-value]

    subtotal = money(sum(line["qty"] * line["unit_price"] for line in lines))
    percent, code, reason, freebies = 0.0, None, None, []
    if paid and customer.total_orders == 0:
        percent, code, reason = 10.0, "WELCOME10", "Pehla order — Welcome 10% OFF"
    elif paid and customer.total_orders == 4:
        freebies = ["Cold Coffee"]
    elif paid and subtotal >= 999:
        freebies = ["Gulab Jamun"]

    bill_lines = [dict(line) for line in lines]
    for freebie in freebies:
        item = menu_engine.find_item(db, freebie)
        bill_lines.append({"name": item.name if item else freebie, "qty": 1, "unit_price": item.price if item else 0, "is_freebie": True})

    bill = build_bill(db, bill_lines, discount_percent=percent, discount_code=code, discount_reason=reason, freebies=freebies)
    created = utcnow() - timedelta(days=days_ago, hours=random.randint(0, 5), minutes=random.randint(0, 59))
    order = Order(
        order_no=f"{1000 + (db.scalar(select(func.count(Order.id))) or 0) + 1}",
        customer_id=customer.id,
        customer_phone=customer.phone,
        customer_name=customer.name,
        items=[
            {"name": line.name, "qty": line.qty, "price": line.unit_price, "line_total": line.line_total, "free": line.is_freebie}
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
        payment_status="paid" if paid else "pending",
        payment_link=None if paid else "/pay/demo",
        order_status="delivered" if paid else "awaiting_payment",
        channel=random.choice(["whatsapp", "whatsapp", "whatsapp", "qr", "dashboard"]),
        created_at=created,
        updated_at=created,
        paid_at=created if paid else None,
        delivered_at=created + timedelta(minutes=30) if paid else None,
        feedback_asked=paid,
    )
    db.add(order)
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
    if paid:
        payment = Payment(
            order_id=order.id,
            amount=order.total_amount,
            provider="mock",
            provider_ref=f"mock_demo_{order.order_no}",
            link=f"/pay/demo_{order.order_no}",
            status="paid",
            created_at=created,
            paid_at=created,
        )
        db.add(payment)
        memory.apply_order_to_memory(db, customer, order)
        # memory ke hisaab se last visit ko theek karo
        customer.last_visit_at = created
        customer.created_at = min(customer.created_at or created, created)
    db.flush()
    return order


def seed_demo(db: Session, force: bool = False) -> dict:
    """Poora demo setup — menu, rules, customers, orders, feedback, booking."""
    menu_added = menu_engine.ensure_menu(db)
    rules_added = discounts.seed_rules(db)

    existing = db.scalar(select(func.count(Customer.id))) or 0
    if existing > 0 and not force:
        db.commit()
        return {"menu_added": menu_added, "rules_added": rules_added, "customers": existing, "skipped": True}

    today = today_ist_date()
    for row in DEMO_CUSTOMERS:
        customer = Customer(
            phone=clean_phone(row["phone"]),
            name=row["name"],
            veg_pref=row["veg"],
            language="hinglish",
            notes=list(row.get("notes") or []),
            tags=["regular"] if len(row["history"]) >= 4 else ["new"],
            favourite_items=[],
            last_order_items=[],
            flow_state={},
            opt_in=bool(row.get("opt_in")),
            opted_out=bool(row.get("opted_out")),
            birthday=(today + timedelta(days=int(row["birthday_offset"]))).strftime("%m-%d"),
            first_seen_at=utcnow() - timedelta(days=int(row["days_ago_first"])),
            last_seen_at=utcnow() - timedelta(days=min(days for days, _ in row["history"])),
            created_at=utcnow() - timedelta(days=int(row["days_ago_first"])),
        )
        db.add(customer)
        db.flush()
        for days_ago, items in row["history"]:
            _demo_order(db, customer, items, days_ago, paid=True)
        customer.last_seen_at = customer.last_visit_at

    # aaj ke orders (dashboard me numbers dikhne ke liye)
    sneha = memory.get_customer(db, "919876543213")
    if sneha:
        _demo_order(db, sneha, [("Farmhouse Pizza", 1), ("Cold Coffee", 2), ("Choco Lava Cake", 2)], 0, paid=True)

    # ek pending payment wala order (dashboard ke liye interesting case)
    pending_customer = memory.get_customer(db, "919876543216")
    if pending_customer:
        _demo_order(db, pending_customer, [("Paneer Tikka", 2), ("Cold Coffee", 2)], 0, paid=False)

    # owner bhi ek "customer" hai — report usko jaati hai
    owner = memory.get_or_create_customer(db, settings.owner_whatsapp, "Owner (Restaurant)")[0]
    owner.tags = sorted(set(list(owner.tags or []) + ["owner"]))
    owner.opt_in = True

    # feedback
    for name, rating, comment in DEMO_FEEDBACK:
        customer = db.scalar(select(Customer).where(Customer.name == name))
        if not customer:
            continue
        last_order = db.scalar(select(Order).where(Order.customer_phone == customer.phone).order_by(Order.created_at.desc()).limit(1))
        db.add(
            Feedback(
                customer_phone=customer.phone,
                customer_name=customer.name,
                order_id=last_order.id if last_order else None,
                rating=rating,
                comment=comment,
                created_at=utcnow() - timedelta(days=random.randint(1, 12)),
            )
        )

    # coupons
    for code, percent, source, phone, used in DEMO_COUPONS:
        if db.scalar(select(Coupon).where(Coupon.code == code)):
            continue
        db.add(
            Coupon(
                code=code,
                discount_percent=percent,
                customer_phone=phone,
                source=source,
                is_used=used,
                used_at=utcnow() - timedelta(days=3) if used else None,
                expiry_date=utcnow() + timedelta(days=20),
            )
        )

    # table bookings — ek aaj (reminder test) + ek kal
    rahul = memory.get_customer(db, "919876543210")
    amit = memory.get_customer(db, "919876543212")
    if rahul:
        slot = now_ist() + timedelta(minutes=45)
        db.add(
            Reservation(
                customer_phone=rahul.phone,
                customer_name=rahul.name,
                date=today,
                time=slot.strftime("%H:%M"),
                persons=4,
                status="confirmed",
                notes="window side table",
            )
        )
    if amit:
        db.add(
            Reservation(
                customer_phone=amit.phone,
                customer_name=amit.name,
                date=today + timedelta(days=1),
                time="20:30",
                persons=6,
                status="confirmed",
                notes="birthday dinner, cake le aayenge",
            )
        )

    db.commit()
    return {
        "menu_added": menu_added,
        "rules_added": rules_added,
        "customers": db.scalar(select(func.count(Customer.id))),
        "orders": db.scalar(select(func.count(Order.id))),
        "feedback": db.scalar(select(func.count(Feedback.id))),
        "reservations": db.scalar(select(func.count(Reservation.id))),
        "skipped": False,
    }


def reset_demo(db: Session) -> dict:
    """Sab data saaf karke naya demo banao (demo button ke liye)."""
    for table in (Payment, OrderItem, Order, Feedback, Reservation, Coupon, Customer, MenuItem,):
        db.query(table).delete()
    from .models import Alert as AlertModel
    from .models import Campaign as CampaignModel
    from .models import DiscountRule as RuleModel
    from .models import Message as MessageModel

    for table in (MessageModel, AlertModel, CampaignModel, RuleModel):
        db.query(table).delete()
    db.commit()
    return seed_demo(db, force=True)


def main() -> None:  # pragma: no cover
    from .database import init_db, session_scope

    init_db()
    with session_scope() as db:
        result = seed_demo(db, force="--force" in __import__("sys").argv)
    print("Seed result:", result)


if __name__ == "__main__":  # pragma: no cover
    main()
