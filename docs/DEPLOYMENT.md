# DEPLOYMENT — agent ko 24x7 online kaise rakhein

Agent ko internet par ek public URL chahiye (Meta webhook usi par aayega). 3 tarike:

---

## 1. Render / Railway (sabse aasan, beginner-friendly)

**Render:**
1. GitHub par ye repo push karo
2. Render → New → **Web Service** → repo select → Render `Dockerfile` khud padh lega
3. Environment variables daalo (`.env` ki keys) — Render dashboard → Environment
4. Free plan par server so jaata hai; **paid ($7/mo)** lo to 24x7 chalega (agent ke liye zaroori)
5. URL milega: `https://sharma-cafe-agent.onrender.com` → `PUBLIC_BASE_URL` me daalo
6. Meta webhook: `https://sharma-cafe-agent.onrender.com/webhook`

**Railway:** New Project → Deploy from GitHub → Variables me `.env` content paste → Settings → Generate Domain.

> **Disk note:** SQLite file container restart par mit sakti hai. Render me "Persistent Disk" lagao (`/data`) aur
> `DATABASE_URL="sqlite:////data/sharma_cafe.db"` rakho — ya Supabase Postgres use karo (recommended).

---

## 2. VPS (DigitalOcean / Hetzner / AWS Lightsail — ₹400-800/mahina)

```bash
ssh root@your-server-ip
apt update && apt install -y docker.io docker-compose-plugin nginx certbot python3-certbot-nginx git
git clone <repo-url> /opt/wa-agent && cd /opt/wa-agent
cp .env.example .env && nano .env      # keys daalo (APP_ENV=production, ADMIN_TOKEN, POSTGRES_PASSWORD, secrets)
docker compose build
# Existing database par run karne se pehle backup + schema/version verify karein.
# Sirf approved migration step me chalayen (app startup ise khud nahi chalata):
docker compose run --rm app alembic upgrade head
docker compose up -d
```

`docker-compose.yml` me Postgres + agent dono hain. HTTPS ke liye nginx + certbot:

```nginx
server {
    server_name agent.sharmacafe.in;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```
```bash
certbot --nginx -d agent.sharmacafe.in
```

Backup (roz 2 baje):
```bash
0 2 * * * docker exec wa-agent-db pg_dump -U agent sharmacafe | gzip > /backup/agent-$(date +\%F).sql.gz
```

---

## 3. Apna laptop (sirf testing ke liye)

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```
Bahar se reach karne ke liye tunnel: `ngrok http 8000` (URL Meta webhook me daalo).
Meta ke webhook ke liye HTTPS zaroori hai — ngrok/cloudflared free me de dete hain.

---

## Docker

**Dockerfile** repo me ready hai (Python 3.11 slim + uvicorn).
**docker-compose.yml** Postgres + agent chalata hai:

```bash
docker compose build
# Migration explicit/reviewed; skip until existing database schema has been checked.
docker compose run --rm app alembic upgrade head
docker compose up -d
docker compose logs -f app       # logs
docker compose down              # band
```

Endpoints jo monitor karne layak hain:
```
GET /health          → status + modes (WhatsApp/AI/Payment live ya mock)
GET /api/health      → counts (customers, orders, messages) — ADMIN_TOKEN lagao
```

---

## Production checklist

- [ ] `APP_ENV=production` (isi se startup strict hota hai: unsafe config par app start nahi hota)
- [ ] `ADMIN_TOKEN` set, kam se kam 32 random chars (`python -c "import secrets;print(secrets.token_urlsafe(32))"`)
- [ ] `WHATSAPP_MODE=live`, `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_APP_SECRET`, random `WHATSAPP_VERIFY_TOKEN` (at least 24 chars); `PAYMENT_MODE=live`, `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET` set
- [ ] `POSTGRES_PASSWORD` random only when using Docker Compose's local PostgreSQL service; it is not the Neon password/setting
- [ ] `PUBLIC_BASE_URL` sahi (payment links isi se bante hain)
- [ ] `DATABASE_URL` PostgreSQL using Psycopg 3 (SQLite sirf demo/single cafe); Neon ka pooled connection URL preferred hai. `postgresql://...` URLs are normalized to `postgresql+psycopg://...` by config.
- [ ] `DEMO_SEED=false` — production startup refuses demo seeding to avoid inserting sample customers/orders.
- [ ] Schema migrations are a reviewed, explicit release step (never automatic at app startup): after backup and schema/version review, run `docker compose run --rm app alembic upgrade head` or `make migrate`. Existing Neon schema ko pehle verify/stamp plan ke bina migrate na karein; `0001_baseline` fresh schema ke liye tables create karta hai.
- [ ] `FORWARDED_ALLOW_IPS` = sirf reverse proxy ka IP (HTTPS proxy ke peeche)
- [ ] `AUTOMATION_ENABLED=true` aur `OWNER_REPORT_TIME` owner ki pasand ka
- [ ] Backup cron + uptime monitor (uptime kuma / healthchecks.io) → `/ready` par
- [ ] `MAX_PROACTIVE_PER_DAY` owner ke message budget ke hisaab se (Meta fees!)
- [ ] Logs me token/keys kahin print nahi ho rahe (logger redact karta hai; purane access logs me agar `?token=` tha to rotate + purge karo)
- [ ] Docs: `docs/SECURITY_AUDIT.md` ka secure configuration checklist

**Abhi ki limitations (production se pehle samajh lo):** ek deployment = ek restaurant (multi-tenant nahi hai),
roles nahi hain (ek admin token), Postgres aur Docker image is sandbox me verify nahi hue — `docs/FEATURE_STATUS.md` dekho.

---

## Multi-restaurant — abhi ki situation

**Abhi multi-tenant nahi hai.** Har restaurant ke liye alag deployment (alag DB, alag `.env`) chalana hi safe tareeka hai.
Shared SaaS ke liye tenant model zaroori hai — `docs/IMPLEMENTATION_PLAN.md` (P1-1).

Ek hi code, har restaurant ke liye alag deployment:
```bash
# restaurant A
PORT=8001 DATABASE_URL="sqlite:///./data/cafe_a.db" RESTAURANT_NAME="Cafe A" \
  uvicorn app.main:app --port 8001
```
Ya Docker me per-customer container + alag `.env`. Ek central panel ke liye bhi abhi koi shared model nahi hai.
