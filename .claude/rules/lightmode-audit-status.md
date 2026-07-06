# Light-Mode Audit Tracker (#1997 / #1998 / #1999)

Running status of the platform-wide light-mode (LCARS) compliance audit + fix.
Verified live in the browser (both light **and** dark) unless noted. Updated as work progresses.

**Systemic fix (PR #2072):** `light-mode.css` now re-declares the bare `--archie-*` token
aliases under `body.light-mode` so they resolve light at body scope — this repairs **every**
module that styles with `--archie-*` tokens. Modules below marked *clean* benefited from this
(or were already fine); modules marked *fixed* also needed a private-namespace/literal-hex remap.

Legend: ✅ verified light · 🔧 fixed this pass · ⏳ pending visual audit · ⛔ N/A (disabled/redirect)

| Module | Route | Status | Notes |
|--------|-------|--------|-------|
| Dashboard (core) | `/dashboard` | ✅ | clean (minor: footer text low-contrast, cosmetic) |
| Security & Network | `/tools/security-network` | ✅ | clean |
| Account Center | `/tools/account-center` | ✅ | clean |
| Repair Bay | `/tools/repair-bay` | ✅ | clean |
| Consciousness | `/tools/consciousness` | ✅ | clean (Neural Core / HoloSphere OK) |
| Email HQ | `/tools/email-manager` | 🔧 | PR #2072 — bare tokens + literal-hex holdouts (msg row, ai banner, actions, chips) |
| Google Work Suite | `/tools/google-work-suite` | 🔧 | PR #2073 — private `--gws-*` namespace remap |
| Game Studio | `/tools/game-studio` | 🔧 | PR #2073 — private `--gs-*` namespace remap (builder canvas left dark by design) |
| Department HQ | `/tools/department-hq` | 🔧 | this pass — private `--dhq-*` remap + `--dhq-card-bg` + crew card/header. **Overview + Roster verified; deeper tabs (Dispatch/Fleet/COMs/Social/Perf/Devices/Contractors/Autonomy/Approvals) rely on the token remap, not yet individually screenshotted** |
| Agent Academy | `/tools/agent-academy` | 🔧 | this pass — private `--aa-*` remap (RUN BENCHMARK panel was dark) |
| Backup Manager | `/tools/backup-manager` | ✅ | clean |
| C.R.E.E.D. Command | `/tools/creed-command` | ✅ | clean (E.T.H.O.S. KPIs readable) |
| Media Studio | `/tools/media-studio` | ✅ | clean (dashboard readable; the "Page not found" toasts are 404'ing media-backend calls — a data issue, NOT light-mode) |
| WTF Hub | `/tools/wtf-hub` | 🔧 | fixed — `body.light-mode` overrides in the template `<style>` for `.wtf-card`/`.wtf-tab`/`.wtf-btn-sm` + `#wtf-mail-list/read` (`!important` beats inline styles). Template change → platform restart. Overview verified light AND dark (`.wtf-card` stays `#0d1117` in dark) |
| StockBot | `/tools/stockbot` | ⛔ | redirects → Market Watch standalone |
| A.R.C.H.I.E. Chat | `/tools/archie-chat` | ⛔ | redirects → comms service (:3002) |
| Website Designer | `/tools/website-studio` | ⛔ | redirects → dashboard (disabled) |
| System Operations | `/tools/system-operations` | ⛔ | disabled (→ KSO standalone) |
| Media Hub | `/tools/media-hub` | ⛔ | redirects → dashboard (launch tile → standalone) |
| Family Tree | `/tools/family-tree` | ⏳ | |
| Fitness | `/tools/fitness` | ⏳ | |
| Therapy | `/tools/therapy` | ⏳ | |
| DOC | `/tools/doc` | ⏳ | |
| Mailbox Story | `/tools/mailbox-story` | ⏳ | |
| WTF Hub | `/tools/wtf-hub` | ⏳ | |
| SaaS Manager | `/tools/saas-manager` | ⏳ | folded into Account Center ORGS |
| My Profile | `/tools/my-profile` | ⏳ | |
| Archie Pool | `/tools/archie-pool` | ⏳ | |
| Pool Management | `/tools/pool-management` | ⏳ | |

## Root-cause pattern (KB #278763)
1. **`--archie-*` bare-token modules** → fixed globally by the `light-mode.css` alias re-declaration.
2. **Private-namespace modules** (`--gws-*`, `--gs-*`, `--dhq-*`) → dark literals at `:root`,
   unreachable by the shared fix; each needs a `body.light-mode` token remap.
3. **Literal-hex / rgba(0,0,0,x) holdouts** on specific elements → per-element `body.light-mode` override.
Every override is scoped to `body.light-mode`; dark mode stays pixel-identical.
