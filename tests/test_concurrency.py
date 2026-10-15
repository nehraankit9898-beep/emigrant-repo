"""Concurrency tests — IMPLEMENTATION_PLAN.md ka P0-2.

Ye chaar claim race-safety ke hain; isse pehle sirf code-review ke bharose the:

1. Do parallel orders ko kabhi ek hi `order_no` nahi milna chahiye
   (pehle order_no row-count se banta tha — do orders ek hi number le lete the).
2. Ek coupon do jagah ek saath redeem ho to sirf EK jeetna chahiye.
3. Meta/Razorpay ki duplicate webhook delivery sirf ek baar process honi chahiye.
4. Ek payment do baar settle nahi hona chahiye (duplicate webhook / double click).

Postgres par chalane ke liye (asli evidence — SQLite writes serialise karta hai):
    TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/agent_test pytest tests/test_concurrency.py
"""

from __future__ import annotations

import threading

from app import discounts, memory, orchestrator, payments, pricing
from app.database import SessionLocal
from app.models import Coupon, Payment
from app.security import claim_event

WORKERS = 12
BARRIER_TIMEOUT = 30  # seconds — worker atak jaye to test hang na ho


def _run_in_threads(fn, count=WORKERS):
    """`fn(index)` ko kai threads me ek saath chalao (barrier se contention badhao)."""
    barrier = threading.Barrier(count, timeout=BARRIER_TIMEOUT)
    results: list = [None] * count
    errors: list[BaseException] = []

    def worker(index: int) -> None:
        try:
            barrier.wait()
            results[index] = fn(index)
        except BaseException as exc:  # noqa: BLE001 - thread me exception gumna nahi chahiye
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=BARRIER_TIMEOUT)
    assert not errors, f"threads me error: {errors[:3]}"
    assert not any(t.is_alive() for t in threads), "worker threads atak gaye"
    return results


def _new_session():
    """Har thread ko apni session (asli request ki tarah)."""
    return SessionLocal()


# --------------------------------------------------------------------------
# 1. Order numbers
# --------------------------------------------------------------------------
def test_parallel_orders_get_unique_order_numbers(db):
    def place(index: int):
        session = _new_session()
        try:
            customer, _ = memory.get_or_create_customer(session, f"9198800{index:05d}", f"Racer{index}")
            order, _bill = orchestrator.create_order(
                session, customer, [{"name": "Masala Dosa", "qty": 2, "unit_price": 140}]
            )
            session.commit()
            return order.order_no
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    numbers = _run_in_threads(place, count=WORKERS)
    assert len(numbers) == WORKERS
    assert len(set(numbers)) == WORKERS, f"duplicate order_no mile: {numbers}"


def test_order_numbers_stay_unique_against_existing_rows(db):
    """Sequence se bane number purane rows se takra nahi sakte."""
    customer, _ = memory.get_or_create_customer(db, "919880099999", "Base")
    first, _ = orchestrator.create_order(db, customer, [{"name": "Masala Dosa", "qty": 1, "unit_price": 140}])
    db.commit()

    numbers = [first.order_no]
    for index in range(WORKERS):
        session = _new_session()
        try:
            cust, _ = memory.get_or_create_customer(session, f"9198801{index:05d}", f"Racer{index}")
            order, _ = orchestrator.create_order(session, cust, [{"name": "Masala Dosa", "qty": 1, "unit_price": 140}])
            session.commit()
            numbers.append(order.order_no)
        finally:
            session.close()

    assert len(set(numbers)) == len(numbers), f"duplicate: {numbers}"


# --------------------------------------------------------------------------
# 2. Coupon single-use
# --------------------------------------------------------------------------
def test_coupon_redeemed_only_once_under_contention(db):
    customer, _ = memory.get_or_create_customer(db, "919880200001", "CouponRacer")
    coupon = discounts.issue_coupon(db, percent=10, customer_phone=customer.phone)
    db.commit()
    coupon_id = coupon.id

    def redeem(_index: int):
        session = _new_session()
        try:
            row = session.get(Coupon, coupon_id)
            won = pricing.redeem_coupon(session, row)
            session.commit()
            return won
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    results = _run_in_threads(redeem)
    assert results.count(True) == 1, f"coupon {results.count(True)} baar redeem ho gaya"


