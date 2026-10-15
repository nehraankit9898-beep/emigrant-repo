# FEATURE STATUS — Sharma Cafe WhatsApp AI Agent

Date: 2026-10-15 · Branch: `arena/dd5271e6-emigrant-repo` (base `main@e1aef9d`)

> **Update (this pass):** four defects found by live end-to-end testing are fixed and covered by
> regression tests — see [Bug fixes verified in this pass](#bug-fixes-verified-in-this-pass) at the
> bottom. Concurrency claims (P0-2) now have tests instead of code review only.

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
| 5 | Inbound dedupe (WhatsApp message id) | **WORKING_VERIFIED** (sequential + threads) | `test_flow` idempotency tests + `test_concurrency`: 12 threads claim one event → 1 winner; claim in same transaction | Concurrent duplicate on Postgres not run |
| 6 | Menu browse / text ordering (demo brain) | **WORKING_VERIFIED** | `test_flow` (26 tests), `scripts.demo_chat` run, manual M-09 | Demo brain is rule-based, not LLM |
| 7 | Kitchen flow (confirm → preparing → ready → delivered) | **WORKING_VERIFIED** | `test_flow` `walk_to_delivered` helper; transition validation | Dashboard buttons not browser-tested |
| 8 | Unknown order status update | **PARTIAL** | Code returns 400 before transition check; no dedicated test found | Add a route test |
| 9 | Order numbering | **WORKING_VERIFIED** | `1000 + primary key` (sequence-backed, no reuse); `test_concurrency`: 12 parallel orders → 12 unique numbers, no collision with existing rows | Concurrent run on Postgres still not executed (SQLite only here) |
| 10 | Bill engine (Decimal, paise rounding) | **WORKING_VERIFIED** | `test_pricing` (9): exact 3×33.33, 15% off, 5% GST → 89.24; rounding 0.285→0.29; qty 0 rejected | — |
| 11 | Discount cap (25%) and non-negative total | **WORKING_VERIFIED** | `test_pricing` | — |
| 12 | Freebies excluded from subtotal | **WORKING_VERIFIED** | `test_pricing` | — |
| 13 | Per-restaurant GST | **NOT_IMPLEMENTED** | No tenant model. GST is one per deployment (`GST_PERCENT`, default 5.0, Decimal math) | Needs restaurant table + per-tenant tax setting |
| 14 | Universal GST hardcoding | **PARTIAL** | Default `5.0` in `config.py` is a default, overridable by env | Remove default for SaaS use |
| 15 | Discount rules (`nth_order`) | **PARTIAL** | Rules fire; behaviour is "order number ≥ N", not "exactly the N-th" | **Product decision needed** (see plan) |
| 16 | Coupon issue / single use | **WORKING_VERIFIED** | `test_coupons` (5) + `test_concurrency`: 12 threads race to redeem one coupon → exactly 1 winner | Concurrent run on Postgres not executed |
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
| 48 | Settings API (`PUT /api/settings`) | **WORKING_VERIFIED** | `test_billing_regressions`: saved overrides apply immediately (`gst_percent` 5→18 shows in the next bill), reload from DB on restart, invalid values rejected (`rejected` in response, nothing changes), over-long text rejected (200-char cap) | Still per-deployment (not per-tenant); `templates` section stored but unused |
| 49 | Rate limiting | **NOT_IMPLEMENTED** | none | Add at proxy or middleware |
| 50 | Outbox / demo WhatsApp payload views | **MOCK_ONLY** | admin-gated | Demo-only data views |
| 51 | Owner / user documentation | **PARTIAL** | `docs/OWNER-DEMO-SCRIPT.md`, `docs/API-SETUP-GUIDE.md` (existing) | Setup guide not re-verified line by line |

## Bug fixes verified in this pass

Found by running the app (not by reading it): a scripted walkthrough of the real HTTP API plus
targeted probes of every money path. Each defect was first **reproduced on the unfixed code**
(`git worktree` at the base commit) and then shown passing after the fix, so the tests are known
to catch the bug rather than merely describing current behaviour.

| # | Defect | Impact | Reproduction (before fix) | Fix | Test |
|---|---|---|---|---|---|
| B-1 | Pending order was not tracked — `flow_state["active_order"]` was set **only** for COD orders | Customer who asks for the payment link again gets *"Sir abhi koi pending bill nahi hai"* while the order is still unpaid; `order status` said *"link bhejun phir se?"* and `pay` then refused — contradictory | `pay` reply: `Sir abhi koi pending bill nahi hai 🙏` | Set `active_order` for every order, plus a DB fallback (`latest_unpaid_order`) that ignores cancelled orders | `test_pending_order_is_tracked_after_order`, `test_pay_returns_link_for_unpaid_order`, `test_latest_unpaid_order_ignores_cancelled`, `test_pay_after_payment_says_nothing_pending` |
| B-2 | `bill` rebuilt the bill from `order.items` **without the discount** | Customer is shown a **higher** total than they were charged — after paying ₹718.20 the agent still said *"Total: ₹798"* | `bill ₹798.0 vs asli ₹718.2` | `pricing.bill_from_order()` rebuilds using the rates stored on the order | `test_bill_after_payment_matches_original_total`, `test_bill_from_order_reproduces_stored_total`, `test_bill_from_order_keeps_freebies` |
| B-3 | `/api/orders/{no}/resend-link` had the same defect | The link charges ₹718.20 but the message quotes ₹798 | `message ₹798.0 vs order ₹718.2` | Route uses `bill_from_order` | `test_resend_link_quotes_order_total` |
| B-4 | `PUT /api/settings` wrote to a table **nothing read** | Settings tab silently did nothing for GST / restaurant fields — *"saved"* was returned, the next bill was unchanged | `GST apply nahi hua (abhi bhi 5.0)` | Validated override map (`settings.apply_overrides`) applied on save **and** reloaded from DB at startup | `test_settings_put_applies_gst_to_next_bill`, `test_settings_are_read_back_from_db`, `test_settings_override_rejects_*` |

Root cause of B-2/B-3: `Order` stored the discount **amount** but not the **rate**, so a rebuild
could not reproduce the original bill. Two new columns (`discount_percent`, `gst_percent`) plus
migration `0003_order_bill_rates` now store the applied rates — which also means a historical bill
keeps showing the rate that was actually used, even after config changes
(`test_bill_from_order_ignores_later_config_change`).

Migration notes: `0003` is non-destructive and idempotent, back-fills legacy rows from
`discount_amount / subtotal` and `gst_amount / taxable`, and round-trips on downgrade/upgrade.
`app.database.add_missing_columns()` additionally lets an existing **dev** database gain new
columns instead of crashing with *"no such column"* (production schema remains migration-only).
Verified: 46 pre-existing demo orders all rebuild to their exact stored totals.

### Crash-class defects (second sweep — malformed input)

Found by firing ~93 malformed/garbage payloads at the running server. All four were
**HTTP 500 crashes**, all pre-existing, and all reachable from ordinary user input
rather than exotic attacks.

| # | Defect | Trigger | Fix |
|---|---|---|---|
| B-5 | Order quantity outside 1–100 crashed the request | Customer types *"50000 paneer tikka"* on WhatsApp, or a dashboard order with `qty` 0 / −3 / 999999 | `MAX_ORDER_QTY` in config — single source of truth for the parser **and** the bill check, so they cannot drift; parser clamps + flags `quantity_out_of_range`; chat replies in Hinglish, API returns 400 |
| B-6 | Non-numeric menu price crashed | Menu tab `price: "abc"` (add **and** edit). `NaN` passed every range check (`NaN < 0` is False) and produced a NOT NULL constraint failure on insert | shared `_num()` parser → 400; rejects non-numeric, negative, NaN, Infinity |
| B-7 | Non-numeric rule `priority` crashed | `POST /api/rules` with `priority: "abc"` | same `_num()` → 400 |
| B-8 | **A malformed discount rule took ordering offline for every customer** | Save a rule with `reward.value: "abc"` — validation existed on *update* only, not *create*, so `float("abc")` then raised in `best_discount()` on **every** order | validated on create too; `_as_float`/`_as_int` make the discount engine **total** (never raises), so a bad rule is skipped instead of crashing |

**B-8 was the most severe defect found in this pass.** One bad rule saved from the
dashboard stopped all ordering for all customers until someone edited the database by
hand. The engine is now total: a malformed rule can no longer stop ordering.

Root cause of all four: `float()` / `int()` applied directly to user-supplied JSON with
no validation, on code paths where a `ValueError` becomes an unhandled 500 — and in
B-8's case on the hot path that every order travels through.

Verified after the fix: **93/93 malformed payloads return clean 2xx/4xx, zero 5xx**
(was 6 crashes). Each new test fails on the unfixed code with the exact
`ValueError` / `TypeError`, and passes after.

## Summary counts (computed from the table above)

- Total rows: 51
- WORKING_VERIFIED: 21  (row 40 is SQLite-only)
- PARTIAL: 19
- MOCK_ONLY: 2
- NOT_IMPLEMENTED: 4  (per-restaurant GST, RBAC, tenant isolation, rate limiting)
- BLOCKED_EXTERNAL_SETUP: 5  (WhatsApp live, Razorpay live, PostgreSQL, Docker, live LLM)
- BROKEN: 0 known. Baseline defects are in PROJECT_AUDIT §3; this pass's defects in the table above.
