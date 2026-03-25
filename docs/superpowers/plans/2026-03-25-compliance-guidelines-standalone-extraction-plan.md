# Compliance Guidelines + Standalone Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Codify compliance standards as enforceable rules, then complete the Kytran System Operations standalone migration with full LCARS theme, auth interconnection, and Code Health visibility.

**Architecture:** Two phases — Phase A creates governance documents (rules files + KB entries) that every session loads. Phase B uses those standards as acceptance criteria to complete the KSM standalone, add it to Code Health, fix LCARS theming, and wire auth. Both phases modify platform files; Phase B also modifies the standalone at `/mnt/archie_brain/kytran-server-manager/`.

**Tech Stack:** Markdown (rules files), Python/Flask (code metrics, routes), JavaScript (Consciousness UI), CSS (LCARS frames), PostgreSQL (compliance data), SQLite (standalone DB)

---

## File Map

### Phase A — Compliance Guidelines
| Action | File | Responsibility |
|--------|------|---------------|
| Create | `.claude/rules/compliance-standards.md` | Platform-wide security, code quality, compliance, public posture rules |
| Create | `.claude/rules/standalone-extraction.md` | Tiered extraction playbook for module independence |
| Modify | `memory/MEMORY.md` | Add references to new rules files |

### Phase B — KSM Standalone Completion
| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `platform_v2/services/code_metrics_service.py` | Add `STANDALONE_PRODUCTS` registry, extend `scan_codebase()` |
| Modify | `platform_v2/tools/consciousness/code_health_routes.py` | Add standalone metrics + compliance cross-reference endpoint |
| Modify | `platform_v2/static/js/consciousness.js` | Render standalone section in Code Health tab |
| Modify | `kytran-server-manager/kytran_server_manager/static/css/lcars-frames.css` | Full LCARS frame styling matching admin modules |
| Modify | `kytran-server-manager/kytran_server_manager/templates/dashboard.html` | Apply LCARS frame HTML structure |
| Modify | `kytran-server-manager/kytran_server_manager/templates/login.html` | Apply LCARS styling to login |
| Modify | `kytran-server-manager/kytran_server_manager/auth.py` | Add SSO-ready endpoint stub |
| Create | `kytran-server-manager/kytran_server_manager/routes/proxy_routes.py` | NPM Proxy integration (missing from standalone) |
| Modify | `kytran-server-manager/kytran_server_manager/routes/__init__.py` | Register new proxy routes |
| Modify | `platform_v2/tools/system_operations/routes.py` | Add redirect to standalone (Tier 2 prep) |

---

## Phase A: Compliance Guidelines Foundation

### Task A1: Create `compliance-standards.md` Rules File

**Files:**
- Create: `.claude/rules/compliance-standards.md`

- [ ] **Step 1: Create the rules file**

```markdown
# Compliance Standards (Established 2026-03-25)

Platform-wide security, code quality, compliance scanning, and public posture rules.
These apply to ALL work — platform modules, standalone products, and infrastructure.

## Security Hardening

- All Docker containers: `read_only: true`, no `--privileged`, explicit capability drops
- Resource limits required on every container (CPU + memory in `docker-compose.yml`)
- No secrets in env vars or code — use Docker secrets or `.env` files (never committed)
- DB passwords: `os.getenv("DB_PASSWORD", "")` only, never hardcoded
- TLS required for all external-facing services (NPM proxy + SSL cert)
- UFW firewall: default deny inbound, explicit allow rules only
- SSH: key-only auth, no root login, fail2ban active
- Container images: pinned version tags (no `:latest` in production), trusted base images only
- Tmpfs mounts for writable temp directories inside read-only containers
- Secrets scanning: check for credentials before every commit

## Code Quality

- Route splitting per ADR-045: `register_*_routes(bp, admin_required)` pattern
- No single route file over 600 lines — split by domain
- Service extraction: routes are thin HTTP handlers, business logic in `services/`
- All DB connections: `try/finally: conn.close()` or context manager — no leaks
- Specific exceptions only — no bare `except:`, minimum `except Exception`
- No direct Ollama inference from modules — Bridge dispatcher only (ADR-013)
- Black formatting enforced via pre-commit hook
- No hardcoded IPs or ports — use config/env vars
- Import shared modules (`from db import get_db`) — no local redefinitions

## Compliance Scanning

- Any customer-facing or infrastructure service MUST have a compliance scan profile
- Rule packs: JSON-driven, stored in `rule_packs/` directory — add rules without code changes
- Rule format: `rule_id`, `severity` (low/medium/high), `check_type`, `fix`, `soc2_mapping`
- Scans auto-run every 6 hours via agent loop
- Findings tracked in `compliance_scan_results` with severity + remediation path
- One-click remediation via host command client for automatable fixes
- 5 active rule packs: Ubuntu STIG (51), Docker STIG (30), HIPAA (30), Network STIG (27), CIS Ubuntu (40)

## Public Compliance Posture

- Live SVG badges for all applicable frameworks (STIG, SOC 2, HIPAA, CIS, Network)
- Badge scoring: Green (90%+), Blue (80%+), Yellow (70%+), Red (<60%)
- Grade scale: A+ (95%), A (90%), B+ (85%), B (80%), C (70%), D (60%), F (<60%)
- Trust center page required for any product offered as a service
- SOC 2 evidence collection mapped to 5/5 Trust Service Criteria
- Badge scores auto-refresh from latest scan results
- Competitor comparison page updated when new products ship

## Standalone Products

- All standalone products must follow the extraction playbook in `standalone-extraction.md`
- Standalone products must be registered in Code Health scanner (`STANDALONE_PRODUCTS` in `code_metrics_service.py`)
- Each standalone tracked in Consciousness module with compliance tier status
- See `standalone-extraction.md` for Tier 1/2/3 requirements
```

