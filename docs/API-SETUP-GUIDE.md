# API SETUP GUIDE (Hinglish) — Demo se Live tak, step-by-step

Ye guide tumhe **mock mode** se **asli WhatsApp + asli AI + asli payment** tak le jaayegi.
Har step ke baad kya check karna hai, wo bhi likha hai. Pehle `.env` banao:

```bash
cp .env.example .env      # Windows: copy .env.example .env
```

---

## PART 1 — WhatsApp Cloud API (sabse zaruri)

Do raaste hain — report ke Section 7 me detail hai.

### Raasta A: BSP ke through (beginner, jaldi)
AiSensy / WATI / Interakt / Gupshup jaise partner se account lo (₹999–₹2,500/mahina).
Wo Meta ka kaam khud karwa dete hain, tumhe bas unka webhook hamare `/webhook` par point karna hota hai
(kuch BSP apna API use karte hain — tab `app/whatsapp.py` me `_graph_post()` ko unke endpoint par badal do).

### Raasta B: Direct Meta Cloud API (sasta, recommended)

**Step 1 — Meta Business**
business.facebook.com par restaurant ke naam se business account banao.

**Step 2 — Developer App**
developers.facebook.com → My Apps → Create App → "Business" type → app ke andar **WhatsApp** product add karo.

**Step 3 — Number jodo**
Ek aisa number (naya SIM) jo pehle kisi normal WhatsApp par registered **na** ho.
Meta se OTP aayega, verify karo. Display name restaurant ka rakho (approval me 1-2 din lag sakte hain).

**Step 4 — IDs `.env` me daalo**
WhatsApp → API Setup page se:
```env
WHATSAPP_MODE="live"
WHATSAPP_PHONE_NUMBER_ID="1234567890xxxx"     # Phone number ID
WHATSAPP_TOKEN="EAAG..."                       # Temporary token (24 ghante)
WHATSAPP_VERIFY_TOKEN="koi-bhi-lamba-shabd"   # Tum khud banate ho (Meta me yahi daalna hai)
WHATSAPP_APP_SECRET="app secret"               # App settings → Basic → App Secret
WHATSAPP_API_VERSION="v21.0"
```

**Step 5 — Permanent Token (24 ghante wala kaam ka nahi)**
Business Settings → Users → **System Users** → Add → Generate Token → whatsapp_business_messaging + whatsapp_business_management permission → token `.env` me (`WHATSAPP_TOKEN`).

**Step 6 — Webhook lagao**
1. Agent ko public URL par chalao (docs/DEPLOYMENT.md) — jaise `https://agent.sharmacafe.in`
2. Meta → WhatsApp → Configuration → Webhook → URL: `https://agent.sharmacafe.in/webhook`
3. Verify token: wahi jo `.env` me hai → Verify & Save (hamara server `hub.challenge` wapas bhej deta hai)
4. Subscribe: **messages** field tick karo (message status/baad me bhi kar sakte ho)

**Step 7 — Test**
Apne phone se (jo number Meta me test recipient list me add kiya ho) WhatsApp par "hi" bhejo →
dashboard ke Live Chat/Outbox me asli message aayega aur jawab bhi jaayega.

**Step 8 — Template messages (24 ghante ke baad offer bhejne ke liye)**
Meta → WhatsApp → Message Templates → Create:
```
Hello {{1}}, aapke liye {{2}}% OFF — code {{3}}. Sharma Cafe 🍽️
```
Approve hone ke baad `app/whatsapp.py` ka `send_template()` use karo. **Golden rule:** template sirf un logon ko
jo opt-in hain (hamare DB me `opt_in = true`), aur har message me "STOP" ka option.

### WhatsApp ke 2 khass rule (bhoolna mat)
- **24-hour window**: customer ne message kiya to 24 ghante tak free reply. Uske baad template + fees.
- **Quality rating**: spam = number block. Isliye hamare code me `MAX_PROACTIVE_PER_DAY` (default 200) aur
  winback/broadcast sirf opt-in par chalta hai.

---

## PART 2 — AI (LLM)

Agent ke paas **do brain** ka option hai:

