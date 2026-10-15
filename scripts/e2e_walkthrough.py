"""End-to-end chat walkthrough against the live server (read-only-ish).

Usage: python scripts/e2e_walkthrough.py [base_url]
"""

from __future__ import annotations

import random
import sys

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
PHONE = sys.argv[2] if len(sys.argv) > 2 else f"919555{random.randint(100000, 999999)}"

STEPS = [
    "hello",
    "menu bhejo",
    "2 paneer butter masala, 4 butter naan aur ek cold coffee",
    "bill",
    "pay",
    "order status",
    "table book karna hai kal 8 baje 4 log",
    "5 star",
    "mera birthday 15 march hai",
    "loyalty points kitne hai",
    "insaan se baat karni hai",
    "thanks",
]


def simulate(c: httpx.Client, phone: str, text: str, name: str = "Walkthrough") -> dict:
    r = c.post(f"{BASE}/api/simulate", json={"phone": phone, "text": text, "name": name}, timeout=60.0)
    if r.status_code >= 500:
        print(f"  !! HTTP {r.status_code}: {r.text[:600]}")
        return {}
    return r.json()


def main() -> int:
    fails = 0
    with httpx.Client(timeout=60.0) as c:
        for text in STEPS:
            print(f"\n{'='*72}\n>>> {text}")
            data = simulate(c, PHONE, text)
            if not data:
                fails += 1
                continue
            print(f"    intent = {data.get('intent')}")
            for rep in data.get("replies", []):
                body = rep.get("text", "")
                print("    ---")
                for line in body.split("\n"):
                    print(f"    | {line}")
            if not data.get("replies"):
                print("    (no reply)")
    print(f"\n\n{'='*72}\nWalkthrough finished. {fails} server errors.")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
