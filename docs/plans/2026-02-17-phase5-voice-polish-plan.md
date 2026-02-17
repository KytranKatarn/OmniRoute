# Phase 5: Voice Integration Polish — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add STT input UI to Chat tab, voice sidebar for config/status/metrics, profile locking UX in Consciousness Voice tab, and backend endpoints for cache invalidation and recent activity.

**Architecture:** 4 components — STT input (mic button + waveform in chat input area), voice sidebar (collapsible right panel in chat), profile locking UX (warnings + indicators in Consciousness), and 2 new backend endpoints. One migration adds lock audit metadata. collaboration.js already has complete STT code — we wire the DOM elements it expects.

**Tech Stack:** HTML/CSS (Jinja2 templates), vanilla JS, Python/Flask (routes), PostgreSQL (migration)

**Security note:** All dynamic content uses DOM methods (createElement/textContent). The few places using innerHTML contain only static strings with developer-controlled values (lucide icon names, numeric metrics), not user-provided content. This matches existing codebase patterns.

---

### Task 1: Database Migration — Lock Audit Metadata

**Files:**
- Create: `database/migrations/109_voice_locking_metadata.sql`

**Step 1: Write the migration SQL**

```sql
-- Migration 109: Voice locking audit metadata
-- Adds locked_at timestamp and locked_with_params to track when/how cache was locked

ALTER TABLE voice_word_cache
ADD COLUMN IF NOT EXISTS locked_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS locked_with_params JSONB;

-- Backfill: set locked_at for already-locked entries to their last update time
UPDATE voice_word_cache
SET locked_at = COALESCE(last_used, created_at, NOW())
WHERE is_locked = TRUE AND locked_at IS NULL;

COMMENT ON COLUMN voice_word_cache.locked_at IS 'When this entry was locked (immutability timestamp)';
COMMENT ON COLUMN voice_word_cache.locked_with_params IS 'Voice parameters snapshot at lock time (speaker, speed, pitch, warmth, engine)';
```

**Step 2: Run the migration**

Run: `docker exec archie_database psql -U archie -d archie` and paste the SQL.

**Step 3: Verify**

Run: `docker exec archie_database psql -U archie -d archie -c "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'voice_word_cache' AND column_name IN ('locked_at', 'locked_with_params');"`

Expected: 2 rows (locked_at timestamp, locked_with_params jsonb).

**Step 4: Commit**

---

### Task 2: Backend — Update Pre-gen Locking + New Endpoints

**Files:**
- Modify: `platform_v2/tools/consciousness/voice_pregen.py` (lines 529-550, lock function)
- Modify: `platform_v2/tools/archie_core/routes.py` (after line 1326, add 2 endpoints)
- Modify: `platform_v2/tools/consciousness/routes.py` (add 1 endpoint for profile lock status)

**Step 1: Update voice_pregen.py lock function to set locked_at + locked_with_params**

In `voice_pregen.py`, find the two `UPDATE voice_word_cache SET is_locked = TRUE` statements (around lines 529-550). Update both to also set `locked_at` and `locked_with_params`.

For the agent-specific lock (line 533-541), change the SQL to:

```sql
UPDATE voice_word_cache
SET is_locked = TRUE,
    locked_at = NOW(),
    locked_with_params = (
        SELECT jsonb_build_object(
            'speaker', avp.speaker,
            'speed', avp.speed,
            'pitch_shift', avp.pitch_shift,
            'warmth', avp.warmth,
            'engine', avp.engine,
            'voice_blend', avp.voice_blend
        )
        FROM agent_voice_profiles avp
        WHERE avp.agent_id = %s AND avp.engine = %s AND avp.language = %s
        LIMIT 1
    )
WHERE agent_id = %s AND engine = %s AND language = %s
AND is_locked = FALSE
```

Parameters: `(agent_id, effective_engine, language, agent_id, effective_engine, language)`

For the global lock (lines 544-550), keep `locked_with_params = NULL`:

```sql
UPDATE voice_word_cache
SET is_locked = TRUE, locked_at = NOW()
WHERE agent_id IS NULL AND engine = %s AND language = %s
AND is_locked = FALSE
```

Also update the hardcoded ARCHIE lock (lines 288-299) with the same `locked_at = NOW()` addition.

**Step 2: Add `GET /api/voice/recent` endpoint to routes.py**

After the last voice endpoint (after line 1326), add:

