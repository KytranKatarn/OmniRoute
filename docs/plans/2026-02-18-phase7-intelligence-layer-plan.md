# Phase 7: Intelligence Layer — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add analytics dashboard, contextual memory system, proactive chat integration, and conversation export to the ARCHIE chat interface.

**Architecture:** Add ~10 API endpoints to `archie_core/routes.py` (1500 lines), 3 new intent types to `intent_parser.py` (795 lines), fix briefing pipeline in `proactive_intelligence.py` (696 lines), and add 4 sidebar/UI features to `archie_chat.html` (4230 lines). One migration for schema additions.

**Tech Stack:** Flask, PostgreSQL, Chart.js, EventSource (reuse Phase 6 SSE), qwen25-classify (auto-extraction), existing `el()`-style DOM helpers, `--archie-*` design tokens.

---

## Context for All Tasks

**Design spec:** `docs/plans/2026-02-18-phase7-intelligence-layer-design.md`

**Key files:**
- `platform_v2/tools/archie_core/routes.py` — 1500 lines, `archie_chat_bp` Blueprint at line 38 (url_prefix `/tools/archie-chat`), `get_db()` at line 41, last route ends ~line 1500
- `ai_bridge/intent_parser.py` — 795 lines, `IntentParser` class, `INTENT_TYPES` list at lines 27-42, `_quick_classify()` at line 109, patterns at lines 113-415
- `ai_bridge/orchestration_engine.py` — 2054 lines, `orchestrate()` at lines 205-439, team action handler pattern at line 964
- `ai_bridge/proactive_intelligence.py` — 696 lines, `BriefingGenerator` (42-300), `AnomalyDetector` (307-472)
- `platform_v2/templates/tools/archie_chat.html` — 4230 lines, sidebar 2725-2809, status bar 2813-2867, JS script 3164-4228

**DB connection in archie_core:** Uses `get_db()` (NOT `get_db_connection()` like bridge routes).

**Important column names** (verified in Phase 6):
- `agents` table: `name` (not codename), `display_name`, `status`
- `orchestration_steps`: `step_data` (not data), `step_order` (not label), `model_used`, `agent_id`
- `orchestration_sessions`: `session_id` (UUID), `status`, `total_steps`, `total_duration_ms`, `created_at`
- `agent_emotional_state`: `current_mood`, `stress_level`, `energy_level`, `timestamp`
- `system_notifications`: Check if `is_read`, `user_id` columns exist — if not, migration adds them
- `long_term_memory`: Has `user_id`, `memory_type`, `category`, `content`, `importance_score`, `access_count`, `tags`, `source_module`, `decay_immunity`

---

### Task 1: Create Migration 111

**Files:**
- Create: `database/migrations/111_intelligence_layer.sql`

**Step 1: Verify existing schema before writing migration**

Check what columns exist:
```bash
docker exec archie_database psql -U archie -d archie -c "\d long_term_memory"
docker exec archie_database psql -U archie -d archie -c "\d system_notifications"
```

**Step 2: Write the migration file**

```sql
-- Migration 111: Intelligence Layer additions
-- Phase 7: Analytics, Memory, Proactive, Export

-- Memory system enhancements
ALTER TABLE long_term_memory ADD COLUMN IF NOT EXISTS source_type TEXT DEFAULT 'system';
ALTER TABLE long_term_memory ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN DEFAULT FALSE;
CREATE INDEX IF NOT EXISTS idx_ltm_user_active ON long_term_memory(user_id) WHERE is_deleted = FALSE;

-- Notification read tracking (add if columns don't exist)
ALTER TABLE system_notifications ADD COLUMN IF NOT EXISTS is_read BOOLEAN DEFAULT FALSE;
ALTER TABLE system_notifications ADD COLUMN IF NOT EXISTS read_at TIMESTAMP;
CREATE INDEX IF NOT EXISTS idx_sn_unread ON system_notifications(created_at DESC) WHERE is_read = FALSE;

-- Chat export log
CREATE TABLE IF NOT EXISTS chat_export_log (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    conversation_id TEXT NOT NULL,
    export_format TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);
```

Adjust based on what the `\d` commands reveal — skip any ALTER that adds already-existing columns.

**Step 3: Run the migration**

```bash
docker cp database/migrations/111_intelligence_layer.sql archie_database:/tmp/
docker exec archie_database psql -U archie -d archie -f /tmp/111_intelligence_layer.sql
```

**Step 4: Verify**

```bash
docker exec archie_database psql -U archie -d archie -c "\d long_term_memory" | grep -E "source_type|is_deleted"
docker exec archie_database psql -U archie -d archie -c "\d system_notifications" | grep -E "is_read|read_at"
docker exec archie_database psql -U archie -d archie -c "\d chat_export_log"
```

**Step 5: Commit**

```bash
git add database/migrations/111_intelligence_layer.sql
git commit -m "feat(db): migration 111 — intelligence layer schema additions"
```

---

### Task 2: Analytics API Endpoints

**Files:**
- Modify: `platform_v2/tools/archie_core/routes.py` (add after the last route, ~line 1500)

**Step 1: Verify table/column names**

```bash
docker exec archie_database psql -U archie -d archie -c "\d ai_conversations"
docker exec archie_database psql -U archie -d archie -c "SELECT DISTINCT jsonb_object_keys(metadata) FROM ai_conversations WHERE metadata IS NOT NULL LIMIT 20;"
docker exec archie_database psql -U archie -d archie -c "\d voice_generation_log"
docker exec archie_database psql -U archie -d archie -c "\d voice_word_cache"
```

Use actual column names from the output. The plan assumes metadata JSONB has keys: `response_time_ms`, `model`, `agent_used`, `total_duration_ms`, `tokens`.

**Step 2: Add 4 analytics endpoints**

Add after the last existing route in routes.py:

```python
# ============================================================
# Phase 7: Analytics Endpoints
# ============================================================

@archie_chat_bp.route("/api/analytics/conversation-metrics")
@login_required
def analytics_conversation_metrics():
    """Conversation metrics for current user."""
    range_days = request.args.get("range", 7, type=int)
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        uid = current_user.id
        # Message counts
        cur.execute("""
            SELECT
                COUNT(*) FILTER (WHERE created_at > CURRENT_DATE) as today,
                COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '7 days') as week,
                COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '30 days') as month
            FROM ai_conversations WHERE user_id = %s
        """, (uid,))
        counts = cur.fetchone()
        # Avg response time
        cur.execute("""
            SELECT AVG((metadata->>'response_time_ms')::float) as avg_response_ms
            FROM ai_conversations
            WHERE user_id = %s AND metadata->>'response_time_ms' IS NOT NULL
            AND created_at > NOW() - INTERVAL '%s days'
        """, (uid, range_days))
        avg_resp = cur.fetchone()
        # Daily trend
        cur.execute("""
            SELECT DATE(created_at) as day, COUNT(*) as count
            FROM ai_conversations
            WHERE user_id = %s AND created_at > NOW() - INTERVAL '%s days'
            GROUP BY DATE(created_at)
            ORDER BY day
        """, (uid, range_days))
        trend = cur.fetchall()
        # Active threads
        cur.execute("""
            SELECT COUNT(*) as active
            FROM ai_conversation_threads
            WHERE user_id = %s AND is_archived = FALSE
        """, (uid,))
        threads = cur.fetchone()
        cur.close()
        conn.close()
        for t in trend:
            t["day"] = t["day"].isoformat() if t.get("day") else None
        return jsonify({
            "today": counts["today"] or 0,
            "week": counts["week"] or 0,
            "month": counts["month"] or 0,
            "avg_response_ms": round(avg_resp["avg_response_ms"] or 0),
            "active_threads": threads["active"] or 0,
            "daily_trend": trend,
        })
    except Exception as e:
        logger.error("analytics_conversation_metrics error: %s", e)
        return jsonify({"today": 0, "week": 0, "month": 0, "avg_response_ms": 0, "active_threads": 0, "daily_trend": []})
```

