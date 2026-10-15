"""Database tables — report ke Section 10 wala data design (aur thoda extra).

Ek nazar me:
  customers   -> har customer ki "file" (memory) — phone hi pehchan hai
  menu_items  -> menu + price (AI price kabhi nahi banata, yahi se aata hai)
  orders      -> order + bill + payment status
  order_items -> kis order me kya-kya tha (analytics ke liye)
  coupons     -> discount code, ek code ek hi baar chalega
  reservations-> table booking
  feedback    -> rating + comment
  messages    -> poora chat itihaas (in/out dono)
  alerts      -> owner/staff ko bhejne wale alert
  campaigns   -> birthday / winback / broadcast ka record
  payments    -> payment link + status (webhook idempotency ke liye)
  discount_rules -> Section 5 wali discount table (dashboard se editable)
  app_settings   -> runtime settings (system prompt, toggles, profile edit)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    """Naive UTC — sab jagah yahi use hota hai (display par IST me convert)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    phone: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(120))
    birthday: Mapped[Optional[str]] = mapped_column(String(5))  # "MM-DD"
    veg_pref: Mapped[str] = mapped_column(String(10), default="any")  # veg | nonveg | any

    total_visits: Mapped[int] = mapped_column(Integer, default=0)
    total_orders: Mapped[int] = mapped_column(Integer, default=0)
    total_spent: Mapped[float] = mapped_column(Float, default=0.0)
    loyalty_points: Mapped[int] = mapped_column(Integer, default=0)
    last_order_summary: Mapped[Optional[str]] = mapped_column(String(400))
    last_order_items: Mapped[Optional[list]] = mapped_column(JSON)
    favourite_items: Mapped[Optional[list]] = mapped_column(JSON)
    notes: Mapped[Optional[list]] = mapped_column(JSON)  # ["kam mirchi", "no onion"]
    tags: Mapped[Optional[list]] = mapped_column(JSON)  # ["regular", "big_spender"]

    language: Mapped[str] = mapped_column(String(12), default="hinglish")
    opt_in: Mapped[bool] = mapped_column(Boolean, default=False)
    opted_out: Mapped[bool] = mapped_column(Boolean, default=False)
    human_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    flow_state: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)

    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_visit_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class MenuItem(Base):
    __tablename__ = "menu_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    aliases: Mapped[Optional[list]] = mapped_column(JSON)  # ["pbm", "paneer masala"]
    price: Mapped[float] = mapped_column(Float, default=0.0)
    category: Mapped[str] = mapped_column(String(60), default="Other", index=True)
    is_veg: Mapped[bool] = mapped_column(Boolean, default=True)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)
    is_signature: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[Optional[str]] = mapped_column(String(400))
    image_url: Mapped[Optional[str]] = mapped_column(String(400))
    sold_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_no: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    customer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("customers.id"))
    customer_phone: Mapped[str] = mapped_column(String(20), index=True)
    customer_name: Mapped[Optional[str]] = mapped_column(String(120))
    table_number: Mapped[Optional[str]] = mapped_column(String(10))

    items: Mapped[list] = mapped_column(JSON, default=list)  # [{name, qty, price, line_total, free}]
    subtotal: Mapped[float] = mapped_column(Float, default=0.0)
    discount_amount: Mapped[float] = mapped_column(Float, default=0.0)
    discount_code: Mapped[Optional[str]] = mapped_column(String(30))
    discount_reason: Mapped[Optional[str]] = mapped_column(String(200))
    freebies: Mapped[Optional[list]] = mapped_column(JSON)  # ["Gulab Jamun (2 pc)"]
    packaging: Mapped[float] = mapped_column(Float, default=0.0)
    delivery: Mapped[float] = mapped_column(Float, default=0.0)
    taxable: Mapped[float] = mapped_column(Float, default=0.0)
    gst_amount: Mapped[float] = mapped_column(Float, default=0.0)
    total_amount: Mapped[float] = mapped_column(Float, default=0.0)

    payment_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|paid|failed|cod
    payment_link: Mapped[Optional[str]] = mapped_column(String(500))
    payment_ref: Mapped[Optional[str]] = mapped_column(String(120))
    order_status: Mapped[str] = mapped_column(String(30), default="placed")
    channel: Mapped[str] = mapped_column(String(20), default="whatsapp")  # whatsapp|dashboard|qr
    notes: Mapped[Optional[str]] = mapped_column(String(400))
    feedback_asked: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    customer: Mapped[Optional[Customer]] = relationship()
    order_items: Mapped[list["OrderItem"]] = relationship(back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    menu_item_id: Mapped[Optional[int]] = mapped_column(ForeignKey("menu_items.id"))
    name: Mapped[str] = mapped_column(String(120))
    qty: Mapped[int] = mapped_column(Integer, default=1)
    unit_price: Mapped[float] = mapped_column(Float, default=0.0)
    line_total: Mapped[float] = mapped_column(Float, default=0.0)
    is_freebie: Mapped[bool] = mapped_column(Boolean, default=False)

    order: Mapped[Order] = relationship(back_populates="order_items")


class Coupon(Base):
    __tablename__ = "coupons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    discount_percent: Mapped[float] = mapped_column(Float, default=0.0)
    free_item_name: Mapped[Optional[str]] = mapped_column(String(120))
    customer_phone: Mapped[Optional[str]] = mapped_column(String(20), index=True)
    source: Mapped[Optional[str]] = mapped_column(String(40))  # welcome|winback|thanks|birthday|loyalty|manual
    min_bill_amount: Mapped[float] = mapped_column(Float, default=0.0)
    is_used: Mapped[bool] = mapped_column(Boolean, default=False)
    used_on_order_id: Mapped[Optional[int]] = mapped_column(ForeignKey("orders.id"))
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    expiry_date: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Reservation(Base):
    __tablename__ = "reservations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_phone: Mapped[str] = mapped_column(String(20), index=True)
    customer_name: Mapped[Optional[str]] = mapped_column(String(120))
    date: Mapped[datetime] = mapped_column(Date, index=True)
    time: Mapped[str] = mapped_column(String(12))  # "19:00"
    persons: Mapped[int] = mapped_column(Integer, default=2)
    status: Mapped[str] = mapped_column(String(20), default="confirmed")  # confirmed|cancelled|done|no_show
    notes: Mapped[Optional[str]] = mapped_column(String(300))
    reminder_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_phone: Mapped[str] = mapped_column(String(20), index=True)
    customer_name: Mapped[Optional[str]] = mapped_column(String(120))
    order_id: Mapped[Optional[int]] = mapped_column(ForeignKey("orders.id"))
    rating: Mapped[int] = mapped_column(Integer, default=0)
    comment: Mapped[Optional[str]] = mapped_column(Text)
    review_link_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_phone: Mapped[str] = mapped_column(String(20), index=True)
    direction: Mapped[str] = mapped_column(String(8))  # in | out
    text: Mapped[str] = mapped_column(Text, default="")
    message_type: Mapped[str] = mapped_column(String(20), default="text")  # text|button|image|audio|template|system
    intent: Mapped[Optional[str]] = mapped_column(String(40))
    channel: Mapped[str] = mapped_column(String(20), default="whatsapp")
    meta: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(30), index=True)  # complaint|new_order|payment|handover|party|system
    message: Mapped[str] = mapped_column(Text)
    customer_phone: Mapped[Optional[str]] = mapped_column(String(20))
    order_id: Mapped[Optional[int]] = mapped_column(ForeignKey("orders.id"))
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(30))  # birthday|winback|broadcast|report|special
    message: Mapped[str] = mapped_column(Text, default="")
    audience_count: Mapped[int] = mapped_column(Integer, default=0)
    sent_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|sent|partial|blocked
    details: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    provider: Mapped[str] = mapped_column(String(20), default="mock")  # mock|razorpay
    provider_ref: Mapped[Optional[str]] = mapped_column(String(120), index=True)
    link: Mapped[Optional[str]] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="created")  # created|paid|failed|expired
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class DiscountRule(Base):
    __tablename__ = "discount_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[Optional[str]] = mapped_column(String(30))  # WELCOME10 etc.
    name: Mapped[str] = mapped_column(String(120))
    trigger: Mapped[str] = mapped_column(String(40))  # first_order|nth_order|loyalty|bill_amount|birthday|winback|thanks|manual
    condition: Mapped[dict] = mapped_column(JSON, default=dict)  # {"nth": 3} {"min_bill": 999}
    reward: Mapped[dict] = mapped_column(JSON, default=dict)  # {"type": "percent", "value": 15}
    message: Mapped[Optional[str]] = mapped_column(String(300))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[Optional[dict]] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