```python
@archie_chat_bp.route("/api/voice/recent", methods=["GET"])
@login_required
def voice_recent():
    """Recent voice generation activity for the current user."""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT text_input, time_ms, cache_hit, emotion_used, engine, language,
                   created_at
            FROM voice_generation_log
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT 5
        """,
            (session["user_id"],),
        )
        rows = cur.fetchall()
        recent = []
        for r in rows:
            recent.append(
                {
                    "text": (r[0] or "")[:60],
                    "latency_ms": r[1],
                    "cache_hit": r[2],
                    "emotion": r[3],
                    "engine": r[4],
                    "language": r[5] or "en",
                    "created_at": r[6].isoformat() if r[6] else None,
                }
            )
        return jsonify({"success": True, "recent": recent})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})
```

**Step 3: Add `POST /api/voice/profiles/<id>/invalidate-cache` endpoint**

```python
@archie_chat_bp.route(
    "/api/voice/profiles/<int:profile_id>/invalidate-cache", methods=["POST"]
)
@login_required
def invalidate_voice_cache(profile_id):
    """Unlock or clear cached voice entries for a profile."""
    try:
        data = request.get_json() or {}
        clear = data.get("clear", False)
        regenerate = data.get("regenerate", False)

        conn = get_db()
        cur = conn.cursor()

        # Get profile info
        cur.execute(
            "SELECT agent_id, engine, language FROM agent_voice_profiles WHERE id = %s",
            (profile_id,),
        )
        profile = cur.fetchone()
        if not profile:
            return jsonify({"success": False, "error": "Profile not found"})

        agent_id, engine, language = profile

        if clear:
            cur.execute(
                """DELETE FROM voice_word_cache
                WHERE agent_id = %s AND engine = %s AND language = %s
                AND is_locked = TRUE""",
                (agent_id, engine, language),
            )
            deleted = cur.rowcount
            unlocked = 0
        else:
            cur.execute(
                """UPDATE voice_word_cache
                SET is_locked = FALSE, locked_at = NULL, locked_with_params = NULL
                WHERE agent_id = %s AND engine = %s AND language = %s
                AND is_locked = TRUE""",
                (agent_id, engine, language),
            )
            unlocked = cur.rowcount
            deleted = 0

        conn.commit()

        pregen_job_id = None
        if regenerate:
            cur.execute(
                """INSERT INTO voice_pregen_jobs
                (agent_id, status, job_type, total_words, language, engine)
                VALUES (%s, 'pending', 'manual', 200, %s, %s)
                RETURNING id""",
                (agent_id, language, engine),
            )
            row = cur.fetchone()
            if row:
                pregen_job_id = row[0]
            conn.commit()

        return jsonify(
            {
                "success": True,
                "unlocked": unlocked,
                "deleted": deleted,
                "pregen_job_id": pregen_job_id,
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})
```

**Step 4: Add profile-lock-status endpoint to consciousness routes.py**

```python
@consciousness_bp.route("/api/voice/profile-lock-status/<int:profile_id>")
@login_required
def voice_profile_lock_status(profile_id):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """SELECT COUNT(*) FROM voice_word_cache vwc
            JOIN agent_voice_profiles avp ON avp.id = %s
            WHERE vwc.agent_id = avp.agent_id
            AND vwc.engine = avp.engine
            AND vwc.language = avp.language
            AND vwc.is_locked = TRUE""",
            (profile_id,),
        )
        count = cur.fetchone()[0]
        return jsonify({"success": True, "locked_count": count})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})
```

**Step 5: Verify column names**

Check `voice_generation_log` column names before testing:

Run: `docker exec archie_database psql -U archie -d archie -c "SELECT column_name FROM information_schema.columns WHERE table_name = 'voice_generation_log' ORDER BY ordinal_position;"`

Adjust the `voice_recent()` query column names if needed.

**Step 6: Commit**

---

### Task 3: Add STT Input UI to Chat Tab

**Files:**
- Modify: `platform_v2/templates/tools/archie_chat.html`

**Step 1: Add STT CSS**

