# PROJECT AUDIT — Sharma Cafe WhatsApp AI Agent

Date: 2026-10-15 · Branch: `arena/dd5271e6-emigrant-repo` (base `main@e1aef9d`)

> **Second pass (this branch).** The previous audit reviewed the code; this pass **ran the product**
> and found four defects that passed all 61 existing tests. They are listed in §7 with their
> reproduction and fix. Test suite is now 86.

## 1. Scope and method

This audit covers the existing repository (FastAPI + SQLAlchemy, HTML/JS dashboard, SQLite/PostgreSQL,
WhatsApp Cloud API, optional LLM, Razorpay, Docker). The project was **hardened in place**, not replaced.

Evidence is reported in three separate categories. Nothing here is a penetration test.

| Category | What was done | Result |
|---|---|---|
| **Code review** | Read models, routes, payments, WhatsApp, orchestrator, pricing, discounts, automations, dashboard, Docker/CI, config | Findings listed in `SECURITY_AUDIT.md` and `FEATURE_STATUS.md` |
| **Automated tests** | `pytest` (61 tests), `ruff` (F/E9 rules), `compileall`, demo-chat smoke script, Alembic migration tests, JS syntax check of dashboard | 61 passed; ruff clean; see §5 |
| **Manual HTTP checks** | Live `uvicorn` process on `0.0.0.0:8000` in demo mode, requests with curl | Auth, webhook verify, order creation behaved as expected; see `SECURITY_AUDIT.md` §4 |

Not done: browser testing of the dashboard, Docker image build, PostgreSQL runtime tests, live Meta/Razorpay
calls, load/concurrency tests, and any intrusive testing. The sandbox has no Docker, `psql`, or Postgres.

## 2. Architecture (as found, with changes)

| Module | Role | State after this work |
|---|---|---|
| `app/main.py` | FastAPI app, webhooks (`/webhook`, `/webhook/razorpay`), mock payment pages, `/health`, `/ready` | Webhook dedupe in the same transaction, fail-closed signatures, production startup check, JSON logs in production |
| `app/api.py` | Dashboard REST API (`/api/*`) | `require_admin` header-only gate, audited writes, transition validation, reservation wiring, demo endpoints guarded |
| `app/orchestrator.py` | "Brain": intent → menu/bill/discount/reservation/feedback → reply → DB | Coupon claim/redeem/attach/release wired in; order numbers from DB primary key |
| `app/pricing.py`, `app/utils.py` | Bill engine, money | Decimal end to end, rounding to paise (`ROUND_HALF_UP`), coupon helpers |
| `app/discounts.py` | Discount rules, coupon issue/mark-used | `secrets`-based codes, longer thanks-coupon tail |
| `app/payments.py` | Razorpay links, webhook signature, `settle_payment` | Fail-closed HMAC, amount reconciliation, no mock fallback when live |
| `app/whatsapp.py` | Cloud API send/receive | Fail-closed `X-Hub-Signature-256`, constant-time verify token, status payloads detected, honest send results |
| `app/reservations.py` | Reservation capacity | New: overlap-aware capacity, date/time/party-size validation, Postgres advisory lock |
| `app/security.py` | Shared security helpers | New: constant-time compare, redaction, audit writer, event claim (idempotency) |
| `app/logging_setup.py` | Logging | New: redacts phone numbers, token/secret query params, bearer tokens |
| `app/automations.py` | Scheduled reminders, winback, birthday, owner report | Reminder window bug fixed; consent path not yet verified by running |
| `app/llm.py` | Optional LLM with demo fallback | Unchanged in this pass; customer text isolation still open |
| `app/static/dashboard.html` | Single-page dashboard | Token in `sessionStorage` + header only; broadcast opt-in only with confirm |
| `migrations/` | Alembic | New: baseline from original schema + audit/idempotency tables |
| `Dockerfile`, `docker-compose.yml`, CI | Packaging | Non-root user, `/ready` healthcheck, migrate-then-serve, no hardcoded DB password |

## 3. Baseline findings (before this work)

Ordered by severity. Each is addressed in `SECURITY_AUDIT.md` (status column) or `IMPLEMENTATION_PLAN.md`.

1. Webhook signature verification was optional (unsigned requests accepted when the secret was unset).
2. Razorpay webhook could mark an order paid without verified signature / amount check.
3. Dashboard token could be passed in the URL (`?token=`), which is written to access logs.
4. Admin API had no server-side authorization model beyond an optional header; no roles.
5. Webhook replays were not deduplicated, so a duplicate delivery could re-run payment or message side effects.
6. Money used `float` in the bill path (rounding drift, e.g. 3 × 33.33).
7. Coupons had no atomic redemption (double use possible under concurrent requests).
8. Order numbers were computed from a row count (collision under concurrency).
9. Schema changes were `create_all` only (no migrations; risk of data loss on upgrade).
10. Docker: ran as root; healthcheck on `/health`; `docker-compose.yml` contained a hardcoded Postgres password.
11. Dockerfile did not copy migration files (fixed in this pass, see §4).
12. Reservation reminders were sent for bookings hours in the past (fixed).
13. Quantity `0` silently became `1` in ordering (fixed).
14. Broadcast had a "send to all" path that ignored opt-in (removed from dashboard; API requires opt-in).

## 4. Changes made (summary)

