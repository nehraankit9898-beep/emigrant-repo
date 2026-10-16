# Deployment and repository audit — Netlify / Neon request

**Audit date:** 2026-10-15  
**Repository:** `nehraankit9898-beep/emigrant-repo`  
**Working branch:** `arena/2445ccf3-emigrant-repo` (kept unchanged)  
**Decision:** **Not ready to redeploy to Netlify as this checkout stands.** The inspected repository is not a StayLoop hotel application and has no Netlify runtime/build configuration. The actual production 500 cannot be attributed to a single cause without the Netlify build and function/runtime logs.

## 1. Critical scope finding

The checked-out code identifies itself as a **Sharma Cafe WhatsApp AI Agent** (README title and app metadata), not StayLoop. It contains one restaurant dashboard and business workflow; it does **not** contain hotel registration/management, restaurant tenant accounts, user accounts, RBAC, admin/super-admin roles, or tenant isolation. `beyto.in` does not appear in the tracked source/configuration.

This means the requested StayLoop feature inventory and production environment cannot be faithfully audited or repaired from this checkout. No StayLoop features were added or removed, and the existing restaurant-agent architecture was not replaced.

## 2. Architecture found

| Area | Evidence / current design |
|---|---|
| Application | Python 3.11, FastAPI ASGI app (`app/main.py`, `app/api.py`) |
| UI | One inline HTML/CSS/JavaScript dashboard at `app/static/dashboard.html`; served by FastAPI at `/`; tabs are client-side state, not a separate React/SPA build |
| API | Same-origin `/api/*` routes; signed WhatsApp and Razorpay webhooks; payment pages under `/pay/*`; `/health` and `/ready` |
| Business features | Restaurant chat/memory, menu, orders, billing/discounts/coupons, mock/live payment, reservations, feedback, campaigns, dashboard, and scheduled automations |
| Database | SQLAlchemy models in `app/models.py`; SQLite default; PostgreSQL via `DATABASE_URL`; Alembic history in `migrations/versions/` |
| Runtime/deployment | Uvicorn process in `Dockerfile`; Docker Compose for local PostgreSQL; GitHub Actions runs pytest/compile checks |
| Netlify | No `netlify.toml`, `package.json`, Node lockfile, `netlify/functions/`, publish directory, or FastAPI-to-Netlify function adapter |
| Dependencies | One `requirements.txt`; no npm dependencies and no Python lockfile. Requirements use minimum versions (`>=`), so resolution is not locked/reproducible across time |

### Existing feature inventory and gaps

- **Present:** restaurant dashboard and API, customer memory, menu/order workflow, discount rules and coupons, payment flow, table reservations, feedback, opt-in campaigns, automations, reports, and signed provider webhooks.
- **Authentication:** one shared `ADMIN_TOKEN` header/Bearer gate for `/api/*`; it is not a user login system.
- **Not implemented in this repository:** hotel management, multi-business tenancy, `restaurant_id` scoping, separate staff/owner/super-admin roles, or super-admin controls. These must not be represented as preserved or verified StayLoop functionality.
- **Operational constraint:** the automation scheduler is started in the ASGI lifespan. A short-lived serverless function invocation is not a reliable place to run this perpetual scheduler; a Netlify adaptation would need a separate scheduled trigger/worker.

## 3. Root-cause report

