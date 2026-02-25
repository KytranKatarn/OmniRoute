# Dashboard "Starship Bridge" Redesign — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Full rebuild of the ARCHIE Dashboard into a layered "Starship Bridge" command center with cinematic boot sequence, HUD vitals, mission briefing, featured modules, and responsive category grid.

**Architecture:** Single-template rebuild of `dashboard_dynamic.html` (~2,793 lines → new). Backend gets 4 new API endpoints in `app.py` for system stats, AI status, recent activity, and alerts. `dashboard_generator.py` gets minor extensions for featured module support. All CSS inline in template (matches existing module pattern). Three responsive breakpoints: 374px, 717px, 1280px+.

**Tech Stack:** Flask/Jinja2, vanilla CSS (--archie-* token system), vanilla JS, Lucide icons, Canvas API (matrix rain), existing `/api/modules/health` and `/api/module-agents` endpoints.

**Design Doc:** `docs/plans/2026-02-18-dashboard-redesign-design.md`

---

## Task 1: Add Backend API Endpoints

4 new API endpoints in `app.py` to power the HUD vitals and mission briefing sections.

**Files:**
- Modify: `platform_v2/app.py` (after line ~998, the dashboard route block)

**Step 1: Add `/api/dashboard/system-stats` endpoint**

Insert after the dashboard route (after line 998 in app.py). This endpoint returns CPU, memory, disk, and uptime for the HUD vitals strip.

```python
@app.route("/api/dashboard/system-stats")
@login_required
def api_dashboard_system_stats():
    """System stats for dashboard HUD vitals"""
    import psutil

    try:
        uptime_seconds = int(time.time() - start_time)
        hours, remainder = divmod(uptime_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)

        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage("/")

        return jsonify({
            "success": True,
            "cpu_percent": cpu_percent,
            "memory_percent": memory.percent,
            "memory_used_gb": round(memory.used / (1024**3), 1),
            "memory_total_gb": round(memory.total / (1024**3), 1),
            "disk_percent": disk.percent,
            "disk_used_gb": round(disk.used / (1024**3), 1),
            "disk_total_gb": round(disk.total / (1024**3), 1),
            "uptime_seconds": uptime_seconds,
            "uptime_formatted": f"{hours}h {minutes}m {seconds}s",
        })
    except Exception as e:
        logger.error(f"System stats API error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
```

**Step 2: Add `/api/dashboard/ai-status` endpoint**

```python
@app.route("/api/dashboard/ai-status")
@login_required
def api_dashboard_ai_status():
    """AI bridge status for dashboard HUD"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get active agents count
        cur.execute("SELECT COUNT(*) as count FROM agents WHERE status = 'active'")
        agent_count = cur.fetchone()["count"]

        # Get today's AI interaction count
        cur.execute(
            "SELECT COUNT(*) as count FROM orchestration_sessions WHERE created_at >= CURRENT_DATE"
        )
        today_interactions = cur.fetchone()["count"]

        # Get service statuses for AI-related services
        cur.execute(
            "SELECT service_name, status FROM service_status WHERE service_name IN ('ollama', 'ai_bridge', 'consciousness')"
        )
        services = {row["service_name"]: row["status"] for row in cur.fetchall()}

        cur.close()
        conn.close()

        # Determine overall AI status
        ai_online = all(s == "online" for s in services.values()) if services else True

        return jsonify({
            "success": True,
            "ai_online": ai_online,
            "active_agents": agent_count,
            "today_interactions": today_interactions,
            "services": services,
        })
    except Exception as e:
        logger.error(f"AI status API error: {e}")
        return jsonify({"success": True, "ai_online": True, "active_agents": 0, "today_interactions": 0, "services": {}})
```

**Step 3: Add `/api/dashboard/recent-activity` endpoint**

