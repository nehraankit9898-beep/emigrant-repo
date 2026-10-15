"""Discount / Coupon Rule Engine — report ka Section 5.

**Sabse bada rule:** Discount AI nahi deta, *tumhara rule* deta hai.
Ye file pehle se tay ki gayi table par chalti hai. AI bas bolta hai
"aapko 10% off mila hai", percent yahan se aata hai.
"""

from __future__ import annotations

import secrets
import string
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import Coupon, Customer, DiscountRule
from .utils import money, now_ist, rupees, utcnow

# --------------------------------------------------------------------------
# Default rules — dashboard se edit ho sakte hain
# --------------------------------------------------------------------------
DEFAULT_RULES: list[dict] = [
    dict(code="WELCOME10", name="Pehla order — Welcome 10% OFF", trigger="first_order",
         condition={"order_number": 1}, reward={"type": "percent", "value": 10}, priority=10,
         message="Pehli baar aane ki khushi me 10% OFF (code: WELCOME10) 🎉"),
    dict(code="REGULAR15", name="3rd order — Regular 15% OFF", trigger="nth_order",
         condition={"order_number": 3}, reward={"type": "percent", "value": 15}, priority=20,
         message="Aap hamare regular ban gaye — 15% OFF (code: REGULAR15) 🙌"),
    dict(code="LOYALFREE", name="5th order — Coffee FREE", trigger="nth_order",
         condition={"order_number": 5}, reward={"type": "free_item", "item": "Cold Coffee"}, priority=15,
         message="5th order par ek Cold Coffee bilkul FREE ☕"),
    dict(code="BIGBILL", name="Bill ₹999+ — Dessert FREE", trigger="bill_amount",
         condition={"min_bill": 999}, reward={"type": "free_item", "item": "Gulab Jamun"}, priority=30,
         message="Bada order! Ek Gulab Jamun hamari taraf se 🎁"),
    dict(code="BIRTHDAY", name="Birthday din — Dessert FREE + wish", trigger="birthday",
         condition={}, reward={"type": "free_item", "item": "Choco Lava Cake"}, priority=5,
         message="Happy Birthday! Aaj ek dessert bilkul FREE 🎂"),
    dict(code="MISSYOU20", name="30 din gayab — 20% OFF", trigger="winback",
         condition={"days": 30}, reward={"type": "percent", "value": 20}, priority=25,
         message="Aapko bahut yaad kiya! 20% OFF (code: MISSYOU20) 😄"),
    dict(code="THANKS5", name="Thanks ke baad agle order par 5%", trigger="thanks",
         condition={}, reward={"type": "percent", "value": 5, "for_next_order": True}, priority=40,
         message="Shukriya! Agle order ke liye 5% ka tohfa code bhej raha hoon 🎁"),
]


def seed_rules(db: Session, force: bool = False) -> int:
    if force:
        db.query(DiscountRule).delete()
    existing = db.scalar(select(DiscountRule).limit(1))
    if existing and not force:
        return 0
    added = 0
    for row in DEFAULT_RULES:
        if db.scalar(select(DiscountRule).where(DiscountRule.code == row["code"])):
            continue
        db.add(DiscountRule(**row))
        added += 1
    db.flush()
    return added


def active_rules(db: Session) -> list[DiscountRule]:
    return list(db.scalars(select(DiscountRule).where(DiscountRule.is_active.is_(True)).order_by(DiscountRule.priority)))


# --------------------------------------------------------------------------
# Rule matching
# --------------------------------------------------------------------------
def matching_rules(
    db: Session,
    customer: Customer,
    subtotal: float,
    order_number: int | None = None,
    is_birthday: bool = False,
) -> list[DiscountRule]:
    """Kaun-kaun se rule aaj lagte hain? (jhooth nahi, sirf sach wale)"""
    order_number = order_number if order_number is not None else (customer.total_orders or 0) + 1
    hits: list[DiscountRule] = []
    for rule in active_rules(db):
        cond = rule.condition or {}
        reward = rule.reward or {}
        if rule.trigger == "first_order" and order_number != 1:
            continue
        if rule.trigger == "nth_order" and order_number < int(cond.get("order_number", 999)):
            continue
        if rule.trigger == "bill_amount" and subtotal < float(cond.get("min_bill", 0)):
            continue
        if rule.trigger == "birthday" and not is_birthday:
            continue
        if rule.trigger == "winback":
            days = int(cond.get("days", settings.winback_days))
            if not customer.last_visit_at:
                continue
            from .utils import days_between

            if days_between(customer.last_visit_at, utcnow()) < days:
                continue
        if rule.trigger == "thanks":
            continue  # ye alag se, payment ke baad diya jata hai
        if reward.get("type") == "free_item" and int(cond.get("order_number", 0)) and order_number != int(cond["order_number"]):
            continue
        hits.append(rule)
    return hits


