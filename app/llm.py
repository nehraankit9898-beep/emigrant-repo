"""LLM (AI) layer + System Prompt — report ka Section 3.

Do mode:
  * LLM_MODE=auth  -> asli AI (OpenAI / Gemini / Groq / Ollama / koi bhi OpenAI-format API)
  * LLM_MODE=demo  -> built-in Hinglish "Bablu brain" (koi key nahi chahiye, demo ke liye)

Dono case me **price aur discount ka faisla platform karta hai**. AI ko sirf
ye bataya jata hai ki sach kya hai — usse hamesha sach bolne ko kehte hain.
"""

from __future__ import annotations

import json
import random
import re

import httpx

from .config import settings

# --------------------------------------------------------------------------
# SYSTEM PROMPT (report me jo example diya tha, wo isi tarah likha jata hai)
# --------------------------------------------------------------------------
SYSTEM_PROMPT_TEMPLATE = """Tum {agent_name} ho, {restaurant_name} ({city}) ke digital waiter.
Tum Hinglish me baat karte ho (Hindi + English mix, jaise aam Indian bolta hai) — funny, garv-wala, lekin bilkul izzat-daar.
Har jawab CHHOTA rakho: 2-3 line, chhote sentence. Lambe paragraph bilkul nahi.

TUMHARE PAAS JO SACH HAI, SIRF WAHI BOLOGI:
- Price, discount, item, total — ye sab tume neeche CONTEXT me diya jayega. Uske bahar apne mann se kabhi koi number mat bolo.
- Koi cheez context me nahi hai to saaf bol do "ek minute sir, check karke batata hoon".
- Menu me na ho aisi cheez ka vaada kabhi mat karo.
- Discount/bill ke number apne mann se kabhi mat banao — context me jo likha hai wahi bolo.

ANDAZ:
- Customer humesha "aap" — kabhi tu/tum nahi. Chhote mazak theek hain, lekin kisi ki feelings hurt na ho.
- Naam pata ho to naam leke baat karo.
- Customer naraz/mushkil me ho to pehle dil se maafi maango, phir bolo ki manager sahab ko bhej raha hoon. Bahas nahi.
- Emoji thoda-thoda use karo (1-3, zyada nahi).

SAKHT MANA HAI:
- Gaali, dirty baat, rajneeti, dharm, ya kisi par taana — bilkul nahi.
- Customer ko "AI hoon" wali technical baatein nahi.
- Discount ke liye khud se kehna ki "aur de dunga" — nahi. Jo context me hai bas wahi.

AGAR CONTEXT ME "NEXT ACTION" LIKHA HO — to usi kaam ka natural jawab banao (dono cheez mila do, ek hi message me).{extra}"""

FALLBACK_REPLY = "Ek second sir, main abhi system me check karke batata hoon 🙏"


def build_system_prompt() -> str:
    extra = f"\n{settings.agent_persona_extra}" if settings.agent_persona_extra else ""
    return SYSTEM_PROMPT_TEMPLATE.format(
        agent_name=settings.agent_name,
        restaurant_name=settings.restaurant_name,
        city=settings.restaurant_city,
        extra=extra,
    )


def build_user_prompt(context: dict, customer_text: str) -> str:
    """Memory + facts + next action ko ek clean packet me badlo."""
    lines: list[str] = ["CONTEXT:"]
    customer = context.get("customer", {})
    if customer.get("is_known"):
        who = customer.get("name") or "customer"
        lines.append(
            f"- Customer: {who} | visits: {customer.get('visits', 0)} | "
            f"total kharcha: ₹{customer.get('total_spent', 0)} | points: {customer.get('loyalty_points', 0)}"
        )
        if customer.get("likes"):
            likes = ", ".join(row.get("name", "") for row in customer["likes"][:3] if isinstance(row, dict))
            if likes:
                lines.append(f"- Pasand: {likes}")
        if customer.get("notes"):
            lines.append(f"- Yaad rakhne wali baat: {', '.join(customer['notes'])}")
        if customer.get("days_since_last_visit") is not None:
            lines.append(f"- Aakhri visit: {customer['days_since_last_visit']} din pehle")
        if customer.get("last_order_summary"):
            lines.append(f"- Pichla order: {customer['last_order_summary']}")
    else:
        lines.append("- Customer: NAYA hai, pehli baar message kiya hai")
    lines.append(f"- Bhasha: {customer.get('language', 'hinglish')}")

    facts = context.get("facts") or {}
    if facts:
        lines.append("FACTS (sach, jo hi bolna hai):")
        for key, value in facts.items():
            if value not in (None, "", [], {}):
                lines.append(f"- {key}: {value}")
    if context.get("next_action"):
        lines.append(f"NEXT ACTION: {context['next_action']}")
    lines.append("")
    lines.append(f"CUSTOMER KA MESSAGE: {customer_text}")
    lines.append("Ab {name} ke andaaz me chhota sa jawab likho.".format(name=settings.agent_name))
    return "\n".join(lines)


