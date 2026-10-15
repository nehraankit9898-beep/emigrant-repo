"""Reproduce suspected bugs against the live server.

Usage: python scripts/bug_hunt.py [base_url]
"""

from __future__ import annotations

import random
import re
import sys

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"

MONEY = re.compile(r"Total: ₹([\d.]+)")


def new_phone() -> str:
    return f"9197{random.randint(10000000, 99999999)}"


def say(c, phone, text):
    r = c.post(f"{BASE}/api/simulate", json={"phone": phone, "text": text}, timeout=60.0)
    r.raise_for_status()
    return r.json()


def joined(data) -> str:
    return "\n".join(r["text"] for r in data.get("replies", []))


def check(name, ok, detail=""):
    mark = "PASS" if ok else "*** FAIL ***"
    print(f"[{mark}] {name}" + (f"\n        {detail}" if detail else ""))
    return 0 if ok else 1


def main() -> int:
    fails = 0
    with httpx.Client(timeout=60.0) as c:
        # --------------------------------------------------------------
        # BUG 1: pending order is not tracked -> "pay" cannot find it
        # --------------------------------------------------------------
        phone = new_phone()
        say(c, phone, "2 paneer butter masala, 4 butter naan")
        pay = say(c, phone, "pay")
        body = joined(pay)
        fails += check(
            "BUG-1  'pay' finds the pending order and re-sends the payment link",
            "http" in body.lower(),
            f"intent={pay.get('intent')} reply={body[:160]!r}",
        )

        # --------------------------------------------------------------
        # BUG 2: 'bill' rebuilds the bill WITHOUT the discount -> wrong total
        # (unpaid order par bill payment-link wale format me aata hai, isliye
        #  dono form check karte hain: "Total: ₹X" aur "bill *₹X*")
        # --------------------------------------------------------------
        phone = new_phone()
        order = joined(say(c, phone, "2 paneer butter masala, 4 butter naan"))  # 1st order -> WELCOME10 10%
        o_total = MONEY.search(order)
        o_val = float(o_total.group(1)) if o_total else None

        bill = joined(say(c, phone, "bill"))
        quoted = {float(m) for m in re.findall(r"₹([\d.]+)", bill)}
        fails += check(
            "BUG-2  'bill' shows the SAME total as the order bill (unpaid)",
            o_val is not None and o_val in quoted,
            f"order_total={o_val} amounts_shown={sorted(quoted)}",
        )

        # payment ke baad bhi wahi total (fix se pehle yahan discount hat jaata tha)
        link = re.search(r"/pay/(\S+)", bill)
        if link:
            c.post(f"{BASE}/pay/{link.group(1)}/confirm", follow_redirects=False)
            paid_bill = joined(say(c, phone, "bill"))
            m = MONEY.search(paid_bill)
            p_val = float(m.group(1)) if m else None
            fails += check(
                "BUG-2b 'bill' after payment still matches the original total",
                p_val is not None and o_val is not None and abs(p_val - o_val) < 0.01,
                f"order_total={o_val} bill_after_payment={p_val}",
            )

        # --------------------------------------------------------------
        # BUG 3: 'resend-link' quote must match the order total
        # --------------------------------------------------------------
        orders = c.get(f"{BASE}/api/orders?limit=5").json()
        target = next((o for o in orders if o["payment_status"] == "pending"), None)
        if target:
            r = c.post(f"{BASE}/api/orders/{target['order_no']}/resend-link")
            msg = r.json().get("message", "")
            m = MONEY.search(msg)
            q_val = float(m.group(1)) if m else None
            fails += check(
                "BUG-3  resend-link quote == order.total_amount",
                q_val is not None and abs(q_val - float(target["total"])) < 0.01,
                f"order_total={target['total']} quoted={q_val}",
            )
        else:
            print("[skip] BUG-3 no pending order found")

        # --------------------------------------------------------------
        # BUG 4: coupon typed in chat should apply
        # --------------------------------------------------------------
        phone = new_phone()
        r = c.post(f"{BASE}/api/coupons", json={"percent": 15, "customer_phone": phone})
        coupon_code = r.json().get("code") if r.status_code == 200 else None
        if coupon_code:
            body = joined(say(c, phone, f"2 masala dosa code {coupon_code}"))
            fails += check(
                "BUG-4  typed coupon code is applied to the order",
                coupon_code in body,
                f"coupon={coupon_code} reply={body[:200]!r}",
            )
        else:
            print(f"[skip] BUG-4 coupon creation failed: {r.status_code} {r.text[:200]}")

    print(f"\n{fails} failing check(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
