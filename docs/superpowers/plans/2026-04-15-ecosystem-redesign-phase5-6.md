# LLM Ecosystem Redesign — Phase 5+6: Academy Rework & Telegram Unification

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework Agent Academy to test competency against department profiles and build department readiness scorecards. Unify all Telegram messaging through A.R.C.H.I.E. as single voice to Kytran.

**Architecture:** Academy already has benchmark_routes.py (417 lines), training_routes.py (191 lines), and benchmark_service.py (210 lines). We extend, not rebuild. Telegram unification creates a single telegram_service.py that all 7 current senders migrate to.

**Tech Stack:** Python (Flask), PostgreSQL, python-telegram-bot v21+

**Spec:** `docs/superpowers/specs/2026-04-15-llm-ecosystem-redesign-design.md` — Sections 11, 12
**Depends on:** Phase 3+4 complete (capability-aware dispatch, welfare metrics working)

---

## File Map

| Action | File | Purpose |
|--------|------|---------|
| Modify | `tools/agent_academy/benchmark_routes.py` | Add competency test endpoints |
| Modify | `tools/agent_academy/benchmark_service.py` | Competency scoring against dept profiles |
| Modify | `tools/agent_academy/training_routes.py` | Growth tracking from real dispatch data |
| Create | `platform_v2/services/telegram_service.py` | Unified Telegram messaging service |
| Modify | `ai_bridge/agent_loop.py` | Migrate to telegram_service |
| Modify | `ai_bridge/mission_manager.py` | Migrate to telegram_service |
| Modify | `tools/security_network/compliance_safe_exec.py` | Migrate to telegram_service |
| Modify | `tools/security_network/jobs.py` | Migrate to telegram_service |
| Modify | `tools/repair_bay/services/forge_self_heal.py` | Migrate to telegram_service |
| Modify | `services/agent_jobs.py` | Migrate to telegram_service |
| Modify | `services/qa_service.py` | Migrate to telegram_service |

---

### Task 1: Competency Test Framework

**Files:**
- Modify: `tools/agent_academy/benchmark_service.py` (210 lines)
- Modify: `tools/agent_academy/benchmark_routes.py` (417 lines)
- Create: `database/migrations/105_competency_scores.sql`

- [ ] **Step 1: Create competency scores migration**

Create `database/migrations/105_competency_scores.sql`:

```sql
BEGIN;

-- Competency scores: per-agent, per-capability scores (0.0-1.0)
CREATE TABLE IF NOT EXISTS agent_competency_scores (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER NOT NULL REFERENCES agents(id),
    capability VARCHAR(100) NOT NULL,
    score DECIMAL(3,2) NOT NULL DEFAULT 0.5,
    test_count INTEGER NOT NULL DEFAULT 0,
    last_tested TIMESTAMP DEFAULT NOW(),
    source VARCHAR(50) DEFAULT 'benchmark',  -- benchmark, dispatch, manual
    UNIQUE(agent_id, capability)
);

CREATE INDEX IF NOT EXISTS idx_competency_agent ON agent_competency_scores(agent_id);
CREATE INDEX IF NOT EXISTS idx_competency_capability ON agent_competency_scores(capability);

-- Department readiness view
CREATE OR REPLACE VIEW v_department_readiness AS
SELECT
    dcp.department,
    dcp.floor,
    AVG(acs.score) as avg_readiness,
    COUNT(DISTINCT acs.agent_id) as agents_tested,
    COUNT(*) FILTER (WHERE acs.score < 0.3) as failing_capabilities,
    COUNT(*) FILTER (WHERE acs.score >= 0.7) as strong_capabilities
FROM department_capability_profiles dcp
CROSS JOIN LATERAL jsonb_array_elements_text(dcp.required_capabilities) cap(name)
LEFT JOIN agents a ON a.department = dcp.department AND a.worker_type = 'ai' AND a.shift_state = 'active'
LEFT JOIN agent_competency_scores acs ON acs.agent_id = a.id AND acs.capability = cap.name
GROUP BY dcp.department, dcp.floor
ORDER BY avg_readiness ASC NULLS FIRST;

COMMIT;
```