```python
@archie_chat_bp.route("/api/analytics/model-usage")
@login_required
def analytics_model_usage():
    """Model and agent usage distribution."""
    range_days = request.args.get("range", 7, type=int)
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        # Model distribution
        cur.execute("""
            SELECT model_used, COUNT(*) as count
            FROM orchestration_steps
            WHERE model_used IS NOT NULL
            AND created_at > NOW() - INTERVAL '%s days'
            GROUP BY model_used
            ORDER BY count DESC
        """, (range_days,))
        models = cur.fetchall()
        # Agent usage
        cur.execute("""
            SELECT a.name as agent_name, a.display_name, COUNT(*) as count
            FROM orchestration_steps st
            JOIN agents a ON a.id = st.agent_id
            WHERE st.agent_id IS NOT NULL
            AND st.created_at > NOW() - INTERVAL '%s days'
            GROUP BY a.id, a.name, a.display_name
            ORDER BY count DESC
            LIMIT 10
        """, (range_days,))
        agents = cur.fetchall()
        # Step timing
        cur.execute("""
            SELECT step_type, COUNT(*) as count, AVG(duration_ms) as avg_ms
            FROM orchestration_steps
            WHERE created_at > NOW() - INTERVAL '%s days'
            GROUP BY step_type
            ORDER BY avg_ms DESC
        """, (range_days,))
        timing = cur.fetchall()
        cur.close()
        conn.close()
        for t in timing:
            t["avg_ms"] = round(t["avg_ms"] or 0)
        return jsonify({"models": models, "agents": agents, "step_timing": timing})
    except Exception as e:
        logger.error("analytics_model_usage error: %s", e)
        return jsonify({"models": [], "agents": [], "step_timing": []})
```

```python
@archie_chat_bp.route("/api/analytics/cost")
@login_required
def analytics_cost():
    """Token and cost tracking."""
    range_days = request.args.get("range", 30, type=int)
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT provider, model_name,
                   SUM(total_tokens) as total_tokens,
                   SUM(cost_usd) as total_cost,
                   COUNT(*) as call_count
            FROM cloud_model_usage
            WHERE created_at > NOW() - INTERVAL '%s days'
            GROUP BY provider, model_name
            ORDER BY total_cost DESC
        """, (range_days,))
        costs = cur.fetchall()
        for c in costs:
            c["total_cost"] = float(c["total_cost"] or 0)
        cur.close()
        conn.close()
        return jsonify({"costs": costs})
    except Exception as e:
        logger.error("analytics_cost error: %s", e)
        return jsonify({"costs": []})
```

```python
@archie_chat_bp.route("/api/analytics/voice")
@login_required
def analytics_voice():
    """Voice generation stats."""
    range_days = request.args.get("range", 7, type=int)
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        # Generation count + cache stats
        cur.execute("""
            SELECT COUNT(*) as total_generations,
                   COUNT(*) FILTER (WHERE cached = TRUE) as cache_hits,
                   AVG(generation_time_ms) as avg_latency_ms
            FROM voice_generation_log
            WHERE created_at > NOW() - INTERVAL '%s days'
        """, (range_days,))
        stats = cur.fetchone()
        total = stats["total_generations"] or 0
        hits = stats["cache_hits"] or 0
        cur.close()
        conn.close()
        return jsonify({
            "total_generations": total,
            "cache_hits": hits,
            "cache_hit_rate": round((hits / total * 100) if total > 0 else 0, 1),
            "avg_latency_ms": round(stats["avg_latency_ms"] or 0),
        })
    except Exception as e:
        logger.error("analytics_voice error: %s", e)
        return jsonify({"total_generations": 0, "cache_hits": 0, "cache_hit_rate": 0, "avg_latency_ms": 0})
```

**Step 3: Verify routes load**

```bash
docker exec archie_platform python3 -c "from tools.archie_core.routes import archie_chat_bp; print('OK')"
```

**Step 4: Commit**

```bash
git add platform_v2/tools/archie_core/routes.py
git commit -m "feat(chat): analytics API endpoints — conversation metrics, model usage, cost, voice"
```

---

### Task 3: Memory API Endpoints

**Files:**
- Modify: `platform_v2/tools/archie_core/routes.py` (add after analytics endpoints)

**Step 1: Add memory endpoints**

```python
# ============================================================
# Phase 7: Memory Endpoints
# ============================================================

@archie_chat_bp.route("/api/memory/list")
@login_required
def memory_list():
    """List active memories for current user."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT id, memory_type, category, content, importance_score,
                   access_count, tags, source_type, created_at
            FROM long_term_memory
            WHERE user_id = %s AND is_deleted = FALSE
            ORDER BY importance_score DESC, created_at DESC
            LIMIT 100
        """, (current_user.id,))
        memories = cur.fetchall()
        cur.close()
        conn.close()
        for m in memories:
            m["created_at"] = m["created_at"].isoformat() if m.get("created_at") else None
        return jsonify({"memories": memories})
    except Exception as e:
        logger.error("memory_list error: %s", e)
        return jsonify({"memories": []})
```

```python
@archie_chat_bp.route("/api/memory/store", methods=["POST"])
@login_required
def memory_store():
    """Manually store a memory."""
    data = request.get_json() or {}
    content = data.get("content", "").strip()
    category = data.get("category", "general")
    if not content:
        return jsonify({"error": "Content required"}), 400
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO long_term_memory
            (user_id, memory_type, category, content, importance_score, source_type, source_module)
            VALUES (%s, 'fact', %s, %s, 0.7, 'manual', 'chat')
            RETURNING id
        """, (current_user.id, category, content))
        new_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"id": new_id, "status": "stored"})
    except Exception as e:
        logger.error("memory_store error: %s", e)
        return jsonify({"error": str(e)}), 500
```

```python
@archie_chat_bp.route("/api/memory/<int:memory_id>/delete", methods=["POST"])
@login_required
def memory_delete(memory_id):
    """Soft-delete a memory."""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            UPDATE long_term_memory SET is_deleted = TRUE
            WHERE id = %s AND user_id = %s
        """, (memory_id, current_user.id))
        conn.commit()
        affected = cur.rowcount
        cur.close()
        conn.close()
        return jsonify({"deleted": affected > 0})
    except Exception as e:
        logger.error("memory_delete error: %s", e)
        return jsonify({"error": str(e)}), 500
```

```python
@archie_chat_bp.route("/api/memory/preferences")
@login_required
def memory_preferences():
    """User preference entries with confidence."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT id, category, preference_key, preference_value,
                   confidence, times_confirmed, times_contradicted,
                   first_observed_at, last_confirmed_at
            FROM user_memory_preferences
            WHERE user_id = %s AND is_active = TRUE
            ORDER BY confidence DESC
        """, (current_user.id,))
        prefs = cur.fetchall()
        cur.close()
        conn.close()
        for p in prefs:
            p["first_observed_at"] = p["first_observed_at"].isoformat() if p.get("first_observed_at") else None
            p["last_confirmed_at"] = p["last_confirmed_at"].isoformat() if p.get("last_confirmed_at") else None
        return jsonify({"preferences": prefs})
    except Exception as e:
        logger.error("memory_preferences error: %s", e)
        return jsonify({"preferences": []})
```

