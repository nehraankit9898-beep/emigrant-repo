"""WhatsApp Cloud API client — report ka Section 7 (API 1).

Do mode:
  * WHATSAPP_MODE=mock -> kuch bahar nahi jata, sab "outbox" me dikhta hai
    (dashboard ke Live Chat + Outbox me). Demo/testing ke liye perfect.
  * WHATSAPP_MODE=live -> asli Meta Graph API par message jayega.

Webhook verification, signature check aur incoming message parsing — sab yahin.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import settings
from .utils import clean_phone, utcnow

GRAPH_BASE = "https://graph.facebook.com"

# mock mode ka "sent items" dabba (dashboard ise padhta hai)
OUTBOX: deque[dict] = deque(maxlen=200)


# --------------------------------------------------------------------------
# Incoming message
# --------------------------------------------------------------------------
@dataclass
class Inbound:
    phone: str
    profile_name: str | None = None
    type: str = "text"
    text: str = ""
    message_id: str | None = None
    timestamp: int | None = None
    media_id: str | None = None
    interactive_id: str | None = None
    button_text: str | None = None
    raw: dict = field(default_factory=dict)
    source: str = "whatsapp"

    @property
    def effective_text(self) -> str:
        if self.type == "text":
            return self.text
        if self.type == "interactive":
            return (self.button_text or self.interactive_id or "").strip()
        if self.type in {"audio", "voice"}:
            return self.text or "__VOICE_NOTE__"
        if self.type == "image":
            return self.text or "__IMAGE__"
        if self.type == "location":
            return "__LOCATION__"
        return self.text or ""


def parse_webhook(payload: dict) -> list[Inbound]:
    """Meta ka webhook JSON -> hamare Inbound messages (report Section 7 ka format)."""
    inbound: list[Inbound] = []
    for entry in payload.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            value = change.get("value", {}) or {}
            contacts = {c.get("wa_id"): c for c in (value.get("contacts") or [])}
            for message in value.get("messages", []) or []:
                phone = clean_phone(message.get("from", ""))
                contact = contacts.get(phone, {})
                profile_name = ((contact.get("profile") or {}).get("name")) or None
                msg_type = message.get("type", "text")
                text = ""
                media_id = None
                interactive_id = None
                button_text = None
                if msg_type == "text":
                    text = ((message.get("text") or {}).get("body") or "").strip()
                elif msg_type in {"audio", "voice"}:
                    media_id = (message.get(msg_type) or {}).get("id")
                elif msg_type == "image":
                    media_id = (message.get("image") or {}).get("id")
                    text = ((message.get("image") or {}).get("caption") or "").strip()
                elif msg_type == "document":
                    media_id = (message.get("document") or {}).get("id")
                    text = ((message.get("document") or {}).get("caption") or "").strip()
                elif msg_type == "button":
                    button_text = ((message.get("button") or {}).get("text") or "").strip()
                elif msg_type == "interactive":
                    interactive = message.get("interactive") or {}
                    button_reply = (interactive.get("button_reply") or {}) if isinstance(interactive, dict) else {}
                    list_reply = (interactive.get("list_reply") or {}) if isinstance(interactive, dict) else {}
                    interactive_id = button_reply.get("id") or list_reply.get("id")
                    button_text = button_reply.get("title") or list_reply.get("title")
                inbound.append(
                    Inbound(
                        phone=phone,
                        profile_name=profile_name,
                        type=msg_type,
                        text=text,
                        message_id=message.get("id"),
                        timestamp=int(message.get("timestamp") or time.time()),
                        media_id=media_id,
                        interactive_id=interactive_id,
                        button_text=button_text,
                        raw=message,
                    )
                )
    return inbound


def verify_signature(body: bytes, signature_header: str | None) -> bool:
    """Meta ke X-Hub-Signature-256 se check karo ki request asli Meta ki hai."""
    if not settings.whatsapp_app_secret:
        return True  # secret set nahi hai to (demo me) allow
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(settings.whatsapp_app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header.split("=", 1)[1])


def verify_webhook_challenge(mode: str, token: str, challenge: str) -> str | None:
    """Meta GET verification (hub.mode, hub.verify_token, hub.challenge)."""
    if mode == "subscribe" and token == settings.whatsapp_verify_token:
        return challenge
    return None


# --------------------------------------------------------------------------
# Outgoing message
# --------------------------------------------------------------------------
def _chunks(text: str, size: int = 3800) -> list[str]:
    if len(text) <= size:
        return [text]
    parts, current = [], ""
    for line in text.splitlines(keepends=True):
        if len(current) + len(line) > size:
            parts.append(current)
            current = ""
        current += line
    if current:
        parts.append(current)
    return parts


def _record(to: str, kind: str, payload: dict, ok: bool = True, error: str | None = None) -> dict:
    row = {
        "to": clean_phone(to),
        "kind": kind,
        "payload": payload,
        "ok": ok,
        "error": error,
        "mode": "live" if settings.whatsapp_live else "mock",
        "at": utcnow().isoformat(),
    }
    OUTBOX.append(row)
    return row


def _graph_post(path: str, payload: dict, timeout: float = 20.0) -> tuple[bool, dict]:
    if not settings.whatsapp_live:
        return True, {"mock": True}
    url = f"{GRAPH_BASE}/{settings.whatsapp_api_version}/{settings.whatsapp_phone_number_id}/{path}"
    headers = {"Authorization": f"Bearer {settings.whatsapp_token}", "Content-Type": "application/json"}
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(url, json=payload, headers=headers)
            data = response.json() if response.content else {}
            if response.status_code >= 400:
                return False, {"status": response.status_code, "error": data}
            return True, data
    except Exception as exc:
        return False, {"error": str(exc)[:300]}


def send_text(to: str, text: str, preview_url: bool = False) -> list[dict]:
    """Message bhejo (lamba text ho to tukdon me)."""
    results = []
    for chunk in _chunks(text):
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": clean_phone(to),
            "type": "text",
            "text": {"preview_url": preview_url, "body": chunk},
        }
        ok, data = _graph_post("messages", payload)
        results.append(_record(to, "text", {"body": chunk}, ok=ok, error=None if ok else str(data)))
    return results


def send_buttons(to: str, body: str, buttons: list[dict]) -> dict:
    """Quick reply buttons (max 3) — 'Haan / Nahi' type jawab ke liye."""
    buttons = buttons[:3]
    payload = {
        "messaging_product": "whatsapp",
        "to": clean_phone(to),
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body[:1024]},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": b.get("id", f"btn_{idx}"), "title": (b.get("title") or "OK")[:20]}}
                    for idx, b in enumerate(buttons)
                ]
            },
        },
    }
    ok, data = _graph_post("messages", payload)
    return _record(to, "buttons", {"body": body, "buttons": buttons}, ok=ok, error=None if ok else str(data))


def send_catalog_link(to: str, text: str, url: str) -> list[dict]:
    """Menu ka link/photo bhejna."""
    return send_text(to, f"{text}\n{url}", preview_url=True)


def send_image(to: str, link: str, caption: str = "") -> dict:
    payload = {
        "messaging_product": "whatsapp",
        "to": clean_phone(to),
        "type": "image",
        "image": {"link": link, "caption": caption[:1024]},
    }
    ok, data = _graph_post("messages", payload)
    return _record(to, "image", {"link": link, "caption": caption}, ok=ok, error=None if ok else str(data))


def send_template(to: str, name: str, params: list[str], language: str = "hi") -> dict:
    """Approved template message (24 ghante ke baad zaroori — report Section 17)."""
    payload = {
        "messaging_product": "whatsapp",
        "to": clean_phone(to),
        "type": "template",
        "template": {
            "name": name,
            "language": {"code": language},
            "components": [
                {"type": "body", "parameters": [{"type": "text", "text": str(p)} for p in params]}
            ],
        },
    }
    ok, data = _graph_post("messages", payload)
    return _record(to, "template", {"name": name, "params": params}, ok=ok, error=None if ok else str(data))


def mark_read(message_id: str | None) -> None:
    if not message_id or not settings.whatsapp_live:
        return
    _graph_post("messages", {"messaging_product": "whatsapp", "status": "read", "message_id": message_id})


def download_media(media_id: str) -> tuple[bytes | None, str | None]:
    """Voice note / photo ka data (live me). Mock me None."""
    if not settings.whatsapp_live or not media_id:
        return None, None
    headers = {"Authorization": f"Bearer {settings.whatsapp_token}"}
    try:
        with httpx.Client(timeout=30) as client:
            meta = client.get(f"{GRAPH_BASE}/{settings.whatsapp_api_version}/{media_id}", headers=headers).json()
            url = meta.get("url")
            mime = meta.get("mime_type")
            if not url:
                return None, None
            blob = client.get(url, headers=headers).content
        return blob, mime
    except Exception:
        return None, None


def transcribe_audio(blob: bytes, mime: str | None) -> str | None:
    """Voice note -> text (OpenAI Whisper). Key na ho to None."""
    if not (blob and settings.llm_api_key and settings.llm_provider == "openai"):
        return None
    try:
        with httpx.Client(timeout=45) as client:
            response = client.post(
                f"{settings.llm_endpoint}/audio/transcriptions",
                headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                files={"file": ("voice.ogg", blob, mime or "audio/ogg")},
                data={"model": "whisper-1"},
            )
            response.raise_for_status()
            return (response.json().get("text") or "").strip()
    except Exception:
        return None


def outbox_tail(limit: int = 30, phone: str | None = None) -> list[dict]:
    rows = list(OUTBOX)
    if phone:
        phone = clean_phone(phone)
        rows = [row for row in rows if row["to"] == phone]
    return rows[-limit:]


def graph_payload_preview(to: str, text: str) -> str:
    """Report me dikhaya gaya asli request body (documentation ke liye)."""
    return json.dumps(
        {
            "messaging_product": "whatsapp",
            "to": clean_phone(to),
            "type": "text",
            "text": {"body": text},
        },
        ensure_ascii=False,
        indent=2,
    )
