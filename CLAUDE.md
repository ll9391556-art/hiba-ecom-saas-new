# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

OrderFlow: a multi-tenant SaaS for Algerian e-commerce merchants (orders, products, public storefront, landing pages, and a Gemini-powered Messenger/Instagram/WhatsApp sales bot). Flask backend on Firebase Realtime Database (Admin SDK, server-side only), vanilla-JS frontend with no build step. UI strings and code comments are in Arabic (often Algerian Darija) and French — keep that style.

## Commands

Tests (no Firebase, Gemini or network needed — see "Tests" below). Python 3.14 is known to work; the Dockerfile uses 3.10.

```powershell
py -3.14 -m venv .venv
.venv\Scripts\python.exe -m pip install "flask==3.0.3" "flask-cors==4.0.1" "requests==2.32.3" bcrypt PyJWT cryptography -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest -q                                              # all tests
.venv\Scripts\python.exe -m pytest tests/test_smoke.py::test_health_returns_200 -q # single test
.venv\Scripts\python.exe -m py_compile app.py core/*.py services/*.py features/*.py tests/*.py  # syntax check
```

There is no linter configured.

Running the server:
- Production: `gunicorn app:app` (Dockerfile `CMD` and `Procfile`); all settings are in `gunicorn.conf.py`: bind `0.0.0.0:$PORT` (default 10000), `WEB_CONCURRENCY` workers (default 2), `GUNICORN_THREADS` threads (default 8), gthread, timeout 120, no preload. 2 workers fit Render's 512 MB; each worker is roughly 120-180 MB. The keepalive runs once, in the gunicorn master (`when_ready`), pinging `$RENDER_EXTERNAL_URL/healthz`.
- `python app.py` fails with a circular-import error (blueprints do `from app import ...` while the main module is `__main__`). `flask --app app run` imports the module as `app` and should avoid this (not yet verified). gunicorn does not run on Windows.
- Needs `FIREBASE_CREDENTIALS` (service-account JSON as a string), `JWT_SECRET`, `ENCRYPTION_KEY` (Fernet), `META_APP_SECRET`/`FB_APP_SECRET`, `VERIFY_TOKEN`, `ADMIN_API_KEY`. Webhook signatures (`verify_sig`) are checked against `META_APP_SECRET` and, if set, `INSTAGRAM_APP_SECRET` (Instagram API with Instagram Login signs with its own secret); `FB_APP_SECRET` is only the OAuth `client_secret`. In production (`RENDER=true` or `APP_ENV=production`) `import app` raises if `JWT_SECRET` or `ENCRYPTION_KEY` is missing or the key isn't a valid Fernet key; elsewhere it warns and uses a temporary per-process value. `/healthz` is liveness (always 200, use it as Render's Health Check Path); `/health` also checks Firebase (cached 30 s, 503 on failure).

Deployment: production runs Python 3.10 in Docker (`Dockerfile`), so keep code compatible with 3.10. There is no CI deploy workflow (the Hugging Face sync workflow was removed). A `Procfile` exists for non-Docker runs; the `README.md` front matter is a leftover from Hugging Face Spaces. In the Render dashboard, the Docker Command field must stay empty (it would override the Dockerfile `CMD`).

## Architecture

