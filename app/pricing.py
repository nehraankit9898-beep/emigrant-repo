"""Bill Engine — order se pura bill (item, discount, freebie, GST, total).

**Zaroori baat (report Section 16):** AI price nahi banata. Yahi file bill
banati hai — item ka price menu se, GST config se, discount rule se.
Isliye galti ka chance zero.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from .config import settings
from .models import Coupon, MenuItem
from .utils import money, rupees


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
    apply_gst: bool = True,
    cap_discount: bool = True,
) -> Bill:
    """Lines -> pura bill. Discount cap se zyada kabhi nahi (safety)."""
    bill = Bill()
    for raw in lines:
        if isinstance(raw, BillLine):
            bill.lines.append(raw)
            continue
        qty = int(raw.get("qty", 1) or 1)
        unit = money(raw.get("unit_price", raw.get("price", 0)))
        line_total = money(unit * qty)
        bill.lines.append(
            BillLine(
                name=str(raw.get("name", "Item")),
                qty=qty,
                unit_price=unit,
                line_total=line_total,
                is_freebie=bool(raw.get("is_freebie", False)),
            )
        )

    bill.subtotal = money(sum(line.line_total for line in bill.lines if not line.is_freebie))
    bill.packaging = money(settings.packaging_charge if packaging is None else packaging)
    bill.delivery = money(settings.delivery_charge if delivery is None else delivery)

    percent = float(discount_percent or 0)
    if cap_discount:
        percent = min(percent, settings.max_discount_percent)
    percent = max(0.0, percent)
    bill.discount_percent = percent
    bill.discount_amount = money(bill.subtotal * percent / 100)
    bill.discount_code = discount_code
    bill.discount_reason = discount_reason
    bill.freebies = list(freebies or [])

    bill.taxable = money(bill.subtotal - bill.discount_amount + bill.packaging + bill.delivery)
    bill.gst_percent = float(settings.gst_percent or 0) if apply_gst else 0.0
    bill.gst_amount = money(bill.taxable * bill.gst_percent / 100)
    bill.total = money(bill.taxable + bill.gst_amount)
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


def bill_for_menu_item_names(db: Session, names: list[str]) -> Bill:
    """Chhote helper — naam ki list se bill (reports/testing ke liye)."""
    from .menu import find_item

    lines: list[dict] = []
    for name in names:
        item: MenuItem | None = find_item(db, name)
        if item:
            lines.append({"name": item.name, "qty": 1, "unit_price": item.price})
    return build_bill(db, lines)
