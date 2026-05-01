# Agent Social Presence Engine — Phase 2: Content Calendar + Auto-Suggest

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Kytran Empowerment's S.I.G.N.A.L. a weekly content calendar where themed posts auto-generate and queue for approval, and gap detection nudges via Telegram when a day is empty.

**Architecture:** New `social_content_calendar` (weekly slots) and `agent_social_voice` (per-agent frequency + sample phrases) tables. `calendar_service.py` handles all CRUD and themed caption generation by extending the existing `generate_post_content` with theme tone context. A new DHQ S.I.G.N.A.L. "Calendar" sub-tab shows a week grid. An APScheduler job runs at 8am daily to auto-fill slots and detect gaps.

**Tech Stack:** Flask + Jinja2 + vanilla JS, PostgreSQL, LCARS aesthetic, APScheduler (already in agent_loop.py), DHQ dispatch for S.I.G.N.A.L. caption writing. Builds on Phase 1 (social_content_themes table, theme_service.py).

---

## Prerequisites (must exist from Phase 1)
- `social_content_themes` table with 9 themes (migration 363)
- `platform_v2/tools/media_studio/services/theme_service.py`
- `platform_v2/tools/department_hq/theme_routes.py`

---

## File Structure

| Action | Path | Purpose |
|--------|------|---------|
| Create | `database/migrations/364_social_content_calendar.sql` | Calendar slots + voice extension tables |
| Create | `platform_v2/tools/media_studio/services/calendar_service.py` | Calendar CRUD + themed caption generation |
| Modify | `platform_v2/tools/department_hq/theme_routes.py` | Add 9 calendar + voice API routes |
| Modify | `platform_v2/tools/department_hq/static/js/department-hq.js` | Calendar sub-tab + week grid UI |
| Modify | `platform_v2/ai_bridge/agent_loop.py` | Daily auto-suggest worker (8am) |

---

### Task 1: Migration 364 — social_content_calendar + agent_social_voice

**Files:**
- Create: `database/migrations/364_social_content_calendar.sql`

- [ ] **Step 1: Write the migration**

```sql
-- database/migrations/364_social_content_calendar.sql

CREATE TABLE IF NOT EXISTS social_content_calendar (
    id SERIAL PRIMARY KEY,
    day_of_week SMALLINT NOT NULL CHECK (day_of_week BETWEEN 0 AND 6),
    slot_order SMALLINT DEFAULT 0,
    theme_id INTEGER REFERENCES social_content_themes(id),
    featured_agent_id INTEGER REFERENCES agents(id),
    auto_generate BOOLEAN DEFAULT false,
    time_of_day TIME DEFAULT '09:00:00',
    platform VARCHAR(50) DEFAULT 'linkedin',
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (day_of_week, slot_order)
);

CREATE TABLE IF NOT EXISTS agent_social_voice (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER UNIQUE REFERENCES agents(id),
    post_frequency_per_week SMALLINT DEFAULT 2,
    sample_phrases TEXT[] DEFAULT '{}',
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_scc_day ON social_content_calendar(day_of_week);
CREATE INDEX IF NOT EXISTS idx_asv_agent ON agent_social_voice(agent_id);

-- Seed 3 default weekly slots: Mon=Live the Dream, Wed=Wellness, Fri=Build & Innovate
INSERT INTO social_content_calendar (day_of_week, slot_order, theme_id, featured_agent_id, auto_generate, time_of_day)
VALUES
  (0, 0, (SELECT id FROM social_content_themes WHERE slug='live-dream'), (SELECT id FROM agents WHERE name='S.I.G.N.A.L.' LIMIT 1), false, '09:00:00'),
  (2, 0, (SELECT id FROM social_content_themes WHERE slug='wellness-healing'), (SELECT id FROM agents WHERE name='V.I.T.A.L.' LIMIT 1), false, '10:00:00'),
  (4, 0, (SELECT id FROM social_content_themes WHERE slug='build-innovate'), (SELECT id FROM agents WHERE name='F.O.R.G.E.' LIMIT 1), false, '09:00:00')
ON CONFLICT (day_of_week, slot_order) DO NOTHING;
```

- [ ] **Step 2: Run the migration**

```bash
docker exec -i archie_database psql -U archie -d archie < /mnt/archie_brain/database/migrations/364_social_content_calendar.sql
```