**Backend layout** (being split out of `app.py` in Phase 4; see the plan in the PR history):
- `core/` — no business logic, no Flask app: `config.py` (env, secrets fail-fast, logging setup, constants, `PLANS`), `db.py` (`_fb_*` helpers, retry, `_fb_query`/`_fb_keys`), `http.py` (`ok_json`/`err_json`, arg parsing), `security.py` (JWT, `require_*` decorators, passwords, local + Firebase-backed rate limits, Fernet, SSRF/DNS pinning), `util.py` (`_safe_int`, `_cents`, `_mask_id`), `audit.py` (`log_audit_entry`).
- `services/` — business logic: `orders.py` (indexed order fields, `_save_order`/`_patch_order`, running totals, pricing/profit, storefront cache), `users.py` (user record/plan, usage caps, name/uid/channel indexes, lifetime counter, bot-settings save, channel settings cache), `coupons.py` (the single coupon check), `bot.py` (webhook verification and handling, Gemini, history, bot orders, Meta send/media, bot executor).
- `routes/` — one Blueprint per area: `public` (/, health, privacy, storefront, addOrder, trackOrder, ratings, `/lp/<id>`), `oauth`, `webhook`, `auth` (login, /api/me, team), `orders`, `catalog` (products, cities, customers, dashboard), `store` (settings, landing management, uploads), `integrations` (Woo), `messaging` (bot settings, conversations), `account`, `admin`, `saas`.
- `templates/` — HTML for `/admin`, `/privacy`, `/lp/<id>` and the OAuth popups, rendered with `core.templates.render` (its own Jinja env, autoescape on, works outside a request). `{{ x }}` escapes `x`; pass already-built HTML as `Markup(...)`. `tests/golden/*.html` + `tests/test_templates_golden.py` pin the rendered bytes (regenerate with `UPDATE_GOLDEN=1` only for an intentional change).
- `app.py` (~420 lines) only creates the Flask app (ProxyFix, CORS, request hooks, Firebase init, cleanup threads), registers the `routes/` blueprints and then `features/*_api.py`, and re-exports every name from `core/`, `services/` and `routes/` so `features/` and tests can keep doing `from app import ...`.
- Layering rule (enforced by `tests/test_architecture.py`): `core/`, `services/` and `routes/` never import `app` or `features`; `app.py` has no function-level `features` imports. New shared code goes in `core/`/`services/`, not in `app.py`.
- `tests/route_snapshot.json` pins every (URL rule, methods) pair; refactors must leave it unchanged (update it only when intentionally adding or removing a route).

**Firebase data model** (paths built with f-strings; product, city and coupon *names* are used as keys):
- `users/{username}` — owner account **and** bot settings in one node: `Password` (bcrypt), `User_ID`, `plan`, `source`, Gemini key, FB/IG/WhatsApp tokens and channel IDs. `uid_index/{uid}` → username. `uname_index/{lowercase}` → users key and `team_uname_index/{lowercase}` → team_users key (login, case-insensitive uniqueness); `counters/lifetimeAccounts` (transaction). Nothing outside `/api/admin/rebuildIndexes` and `listClients` may read `/users` or `/team_users` whole; after adding an index, write it on every create/rename and add it to `_rebuild_user_indexes`.
- `team_users/{memberUsername}` — team-member logins (`ownerUid`, `permissions`, `active`). It is mirrored in `data/{uid}/teamMembers`.
- Running totals: `data/{uid}/stats` (counts, `profitCents`, `sales/{key}`, `ratings/{key}`) and `data/{uid}/customers/{phoneDigits}`. Every order write must go through `_save_order(uid, id, order, before=...)` / `_patch_order` so `_apply_order_change` keeps them exact; stock (sold/available/stat) is derived at read time from products + `stats.sales`. `_compute_stats` / `_compute_customers` are the reference full recompute (`/api/recalcStats`, `rebuildIndexes`). `/api/saas` cannot touch `orders`, `stats`, `customers` or `ratings`.
- `data/{uid}/...` — per-tenant data: `orders`, `products`, `cities`, `coupons`, `storeSettings`, `landingPages`, `integrations` (secrets Fernet-encrypted), `usage/{YYYY-MM}`, `fbTokens`, `auditLog`, `ratings`, `trackingSettings`.
- `channel_index/{pageId|phoneNumberId}` → username, used by the webhook to find the merchant. `conversations/{uid}/{sender}`, `conversations_meta/{uid}`, `ai_logs/{uid}`, `admin_chats/{uid}`, `support_tickets`. Bot history is `chats/{merchant_uid}/{sender_id}`; legacy `chats/{sender_id}` nodes (shared across merchants, pre-SEC-005) are kept but never read. In-memory bot dedupe and rate-limit keys are `uid:sid`.
- `_fb_get` returns `None` on errors as well as on "not found".