```python
@app.route("/api/dashboard/recent-activity")
@login_required
def api_dashboard_recent_activity():
    """Recent user activity for mission briefing"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT action, module, details, created_at, username
            FROM user_activity_log
            ORDER BY created_at DESC
            LIMIT 10
            """
        )
        activities = cur.fetchall()
        cur.close()
        conn.close()

        return jsonify({
            "success": True,
            "activities": [
                {
                    "action": a["action"],
                    "module": a["module"],
                    "details": a["details"],
                    "username": a["username"],
                    "timestamp": a["created_at"].isoformat() if a["created_at"] else None,
                }
                for a in activities
            ],
        })
    except Exception as e:
        logger.error(f"Recent activity API error: {e}")
        return jsonify({"success": True, "activities": []})
```

**Step 4: Add `/api/dashboard/alerts` endpoint**

```python
@app.route("/api/dashboard/alerts")
@login_required
def api_dashboard_alerts():
    """System alerts for mission briefing"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get unread notifications as alerts
        cur.execute(
            """
            SELECT type, title, message, priority, created_at
            FROM notifications
            WHERE user_id = %s AND is_read = FALSE
            ORDER BY created_at DESC
            LIMIT 10
            """,
            (current_user.id,),
        )
        alerts = cur.fetchall()

        # Get service health issues
        cur.execute(
            "SELECT service_name, status, error_message FROM service_status WHERE status != 'online'"
        )
        service_issues = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({
            "success": True,
            "alerts": [
                {
                    "type": a["type"],
                    "title": a["title"],
                    "message": a["message"],
                    "priority": a["priority"],
                    "timestamp": a["created_at"].isoformat() if a["created_at"] else None,
                }
                for a in alerts
            ],
            "service_issues": [
                {
                    "service": s["service_name"],
                    "status": s["status"],
                    "error": s["error_message"],
                }
                for s in service_issues
            ],
        })
    except Exception as e:
        logger.error(f"Alerts API error: {e}")
        return jsonify({"success": True, "alerts": [], "service_issues": []})
```

**Step 5: Verify psutil is available in Docker**

Run: `docker exec archie_platform python3 -c "import psutil; print(psutil.cpu_percent())"`

If missing, add to requirements and rebuild. If available, proceed.

**Step 6: Restart container and test endpoints**

Run:
```bash
docker compose restart archie_platform
# Wait 10s for startup
curl -s http://192.168.1.200:3000/api/dashboard/system-stats -b "session=<cookie>" | python3 -m json.tool
```

Expected: JSON with cpu_percent, memory_percent, uptime fields.

**Step 7: Commit**

```bash
git add platform_v2/app.py
git commit -m "feat(dashboard): add 4 API endpoints for Starship Bridge HUD vitals and mission briefing"
```

---

## Task 2: Rebuild Dashboard Template — Boot Sequence + Background

The first major chunk of the template: cinematic boot overlay and ambient background.

**Files:**
- Modify: `platform_v2/templates/dashboard_dynamic.html` — rewrite from scratch

**Step 1: Back up current template**

```bash
cp platform_v2/templates/dashboard_dynamic.html platform_v2/templates/dashboard_dynamic.html.bak
```

**Step 2: Write the template skeleton + boot sequence + background**

Create the new `dashboard_dynamic.html` with:
- Jinja2 extends `base.html`
- All CSS in `{% block styles %}`
- Boot sequence overlay HTML + CSS + JS
- Matrix rain canvas + nebula gradient background
- Placeholder sections for remaining content

The boot sequence must implement:
- Phase 0: Pure black, cursor blink (0-0.3s)
- Phase 1: Typing "INITIALIZING A.R.C.H.I.E. CORE..." with screen flicker (0.3-1s)
- Phase 2: 6 subsystem progress bars filling sequentially (1-2.5s)
- Phase 3: Amber "THREAT LEVEL: NOMINAL" flash + screen shake (2.5-3s)
- Phase 4: ARCHIE logo + ring pulse + "SYSTEM ONLINE" (3-3.5s)
- Phase 5: Overlay splits horizontally (3.5-4s)
- Skip button in bottom-right, localStorage `archie-boot-skip` remembers

Matrix rain: slower, opacity 0.15, katakana + binary + "ARCHIE".
Nebula: animated radial gradient, 60s cycle, dark blue/purple/black.
Light mode: no matrix rain, subtle gradient mesh.

Use the `/frontend-design` skill for the actual visual implementation of this section.