- [ ] **Step 2: Run migration**

```bash
docker exec archie_database psql -U archie -d archie -f /mnt/archie_brain/database/migrations/105_competency_scores.sql
```

- [ ] **Step 3: Add competency test endpoint to benchmark_routes.py**

In `benchmark_routes.py`, add a new route after the existing `/api/benchmarks/run`:

```python
@bp.route("/api/competency/test", methods=["POST"])
@admin_required
def run_competency_test():
    """Test an agent against their department's required capabilities.

    POST body: { "agent_id": int } or { "department": string }
    Uses department_capability_profiles to generate test prompts per capability,
    dispatches to agent, scores response.
    """
    data = request.get_json() or {}
    agent_id = data.get("agent_id")
    department = data.get("department")

    # Get department capabilities
    cur.execute("""
        SELECT dcp.required_capabilities
        FROM department_capability_profiles dcp
        JOIN agents a ON a.department = dcp.department
        WHERE a.id = %s OR dcp.department = %s
        LIMIT 1
    """, (agent_id, department))
    # ... generate test prompts, dispatch, score, store in agent_competency_scores
```

- [ ] **Step 4: Add department readiness endpoint**

```python
@bp.route("/api/competency/readiness")
@admin_required
def department_readiness():
    """Department readiness scorecard — feeds A.R.C.H.I.E.'s executive dashboard."""
    cur.execute("SELECT * FROM v_department_readiness")
    return jsonify({"success": True, "departments": [dict(r) for r in cur.fetchall()]})
```

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: competency test framework — per-agent capability scores, department readiness view

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Growth Tracking from Dispatch Data

**Files:**
- Modify: `tools/agent_academy/training_routes.py` (191 lines)

- [ ] **Step 1: Add dispatch-based growth endpoint**

In `training_routes.py`, add an endpoint that pulls real dispatch success rates per capability:

```python
@bp.route("/api/training/growth/<int:agent_id>")
@admin_required
def agent_growth(agent_id):
    """Track agent growth over time — real dispatch metrics, not just benchmarks."""
    cur.execute("""
        SELECT
            DATE_TRUNC('week', created_at) as week,
            COUNT(*) as total_dispatches,
            COUNT(*) FILTER (WHERE success = true) as successes,
            ROUND(AVG(CASE WHEN success THEN 1.0 ELSE 0.0 END), 2) as success_rate,
            AVG(duration_ms) as avg_duration
        FROM dispatch_escalation_log
        WHERE original_agent_id = %s
        GROUP BY week
        ORDER BY week DESC
        LIMIT 12
    """, (agent_id,))
    return jsonify({"success": True, "growth": [dict(r) for r in cur.fetchall()]})
```

- [ ] **Step 2: Add capability matrix endpoint**

```python
@bp.route("/api/training/capability-matrix")
@admin_required
def capability_matrix():
    """Visual map: department requirements vs agent capabilities, gaps highlighted."""
    cur.execute("""
        SELECT dcp.department, dcp.floor, dcp.required_capabilities,
               json_agg(json_build_object(
                   'agent', a.name,
                   'scores', (SELECT json_object_agg(capability, score) FROM agent_competency_scores WHERE agent_id = a.id)
               )) as agents
        FROM department_capability_profiles dcp
        LEFT JOIN agents a ON a.department = dcp.department AND a.worker_type = 'ai' AND a.shift_state = 'active'
        GROUP BY dcp.department, dcp.floor, dcp.required_capabilities
        ORDER BY dcp.department
    """)
    return jsonify({"success": True, "matrix": [dict(r) for r in cur.fetchall()]})
```

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "feat: growth tracking + capability matrix — real dispatch metrics in Academy

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Unified Telegram Service

**Files:**
- Create: `platform_v2/services/telegram_service.py`

This is the core of Phase 6 — a single service that all modules call instead of their own `_send_telegram()` functions.

- [ ] **Step 1: Create telegram_service.py**

Create `/mnt/archie_brain/platform_v2/services/telegram_service.py`:

