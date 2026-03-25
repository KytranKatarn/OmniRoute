# Kytran System Operations — Tier 2 Completion Design

**Date**: 2026-03-25
**Project**: #193 — Kytran System Operations — Standalone Product + Compliance Engine
**Status**: Design Approved
**Scope**: Tier 2 requirements — SSO, compliance scanning, badges, subdomain, launch page, health endpoint, responsive polish, tier progress badge
**Depends on**: Tier 1 (completed 2026-03-25)

---

## Problem Statement

Tier 1 shipped the standalone with all features migrated, LCARS theme, local auth, Docker-ready, and Code Health registration. Tier 2 (30-day target) connects the standalone back to A.R.C.H.I.E. with SSO, adds compliance scanning with live badges, sets up the subdomain, replaces the ARCHIE module with a launch page, and polishes the responsive experience.

---

## Deliverable 1: OAuth — "Sign in with Kytran"

### Flow
1. User clicks "Sign in with Kytran" on standalone login page
2. Standalone redirects to `{ARCHIE_HUB_URL}/oauth/authorize?client_id=kytran-sysops&redirect_uri={STANDALONE_URL}/auth/sso/callback&response_type=code`
3. ARCHIE shows its login (Google OAuth or local) if not already authenticated
4. After auth, ARCHIE redirects back with authorization code: `{redirect_uri}?code={auth_code}`
5. Standalone exchanges code for JWT via `POST {ARCHIE_HUB_URL}/oauth/token`
6. Standalone creates/links local user from JWT payload (username, role, email)
7. User is logged in to standalone with ARCHIE identity

### ARCHIE Side (New)

**Routes** (new file `platform_v2/oauth_provider.py` or in `app.py`):
- `GET /oauth/authorize` — validates client_id, shows consent/login, generates auth code
- `POST /oauth/token` — exchanges auth code for JWT containing `{user_id, username, email, role}`
- Auth codes expire after 5 minutes, single-use

**Database**:
- `oauth_clients` table: `id`, `client_id` (varchar, unique), `client_secret` (varchar), `redirect_uri` (varchar), `name` (varchar), `created_at`
- `oauth_codes` table: `id`, `code` (varchar, unique), `client_id` (varchar), `user_id` (int), `redirect_uri` (varchar), `expires_at` (timestamp), `used` (boolean)

**Pre-registered client**:
- client_id: `kytran-sysops`
- client_secret: generated, stored in standalone's env
- redirect_uri: `http://192.168.1.200:8085/auth/sso/callback`
- name: "Kytran System Operations"

### Standalone Side (Upgrade Existing Stub)

**Modified file**: `kytran-server-manager/kytran_server_manager/auth.py`

- `/auth/sso` — redirects to ARCHIE's `/oauth/authorize` (replaces 501 stub)
- `/auth/sso/callback` — new endpoint: receives code, exchanges for JWT, creates/links user, sets Flask-Login session
- `/auth/sso/status` — updated: returns `sso_enabled: true` when `ARCHIE_HUB_URL` is configured

**Config env vars**:
- `ARCHIE_HUB_URL` — e.g., `http://192.168.1.200:3000` (when not set, SSO hidden, local-only)
- `ARCHIE_CLIENT_ID` — `kytran-sysops`
- `ARCHIE_CLIENT_SECRET` — shared secret

**Login page update**: "Sign in with Kytran" button visible when `ARCHIE_HUB_URL` is set, hidden otherwise. Styled as a secondary login option below the local form.

---

## Deliverable 2: Compliance Scanning + Live Badges

### Self-Contained Scanning

**Existing files** (already in standalone):
- `kytran-server-manager/kytran_server_manager/services/compliance_service.py` — scan engine
- `kytran-server-manager/kytran_server_manager/routes/compliance_routes.py` — API endpoints
- `kytran-server-manager/rule_packs/` — JSON rule pack files

**New: Background scheduler**:
- APScheduler or `threading.Timer` loop in app startup
- Runs compliance scan every 6 hours (configurable via `COMPLIANCE_SCAN_INTERVAL` env var)
- First scan runs 60 seconds after app startup
- Results stored in standalone's SQLite: `compliance_scans` + `compliance_scan_results` tables

