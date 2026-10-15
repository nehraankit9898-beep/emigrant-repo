"""Bill Engine — order se pura bill (item, discount, freebie, GST, total).

**Zaroori baat (report Section 16):** AI price nahi banata. Yahi file bill
banati hai — item ka price menu se, GST config se, discount rule se.
Isliye galti ka chance zero.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import re
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .config import settings
from .models import Coupon, MenuItem
from .utils import q2, rupees, to_decimal, utcnow


@dataclass
class BillLine:
    name: str
    qty: int
    unit_price: float
    line_total: float
    is_freebie: bool = False


@dataclass
class Bill:
    lines: list[BillLine] = field(default_factory=list)
    subtotal: float = 0.0
    discount_amount: float = 0.0
    discount_percent: float = 0.0
    discount_code: str | None = None
    discount_reason: str | None = None
    freebies: list[str] = field(default_factory=list)
    packaging: float = 0.0
    delivery: float = 0.0
    taxable: float = 0.0
    gst_amount: float = 0.0
    gst_percent: float = 0.0
    total: float = 0.0

    # ---------------- text ----------------
    def text(self, restaurant: str | None = None, include_header: bool = True) -> str:
        name = restaurant or settings.restaurant_name
        out: list[str] = []
        if include_header:
            out.append(f"*{name} — Bill* 🧾")
            out.append("")
        for line in self.lines:
            if line.is_freebie:
                out.append(f"🎁 {line.name} x{line.qty} — *FREE*")
            else:
                out.append(f"• {line.name} x{line.qty} — {rupees(line.line_total)}")
        out.append("")
        out.append(f"Subtotal: {rupees(self.subtotal)}")
        if self.discount_amount > 0:
            label = f" ({self.discount_code})" if self.discount_code else ""
            percent = f" {int(self.discount_percent)}% off" if self.discount_percent else ""
            out.append(f"Discount{percent}{label}: -{rupees(self.discount_amount)} 🙌")
            if self.discount_reason:
                out.append(f"  _{self.discount_reason}_")
        if self.packaging:
            out.append(f"Packaging: {rupees(self.packaging)}")
        if self.delivery:
            out.append(f"Delivery: {rupees(self.delivery)}")
        if self.gst_amount:
            out.append(f"GST ({_fmt_percent(self.gst_percent)}): {rupees(self.gst_amount)}")
        out.append(f"*Total: {rupees(self.total)}*")
        if self.freebies:
            out.append("")
            out.append("🎁 Aaj ki taraf se: " + ", ".join(self.freebies))
        return "\n".join(out)

    def to_dict(self) -> dict:
        return {
            "lines": [line.__dict__ for line in self.lines],
            "subtotal": self.subtotal,
            "discount_amount": self.discount_amount,
            "discount_percent": self.discount_percent,
            "discount_code": self.discount_code,
            "discount_reason": self.discount_reason,
            "freebies": self.freebies,
            "packaging": self.packaging,
            "delivery": self.delivery,
            "taxable": self.taxable,
            "gst_percent": self.gst_percent,
            "gst_amount": self.gst_amount,
            "total": self.total,
        }


def _fmt_percent(value: float) -> str:
    return f"{int(value)}%" if abs(value - int(value)) < 0.01 else f"{value:.1f}%"


def build_bill(
    db: Session,
    lines: list[dict] | list[BillLine],
    discount_percent: float = 0.0,
    discount_code: str | None = None,
    discount_reason: str | None = None,
    freebies: list[str] | None = None,
    packaging: float | None = None,
    delivery: float | None = None,
    gst_percent: float | None = None,
    apply_gst: bool = True,
    cap_discount: bool = True,
) -> Bill:
    """Lines -> pura bill. Saara arithmetic Decimal me (paise tak round, HALF_UP). Discount cap se zyada kabhi nahi.

    Freebie lines subtotal me nahi jodte. GST sirf `taxable` (subtotal - discount + packaging + delivery) par.
    """
    bill = Bill()
    for raw in lines:
        if isinstance(raw, BillLine):
            bill.lines.append(raw)
            continue
        raw_qty = raw.get("qty", 1)
        try:
            qty_number = float(1 if raw_qty in (None, "") else raw_qty)
        except (TypeError, ValueError) as exc:
            raise ValueError("quantity number hona chahiye") from exc
        if qty_number != int(qty_number):
            raise ValueError("quantity poori ginti honi chahiye")
        qty = int(qty_number)
        if qty < 1 or qty > 100:
            raise ValueError("quantity 1 se 100 ke beech honi chahiye")
        unit = q2(raw.get("unit_price", raw.get("price", 0)))
        if unit < 0:
            raise ValueError("price negative nahi ho sakta")
        line_total = q2(unit * qty)
        bill.lines.append(
            BillLine(
                name=str(raw.get("name", "Item")),
                qty=qty,
                unit_price=float(unit),
                line_total=float(line_total),
                is_freebie=bool(raw.get("is_freebie", False)),
            )
        )

    subtotal = sum((q2(line.line_total) for line in bill.lines if not line.is_freebie), Decimal("0"))
    packaging_d = q2(settings.packaging_charge if packaging is None else packaging)
    delivery_d = q2(settings.delivery_charge if delivery is None else delivery)

    percent = to_decimal(discount_percent or 0)
    if cap_discount:
        percent = min(percent, to_decimal(settings.max_discount_percent))
    percent = max(Decimal("0"), percent)
    discount = q2(subtotal * percent / Decimal("100"))
    discount = min(discount, subtotal)  # discount kabhi subtotal se zyada nahi (negative total impossible)

    taxable = q2(subtotal - discount + packaging_d + delivery_d)
    # gst_percent diya gaya ho to wahi lagao (purane order ka bill dobara banate waqt),
    # warna aaj ki config. Isse total hamesha gst_amount ke saath consistent rahta hai.
    gst_percent_d = to_decimal(settings.gst_percent if gst_percent is None else gst_percent)
    gst_percent = gst_percent_d if apply_gst else Decimal("0")
    gst = q2(taxable * gst_percent / Decimal("100"))
    total = q2(taxable + gst)

    bill.subtotal = float(subtotal)
    bill.packaging = float(packaging_d)
    bill.delivery = float(delivery_d)
    bill.discount_percent = float(percent)
    bill.discount_amount = float(discount)
    bill.discount_code = discount_code
    bill.discount_reason = discount_reason
    bill.freebies = list(freebies or [])
    bill.taxable = float(taxable)
    bill.gst_percent = float(gst_percent)
    bill.gst_amount = float(gst)
    bill.total = float(total)
    return bill


def validate_coupon(db: Session, code: str, customer_phone: str, subtotal: float) -> tuple[Coupon | None, str]:
    """Coupon asli hai? kisike naam ka? pehle use to nahi hua? (Report Section 5)"""
    code = (code or "").strip().upper()
    if not code:
        return None, ""
    coupon = db.query(Coupon).filter(Coupon.code == code).one_or_none()
    if not coupon:
        return None, "Ye code hamare system me nahi mila 🤔"
    if coupon.is_used:
        return None, "Ye code pehle use ho chuka hai — ek code sirf ek baar chalta hai 😅"
    if coupon.expiry_date and coupon.expiry_date < _now():
        return None, "Ye code ki date nikal gayi hai 🙂"
    if coupon.customer_phone and coupon.customer_phone != customer_phone:
        return None, "Ye code kisi aur customer ke liye bana tha 🙃"
    if coupon.min_bill_amount and subtotal < coupon.min_bill_amount:
        return None, f"Ye code {rupees(coupon.min_bill_amount)} se upar ke bill par chalega"
    return coupon, ""


def _now():
    from .utils import utcnow

    return utcnow()


def coupon_lines(coupon: Coupon, db: Session) -> tuple[float, str | None, list[str]]:
    """Coupon -> (percent, free item, reason)."""
    percent = float(coupon.discount_percent or 0)
    if percent > settings.max_discount_percent:
        percent = settings.max_discount_percent
    free_item = coupon.free_item_name
    return percent, free_item, f"Coupon {coupon.code} ({coupon.source or 'offer'})"


def bill_from_order(db: Session, order) -> Bill:
    """Purane order ka **wahi** bill dobara banao (items + discount + GST + total).

    Zaroori kyun hai: pehle ye jagah sirf `order.items` se `build_bill()` call karti thi,
    jisme discount/gst ke rates nahi milte the — to GST bina discount ke lagta tha aur
    customer ko asli total se zyada dikhta tha (payment ke baad bhi "Total: ₹798" jab
    asli bill ₹718.20 ka tha).

    Rates order par save hote hain (`discount_percent`, `gst_percent`), isliye config
    badalne ke baad bhi purana bill wahi amount dikhata hai.
    """
    lines = [
        {
            "name": row.get("name"),
            "qty": row.get("qty", 1),
            "unit_price": row.get("price", 0),
            "is_freebie": row.get("free", False),
        }
        for row in (order.items or [])
        if isinstance(row, dict)
    ]
    # Rate order par save hai. Purane orders (columns aane se pehle ke) me 0 hoga —
    # tab amount se rate nikal lete hain, warna discount hat kar total badh jaata.
    percent = float(getattr(order, "discount_percent", 0) or 0)
    if not percent and float(order.discount_amount or 0) > 0 and float(order.subtotal or 0) > 0:
        percent = round(float(order.discount_amount) / float(order.subtotal) * 100, 4)

    gst_percent = getattr(order, "gst_percent", None)
    gst_percent = float(gst_percent) if gst_percent else None
    if not gst_percent and float(order.gst_amount or 0) > 0 and float(order.taxable or 0) > 0:
        gst_percent = round(float(order.gst_amount) / float(order.taxable) * 100, 4)

    bill = build_bill(
        db,
        lines,
        discount_percent=percent,
        discount_code=order.discount_code,
        discount_reason=order.discount_reason,
        freebies=list(order.freebies or []),
        packaging=float(order.packaging or 0),
        delivery=float(order.delivery or 0),
        # Jo rate us waqt lagaya gaya tha wahi reproduce karna hai:
        # config aaj kuch bhi ho, purane order ka total nahi badalna chahiye.
        gst_percent=gst_percent if gst_percent is not None else settings.gst_percent,
        cap_discount=False,
    )
    return bill


def bill_for_menu_item_names(db: Session, names: list[str]) -> Bill:
    """Chhote helper — naam ki list se bill (reports/testing ke liye)."""
    from .menu import find_item

    lines: list[dict] = []
    for name in names:
        item: MenuItem | None = find_item(db, name)
        if item:
            lines.append({"name": item.name, "qty": 1, "unit_price": item.price})
    return build_bill(db, lines)


# --------------------------------------------------------------------------
# Coupon redemption (single-use, race-safe)
# --------------------------------------------------------------------------
_CODE_TOKEN = re.compile(r"\b[A-Za-z][A-Za-z0-9]{3,29}\b")


def find_coupon_in_text(db: Session, text: str, customer_phone: str, subtotal: float) -> tuple[Coupon | None, str]:
    """Customer ke message me coupon code dhundo aur validate karo. (coupon, error_message)."""
    tokens = {token.upper() for token in _CODE_TOKEN.findall(text or "")}
    if not tokens:
        return None, ""
    candidates = db.scalars(select(Coupon).where(Coupon.code.in_(tokens)))
    last_error = ""
    for candidate in candidates:
        coupon, error = validate_coupon(db, candidate.code, customer_phone, subtotal)
        if coupon:
            return coupon, ""
        last_error = error
    return None, last_error


def redeem_coupon(db: Session, coupon: Coupon) -> bool:
    """Coupon ko 'used' mark karo — sirf tab jab abhi tak unused ho (atomic). True = is call ne claim kiya."""
    result = db.execute(
        update(Coupon)
        .where(Coupon.id == coupon.id, Coupon.is_used.is_(False))
        .values(is_used=True, used_at=utcnow())
    )
    if result.rowcount == 1:
        db.refresh(coupon)
        return True
    return False


def attach_coupon_to_order(db: Session, coupon: Coupon, order_id: int) -> None:
    db.execute(update(Coupon).where(Coupon.id == coupon.id).values(used_on_order_id=order_id))


def release_coupons_for_order(db: Session, order_id: int) -> int:
    """Order cancel hone par coupon wapas usable (ek hi baar — cancelled order ka coupon reuse ho sakta hai)."""
    result = db.execute(
        update(Coupon)
        .where(Coupon.used_on_order_id == order_id)
        .values(is_used=False, used_at=None, used_on_order_id=None)
    )
    return int(result.rowcount or 0)
