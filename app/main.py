"""FastAPI app — webhooks, payment pages, dashboard, aur API.

Chalane ka tarika:
    uvicorn app.main:app --host 0.0.0.0 --port 8000
    (ya)  python -m app.main
"""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse

from . import automations, memory, menu as menu_engine, orchestrator, payments, reports, seed, whatsapp
from .api import router as api_router
from .config import BASE_DIR, settings
from .database import SessionLocal, init_db, session_scope
from .utils import rupees, utcnow

STATIC_DIR = Path(__file__).resolve().parent / "static"
SCHEDULER_INTERVAL = int(os.getenv("SCHEDULER_INTERVAL_SECONDS", "45"))


# --------------------------------------------------------------------------
# Scheduler — roz ke kaam khud karna (badges, reminder, report)
# --------------------------------------------------------------------------
_scheduler_task: asyncio.Task | None = None


async def _scheduler_loop() -> None:
    while True:
        try:
            await asyncio.sleep(SCHEDULER_INTERVAL)
            with session_scope() as db:
                automations.run_due_tasks(db)
        except asyncio.CancelledError:  # pragma: no cover
            raise
        except Exception as exc:  # pragma: no cover
            print(f"[scheduler] error: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler_task
    init_db()
    with session_scope() as db:
        menu_engine.ensure_menu(db)
        from . import discounts

        discounts.seed_rules(db)
        if settings.demo_seed:
            seed.seed_demo(db)
    if settings.automation_enabled:
        _scheduler_task = asyncio.create_task(_scheduler_loop())
    print(
        f"\n🍽️  {settings.restaurant_name} — {settings.agent_name} ready\n"
        f"    WhatsApp: {settings.whatsapp_mode} | AI: {'live' if settings.llm_live else 'demo'} "
        f"| Payment: {'live' if settings.payment_live else 'mock'}\n"
        f"    Dashboard: http://localhost:{settings.port}/\n"
    )
    try:
        yield
    finally:
        if _scheduler_task:
            _scheduler_task.cancel()
            try:
                await _scheduler_task
            except asyncio.CancelledError:
                pass


app = FastAPI(
    title=f"{settings.restaurant_name} — WhatsApp AI Agent",
    description="Restaurant/Cafe WhatsApp AI Agent (memory + funny + orders + payments + owner reports).",
    version="1.0.0",
    lifespan=lifespan,
)
app.include_router(api_router)


# --------------------------------------------------------------------------
# WhatsApp webhook
# --------------------------------------------------------------------------
@app.get("/webhook", response_class=PlainTextResponse)
async def webhook_verify(request: Request):
    """Meta ka verification (hub.mode / hub.verify_token / hub.challenge)."""
    params = request.query_params
    challenge = whatsapp.verify_webhook_challenge(
        params.get("hub.mode", ""), params.get("hub.verify_token", ""), params.get("hub.challenge", "")
    )
    if challenge is None:
        raise HTTPException(status_code=403, detail="verify token match nahi hua")
    return challenge


@app.post("/webhook")
async def webhook_receive(request: Request, background: BackgroundTasks, x_hub_signature_256: str | None = Header(default=None)):
    """Meta se aane wale messages — yahin se poora agent chalta hai."""
    body = await request.body()
    if not whatsapp.verify_signature(body, x_hub_signature_256):
        raise HTTPException(status_code=403, detail="signature invalid")
    try:
        payload = json.loads(body or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid json")

    inbound_messages = whatsapp.parse_webhook(payload)
    if inbound_messages:
        background.add_task(_process_inbound_batch, inbound_messages)
    return {"status": "EVENT_RECEIVED", "count": len(inbound_messages)}


def _process_inbound_batch(inbound_messages: list[whatsapp.Inbound]) -> None:
    with session_scope() as db:
        for inbound in inbound_messages:
            whatsapp.mark_read(inbound.message_id)
            try:
                orchestrator.handle_inbound(db, inbound)
            except Exception as exc:  # pragma: no cover
                orchestrator.log_message(db, inbound.phone, "out", f"[error] {exc}", message_type="system")
                raise


# --------------------------------------------------------------------------
# Payment webhooks + mock payment page
# --------------------------------------------------------------------------
@app.post("/webhook/razorpay")
async def razorpay_webhook(request: Request, x_razorpay_signature: str | None = Header(default=None)):
    body = await request.body()
    if not payments.verify_razorpay_signature(body, x_razorpay_signature):
        raise HTTPException(status_code=403, detail="razorpay signature invalid")
    event = payments.parse_razorpay_event(body)
    if not event or not event.get("paid"):
        return {"status": "ignored", "event": event.get("event") if event else None}

    with session_scope() as db:
        payment = payments.find_payment(db, provider_ref=event.get("provider_ref"), order_no=event.get("order_no"))
        if not payment:
            return {"status": "payment not found", "event": event}
        order = payments.mark_paid(db, payment, ref=event.get("provider_ref"), via="razorpay_webhook")
        if order:
            orchestrator.on_payment_success(db, order, via="razorpay")
    return {"status": "ok", "order": event.get("order_no")}


@app.get("/pay/{token}", response_class=HTMLResponse)
async def mock_pay_page(token: str):
    with session_scope() as db:
        payment, order = payments.payment_by_token(db, token)
        if not payment:
            return HTMLResponse("<h2>Ye payment link expire ho gaya hai 🙏</h2>", status_code=404)
        if payment.status == "paid":
            return RedirectResponse(f"/pay/{token}/done")
        return HTMLResponse(payments.mock_pay_page_html(payment, order, settings.restaurant_name))


@app.post("/pay/{token}/confirm")
async def mock_pay_confirm(token: str):
    with session_scope() as db:
        payment, order = payments.payment_by_token(db, token)
        if not payment:
            raise HTTPException(status_code=404, detail="payment not found")
        order = payments.mark_paid(db, payment, ref=payment.provider_ref, via="mock_page")
        if order:
            orchestrator.on_payment_success(db, order, via="mock_page")
    return RedirectResponse(f"/pay/{token}/done", status_code=303)


@app.get("/pay/{token}/done", response_class=HTMLResponse)
async def mock_pay_done(token: str):
    with session_scope() as db:
        payment, order = payments.payment_by_token(db, token)
        amount = rupees(payment.amount) if payment else ""
        order_no = order.order_no if order else "-"
    return HTMLResponse(
        f"""<!doctype html><html><head><meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1"><title>Payment ho gaya</title>
        <style>body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#f0fdf4;display:flex;
        align-items:center;justify-content:center;min-height:100vh;margin:0}}
        .card{{background:#fff;padding:34px;border-radius:18px;box-shadow:0 20px 50px rgba(21,128,61,.18);
        text-align:center;max-width:380px}}h1{{font-size:20px;margin:12px 0 6px}}
        p{{color:#475569;font-size:14px;margin:4px 0 18px}}.tick{{font-size:52px}}
        a{{display:inline-block;background:#16a34a;color:#fff;text-decoration:none;padding:12px 22px;
        border-radius:12px;font-weight:600}}</style></head><body><div class="card">
        <div class="tick">✅</div><h1>Payment mil gaya!</h1>
        <p>Order #{order_no} — {amount}<br>WhatsApp par thanks message aur agla offer code chala gaya hai 🎁</p>
        <a href="/">Dashboard kholo</a></div></body></html>"""
    )


# --------------------------------------------------------------------------
# Misc
# --------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "restaurant": settings.restaurant_name,
        "agent": settings.agent_name,
        "modes": settings.mode_report(),
        "time": utcnow().isoformat(),
    }


@app.get("/privacy", response_class=HTMLResponse)
async def privacy_page():
    return HTMLResponse(
        f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
        <title>Privacy — {settings.restaurant_name}</title>
        <style>body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:720px;margin:40px auto;
        padding:0 18px;line-height:1.65;color:#1e293b}}h1{{font-size:22px}}h2{{font-size:16px;margin-top:26px}}
        code{{background:#f1f5f9;padding:2px 6px;border-radius:6px}}</style></head><body>
        <h1>{settings.restaurant_name} — WhatsApp Agent Privacy Note</h1>
        <p>Hum sirf wahi data rakhte hain jisse aapka order, booking aur offer kaam kare:</p>
        <h2>Kya store hota hai</h2>
        <ul><li>WhatsApp number (aapki pehchan)</li><li>Naam (agar aap batayein)</li>
        <li>Order history, pasand, loyalty points</li><li>Birthday (agar aap batayein — wish bhejne ke liye)</li></ul>
        <h2>Kya nahi karte</h2>
        <ul><li>Data kisi ko bechte nahi</li><li>Aapki permission ke bina promo message nahi bhejte</li>
        <li><code>STOP</code> likhte hi saare offers band</li></ul>
        <h2>Data hatana hai?</h2>
        <p>WhatsApp par <code>DELETE MY DATA</code> likh dijiye ya {settings.restaurant_phone} par message kijiye — hum aapka data hata denge.</p>
        <p>Ye note DPDP Act, 2023 (India) ke hisaab se likha gaya hai.</p></body></html>"""
    )


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    index = STATIC_DIR / "dashboard.html"
    if not index.exists():
        return HTMLResponse(
            "<h1>Dashboard file missing hai</h1><p><code>app/static/dashboard.html</code> honi chahiye.</p>",
            status_code=500,
        )
    return HTMLResponse(index.read_text(encoding="utf-8"))


def run() -> None:  # pragma: no cover
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.port, reload=False)


if __name__ == "__main__":  # pragma: no cover
    run()
