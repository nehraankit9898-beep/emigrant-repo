# README — Restaurant/Cafe WhatsApp AI Agent (Hinglish, funny + memory wala)

> Ye repo **sirf report nahi hai** — isme poora **chalne wala WhatsApp AI Agent** hai:
> funny Hinglish waiter + customer memory + menu/order/bill + discount rule engine +
> UPI payment + table booking + feedback + birthday/winback + owner ki daily report,
> aur ek **live dashboard** jisme aap agent se chat karke sab test kar sakte ho.

Report (A to Z jaankari, sasta/mahanga, timeline, business plan): **[WhatsApp-Restaurant-Agent-A-to-Z-Report.md](WhatsApp-Restaurant-Agent-A-to-Z-Report.md)**

---

## 1. Sabse jaldi kaise chalao (60 second)

```bash
git clone <is-repo-ka-url> && cd emigrant-repo
python3 -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Bas. Ab kholo **http://localhost:8000** — ye dashboard hai.

> Koi API key, koi WhatsApp account, koi paisa — kuch nahi chahiye.
> Default mode **demo** hai: WhatsApp mock (messages dashboard me dikhte hain),
> AI ke liye built-in Hinglish brain, payment ke liye mock page.
> Demo data (Sharma Cafe ke customers, orders, feedback) khud load ho jaata hai.

Terminal me sirf demo dekhna ho to:

```bash
python -m scripts.demo_chat --reset        # poora chat + memory ka demo
python -m pytest -q                        # 25 tests (flow, discount, memory, webhook...)
```

---

## 2. Dashboard me kya-kya hai

| Tab | Kaam |
|---|---|
| **Overview** | Aaj ki sale, orders, avg bill, top items, hourly chart, alerts, owner report ka text |
| **Live Chat** | Agent se baat karo (asli WhatsApp jaisa hi pipeline chalta hai) — bill, payment link, sab live ban jaata hai |
| **Orders** | Manual/QR order daalo, payment mark karo, kitchen status badlo (customer ko message khud jaata hai) |
| **Menu** | Item add/edit/price change/hide — jo WhatsApp par jaata hai wahi preview me dikhta hai |
| **Memory** | Har customer ki file: visits, kharcha, pasand, notes, birthday, points, opt-in status, segments |
| **Offers** | Discount rules (Section 5 wali table), coupons, free item — sab editable |
| **Campaigns** | Birthday wishes, winback 20% OFF, broadcast — **sirf opt-in customers ko**, STOP wale skip |
| **Table Booking** | Booking list + nayi booking, 1 ghanta pehle reminder khud jaata hai |
| **Feedback** | Rating, Google review link, 1-3 star par owner ko turant alert |
| **Alerts** | Complaint, naya order, payment, handover — owner ke liye |
| **Automation** | Agent khud kya-kya karta hai + "abhi chalao" button |
| **Settings** | System prompt dekho, persona edit karo, modes dekho, Graph API payload dekho |

Dashboard khud customer ban ke message bhejta hai — matlab **WhatsApp account ke bina bhi poora product test ho jaata hai.**

---

## 3. Kitne kaam karta hai (features A to Z)

**Core (Phase 1)**
- F1 Funny welcome — naye ko swagat, purane ko naam leke ("12 din baad darshan diye!")
- F2 Customer memory — number = pehchan; naam, pasand, notes, last order, kitni baar aaya
- F3 Digital menu — category-wise, veg/non-veg, signature items
- F4 Chat se order — "2 paneer butter masala, 4 butter naan", "do masala dosa", Hindi words bhi
- F5 Smart suggestion — bika hua/signature item recommend
- F6 Discount rule engine — WELCOME10, REGULAR15, BIGBILL, MISSYOU20, birthday...
- F7 Bill + UPI payment link — GST, discount, freebie sab bill me
- F8 Payment ke baad thanks + agle order ka code (THANKS-x)
- F9 Table booking — date/time/persons slot-filling, full-slot handling, reminder
- F10 Order status — kitchen → pack → rider → delivered, har step par message

**Growth (Phase 2)**
- F11 Birthday wish + free dessert coupon (subah 9 baje khud)
- F12 Winback — 30 din se gayab customer ko 20% OFF (sirf permission wale ko)
- F13 Loyalty points — har ₹100 par points, free coffee wala milestone
- F14 Feedback + Google review — 4-5 star par review link + coupon, 1-3 star par owner alert
- F15 Broadcast — sabko offer (opt-in filter + roz ki limit + STOP respect)
- F16 Complaint handling — maafi + owner ko turant alert + free dessert coupon

**Pro (Phase 3)**
- F17 Table QR order (channel="qr" + table number, dashboard se bhi)
- F18 Party/catering enquiry — date, log, budget poochh ke owner ko alert
- F19 Owner daily report — raat ko WhatsApp par sale/orders/top item/rating
- F20 Human handover — "insaan se baat karni hai" → customer ko bata ke staff ko chat, agent chup
- F21 Multi-language — Hinglish / Hindi / English auto-detect
- F22 Multi-branch ready — ek hi code se kai restaurant (per-restaurant .env + DB)

---

## 4. Architecture (report Section 6 wala diagram, ab code me)

```
Customer (WhatsApp)
   │  "2 paneer butter masala bhejo"
   ▼