**Auth and tenancy.**
- JWT HS256 in `Authorization: Bearer`. The frontend stores it in `localStorage.of_token`.
- Every JWT carries `typ`: `"session"` (login) or `"oauth_state"` (Facebook connect); `decode_token(token, typ=...)` rejects any token whose `typ` is missing or different.
- Roles: `owner` (7-day token) or `member` (24h; `require_auth` re-checks `team_users` on every request).
- Decorator order is `@require_auth` then `@require_perm("<key>")` (owners always pass) or `@require_owner`. `@require_admin` uses the `X-Admin-Key` header.
- The tenant is always `request.auth_uid` from the token. Public storefront endpoints instead take a `userId` query or body param.
- `/api/saas` is a generic Firebase get/set/update/push proxy restricted by `_path_allowed`. It decodes the JWT itself instead of using `require_auth`.
- Plans and feature flags live in `PLANS`. Monthly caps are enforced via `_under_cap` / `_increment_usage`.

**Bot pipeline** (`services/bot.py`). `/webhook` → `verify_sig` (HMAC) → `submit_webhook` → `handle_webhook_payload` on `_executor` → `get_user_settings(channel_id)` → `process_bg` → `ask_gemini` (prompt asks for order JSON between `###JSON_START###` and `###JSON_END###`) → `extract_json` / `validate_order` → `save_order_from_bot`.

**Per-process state.** Caches, rate limits and bot-order dedupe are module-level dicts, so they are per gunicorn worker. Cleanup daemon threads start at import time in every worker; the keepalive does not (it lives in `gunicorn.conf.py`).

