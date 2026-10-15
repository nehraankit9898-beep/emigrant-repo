"""Terminal demo — server ke bina hi poora WhatsApp agent chal ke dikhao.

Chalao:
    python -m scripts.demo_chat
    python -m scripts.demo_chat --phone 919812345678 --name "Rahul"
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DATABASE_URL", "sqlite:///./data/demo_chat.db")
os.environ.setdefault("WHATSAPP_MODE", "mock")
os.environ.setdefault("LLM_MODE", "demo")
os.environ.setdefault("PAYMENT_MODE", "mock")
os.environ.setdefault("AUTOMATION_ENABLED", "false")

from app import discounts, memory, menu as menu_engine, orchestrator, payments, seed  # noqa: E402
from app.database import init_db, session_scope  # noqa: E402
from app.models import Order, Payment  # noqa: E402
from sqlalchemy import select  # noqa: E402

GREEN, CYAN, YELLOW, DIM, RESET = "\033[92m", "\033[96m", "\033[93m", "\033[2m", "\033[0m"


def customer_says(text: str) -> None:
    print(f"\n{CYAN}👤 Customer:{RESET} {text}")


def agent_says(text: str) -> None:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        prefix = f"{GREEN}🤖 Bablu:{RESET} " if index == 0 else " " * 12
        print(f"{prefix}{line}" if line else "")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sharma Cafe WhatsApp agent ka terminal demo")
    parser.add_argument("--phone", default="919812345678")
    parser.add_argument("--name", default="Rahul Sharma")
    parser.add_argument("--reset", action="store_true", help="database saaf karke naya demo")
    args = parser.parse_args()

    init_db()
    with session_scope() as db:
        menu_engine.ensure_menu(db)
        discounts.seed_rules(db)
        if args.reset:
            seed.reset_demo(db)

    print(f"\n{DIM}{'=' * 74}\n  Sharma Cafe — WhatsApp AI Agent (Bablu) ka LIVE demo\n{'=' * 74}{RESET}")

    script = [
        "Hi",
        "menu bhejo",
        "2 paneer butter masala, 4 butter naan aur ek cold coffee",
        "aaj shaam 7 baje 4 logo ki table bhi book kar do",
        "1 butter chicken, 3 garlic naan",  # dobara order (memory check)
        "aaj ki sale batado",
        "kuch achha sa batao",
        "mera birthday 15 March hai",
        "insaan se baat karni hai",
    ]

    with session_scope() as db:
        for text in script:
            customer_says(text)
            result = orchestrator.simulate_inbound(db, args.phone, text, profile_name=args.name, channel="demo")
            db.flush()
            for reply in result.replies:
                agent_says(reply.text)
                print(f"{DIM}   (intent: {reply.intent}){RESET}")
            if not result.replies:
                print(f"{YELLOW}   (message staff ko forward ho gaya — agent chup){RESET}")

        # staff ne baat kar li -> agent wapas on (dashboard ka toggle bhi yahi karta hai)
        customer = memory.get_customer(db, args.phone)
        if customer and customer.human_mode:
            customer.human_mode = False
            print(f"{DIM}   (staff ne baat kar li — agent wapas ON){RESET}")

        # payment ka jadoo — pehla order pay kara do
        order = db.scalar(
            select(Order).where(Order.customer_phone == args.phone, Order.payment_status == "pending").order_by(Order.id)
        )
        if order:
            payment = db.scalar(select(Payment).where(Payment.order_id == order.id))
            customer_says("payment kar diya (UPI)")
            payments.mark_paid(db, payment, via="demo")
            replies = orchestrator.on_payment_success(db, order, via="demo")
            for reply in replies:
                agent_says(reply.text)
                print(f"{DIM}   (intent: {reply.intent}){RESET}")

            # khana pahunch gaya -> feedback
            orchestrator.advance_order_status(db, order, "delivered")
            customer_says("5")
            result = orchestrator.simulate_inbound(db, args.phone, "5", channel="demo")
            for reply in result.replies:
                agent_says(reply.text)

        customer = memory.get_customer(db, args.phone)
        print(f"\n{DIM}{'=' * 74}")
        print("  Agent ki yaad-dasht (memory) — jo usne yaad rakha:")
        print(f"{'=' * 74}{RESET}")
        print(f"  Naam:            {customer.name}")
        print(f"  Visits:          {customer.total_visits}")
        print(f"  Total kharcha:   ₹{customer.total_spent:,.0f}")
        print(f"  Loyalty points:  {customer.loyalty_points}")
        print(f"  Pasand:          {', '.join(row['name'] for row in (customer.favourite_items or [])[:3])}")
        print(f"  Pichla order:    {customer.last_order_summary}")
        print(f"  Birthday:        {customer.birthday}")
        print(f"  Notes:           {', '.join(customer.notes or []) or '—'}")

    print(f"\n{DIM}Dashboard dekhna hai? -> uvicorn app.main:app --host 0.0.0.0 --port 8000{RESET}\n")


if __name__ == "__main__":
    main()