- [ ] **Step 2: Verify the file loads**

Run: `cat .claude/rules/compliance-standards.md | head -5`
Expected: Shows the header "# Compliance Standards (Established 2026-03-25)"

- [ ] **Step 3: Commit**

```bash
git add .claude/rules/compliance-standards.md
git commit -m "feat(compliance): add platform-wide compliance standards rules file"
```

---

### Task A2: Create `standalone-extraction.md` Rules File

**Files:**
- Create: `.claude/rules/standalone-extraction.md`

- [ ] **Step 1: Create the extraction playbook**

```markdown
# Standalone Extraction Playbook (Established 2026-03-25)

Tiered checklist for pulling any module out of A.R.C.H.I.E. into an independent standalone product.
Every extraction follows this playbook. No exceptions.

## Tier 1 — Must Ship (Blocking Release)

| # | Requirement | Verification |
|---|-------------|-------------|
| 1 | All features from ARCHIE module transferred and working | Side-by-side route audit, browser test every endpoint |
| 2 | Full LCARS theme matching platform admin modules | Frame blocks with sidebar, elbow corners, accent colors, responsive (480/768/1024px) |
| 3 | Authentication — local auth minimum, SSO-ready `/auth/sso` endpoint stubbed (returns 501) | Login flow works end-to-end |
| 4 | Own database (SQLite default, PostgreSQL option) | Zero dependency on ARCHIE's database |
| 5 | Own static assets (CSS/JS self-contained) | No imports from ARCHIE's shared files |
| 6 | Docker-ready: `Dockerfile` + `docker-compose.yml` with compliance (read-only rootfs, resource limits, pinned tags) | `docker compose up` works from clean clone |
| 7 | README with install, configure, run instructions | Someone unfamiliar can get it running in <10 min |
| 8 | Passes Tier 1 compliance checks from `compliance-standards.md` | No hardcoded secrets, resource limits set, pinned tags |
| 9 | Registered in Code Health scanner | Shows in Consciousness module Code Health tab |

## Tier 2 — Within 30 Days of Ship

| # | Requirement | Verification |
|---|-------------|-------------|
| 1 | Auth interconnection — "Sign in with Kytran" OAuth flow | ARCHIE login grants access to standalone |
| 2 | Compliance scanning integrated — runs own relevant rule packs | `/api/compliance/scan` returns results |
| 3 | Live compliance badges on standalone dashboard | SVG badges rendering with real scores |
| 4 | Subdomain with SSL via NPM proxy | `server.kytranempowerment.com` loads over HTTPS |
| 5 | ARCHIE dashboard module replaced with redirect/launch link | Module click opens standalone |
| 6 | Health endpoint for ARCHIE monitoring | `/api/health` returns status + version |
| 7 | Mobile/responsive polish at all breakpoints | Tested at 480px, 768px, 1024px |
| 8 | Code Health shows compliance tier progress | Green/yellow/red badge in Consciousness |

## Tier 3 — Roadmap (Within 90 Days)

| # | Requirement | Verification |
|---|-------------|-------------|
| 1 | SOC 2 evidence collection + PDF reports | Generated PDF passes manual review |
| 2 | S.H.I.E.L.D. agent integration via Bridge dispatch | AI-powered compliance analysis working |
| 3 | Subscription-gated features (free vs paid) | Feature flags + payment flow tested |
| 4 | Node/Starship integration — deployable on fleet nodes | Standalone runs on node hardware |
| 5 | Agent loop job monitoring standalone health | ARCHIE alerts on standalone downtime |
| 6 | Public product page with pricing | Page live on kytranempowerment.com |

## Extraction Process

1. **Audit** — Read every route, template, feature in the ARCHIE module. Document what exists.
2. **Gap analysis** — Compare against standalone. List missing, different, extra.
3. **Migrate** — Transfer missing features. Adapt to standalone architecture.
4. **Theme** — Apply full LCARS frame styling (sidebar + elbows + header bar + segments).
5. **Auth bridge** — SSO endpoint stub (Tier 1) or full OAuth (Tier 2).
6. **Code Health** — Register in `STANDALONE_PRODUCTS` in `code_metrics_service.py`.
7. **Compliance scan** — Run through applicable rule packs. Fix failures.
8. **Redirect** — Replace ARCHIE module with launch link.
9. **Verify** — Browser test all features, compliance green, badges live, Code Health reporting.

## Active Standalone Products

| Product | Port | Path | Tier | Status |
|---------|------|------|------|--------|
| Kytran System Operations | 8085 | `/mnt/archie_brain/kytran-server-manager` | 1 | In Progress |
```