Expected output: `CREATE TABLE`, `CREATE TABLE`, `CREATE INDEX x2`, `INSERT 0 3`

- [ ] **Step 3: Verify**

```bash
docker exec archie_database psql -U archie -d archie -c "
SELECT c.day_of_week, t.name AS theme, a.display_name AS agent, c.auto_generate
FROM social_content_calendar c
JOIN social_content_themes t ON t.id = c.theme_id
LEFT JOIN agents a ON a.id = c.featured_agent_id
ORDER BY c.day_of_week;"
```

Expected: 3 rows for days 0 (Mon), 2 (Wed), 4 (Fri).

- [ ] **Step 4: Commit**

```bash
git add database/migrations/364_social_content_calendar.sql
git commit -m "feat(social-presence): migration 364 — social_content_calendar + agent_social_voice + 3 default slots"
```

---

### Task 2: calendar_service.py

**Files:**
- Create: `platform_v2/tools/media_studio/services/calendar_service.py`

- [ ] **Step 1: Write the service**

```python
# platform_v2/tools/media_studio/services/calendar_service.py
"""Calendar service — weekly content slots + themed caption generation."""
import logging
from datetime import date, timedelta
from typing import Dict, List, Optional

from database import get_db_cursor

logger = logging.getLogger(__name__)

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def get_week_calendar() -> List[Dict]:
    """Return all 7 days with their slots + status of queued items this week."""
    monday = date.today() - timedelta(days=date.today().weekday())
    week_dates = [monday + timedelta(days=i) for i in range(7)]

    with get_db_cursor() as (conn, cur):
        cur.execute("""
            SELECT c.*, t.name AS theme_name, t.accent_color,
                   a.display_name AS agent_name, a.name AS agent_slug
            FROM social_content_calendar c
            LEFT JOIN social_content_themes t ON t.id = c.theme_id
            LEFT JOIN agents a ON a.id = c.featured_agent_id
            WHERE c.is_active = true
            ORDER BY c.day_of_week, c.slot_order
        """)
        slots = [dict(r) for r in cur.fetchall()]

        # Check which days have social_video_queue items this week
        cur.execute("""
            SELECT EXTRACT(DOW FROM created_at)::int AS dow, status, COUNT(*) AS cnt
            FROM social_video_queue
            WHERE created_at >= %s AND created_at < %s + INTERVAL '7 days'
            GROUP BY dow, status
        """, (monday, monday))
        queue_status = {}
        for r in cur.fetchall():
            dow = (r["dow"] - 1) % 7  # convert Sun=0 to Mon=0
            queue_status.setdefault(dow, []).append({"status": r["status"], "count": r["cnt"]})

    days = []
    slot_by_day = {}
    for s in slots:
        slot_by_day.setdefault(s["day_of_week"], []).append(s)

    for i in range(7):
        days.append({
            "day_of_week": i,
            "day_name": DAY_NAMES[i],
            "date": week_dates[i].isoformat(),
            "slots": slot_by_day.get(i, []),
            "queue_status": queue_status.get(i, []),
        })
    return days


def get_calendar_slots() -> List[Dict]:
    """Return all active calendar slots."""
    with get_db_cursor() as (conn, cur):
        cur.execute("""
            SELECT c.*, t.name AS theme_name, t.accent_color,
                   a.display_name AS agent_name
            FROM social_content_calendar c
            LEFT JOIN social_content_themes t ON t.id = c.theme_id
            LEFT JOIN agents a ON a.id = c.featured_agent_id
            ORDER BY c.day_of_week, c.slot_order
        """)
        return [dict(r) for r in cur.fetchall()]


def upsert_calendar_slot(day_of_week: int, slot_order: int = 0, **kwargs) -> Dict:
    """Create or update a calendar slot."""
    allowed = {"theme_id", "featured_agent_id", "auto_generate", "time_of_day",
               "platform", "is_active"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    with get_db_cursor(commit=True) as (conn, cur):
        set_clause = ", ".join(f"{k} = EXCLUDED.{k}" for k in fields) if fields else "is_active = is_active"
        insert_cols = ["day_of_week", "slot_order"] + list(fields.keys())
        insert_vals = [day_of_week, slot_order] + list(fields.values())
        placeholders = ", ".join(["%s"] * len(insert_cols))
        cur.execute(f"""
            INSERT INTO social_content_calendar ({', '.join(insert_cols)})
            VALUES ({placeholders})
            ON CONFLICT (day_of_week, slot_order) DO UPDATE SET {set_clause}
            RETURNING *
        """, insert_vals)
        return dict(cur.fetchone())


def delete_calendar_slot(slot_id: int) -> bool:
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("DELETE FROM social_content_calendar WHERE id = %s", (slot_id,))
        return cur.rowcount > 0


def get_agent_voice(agent_id: int) -> Dict:
    """Return agent voice settings (combines agents table + agent_social_voice)."""
    with get_db_cursor() as (conn, cur):
        cur.execute("""
            SELECT a.writing_tone, a.writing_style, a.social_topics,
                   v.post_frequency_per_week, v.sample_phrases
            FROM agents a
            LEFT JOIN agent_social_voice v ON v.agent_id = a.id
            WHERE a.id = %s
        """, (agent_id,))
        row = cur.fetchone()
        if not row:
            return {}
        return {
            "tone": row["writing_tone"] or "professional",
            "style": row["writing_style"] or "",
            "social_topics": row["social_topics"] or [],
            "post_frequency_per_week": row["post_frequency_per_week"] or 2,
            "sample_phrases": row["sample_phrases"] or [],
        }


def upsert_agent_voice(agent_id: int, **kwargs) -> Dict:
    """Update agent_social_voice extended fields."""
    allowed = {"post_frequency_per_week", "sample_phrases"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return get_agent_voice(agent_id)
    cols = list(fields.keys())
    vals = list(fields.values()) + [agent_id]
    set_clause = ", ".join(f"{k} = %s" for k in cols)
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(f"""
            INSERT INTO agent_social_voice (agent_id, {', '.join(cols)})
            VALUES ({', '.join(['%s'] * (len(cols) + 1))})
            ON CONFLICT (agent_id) DO UPDATE SET {set_clause}, updated_at = NOW()
        """, [agent_id] + list(fields.values()) + list(fields.values()))
    return get_agent_voice(agent_id)


def generate_themed_caption(agent_id: int, theme_id: int, scene_description: str = "") -> str:
    """Generate a social media caption for an agent in a specific theme's tone.

    Extends the existing generate_post_content with theme context.
    Returns caption text or empty string on failure.
    """
    from services.agent_service import get_agent
    from services.agent_social_service import get_writing_voice

    from .theme_service import get_theme

    agent = get_agent(agent_id)
    theme = get_theme(theme_id)
    if not agent or not theme:
        return ""

    voice = get_writing_voice(agent_id) or {}
    name = agent.get("display_name") or agent.get("name", "")
    dept = agent.get("department", "")
    tone = voice.get("tone", "professional")
    theme_tone = theme.get("tone", "")
    hashtags = " ".join(theme.get("hashtags", [])[:3])

    scene_hint = f" Scene: {scene_description}." if scene_description else ""
    prompt = (
        f"Write a short social media post (2-3 sentences max) as {name}, "
        f"who works in {dept}. "
        f"Theme: {theme.get('name', '')}. Tone: {theme_tone or tone}.{scene_hint} "
        f"Write in first person. Be authentic, human, and engaging. "
        f"End with: {hashtags}"
    )

    try:
        from tools.department_hq.services.department_dispatcher import dispatch_json

        result = dispatch_json(prompt, capability="content_writing")
        if result.get("success"):
            return result.get("response", "").strip()
    except Exception as exc:
        logger.warning("generate_themed_caption failed for agent %s: %s", agent_id, exc)
    return ""


def get_slots_due_for_generation(days_ahead: int = 3) -> List[Dict]:
    """Return calendar slots that are auto_generate=true and have no queued item today+N days."""
    today = date.today()
    due = []
    for offset in range(days_ahead):
        target = today + timedelta(days=offset)
        dow = target.weekday()  # Mon=0 ... Sun=6
        with get_db_cursor() as (conn, cur):
            cur.execute("""
                SELECT c.*, t.name AS theme_name, t.slug AS theme_slug,
                       t.accent_color, t.tone AS theme_tone, t.hashtags,
                       a.display_name AS agent_name, a.id AS agent_id_val
                FROM social_content_calendar c
                JOIN social_content_themes t ON t.id = c.theme_id
                LEFT JOIN agents a ON a.id = c.featured_agent_id
                WHERE c.day_of_week = %s AND c.auto_generate = true AND c.is_active = true
            """, (dow,))
            slots = [dict(r) for r in cur.fetchall()]

            for slot in slots:
                # Check if already queued for this target date
                cur.execute("""
                    SELECT id FROM social_video_queue
                    WHERE theme_id = %s
                    AND created_at::date = %s
                """, (slot["theme_id"], target.isoformat()))
                if not cur.fetchone():
                    slot["target_date"] = target.isoformat()
                    due.append(slot)
    return due


def get_empty_days_this_week() -> List[int]:
    """Return day_of_week values that have no queued content this week."""
    monday = date.today() - timedelta(days=date.today().weekday())
    with get_db_cursor() as (conn, cur):
        cur.execute("""
            SELECT DISTINCT ((EXTRACT(DOW FROM created_at)::int + 6) % 7) AS dow
            FROM social_video_queue
            WHERE created_at >= %s AND created_at < %s + INTERVAL '7 days'
        """, (monday, monday))
        posted_days = {r["dow"] for r in cur.fetchall()}
    return [d for d in range(7) if d not in posted_days]
```