def best_discount(hits: list[DiscountRule]) -> tuple[float, DiscountRule | None]:
    """Sabse bada percent discount (ek hi lagta hai — customer ka fayda)."""
    best_percent, best_rule = 0.0, None
    for rule in hits:
        reward = rule.reward or {}
        if reward.get("type") == "percent":
            value = float(reward.get("value", 0) or 0)
            if value > best_percent:
                best_percent, best_rule = value, rule
    return min(best_percent, settings.max_discount_percent), best_rule


def freebies_from_rules(hits: list[DiscountRule], subtotal: float) -> list[str]:
    """Free item waale rules — item ka naam (ek se zyada na ho)."""
    items: list[str] = []
    for rule in sorted(hits, key=lambda r: r.priority):
        reward = rule.reward or {}
        if reward.get("type") == "free_item":
            item = reward.get("item")
            if item and item not in items:
                items.append(item)
    return items[:1] if subtotal < 999 else items[:2]


def evaluate_for_order(db: Session, customer: Customer, subtotal: float, order_number: int | None = None) -> dict:
    """Order ke waqt poora discount faisla — dashboard me bhi dikhta hai."""
    is_birthday = _is_birthday_today(customer)
    hits = matching_rules(db, customer, subtotal, order_number=order_number, is_birthday=is_birthday)
    percent, rule = best_discount(hits)
    freebies = freebies_from_rules(hits, subtotal)
    return {
        "percent": percent,
        "code": rule.code if rule else None,
        "reason": rule.message if rule else None,
        "rule_name": rule.name if rule else None,
        "freebies": freebies,
        "matched": [r.name for r in hits],
        "is_birthday": is_birthday,
        "order_number": order_number if order_number is not None else (customer.total_orders or 0) + 1,
    }


def _is_birthday_today(customer: Customer) -> bool:
    if not customer.birthday:
        return False
    return customer.birthday == now_ist().strftime("%m-%d")


# --------------------------------------------------------------------------
# Coupon banane / use karne ka kaam
# --------------------------------------------------------------------------
def _rand_code(prefix: str, size: int = 4) -> str:
    # secrets: predictable random nahi (coupon guessing se bachav)
    tail = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(size))
    return f"{prefix}{tail}"


def issue_coupon(
    db: Session,
    percent: float = 0.0,
    source: str = "manual",
    customer_phone: str | None = None,
    code: str | None = None,
    free_item_name: str | None = None,
    valid_days: int = 30,
    min_bill_amount: float = 0.0,
) -> Coupon:
    """Naya coupon banao. Ek hi code do baar nahi banega."""
    percent = min(float(percent or 0), settings.max_discount_percent)
    code = (code or _rand_code("CARE")).upper()
    while db.scalar(select(Coupon).where(Coupon.code == code)):
        code = _rand_code(code[:3] or "CARE")
    coupon = Coupon(
        code=code,
        discount_percent=percent,
        free_item_name=free_item_name,
        customer_phone=customer_phone,
        source=source,
        min_bill_amount=min_bill_amount,
        expiry_date=utcnow() + timedelta(days=valid_days),
    )
    db.add(coupon)
    db.flush()
    return coupon