```python
"""
Unified Telegram Service — A.R.C.H.I.E.'s Voice

All Telegram messages route through this service. A.R.C.H.I.E. is the unified
messenger to Kytran (CEO). Messages are categorized, prioritized, and optionally
batched into digests.

Usage:
    from services.telegram_service import send_telegram
    send_telegram("security_alert", "Compliance Failure", "Rule XYZ failed on node hub")

Categories & Priority:
    security_alert     → Critical (immediate)
    approval_request   → High (immediate with buttons)
    compliance_failure → High (immediate)
    qa_results         → Medium (batched into digest)
    welfare_alert      → Medium (immediate if critical threshold)
    email_digest       → Low (morning briefing)
    status_update      → Low (A.R.C.H.I.E.'s periodic check-in)
    mission_change     → Medium (batched with context)

Decision #441 — LLM Ecosystem Redesign
"""

import logging
from typing import Optional

logger = logging.getLogger("telegram_service")

# Priority levels
PRIORITY_CRITICAL = "critical"  # Send immediately
PRIORITY_HIGH = "high"          # Send immediately
PRIORITY_MEDIUM = "medium"      # Batch unless threshold
PRIORITY_LOW = "low"            # Batch into digest

CATEGORY_PRIORITY = {
    "security_alert": PRIORITY_CRITICAL,
    "approval_request": PRIORITY_HIGH,
    "compliance_failure": PRIORITY_HIGH,
    "qa_results": PRIORITY_MEDIUM,
    "welfare_alert": PRIORITY_MEDIUM,
    "email_digest": PRIORITY_LOW,
    "status_update": PRIORITY_LOW,
    "mission_change": PRIORITY_MEDIUM,
}


def send_telegram(category: str, title: str, detail: str,
                  buttons: Optional[list] = None, parse_mode: str = "HTML"):
    """Send a Telegram message as A.R.C.H.I.E.

    Args:
        category: Message category (determines priority and batching)
        title: Short title for the message
        detail: Full message body
        buttons: Optional inline keyboard buttons [{text, callback_data}]
        parse_mode: Telegram parse mode (HTML or Markdown)
    """
    priority = CATEGORY_PRIORITY.get(category, PRIORITY_MEDIUM)

    # Format as A.R.C.H.I.E.'s voice
    icon = _category_icon(category)
    message = f"{icon} <b>{title}</b>\n\n{detail}\n\n<i>— A.R.C.H.I.E.</i>"

    # For now: all messages send immediately (batching is Phase 6b future work)
    _send_now(message, buttons=buttons, parse_mode=parse_mode)

    logger.info(f"Telegram [{category}/{priority}]: {title}")


def _category_icon(category: str) -> str:
    """Get icon for message category."""
    icons = {
        "security_alert": "🔴",
        "approval_request": "🟡",
        "compliance_failure": "🔴",
        "qa_results": "📊",
        "welfare_alert": "💙",
        "email_digest": "📧",
        "status_update": "📋",
        "mission_change": "🔄",
    }
    return icons.get(category, "📌")


def _send_now(text: str, buttons: Optional[list] = None, parse_mode: str = "HTML"):
    """Send message immediately via Telegram gateway."""
    try:
        from ai_bridge.telegram_gateway import TelegramGateway
        import flask

        app = flask.current_app._get_current_object()
        gateway = getattr(app, '_telegram_gateway', None)

        if not gateway or not gateway._running:
            logger.warning("Telegram gateway not running — message dropped")
            return

        # Get Kytran's telegram_id
        from database import get_db
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT telegram_id FROM telegram_users WHERE is_authorized = true LIMIT 1")
        row = cur.fetchone()
        cur.close()
        conn.close()

        if not row:
            logger.warning("No authorized Telegram user found")
            return

        telegram_id = row[0]

        # Send via gateway's bot
        import asyncio
        bot = gateway._application.bot

        kwargs = {"chat_id": telegram_id, "text": text, "parse_mode": parse_mode}
        if buttons:
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            keyboard = [[InlineKeyboardButton(b["text"], callback_data=b["callback_data"]) for b in buttons]]
            kwargs["reply_markup"] = InlineKeyboardMarkup(keyboard)

        asyncio.run_coroutine_threadsafe(bot.send_message(**kwargs), gateway._loop)

    except Exception as e:
        logger.error(f"Telegram send failed: {e}")
```

