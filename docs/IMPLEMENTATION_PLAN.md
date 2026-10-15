# IMPLEMENTATION PLAN — remaining work

Date: 2026-10-15 · Branch: `arena/dd5271e6-emigrant-repo` (base `main@e1aef9d`)

Ordering: P0 = blocks safe production use · P1 = needed for the SaaS target · P2 = hardening / polish.
Each item lists the verification that must exist before its status can change to WORKING_VERIFIED.

## Done in this pass (for reference)

- Fail-closed WhatsApp and Razorpay signatures; constant-time compares; log redaction.
- Webhook dedupe (`processed_events`) inside the processing transaction.
- Decimal billing with paise rounding; qty validation; coupon single-use / phone-bound / expiry / cancel-release.
- Reservation capacity module (overlap-aware), validation, Postgres advisory lock (code only on Postgres).
- Order numbers from primary key; `on_payment_success` no longer regresses kitchen status.
- Coupon codes via `secrets`; thanks code tail 6 characters.
- Reminder bug (bookings hours in the past): fixed and tested.
- Alembic baseline + `0002_audit_events`; `create_all` disabled in production.
- Docker: non-root, `/ready` healthcheck, `alembic upgrade head` before serve, no hardcoded DB password.
- Dashboard: token from header only; broadcast opt-in with confirm.
- Ruff F401/F811 cleanup.

## Done in this pass (bug-fix + verify)

Found by running the product, not by reading it (see `docs/FEATURE_STATUS.md` → *Bug fixes verified
in this pass*). Each was reproduced on the base commit before being fixed, so every regression test
is proven to fail without the fix.

- **B-1** pending order tracking: `pay` / `bill` now find the unpaid order (COD-only bug) — with a
  DB-backed fallback that ignores cancelled orders.
- **B-2 / B-3** bills rebuilt from `order.items` dropped the discount, so customers were shown a
  *higher* total than they were charged (`₹798` instead of `₹718.20`), including after paying.
  Fixed with `pricing.bill_from_order()` + new `orders.discount_percent` / `orders.gst_percent`
  columns (migration `0003_order_bill_rates`, non-destructive, back-filling, reversible).
- **B-4** `PUT /api/settings` wrote to a table nothing read. Now a validated override map
  (`settings.apply_overrides`) applies on save and reloads from the DB at startup.
- Dev databases gain new columns automatically instead of crashing (`add_missing_columns`);
  production schema stays migration-only.
- **P0-2 concurrency tests** (`tests/test_concurrency.py`, 8 tests): parallel order numbers,
  parallel coupon redeem, parallel duplicate webhooks, parallel payment settle.
- Test suite: 61 → 86 tests. `scripts/bug_hunt.py` and `scripts/smoke_api.py` added as repeatable
  live verification.

## P0 — required before any real customer data

| # | Item | Why | Verification required | Owner/Blocker |
|---|---|---|---|---|
| P0-1 | Run the suite and `alembic upgrade head` against **PostgreSQL 16** | Advisory lock, row updates, and migrations are only SQLite-tested | Test run on Postgres: migrations, reservation lock, coupon race, payment webhook race | Needs Postgres (not in sandbox) — BLOCKED_EXTERNAL_SETUP |
| P0-2 | Concurrency tests (threads or two processes): parallel orders (order_no), parallel coupon redeem, parallel duplicate webhooks | Claims of race-safety were code-reviewed only | Tests that fail on the old code and pass on the new | **DONE (tests written, 8 tests).** Still needs a run on PostgreSQL for real evidence: `TEST_DATABASE_URL=postgresql+psycopg://… pytest tests/test_concurrency.py` |
| P0-3 | Build the Docker image and run `docker compose up` with a real `.env` | Dockerfile/compose changed but not built | `docker build` succeeds; `/ready` 200 inside the container; container runs as uid 10001 | Needs Docker — BLOCKED_EXTERNAL_SETUP |
| P0-4 | Rotate `ADMIN_TOKEN` values that were ever put in a URL; purge old access logs | S-08 | Owner action + check | Owner action |
| P0-5 | Live WhatsApp round trip: verify, inbound signed message, outbound send, delivery status, and a provider rejection shown as "not sent" | Honest send status is unverified against Meta | Real Meta test number; logs show message id | Needs Meta credentials — BLOCKED_EXTERNAL_SETUP |
| P0-6 | Live Razorpay: create link, pay in test mode, receive signed webhook, duplicate delivery, amount mismatch | Payment integrity verified only with fixtures | Razorpay test keys; real webhook delivery | Needs Razorpay test account — BLOCKED_EXTERNAL_SETUP |

## P1 — SaaS target