def standard_coupon_for(db: Session, rule: DiscountRule, customer_phone: str) -> Coupon:
    """Rule waale fixed code (WELCOME10) ko customer ke naam se issue karo."""
    existing = db.scalar(select(Coupon).where(Coupon.code == rule.code, Coupon.customer_phone == customer_phone))
    if existing and not existing.is_used:
        return existing
    if not existing:
        coupon = Coupon(
            code=rule.code,
            discount_percent=float((rule.reward or {}).get("value", 0) or 0),
            free_item_name=(rule.reward or {}).get("item"),
            customer_phone=customer_phone,
            source=rule.trigger,
            expiry_date=utcnow() + timedelta(days=45),
        )
        db.add(coupon)
        db.flush()
        return coupon
    # purana use ho gaya to naya banao (code ke aage number lagao)
    return issue_coupon(
        db,
        percent=float((rule.reward or {}).get("value", 0) or 0),
        free_item_name=(rule.reward or {}).get("item"),
        source=rule.trigger,
        customer_phone=customer_phone,
    )


def thanks_coupon(db: Session, customer: Customer) -> Coupon:
    """Payment ke baad 'agle order me kaam aane wala' code (THANKS5 type)."""
    rule = db.scalar(select(DiscountRule).where(DiscountRule.trigger == "thanks"))
    percent = float(((rule.reward if rule else {}) or {}).get("value", 5) or 5)
    code = _rand_code("THANKS", 6)
    return issue_coupon(db, percent=percent, source="thanks", customer_phone=customer.phone, code=code, valid_days=30)


def mark_used(db: Session, coupon: Coupon, order_id: int | None = None) -> None:
    coupon.is_used = True
    coupon.used_at = utcnow()
    coupon.used_on_order_id = order_id
    rule = db.scalar(select(DiscountRule).where(DiscountRule.code == coupon.code))
    if rule:
        rule.used_count = (rule.used_count or 0) + 1
    db.flush()


def record_rule_use(db: Session, code: str | None) -> None:
    if not code:
        return
    rule = db.scalar(select(DiscountRule).where(DiscountRule.code == code))
    if rule:
        rule.used_count = (rule.used_count or 0) + 1


def loyalty_offer(customer: Customer) -> str | None:
    """Points se free coffee ka message (F13)."""
    if int(customer.loyalty_points or 0) >= settings.free_coffee_points:
        return f"Aapke {customer.loyalty_points} points ho gaye hain — ek *Cold Coffee bilkul FREE*! ☕"
    return None


def winback_message(customer: Customer, coupon: Coupon) -> str:
    name = (customer.name or "ji").split()[0]
    return (
        f"{name} ji, kahan gayab ho gaye? 😄 {settings.restaurant_name} ki kitchen aapko yaad kar rahi hai.\n"
        f"Aapke liye sirf aap ke liye *{int(coupon.discount_percent)}% OFF* — code: *{coupon.code}*\n"
        f"Aaj hi aa jaiye, aap wali table khaali rakhi hai 😉"
    )


def birthday_message(customer: Customer, freebie: str | None) -> str:
    name = (customer.name or "ji").split()[0]
    gift = f" Aur aaj ek *{freebie} bilkul FREE* 🎁" if freebie else ""
    return (
        f"🎂 *Happy Birthday {name} ji!* 🎉\n"
        f"{settings.restaurant_name} ki poori team ki taraf se dher saari shubhkamnayein.{gift}\n"
        f"Aaj zaroor aa jaiye — cake ke saath entry bilkul special hogi 😄"
    )


def lapsed_text(customer: Customer) -> str:
    from .utils import days_between

    days = days_between(customer.last_visit_at, utcnow()) if customer.last_visit_at else 0
    return f"{days} din ho gaye aapko dekhe hue" if days else ""


def discount_summary_text(result: dict, subtotal: float) -> str:
    """Customer ko dikhane wali line, jaise report ke examples me hai."""
    if result["percent"] <= 0 and not result["freebies"]:
        return ""
    parts = []
    if result["percent"]:
        saved = money(subtotal * result["percent"] / 100)
        code = f" (code: {result['code']})" if result["code"] else ""
        parts.append(f"{int(result['percent'])}% OFF{code} — {rupees(saved)} bach gaye 🎉")
    if result["freebies"]:
        parts.append("Aaj ki taraf se free: " + ", ".join(result["freebies"]) + " 🎁")
    return "\n".join(parts)