**Step 2: Verify**

```bash
docker exec archie_platform python3 -c "from tools.archie_core.routes import archie_chat_bp; print('OK')"
```

**Step 3: Commit**

```bash
git add platform_v2/tools/archie_core/routes.py
git commit -m "feat(chat): memory API endpoints — list, store, delete, preferences"
```

---

### Task 4: Memory Intent Handling

**Files:**
- Modify: `ai_bridge/intent_parser.py` (add memory/briefing intent types)
- Modify: `ai_bridge/orchestration_engine.py` (add memory command handler)

**Step 1: Read intent parser to find exact insertion points**

Read `ai_bridge/intent_parser.py` lines 27-42 (INTENT_TYPES) and lines 400-420 (end of _quick_classify patterns).

**Step 2: Add new intent types to INTENT_TYPES list**

After `"conversation"` (line 41), add:
```python
    "memory_store",
    "memory_forget",
    "memory_list",
    "briefing_command",
```

**Step 3: Add keyword patterns in `_quick_classify()`**

Before the final `return None` in `_quick_classify()` (around line 417), add:

```python
        # Memory commands
        memory_store_pat = r'\b(remember\s+(that|this|my)|note\s+that|save\s+(this|that)\s+to\s+memory)\b'
        if re.search(memory_store_pat, lower):
            return {"type": "memory_store", "confidence": 0.95}

        memory_forget_pat = r'\b(forget\s+(about|that|my)|remove\s+memory|delete\s+memory|stop\s+remembering)\b'
        if re.search(memory_forget_pat, lower):
            return {"type": "memory_forget", "confidence": 0.95}

        memory_list_pat = r'\b(what\s+do\s+you\s+remember|my\s+preferences|list\s+(my\s+)?memories|show\s+(my\s+)?memories)\b'
        if re.search(memory_list_pat, lower):
            return {"type": "memory_list", "confidence": 0.95}

        # Briefing commands
        briefing_pat = r'\b(generate\s+briefing|daily\s+summary|morning\s+report|give\s+me\s+a?\s*briefing|configure\s+(my\s+)?briefing)\b'
        if re.search(briefing_pat, lower):
            return {"type": "briefing_command", "confidence": 0.90}
```

**Step 4: Add memory handler to orchestration engine**

Read `ai_bridge/orchestration_engine.py` and find where `_execute_team_action()` is called (around line 280-290 in `orchestrate()`). Before the team action check, add a memory check:

```python
        # Memory commands
        if intent_type in ("memory_store", "memory_forget", "memory_list"):
            response_text = self._handle_memory_command(
                intent_type, user_message, user_id, steps
            )
            # ... (persist steps and return like team_action does)
```

Add the handler method to the OrchestrationEngine class (after `_handle_status_query`):

```python
    def _handle_memory_command(self, intent_type, message, user_id, steps):
        """Handle memory store/forget/list commands."""
        import psycopg2
        from psycopg2.extras import RealDictCursor

        try:
            conn = psycopg2.connect(
                host=os.environ.get("DB_HOST", "archie_database"),
                port=os.environ.get("DB_PORT", "5432"),
                dbname=os.environ.get("DB_NAME", "archie"),
                user=os.environ.get("DB_USER", "archie"),
                password=os.environ.get("DB_PASSWORD", "archie"),
            )
            cur = conn.cursor(cursor_factory=RealDictCursor)

            if intent_type == "memory_store":
                # Extract content after "remember that" / "note that"
                import re
                content = re.sub(
                    r'^(remember\s+(that|this|my)|note\s+that|save\s+(this|that)\s+to\s+memory)\s*',
                    '', message, flags=re.IGNORECASE
                ).strip()
                if not content:
                    content = message
                # Auto-classify category
                category = "general"
                if any(w in content.lower() for w in ["code", "python", "javascript", "api", "function"]):
                    category = "technical"
                elif any(w in content.lower() for w in ["prefer", "like", "always", "never", "style"]):
                    category = "preference"
                cur.execute("""
                    INSERT INTO long_term_memory
                    (user_id, memory_type, category, content, importance_score, source_type, source_module)
                    VALUES (%s, 'fact', %s, %s, 0.7, 'manual', 'chat')
                """, (user_id, category, content))
                conn.commit()
                response = f"Got it! I'll remember that. Stored under '{category}' category."

            elif intent_type == "memory_forget":
                import re
                target = re.sub(
                    r'^(forget\s+(about|that|my)|remove\s+memory|delete\s+memory|stop\s+remembering)\s*',
                    '', message, flags=re.IGNORECASE
                ).strip()
                cur.execute("""
                    UPDATE long_term_memory SET is_deleted = TRUE
                    WHERE user_id = %s AND is_deleted = FALSE
                    AND content ILIKE %s
                """, (user_id, f"%{target}%"))
                affected = cur.rowcount
                conn.commit()
                response = f"Done. Removed {affected} memory entries matching '{target}'." if affected > 0 else f"No memories found matching '{target}'."

            elif intent_type == "memory_list":
                cur.execute("""
                    SELECT category, content, importance_score, source_type
                    FROM long_term_memory
                    WHERE user_id = %s AND is_deleted = FALSE
                    ORDER BY importance_score DESC, created_at DESC
                    LIMIT 20
                """, (user_id,))
                memories = cur.fetchall()
                if memories:
                    lines = []
                    current_cat = None
                    for m in memories:
                        cat = m["category"] or "general"
                        if cat != current_cat:
                            lines.append(f"\n**{cat.title()}:**")
                            current_cat = cat
                        src = f" (auto)" if m["source_type"] == "auto-extracted" else ""
                        lines.append(f"- {m['content']}{src}")
                    response = "Here's what I remember about you:\n" + "\n".join(lines)
                else:
                    response = "I don't have any memories stored for you yet. Tell me something to remember!"

                # Also check preferences
                cur.execute("""
                    SELECT preference_key, preference_value, confidence
                    FROM user_memory_preferences
                    WHERE user_id = %s AND is_active = TRUE
                    ORDER BY confidence DESC
                """, (user_id,))
                prefs = cur.fetchall()
                if prefs:
                    response += "\n\n**Learned Preferences:**"
                    for p in prefs:
                        conf = int((p["confidence"] or 0) * 100)
                        response += f"\n- {p['preference_key']}: {p['preference_value']} ({conf}% confident)"

            else:
                response = "I'm not sure what to do with that memory command."

            cur.close()
            conn.close()
            return response

        except Exception as e:
            logger.error("Memory command error: %s", e)
            return f"Sorry, I had trouble with that memory command: {str(e)}"
```

**Step 5: Wire the memory handler into orchestrate()**

In `orchestrate()`, find where intent_type branching happens (around line 280-295). Add before the team management check:

```python
        if intent_type in ("memory_store", "memory_forget", "memory_list"):
            step = ThinkingStep(
                step_type="memory_command",
                label="Memory Command",
                data={"intent": intent_type},
                duration_ms=0,
                success=True,
            )
            steps.append(step)
            response_text = self._handle_memory_command(
                intent_type, user_message, user_id, steps
            )
            # Persist and return
            total_ms = int((time.time() - start_time) * 1000)
            if db_session_id:
                self._persist_steps(db_session_id, steps)
                self._complete_session(db_session_id, len(steps), total_ms)
            _push_event("task_complete", data={
                "duration_ms": total_ms,
                "success": True,
                "message_preview": user_message[:80] if user_message else "",
            })
            return OrchestrationResult(
                success=True,
                response=response_text,
                thinking_steps=steps,
                conversation_id=conversation_id,
                session_id=session_uuid,
                total_duration_ms=total_ms,
            )
```