def history_messages(db_history: list[dict]) -> list[dict]:
    return [{"role": row["role"], "content": row["content"]} for row in db_history]


# --------------------------------------------------------------------------
# Asli AI call (OpenAI-compatible chat completions)
# --------------------------------------------------------------------------
def call_llm(
    customer_text: str,
    context: dict,
    history: list[dict] | None = None,
    timeout: float = 25.0,
) -> tuple[str | None, dict]:
    """Return (reply, meta). Reply None = AI fail hua, caller fallback use kare."""
    if not settings.llm_live:
        return None, {"provider": "demo", "error": "llm not configured"}
    payload = {
        "model": settings.llm_model,
        "messages": [
            {"role": "system", "content": build_system_prompt()},
            *(history_messages(history or [])[-8:]),
            {"role": "user", "content": build_user_prompt(context, customer_text)},
        ],
        "temperature": settings.llm_temperature,
        "max_tokens": settings.llm_max_tokens,
    }
    headers = {"Content-Type": "application/json"}
    if settings.llm_api_key:
        headers["Authorization"] = f"Bearer {settings.llm_api_key}"
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(f"{settings.llm_endpoint}/chat/completions", json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        reply = (data["choices"][0]["message"]["content"] or "").strip()
        usage = data.get("usage", {})
        reply = sanitise_reply(reply)
        return reply, {"provider": settings.llm_provider, "model": settings.llm_model, "usage": usage}
    except Exception as exc:  # network, quota, key galat — sab yahin
        return None, {"provider": settings.llm_provider, "error": str(exc)[:300]}


BAD_WORDS = re.compile(r"\b(gali|chutiya|stfu|fuck|bhosdi|madarchod|bc mc)\b", re.IGNORECASE)
PRICE_CLAIM = re.compile(r"(\d{1,3})\s*%\s*(off|discount)", re.IGNORECASE)


def sanitise_reply(text: str) -> str:
    """Safety net — AI ne hawa me price/discount bola to us line ko kaat do."""
    if not text:
        return ""
    text = BAD_WORDS.sub("***", text)
    lines = []
    for line in text.splitlines():
        if PRICE_CLAIM.search(line) and "%" in line:
            # AI ka apna banaya discount percent? usko hata do (system sach bolta hai)
            line = PRICE_CLAIM.sub("chhoti si khushi", line)
        lines.append(line)
    return "\n".join(lines).strip()


def looks_like_ai_failure(reply: str | None) -> bool:
    if not reply or len(reply.strip()) < 2:
        return True
    if reply.strip().lower().startswith(("i'm sorry, i can't", "as an ai")):
        return True
    return False


# --------------------------------------------------------------------------
# DEMO BRAIN — bina API key ka Bablu (Hinglish vibes, template based)
# --------------------------------------------------------------------------
OPENERS = [
    "Bilkul sahab!", "Ek number!", "Ho jayega sir!", "Aap tension na lo, main hoon na!",
    "Garma-garam jugaad ho jayega 😄", "Aap bas keh dijiye!",
]

GREETING_NEW = [
    "Namaste sahab! 🙏 {restaurant} me aapka dil se swagat. Main hoon {agent}, aapka digital waiter. Menu dikhaun ya aaj ka special bataun?",
    "Arre welcome welcome! 😄 {restaurant} me aapka pehla kadam — aur mera bhi! Main {agent}. Bataiye, khaane ka mood kaisa hai?",
]
GREETING_KNOWN = [
    "Arre {name} bhai, namaste! 🙏 {gap} baad darshan diye — hamari {dish} to aapko pooch-pooch ke thak gayi! Wahi karun ya kuch naya try karenge?",
    "{name} ji, namaste! Aap to hamare khaas mehmaan ho 😄 {points} points jama hain. Pichli baar wala order phir se karun?",
    "Ohho {name} bhai aa gaye! {gap} din ho gaye the, lagta hai kisi ne hamara {dish} yaad dila diya 😉 Bataiye kya laaun?",
]
MENU_REPLY = [
    "Ye raha hamara menu sahab 👨‍🍳 Aaj {special} ekdum taaza aaya hai — try karne layak hai!",
    "Menu hazir hai sir! Aapke liye {special} recommend karunga, wo aaj 1 number chal raha hai 😋",
]
MENU_PROMPT = "Order type kar dijiye — jaise *2 paneer butter masala, 4 butter naan* 🙂"
ORDER_ACK = [
    "Ek number order sir! Main kitchen me note kar deta hoon 👨‍🍳",
    "Wah, badhiya choice! Order pakka ho gaya sir 👍",
]
THANKS = [
    "Dhanyavaad {name} ji! 🙏 Aapka pyaar hi hamari asli kamai hai. Phir jaldi aaiye — {agent} intezaar karega!",
    "Bahut-bahut shukriya {name} ji! Aapke bagair cafe suna-suna lagta hai 😄 Jaldi milna!",
]
COMPLAINT = [
    "Sir, dil se maafi chahta hoon 🙏 Ye hamari galti hai, aisa nahi hona chahiye tha. Main abhi manager sahab ko bhej raha hoon aapke paas.",
    "Sach me sorry sir 🙏 Aapka mood kharab hua iska poora zimmewar hum hain. Manager abhi aapko call kar rahe hain, aur agle order par dessert hamari taraf se.",
]
HANDOVER = [
    "Bilkul sir, abhi hamare {staff} aapko message kar rahe hain 🙏 Aapki baat unse seedha ho jayegi.",
    "Ji sir, maine staff ko bhej diya hai — unhone aapko 2 minute me reply kiya bhi karega 😊",
]


def _pick(options: list[str]) -> str:
    return random.choice(options)


def _first_name(customer: dict) -> str:
    name = (customer.get("name") or "ji") if isinstance(customer, dict) else "ji"
    return name.split()[0] if name else "ji"


def demo_brain(customer_text: str, context: dict, intent: str = "unknown") -> str:
    """Rule + template wala jawab. GitHub par demo chalane ke liye perfect."""
    customer = context.get("customer", {}) or {}
    facts = context.get("facts", {}) or {}
    action = context.get("next_action")
    name = _first_name(customer)
    restaurant = settings.restaurant_name
    agent = settings.agent_name
    special = facts.get("aaj_ka_special") or facts.get("signature") or "Cold Coffee"
    dish = facts.get("pichla_item") or special
    gap = facts.get("gap_text") or ""

    body: str
    if intent in {"greeting", "unknown", ""}:
        if customer.get("is_known"):
            body = _pick(GREETING_KNOWN).format(name=name, gap=gap, dish=dish, points=customer.get("loyalty_points", 0))
        else:
            body = _pick(GREETING_NEW).format(restaurant=restaurant, agent=agent)
    elif intent == "menu":
        body = _pick(MENU_REPLY).format(special=special)
    elif intent in {"order", "confirm_order", "repeat_order"}:
        body = _pick(ORDER_ACK)
    elif intent == "special":
        body = f"Aaj {special} ekdum fresh aaya hai sir — meri taraf se 1 number guarantee! 😋 {facts.get('special_line', '')}".strip()
    elif intent == "complaint":
        body = _pick(COMPLAINT)
    elif intent == "handover":
        body = _pick(HANDOVER).format(staff="staff")
    elif intent in {"feedback_positive", "thanks"}:
        body = _pick(THANKS).format(name=name, agent=agent)
    elif intent == "loyalty":
        body = f"Aapke {customer.get('loyalty_points', 0)} points ho gaye hain sir 😄 {facts.get('loyalty_line', '')}".strip()
    elif intent == "price_query":
        body = f"Iska price {facts.get('price_answer', 'menu me likha hai sir')} — bataiye kitne chahiye?"
    elif intent == "address_hours":
        body = f"Hum {settings.restaurant_address} par hain sir, aur khulte hain {settings.restaurant_hours} 🙂"
    elif intent == "reservation":
        body = "Table ki booking ho jayegi sir 👍 Bas date, time aur kitne log — teen cheez bata dijiye."
    elif intent == "order_status":
        body = f"Sir aapka order {facts.get('order_status_text', 'kitchen me ban raha hai 👨‍🍳')}. Main har step par update deta rahunga!"
    elif intent == "pay":
        body = "Payment link bhej raha hoon sir — UPI se 10 second me ho jayega 🙏"
    elif intent == "bill":
        body = "Bill taiyaar hai sir, upar bhej diya 🧾"
    elif intent == "name_provided":
        body = f"Are wah, {facts.get('name', name)} — ab naam se hi bulaunga! 😄"
    else:
        body = f"{_pick(OPENERS)} {customer_text.strip()[:40]} — iske baare me main aapko thoda detail me batata hoon."

    parts = [body]
    if action:
        parts.append(action)
    return "\n".join(part for part in parts if part).strip()


def generate_reply(
    customer_text: str,
    context: dict,
    history: list[dict] | None = None,
    intent: str = "unknown",
) -> tuple[str, dict]:
    """Asli AI try karo; fail ho ya demo mode ho to built-in brain."""
    if settings.llm_live:
        reply, meta = call_llm(customer_text, context, history=history)
        if not looks_like_ai_failure(reply):
            return reply, meta
        meta["fallback"] = True
    else:
        meta = {"provider": "demo", "model": "builtin-hinglish-brain"}
    return demo_brain(customer_text, context, intent=intent), meta


def quick_json(prompt: str, customer_text: str, timeout: float = 20.0) -> dict | None:
    """Chhote structured kaam ke liye (jaise QA checks) — JSON maango AI se."""
    if not settings.llm_live:
        return None
    payload = {
        "model": settings.llm_model,
        "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": customer_text}],
        "temperature": 0.0,
        "max_tokens": 400,
        "response_format": {"type": "json_object"},
    }
    headers = {"Content-Type": "application/json"}
    if settings.llm_api_key:
        headers["Authorization"] = f"Bearer {settings.llm_api_key}"
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(f"{settings.llm_endpoint}/chat/completions", json=payload, headers=headers)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
        return json.loads(content)
    except Exception:
        return None