**New: Manual trigger**:
- `POST /api/compliance/scan` — triggers immediate scan, returns job status
- Dashboard button "Run Compliance Scan" calls this endpoint

### Live SVG Badges

**New endpoint**: `GET /api/compliance/badge/<pack_id>.svg`
- Generates SVG badge matching ARCHIE's format
- Color grading: Green (#22c55e) 90%+, Blue (#3b82f6) 80%+, Yellow (#f59e0b) 70%+, Red (#ef4444) <60%
- Grade scale: A+ (95%), A (90%), B+ (85%), B (80%), C (70%), D (60%), F (<60%)
- Pack IDs: `ubuntu-stig`, `docker-stig`, `network-stig`, `cis-ubuntu`, `hipaa`, `overall`

**Dashboard integration**:
- Compliance summary bar at top of dashboard: overall score + individual pack badges
- Auto-refreshes from latest scan results
- Clicking a badge opens detailed findings for that pack

### Hub Reporting (When Connected)

- When `ARCHIE_HUB_URL` is configured, after each scan completes:
  - `POST {ARCHIE_HUB_URL}/api/standalone/compliance-report` with scan results payload
  - Payload: `{product_name, scan_id, overall_score, pack_scores, timestamp, findings_summary}`
- ARCHIE receives and stores in `compliance_scans` table with `scan_target = 'Kytran System Operations'`
- Code Health cross-reference endpoint (already built in B6) reads this data
- If ARCHIE unreachable: scan completes locally, report queued for retry on next scan cycle

**New ARCHIE endpoint**: `POST /api/standalone/compliance-report`
- Authenticated via `Authorization: Bearer {client_id}:{client_secret}` header (same OAuth credentials, base64 encoded)
- Stores scan results in ARCHIE's compliance tables
- Returns 200 on success

---

## Deliverable 3: Infrastructure

### Subdomain — `server.kytranempowerment.com`

**AdGuard DNS**:
- Add DNS rewrite: `server.kytranempowerment.com` -> `192.168.1.200`

**NPM Proxy Manager**:
- New proxy host: `server.kytranempowerment.com` -> `http://192.168.1.200:8085`
- SSL: Let's Encrypt certificate (internal validation)
- Force HTTPS

**Scope**: Internal-only for Tier 2. Public access (port forwarding, Hostinger DNS) deferred to Tier 3 with compliance review.

### Health Endpoint

**New endpoint on standalone**: `GET /api/health` (no auth required)

Response:
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "uptime_seconds": 3600,
  "database": "ok",
  "last_compliance_scan": "2026-03-25T19:00:00",
  "compliance_score": 92.8,
  "connected_to_hub": true,
  "tier_progress": {
    "current_tier": 2,
    "completed": 3,
    "total": 8,
    "items": {
      "sso": true,
      "compliance_scanning": true,
      "badges": true,
      "subdomain": false,
      "redirect": false,
      "health_endpoint": false,
      "responsive": false,
      "code_health_badge": false
    }
  }
}
```

Tier progress items auto-detected:
- `sso`: `ARCHIE_HUB_URL` is set and `/auth/sso` returns 302 (not 501)
- `compliance_scanning`: last scan exists and is < 24 hours old
- `badges`: `/api/compliance/badge/overall.svg` returns 200
- `subdomain`: `SERVER_SUBDOMAIN` env var is set
- `redirect`: `ARCHIE_HUB_URL` is set (implies launch page exists)
- `health_endpoint`: always true (this endpoint exists)
- `responsive`: hardcoded true after responsive polish is deployed
- `code_health_badge`: `ARCHIE_HUB_URL` is set and tier reporting works

### ARCHIE Launch Page (Replaces System Ops Module)

**Route**: `/tools/system-operations` (same URL, new content)

**Template**: Minimal LCARS card showing:
- Health status: green/red dot pulled from standalone's `/api/health`
- Compliance score badge (from health response)
- Version number
- Tier progress: "Tier 2: 5/8 complete" with mini progress bar
- **"Launch System Operations"** button -> opens `server.kytranempowerment.com` (or fallback `192.168.1.200:8085`) in new tab
- "Sign in with Kytran" note explaining SSO
- Auto-refreshes health every 30 seconds via JS fetch

**Config**: `STANDALONE_SYSOPS_URL` env var in ARCHIE (defaults to `http://192.168.1.200:8085`)