- [ ] **Step 2: Verify imports in container**

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0, '/app')
from tools.media_studio.services.calendar_service import get_week_calendar, get_calendar_slots
slots = get_calendar_slots()
print(f'OK: {len(slots)} calendar slots')
for s in slots:
    print(f'  Day {s[\"day_of_week\"]}: {s[\"theme_name\"]} — {s[\"agent_name\"]}')
" 2>&1
```

Expected: `OK: 3 calendar slots` with Mon/Wed/Fri and their themes.

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/media_studio/services/calendar_service.py
git commit -m "feat(social-presence): calendar_service.py — week calendar, slot CRUD, agent voice, themed caption generation"
```

---

### Task 3: Calendar + Voice API Routes

**Files:**
- Modify: `platform_v2/tools/department_hq/theme_routes.py`

- [ ] **Step 1: Add 9 routes to `theme_routes.py` in `register_theme_routes()`**

Add these after the existing 5 theme routes:

```python
    # ── Calendar ──────────────────────────────────────────────────

    @bp.route("/api/signal/calendar")
    @admin_required
    def api_signal_calendar():
        """Return week calendar with slots and queue status."""
        from platform_v2.tools.media_studio.services.calendar_service import get_week_calendar
        return jsonify({"days": get_week_calendar()})

    @bp.route("/api/signal/calendar/slots")
    @admin_required
    def api_signal_calendar_slots():
        """Return all active calendar slots."""
        from platform_v2.tools.media_studio.services.calendar_service import get_calendar_slots
        return jsonify({"slots": get_calendar_slots()})

    @bp.route("/api/signal/calendar/slots", methods=["POST"])
    @admin_required
    def api_signal_upsert_slot():
        """Create or update a calendar slot."""
        from platform_v2.tools.media_studio.services.calendar_service import upsert_calendar_slot
        data = request.get_json() or {}
        slot = upsert_calendar_slot(
            day_of_week=data.get("day_of_week", 0),
            slot_order=data.get("slot_order", 0),
            **{k: v for k, v in data.items() if k not in ("day_of_week", "slot_order")},
        )
        return jsonify(slot), 201

    @bp.route("/api/signal/calendar/slots/<int:slot_id>", methods=["DELETE"])
    @admin_required
    def api_signal_delete_slot(slot_id):
        """Delete a calendar slot."""
        from platform_v2.tools.media_studio.services.calendar_service import delete_calendar_slot
        ok = delete_calendar_slot(slot_id)
        return jsonify({"deleted": ok})

    @bp.route("/api/signal/calendar/generate-caption", methods=["POST"])
    @admin_required
    def api_signal_generate_caption():
        """Generate a themed caption for an agent via S.I.G.N.A.L. dispatch."""
        from platform_v2.tools.media_studio.services.calendar_service import generate_themed_caption
        data = request.get_json() or {}
        agent_id = data.get("agent_id")
        theme_id = data.get("theme_id")
        scene = data.get("scene_description", "")
        if not agent_id or not theme_id:
            return jsonify({"error": "agent_id and theme_id required"}), 400
        caption = generate_themed_caption(agent_id, theme_id, scene)
        return jsonify({"caption": caption})

    # ── Agent Voice ────────────────────────────────────────────────

    @bp.route("/api/signal/agent/<int:agent_id>/voice")
    @admin_required
    def api_signal_agent_voice(agent_id):
        """Return agent voice settings."""
        from platform_v2.tools.media_studio.services.calendar_service import get_agent_voice
        return jsonify(get_agent_voice(agent_id))

    @bp.route("/api/signal/agent/<int:agent_id>/voice", methods=["PATCH"])
    @admin_required
    def api_signal_update_agent_voice(agent_id):
        """Update agent_social_voice extended fields."""
        from platform_v2.tools.media_studio.services.calendar_service import upsert_agent_voice
        data = request.get_json() or {}
        voice = upsert_agent_voice(agent_id, **data)
        return jsonify(voice)
```