**Step 3: Test boot sequence in browser**

Navigate to `http://192.168.1.200:3000/dashboard` and verify:
- Boot sequence plays through all 5 phases
- Skip button works and remembers via localStorage
- Matrix rain renders on canvas
- Light mode disables matrix rain

**Step 4: Commit**

```bash
git add platform_v2/templates/dashboard_dynamic.html
git commit -m "feat(dashboard): rebuild template with cinematic boot sequence and ambient background"
```

---

## Task 3: Command Bar + HUD Vitals Strip

The top navigation bar and live system vitals.

**Files:**
- Modify: `platform_v2/templates/dashboard_dynamic.html` (add to existing skeleton)

**Step 1: Add Command Bar HTML + CSS**

Fixed 48px glassmorphic bar:
- Left: user avatar circle (first letter of username), display name, role badge, tier badge
- Center: search input with magnifying glass icon and "Ctrl+K" hint
- Right: notification bell with unread count badge, theme toggle (sun/moon via archie-theme.js), Dev HQ link (admin only), logout button
- On scroll: add `.scrolled` class with bottom border glow

Template data available from Jinja2 context:
- `{{ current_user.username }}` — username
- `{{ dashboard_data.user_role }}` — role (ADMIN, PREMIUM, USER, etc.)
- `{{ dashboard_data.subscription_tier }}` — tier (admin, pro, free)

**Step 2: Add HUD Vitals Strip HTML + CSS + JS**

6 glassmorphic stat pods below command bar:
- System Health (aggregate ring gauge)
- CPU Load (ring gauge)
- Memory (ring gauge with used/total label)
- AI Status (pulsing dot + ONLINE/OFFLINE label)
- Active Agents (count + icon)
- Uptime (formatted duration)

JavaScript: fetch `/api/dashboard/system-stats` and `/api/dashboard/ai-status` every 15 seconds. Animate ring gauges with CSS `conic-gradient` or SVG circle `stroke-dashoffset`.

Responsive:
- 1280px+: 6 pods in a flex row
- 717px: horizontal scroll strip
- 374px: 2x3 CSS grid

**Step 3: Test in browser at all 3 breakpoints**

Verify:
- Command bar sticks to top on scroll
- HUD vitals populate from API
- Ring gauges animate on data load
- Responsive layout works at 374px, 717px, 1280px

**Step 4: Commit**

```bash
git add platform_v2/templates/dashboard_dynamic.html
git commit -m "feat(dashboard): add command bar and HUD vitals strip with live system stats"
```

---

## Task 4: Mission Briefing Row

Three info cards below the HUD strip.

**Files:**
- Modify: `platform_v2/templates/dashboard_dynamic.html`

**Step 1: Add Mission Briefing HTML + CSS + JS**

3 LCARS-framed cards in a flex row (stack on mobile):

1. **Recent Activity** card:
   - LCARS framed header: cyan accent, "RECENT ACTIVITY" title, activity icon
   - Fetch `/api/dashboard/recent-activity`
   - Show last 5 items: action icon + description + relative timestamp ("2m ago")
   - Empty state: "No recent activity"

2. **System Alerts** card:
   - LCARS framed header: amber accent, "SYSTEM ALERTS" title, alert icon
   - Fetch `/api/dashboard/alerts`
   - Color-coded items: green (all clear), amber (warnings), red (critical)
   - Show unread notification alerts + service health issues
   - Empty state: green "ALL SYSTEMS NOMINAL" message

3. **AI Insights** card:
   - LCARS framed header: purple accent, "AI INSIGHTS" title, brain icon
   - Data from `/api/dashboard/ai-status`
   - Show: today's interaction count, active agent count, consciousness status
   - Mini bar showing interaction trend (placeholder, static for now)

Each card: `border-radius: 12px`, glassmorphic background, LCARS top/bottom gradient lines matching accent color.

Responsive:
- 1280px+: 3 columns
- 717px: 3 columns (narrower)
- 374px: single column stacked

**Step 2: Test in browser**

Verify all 3 cards render, data populates, responsive stacking works.

**Step 3: Commit**