---

## Deliverable 4: Mobile/Responsive + Code Health Tier Badge

### Responsive Polish on Standalone

- Tab navigation: horizontal scroll with snap on mobile
- Data tables: horizontal scroll with `-webkit-overflow-scrolling: touch`
- Compliance badges: stack vertically below 480px
- All buttons/links: minimum 44x44px touch targets
- Login page: form fields full-width on mobile, SSO button full-width
- Dashboard cards: single column below 768px
- Apply UI/UX Pro Max guidelines matching Code Health tab redesign

### Code Health Tier Progress Badge

**Update standalone table in Consciousness JS** (`_renderStandaloneTable`):
- Replace static "TIER 1" badge with dynamic tier progress
- Fetch from `/api/code-health/standalone-status` (already built, extend with tier data)
- Display: "TIER 2: 5/8" with mini progress bar
- Color: red (0-25%), amber (25-75%), green (75-100%)

**Update standalone-status endpoint**:
- Query standalone's `/api/health` for tier_progress data
- Include in the response alongside compliance scores

---

## File Map

### ARCHIE Platform
| Action | File | What |
|--------|------|------|
| Create | `platform_v2/oauth_provider.py` | OAuth authorize + token endpoints |
| Create | `database/migrations/XXX_oauth_clients.sql` | oauth_clients + oauth_codes tables |
| Modify | `platform_v2/app.py` | Register OAuth routes |
| Modify | `platform_v2/tools/system_operations/routes.py` | Replace module with launch page |
| Create | `platform_v2/templates/tools/system_operations_launch.html` | Launch page template |
| Modify | `platform_v2/tools/consciousness/code_health_routes.py` | Extend standalone-status with tier data |
| Modify | `platform_v2/static/js/consciousness.js` | Dynamic tier progress badge |
| Create | `platform_v2/api_standalone.py` | `/api/standalone/compliance-report` receiver |

### Standalone (kytran-server-manager)
| Action | File | What |
|--------|------|------|
| Modify | `auth.py` | SSO redirect + callback, upgrade from stub |
| Modify | `templates/login.html` | SSO button (conditional on hub config) |
| Create | `routes/health_routes.py` | `/api/health` + tier progress |
| Create | `routes/badge_routes.py` | `/api/compliance/badge/<pack>.svg` |
| Modify | `routes/compliance_routes.py` | Manual scan trigger, hub reporting |
| Modify | `routes/__init__.py` | Register new routes |
| Create | `services/scheduler.py` | Background compliance scan scheduler |
| Create | `services/hub_client.py` | ARCHIE hub communication (report scores, exchange tokens) |
| Modify | `app.py` | Start scheduler, configure hub URL |
| Modify | `templates/dashboard.html` | Compliance summary bar, scan button |
| Modify | `static/css/lcars-frames.css` | Responsive polish |

### Infrastructure (Manual/Script)
| Action | What |
|--------|------|
| AdGuard | DNS rewrite `server.kytranempowerment.com` -> `192.168.1.200` |
| NPM | Proxy host + SSL cert for subdomain |

---

## Out of Scope (Tier 3)

- Public-facing subdomain (port forwarding, Hostinger DNS)
- SOC 2 evidence collection + PDF reports
- S.H.I.E.L.D. agent integration
- Subscription-gated features
- Node/Starship integration
- Agent loop health monitoring job

---

## Success Criteria

1. "Sign in with Kytran" works end-to-end: click button -> ARCHIE login -> back to standalone logged in
2. Compliance scans run every 6 hours automatically, results in standalone DB
3. Live SVG badges render on standalone dashboard with real scores
4. `server.kytranempowerment.com` loads over HTTPS internally
5. ARCHIE System Ops module shows launch page with health status
6. `/api/health` returns comprehensive status including tier progress
7. Standalone reports compliance scores to ARCHIE hub
8. Code Health shows dynamic tier progress badge
9. All views work at 480px / 768px / 1024px breakpoints with 44px touch targets