- **Security/payments:** fail-closed signatures (WhatsApp and Razorpay), constant-time comparisons, webhook
  event dedupe (`processed_events`), Razorpay amount reconciliation, mock-payment endpoints blocked when live,
  audit trail (`audit_logs`), log redaction, production startup refusal on unsafe config, `/ready` endpoint.
- **Money:** Decimal end to end; `q2`/`money` rounding helpers; exact bill math verified by tests; qty validation.
- **Coupons:** atomic single-use claim, bound to phone, expiry, release on cancel, double-redeem test.
- **Reservations:** overlap-aware capacity, validation of date/time/persons, advisory lock on Postgres.
- **Orders:** transition validation, unknown status → 400, order number from primary key.
- **Data:** Alembic baseline (`0001_baseline`) generated from the original schema; `0002_audit_events` adds two
  tables; `init_db()` no longer calls `create_all` in production.
- **Packaging:** non-root container, migrate-before-serve command, no hardcoded DB password, `POSTGRES_PASSWORD`
  required by compose.
- **Dashboard:** token moved out of URL; broadcast restricted to opt-in with confirmation; demo-only buttons labelled.
- **Lint:** removed 17 unused imports and one redefinition (ruff F401/F811); fixed the reminder logic bug.

## 5. Test results (this pass)

Commands run in `/home/user/emigrant-repo` with `.venv` (Python 3.11):

```
.venv/bin/python -m pytest -q        → 61 passed, 1 warning (Starlette httpx deprecation, third-party)
.venv/bin/ruff check app tests scripts migrations --select F,E9   → All checks passed!
node --check (extracted dashboard <script>)                        → OK
```

Per file: `test_flow.py` 26, `test_security_regression.py` 19, `test_pricing.py` 9, `test_coupons.py` 5,
`test_migrations.py` 2.

Also run:
- `scripts/demo_chat` against a temp SQLite DB: clean output, order created, payment flow executed.
- Live `uvicorn app.main:app` (demo env): endpoints in `SECURITY_AUDIT.md` §4 returned the expected codes.
- Alembic: fresh `upgrade head` (16 tables), existing-data upgrade preserving a customer row, downgrade/upgrade round trip.
- Image-equivalent migration: copied the files the Dockerfile copies into a clean directory and ran
  `alembic upgrade head` there (16 tables created).

Not run: Docker build, Postgres migration/concurrency tests, browser tests, live provider tests.

## 7. Second pass — defects found by running the product

The first pass reviewed code; this pass exercised the running app (scripted walkthroughs of the
real HTTP API plus targeted probes of every money path) and found four defects that **all 61
existing tests passed straight through**. Each was reproduced on the base commit in a `git worktree`
*before* being fixed, so the new tests are proven to fail without the fix.

| # | Defect | Observed on base commit | Fix |
|---|---|---|---|
| B-1 | Pending order not tracked (COD-only `active_order`) | `pay` → `Sir abhi koi pending bill nahi hai 🙏` while the order was unpaid | Track every order + DB fallback (`latest_unpaid_order`), cancelled excluded |
| B-2 | `bill` rebuilt without discount | `bill ₹798.0 vs asli ₹718.2` — also after payment | `pricing.bill_from_order()` + stored `discount_percent` / `gst_percent` |
| B-3 | `resend-link` same defect | `message ₹798.0 vs order ₹718.2` | route uses `bill_from_order` |
| B-4 | `PUT /api/settings` wrote to a read-never table | `GST apply nahi hua (abhi bhi 5.0)` | validated `settings.apply_overrides`, applied on save + reloaded at startup |

Underlying cause of B-2/B-3: `Order` stored the discount **amount** but not the **rate**, so a
rebuild could not reproduce the original bill. Migration `0003_order_bill_rates` adds
`orders.discount_percent` and `orders.gst_percent` — non-destructive, back-fills legacy rows,
reversible (round-trip verified), and it also means a historical bill keeps showing the rate that
was actually applied even after the config changes.

Migration `0003` was verified on: a fresh DB (18 tables), an existing DB with seeded legacy orders
(rates back-filled correctly, data preserved), and downgrade → upgrade round trip. Separately,
`app.database.add_missing_columns()` stops an existing **dev** database from crashing with
*"no such column"* after a schema change; production schema remains migration-only. Checked against
the 46 pre-existing demo orders — every one rebuilds to its exact stored total.

Commands used for verification:

```bash
.venv/bin/python -m pytest -q                    # 86 passed
.venv/bin/python scripts/smoke_api.py            # 53 routes, no 5xx
.venv/bin/python scripts/bug_hunt.py             # 5 checks, 0 failing
.venv/bin/ruff check app tests scripts migrations --select F,E9   # clean
python -m compileall -q app scripts tests        # clean
```

## 6. Remaining gaps (short list; detail in IMPLEMENTATION_PLAN.md)

- No multi-tenant model: one deployment = one restaurant. Multi-restaurant SaaS is NOT_IMPLEMENTED.
- No roles (owner / staff / read-only); a single shared admin token.
- Per-restaurant GST not implemented; GST is a per-deployment setting (now overridable at runtime
  from the Settings tab, but still one value per deployment).
- PostgreSQL path, concurrent order/coupon/webhook races: **tests now exist**
  (`tests/test_concurrency.py`, 8 tests) but have only been executed on SQLite. Run them with
  `TEST_DATABASE_URL` pointing at Postgres for real evidence.
- Automations consent rules: partially covered by tests; not fully verified.
- LLM prompt isolation: not implemented.
- Live WhatsApp and Razorpay: blocked by external credentials (not available in this sandbox).
