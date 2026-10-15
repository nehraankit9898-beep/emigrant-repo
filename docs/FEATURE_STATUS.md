# FEATURE STATUS — Sharma Cafe WhatsApp AI Agent

Date: 2026-10-15 · Branch: `arena/962345dc-emigrant-repo`

## Status definitions

| Status | Meaning |
|---|---|
| **WORKING_VERIFIED** | Ran it (automated test and/or live local HTTP/CLI run) and observed the expected result |
| **PARTIAL** | Some behaviour verified; known gaps or parts only code-reviewed |
| **BROKEN** | Known defect (reproduced or clearly shown in code) |
| **MOCK_ONLY** | Works only with the demo/mock provider; no live path verified |
| **NOT_IMPLEMENTED** | Required by the target but absent |
| **BLOCKED_EXTERNAL_SETUP** | Needs credentials, accounts, or tooling not available in this sandbox |

"Code review only" is not a verification. Nothing below is marked WORKING_VERIFIED on reading alone.

## Feature table

| # | Feature | Status | Evidence / basis | Gap |
|---|---|---|---|---|
| 1 | WhatsApp webhook receive (signed) | **WORKING_VERIFIED** (mock/local) | `test_security_regression` (unsigned/forged rejected); `test_flow` webhook tests; manual M-06/M-07 | Live Meta delivery not tested |
| 2 | WhatsApp webhook verify handshake | **WORKING_VERIFIED** | manual M-06 (403 wrong token), M-07 (challenge echoed) | — |
| 3 | WhatsApp outbound send, honest result | **PARTIAL** | Mock sends exercised in tests; code returns provider result | Provider rejection → "not sent" path not run against Meta |
| 4 | WhatsApp live (Cloud API) | **BLOCKED_EXTERNAL_SETUP** | Needs `WHATSAPP_TOKEN`, phone number ID, approved templates | Account setup by owner |
| 5 | Inbound dedupe (WhatsApp message id) | **WORKING_VERIFIED** (sequential) | `test_flow` idempotency tests; claim in same transaction | Concurrent duplicate on Postgres not run |
| 6 | Menu browse / text ordering (demo brain) | **WORKING_VERIFIED** | `test_flow` (26 tests), `scripts.demo_chat` run, manual M-09 | Demo brain is rule-based, not LLM |
| 7 | Kitchen flow (confirm → preparing → ready → delivered) | **WORKING_VERIFIED** | `test_flow` `walk_to_delivered` helper; transition validation | Dashboard buttons not browser-tested |
| 8 | Unknown order status update | **PARTIAL** | Code returns 400 before transition check; no dedicated test found | Add a route test |
| 9 | Order numbering | **PARTIAL** | Now `1000 + primary key` (sequence-backed, no reuse); used across test suite | Concurrent creation on Postgres not run |
| 10 | Bill engine (Decimal, paise rounding) | **WORKING_VERIFIED** | `test_pricing` (9): exact 3×33.33, 15% off, 5% GST → 89.24; rounding 0.285→0.29; qty 0 rejected | — |
| 11 | Discount cap (25%) and non-negative total | **WORKING_VERIFIED** | `test_pricing` | — |
| 12 | Freebies excluded from subtotal | **WORKING_VERIFIED** | `test_pricing` | — |
| 13 | Per-restaurant GST | **NOT_IMPLEMENTED** | No tenant model. GST is one per deployment (`GST_PERCENT`, default 5.0, Decimal math) | Needs restaurant table + per-tenant tax setting |
| 14 | Universal GST hardcoding | **PARTIAL** | Default `5.0` in `config.py` is a default, overridable by env | Remove default for SaaS use |
| 15 | Discount rules (`nth_order`) | **PARTIAL** | Rules fire; behaviour is "order number ≥ N", not "exactly the N-th" | **Product decision needed** (see plan) |
| 16 | Coupon issue / single use | **PARTIAL** | `test_coupons` (5): single use, phone-bound, expiry, cancel releases, double redeem loses | Race-safety verified only in one process (SQLite) |
| 17 | Coupon codes unpredictable | **PARTIAL** | Code uses `secrets.choice` (code review only); thanks tail 6 chars | Not tested by running |
| 18 | Razorpay payment link creation (live) | **BLOCKED_EXTERNAL_SETUP** | Needs `RAZORPAY_KEY_ID`/`SECRET` | — |
| 19 | Razorpay webhook (signed, fail-closed) | **PARTIAL** | Regression tests with fixture secret: unsigned/forged rejected, duplicate skipped | Live Razorpay events not received |
| 20 | Payment marked paid only by verified signal | **WORKING_VERIFIED** | `settle_payment` only path; regression tests; browser cannot set paid | — |
| 21 | Amount reconciliation (paise) | **WORKING_VERIFIED** | regression test: mismatch not marked paid, audit entry written | — |
| 22 | Demo / mock payment (simulate) | **MOCK_ONLY** | `demo_chat` run; `/api/simulate` manual M-09; blocked when live | Labelled as demo in dashboard |
| 23 | `on_payment_success` idempotent for kitchen status | **WORKING_VERIFIED** (after fix) | `test_late_payment_success_does_not_regress_kitchen_status` | — |
| 24 | Reservations (chat + dashboard) | **PARTIAL** | `test_flow` reservation tests pass; capacity/overlap module + validation tested via flow | Chat path still uses exact-time matching; `MAX_SEATS_PER_SLOT = 24` constant still in orchestrator; Postgres advisory lock not run |
| 25 | Feedback / complaints with human handover | **WORKING_VERIFIED** | `test_flow` feedback, complaint, handover tests | Human-agent UI workflow is minimal |
| 26 | Automations: reservation reminders | **PARTIAL** | Window bug fixed; `test_pricing` `test_reservation_reminder_only_inside_window` | Scheduler not run as a daemon here |
| 27 | Automations: winback / birthday | **PARTIAL** | flow tests exist; consent rule (opt-in) covered by regression tests | Not fully verified end-to-end |
| 28 | Owner daily report | **PARTIAL** | code present (`send_owner_report_if_due`) | Not run in tests |
| 29 | Broadcast / marketing consent | **PARTIAL** | API requires opt-in; dashboard "send to all" removed; regression test | Dashboard confirm dialog not browser-tested |
| 30 | CRM (customers, visits, spend, loyalty) | **PARTIAL** | `memory.py` updates via order tests; customer fields present | No CRM search/export UI verified |
| 31 | Dashboard on real APIs | **PARTIAL** | Endpoints verified via HTTP (M-01..M-09); JS syntax checked | No browser test of UI flows |
| 32 | Dashboard token flow (sessionStorage, header only) | **PARTIAL** | Code review + JS syntax check; M-02 confirms URL token rejected | Not clicked through in a browser |
| 33 | Admin authentication (shared token) | **WORKING_VERIFIED** | M-01..M-04; constant-time compare; production fail-closed | — |
| 34 | RBAC (owner / staff / read-only) | **NOT_IMPLEMENTED** | Only one token | Requires user model + roles |
| 35 | Tenant isolation (`restaurant_id`) | **NOT_IMPLEMENTED** | No `restaurant_id` in models (grep = 0) | Multi-restaurant SaaS not built |
| 36 | Audit logs | **PARTIAL** | `audit_logs` table (migration verified); writes in admin, demo, payment-mismatch paths | Coverage not exhaustive; no viewer UI |
| 37 | Log redaction (phones, tokens) | **WORKING_VERIFIED** | `test_log_redaction_masks_tokens_and_phones`; uvicorn access log filter | — |
| 38 | Production startup refuses unsafe config | **WORKING_VERIFIED** | Ran with `APP_ENV=production` + defaults → RuntimeError | — |
| 39 | Health / readiness endpoints | **WORKING_VERIFIED** | `/health` 200, `/ready` 200 `config_ok: true` (manual) | — |
| 40 | Schema migrations (Alembic) | **WORKING_VERIFIED** (SQLite) | `test_migrations` (2) + manual: fresh head (16 tables), legacy data preserved, downgrade/upgrade | PostgreSQL not run |
| 41 | Production DB (PostgreSQL) | **BLOCKED_EXTERNAL_SETUP** | No Postgres/psql in sandbox | Run `alembic upgrade head` + concurrency tests on a real Postgres |
| 42 | Docker image build and run | **BLOCKED_EXTERNAL_SETUP** | No Docker in sandbox; Dockerfile file set checked by simulation | Build and run in CI or locally |
| 43 | Docker compose secrets | **PARTIAL** | Code review: no hardcoded password; `${POSTGRES_PASSWORD:?}` required | Not `docker compose config`-validated (no Docker) |
| 44 | CI (GitHub Actions) | **PARTIAL** | workflow runs pytest + compileall + demo smoke; `APP_ENV=development` | CI run not observed from this sandbox |
| 45 | LLM (live provider) | **BLOCKED_EXTERNAL_SETUP** | Needs API key | — |
| 46 | LLM prompt isolation against injection | **PARTIAL** | Server recomputes prices and validates items; no prompt sandboxing | Customer text is not delimited/isolated in prompt |
| 47 | LLM fallback to demo brain | **WORKING_VERIFIED** | demo flows run | — |
| 48 | Settings API (`PUT /api/settings`) | **PARTIAL** | Requires admin | Mutates process-global settings; not persisted; not per-tenant |
| 49 | Rate limiting | **NOT_IMPLEMENTED** | none | Add at proxy or middleware |
| 50 | Outbox / demo WhatsApp payload views | **MOCK_ONLY** | admin-gated | Demo-only data views |
| 51 | Owner / user documentation | **PARTIAL** | `docs/OWNER-DEMO-SCRIPT.md`, `docs/API-SETUP-GUIDE.md` (existing) | Setup guide not re-verified line by line |

## Summary counts (computed from the table above)

- Total rows: 51
- WORKING_VERIFIED: 18  (row 40 is SQLite-only)
- PARTIAL: 22
- MOCK_ONLY: 2
- NOT_IMPLEMENTED: 4  (per-restaurant GST, RBAC, tenant isolation, rate limiting)
- BLOCKED_EXTERNAL_SETUP: 5  (WhatsApp live, Razorpay live, PostgreSQL, Docker, live LLM)
- BROKEN: 0 known after this pass. Baseline defects are listed in PROJECT_AUDIT §3 and their fixes in §4.
