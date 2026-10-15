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
cp .env.example .env && nano .env      # keys daalo
docker compose up -d --build
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
docker compose up -d --build     # chalu
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

- [ ] `ADMIN_TOKEN` set (dashboard bina token kholna band)
- [ ] `WHATSAPP_APP_SECRET` + `RAZORPAY_WEBHOOK_SECRET` set (warna webhook verify loose rehta hai)
- [ ] `PUBLIC_BASE_URL` sahi (payment links isi se bante hain)
- [ ] `DATABASE_URL` Postgres (SQLite sirf demo/single cafe)
- [ ] `AUTOMATION_ENABLED=true` aur `OWNER_REPORT_TIME` owner ki pasand ka
- [ ] Backup cron + uptime monitor (uptime kuma / healthchecks.io) → `/health` par
- [ ] `MAX_PROACTIVE_PER_DAY` owner ke message budget ke hisaab se (Meta fees!)
- [ ] Logs me token/keys kahin print nahi ho rahe (`grep -i token` logs par)

---

## Multi-restaurant (SaaS) banane ke liye

Ek hi code, har restaurant ke liye alag:
```bash
# restaurant A
PORT=8001 DATABASE_URL="sqlite:///./data/cafe_a.db" RESTAURANT_NAME="Cafe A" \
  uvicorn app.main:app --port 8001
```
Ya Docker me per-customer container + alag `.env`. Dashboard ka `/api/*` same rehta hai,
isliye ek central admin panel bana ke saare restaurants ke `/api/summary` pull kar sakte ho.