Also add `"memory_command"` to the `orchestration_steps` check constraint if it exists. Check:
```bash
docker exec archie_database psql -U archie -d archie -c "SELECT conname, consrc FROM pg_constraint WHERE conrelid = 'orchestration_steps'::regclass AND contype = 'c';"
```

If there's a check constraint on `step_type`, add the new values:
```sql
ALTER TABLE orchestration_steps DROP CONSTRAINT IF EXISTS orchestration_steps_step_type_check;
ALTER TABLE orchestration_steps ADD CONSTRAINT orchestration_steps_step_type_check CHECK (step_type IN ('intent_parse', 'iaae_check', 'welfare_check', 'route_decision', 'gpu_check', 'agent_select', 'execute', 'fallback', 'team_action', 'memory_command', 'briefing_command'));
```

**Step 6: Verify**

```bash
docker exec archie_platform python3 -c "from ai_bridge.intent_parser import IntentParser; p = IntentParser(); r = p._quick_classify('remember that I prefer dark mode'); print(r)"
docker exec archie_platform python3 -c "from ai_bridge.orchestration_engine import OrchestrationEngine; print('OK')"
```

**Step 7: Commit**

```bash
git add ai_bridge/intent_parser.py ai_bridge/orchestration_engine.py
git commit -m "feat(ai): memory intent handling — store, forget, list commands via chat"
```

---

### Task 5: Notification + Briefing API Endpoints

**Files:**
- Modify: `platform_v2/tools/archie_core/routes.py` (add notification endpoints)
- Modify: `ai_bridge/proactive_intelligence.py` (fix briefing delivery, add chat integration)

**Step 1: Add notification endpoints to routes.py**

```python
# ============================================================
# Phase 7: Notification Endpoints
# ============================================================

@archie_chat_bp.route("/api/notifications/unread")
@login_required
def notifications_unread():
    """Unread system notifications for current user."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        # Count unread
        cur.execute("""
            SELECT COUNT(*) as count FROM system_notifications
            WHERE is_read = FALSE
        """)
        count = cur.fetchone()["count"]
        # Recent unread (last 5)
        cur.execute("""
            SELECT id, notification_type, title, message, severity, created_at
            FROM system_notifications
            WHERE is_read = FALSE
            ORDER BY created_at DESC
            LIMIT 5
        """)
        recent = cur.fetchall()
        cur.close()
        conn.close()
        for r in recent:
            r["created_at"] = r["created_at"].isoformat() if r.get("created_at") else None
        return jsonify({"count": count, "notifications": recent})
    except Exception as e:
        logger.error("notifications_unread error: %s", e)
        return jsonify({"count": 0, "notifications": []})
```

```python
@archie_chat_bp.route("/api/notifications/<int:notification_id>/read", methods=["POST"])
@login_required
def notification_mark_read(notification_id):
    """Mark a notification as read."""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            UPDATE system_notifications SET is_read = TRUE, read_at = NOW()
            WHERE id = %s
        """, (notification_id,))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"ok": True})
    except Exception as e:
        logger.error("notification_mark_read error: %s", e)
        return jsonify({"error": str(e)}), 500
```

```python
@archie_chat_bp.route("/api/briefings/generate-now", methods=["POST"])
@login_required
def briefing_generate_now():
    """Trigger immediate briefing generation."""
    try:
        from ai_bridge.proactive_intelligence import BriefingGenerator
        gen = BriefingGenerator()
        result = gen.generate_due_briefings()
        return jsonify({"status": "generated", "result": result})
    except Exception as e:
        logger.error("briefing_generate_now error: %s", e)
        return jsonify({"error": str(e)}), 500
```

```python
@archie_chat_bp.route("/api/briefings/config")
@login_required
def briefing_config():
    """Get briefing configuration."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT id, name, briefing_type, is_active, sections, schedule_cron, delivery_channels FROM briefings ORDER BY id")
        briefings = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify({"briefings": briefings})
    except Exception as e:
        logger.error("briefing_config error: %s", e)
        return jsonify({"briefings": []})
```

**Step 2: Fix briefing generation in proactive_intelligence.py**

Read `_compose_briefing()` (around line 168-210) and `_deliver_briefing()` (around line 212-240). The issue is likely the dispatcher call failing. Add better logging and a fallback:

In `_compose_briefing()`, ensure there's a robust fallback when the dispatcher fails:
```python
# If dispatcher fails, use the raw_summary directly
if not content:
    content = raw_summary
    logger.warning("Briefing AI formatting failed, using raw summary")
```

In `_deliver_briefing()`, add chat delivery:
```python
# Also insert as chat message for the user
try:
    cur.execute("""
        INSERT INTO ai_conversations (user_id, tool_name, conversation_id, message, response, model, metadata)
        VALUES (%s, 'archie-chat', %s, 'Daily Briefing', %s, 'system',
                %s::jsonb)
    """, (
        briefing.get("user_id", 2),  # Default to user 2 (Kytran)
        f"briefing-{briefing['id']}-{datetime.now().strftime('%Y%m%d')}",
        content,
        json.dumps({"chat_mode": "briefing", "source": "proactive"}),
    ))
except Exception as be:
    logger.warning("Failed to insert briefing as chat message: %s", be)
```

**Step 3: Verify**

```bash
docker exec archie_platform python3 -c "from tools.archie_core.routes import archie_chat_bp; print('OK')"
```

**Step 4: Commit**

```bash
git add platform_v2/tools/archie_core/routes.py ai_bridge/proactive_intelligence.py
git commit -m "feat(chat): notification + briefing API endpoints, fix briefing delivery"
```

---

### Task 6: Export API Endpoints

**Files:**
- Modify: `platform_v2/tools/archie_core/routes.py` (add export endpoints)

**Step 1: Add export endpoints**

```python
# ============================================================
# Phase 7: Export Endpoints
# ============================================================

@archie_chat_bp.route("/api/conversations/<conversation_id>/export")
@login_required
def conversation_export(conversation_id):
    """Export a conversation as Markdown or JSON."""
    fmt = request.args.get("format", "md")
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT id, message, response, model, created_at, metadata
            FROM ai_conversations
            WHERE conversation_id = %s AND user_id = %s
            ORDER BY created_at ASC
        """, (conversation_id, current_user.id))
        messages = cur.fetchall()
        # Get thread title
        cur.execute("""
            SELECT title FROM ai_conversation_threads WHERE conversation_id = %s
        """, (conversation_id,))
        thread = cur.fetchone()
        title = thread["title"] if thread else f"Conversation {conversation_id}"
        cur.close()
        conn.close()

        if not messages:
            return jsonify({"error": "No messages found"}), 404

        if fmt == "json":
            for m in messages:
                m["created_at"] = m["created_at"].isoformat() if m.get("created_at") else None
            return jsonify({"title": title, "messages": messages, "exported_at": datetime.utcnow().isoformat()})

        # Markdown format
        lines = [f"# {title}\n", f"*Exported: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}*\n"]
        for m in messages:
            ts = m["created_at"].strftime("%H:%M") if m.get("created_at") else ""
            model = m.get("model") or ""
            lines.append(f"\n---\n\n**You** ({ts}):\n{m['message']}\n")
            lines.append(f"\n**ARCHIE** ({ts}, {model}):\n{m['response']}\n")

        content = "\n".join(lines)
        return Response(
            content,
            mimetype="text/markdown",
            headers={"Content-Disposition": f"attachment; filename=archie-chat-{conversation_id[:8]}.md"},
        )
    except Exception as e:
        logger.error("conversation_export error: %s", e)
        return jsonify({"error": str(e)}), 500
```