- [ ] **Step 2: Restart and test**

```bash
docker compose restart archie_platform && sleep 4
```

Navigate to `http://192.168.1.200:3000/tools/department-hq/api/signal/calendar` (logged in as admin) — expect JSON with `{"days": [...7 items...]}`.

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/department_hq/theme_routes.py
git commit -m "feat(social-presence): 7 calendar + voice API routes in theme_routes.py"
```

---

### Task 4: DHQ S.I.G.N.A.L. Calendar Sub-tab UI

**Files:**
- Modify: `platform_v2/tools/department_hq/static/js/department-hq.js`

> **Context:** In `department-hq.js`, the S.I.G.N.A.L. sub-tabs are rendered in `renderSignalShell()` as a string concat. The `loadSignalTab(tab)` switch dispatches to render functions. Phase 1 added `Themes` as the last sub-tab. This task adds `Calendar` between `Hashtags` and `Themes`.

- [ ] **Step 1: Add Calendar button to sub-tab bar**

Find `'<button class="signal-sub" data-sub="themes"'` and insert BEFORE it:

```javascript
        + '<button class="signal-sub" data-sub="calendar" onclick="switchSignalTab(\'calendar\')">📅 Calendar</button>'
```

- [ ] **Step 2: Add `calendar` case to `loadSignalTab` switch**

Find `case 'themes':    await renderSignalThemes(el);    break;` and add BEFORE it:

```javascript
            case 'calendar':  await renderSignalCalendar(el);  break;