- [ ] **Step 2: Commit the service**

```bash
git add platform_v2/services/telegram_service.py
git commit -m "feat: unified telegram_service.py — A.R.C.H.I.E.'s single voice to Kytran

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Migrate Senders to Unified Service

**Files:**
- Modify: 7 files that currently have their own `_send_telegram()` functions

This task migrates each sender to use `from services.telegram_service import send_telegram`. Each file gets a thin wrapper replacement.

- [ ] **Step 1: Migrate repair_bay/forge_self_heal.py**

In `/mnt/archie_brain/platform_v2/tools/repair_bay/services/forge_self_heal.py` (line 79), replace the local `_send_telegram()` with:

```python
def _send_telegram(text: str):
    """Route through unified telegram service."""
    from services.telegram_service import send_telegram
    send_telegram("compliance_failure", "Repair Bay Alert", text)
```

- [ ] **Step 2: Migrate security_network/jobs.py**

In `/mnt/archie_brain/platform_v2/tools/security_network/jobs.py` (line 632-690), replace the local `_send_telegram()`:

```python
def _send_telegram(msg):
    from services.telegram_service import send_telegram
    send_telegram("security_alert", "Security Scan Alert", msg)
```

- [ ] **Step 3: Migrate security_network/compliance_safe_exec.py**

In `/mnt/archie_brain/platform_v2/tools/security_network/compliance_safe_exec.py` (line 341-353), replace import with:

```python
def _send_telegram(msg):
    from services.telegram_service import send_telegram
    send_telegram("compliance_failure", "Compliance Rollback", msg)
```

- [ ] **Step 4: Migrate services/qa_service.py**

In `/mnt/archie_brain/platform_v2/services/qa_service.py` (line 387), update `_send_qa_telegram_alert()`:

```python
def _send_qa_telegram_alert(suite_name, run_id, total, passed, failed, errors, results):
    from services.telegram_service import send_telegram
    detail = f"Suite: {suite_name} (#{run_id})\nPassed: {passed}/{total} | Failed: {failed} | Errors: {errors}"
    send_telegram("qa_results", f"QA Results: {suite_name}", detail)
```

- [ ] **Step 5: Migrate services/agent_jobs.py**

In `/mnt/archie_brain/platform_v2/services/agent_jobs.py` (line 152), update `_send_hr_telegram_alerts()` to use:

```python
from services.telegram_service import send_telegram
# Replace direct bot.send_message calls with:
send_telegram("welfare_alert", f"Agent Welfare: {agent_name}", alert_text)
```

- [ ] **Step 6: Note on agent_loop.py and mission_manager.py**

These files in `ai_bridge/` have more complex Telegram interactions (approval buttons, escalation flows). They should migrate last and may need the `buttons` parameter. For now, leave them — they still work, and the unified service is available for new code.

- [ ] **Step 7: Restart and verify**

```bash
docker compose restart archie_platform
docker logs --tail 20 archie_platform 2>&1 | grep -i "error\|telegram"
```

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat: migrate 5 Telegram senders to unified service — A.R.C.H.I.E. speaks with one voice

agent_loop.py and mission_manager.py kept on legacy (complex button flows).
All platform_v2 senders now route through telegram_service.py.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Summary

| Task | What It Does | Effort | Depends On |
|------|-------------|--------|------------|
| 1 | Competency test framework + department readiness | medium | Phase 3 (capability tags) |
| 2 | Growth tracking + capability matrix | small | Task 1 |
| 3 | Create unified telegram_service.py | medium | None |
| 4 | Migrate 5 senders to unified service | medium | Task 3 |

**After Phase 5+6:** Academy tests agents against department capabilities, readiness scorecards visible in DHQ, all Telegram messages come from A.R.C.H.I.E. in a unified voice.