def test_coupon_attached_to_only_one_order(db):
    """Do orders ek saath ek hi coupon use karein to sirf ek ko discount milega."""
    customer, _ = memory.get_or_create_customer(db, "919880300001", "DoubleSpend")
    coupon = discounts.issue_coupon(db, percent=10, customer_phone=customer.phone)
    db.commit()
    coupon_id = coupon.id

    def spend(index: int):
        session = _new_session()
        try:
            cust, _ = memory.get_or_create_customer(session, "919880300001", "DoubleSpend")
            row = session.get(Coupon, coupon_id)
            won = pricing.redeem_coupon(session, row)
            session.commit()
            return won
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    results = _run_in_threads(spend)
    assert results.count(True) == 1
    db.refresh(coupon)
    assert coupon.is_used is True


# --------------------------------------------------------------------------
# 3. Webhook idempotency
# --------------------------------------------------------------------------
def test_duplicate_webhook_event_claimed_once(db):
    event_key = "wamid.CONCURRENT_TEST_001"

    def claim(_index: int):
        session = _new_session()
        try:
            first = claim_event(session, "whatsapp", event_key)
            session.commit()
            return first
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    results = _run_in_threads(claim)
    assert results.count(True) == 1, f"event {results.count(True)} baar process hua (duplicate delivery)"


def test_duplicate_razorpay_event_claimed_once(db):
    event_key = "payment_link.paid:pay_CONCURRENT_001"

    def claim(_index: int):
        session = _new_session()
        try:
            first = claim_event(session, "razorpay", event_key)
            session.commit()
            return first
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    results = _run_in_threads(claim)
    assert results.count(True) == 1


# --------------------------------------------------------------------------
# 4. Payment settle
# --------------------------------------------------------------------------
def test_payment_settled_only_once_under_contention(db):
    customer, _ = memory.get_or_create_customer(db, "919880400001", "PayRacer")
    order, _bill = orchestrator.create_order(
        db, customer, [{"name": "Masala Dosa", "qty": 2, "unit_price": 140}]
    )
    payment = payments.create_payment(db, order)
    db.commit()
    payment_id = payment.id

    def settle(_index: int):
        session = _new_session()
        try:
            row = session.get(Payment, payment_id)
            won = payments.settle_payment(session, row, ref="pay_CONCURRENT", via="test")
            session.commit()
            return won
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    results = _run_in_threads(settle)
    assert results.count(True) == 1, f"payment {results.count(True)} baar settle ho gaya"

    db.expire_all()
    row = db.get(Payment, payment_id)
    assert row.status == "paid"
    assert row.paid_at is not None


def test_settle_does_not_regress_kitchen_status(db):
    """Duplicate/late payment call kitchen ka aage wala status peeche nahi karega."""
    customer, _ = memory.get_or_create_customer(db, "919880500001", "KitchenRacer")
    order, _bill = orchestrator.create_order(
        db, customer, [{"name": "Masala Dosa", "qty": 2, "unit_price": 140}]
    )
    payment = payments.create_payment(db, order)
    db.commit()

    orchestrator.advance_order_status(db, order, "confirmed")
    payment = db.get(Payment, payment.id)
    payments.settle_payment(db, payment, via="test")
    orchestrator.on_payment_success(db, order, via="test", deliver_replies=False)
    db.commit()

    # settle_payment awaiting_payment -> confirmed karta hai
    orchestrator.advance_order_status(db, order, "preparing", deliver_reply=False)
    db.commit()

    # der se aaya duplicate webhook: preparing ko wapas confirmed nahi karna chahiye
    duplicate = db.get(Payment, payment.id)
    assert payments.settle_payment(db, duplicate, via="test") is False
    orchestrator.on_payment_success(db, order, via="test", deliver_replies=False)
    db.commit()
    assert order.order_status == "preparing"