```python
@archie_chat_bp.route("/api/conversations/<conversation_id>/save-to-kb", methods=["POST"])
@login_required
def save_conversation_to_kb(conversation_id):
    """Save conversation to knowledge base."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        # Get messages
        cur.execute("""
            SELECT message, response, created_at FROM ai_conversations
            WHERE conversation_id = %s AND user_id = %s
            ORDER BY created_at ASC
        """, (conversation_id, current_user.id))
        messages = cur.fetchall()
        if not messages:
            return jsonify({"error": "No messages found"}), 404
        # Get thread title
        cur.execute("SELECT title FROM ai_conversation_threads WHERE conversation_id = %s", (conversation_id,))
        thread = cur.fetchone()
        title = thread["title"] if thread else f"Chat Export: {messages[0]['message'][:60]}"
        # Build content
        content_lines = []
        for m in messages:
            content_lines.append(f"**User:** {m['message']}")
            content_lines.append(f"**ARCHIE:** {m['response']}\n")
        content = "\n".join(content_lines)
        # Insert into knowledge_base
        cur.execute("""
            INSERT INTO knowledge_base (title, content, source_type, importance_score, tags)
            VALUES (%s, %s, 'chat_export', 0.6, ARRAY['chat-export', 'conversation'])
            RETURNING id
        """, (title, content))
        kb_id = cur.fetchone()["id"]
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"kb_id": kb_id, "title": title})
    except Exception as e:
        logger.error("save_to_kb error: %s", e)
        return jsonify({"error": str(e)}), 500
```

```python
@archie_chat_bp.route("/api/conversations/<conversation_id>/summarize", methods=["POST"])
@login_required
def conversation_summarize(conversation_id):
    """Generate AI summary of a conversation."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT message, response FROM ai_conversations
            WHERE conversation_id = %s AND user_id = %s
            ORDER BY created_at ASC
        """, (conversation_id, current_user.id))
        messages = cur.fetchall()
        cur.close()
        conn.close()
        if not messages:
            return jsonify({"error": "No messages found"}), 404
        # Build conversation text
        text = ""
        for m in messages:
            text += f"User: {m['message']}\nARCHIE: {m['response']}\n\n"
        # Truncate if too long
        if len(text) > 8000:
            text = text[:4000] + "\n...\n" + text[-4000:]
        # Call Ollama for summary
        import requests as req
        resp = req.post(
            os.getenv("OLLAMA_URL", "http://host.docker.internal:11434") + "/api/generate",
            json={
                "model": "dolphin3-8k:latest",
                "prompt": f"Summarize this conversation in 3-5 bullet points. Be concise.\n\n{text}",
                "stream": False,
            },
            timeout=60,
        )
        if resp.ok:
            summary = resp.json().get("response", "Summary generation failed.")
        else:
            summary = "Could not generate summary at this time."
        return jsonify({"summary": summary})
    except Exception as e:
        logger.error("conversation_summarize error: %s", e)
        return jsonify({"error": str(e)}), 500
```

```python
@archie_chat_bp.route("/api/analytics/export")
@login_required
def analytics_export():
    """Export analytics as CSV."""
    range_days = request.args.get("range", 7, type=int)
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT DATE(created_at) as date, COUNT(*) as messages,
                   AVG((metadata->>'response_time_ms')::float) as avg_response_ms
            FROM ai_conversations
            WHERE user_id = %s AND created_at > NOW() - INTERVAL '%s days'
            GROUP BY DATE(created_at)
            ORDER BY date
        """, (current_user.id, range_days))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        # Build CSV
        lines = ["date,messages,avg_response_ms"]
        for r in rows:
            lines.append(f"{r['date']},{r['messages']},{round(r['avg_response_ms'] or 0)}")
        csv_content = "\n".join(lines)
        return Response(
            csv_content,
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename=archie-analytics-{range_days}d.csv"},
        )
    except Exception as e:
        logger.error("analytics_export error: %s", e)
        return jsonify({"error": str(e)}), 500
```

**Step 2: Add Response import if not present**

Check if `Response` is already imported from Flask. If not, add it to the Flask import line.

**Step 3: Verify**

```bash
docker exec archie_platform python3 -c "from tools.archie_core.routes import archie_chat_bp; print('OK')"
```

**Step 4: Commit**

```bash
git add platform_v2/tools/archie_core/routes.py
git commit -m "feat(chat): export endpoints — conversation md/json, save-to-kb, summarize, analytics CSV"
```

---

### Task 7: Chat UI — Analytics Panel

**Files:**
- Modify: `platform_v2/templates/tools/archie_chat.html`

**Step 1: Read the sidebar structure**

Read lines 2725-2810 to understand the sidebar layout. The analytics panel will be added as a collapsible section in the sidebar.

**Step 2: Add analytics CSS**

In the `<style>` section (before `{% endblock %}` around line 2718), add:

```css
/* === Analytics Panel === */
.analytics-panel{padding:8px 12px;border-top:1px solid var(--archie-border,#2a3a4a)}
.analytics-toggle{display:flex;justify-content:space-between;align-items:center;cursor:pointer;padding:6px 0;font-size:.8rem;font-weight:600;color:var(--archie-accent,#60a5fa)}
.analytics-body{display:none;padding-top:8px}
.analytics-body.open{display:block}
.an-metric{display:flex;justify-content:space-between;padding:3px 0;font-size:.8rem}
.an-metric .an-val{font-family:'Orbitron',monospace;color:var(--archie-accent,#60a5fa)}
.an-chart{height:60px;margin:8px 0}
.an-section-title{font-size:.7rem;color:var(--archie-muted,#6b7280);text-transform:uppercase;margin-top:10px;letter-spacing:.5px}
.an-export-btn{font-size:.7rem;padding:2px 8px;border:1px solid var(--archie-border,#2a3a4a);border-radius:4px;background:none;color:var(--archie-text,#e2e8f0);cursor:pointer;margin-top:6px}
.an-export-btn:hover{border-color:var(--archie-accent,#60a5fa)}
```

**Step 3: Add analytics HTML section**

In the sidebar (after the recent commands section, before `</aside>` around line 2809), add:

```html
<!-- Analytics Panel -->
<div class="analytics-panel">
    <div class="analytics-toggle" onclick="toggleAnalytics()">
        <span>Analytics</span>
        <span id="an-arrow">&#9654;</span>
    </div>
    <div class="analytics-body" id="analytics-body">
        <div id="an-conversation-metrics"></div>
        <canvas id="an-trend-chart" class="an-chart"></canvas>
        <div class="an-section-title">Model Usage</div>
        <div id="an-model-usage"></div>
        <div class="an-section-title">Voice</div>
        <div id="an-voice-stats"></div>
        <button class="an-export-btn" onclick="exportAnalyticsCSV()">Export CSV</button>
    </div>
</div>
```

**Step 4: Add analytics JS functions**

In the `<script>` section (before the activity badge polling IIFE at end), add:

```javascript
// Analytics panel
function toggleAnalytics() {
    var body = document.getElementById('analytics-body');
    var arrow = document.getElementById('an-arrow');
    if (!body) return;
    if (body.classList.contains('open')) {
        body.classList.remove('open');
        arrow.textContent = '\u25B6';
    } else {
        body.classList.add('open');
        arrow.textContent = '\u25BC';
        loadAnalytics();
    }
}

function loadAnalytics() {
    fetch('/tools/archie-chat/api/analytics/conversation-metrics?range=7')
        .then(function(r) { return r.json(); })
        .then(function(d) {
            var el = document.getElementById('an-conversation-metrics');
            if (!el) return;
            el.textContent = '';
            var items = [
                {label: 'Today', val: d.today || 0},
                {label: 'This Week', val: d.week || 0},
                {label: 'Avg Response', val: (d.avg_response_ms || 0) + 'ms'},
                {label: 'Active Threads', val: d.active_threads || 0},
            ];
            items.forEach(function(it) {
                var row = document.createElement('div');
                row.className = 'an-metric';
                var lbl = document.createElement('span');
                lbl.textContent = it.label;
                var val = document.createElement('span');
                val.className = 'an-val';
                val.textContent = it.val;
                row.appendChild(lbl);
                row.appendChild(val);
                el.appendChild(row);
            });
            // Sparkline if Chart.js available
            if (d.daily_trend && d.daily_trend.length > 0 && typeof Chart !== 'undefined') {
                var canvas = document.getElementById('an-trend-chart');
                if (canvas) {
                    new Chart(canvas, {
                        type: 'line',
                        data: {
                            labels: d.daily_trend.map(function(t) { return t.day; }),
                            datasets: [{
                                data: d.daily_trend.map(function(t) { return t.count; }),
                                borderColor: '#60a5fa',
                                backgroundColor: 'rgba(96,165,250,0.1)',
                                fill: true,
                                tension: 0.3,
                                pointRadius: 2,
                            }]
                        },
                        options: {
                            plugins: { legend: { display: false } },
                            scales: { x: { display: false }, y: { display: false } },
                            responsive: true,
                            maintainAspectRatio: false,
                        }
                    });
                }
            }
        })
        .catch(function() {});

    fetch('/tools/archie-chat/api/analytics/model-usage?range=7')
        .then(function(r) { return r.json(); })
        .then(function(d) {
            var el = document.getElementById('an-model-usage');
            if (!el) return;
            el.textContent = '';
            (d.models || []).slice(0, 5).forEach(function(m) {
                var row = document.createElement('div');
                row.className = 'an-metric';
                var lbl = document.createElement('span');
                lbl.textContent = m.model_used || 'unknown';
                var val = document.createElement('span');
                val.className = 'an-val';
                val.textContent = m.count;
                row.appendChild(lbl);
                row.appendChild(val);
                el.appendChild(row);
            });
        })
        .catch(function() {});

    fetch('/tools/archie-chat/api/analytics/voice?range=7')
        .then(function(r) { return r.json(); })
        .then(function(d) {
            var el = document.getElementById('an-voice-stats');
            if (!el) return;
            el.textContent = '';
            var items = [
                {label: 'Generations', val: d.total_generations || 0},
                {label: 'Cache Hit', val: (d.cache_hit_rate || 0) + '%'},
                {label: 'Avg Latency', val: (d.avg_latency_ms || 0) + 'ms'},
            ];
            items.forEach(function(it) {
                var row = document.createElement('div');
                row.className = 'an-metric';
                var lbl = document.createElement('span');
                lbl.textContent = it.label;
                var val = document.createElement('span');
                val.className = 'an-val';
                val.textContent = it.val;
                row.appendChild(lbl);
                row.appendChild(val);
                el.appendChild(row);
            });
        })
        .catch(function() {});
}

function exportAnalyticsCSV() {
    window.open('/tools/archie-chat/api/analytics/export?range=7', '_blank');
}
```

**Step 5: Add Chart.js import if not present**

Check if Chart.js is already loaded in archie_chat.html. If not, add before `</body>`:
```html
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
```

Or check if it's available from the platform's static files.

**Step 6: Verify template parses**

```bash
docker exec archie_platform python3 -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('/app/templates'))
t = env.get_template('tools/archie_chat.html')
print('OK')
"
```

**Step 7: Commit**

```bash
git add platform_v2/templates/tools/archie_chat.html
git commit -m "feat(chat): analytics panel in sidebar with conversation metrics, model usage, voice stats"
```

---

### Task 8: Chat UI — Memory Panel

**Files:**
- Modify: `platform_v2/templates/tools/archie_chat.html` (continue editing)

**Step 1: Add memory CSS**

```css
/* === Memory Panel === */
.memory-panel{padding:8px 12px;border-top:1px solid var(--archie-border,#2a3a4a)}
.memory-toggle{display:flex;justify-content:space-between;align-items:center;cursor:pointer;padding:6px 0;font-size:.8rem;font-weight:600;color:var(--archie-accent,#60a5fa)}
.memory-body{display:none;padding-top:8px;max-height:300px;overflow-y:auto}
.memory-body.open{display:block}
.mem-item{padding:6px 8px;border:1px solid var(--archie-border,#2a3a4a);border-radius:4px;margin-bottom:6px;font-size:.8rem;position:relative}
.mem-item .mem-cat{font-size:.65rem;color:var(--archie-accent,#60a5fa);text-transform:uppercase;font-weight:600}
.mem-item .mem-content{margin-top:2px;color:var(--archie-text,#e2e8f0)}
.mem-item .mem-del{position:absolute;top:4px;right:6px;font-size:.7rem;color:var(--archie-muted,#6b7280);cursor:pointer;background:none;border:none;padding:2px}
.mem-item .mem-del:hover{color:#f87171}
.mem-search{width:100%;padding:4px 8px;border:1px solid var(--archie-border,#2a3a4a);border-radius:4px;background:var(--archie-card-bg,#0a1628);color:var(--archie-text,#e2e8f0);font-size:.8rem;margin-bottom:6px}
.mem-empty{text-align:center;padding:16px;color:var(--archie-muted,#6b7280);font-size:.8rem}
```

**Step 2: Add memory HTML section**

In the sidebar, after the analytics panel, add:

```html
<!-- Memory Panel -->
<div class="memory-panel">
    <div class="memory-toggle" onclick="toggleMemory()">
        <span>Memory</span>
        <span id="mem-arrow">&#9654;</span>
    </div>
    <div class="memory-body" id="memory-body">
        <input class="mem-search" id="mem-search" placeholder="Search memories..." oninput="filterMemories(this.value)">
        <div id="mem-list"></div>
    </div>
</div>
```

**Step 3: Add memory JS functions**

