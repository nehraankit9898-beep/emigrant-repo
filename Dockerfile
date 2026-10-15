# Sharma Cafe WhatsApp AI Agent — production image
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /app

# pehle requirements (docker layer cache ke liye)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY tests ./tests
COPY n8n ./n8n
COPY docs ./docs
COPY alembic.ini ./
COPY migrations ./migrations

# SQLite file ke liye folder (demo me kaam aata hai; production me Postgres behtar hai)
RUN useradd --create-home --uid 10001 appuser \
 && mkdir -p /app/data \
 && chown -R appuser:appuser /app/data

# root ke bajaye non-root user se chalao (security)
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/ready')" || exit 1

# --proxy-headers: reverse proxy (HTTPS) ke peeche chalaane ke liye; FORWARDED_ALLOW_IPS env se restrict karo
# Pehle schema migrate (production me create_all nahi chalta), phir server. Data kabhi reset nahi hota.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips=${FORWARDED_ALLOW_IPS:-127.0.0.1}"]