- [ ] **Step 2: Verify the file loads**

Run: `cat .claude/rules/standalone-extraction.md | head -5`
Expected: Shows "# Standalone Extraction Playbook"

- [ ] **Step 3: Commit**

```bash
git add .claude/rules/standalone-extraction.md
git commit -m "feat(compliance): add standalone extraction playbook rules file"
```

---

### Task A3: Store KB Entries via MCP

**Files:** None (database entries via MCP)

- [ ] **Step 1: Store compliance standards in knowledge base**

```python
mcp__archie__store_memory(
    title="Compliance Standards — Platform-Wide Security & Quality Rules",
    content="Platform-wide compliance standards covering security hardening (read-only containers, no secrets in env, TLS, UFW), code quality (ADR-045 route split, service extraction, no bare except), compliance scanning (178 rules, 5 packs, 6h auto-scan), and public posture (live SVG badges, SOC 2 evidence, trust center). See .claude/rules/compliance-standards.md for full rules.",
    knowledge_type="vault_note",
    tags=["compliance", "guidelines", "security", "governance"],
    importance=0.95
)
```

- [ ] **Step 2: Store extraction playbook in knowledge base**

```python
mcp__archie__store_memory(
    title="Standalone Extraction Playbook — Tiered Checklist for Module Independence",
    content="Three-tier playbook for extracting ARCHIE modules into standalone products. Tier 1 (must ship): all features migrated, LCARS theme, auth, Docker-ready, Code Health registered. Tier 2 (30 days): SSO interconnection, compliance scanning, subdomain, badges. Tier 3 (90 days): SOC 2 evidence, S.H.I.E.L.D. integration, subscriptions, node deployment. See .claude/rules/standalone-extraction.md for full checklist.",
    knowledge_type="vault_note",
    tags=["standalone", "extraction", "playbook", "compliance"],
    importance=0.95
)
```

- [ ] **Step 3: Verify both entries are searchable**

```python
mcp__archie__search_knowledge(query="compliance standards standalone extraction", types=["vault_note"], limit=5)
```

Expected: Both entries returned with relevance scores.

---

### Task A4: Update MEMORY.md

**Files:**
- Modify: `/home/kytran/.claude/projects/-mnt-archie-brain/memory/MEMORY.md`

- [ ] **Step 1: Add rules file references to MEMORY.md**

Add after the "6 Behavioral Rules" section, a new section:

```markdown
## Compliance & Extraction Standards (2 files)
- `.claude/rules/compliance-standards.md` — Platform-wide security hardening, code quality, compliance scanning, public posture
- `.claude/rules/standalone-extraction.md` — Tiered playbook (Tier 1/2/3) for extracting modules into standalone products
```

- [ ] **Step 2: Commit**

```bash
git add memory/MEMORY.md
git commit -m "docs(compliance): add compliance + extraction rules to memory index"
```

---

## Phase B: KSM Standalone Completion (Tier 1)

### Task B1: Code Health — Register Standalone in Scanner

**Files:**
- Modify: `platform_v2/services/code_metrics_service.py`

- [ ] **Step 1: Add STANDALONE_PRODUCTS registry**

Add at the top of `code_metrics_service.py` (after imports, before first function):

```python
# Standalone products tracked in Code Health (see .claude/rules/standalone-extraction.md)
STANDALONE_PRODUCTS = [
    {
        "name": "Kytran System Operations",
        "path": "/mnt/archie_brain/kytran-server-manager",
        "module_key": "standalone_kytran_system_operations",
        "tier": 1,
        "compliance_packs": [
            "ubuntu-stig", "docker-stig", "network-stig", "cis-ubuntu", "hipaa"
        ],
    }
]
```

- [ ] **Step 2: Add standalone scanning function**

Add a new function after `_get_module_stats()` (around line 97):