```

- [ ] **Step 3: Add `renderSignalCalendar` function**

Find `async function renderSignalThemes(el)` and add BEFORE it:

```javascript
async function renderSignalCalendar(el) {
    var data = await api('/api/signal/calendar');
    var days = data.days || [];
    var DAY_NAMES = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'];
    var html = '<div style="margin-bottom:10px;color:#555;font-size:0.6rem;letter-spacing:2px;text-transform:uppercase;">Content Calendar — This Week</div>'
        + '<div style="display:grid;grid-template-columns:repeat(7,1fr);gap:6px;">';
    for (var i = 0; i < days.length; i++) {
        var day = days[i];
        var slots = day.slots || [];
        var queueItems = day.queue_status || [];
        var hasContent = queueItems.length > 0;
        var dayColor = hasContent ? '#22c55e' : '#333';
        html += '<div style="background:#0d1117;border:1px solid ' + dayColor + '44;border-radius:6px;padding:8px;min-height:80px;">'
            + '<div style="font-size:0.55rem;color:' + dayColor + ';font-family:\'Orbitron\',sans-serif;margin-bottom:5px;">' + DAY_NAMES[i].substring(0,3).toUpperCase() + '</div>'
            + '<div style="font-size:0.5rem;color:#444;margin-bottom:5px;">' + day.date + '</div>';
        if (slots.length === 0) {
            html += '<div style="font-size:0.52rem;color:#333;font-style:italic;">No slot</div>';
        } else {
            for (var j = 0; j < slots.length; j++) {
                var slot = slots[j];
                var themeColor = slot.accent_color || '#8b5cf6';
                html += '<div style="border-left:2px solid ' + themeColor + ';padding-left:4px;margin-bottom:4px;">'
                    + '<div style="font-size:0.5rem;color:' + themeColor + ';">' + esc(slot.theme_name || '') + '</div>'
                    + '<div style="font-size:0.48rem;color:#555;">' + esc(slot.agent_name || '—') + '</div>'
                    + (slot.auto_generate ? '<div style="font-size:0.45rem;color:#a78bfa;">⚡ auto</div>' : '')
                    + '</div>';
            }
        }
        if (hasContent) {
            html += '<div style="font-size:0.48rem;color:#22c55e;margin-top:4px;">✓ ' + queueItems.length + ' queued</div>';
        }
        html += '</div>';
    }
    html += '</div>'
        + '<div style="margin-top:12px;font-size:0.58rem;color:#555;">Click a slot to edit · Toggle ⚡ auto to enable auto-generation</div>';
    setHtml(el, html);
}
```

- [ ] **Step 4: Restart and verify**

```bash
docker compose restart archie_platform
```

Navigate to DHQ → S.I.G.N.A.L. → Calendar sub-tab. Should show a 7-column week grid with Mon/Wed/Fri having theme slots (Live the Dream, Wellness & Healing, Build & Innovate).

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/department_hq/static/js/department-hq.js
git commit -m "feat(social-presence): DHQ S.I.G.N.A.L. Calendar sub-tab — 7-column week grid with theme slots + queue status"
```