| Severity | Finding | Evidence | Status / action |
|---|---|---|---|
| **Blocker** | The repository does not match the requested StayLoop application. | README, module names, models, and UI describe a single-cafe WhatsApp agent; no StayLoop/hotel/super-admin source was found. | **Unresolved.** Provide the correct StayLoop repository/branch if this is not the intended project. |
| **Blocker** | This code cannot be deployed as a Netlify static site and serve its APIs as-is. | The app is a long-running FastAPI/Uvicorn server; no Netlify build, functions, or ASGI adapter exists. Publishing `app/static` alone would serve the HTML without the `/api/*` backend. | **Unresolved.** Do not set a guessed publish directory or claim Netlify readiness. Implement and test a compatible serverless adapter (and move scheduling out of request lifespan) or deploy this ASGI app to a container host. |
| **Unconfirmed production incident** | Exact cause of `GET /` HTTP 500 on `beyto.in` is unknown. | No Netlify deploy ID/build log, function log, site settings, or production environment-variable names were available. The domain was not independently queried. | **Needs evidence.** See §10 for the exact Netlify log/settings needed. |
| **Confirmed failure mode** | When `APP_ENV=production`, invalid/missing production configuration raises during FastAPI startup; every request can fail before `/` is served. | Reproduced locally with an intentionally incomplete production environment. The sanitized startup error listed missing admin token, PostgreSQL URL, WhatsApp live credentials/verify token, payment live mode, and HTTPS `PUBLIC_BASE_URL`. This is a possible 500 cause, not proof of the live Netlify cause. | **Guardrails improved.** Production now validates the full set of live provider credentials and refuses demo seeding. Netlify values still need verification. |
| **Confirmed source defect** | Conventional `/favicon.ico` had no route or asset; the dashboard also had no icon link. | No favicon source existed before the change. | **Fixed in this checkout.** Added SVG and ICO assets, explicit icon links, and `/favicon.ico` + `/favicon.svg` responses; local GET checks return 200 with their matching image content types. |
| **Confirmed production-safety defect** | `DEMO_SEED` defaulted to `true` even in production, so an empty production database could receive demo customers/orders during app startup. | `Settings.demo_seed` default and `lifespan()` call to `seed.seed_demo()`; the seed function inserts demo customer/order data when no customers exist. | **Fixed.** Defaults off in production; explicitly setting it true now prevents production startup. Development/demo behavior remains enabled by default. |
| **Confirmed production-configuration gap** | `PAYMENT_MODE=live` could pass validation without Razorpay API keys, while `payment_live` would be false and select mock payment behavior. WhatsApp token/phone ID and the sample verify token were also not validated. | `Settings.payment_live` / `whatsapp_live` depend on credentials; prior `production_problems()` did not check the complete credential set. | **Fixed.** Production startup now requires WhatsApp token, phone-number ID, app secret, a non-placeholder verify token, Razorpay key ID/secret/webhook secret, and other production settings. |
| **Compatibility risk** | PostgreSQL URL driver selection depended on SQLAlchemy's default behavior for unqualified `postgresql://` URLs. | `psycopg[binary]` is installed; explicit `postgresql+psycopg://` is the stable driver URL for this project. | **Fixed defensively.** `postgresql://` and legacy `postgres://` are normalized to `postgresql+psycopg://`; query parameters such as `sslmode=require` are retained. This was not confirmed as the live incident cause. |
| **Data-safety issue** | The Docker image automatically ran `alembic upgrade head` on every start. Migration `0001_baseline` creates tables and is not a safe blind baseline for an existing database without migration history. | `Dockerfile` command and `migrations/versions/0001_baseline_original_schema.py`. | **Fixed per the no-auto-migration requirement.** Migrations are now a separate explicit release step. Existing Neon schema/version must be reviewed before running any migration. |
| **Security/product gap** | Shared-token auth is not RBAC or tenant isolation. | `app/api.py` `require_admin`; no `restaurant_id` tenant key or role/user model in `app/models.py`. | **Unresolved product gap.** Do not use this as a multi-tenant hotel/restaurant SaaS or claim super-admin isolation. |

### Why the actual Netlify 500 is not declared fixed

A local Uvicorn run serves `/` successfully. The repository does not reveal which build command, publish directory, environment variables, or function runtime Netlify is currently using. A code-supported startup failure is reproducible when production configuration is incomplete, but only the actual failed deploy/runtime log can establish whether that is what happened on `beyto.in`. No external deployment success is claimed.

## 4. Duplicate-code / dead-code review

- `jscpd` scanned Python source/tests/scripts with AST similarity enabled: **6 candidate clones, 77 lines / 0.81% of 9,538 scanned lines**. They correspond to distinct flows: birthday vs. winback campaign rules; two LLM requests with different payload/response handling; demo-seed vs. live order creation; and list serializers for different entities. They were not consolidated because their business rules and side effects differ.
- Route registration review found **59 distinct method/path pairs** and no duplicate method/path registration.
- `vulture` at 80% confidence found one provably dead constant conditional in `app/seed.py`; it was reduced to its existing runtime value (`"Veg Burger"`). Remaining findings are pytest fixture arguments and intentionally accepted lambda keyword arguments, not safe removals.
- No files or dependencies were removed. No abandoned feature implementation was deleted based only on search results.
- `jscpd` in this pass did not parse the inline HTML dashboard as a Python/JavaScript source file; its JavaScript syntax was checked separately. This is not a proof that every semantic duplicate across all formats is absent.

## 5. Database / Neon audit

- The application reads **`DATABASE_URL`**. It does not read `NEON_DATABASE_URL`, `DATABASE_URI`, or `POSTGRES_URL`.
- Use Neon’s pooled PostgreSQL endpoint for a serverless-oriented deployment, keep the URL server-side, and use TLS (`sslmode=require` as included by Neon). The updated config normalizes an ordinary `postgresql://` URL to Psycopg 3.
- The `.env.example` local default is SQLite. Production startup requires a PostgreSQL/Psycopg 3 URL.
- No local `.env`, Neon URL, Postgres client, Docker, or database credentials were available. **No connection to Neon was attempted, no production query was issued, and no production data/schema was changed.**
- A fresh, isolated **SQLite-only** migration probe succeeded at `0003_order_bill_rates` and created 16 tables. This does not prove PostgreSQL compatibility or Neon connectivity.
- **Existing schema blocker:** `0001_baseline` creates the original tables unconditionally. If Neon already has app tables but no `alembic_version`, running `alembic upgrade head` blindly may fail on existing tables. First read `alembic_version` and inspect the schema. Only `alembic stamp 0001_baseline` after confirming the existing schema exactly matches that baseline; otherwise prepare a reviewed, non-destructive reconciliation plan. Do not run downgrade/reset/drop commands on the live database.
- App startup still idempotently inserts default menu/rule rows when those tables are empty. It skips demo customer/order seeding in production. This behavior should be reviewed against the real Neon contents before first production startup.