Insert before the responsive section (before `@media` rules, around line 2160). CSS for mic button, listening state, waveform animation, voice status overlay. See design doc for full CSS (~60 lines covering #voice-input-btn, .listening state with mic-pulse animation, #voice-status, #voice-waveform with 5 animated bars).

**Step 2: Add mic button + voice status to input area**

In the `.input-form` (around line 2619-2633), restructure to add mic button before send button and voice status inside input-wrapper. The voice status contains the waveform (5 `.bar` divs) and status text span. The mic button uses `onclick="toggleVoiceInput()"` which is already defined in collaboration.js.

**Step 3: Add `archie-chat-input` ID alias in JS glue**

In the collaboration glue code section, override `document.getElementById` to return `#messageInput` when `archie-chat-input` is requested. This bridges collaboration.js STT code (which uses `archie-chat-input`) to the actual input element.

**Step 4: Hide mic button if Speech API unsupported**

Add feature detection at init: if `window.SpeechRecognition` and `window.webkitSpeechRecognition` are both absent, hide `#voice-input-btn`.

**Step 5: Commit**

---

### Task 4: Add Voice Sidebar to Chat Tab

**Files:**
- Modify: `platform_v2/templates/tools/archie_chat.html`

**Step 1: Add Voice Sidebar CSS**

~150 lines covering: sidebar panel (fixed right, 300px, slide animation), header, sections, toggle switches, volume slider, engine badges, status dots, metric rows, recent activity items, cache hit/miss badges.

**Step 2: Add voice sidebar toggle button to status bar**

In `.status-right` (around line 2550), add a nav-btn with `audio-waveform` lucide icon and `onclick="toggleVoiceSidebar()"`.

**Step 3: Add voice sidebar HTML**

After interjection modal, before `</main>`. Contains: header with close button, Quick Config section (voice toggle, autoplay toggle, volume slider, engine badge), Status section (engine health dots, cached words, hit rate, last latency, profile name), Recent Activity section (dynamic list).

**Step 4: Add voice sidebar JS functions**

Functions: `toggleVoiceSidebar()`, `toggleVoiceFromSidebar()`, `toggleAutoplay()`, `updateVoiceVolume()`, `syncVoiceSidebarToggles()`, `loadVoiceSidebarData()` (fetches /api/voice/status and /api/voice/recent, populates sidebar).

**Step 5: Commit**

---

### Task 5: Profile Locking UX in Consciousness Voice Tab

**Files:**
- Modify: `platform_v2/templates/tools/consciousness_dashboard.html`

**Step 1: Add lock badge to profile cards**

In the profile card rendering function (around line 5336), after header is built, add a `.profile-lock-badge` div showing lock count. Requires adding `locked_count` to the profile API response.

**Step 2: Add locked count to profile API response**

In the consciousness routes where voice profiles are fetched, add a subquery counting locked cache entries per profile.

**Step 3: Add locked column to cache browser table**

Add "Locked" `<th>` to cache table header (line 1604). In row rendering, add lock/unlock icon cell based on `is_locked` field. Add `is_locked` to the cache query.

**Step 4: Add profile edit warning for locked cache**

In `editVoiceProfile()` (line 5640), fetch `/api/voice/profile-lock-status/<id>` and show a warning banner if locked_count > 0. Warning text: "This profile has N locked cached words. Changing voice parameters will NOT update existing cache."

**Step 5: Add "Save & Regenerate" button**

Next to existing Save button in profile form. Calls `saveAndRegenerate()` which saves the profile, then POSTs to `/api/voice/profiles/<id>/invalidate-cache` with `{clear: true, regenerate: true}`.

**Step 6: Add CSS for lock badges, warnings, and regenerate button**

`.profile-lock-badge` (cyan badge), `.profile-lock-warning` (orange warning banner), `.btn-regenerate` (orange-bordered button).

**Step 7: Commit**

---

### Task 6: Deploy & Verify

**Step 1:** Restart the platform:
```bash
docker compose restart archie_platform
```

**Step 2:** Check logs for errors:
```bash
docker logs --tail 50 archie_platform
```

Expected: no template errors, no 500s.

**Step 3:** Open http://192.168.1.200:3000/tools/archie-chat and verify:
- Mic button visible next to send button (hidden if browser lacks Speech API)
- Click mic: waveform animation, "Listening..." status, button turns red
- Voice sidebar toggle in status bar (audio-waveform icon)
- Click sidebar toggle: slides in from right with Quick Config, Status, Recent Activity
- Voice on/off toggle syncs with existing voice button
- Status shows engine health dots

**Step 4:** Open http://192.168.1.200:3000/tools/consciousness and go to Voice tab:
- Profile cards show lock badge with count (e.g., "Locked (247 words)")
- Cache browser table has "Locked" column with lock/unlock icons
- Edit a profile with locked cache: warning banner appears
- "Save & Regenerate" button clears cache and starts pre-gen job

**Step 5:** Final commit.