---

### Task 5: APScheduler Auto-Suggest Worker

**Files:**
- Modify: `platform_v2/ai_bridge/agent_loop.py`

> **Context:** agent_loop.py has an APScheduler. Workers are registered in `start()` using `self.scheduler.add_job(...)`. Worker methods are defined as `def _method_name(self):`. The file is large (~7000 lines). Phase 1 added `social_video_slideshow_render` (every 2 min). Find it to know where to add the new job.
>
> The Telegram service sends messages via `self.telegram_service.send_info(...)` or `_send_telegram(...)`. Check how other workers send Telegram messages.

- [ ] **Step 1: Find the slideshow render job registration**

```bash
grep -n "social_video_slideshow_render\|social_video_generate\b" /mnt/archie_brain/platform_v2/ai_bridge/agent_loop.py | head -5
```

Note the line number of the slideshow render job registration block.

- [ ] **Step 2: Add the auto-suggest job registration**

Add immediately after the slideshow render job:

```python
        # Job #66: Social content auto-suggest (daily 8am)
        self.scheduler.add_job(
            with_app_context(self._social_content_auto_suggest),
            "cron",
            hour=8,
            minute=0,
            id="social_content_auto_suggest",
            name="S.I.G.N.A.L.: Content Auto-Suggest",
            replace_existing=True,
        )
```

- [ ] **Step 3: Find where `_social_video_slideshow_render` method ends**

```bash
grep -n "def _social_video_slideshow_render\|def _social_video_publish\|def _vigilil" /mnt/archie_brain/platform_v2/ai_bridge/agent_loop.py | head -5
```

Note the line where a new method should be inserted (after `_social_video_slideshow_render` ends, before `_vigilil_network_health`).

- [ ] **Step 4: Add `_social_content_auto_suggest` method**

Insert before `# ── V.I.G.I.L. Handler Methods ──`:

```python
    def _social_content_auto_suggest(self):
        """Daily 8am: auto-generate queued content for calendar slots + detect gaps."""
        try:
            from platform_v2.tools.media_studio.services.calendar_service import (
                generate_themed_caption,
                get_empty_days_this_week,
                get_slots_due_for_generation,
            )
            from platform_v2.tools.media_studio.services.social_video_service import svq_create

            # Auto-generate for slots marked auto_generate=true
            due = get_slots_due_for_generation(days_ahead=3)
            for slot in due:
                agent_id = slot.get("featured_agent_id") or slot.get("agent_id_val")
                theme_id = slot.get("theme_id")
                if not agent_id or not theme_id:
                    continue
                caption = generate_themed_caption(agent_id, theme_id)
                if not caption:
                    logger.warning("[AutoSuggest] Caption generation failed for slot %s", slot.get("id"))
                    continue
                svq_create(
                    title=slot.get("theme_name", "Untitled"),
                    quote_text=caption,
                    media_ids=[],
                    audio_mode="music",
                    platform=slot.get("platform", "linkedin"),
                    scheduled_at=None,
                    user_id=1,
                    theme_id=theme_id,
                )
                logger.info("[AutoSuggest] Queued auto-generate for slot %s (theme: %s)", slot.get("id"), slot.get("theme_name"))

            # Gap detection — notify via Telegram if tomorrow is empty
            from datetime import date, timedelta
            tomorrow_dow = (date.today() + timedelta(days=1)).weekday()
            empty = get_empty_days_this_week()
            if tomorrow_dow in empty:
                from services.telegram_service import send_info
                day_names = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
                try:
                    send_info(
                        f"📅 S.I.G.N.A.L. Calendar: {day_names[tomorrow_dow]} has no content queued. "
                        f"Visit Media Studio → Social Video to create a post."
                    )
                except Exception as tg_err:
                    logger.debug("[AutoSuggest] Telegram notify failed (non-blocking): %s", tg_err)

        except Exception as e:
            logger.exception("[AutoSuggest] Worker error: %s", e)
```