```python
def _get_standalone_stats():
    """Scan registered standalone products and return metrics."""
    standalone_metrics = {}
    for product in STANDALONE_PRODUCTS:
        path = product["path"]
        if not os.path.isdir(path):
            continue
        stats = {"files": 0, "lines": 0, "folders": 0, "by_type": {}}
        type_map = {
            ".py": "python", ".js": "js", ".css": "css",
            ".html": "html", ".sql": "sql", ".sh": "shell", ".json": "json",
        }
        seen_dirs = set()
        for root, dirs, files in os.walk(path):
            dirs[:] = [
                d for d in dirs
                if not d.startswith(".") and d not in ("__pycache__", "node_modules", ".git", "venv", ".venv")
            ]
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                lang = type_map.get(ext)
                if lang is None:
                    continue
                filepath = os.path.join(root, f)
                try:
                    with open(filepath, "r", errors="ignore") as fh:
                        line_count = sum(1 for _ in fh)
                except Exception:
                    line_count = 0
                stats["files"] += 1
                stats["lines"] += line_count
                if lang not in stats["by_type"]:
                    stats["by_type"][lang] = {"files": 0, "lines": 0}
                stats["by_type"][lang]["files"] += 1
                stats["by_type"][lang]["lines"] += line_count
                parent = os.path.dirname(filepath)
                if parent not in seen_dirs:
                    seen_dirs.add(parent)
                    stats["folders"] += 1
        standalone_metrics[product["module_key"]] = stats
    return standalone_metrics
```

- [ ] **Step 3: Integrate into scan_codebase()**

In `scan_codebase()` (line 359), after the existing module scan completes and before the return statement, add:

```python
    # Scan standalone products
    standalone_stats = _get_standalone_stats()
    for key, stats in standalone_stats.items():
        result["modules"][key] = stats
        result["total_files"] += stats["files"]
        result["total_lines"] += stats["lines"]
        result["total_folders"] += stats["folders"]
```

- [ ] **Step 4: Verify scan picks up standalone**

Run: `docker exec archie_platform python3 -c "from services.code_metrics_service import scan_codebase; r = scan_codebase(); print('standalone_kytran_system_operations' in r.get('modules', {}))"`
Expected: `True`

- [ ] **Step 5: Commit**

```bash
git add platform_v2/services/code_metrics_service.py
git commit -m "feat(code-health): register standalone products in Code Health scanner"
```

---

### Task B2: Code Health — Standalone Section in UI

**Files:**
- Modify: `platform_v2/static/js/consciousness.js`
- Modify: `platform_v2/tools/consciousness/templates/consciousness_dashboard.html`

- [ ] **Step 1: Add standalone detection in loadCodeHealth()**

In `loadCodeHealth()` (around line 2620), find where `_renderModuleTable()` is called. Replace or augment it to separate standalone modules from platform modules:

```javascript
// Separate standalone products from platform modules
var standaloneModules = {};
var platformModules = {};
Object.keys(modules).forEach(function(key) {
    if (key.startsWith('standalone_')) {
        standaloneModules[key] = modules[key];
    } else {
        platformModules[key] = modules[key];
    }
});
_renderModuleTable(platformModules, auditedModules, moduleStatusMap, moduleDisplayNames);
_renderStandaloneTable(standaloneModules);
```

- [ ] **Step 2: Add _renderStandaloneTable function**

Add after `_renderModuleTable()` function (around line 2856). Note: uses `setHtml()` helper (already available in consciousness.js) for safe DOM updates where the data is server-controlled metrics, matching the existing pattern used by `_renderModuleTable()`:

```javascript
function _renderStandaloneTable(modules) {
    var el = document.getElementById("chStandaloneTable");
    if (!el) return;
    var keys = Object.keys(modules);
    if (keys.length === 0) {
        el.textContent = "No standalone products registered";
        el.style.cssText = "color:#888;text-align:center;padding:20px;";
        return;
    }
    var rows = keys.map(function(key) {
        var m = modules[key];
        var displayName = key.replace('standalone_', '').replace(/_/g, ' ').replace(/\b\w/g, function(c) { return c.toUpperCase(); });
        var py = (m.by_type && m.by_type.python) || {files: 0, lines: 0};
        var js = (m.by_type && m.by_type.js) || {files: 0, lines: 0};
        var ht = (m.by_type && m.by_type.html) || {files: 0, lines: 0};
        var cs = (m.by_type && m.by_type.css) || {files: 0, lines: 0};
        return '<tr style="border-bottom:1px solid #333;">'
            + '<td style="padding:8px;color:#f59e0b;font-weight:bold;">' + escHtml(displayName) + '</td>'
            + '<td style="text-align:right;padding:8px;">' + (m.files || 0) + '</td>'
            + '<td style="text-align:right;padding:8px;">' + (m.lines || 0).toLocaleString() + '</td>'
            + '<td style="text-align:right;padding:8px;">' + py.lines.toLocaleString() + '</td>'
            + '<td style="text-align:right;padding:8px;">' + js.lines.toLocaleString() + '</td>'
            + '<td style="text-align:right;padding:8px;">' + ht.lines.toLocaleString() + '</td>'
            + '<td style="text-align:right;padding:8px;">' + cs.lines.toLocaleString() + '</td>'
            + '<td style="text-align:center;padding:8px;"><span style="background:#f59e0b;color:#000;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:bold;">TIER 1</span></td>'
            + '</tr>';
    });
    var html = '<table style="width:100%;border-collapse:collapse;font-size:13px;">'
        + '<thead><tr style="border-bottom:2px solid #f59e0b;">'
        + '<th style="text-align:left;padding:8px;color:#f59e0b;">Standalone Product</th>'
        + '<th style="text-align:right;padding:8px;">Files</th>'
        + '<th style="text-align:right;padding:8px;">Lines</th>'
        + '<th style="text-align:right;padding:8px;">Python</th>'
        + '<th style="text-align:right;padding:8px;">JS</th>'
        + '<th style="text-align:right;padding:8px;">HTML</th>'
        + '<th style="text-align:right;padding:8px;">CSS</th>'
        + '<th style="text-align:center;padding:8px;">Tier</th>'
        + '</tr></thead><tbody>' + rows.join('') + '</tbody></table>';
    setHtml(el, html);
}
```