| Mode | Kaise | Kiske liye |
|---|---|---|
| `LLM_MODE=demo` | Built-in Hinglish brain (`app/llm.py` → `demo_brain`) | Demo, client presentation, offline testing — **₹0** |
| `LLM_MODE=auth` | Asli AI API | Live restaurant (behtar Hinglish, real understanding) |

### Asli AI lagane ka tarika
```env
LLM_MODE="auth"
LLM_PROVIDER="openai"          # openai | gemini | groq | ollama | custom
LLM_MODEL="gpt-4o-mini"        # sasta aur tez
LLM_API_KEY="sk-..."
LLM_BASE_URL=""                # custom provider ke liye (khaali = provider default)
LLM_TEMPERATURE="0.7"
LLM_MAX_TOKENS="350"
```

- **Gemini** (sasta/free tier): `LLM_PROVIDER="gemini"`, `LLM_MODEL="gemini-2.0-flash"`, key AI Studio se.
- **Groq** (bahut tez): `LLM_PROVIDER="groq"`, `LLM_MODEL="llama-3.3-70b-versatile"`.
- **Ollama** (local, free): `LLM_PROVIDER="ollama"`, `LLM_BASE_URL="http://localhost:11434/v1"`.
- **Voice notes ka text** (Whisper): `LLM_PROVIDER="openai"` rakho to `app/whatsapp.py` ka `transcribe_audio()` kaam karega.

AI ka character badalna ho to `.env` me:
```env
AGENT_NAME="Bablu"
AGENT_PERSONA_EXTRA="Thoda zyada mazak kar sakte ho, par izzat kabhi mat todna."
```
Ya dashboard → Settings se live edit (System Prompt wahi dikhta jo AI ko jaata hai).

---

## PART 3 — Payment (Razorpay)

```env
PAYMENT_MODE="live"
RAZORPAY_KEY_ID="rzp_live_xxxx"
RAZORPAY_KEY_SECRET="xxxx"
RAZORPAY_WEBHOOK_SECRET="xxxx"       # webhook banate waqt tum dete ho
UPI_ID="sharmacafe@upi"
PUBLIC_BASE_URL="https://agent.sharmacafe.in"   # payment links isi se bante hain
```

1. Razorpay account → KYC (PAN, bank account; GST optional) → 1-2 din
2. Dashboard → Settings → API Keys → Key ID + Secret `.env` me
3. Dashboard → Webhooks → Add: URL `https://agent.sharmacafe.in/webhook/razorpay`, event `payment_link.paid` (aur `payment.captured`), secret `.env` me daalo
4. Test: dashboard Live Chat se order karo → asli payment link jayega → pay karo → thanks message + code aa jayega

**Fees:** ~2% per transaction. Bill me GST hamare `GST_PERCENT` se lagta hai (default 5%).

---

## PART 4 — Database (SQLite → Postgres)

Default SQLite (`data/sharma_cafe.db`) — ek cafe ke liye kaafi hai.
Postgres (Supabase/Railway) chahiye to:
```env
DATABASE_URL="postgresql+psycopg://user:pass@host:5432/dbname"
```
`pip install "psycopg[binary]"` aur bas — tables khud ban jaate hain.

---

## PART 5 — Live jane se pehle checklist

- [ ] `.env` me `.env` secrets? GitHub par nahi gaya? (`git status` me `.env` nahi dikhna chahiye)
- [ ] `ADMIN_TOKEN` set kiya (dashboard public URL par khula na ho)
- [ ] Meta webhook verify ho gaya, "hi" ka jawab aa raha hai
- [ ] Menu real prices ke saath (Menu tab) — galti se purana price nahi ja raha?
- [ ] Discount rules + `MAX_DISCOUNT_PERCENT` owner se approve
- [ ] Payment ek real ₹1 ka test order
- [ ] Owner number `OWNER_WHATSAPP` me, staff number `STAFF_WHATSAPP` me
- [ ] `/privacy` page ka link customer ko bhej sakte ho
- [ ] Ek hafta apne doston se test (report Section 20 checklist)

Kuch atak gaya? `journalctl`/logs dekho, ya `GET /health` aur `GET /api/health` se modes check karo.