Read-only Neon preflight (run in the Neon SQL editor; no data is changed):

```sql
SELECT to_regclass('public.alembic_version') AS alembic_version_table;
-- Run only if the table exists:
SELECT version_num FROM alembic_version;
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
ORDER BY table_name;
```

## 6. Security / performance findings

- **Positive controls present:** API routes use the shared admin-token dependency; webhook verification is fail-closed in production; payment settlement verifies provider signatures/amount; SQLAlchemy is used for application queries; logs have redaction code; production config is fail-closed.
- **Open gaps:** no role-based authorization or tenant boundary; no rate limiter; no systematic CSP/XSS or browser review; no load/performance test. These are not fixed by deployment configuration.
- **Serverless concern:** the default SQLAlchemy pool and perpetual in-process scheduler have not been tuned/tested for Netlify function concurrency. Use Neon pooling and a separately scheduled job only after a real adapter is designed and load-tested.
- **Dependency security:** `pip check` passes, but there is no lockfile and no vulnerability database scan was available. Do not interpret dependency consistency as a CVE audit.

## 7. Files changed

| File | Reason |
|---|---|
| `.env.example` | Document local-only demo seed/verify-token values and production overrides. |
| `app/config.py` | Normalize Neon/PostgreSQL URL driver; avoid production demo seeding; validate complete live credentials. |
| `app/main.py` | Serve the favicon on conventional and explicit paths. |
| `app/seed.py` | Remove a constant-false conditional without changing the seeded value. |
| `app/static/dashboard.html` | Link the SVG favicon. |
| `app/static/favicon.svg`, `app/static/favicon.ico` | New small, self-contained vector and conventional ICO icons. |
| `Dockerfile` | Stop running Alembic migrations automatically at application startup. |
| `docs/DEPLOYMENT.md` | Document explicit migration and production configuration steps. |
| `docs/PROJECT_AUDIT.md`, `docs/SECURITY_AUDIT.md`, `docs/FEATURE_STATUS.md`, `docs/IMPLEMENTATION_PLAN.md` | Mark prior-branch test/status claims as historical and align migration instructions with the current Docker behavior. |
| `README.md` | Remove a stale fixed test count and link to this audit. |
| `tests/test_config.py` | Cover production configuration/seed guards and PostgreSQL URL normalization. |
| `tests/test_http_routes.py` | Cover homepage and favicon responses. |
| `docs/REQUESTED_DEPLOYMENT_AUDIT.md` | This evidence-based audit and blocker list. |

No migration file was applied or changed. No production database data was touched. Tests use an ignored local SQLite database.

## 8. Verification results

| Check | Result |
|---|---|
| `pip install -r requirements.txt` in repository `.venv` | **Passed.** The first test invocation could not import pytest because the sandbox had no project dependencies; global system install was blocked by PEP 668, so dependencies were installed in a virtual environment instead. This was environment setup, not a source/build failure. |
| `pip check` | **Passed:** no broken requirements. No requirements lockfile exists, so versions are not locked. |
| TypeScript / npm production build | **Not applicable:** no package manifest, TypeScript, or frontend build script exists in this checkout. |
| `python -m pytest -q` | **130 passed, 1 third-party Starlette/httpx deprecation warning.** Baseline before edits: 125 passed, same warning. |
| `python -m compileall -q app scripts tests` | **Passed.** |
| Ruff `--select F,E9` | **Passed.** No Ruff configuration/lint command is defined in the repository. Running Ruff with its entire default rule set reports 246 diagnostics; it was not used as a configured gate and no broad auto-fix was applied. |
| Inline dashboard JS `node --check` | **Passed** (1 script block). |
| `scripts/smoke_api.py` against local Uvicorn | **Passed:** 53 routes checked, no server errors. |
| `scripts/bug_hunt.py` against local Uvicorn | **Passed:** 5 regression checks, 0 failures. |
| Local HTTP | `/` 200 HTML; `/favicon.ico` 200 `image/x-icon`; `/favicon.svg` 200 `image/svg+xml`; `/health`, `/ready`, `/api/menu`, `/api/summary` 200; nonexistent payment token returns expected 404. |
| Fresh Alembic migration | **Passed on isolated SQLite only:** `0003_order_bill_rates (head)`, 16 tables. |
| Netlify build/function check | **Not run / blocked:** no Netlify config, adapter, CLI, or deployment log. |
| Docker image build | **Not run / blocked:** Docker is not installed in this workspace. |
| PostgreSQL/Neon connectivity, migrations, pooling and concurrency | **Not run / blocked:** no Neon environment variable/credentials or `psql`; real Postgres is not installed. |
| Browser-based dashboard, live Meta/Razorpay and public `beyto.in` verification | **Not run.** |