Meta WhatsApp Cloud API ──webhook──► app/main.py  (/webhook)
   ▲                                   │
   │                                   ├─ app/memory.py     → customer pehchan + yaad-dasht
   │                                   ├─ app/intent.py     → message ka matlab (rules)
   │                                   ├─ app/menu.py       → item + PRICE (AI se nahi!)
   │                                   ├─ app/discounts.py  → discount ka faisla rule se
   │                                   ├─ app/pricing.py    → bill + GST + total
   │                                   ├─ app/llm.py        → sirf baat ka andaaz (AI/demo brain)
   │                                   └─ app/payments.py   → Razorpay link / mock page
   │                                   │
   └───────────────────────────────────┘  jawab + bill + link
                                       │
                       app/automations.py → birthday, winback, feedback, report, status
                       app/reports.py     → owner ki daily/weekly report
                       app/static/dashboard.html → owner ka control room
```

**Golden Rule (code me sach me lagu):** AI kabhi price/discount ka malik nahi.
`app/llm.py` sirf "kya bolna hai wo kaise bolna hai" likhta hai;
`app/menu.py` + `app/pricing.py` + `app/discounts.py` ke bina ek rupya bhi nahi hilta.
`app/llm.py` ke `sanitise_reply()` me safety net bhi hai — AI hawa me "% off" bole to line kat jaati hai.

---

## 5. Demo → Live kaise karo (3 file, 10 minute)

`.env.example` ko `.env` bana lo, phir ye 3 switch badlo (poori guide: [docs/API-SETUP-GUIDE.md](docs/API-SETUP-GUIDE.md)):

| Kya | `.env` me | Kahan se milega |
|---|---|---|
| Asli WhatsApp | `WHATSAPP_MODE=live` + `WHATSAPP_PHONE_NUMBER_ID` + `WHATSAPP_TOKEN` + `WHATSAPP_VERIFY_TOKEN` | Meta Business app → WhatsApp (guide me step-by-step) |
| Asli AI | `LLM_MODE=auth` + `LLM_PROVIDER` + `LLM_API_KEY` + `LLM_MODEL` | OpenAI / Gemini / Groq (OpenAI-compatible) |
| Asli payment | `PAYMENT_MODE=live` + `RAZORPAY_KEY_ID` + `RAZORPAY_KEY_SECRET` | Razorpay dashboard |

Webhook URL Meta me daalo: `https://<tumhara-domain>/webhook` (verify token wahi jo `.env` me hai).

⚠️ `.env` ko **kabhi** git me push mat karna — `.gitignore` me pehle se hai.

---

## 6. Project structure

```
app/
  main.py          FastAPI app: webhooks, mock payment page, dashboard serve
  api.py           Dashboard/Admin API (saare /api routes)
  config.py        .env se saari settings + mode report
  database.py      SQLite/Postgres engine + session
  models.py        13 tables (customers, menu, orders, coupons, reservations, feedback, messages, alerts, campaigns, payments, rules, settings)
  menu.py          Menu + price + chat se order padhna (Hinglish parsing)
  memory.py        Customer memory, segments, loyalty milestone
  intent.py        Intent engine (order/menu/complaint/handover/STOP/reservation...)
  pricing.py       Bill engine (discount, GST, total) — AI ise chhoo nahi sakta
  discounts.py     Discount/coupon rule engine (Section 5 ki table)
  llm.py           System prompt + asli AI call + demo Hinglish brain + safety net
  whatsapp.py      Cloud API client, webhook parse, signature verify, mock outbox
  payments.py      Razorpay link + mock payment page + webhook verify
  orchestrator.py  Dimaag: har message ka poora safar
  automations.py   Birthday, winback, broadcast, order status, reminder, report
  reports.py       Daily/weekly report (owner ke WhatsApp par)
  seed.py          1 mahine ka demo data
  static/dashboard.html  Owner ka dashboard (single file, koi CDN nahi)
scripts/demo_chat.py   Terminal me live demo
n8n/whatsapp-agent-workflow.json   Low-code (Tarika 2) workflow
tests/                25 tests — poora flow covered
docs/                 Setup guide, deployment, owner demo script
```