- [ ] **Step 3: Add standalone section HTML in Consciousness template**

In the Code Health tab of `consciousness_dashboard.html`, find the module table card and add after it:

```html
<div class="cs-card" style="margin-top:20px;">
    <div class="cs-card-title" style="color:#f59e0b;">
        <i class="fas fa-rocket"></i> Standalone Products
    </div>
    <div id="chStandaloneTable"></div>
</div>
```

- [ ] **Step 4: Deploy and verify**

```bash
docker compose restart archie_platform
```

Navigate to `http://192.168.1.200:3000/tools/consciousness` -> Code Health tab. Verify standalone section appears with gold accent and KSM metrics.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/static/js/consciousness.js platform_v2/tools/consciousness/templates/consciousness_dashboard.html
git commit -m "feat(code-health): add standalone products section to Code Health UI"
```

---

### Task B3: LCARS Theme — Match Admin Module Frame Styling

**Files:**
- Modify: `kytran-server-manager/kytran_server_manager/static/css/lcars-frames.css`
- Modify: `kytran-server-manager/kytran_server_manager/templates/dashboard.html`
- Modify: `kytran-server-manager/kytran_server_manager/templates/login.html`

- [ ] **Step 1: Read the current LCARS frame patterns from admin modules**

Read the LCARS frame HTML structure from working admin modules to understand the exact pattern:
- `platform_v2/templates/tools/backup_manager.html` — look for `.lcars-frame`, sidebar, elbow, segment classes
- `platform_v2/templates/tools/security_network.html` — same pattern

Document the exact HTML structure and CSS classes used so the standalone matches.

- [ ] **Step 2: Update lcars-frames.css to match platform frame styling**

Ensure `lcars-frames.css` has the full frame component set. The current standalone has basic frames but is missing the full sidebar + elbow + segment structure that makes the admin modules look distinctive. Update to include:

```css
/* Full LCARS Frame System — matches A.R.C.H.I.E. admin modules */