A local reproduction with incomplete `APP_ENV=production` failed startup with sanitized configuration diagnostics. This demonstrates an available failure path, not the production incident’s cause.

## 9. Required environment-variable names (no values)

For this application’s strict production configuration:

- `APP_ENV=production`
- `DEMO_SEED=false`
- `DATABASE_URL` (Neon pooled PostgreSQL URL; TLS enabled)
- `ADMIN_TOKEN` (random, at least 24 characters; keep server-side)
- `PUBLIC_BASE_URL` (HTTPS)
- `WHATSAPP_MODE=live`
- `WHATSAPP_TOKEN`
- `WHATSAPP_PHONE_NUMBER_ID`
- `WHATSAPP_APP_SECRET`
- `WHATSAPP_VERIFY_TOKEN` (random, at least 24 characters; do not use the example value)
- `PAYMENT_MODE=live`
- `RAZORPAY_KEY_ID`
- `RAZORPAY_KEY_SECRET`
- `RAZORPAY_WEBHOOK_SECRET`

Optional, depending on enabled features: `LLM_MODE`, `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_BASE_URL`, automation/time settings, `PORT`, and `FORWARDED_ALLOW_IPS`. `POSTGRES_PASSWORD` is for the local Docker Compose PostgreSQL service, not Neon. These variables do not make the code Netlify-compatible by themselves.

## 10. Netlify steps and exact blockers

### Do not redeploy this checkout as a static Netlify site

There is no valid publish/build setting that will provide both this FastAPI app and its APIs. Publishing `app/static` alone will not provide `/api/*`, the signed webhooks, database access, or scheduler. No Netlify settings were guessed or added.

To establish the actual incident, collect these **non-secret** items from Netlify:

1. **Deploys → failed deploy → Deploy log:** the full build log from the first failure through the exit code.
2. **Observability / Functions logs:** stack/error for a production `GET /` and any function cold-start message.
3. **Site configuration → Build & deploy:** base directory, build command, publish directory, functions directory, and the selected runtime/build image.
4. The **names only** of configured production variables (do not send values), plus whether `APP_ENV` is set to production.

If this repository is intended, the choices are:

- deploy the ASGI app on a long-running container host, using the repository Dockerfile; or
- explicitly implement and test a Netlify-compatible function adapter, package the Python app/static file, replace the perpetual scheduler with a scheduled worker, validate serverless database pooling, and run Netlify local/function tests before production.

For the existing Docker path, build the image, review/back up the target DB, explicitly run the approved migration step (`docker compose run --rm app alembic upgrade head`), then start the service. **Do not run that migration against existing Neon until the schema/version preflight in §5 is complete.** Startup no longer applies migrations automatically.

### Neon dashboard checklist

1. In Neon, choose the correct project/database and pooled connection string; do not create/reset a database to work around this app.
2. In the application host’s server-side environment settings, add `DATABASE_URL` and the production variables from §9. Do not put values in the HTML or Git.
3. Run the read-only schema/version preflight in §5. Back up/branch the database before any approved migration.
4. Test `SELECT 1` through the application’s configured driver, then run migrations only through the explicit release step after schema review.
5. Check `/ready`, dashboard APIs, and logs after deploying the application on a compatible runtime.

## 11. Remaining blockers / information required

1. **Correct project identity:** confirm whether this restaurant-agent repository is intended. If the requested StayLoop source differs, provide the repository or branch that contains it.
2. **Actual 500 diagnosis:** provide the failed Netlify deploy ID/log and function/runtime log. Without them, the root cause of the live 500 remains unconfirmed.
3. **Hosting architecture:** choose a compatible container host for this ASGI app, or authorize a separate Netlify-functions adaptation with its associated scheduler/database changes.
4. **Neon safety:** provide schema/version preflight results (not credentials) before any migration decision.
5. **Business/security gaps:** hotel workflows, RBAC and tenant isolation are not in this checkout; implementing them requires product/schema work, not a deployment fix.

**Production readiness conclusion:** locally verified improvements are complete for this repository, but the requested Netlify deployment and Neon production readiness are **not verified and must not be declared complete** until the correct app, Netlify logs/runtime configuration, and read-only Neon schema state are supplied.