---

## 7. API (jhalki)

```
GET  /webhook                 Meta verification (hub.challenge)
POST /webhook                 Meta messages → agent
POST /webhook/razorpay        Payment webhook
GET  /pay/{token}             Mock payment page (demo)
GET  /health                  Status + modes
GET  /privacy                 DPDP-friendly privacy note

API (dashboard):
GET  /api/summary             Cards + today report
POST /api/simulate            {phone, text} → agent chalao (poora pipeline)
GET  /api/messages/{phone}    Chat history
GET  /api/orders              Orders (filters: status/payment)
POST /api/orders              Manual/QR order
PATCH /api/orders/{no}        Status badlo / paid mark karo
GET|POST /api/menu            Menu CRUD
GET|POST /api/rules           Discount rules
POST /api/coupons             Coupon banao
GET  /api/customers           Memory + segments (winback/birthday/optin)
POST /api/campaigns/birthday|winback|broadcast
GET  /api/reports/daily       Owner report + text
POST /api/automations/run     Due tasks abhi chalao
GET  /api/settings, /api/prompt
POST /api/demo/reset          Demo data reset
```

Agar `.env` me `ADMIN_TOKEN` set kiya ho to har API call me `X-Admin-Token` header bhejna hoga.

---

## 8. Testing

```bash
python -m pytest -q
```

25 tests: order parsing (Hindi numbers bhi), bill maths + discount cap, coupon ek hi baar,
payment idempotency, thanks + loyalty points, complaint alert, handover, STOP/START,
table booking + cancel, feedback (good/bad), birthday ek hi baar, winback sirf opt-in ko,
intent engine, language detect, webhook parsing, prompt safety rules.

Report ka Section 20 checklist bhi inhi tests me cover hota hai.

---

## 9. Deploy (24x7 online)

- **Render / Railway** — `Dockerfile` ready hai, ek click me deploy. [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)
- **VPS** — `docker compose up -d` (Postgres + agent + dashboard)
- **Local** — `python -m app.main`
- Live domains: `.env` me `PUBLIC_BASE_URL=https://agent.yourcafe.in` — payment links isi se bante hain

---

## 10. Kanoon & safety (report Section 22)

- Offer message sirf **opt-in** customers ko; `STOP` likhte hi list se out, `START` se wapas in
- Roz ki proactive limit (`MAX_PROACTIVE_PER_DAY`) aur idempotent automations — spam control
- Data sirf order/bill/booking ke liye (DPDP Act 2023 friendly) — `/privacy` page ready hai
- Token/keys sirf `.env` me, code me kabhi nahi; `.gitignore` me secrets blocked
- WhatsApp Business Policy: marketing ke liye template approval + fees (report Section 17)

---

## 11. Pehle 10 din ka plan (report Section 15 ke saath)

1. Din 1: dashboard chalao, Live Chat me apne dost ban ke 20 message bhejo
2. Din 2: menu real cafe ka daal do (Menu tab), rules apne hisaab se set karo
3. Din 3: Meta app + number + `.env` me `WHATSAPP_MODE=live`, webhook URL lagao
4. Din 4: asli number se apne phone par test — bill, payment, thanks, feedback
5. Din 5: ek cafe me free trial lagao, dashboard se roz nazar rakho
6. Din 6-10: feedback dekh ke prompt/menu/discount tune karo → pehla paid customer 🎉

---

## License

Is repo ka code tumhara hai — jo bhi karo, bas restaurant wale ke data ka khayal rakhna 😄

*Report + code dono ek saath: pehle report padho (kyun/kitna/kaise), phir ye repo chalao (kya ban gaya dekhne ke liye).*