- [ ] **Step 5: Restart and verify job registered**

```bash
docker compose restart archie_platform && sleep 5
docker logs archie_platform --tail 30 2>&1 | grep -i "auto.suggest\|social.*content\|error" | head -10
```

Expected: no errors. The job registers silently at startup.

- [ ] **Step 6: Smoke-test the worker manually**

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0, '/app')
from tools.media_studio.services.calendar_service import get_slots_due_for_generation, get_empty_days_this_week
due = get_slots_due_for_generation()
empty = get_empty_days_this_week()
print(f'Slots due: {len(due)}')
print(f'Empty days this week: {empty}')
" 2>&1
```

Expected: `Slots due: 0` (since `auto_generate=false` in seed) and `Empty days: [0,1,2,3,4,5,6]` (no posts yet).

- [ ] **Step 7: Commit**

```bash
git add platform_v2/ai_bridge/agent_loop.py
git commit -m "feat(social-presence): social_content_auto_suggest worker — daily 8am auto-generate + gap detection Telegram"
```

---

### Task 6: Push + End-to-End Verification

- [ ] **Step 1: Push all commits**

```bash
git push origin main
```

- [ ] **Step 2: Verify DB tables**

```bash
docker exec archie_database psql -U archie -d archie -c "
SELECT table_name FROM information_schema.tables
WHERE table_name IN ('social_content_calendar','agent_social_voice')
ORDER BY table_name;"
```

Expected: 2 rows.

- [ ] **Step 3: Verify calendar slots**

```bash
docker exec archie_database psql -U archie -d archie -c "
SELECT c.day_of_week, t.name AS theme, a.display_name AS agent, c.auto_generate
FROM social_content_calendar c
JOIN social_content_themes t ON t.id = c.theme_id
LEFT JOIN agents a ON a.id = c.featured_agent_id
ORDER BY c.day_of_week;"
```

Expected: 3 rows (Mon, Wed, Fri).

- [ ] **Step 4: Browser verification**

Navigate to `http://192.168.1.200:3000/tools/department-hq` → S.I.G.N.A.L. tab:
- [ ] "📅 Calendar" sub-tab button appears next to Themes
- [ ] Click Calendar → 7-column week grid shows
- [ ] Mon, Wed, Fri cells show theme badge + agent name
- [ ] Other days show "No slot" in dim text

- [ ] **Step 5: Verify calendar API**

Navigate to `http://192.168.1.200:3000/tools/department-hq/api/signal/calendar` — expect 7-day JSON.

- [ ] **Step 6: Enable auto-generate on one slot and run worker manually**

```bash
docker exec archie_database psql -U archie -d archie -c "
UPDATE social_content_calendar SET auto_generate = true WHERE day_of_week = 0;"

docker exec archie_platform python3 -c "
import sys; sys.path.insert(0, '/app')
from tools.media_studio.services.calendar_service import get_slots_due_for_generation
slots = get_slots_due_for_generation(days_ahead=7)
print(f'Slots due after enable: {len(slots)}')
for s in slots:
    print(f'  Day {s[\"day_of_week\"]}: {s[\"theme_name\"]}')
" 2>&1
```

Expected: at least 1 slot returned for Monday (day 0).

---

## What Phase 3 Adds (separate plan)

- Lifestyle / Selfie / Announcement generation modes in Media Studio Generate tab
- IP-Adapter ComfyUI workflow for face consistency in lifestyle images
- M.U.S.E. prompt refinement per scene before sending to P.I.X.E.L.
- Per-agent social accounts (Task #2511) as a zero-architecture-change layer