**Frontend** (no build step; plain classic `<script>` tags sharing one global scope, loaded in order).
- `/` serves `static/index.html` (merchant dashboard); `/?store=<uid>` serves `static/shop.html` (public storefront). Same origin, so a storefront XSS can still read `localStorage.of_token`.
- CSS: `static/css/app.css`. JS: `static/js/` — shared `core.js` (config, i18n, `esc`, toast, `SHOP_UID`, event delegation) → `actions.js` → `api.js`; dashboard adds `auth`, `dashboard`, `orders`, `catalog`, `store`, `messaging`, `settings`, `ui`, `theme`, `main`; the storefront adds `shop`, `theme`, `shop-main`. `static/features/*.html` load `core.js` + `api.js` and keep their own page script. The order is pinned by `tests/test_frontend_layout.py`; a later file's functions don't exist yet while an earlier file runs its load-time code.
- `core.js` still hard-codes `API_URL = "https://orderconfidence.com/api"`, so a locally opened frontend talks to production.
- No inline event handlers. Write `data-on-click="fn(this.dataset.id)"` (also `change`, `input`, `keydown`, `error`) and add the same text as a key in `static/js/actions.js` (or the page's `registerActions({...})` for feature pages): `"fn(this.dataset.id)": function(event){ fn(this.dataset.id); }`. `this` is the element; `event.stopPropagation()` stops parent handlers, as inline handlers did. Tests fail on any `onclick=` and on any `data-on-*` text without a table entry. Pass values through `data-*` attributes (escaped with `esc()`), never by concatenating them into the handler text.
- API responses use the envelope `{status: "ok", data}` or `{status: "error", message}` (`ok_json` / `err_json`).
- Escape anything inserted with `innerHTML` using `esc()`.
- Static tests read pages through `tests/frontend.py` (`page_source`, `dashboard_and_shop`), which inlines the local scripts in load order.

## UI/UX and media rules

- Use modern UI components with GSAP animations and Lenis smooth scrolling. Use high-contrast interactive elements.
- The identity is light only (design D1): no dark backgrounds anywhere; `--ink` (#0B0B1F) is for text only. All colors and sizes are CSS variables in `static/css/tokens.css`, loaded before `app.css` by every page (templates included); old names (`--card`, `--accent`…) are kept as light aliases. Font: Readex Pro, body text ≥ 16px, buttons 14–16px corners, cards 20–28px. Logo: `static/img/logo.svg` / `logo-volt.svg`, favicon `static/favicon.svg`. `theme.js` keeps `applyTheme`/`toggleTheme`/`DARK_MODE` (always `false`) for old callers; the toggle markup stays `hidden`, and `localStorage.of_theme` is ignored. Status badges: `bp` pending, `bc` confirmed order only, `bi` delivered, `br` refused, `bn` neutral, `bs` in stock / published / active. `tests/test_design_d1.py` pins all of this.
- Always structure smooth scrolling with `lenis`. Use `gsap` (with `ScrollTrigger`) for scroll triggers, timeline animations and landing-page hero reveals.
- **Loading the libraries:** Flask serves only `static/`, so `node_modules/` is not reachable from the browser and there is no bundler. Load the versions pinned in `package-lock.json` (gsap 3.15.0, lenis 1.3.27) the same way Chart.js is loaded in `index.html`: an exact-version jsDelivr URL (`gsap@3.15.0/dist/gsap.min.js`, `gsap@3.15.0/dist/ScrollTrigger.min.js`, `lenis@1.3.27/dist/lenis.min.js` plus `lenis.css`) with an SRI `integrity` hash. Alternatively, copy those `dist` files into `static/`.
- **Where pages are built:**
  - Public landing pages (`/lp/<id>`) are rendered server-side by `_build_landing_html` (`services/landing.py`) with `templates/landing.html`. It's a Jinja template: write CSS/JS braces normally, but `{{`, `{%` and `{#` start Jinja syntax; dynamic text goes in as `{{ var }}` (autoescaped), pre-built HTML snippets as `Markup`.
  - The storefront is `static/shop.html` + `static/js/shop.js`; the dashboard is `static/index.html` + its `static/js/*.js`.
  - Keep the existing `@media (prefers-reduced-motion: reduce)` handling for any new animation.
- **Media tools:** media creation and editing goes through Python tools (FFmpeg, MoviePy, Whisper). None of them are installed or listed in `requirements.txt` yet. Adding them changes the deployed image (Whisper pulls in PyTorch), so confirm with the owner before adding them to production requirements. Heavy processing should not run inside the gunicorn request cycle (120 s timeout).

## Tests

- `tests/fakes.py` injects in-memory `firebase_admin` (db, storage, credentials) and `google.genai` modules into `sys.modules` before `app` is imported. The fake DB mirrors RTDB path rules (rejects `[].?#$`, drops empty segments, prunes empty dicts and `None`). Gemini calls fail unless a test sets `fakes.GEMINI_RESPONDER["fn"]`.
- The fake supports `order_by_child`/`order_by_key` queries (`equal_to`, `start_at`, `end_at`, `limit_to_first/last`) and `get(shallow=True)`. Like the real REST API, `order_by_child` on a child without `.indexOn` in `database.rules.json` raises "Index not defined" — so a new query needs its index added to that file (and to the Firebase console). Every read is logged in `fakes.READS`, so tests can assert a route never downloads a whole node.
- App code queries through `_fb_query(path, child_or_"$key", ...)`. `_fb_get/_fb_put/_fb_patch/_fb_delete/_fb_query` retry once on transient errors; `_fb_push` doesn't (not idempotent).
- **Patch where the code looks the name up.** `app.py` re-exports moved names, so `monkeypatch.setattr(app, "x", ...)` only affects code still in `app.py`. Code in a module sees that module's binding: patch `"core.db.sleep"` (retry), `"services.orders._now_ms"` (order timestamps; deliberately not re-exported), `"services.bot._executor"`, `"services.bot.get_user_settings"`, `"services.bot.process_bg"`, and route-level names in their `routes.<module>` (e.g. `"routes.orders._fb_query"`, `"routes.admin.LIFETIME_MAX_SLOTS"`).
- `tests/conftest.py` forces dummy env vars and blocks all sockets (`fakes.NetworkBlocked`). It resets the DB and the module-level caches before each test, and provides the `client`, `db`, `seed_owner()` and `seed_member(owner, perms=...)` fixtures, which return `headers` with a valid Bearer token.

## Ongoing security work

`AUDIT_REPORT.md` (Arabic) lists findings by ID (SEC-, BUG-, DEP-, PERF-, ARC-, INFO-xxx). Fixes are applied in phases, each on its own branch from `origin/main` (merged by PR), with one commit per ID (`fix(security): SEC-001 ...`) and a test that fails before the fix. The owner approves each phase before the next one starts. Line numbers in the report may be stale, so verify each finding against the current code first.