.lcars-frame {
    display: flex;
    flex-direction: row;
    min-height: 100vh;
    background: var(--bg-primary, #0a0a0f);
}

.lcars-sidebar {
    width: var(--frame-sidebar-w, 48px);
    display: flex;
    flex-direction: column;
    flex-shrink: 0;
}

.lcars-sidebar-segment {
    width: 100%;
    height: var(--frame-seg-h, 28px);
    margin-bottom: var(--frame-seg-gap, 4px);
    border-radius: var(--frame-radius, 20px) 0 0 var(--frame-radius, 20px);
    background: var(--frame-color);
    opacity: 0.7;
}

.lcars-sidebar-segment.active {
    opacity: 1;
    box-shadow: 0 0 12px rgba(var(--frame-rgb), 0.4);
}

.lcars-elbow-top {
    width: var(--frame-sidebar-w, 48px);
    height: var(--frame-elbow-top-h, 52px);
    background: var(--frame-color);
    border-radius: var(--frame-radius, 20px) 0 0 0;
    flex-shrink: 0;
}

.lcars-elbow-bottom {
    width: var(--frame-sidebar-w, 48px);
    height: var(--frame-elbow-bottom-h, 36px);
    background: var(--frame-color);
    border-radius: 0 0 0 var(--frame-radius, 20px);
    flex-shrink: 0;
    margin-top: auto;
}

.lcars-header-bar {
    height: var(--frame-bar-h, 44px);
    background: var(--frame-color);
    display: flex;
    align-items: center;
    padding: 0 20px;
    border-radius: 0 var(--frame-radius, 20px) 0 0;
    margin-left: 4px;
    flex-grow: 1;
}

.lcars-header-bar .lcars-title {
    font-family: 'Antonio', sans-serif;
    font-size: 1.4rem;
    color: var(--bg-primary, #0a0a0f);
    text-transform: uppercase;
    letter-spacing: 2px;
    font-weight: 700;
}

.lcars-footer-bar {
    height: var(--frame-footer-h, 16px);
    background: var(--frame-color);
    border-radius: 0 0 var(--frame-radius, 20px) 0;
    margin-left: 4px;
    opacity: 0.6;
}

.lcars-main {
    flex: 1;
    display: flex;
    flex-direction: column;
    margin-left: 4px;
    overflow-y: auto;
}

.lcars-content {
    flex: 1;
    padding: 20px;
}

/* Responsive */
@media (max-width: 768px) {
    .lcars-sidebar { width: 32px; }
    .lcars-sidebar-segment { height: 20px; }
    .lcars-header-bar { height: 36px; }
    .lcars-header-bar .lcars-title { font-size: 1rem; }
}

@media (max-width: 480px) {
    .lcars-sidebar { width: 24px; }
    .lcars-header-bar .lcars-title { font-size: 0.85rem; letter-spacing: 1px; }
}
```

- [ ] **Step 3: Update dashboard.html to use frame structure**

Wrap the existing dashboard content in the LCARS frame structure:

```html
<div class="lcars-frame">
    <div class="lcars-sidebar">
        <div class="lcars-elbow-top"></div>
        <div class="lcars-sidebar-segment active"></div>
        <div class="lcars-sidebar-segment"></div>
        <div class="lcars-sidebar-segment"></div>
        <div class="lcars-sidebar-segment"></div>
        <div class="lcars-sidebar-segment"></div>
        <div class="lcars-elbow-bottom"></div>
    </div>
    <div class="lcars-main">
        <div class="lcars-header-bar">
            <span class="lcars-title">Kytran System Operations</span>
        </div>
        <div class="lcars-content">
            <!-- existing dashboard content goes here -->
        </div>
        <div class="lcars-footer-bar"></div>
    </div>
</div>
```

- [ ] **Step 4: Apply same frame to login.html**

Update `login.html` to use a centered LCARS frame:

```html
<div class="lcars-frame" style="justify-content:center;align-items:center;min-height:100vh;">
    <div style="max-width:400px;width:100%;">
        <div class="lcars-header-bar" style="border-radius:var(--frame-radius);">
            <span class="lcars-title">System Access</span>
        </div>
        <!-- existing login form -->
    </div>
</div>
```

- [ ] **Step 5: Browser test**

Open `http://192.168.1.200:8085` and verify:
- Left sidebar with colored segments visible
- Top header bar with "Kytran System Operations" title
- Elbow corners connecting sidebar to header
- Footer bar at bottom
- Content area fills remaining space
- Test at 768px and 480px widths for responsive behavior

- [ ] **Step 6: Commit**

```bash
cd /mnt/archie_brain/kytran-server-manager
git add kytran_server_manager/static/css/lcars-frames.css kytran_server_manager/templates/dashboard.html kytran_server_manager/templates/login.html
git commit -m "feat(theme): apply full LCARS frame styling matching A.R.C.H.I.E. admin modules"
```

---

### Task B4: Migrate Missing Routes — NPM Proxy Integration

**Files:**
- Create: `kytran-server-manager/kytran_server_manager/routes/proxy_routes.py`
- Modify: `kytran-server-manager/kytran_server_manager/routes/__init__.py`

- [ ] **Step 1: Read the ARCHIE proxy_routes.py**

Read `platform_v2/tools/system_operations/proxy_routes.py` (143 lines) to understand all NPM proxy endpoints and adapt for standalone.

- [ ] **Step 2: Create standalone proxy_routes.py**

```python
"""NPM (Nginx Proxy Manager) integration routes for standalone."""

from flask import jsonify
import requests
import os


NPM_BASE = os.getenv("NPM_API_URL", "http://192.168.1.200:81/api")
NPM_TOKEN = None


def _get_npm_token():
    """Get or refresh NPM API token."""
    global NPM_TOKEN
    if NPM_TOKEN:
        return NPM_TOKEN
    email = os.getenv("NPM_EMAIL", "")
    password = os.getenv("NPM_PASSWORD", "")
    if not email or not password:
        return None
    try:
        resp = requests.post(
            f"{NPM_BASE}/tokens",
            json={"identity": email, "secret": password},
            timeout=10,
        )
        if resp.status_code == 200:
            NPM_TOKEN = resp.json().get("token")
            return NPM_TOKEN
    except Exception:
        pass
    return None


def _npm_headers():
    """Build auth headers for NPM API."""
    token = _get_npm_token()
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def register_proxy_routes(bp, admin_required):
    @bp.route("/api/proxy/hosts", methods=["GET"])
    @admin_required
    def proxy_hosts():
        """List all proxy hosts from NPM."""
        try:
            resp = requests.get(
                f"{NPM_BASE}/nginx/proxy-hosts",
                headers=_npm_headers(),
                timeout=10,
            )
            if resp.status_code == 200:
                return jsonify({"success": True, "hosts": resp.json()})
            return jsonify({"success": False, "error": f"NPM returned {resp.status_code}"}), resp.status_code
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/proxy/hosts/<int:host_id>", methods=["GET"])
    @admin_required
    def proxy_host_detail(host_id):
        """Get single proxy host details."""
        try:
            resp = requests.get(
                f"{NPM_BASE}/nginx/proxy-hosts/{host_id}",
                headers=_npm_headers(),
                timeout=10,
            )
            if resp.status_code == 200:
                return jsonify({"success": True, "host": resp.json()})
            return jsonify({"success": False, "error": f"NPM returned {resp.status_code}"}), resp.status_code
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/proxy/certificates", methods=["GET"])
    @admin_required
    def proxy_certificates():
        """List SSL certificates from NPM."""
        try:
            resp = requests.get(
                f"{NPM_BASE}/nginx/certificates",
                headers=_npm_headers(),
                timeout=10,
            )
            if resp.status_code == 200:
                return jsonify({"success": True, "certificates": resp.json()})
            return jsonify({"success": False, "error": f"NPM returned {resp.status_code}"}), resp.status_code
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/proxy/status", methods=["GET"])
    @admin_required
    def proxy_status():
        """Check NPM connectivity."""
        try:
            token = _get_npm_token()
            if not token:
                return jsonify({
                    "success": False,
                    "status": "disconnected",
                    "error": "No NPM credentials configured. Set NPM_EMAIL and NPM_PASSWORD env vars.",
                })
            resp = requests.get(
                f"{NPM_BASE}/nginx/proxy-hosts",
                headers=_npm_headers(),
                timeout=5,
            )
            return jsonify({
                "success": True,
                "status": "connected",
                "host_count": len(resp.json()) if resp.status_code == 200 else 0,
            })
        except Exception as e:
            return jsonify({"success": False, "status": "error", "error": str(e)})
```

- [ ] **Step 3: Register proxy routes in __init__.py**

In `kytran-server-manager/kytran_server_manager/routes/__init__.py`, add the import:

```python
from .proxy_routes import register_proxy_routes
```

And in `register_all_routes()`, add the call:

```python
register_proxy_routes(bp, admin_required_decorator)
```

- [ ] **Step 4: Verify routes load**

```bash
cd /mnt/archie_brain/kytran-server-manager
python3 -c "from kytran_server_manager.routes.proxy_routes import register_proxy_routes; print('OK')"
```

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain/kytran-server-manager
git add kytran_server_manager/routes/proxy_routes.py kytran_server_manager/routes/__init__.py
git commit -m "feat(proxy): add NPM proxy integration routes to standalone"
```

---

### Task B5: Auth — Add SSO-Ready Endpoint Stub

**Files:**
- Modify: `kytran-server-manager/kytran_server_manager/auth.py`
- Modify: `kytran-server-manager/kytran_server_manager/templates/login.html`

- [ ] **Step 1: Read current auth.py**

Read `kytran-server-manager/kytran_server_manager/auth.py` to understand the current Flask-Login setup, the route registration pattern, and the `User` class.

- [ ] **Step 2: Add SSO endpoint stub**

Add to `auth.py` after the existing `/login` route:

```python
@app.route("/auth/sso", methods=["GET", "POST"])
def sso_login():
    """SSO endpoint stub -- ready for Tier 2 'Sign in with Kytran' OAuth flow.

    Tier 2 will implement:
    - GET: Redirect to ARCHIE OAuth authorization URL
    - POST: Handle OAuth callback, create/link local user, set session

    For now, returns 501 to signal the endpoint exists but is not yet implemented.
    """
    return jsonify({
        "error": "SSO not yet configured",
        "message": "Sign in with Kytran will be available in a future update. Use local login.",
        "tier": 2,
        "docs": "See standalone-extraction.md Tier 2 requirements",
    }), 501


@app.route("/auth/sso/status", methods=["GET"])
def sso_status():
    """Check SSO configuration status."""
    return jsonify({
        "sso_enabled": False,
        "provider": "kytran",
        "auth_url": None,
        "message": "SSO pending Tier 2 implementation",
    })
```

- [ ] **Step 3: Add SSO indicator on login page**

In `login.html`, add below the existing login form:

```html
<div style="text-align:center;margin-top:20px;padding-top:16px;border-top:1px solid rgba(var(--frame-rgb),0.2);">
    <p style="color:#666;font-size:12px;">
        Sign in with Kytran &mdash; Coming Soon
    </p>
</div>
```

- [ ] **Step 4: Verify endpoint responds**

```bash
curl -s http://192.168.1.200:8085/auth/sso | python3 -m json.tool
```

Expected: `{"error": "SSO not yet configured", ...}` with HTTP 501

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain/kytran-server-manager
git add kytran_server_manager/auth.py kytran_server_manager/templates/login.html
git commit -m "feat(auth): add SSO-ready endpoint stub for Tier 2 Kytran OAuth"
```

---

### Task B6: Code Health — Compliance Cross-Reference Endpoint

**Files:**
- Modify: `platform_v2/tools/consciousness/code_health_routes.py`

- [ ] **Step 1: Read current code_health_routes.py**

Read the full file at `platform_v2/tools/consciousness/code_health_routes.py` to understand the existing endpoint patterns, imports, and DB access.

- [ ] **Step 2: Add standalone status endpoint**

Add a new route after the existing endpoints:

```python
@bp.route("/api/code-health/standalone-status")
@login_required
@admin_required
def code_health_standalone_status():
    """Return standalone product metrics with compliance tier info."""
    from services.code_metrics_service import STANDALONE_PRODUCTS, _get_standalone_stats

    standalone_stats = _get_standalone_stats()
    results = []
    for product in STANDALONE_PRODUCTS:
        key = product["module_key"]
        stats = standalone_stats.get(key, {})

        # Check compliance scan results if available
        compliance_score = None
        last_scan = None
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute("""
                SELECT overall_score, scanned_at
                FROM compliance_scans
                WHERE scan_target = %s
                ORDER BY scanned_at DESC LIMIT 1
            """, (product["name"],))
            row = cur.fetchone()
            if row:
                compliance_score = float(row[0]) if row[0] else None
                last_scan = row[1].isoformat() if row[1] else None
        except Exception:
            pass
        finally:
            if conn:
                conn.close()

        results.append({
            "name": product["name"],
            "module_key": key,
            "tier": product["tier"],
            "path": product["path"],
            "files": stats.get("files", 0),
            "lines": stats.get("lines", 0),
            "by_type": stats.get("by_type", {}),
            "compliance_score": compliance_score,
            "last_compliance_scan": last_scan,
            "compliance_packs": product.get("compliance_packs", []),
        })

    return jsonify({"success": True, "standalones": results})
```

Note: Use whatever DB import pattern the file already uses (`get_db()`, `get_db_cursor()`, etc.). Read the file first to match.

- [ ] **Step 3: Deploy and verify endpoint**

```bash
docker compose restart archie_platform
```

Test the endpoint (requires auth cookie):
```bash
curl -s -b cookies.txt http://192.168.1.200:3000/tools/consciousness/api/code-health/standalone-status | python3 -m json.tool
```

Expected: JSON with KSM entry showing files, lines, tier, compliance data.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/consciousness/code_health_routes.py
git commit -m "feat(code-health): add standalone compliance cross-reference endpoint"
```

---

### Task B7: Log Decision + Update Project + Deploy + Verify

**Files:** None (MCP calls + deployment)

- [ ] **Step 1: Log architectural decision**

```python
mcp__archie__log_decision(
    decision="Compliance standards codified as .claude/rules/ files + KB entries. Standalone extraction follows 3-tier playbook. Code Health extended with STANDALONE_PRODUCTS registry. KSM is first standalone product tracked.",
    context="Compliance push achieved 100% (178 checks). Need to maintain standards for all future work and standalone extractions. System Operations is first module extracted from ARCHIE.",
    project_id=193
)
```

- [ ] **Step 2: Update project understanding**

```python
mcp__archie__update_project_understanding(project_id=193)
```

- [ ] **Step 3: Final deployment**

```bash
docker compose restart archie_platform
```

- [ ] **Step 4: Browser verification checklist**

Open each URL and verify:
- [ ] `http://192.168.1.200:3000/tools/consciousness` -> Code Health tab -> standalone section visible with gold accent
- [ ] KSM metrics showing (files, lines, language breakdown)
- [ ] `http://192.168.1.200:8085` -> LCARS frame visible (sidebar, header, elbows)
- [ ] `http://192.168.1.200:8085/auth/sso` -> returns 501 JSON
- [ ] `http://192.168.1.200:8085/dashboard/api/proxy/status` -> returns proxy status

- [ ] **Step 5: Complete task in Dev HQ**

```python
mcp__archie__complete_task(task_id=1407, notes="Phase A + B Tier 1 plan executed. Compliance rules files created, KB entries stored, Code Health extended for standalones, LCARS theme applied, proxy routes migrated, SSO stub added.")
```

---

## Task Summary

| Task | Phase | Description | Est. |
|------|-------|-------------|------|
| A1 | A | Create `compliance-standards.md` rules file | 3 min |
| A2 | A | Create `standalone-extraction.md` rules file | 3 min |
| A3 | A | Store KB entries via MCP | 2 min |
| A4 | A | Update MEMORY.md | 2 min |
| B1 | B | Code Health — register standalone in scanner | 5 min |
| B2 | B | Code Health — standalone section in UI | 5 min |
| B3 | B | LCARS theme — match admin module frames | 10 min |
| B4 | B | Migrate NPM proxy routes | 5 min |
| B5 | B | Auth — SSO endpoint stub | 3 min |
| B6 | B | Code Health — compliance cross-reference | 5 min |
| B7 | B | Log decision + deploy + verify | 5 min |

**Total: 11 tasks, ~48 minutes**

**Phase A** (Tasks A1-A4): Foundation — rules files + KB. No code changes, all governance.
**Phase B** (Tasks B1-B7): Implementation — Code Health, LCARS, proxy, auth, deploy.
