---
globs: ["platform_v2/app.py", "platform_v2/services/**", "platform_v2/database.py", "platform_v2/rbac.py", "platform_v2/module_registry.py", "platform_v2/dashboard_generator.py", "platform_v2/templates/base.html", "platform_v2/templates/login.html", "platform_v2/templates/signup.html", "platform_v2/templates/dashboard_dynamic.html", "platform_v2/templates/verify_2fa.html", "platform_v2/templates/directory.html"]
---

# APP_CORE Rules (Audited 2026-03-18)

## Structure
- `app.py` — Flask app, route handlers, `|localtime` Jinja2 filter
- `services/auth_service.py` — 12 functions: login, lockout, password complexity, IP rate limiting, 2FA
- `services/dashboard_service.py` — 3 functions: AI status, recent activity, alerts
- `services/notification_service.py` — 10 functions with visibility enforcement (admin=all, user=own)
- `services/code_metrics_service.py` — codebase scanner, git history backfill, orphan detection

## Security (ADR-075 extraction)
- Account lockout: 5 failed attempts → 15min lock (`is_account_locked()`)
- Password complexity: 8+ chars, upper/lower/digit/special (`validate_password_complexity()`)
- IP rate limiting: 20 attempts/15min per IP (`check_ip_rate_limit()`)
- All auth events logged to `auth_events` table

## Template Extraction
- All templates have CSS/JS extracted to `static/css/` and `static/js/`
- `base.html`: 770→393 lines (base.css + base.js)
- `dashboard_dynamic.html`: 4,750→454 lines (dashboard.css + dashboard.js)
- `login.html`: 1,019→161 lines (login.css + login.js)
- `signup.html`: 1,654→246 lines (signup.css + signup.js)
- Shared static files (archie-time.js, station-ops.js/css) counted under APP_CORE

## LCARS header alert state — ONE resolver, fixed precedence (PRs #2463/#2465, 2026-07-25)

`static/js/lcars-header.js` paints `data-alert-state` on `#lcarsHeader`. **Two independent pollers**
feed it (`/api/alerts/unified` and the ops summary), so the state MUST NOT be written directly by
either — #2463 shipped exactly that bug and the elbow sat on `critical`, never reaching `dr`.

Each poller writes only its own module-level input (`_standingCondition` / `_alertsCritical` /
`_opsSeverity`); `_resolveElbowState()` is the sole writer, with fixed precedence:

```
dr  >  critical  >  diverted  >  warning  >  normal
```

- **Signal**: `services/dr_posture_monitor.is_dr_active()` — pure `ARCHIE_DR_MODE` env read, fail-safe
  `False`. `app.py:_dr_mode_flag()` wraps it so it can never raise into the alert bell, and stamps
  `dr_mode` onto `/api/alerts/unified` on **both** the success and exception paths.
- **Render**: `data-alert-state="dr"` → `#ef4444`, **0.7s** pulse (distinct from critical's 1s) +
  `.lcars-divert-tag.is-dr` reading `RED ALERT · STARBASE LOST COMMUNICATION` / `running on Citadel standby`.
- ⚠️ **`ARCHIE_DR_MODE=1` is NOT display-only** — `model_dispatch_service.py:132` **sheds inference** on it
  and tags every dispatch as DRP work. **Never set it on the prod hub to test the UI**; run an isolated
  probe container instead.
- Known cosmetic gaps (not fixed): the banner does **not** render on `/dashboard` (the header include is on
  tool pages only, not `base.html`), and the trailing tag text clips at desktop width (`white-space: nowrap`).
- ⚠️ 23 unit tests **and** a F.O.R.G.E. APPROVE both passed on the broken #2463 build. Only a live browser
  drive caught it. Header-state changes need a real DOM check, not source assertions (KB #283579).

## Module Categories (9 total)
- Admin Ops, AI Command, SaaS Services, Project & Knowledge, Media & Home
- Crypto, Applications, Creative Studios, Coming Soon
- Defined in `module_registry.py` + `dashboard_generator.py`

## Key Gotchas
- Services import: `from services.auth_service import ...` (relative to platform_v2)
- Module perms: add to BOTH `rbac.py` AND `module_registry.py`
- `|localtime` filter defined in `app.py` — converts UTC to configured timezone
- Black pre-commit reformats Python — re-stage after first commit attempt fails
- Files reduced: 53→11 root Python files after service extraction + relocations