| # | Item | Notes | Verification |
|---|---|---|---|
| P1-1 | **Tenant model**: `restaurants` table; `restaurant_id` on every tenant-owned table (customers, orders, payments, menu, coupons, reservations, messages, audit, settings); migrate existing rows to a default restaurant (no deletes) | Currently one deployment = one restaurant (grep finds 0 `restaurant_id`) | Migration test on existing data; cross-tenant access tests returning 404 |
| P1-2 | **Per-restaurant GST and tax settings** in the tenant table (rate as Decimal, validated 0–28) | Replace `GST_PERCENT` global with per-restaurant value; keep env as the default only | Pricing tests for two restaurants with different rates |
| P1-3 | **RBAC**: `users` table with password hashing (argon2/bcrypt) or SSO; roles owner / manager / staff / read-only; server checks per route | Today: one shared admin token | Route-level tests: each role allowed/denied per route |
| P1-4 | **Server-side tenant from session**, never from request body | Depends on P1-1 and P1-3 | Tests: body `restaurant_id` ignored / rejected |
| P1-5 | **Discount rule semantics**: decide whether `nth_order` means "exactly the N-th order" or "from N onward" | Current behaviour: order number ≥ N fires every time | **Product decision** (see below); then test |
| P1-6 | Reservation chat path: use overlap-aware capacity (currently exact-time match); move `MAX_SEATS_PER_SLOT` into per-restaurant config | Double-booking risk in chat path | Tests for overlapping slots; Postgres lock test (P0-1) |
| P1-7 | Automations consent: run tests for winback, birthday, owner report, broadcast with opt-in / opted-out / blocked customers | Partially covered | Tests per rule; a non-consented customer receives nothing |
| P1-8 | ~~Persist `PUT /api/settings` (DB-backed per tenant) instead of process-global mutation~~ | Settings were lost on restart | Test: value survives restart | **Partially done:** overrides now apply immediately and reload from the DB on startup (restart-safe, validated, per-deployment). Per-tenant part still needs P1-1. |
| P1-9 | LLM hardening: delimit customer text, strip control sequences, length cap, output schema validation; AI never sets price/discount/items (already enforced server-side — keep and test) | S-22 | Tests with injection strings: no price change, no unknown item, no DB/shell action |
| P1-10 | Rate limiting on `/webhook`, `/api/*` auth failures, and the Razorpay endpoint | S-23 | Test with burst requests gets 429 |
| P1-11 | Dashboard browser test (Playwright or similar): token flow, order status buttons, broadcast confirm, 401 handling | Dashboard is PARTIAL | Browser test run recorded in repo |
| P1-12 | Structured audit viewer + coverage review of every write route | S-18 partial | Test: each write route creates an audit row |

## P2 — hardening and polish

- CSP header and dashboard XSS review (S-14).
- Remove host port publish of the app in production profile; keep Postgres container-internal (already).
- Replace `datetime.utcnow`-style deprecations and the Starlette httpx warning (third-party) when upgrading.
- Full ruff rule set (currently F/E9 only; 2 unused-variable warnings were fixed; check E/W rules).
- Owner guide (`docs/OWNER-GUIDE.md`) for non-technical staff — currently only a demo script exists.
- Load test of webhook path (only with authorization and on a staging environment).
- Backup/restore runbook with a tested restore on Postgres.

## Product decisions needed from the owner

1. **`nth_order` discount:** Should "3rd order — 15% OFF" apply only to the 3rd order, or to every order from the 3rd onward? (Current: from the 3rd onward.)
2. **Per-restaurant GST:** Is a single GST rate per restaurant enough, or do you need item-level GST slabs (for example 5% vs 18%)?
3. **Tenancy model:** Confirm whether each restaurant gets its own WhatsApp number and its own Razorpay account (recommended), or whether one platform account serves many restaurants.
4. **Broadcast policy:** Keep "opt-in only" as the only marketing path (current), or allow transactional-only messages for customers without opt-in?

## Next task (recommended)

**P0-1 — run the existing suite against PostgreSQL 16.** It is now the single dependency blocking
real evidence for the concurrency work:

```bash
createdb agent_test
TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/agent_test \
  python -m pytest -q          # 86 tests, including migrations + concurrency
alembic upgrade head           # against a Postgres DATABASE_URL
```

This also unblocks P0-3 (Docker build) and P1-6 (Postgres advisory lock for reservations).

Then **P1-1 (tenant model)**: the SaaS blocker, and it changes the schema — so it must be a
non-destructive Alembic migration with a test on existing data, using the same pattern as
`0003_order_bill_rates` (add columns → back-fill → drop server default).

The four product decisions above should be answered before P1-1, so the migration encodes the
decisions instead of guessing them.