```bash
git add platform_v2/templates/dashboard_dynamic.html
git commit -m "feat(dashboard): add mission briefing row with activity, alerts, and AI insights"
```

---

## Task 5: Featured Modules Section

Large pinned module cards.

**Files:**
- Modify: `platform_v2/templates/dashboard_dynamic.html`
- Modify: `platform_v2/dashboard_generator.py` (add featured module logic)

**Step 1: Extend dashboard_generator.py**

Add a `get_featured_modules()` function that returns default featured modules (archie-chat, bridge-command, dev-hq) or user-pinned modules from localStorage (sent as query param). Add the featured modules to the `get_user_dashboard_data()` return dict.

```python
def get_featured_modules(user, pinned_ids=None) -> list:
    """Get featured/pinned modules for dashboard hero section"""
    default_pins = ["archie-chat", "bridge-command", "dev-hq"]
    pin_ids = pinned_ids if pinned_ids else default_pins

    enabled_modules = get_enabled_modules()
    featured = []
    for module in enabled_modules:
        if module.id in pin_ids and can_access_module(module.id, user):
            featured.append({
                "id": module.id,
                "name": module.name,
                "description": module.description,
                "icon": module.icon,
                "route": module.route,
                "category": module.category.value,
            })

    # Maintain pin order
    return sorted(featured, key=lambda m: pin_ids.index(m["id"]) if m["id"] in pin_ids else 99)
```

**Step 2: Add Featured Modules HTML + CSS**

Section with LCARS framed header "PRIORITY STATIONS".
2-3 large cards (~300px height desktop):
- Module icon (large, centered)
- Module name (bold, uppercase)
- Description text
- Live status dot (fetched via existing `/api/modules/health`)
- "Last accessed" timestamp (placeholder text for now)
- Hover: translateY(-8px), glow matching category color
- Pin/unpin toggle button (star icon, toggles localStorage `archie-pinned-modules`)

Category colors on hover border:
- admin_operations / ai_command: `#cc6600`
- development_tools: `#00808f`
- saas_services: `#7c3aed`
- project_knowledge: `#00aa33`
- media_home: `#db2777`

Responsive:
- 1280px+: 3 columns
- 717px: 2 columns
- 374px: 1 column, cards full-width

**Step 3: Test featured modules render and pin/unpin**

**Step 4: Commit**

```bash
git add platform_v2/templates/dashboard_dynamic.html platform_v2/dashboard_generator.py
git commit -m "feat(dashboard): add featured modules section with pin/unpin support"
```

---

## Task 6: Category Grid with Collapsible Panels

The main module listing, organized by category.

**Files:**
- Modify: `platform_v2/templates/dashboard_dynamic.html`

**Step 1: Add Category Grid HTML + CSS + JS**

For each category in `dashboard_data.modules_by_category`:
- **Category panel**: collapsible section
- **LCARS framed header**: category icon + name + module count badge + collapse chevron (▼/▲)
  - Admin badge if category is admin-only
  - Top/bottom gradient lines in category color
- **Compact card grid** inside panel:
  - Each card: Lucide icon + module name + status dot
  - Clickable (links to module route)
  - Coming-soon cards: muted, non-clickable, "COMING SOON" badge
  - Beta cards: "BETA" badge
  - Hover: brief description tooltip, border color → category accent, subtle lift

Collapse state saved in localStorage `archie-dashboard-collapsed` (JSON array of collapsed category keys).

Staggered entry animation: each card delayed by `index * 0.05s`, uses `cardMaterialize` keyframe.

Category accent colors (CSS custom properties per category):
```css
.category-admin_operations { --cat-accent: #cc6600; }
.category-ai_command { --cat-accent: #cc6600; }
.category-development_tools { --cat-accent: #00808f; }
.category-saas_services { --cat-accent: #7c3aed; }
.category-project_knowledge { --cat-accent: #00aa33; }
.category-media_home { --cat-accent: #db2777; }
.category-placeholders_future { --cat-accent: #8b949e; }
```

Grid responsive:
- 1280px+: 4 columns
- 717px: 2 columns
- 374px: 1 column