```javascript
// Memory panel
var _allMemories = [];

function toggleMemory() {
    var body = document.getElementById('memory-body');
    var arrow = document.getElementById('mem-arrow');
    if (!body) return;
    if (body.classList.contains('open')) {
        body.classList.remove('open');
        arrow.textContent = '\u25B6';
    } else {
        body.classList.add('open');
        arrow.textContent = '\u25BC';
        loadMemories();
    }
}

function loadMemories() {
    fetch('/tools/archie-chat/api/memory/list')
        .then(function(r) { return r.json(); })
        .then(function(d) {
            _allMemories = d.memories || [];
            renderMemories(_allMemories);
        })
        .catch(function() {});
}

function renderMemories(memories) {
    var list = document.getElementById('mem-list');
    if (!list) return;
    list.textContent = '';
    if (memories.length === 0) {
        var empty = document.createElement('div');
        empty.className = 'mem-empty';
        empty.textContent = 'No memories yet. Say "Remember that..." to add one.';
        list.appendChild(empty);
        return;
    }
    memories.forEach(function(m) {
        var item = document.createElement('div');
        item.className = 'mem-item';
        var cat = document.createElement('div');
        cat.className = 'mem-cat';
        cat.textContent = m.category || 'general';
        var content = document.createElement('div');
        content.className = 'mem-content';
        content.textContent = m.content || '';
        var del_btn = document.createElement('button');
        del_btn.className = 'mem-del';
        del_btn.textContent = '\u2715';
        del_btn.title = 'Delete memory';
        del_btn.onclick = function() { deleteMemory(m.id, item); };
        item.appendChild(cat);
        item.appendChild(content);
        item.appendChild(del_btn);
        list.appendChild(item);
    });
}

function filterMemories(query) {
    if (!query) {
        renderMemories(_allMemories);
        return;
    }
    var q = query.toLowerCase();
    var filtered = _allMemories.filter(function(m) {
        return (m.content || '').toLowerCase().indexOf(q) !== -1 ||
               (m.category || '').toLowerCase().indexOf(q) !== -1;
    });
    renderMemories(filtered);
}

function deleteMemory(memId, itemEl) {
    fetch('/tools/archie-chat/api/memory/' + memId + '/delete', { method: 'POST' })
        .then(function(r) { return r.json(); })
        .then(function(d) {
            if (d.deleted) {
                itemEl.remove();
                _allMemories = _allMemories.filter(function(m) { return m.id !== memId; });
            }
        })
        .catch(function() {});
}
```

**Step 4: Verify and commit**

```bash
docker exec archie_platform python3 -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('/app/templates'))
t = env.get_template('tools/archie_chat.html')
print('OK')
"
git add platform_v2/templates/tools/archie_chat.html
git commit -m "feat(chat): memory panel in sidebar with search, list, and delete"
```

---

### Task 9: Chat UI — Notification Feed

**Files:**
- Modify: `platform_v2/templates/tools/archie_chat.html` (continue editing)

**Step 1: Add notification CSS**

```css
/* === Notification Feed === */
.notif-bar{display:none;padding:8px 12px;background:var(--archie-card-bg,#0a1628);border-bottom:1px solid var(--archie-border,#2a3a4a);font-size:.8rem}
.notif-bar.has-notifs{display:flex;align-items:center;gap:8px}
.notif-dot{width:8px;height:8px;border-radius:50%;background:#fbbf24;flex-shrink:0}
.notif-text{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--archie-text,#e2e8f0)}
.notif-count{font-size:.7rem;background:var(--archie-accent,#60a5fa);color:#0a1628;border-radius:8px;padding:0 6px;font-weight:700}
.notif-dismiss{background:none;border:none;color:var(--archie-muted,#6b7280);cursor:pointer;font-size:.8rem;padding:2px}
.notif-dismiss:hover{color:var(--archie-text,#e2e8f0)}
```

**Step 2: Add notification bar HTML**

Insert the notification bar inside `.chat-main`, right after the status bar (around line 2867) and before the solo chat container:

```html
<!-- Notification Feed -->
<div class="notif-bar" id="notif-bar">
    <span class="notif-dot"></span>
    <span class="notif-text" id="notif-text"></span>
    <span class="notif-count" id="notif-count"></span>
    <button class="notif-dismiss" id="notif-dismiss" onclick="dismissNotification()" title="Dismiss">&#10005;</button>
</div>
```

**Step 3: Add notification JS**

```javascript
// Notification feed
var _currentNotifId = null;

function pollNotifications() {
    fetch('/tools/archie-chat/api/notifications/unread')
        .then(function(r) { return r.json(); })
        .then(function(d) {
            var bar = document.getElementById('notif-bar');
            if (!bar) return;
            if (d.count > 0 && d.notifications && d.notifications.length > 0) {
                bar.classList.add('has-notifs');
                var latest = d.notifications[0];
                _currentNotifId = latest.id;
                var text = document.getElementById('notif-text');
                if (text) text.textContent = (latest.title || latest.message || 'New notification').substring(0, 100);
                var count = document.getElementById('notif-count');
                if (count) count.textContent = d.count;
            } else {
                bar.classList.remove('has-notifs');
                _currentNotifId = null;
            }
        })
        .catch(function() {});
}

function dismissNotification() {
    if (!_currentNotifId) return;
    fetch('/tools/archie-chat/api/notifications/' + _currentNotifId + '/read', { method: 'POST' })
        .then(function() { pollNotifications(); })
        .catch(function() {});
}

// Poll every 30s
pollNotifications();
setInterval(pollNotifications, 30000);
```

**Step 4: Verify and commit**

```bash
docker exec archie_platform python3 -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('/app/templates'))
t = env.get_template('tools/archie_chat.html')
print('OK')
"
git add platform_v2/templates/tools/archie_chat.html
git commit -m "feat(chat): notification feed bar with unread count and dismiss"
```

---

### Task 10: Chat UI — Export Buttons

**Files:**
- Modify: `platform_v2/templates/tools/archie_chat.html` (continue editing)

**Step 1: Add export CSS**

```css
/* === Export === */
.export-menu{display:none;position:absolute;right:0;top:100%;background:var(--archie-card-bg,#0a1628);border:1px solid var(--archie-border,#2a3a4a);border-radius:6px;padding:4px;z-index:100;min-width:160px}
.export-menu.open{display:block}
.export-menu button{display:block;width:100%;text-align:left;padding:6px 10px;border:none;background:none;color:var(--archie-text,#e2e8f0);font-size:.8rem;cursor:pointer;border-radius:4px}
.export-menu button:hover{background:var(--archie-bg-secondary,#0c1a2e)}
```

**Step 2: Find where conversation items are rendered in the sidebar**

Look at the "Recent commands" section (around lines 2796-2808) or the conversation sidebar. Add export buttons to conversation list items. This depends on how conversations are rendered.

If conversations are rendered server-side (Jinja loop), add a small export icon per conversation. If rendered via JS, modify the JS rendering function.

Add a global export function:

```javascript
// Export functions
function exportConversation(convId, format) {
    window.open('/tools/archie-chat/api/conversations/' + convId + '/export?format=' + (format || 'md'), '_blank');
}

function saveToKnowledgeBase(convId) {
    fetch('/tools/archie-chat/api/conversations/' + convId + '/save-to-kb', { method: 'POST' })
        .then(function(r) { return r.json(); })
        .then(function(d) {
            if (d.kb_id) {
                showToast('Saved to knowledge base: ' + d.title);
            } else {
                showToast('Error: ' + (d.error || 'Unknown error'));
            }
        })
        .catch(function() { showToast('Failed to save'); });
}

function summarizeConversation(convId) {
    showToast('Generating summary...');
    fetch('/tools/archie-chat/api/conversations/' + convId + '/summarize', { method: 'POST' })
        .then(function(r) { return r.json(); })
        .then(function(d) {
            if (d.summary) {
                // Show in a simple modal or alert
                var modal = document.createElement('div');
                modal.style.cssText = 'position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);background:var(--archie-card-bg,#0a1628);border:1px solid var(--archie-border,#2a3a4a);border-radius:8px;padding:20px;z-index:1000;max-width:500px;max-height:80vh;overflow-y:auto';
                var title = document.createElement('h3');
                title.textContent = 'Conversation Summary';
                title.style.cssText = 'margin:0 0 12px;font-family:Orbitron,monospace;font-size:.9rem;color:var(--archie-accent,#60a5fa)';
                var body = document.createElement('div');
                body.textContent = d.summary;
                body.style.cssText = 'font-size:.85rem;white-space:pre-wrap;color:var(--archie-text,#e2e8f0)';
                var actions = document.createElement('div');
                actions.style.cssText = 'margin-top:12px;display:flex;gap:8px';
                var copyBtn = document.createElement('button');
                copyBtn.textContent = 'Copy';
                copyBtn.style.cssText = 'padding:4px 12px;border:1px solid var(--archie-border);border-radius:4px;background:none;color:var(--archie-text);cursor:pointer';
                copyBtn.onclick = function() { navigator.clipboard.writeText(d.summary); showToast('Copied!'); };
                var closeBtn = document.createElement('button');
                closeBtn.textContent = 'Close';
                closeBtn.style.cssText = 'padding:4px 12px;border:1px solid var(--archie-border);border-radius:4px;background:none;color:var(--archie-text);cursor:pointer';
                closeBtn.onclick = function() { modal.remove(); overlay.remove(); };
                actions.appendChild(copyBtn);
                actions.appendChild(closeBtn);
                modal.appendChild(title);
                modal.appendChild(body);
                modal.appendChild(actions);
                var overlay = document.createElement('div');
                overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);z-index:999';
                overlay.onclick = function() { modal.remove(); overlay.remove(); };
                document.body.appendChild(overlay);
                document.body.appendChild(modal);
            }
        })
        .catch(function() { showToast('Summary failed'); });
}

function showToast(msg) {
    var toast = document.createElement('div');
    toast.textContent = msg;
    toast.style.cssText = 'position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:var(--archie-accent,#60a5fa);color:#0a1628;padding:8px 16px;border-radius:6px;font-size:.85rem;z-index:1001;animation:mcSlideIn .3s ease';
    document.body.appendChild(toast);
    setTimeout(function() { toast.remove(); }, 3000);
}
```

**Step 3: Verify and commit**

```bash
docker exec archie_platform python3 -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('/app/templates'))
t = env.get_template('tools/archie_chat.html')
print('OK')
"
git add platform_v2/templates/tools/archie_chat.html
git commit -m "feat(chat): export functions — markdown/json download, save-to-kb, summarize, toast"
```

---

### Task 11: Auto-Extraction Hook

**Files:**
- Modify: `ai_bridge/orchestration_engine.py` (add extraction after successful orchestration)

**Step 1: Add auto-extraction in the success path**

In `orchestrate()`, after the success `_push_event("task_complete", ...)` and before the success `return`, add a lightweight extraction call:

```python
        # Auto-extract preferences (async, non-blocking)
        try:
            self._auto_extract_preference(user_message, response_text, user_id)
        except Exception:
            pass  # Never block chat for extraction
```

Add the extraction method to the class:

```python
    def _auto_extract_preference(self, message, response, user_id):
        """Lightweight preference extraction via classifier."""
        if not message or len(message) < 20:
            return  # Too short to contain preferences
        import requests
        prompt = (
            "Does this user message contain a personal preference, decision, or fact worth remembering? "
            "If yes, extract it as ONE short sentence starting with 'User prefers' or 'User decided'. "
            "If no, respond with exactly: NONE\n\n"
            f"User message: {message[:500]}"
        )
        try:
            resp = requests.post(
                os.environ.get("OLLAMA_URL", "http://host.docker.internal:11434") + "/api/generate",
                json={"model": "qwen25-classify:latest", "prompt": prompt, "stream": False},
                timeout=10,
            )
            if resp.ok:
                result = resp.json().get("response", "").strip()
                if result and result.upper() != "NONE" and len(result) < 200:
                    import psycopg2
                    conn = psycopg2.connect(
                        host=os.environ.get("DB_HOST", "archie_database"),
                        port=os.environ.get("DB_PORT", "5432"),
                        dbname=os.environ.get("DB_NAME", "archie"),
                        user=os.environ.get("DB_USER", "archie"),
                        password=os.environ.get("DB_PASSWORD", "archie"),
                    )
                    cur = conn.cursor()
                    cur.execute("""
                        INSERT INTO long_term_memory
                        (user_id, memory_type, category, content, importance_score, source_type, source_module)
                        VALUES (%s, 'preference', 'auto-detected', %s, 0.5, 'auto-extracted', 'orchestration')
                    """, (user_id, result))
                    conn.commit()
                    cur.close()
                    conn.close()
        except Exception as e:
            logger.debug("Auto-extraction skipped: %s", e)
```

**Step 2: Verify**

```bash
docker exec archie_platform python3 -c "from ai_bridge.orchestration_engine import OrchestrationEngine; print('OK')"
```

**Step 3: Commit**

```bash
git add ai_bridge/orchestration_engine.py
git commit -m "feat(ai): auto-extract user preferences from chat via qwen25-classify"
```

---

### Task 12: Deploy and Verify

**Step 1: Restart the platform**

```bash
docker compose restart archie_platform
```

Wait 15 seconds, check logs:
```bash
docker logs --tail 30 archie_platform
```

**Step 2: Verify migration**

```bash
docker exec archie_database psql -U archie -d archie -c "SELECT source_type FROM long_term_memory LIMIT 1;"
docker exec archie_database psql -U archie -d archie -c "\d chat_export_log"
```

**Step 3: Verify routes**

```bash
docker exec archie_platform python3 -c "from tools.archie_core.routes import archie_chat_bp; print('Routes OK')"
docker exec archie_platform python3 -c "from ai_bridge.orchestration_engine import OrchestrationEngine; print('Engine OK')"
docker exec archie_platform python3 -c "from ai_bridge.intent_parser import IntentParser; p = IntentParser(); print('Parser OK:', p._quick_classify('remember that I like Python'))"
```

**Step 4: Verify templates**

```bash
docker exec archie_platform python3 -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('/app/templates'))
t = env.get_template('tools/archie_chat.html')
print('OK')
"
```

**Step 5: Push**

```bash
git push origin main
```

**Step 6: Update Dev HQ**

Use MCP tools to:
1. `store_memory` — Phase 7 deployed with all commits
2. `log_decision` — Intelligence layer architecture choices
3. Update the master roadmap tracker

---

## Important Notes

- **Black pre-commit hook**: Will reformat Python files. If commit fails, re-stage and commit again.
- **`archie_core/routes.py` uses `get_db()`** (NOT `get_db_connection()` from bridge routes). These are different functions.
- **`system_notifications` columns**: Check if `is_read`, `user_id`, `title`, `message`, `severity` exist. The migration adds `is_read` and `read_at` if missing, but `title`, `message`, `severity` should already exist. Also check if `notification_type` (not `type`) is the column name.
- **`long_term_memory` columns**: Verify `source_module`, `decay_immunity` exist before insertion queries reference them.
- **`orchestration_steps` check constraint**: If a CHECK constraint limits `step_type` values, add `memory_command` and `briefing_command` to the allowed list.
- **`Response` import**: The export endpoints need `Response` from Flask. Verify it's imported.
- **Chart.js**: May not be loaded in archie_chat.html. Check and add CDN link if needed. The analytics sparkline degrades gracefully without it.
- **DOM construction**: All UI uses `document.createElement()` + `textContent`. No innerHTML.
- **archie_chat.html is 4230 lines**: It's large. Each UI task adds ~50-80 lines of CSS + HTML + ~100-150 lines of JS.
