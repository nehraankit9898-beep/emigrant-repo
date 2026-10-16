# SECURITY AUDIT — Sharma Cafe WhatsApp AI Agent

Date: 2026-10-15 · Branch recorded by the earlier audit: `arena/962345dc-emigrant-repo`

> **Historical snapshot:** its branch/test counts describe a prior revision. See [REQUESTED_DEPLOYMENT_AUDIT.md](REQUESTED_DEPLOYMENT_AUDIT.md) for the current checkout and current verification results.

**Important:** this is a code review plus automated tests plus a small set of manual HTTP checks against a local
server. **No penetration test was performed.** No external system was tested. Findings marked *Open* are real gaps.

Status key: **Fixed** (code changed + test or manual check), **Mitigated** (reduced, residual risk stated),
**Open** (not fixed), **Accepted** (intentional, stated).

## 1. Findings and status

| ID | Area | Finding (baseline) | Status | Evidence |
|---|---|---|---|---|
| S-01 | WhatsApp webhook | Signature check skipped when secret unset | **Fixed** — fail-closed (`app/whatsapp.py`) | `test_security_regression.py` (unsigned/forged rejected) |
| S-02 | WhatsApp verify | Verify token compared with `==` | **Fixed** — constant-time (`security.constant_time_equals`) | regression tests |
| S-03 | Razorpay webhook | Accepted when secret unset; could mark paid | **Fixed** — fail-closed HMAC-SHA256, `compare_digest` (`app/payments.py`) | regression tests (unsigned webhook rejected) |
| S-04 | Payment state | Paid could be set by any path | **Fixed** — only `payments.settle_payment` (provider-verified) marks paid; conditional UPDATE | `test_payment_is_idempotent` + regression |
| S-05 | Payment amount | Provider amount not reconciled | **Fixed** — amount/currency compared in paise to order total | regression test |
| S-06 | Replay / duplicates | Duplicate WhatsApp/Razorpay deliveries re-processed | **Fixed** — `processed_events` unique key, claim in same transaction as processing | `test_flow` idempotency + regression |
| S-07 | Mock payments | Mock payment endpoints reachable in live mode | **Fixed** — blocked when live provider configured | regression tests |
| S-08 | Admin token in URL | `?token=` accepted and logged by uvicorn access log | **Fixed (going forward)** — header only; query token rejected (manual check M-03). **Action required:** tokens that were ever sent in a URL must be rotated, and old access logs purged | M-03 |
| S-09 | Admin authz | Optional header, no production enforcement | **Mitigated** — production with empty `ADMIN_TOKEN` returns 503 (fail-closed); constant-time compare | `test_security_regression`, M-01..M-04 |
| S-10 | Admin authz (roles) | Single shared token; no owner/staff/read-only roles | **Open** | — |
| S-11 | Tenant isolation | No `restaurant_id` in data model; one deployment = one tenant | **Open** (by design today; see IMPLEMENTATION_PLAN) | — |
| S-12 | Dev/demo default | With no `ADMIN_TOKEN` in development/demo, the API is open | **Accepted** (local demo only); production refuses to start with unsafe config | config tests, M-05 |
| S-13 | Production startup | Could start with default/insecure secrets | **Fixed** — `production_problems()` refuses start (RuntimeError) | startup check run |
| S-14 | Browser token | Token in URL/localStorage | **Mitigated** — `sessionStorage`, header only; still readable by any XSS. XSS review of the dashboard was **not** systematic, and no CSP header is set | code review |
| S-15 | Hardcoded secrets | `docker-compose.yml` had a Postgres password literal | **Fixed** — `${POSTGRES_PASSWORD:?...}` required | grep: no `change_me`/literal remains |
| S-16 | Container user | Ran as root | **Fixed** — `appuser` uid 10001 | Dockerfile (not built here — see §5) |
| S-17 | Logs | Phone numbers, tokens, bearer values in logs | **Fixed** — `RedactingFilter` on app + uvicorn access logs | `test_log_redaction_masks_tokens_and_phones` |
| S-18 | Audit trail | No record of admin writes | **Fixed** — `audit_logs` written for admin and demo actions | migration test (table present); audit calls in `api.py` |
| S-19 | Money integrity | `float` in bill path | **Fixed** — Decimal + paise | `test_pricing.py` (9) |
| S-20 | Coupon abuse | Double redemption under concurrency; codes predictable | **Mitigated** — atomic claim (single process verified); codes via `secrets`; thanks code tail 6 chars. Postgres concurrency **not run** | `test_coupons.py` (5) |
| S-21 | Consent / marketing | Broadcast ignored opt-in; winback/birthday rules | **Mitigated** — API broadcast requires opt-in; dashboard "send to all" removed. Automations consent not fully run-verified | regression tests (consent, broadcast) |
| S-22 | Prompt injection | Customer text placed unisolated into the LLM prompt; AI can't set prices, but is not sandboxed | **Open** (partial controls: server recomputes prices and validates items) | code review |
| S-23 | Rate limiting | No rate limit on webhook or admin endpoints | **Open** | — |
| S-24 | Outbox exposure | `/api/outbox` and `/api/demo/whatsapp-payload` show message content | **Mitigated** — admin-gated; not tenant-scoped (single tenant) | code review |
| S-25 | SQL / shell exec | AI must not execute SQL/shell | **Verified by review** — no `eval`/`exec`/`subprocess`/raw AI-driven SQL found in `app/` | grep review |
| S-26 | Container/network | Postgres not published to host (no `ports:` on `db`); compose header comment still says `localhost:5432` | **Fixed** (comment is stale; no port exposed) — correct comment in compose | code review |
| S-27 | `PUT /api/settings` | Mutates process-global settings (not persisted, not per-tenant) | **Open** | code review |