**Step 2: Add module health status fetching**

JavaScript: on page load, fetch `/api/modules/health` and update each card's status dot:
- Green pulsing dot + "ONLINE" for healthy
- Red dot + "OFFLINE" for unhealthy
- Amber dot + "DEGRADED" for degraded
- Gray dot + "CHECKING..." as default/loading state

Also fetch `/api/module-agents` for each module to show agent-on-shift badge.

**Step 3: Test at all breakpoints**

Verify:
- All categories render with correct colors
- Collapse/expand works and persists
- Module cards link correctly
- Status dots update from health API
- Agent badges display

**Step 4: Commit**

```bash
git add platform_v2/templates/dashboard_dynamic.html
git commit -m "feat(dashboard): add collapsible category grid with health status and agent badges"
```

---

## Task 7: Status Footer + Final Polish

Footer bar and overall cleanup.

**Files:**
- Modify: `platform_v2/templates/dashboard_dynamic.html`

**Step 1: Add Status Footer HTML + CSS**

Slim bar at bottom (not fixed — scrolls with content):
- Left: system time with blinking `:` separator (updated every second via JS), version badge "v5.32.0"
- Right: green connection dot + "Connected" label, "Last refreshed Xs ago" counter

**Step 2: Light mode pass**

Add `[data-theme="light"]` overrides for all new sections:
- Boot sequence: dark bg stays (cinematic should always be dark)
- Command bar: light glassmorphic bg
- HUD pods: light borders, dark text
- Mission briefing cards: light bg, dark text
- Featured cards: light bg
- Category grid: light bg cards
- Footer: light bg

**Step 3: Accessibility check**

- All interactive elements have `tabindex` or are native focusable elements
- Color contrast meets WCAG AA (4.5:1 for text)
- Status dots have text labels (not color-only)
- Skip button in boot sequence is keyboard-accessible

**Step 4: Remove backup file**

```bash
rm platform_v2/templates/dashboard_dynamic.html.bak
```

**Step 5: Commit**

```bash
git add platform_v2/templates/dashboard_dynamic.html
git commit -m "feat(dashboard): add status footer, light mode, and accessibility polish"
```

---

## Task 8: Playwright Visual Regression Tests

Capture screenshots at all breakpoints for visual baseline.

**Files:**
- Existing: `platform_v2/tests/visual_baseline.mjs`

**Step 1: Run Playwright visual baseline**

```bash
node platform_v2/tests/visual_baseline.mjs --username admin --password 'Kyt$13ran2025'
```

Note: The boot sequence takes ~4s. The visual baseline script may need a longer wait to capture post-boot content. If captures show boot overlay, add a delay or JS injection to skip boot:

```bash
# If needed, use Playwright to dismiss boot overlay:
# page.evaluate(() => { document.querySelector('.boot-overlay')?.remove(); })
```

**Step 2: Capture at all 3 breakpoints manually if needed**

Use Playwright MCP or manual browser testing:
- 374px (Fold5 closed)
- 717px (Fold5 open)
- 1280px+ (Desktop)

Verify: boot sequence, command bar, HUD vitals, mission briefing, featured modules, category grid, footer all render correctly.

**Step 3: Commit screenshots**

```bash
git add screenshots/
git commit -m "test(dashboard): add Playwright visual regression screenshots for Starship Bridge"
```

---

## Task 9: Deploy and Update Dev HQ

Container restart and project tracking updates.

**Step 1: Restart platform container**

```bash
docker compose restart archie_platform
```

**Step 2: Verify live dashboard**

Navigate to `http://192.168.1.200:3000/dashboard` and verify all sections work.

**Step 3: Update Dev HQ via MCP**

- `mcp complete_task` — task #628 "Redesign: Dashboard"
- `mcp update_project_understanding` — project #94, note dashboard rebuild completion
- `mcp log_decision` — document the "Starship Bridge" approach choice
- `mcp store_memory` — update roadmap vault note with dashboard status

**Step 4: Final commit (if any remaining changes)**

```bash
git add -A && git commit -m "chore(dashboard): post-deploy cleanup" && git push
```
