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
.venv\Scripts\python.exe -m py_compile app.py features/*.py tests/*.py              # syntax check
```

There is no linter configured.

Running the server:
- Production: `gunicorn app:app --workers 4 --worker-class gthread --threads 4 --timeout 120 --bind 0.0.0.0:$PORT` (`Procfile`; the `Dockerfile` hard-codes port 7860).
- `python app.py` fails with a circular-import error (blueprints do `from app import ...` while the main module is `__main__`). `flask --app app run` imports the module as `app` and should avoid this (not yet verified). gunicorn does not run on Windows.
- Needs `FIREBASE_CREDENTIALS` (service-account JSON as a string), `JWT_SECRET`, `ENCRYPTION_KEY` (Fernet), `META_APP_SECRET`/`FB_APP_SECRET`, `VERIFY_TOKEN`, `ADMIN_API_KEY`. If `JWT_SECRET`/`ENCRYPTION_KEY` are missing, each worker generates its own random value, so tokens and encrypted credentials break across workers.

Deployment: `.github/workflows/sync_to_huggingface.yml` **force-pushes `main` to a Hugging Face Space on every push to `main`** (Docker SDK, configured by the `README.md` front matter). A `Procfile` also exists for Render.

## Architecture

**Backend layout.** Almost everything lives in `app.py` (~3400 lines): config, auth decorators, Firebase helpers, all core routes, HTML templates for `/admin`, `/privacy`, `/lp/<id>` and the OAuth popup pages, plus the bot pipeline. `features/*_api.py` are Blueprints that import helpers *from* `app` (`from app import require_auth, _fb_get, ...`) and are registered at the very bottom of `app.py`, so any helper a blueprint needs must be defined above that point. `/api/shipping/*` is defined in both `shipping_api.py` and `assistant_api.py`; the `shipping_bp` copy is registered first.

**Firebase data model** (paths built with f-strings; product, city and coupon *names* are used as keys):
- `users/{username}` — owner account **and** bot settings in one node: `Password` (bcrypt), `User_ID`, `plan`, `source`, Gemini key, FB/IG/WhatsApp tokens and channel IDs. `uid_index/{uid}` → username.
- `team_users/{memberUsername}` — team-member logins (`ownerUid`, `permissions`, `active`). It is mirrored in `data/{uid}/teamMembers`.
- `data/{uid}/...` — per-tenant data: `orders`, `products`, `cities`, `coupons`, `storeSettings`, `landingPages`, `integrations` (secrets Fernet-encrypted), `usage/{YYYY-MM}`, `fbTokens`, `auditLog`, `ratings`, `trackingSettings`.
- `channel_index/{pageId|phoneNumberId}` → username, used by the webhook to find the merchant. `conversations/{uid}/{sender}`, `conversations_meta/{uid}`, `ai_logs/{uid}`, `admin_chats/{uid}`, `support_tickets`. `chats/{sender_id}` (bot history) is **not** tenant-scoped.
- `_fb_get` returns `None` on errors as well as on "not found".

**Auth and tenancy.**
- JWT HS256 in `Authorization: Bearer`. The frontend stores it in `localStorage.of_token`.
- Roles: `owner` (7-day token) or `member` (24h; `require_auth` re-checks `team_users` on every request).
- Decorator order is `@require_auth` then `@require_perm("<key>")` (owners always pass) or `@require_owner`. `@require_admin` uses the `X-Admin-Key` header.
- The tenant is always `request.auth_uid` from the token. Public storefront endpoints instead take a `userId` query or body param.
- `/api/saas` is a generic Firebase get/set/update/push proxy restricted by `_path_allowed`. It decodes the JWT itself instead of using `require_auth`.
- Plans and feature flags live in `PLANS`. Monthly caps are enforced via `_under_cap` / `_increment_usage`.

**Bot pipeline.** `/webhook` → `verify_sig` (HMAC) → `handle()` on `_executor` → `get_user_settings(channel_id)` → `process_bg` → `ask_gemini` (prompt asks for order JSON between `###JSON_START###` and `###JSON_END###`) → `extract_json` / `validate_order` → `save_order_from_bot`.

**Per-process state.** Caches, rate limits and bot-order dedupe are module-level dicts, so they are per gunicorn worker. Daemon threads (keepalive, cleanup) start at import time.

**Frontend.**
- `static/index.html` is one file that serves both the merchant dashboard and the public storefront (`/?store=<uid>`) on the same origin.
- It and `static/features/*.html` hard-code `API_URL = "https://orderconfidence.com/api"`, so a locally opened frontend talks to production.
- API responses use the envelope `{status: "ok", data}` or `{status: "error", message}` (`ok_json` / `err_json`).
- Escape anything inserted with `innerHTML` using `esc()`. Prefer `data-*` attributes over interpolating values into `onclick='...'`.

## UI/UX and media rules

- Use modern UI components with GSAP animations and Lenis smooth scrolling. Use high-contrast interactive elements, subtle glows and dark-mode dynamics (the app already has a dark/light toggle stored in `localStorage.of_theme`).
- Always structure smooth scrolling with `lenis`. Use `gsap` (with `ScrollTrigger`) for scroll triggers, timeline animations and landing-page hero reveals.
- **Loading the libraries:** Flask serves only `static/`, so `node_modules/` is not reachable from the browser and there is no bundler. Load the versions pinned in `package-lock.json` (gsap 3.15.0, lenis 1.3.27) the same way Chart.js is loaded in `index.html`: an exact-version jsDelivr URL (`gsap@3.15.0/dist/gsap.min.js`, `gsap@3.15.0/dist/ScrollTrigger.min.js`, `lenis@1.3.27/dist/lenis.min.js` plus `lenis.css`) with an SRI `integrity` hash. Alternatively, copy those `dist` files into `static/`.
- **Where pages are built:**
  - Public landing pages (`/lp/<id>`) are rendered server-side by `_build_landing_html` in `app.py` as one Python f-string, so literal CSS/JS braces must be doubled (`{{ }}`) and every dynamic value must pass through `_esc()`.
  - The storefront and dashboard share `static/index.html`.
  - Keep the existing `@media (prefers-reduced-motion: reduce)` handling for any new animation.
- **Media tools:** media creation and editing goes through Python tools (FFmpeg, MoviePy, Whisper). None of them are installed or listed in `requirements.txt` yet. Adding them changes the deployed image (Whisper pulls in PyTorch), so confirm with the owner before adding them to production requirements. Heavy processing should not run inside the gunicorn request cycle (120 s timeout).

## Tests

- `tests/fakes.py` injects in-memory `firebase_admin` (db, storage, credentials) and `google.genai` modules into `sys.modules` before `app` is imported. The fake DB mirrors RTDB path rules (rejects `[].?#$`, drops empty segments, prunes empty dicts and `None`). Gemini calls fail unless a test sets `fakes.GEMINI_RESPONDER["fn"]`.
- `tests/conftest.py` forces dummy env vars and blocks all sockets (`fakes.NetworkBlocked`). It resets the DB and the module-level caches before each test, and provides the `client`, `db`, `seed_owner()` and `seed_member(owner, perms=...)` fixtures, which return `headers` with a valid Bearer token.
- `tests/fakes.py` also contains a temporary `imghdr` shim, because `app.py` still imports `imghdr`, which was removed in Python 3.13.

## Ongoing security work

`AUDIT_REPORT.md` (Arabic) lists findings by ID (SEC-, BUG-, DEP-, PERF-, ARC-, INFO-xxx). Fixes are being applied in phases on the `security-fixes` branch, with one commit per ID (`fix(security): SEC-001 ...`) and a test that fails before the fix. The owner approves each phase before the next one starts. Line numbers in the report may be stale, so verify each finding against the current code first.