## 2. Authorization model (current)

- **Customer side:** WhatsApp webhook (signed) and Razorpay webhook (signed). No customer login exists.
- **Admin side:** `require_admin` dependency on every `/api/*` write/read route. Token only via
  `X-Admin-Token` or `Authorization: Bearer`. Constant-time compare.
- **Browser never decides:** restaurant id, role, user id, payment status, and prices come from the server.
  Payment status changes only from verified provider events (or the demo-only simulate endpoints, which are
  audited and disabled when a live provider is configured).

## 3. Automated tests relevant to security (run: 61 passed in full suite)

- `tests/test_security_regression.py` (19): route-level checks — unsigned/forged WhatsApp webhook rejected,
  verify-token mismatch 403, unsigned/forged Razorpay webhook rejected, duplicate webhook not reprocessed,
  amount mismatch not marked paid, mock endpoints blocked when live, admin routes need token, consent and
  broadcast opt-in, log redaction.
- `tests/test_coupons.py` (5): single use, bound to phone, expiry, release on cancel, second redeem loses.
- `tests/test_migrations.py` (2): existing customer data preserved across upgrade and downgrade/upgrade.

These are **automated functional/security regression tests**, not adversarial testing.

## 4. Manual HTTP checks (local uvicorn, demo env, ADMIN_TOKEN set)

Run against `http://127.0.0.1:8000` by the author; results observed:

| ID | Request | Expected | Observed |
|---|---|---|---|
| M-01 | `GET /api/summary` without token | 401 | 401 |
| M-02 | `GET /api/summary` with `?token=<valid>` | 401 (query not accepted) | 401 |
| M-03 | `GET /api/summary` with wrong header | 401 | 401 |
| M-04 | `GET /api/summary` with `X-Admin-Token: <valid>` | 200 | 200 |
| M-05 | `GET /health`, `GET /ready` | 200 (public, no secrets) | 200, `{"status":"ready","config_ok":true}` |
| M-06 | `GET /webhook` with wrong verify token | 403 | 403 |
| M-07 | `GET /webhook` with correct verify token | echo challenge | 200, challenge echoed |
| M-08 | `POST /webhook/razorpay` unsigned in demo (no live secret) | handled per demo mode | 200 (demo mode accepts; no live payment is claimed) |
| M-09 | `POST /api/simulate` with token | order flow runs; bill computed by server | 200; correct 10% WELCOME10 discount and 5% GST |
| M-10 | Production with default config | refuses to start | RuntimeError (run earlier in this pass) |

Note M-08: in production with a live secret configured, unsigned Razorpay requests are rejected (regression test).
Live provider behaviour was not exercised.

**Access log finding (S-08):** the uvicorn access log of the pre-fix server recorded
`GET /api/summary?token=<value>`. Rotate any `ADMIN_TOKEN` that was used in a URL and purge those logs.

## 5. What was NOT verified

- No penetration test, fuzzing, or load test.
- No browser test of the dashboard (token flow and confirm dialogs are code-reviewed and JS-syntax-checked only).
- Docker image not built (no Docker in sandbox). Dockerfile changes were checked by copying the same files
  to a clean directory and running the migrate step there.
- PostgreSQL not run (advisory lock, row locks, concurrent webhooks and coupons are code-reviewed only).
- Live Meta WhatsApp and live Razorpay not called (no credentials; no authorization for external testing).

## 6. Secure configuration checklist

- `APP_ENV=production`; startup refuses otherwise-unsafe configs.
- `ADMIN_TOKEN` ≥ 32 random chars (`python -c "import secrets;print(secrets.token_urlsafe(32))"`).
- `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN`, `RAZORPAY_WEBHOOK_SECRET` set.
- `POSTGRES_PASSWORD` random; do not publish the Postgres port in production.
- Run an approved `alembic upgrade head` as a separate, reviewed release step before traffic; the current container no longer runs migrations at startup. Verify the existing schema/version first.
- Terminate TLS at a reverse proxy; set `FORWARDED_ALLOW_IPS` to the proxy address only.
- Keep `.env` out of Git (`.gitignore` and `.dockerignore` already exclude it).
