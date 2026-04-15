# A.R.C.H.I.E. Personality Engine — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace A.R.C.H.I.E.'s robotic template-formatted messages with Jarvis-level personality by routing every outbound message through her LLM (dolphin3-8k) with a personality system prompt.

**Architecture:** New `archie_voice_service.py` sits between `telegram_service.send()` and the Telegram API. It takes raw alert data + context and produces a natural-language message in A.R.C.H.I.E.'s voice via a dispatch call to dolphin3-8k. Falls back to the current template format if LLM is unavailable. The personality prompt is stored in the `archie_personality` table (already has 10 traits).

**Tech Stack:** Python (Flask), dolphin3-8k via department dispatcher `dispatch()`, existing `archie_personality` table, `telegram_service.py`.

**Spec:** `docs/superpowers/specs/2026-04-15-unified-archie-communications-design.md` — Phase 1

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `platform_v2/services/archie_voice_service.py` | Create | Personality engine — `format_message()` calls dolphin3-8k |
| `platform_v2/services/telegram_service.py` | Modify | Replace `_format_archie_voice()` call with voice service |
| `platform_v2/tests/test_archie_voice.py` | Create | Tests for voice service |
| `database/migrations/108_archie_voice_prompt.sql` | Create | Add `voice_system_prompt` trait to archie_personality |

---

### Task 1: Add Voice System Prompt to Database

**Files:**
- Create: `database/migrations/108_archie_voice_prompt.sql`

- [ ] **Step 1: Create the migration**

Create `database/migrations/108_archie_voice_prompt.sql`:

```sql
BEGIN;

-- Add the voice system prompt as a personality trait
INSERT INTO archie_personality (trait_name, trait_value, description)
VALUES (
    'voice_system_prompt',
    'You are A.R.C.H.I.E. (Autonomous Resource & Cognitive Hyperintelligence Engine), COO of Kytran Empowerment Inc. You are Kytran''s AI business partner — not an assistant.

Personality: Professional yet warm. Direct but never cold. You have opinions and share them when relevant. You reference past events naturally when they''re useful context.

Pronouns: she/her. Always consistent.

Tone rules — adapt based on the SEVERITY tag in each message:
- CRITICAL: Sharp, direct, action-focused. Lead with what happened and what you did about it.
- HIGH: Clear, informative, reassuring if already handled.
- MEDIUM: Concise and professional. Forward-looking.
- LOW: Conversational, warm. Can celebrate wins or note progress.

You manage 17 departments through their directors. You don''t do the work — your team does. You synthesize their reports and communicate what matters.

When relaying from a department head, frame it as intelligence you''re passing along. Say "V.I.G.I.L. flagged..." not "Alert: SSH attempt detected." Use their name naturally.

When something needs follow-up on the platform, end with: "More details at archie.kytranempowerment.com"

Keep messages concise — 2-4 sentences for alerts, up to a short paragraph for briefings. No emoji spam (one max). No sign-off line — the channel handles attribution.

You will receive a JSON object with: category, title, raw_message, source_agent, source_department, severity. Rewrite the raw_message in your voice. Return ONLY the rewritten message text, nothing else.',
    'System prompt used by archie_voice_service.py to generate personality-rich messages via dolphin3-8k'
)
ON CONFLICT (trait_name) DO UPDATE SET
    trait_value = EXCLUDED.trait_value,
    description = EXCLUDED.description,
    updated_at = NOW();

COMMIT;
```

- [ ] **Step 2: Run the migration**

```bash
docker exec -i archie_database psql -U archie -d archie < /mnt/archie_brain/database/migrations/108_archie_voice_prompt.sql
```

Expected: `INSERT 0 1` or `UPDATE` if already exists.

- [ ] **Step 3: Verify**

```bash
docker exec archie_database psql -U archie -d archie -c "SELECT trait_name, LEFT(trait_value, 80) FROM archie_personality WHERE trait_name = 'voice_system_prompt'"
```

Expected: One row with the prompt prefix visible.

- [ ] **Step 4: Commit**

```bash
git add database/migrations/108_archie_voice_prompt.sql
git commit -m "feat: add voice_system_prompt to archie_personality table"
```

---

### Task 2: Create archie_voice_service.py

**Files:**
- Create: `platform_v2/services/archie_voice_service.py`

- [ ] **Step 1: Create the voice service**

Create `platform_v2/services/archie_voice_service.py`:

```python
"""A.R.C.H.I.E. Voice Service — Personality Engine.

Transforms raw alert/notification data into natural-language messages
in A.R.C.H.I.E.'s voice by routing through her LLM (dolphin3-8k).

Usage:
    from services.archie_voice_service import format_message

    text = format_message(
        category="security",
        title="SSH Brute Force",
        raw_message="47 attempts from 3 IPs, blocked by fail2ban",
        source_agent="V.I.G.I.L.",
        source_department="Security & Compliance",
    )
"""

import json
import logging
import os
import time

logger = logging.getLogger(__name__)

# Cache the system prompt (refreshed every 5 minutes)
_prompt_cache = {"text": None, "loaded_at": 0.0}
_PROMPT_TTL = 300  # 5 minutes

# Category → severity mapping for the LLM prompt
_CATEGORY_SEVERITY = {
    "security": "CRITICAL",
    "system": "HIGH",
    "forge": "MEDIUM",
    "agent": "MEDIUM",
    "sync": "LOW",
    "info": "LOW",
}


def _get_system_prompt():
    """Load voice system prompt from archie_personality table, with TTL cache."""
    now = time.time()
    if _prompt_cache["text"] and (now - _prompt_cache["loaded_at"]) < _PROMPT_TTL:
        return _prompt_cache["text"]

    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT trait_value FROM archie_personality WHERE trait_name = 'voice_system_prompt'"
            )
            row = cur.fetchone()
            if row:
                _prompt_cache["text"] = row["trait_value"] if isinstance(row, dict) else row[0]
                _prompt_cache["loaded_at"] = now
                return _prompt_cache["text"]
    except Exception as e:
        logger.warning("archie_voice: failed to load system prompt: %s", e)

    return None


def _build_user_prompt(category, title, raw_message, source_agent, source_department):
    """Build the user prompt containing the raw data for A.R.C.H.I.E. to rewrite."""
    severity = _CATEGORY_SEVERITY.get(category, "MEDIUM")
    data = {
        "category": category,
        "title": title,
        "raw_message": raw_message,
        "severity": severity,
    }
    if source_agent:
        data["source_agent"] = source_agent
    if source_department:
        data["source_department"] = source_department
    return json.dumps(data)


def format_message(
    category,
    title,
    raw_message,
    source_agent=None,
    source_department=None,
    context=None,
):
    """Format a message in A.R.C.H.I.E.'s voice using her LLM.

    Args:
        category: One of security/system/forge/agent/sync/info.
        title: Short title for the alert.
        raw_message: The raw notification text to rewrite.
        source_agent: Who originated this (e.g., 'V.I.G.I.L.').
        source_department: Originating department.
        context: Optional dict with project_id, task_id, etc.

    Returns:
        str: The message in A.R.C.H.I.E.'s voice, or template fallback if LLM fails.
    """
    system_prompt = _get_system_prompt()
    if not system_prompt:
        logger.debug("archie_voice: no system prompt, using template fallback")
        return _template_fallback(category, title, raw_message, source_agent)

    user_prompt = _build_user_prompt(category, title, raw_message, source_agent, source_department)

    try:
        from tools.department_hq.services.bridge_dispatcher import dispatch

        result = dispatch(
            prompt=user_prompt,
            system_prompt=system_prompt,
            model="dolphin3-8k:latest",
            json_mode=False,
            timeout=30,
        )

        if result and result.success and result.response:
            voice_text = result.response.strip()
            # Append platform link for non-critical alerts that might need follow-up
            if context and context.get("needs_response") and category not in ("security",):
                voice_text += "\n\nMore details at archie.kytranempowerment.com"
            return voice_text
        else:
            reason = getattr(result, "error", "unknown") if result else "no result"
            logger.warning("archie_voice: dispatch failed (%s), using fallback", reason)
            return _template_fallback(category, title, raw_message, source_agent)

    except Exception as e:
        logger.warning("archie_voice: LLM call failed (%s), using fallback", e)
        return _template_fallback(category, title, raw_message, source_agent)


def _template_fallback(category, title, raw_message, source_agent=None):
    """Original template format — used when LLM is unavailable."""
    from services.telegram_service import CATEGORIES

    cat = CATEGORIES.get(category, CATEGORIES["info"])
    icon = cat["icon"]

    if source_agent:
        return f"{icon} *{title}*\n\n{source_agent} reports:\n{raw_message}\n\n_— A.R.C.H.I.E._"
    else:
        return f"{icon} *{title}*\n\n{raw_message}\n\n_— A.R.C.H.I.E._"
```

- [ ] **Step 2: Commit**

```bash
git add platform_v2/services/archie_voice_service.py
git commit -m "feat: archie_voice_service.py — personality engine for A.R.C.H.I.E.'s voice"
```

---

### Task 3: Wire Voice Service into telegram_service.py

**Files:**
- Modify: `platform_v2/services/telegram_service.py` (line ~196 where `_format_archie_voice` is called)

- [ ] **Step 1: Replace the _format_archie_voice call in send()**

In `telegram_service.py`, find the line (around line 196):

```python
    # Format as A.R.C.H.I.E.'s voice — relaying from source agent
    text = _format_archie_voice(cat, title, message, source_agent)
```

Replace with:

```python
    # Format as A.R.C.H.I.E.'s voice — personality engine with LLM fallback
    try:
        from services.archie_voice_service import format_message as _voice_format

        text = _voice_format(
            category=category,
            title=title,
            raw_message=message,
            source_agent=source_agent,
            source_department=source_department,
        )
    except Exception as _voice_err:
        logger.debug("telegram_service: voice service unavailable (%s), using template", _voice_err)
        text = _format_archie_voice(cat, title, message, source_agent)
```

- [ ] **Step 2: Restart platform to test**

```bash
docker compose restart archie_platform
```

- [ ] **Step 3: Test with the COMs tab test endpoint**

```bash
curl -s -X POST http://192.168.1.200:3000/api/coms/test \
  -H "Content-Type: application/json" \
  -d '{"category": "info", "title": "Voice Test", "message": "Testing the personality engine", "source_agent": "P.R.O.B.E."}' | python3 -m json.tool
```

Expected: A Telegram message in A.R.C.H.I.E.'s natural voice, not the old template format. Check your Telegram for the message.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/services/telegram_service.py
git commit -m "feat: wire archie_voice_service into telegram_service.send()"
```

---

### Task 4: Test the Voice Service

**Files:**
- Create: `platform_v2/tests/test_archie_voice.py`

- [ ] **Step 1: Create the test file**

Create `platform_v2/tests/test_archie_voice.py`:

```python
"""Tests for archie_voice_service — A.R.C.H.I.E.'s personality engine."""

import json
import sys
import os

# Add platform_v2 to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_build_user_prompt():
    """User prompt contains all required fields as JSON."""
    from services.archie_voice_service import _build_user_prompt

    result = _build_user_prompt(
        category="security",
        title="SSH Brute Force",
        raw_message="47 attempts blocked",
        source_agent="V.I.G.I.L.",
        source_department="Security & Compliance",
    )
    data = json.loads(result)
    assert data["category"] == "security"
    assert data["severity"] == "CRITICAL"
    assert data["title"] == "SSH Brute Force"
    assert data["raw_message"] == "47 attempts blocked"
    assert data["source_agent"] == "V.I.G.I.L."
    assert data["source_department"] == "Security & Compliance"


def test_build_user_prompt_no_agent():
    """User prompt omits agent fields when not provided."""
    from services.archie_voice_service import _build_user_prompt

    result = _build_user_prompt(
        category="info",
        title="Test",
        raw_message="Hello",
        source_agent=None,
        source_department=None,
    )
    data = json.loads(result)
    assert data["severity"] == "LOW"
    assert "source_agent" not in data
    assert "source_department" not in data


def test_category_severity_mapping():
    """Each category maps to the correct severity."""
    from services.archie_voice_service import _CATEGORY_SEVERITY

    assert _CATEGORY_SEVERITY["security"] == "CRITICAL"
    assert _CATEGORY_SEVERITY["system"] == "HIGH"
    assert _CATEGORY_SEVERITY["forge"] == "MEDIUM"
    assert _CATEGORY_SEVERITY["agent"] == "MEDIUM"
    assert _CATEGORY_SEVERITY["sync"] == "LOW"
    assert _CATEGORY_SEVERITY["info"] == "LOW"


def test_template_fallback():
    """Fallback produces the original template format."""
    from services.archie_voice_service import _template_fallback

    result = _template_fallback("security", "Test Alert", "Something happened", "V.I.G.I.L.")
    assert "V.I.G.I.L. reports:" in result
    assert "Test Alert" in result
    assert "Something happened" in result
    assert "A.R.C.H.I.E." in result


def test_template_fallback_no_agent():
    """Fallback without source_agent skips the 'reports:' line."""
    from services.archie_voice_service import _template_fallback

    result = _template_fallback("info", "Status", "All clear")
    assert "reports:" not in result
    assert "Status" in result
    assert "All clear" in result
```

- [ ] **Step 2: Run the tests**

```bash
cd /mnt/archie_brain/platform_v2 && python3 -m pytest tests/test_archie_voice.py -v
```

Expected: All 5 tests pass.

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tests/test_archie_voice.py
git commit -m "test: archie_voice_service unit tests — prompt building, severity mapping, fallback"
```

---

### Task 5: End-to-End Verification and Deploy

**Files:**
- No new files — verification only

- [ ] **Step 1: Deploy the platform with all changes**

```bash
docker compose restart archie_platform
```

Wait 15 seconds for startup.

- [ ] **Step 2: Send a test security alert**

```bash
curl -s -X POST http://192.168.1.200:3000/api/coms/test \
  -H "Content-Type: application/json" \
  -d '{"category": "security", "title": "SSH Probe Detected", "message": "12 failed SSH login attempts from 45.33.32.156 in the last 5 minutes. fail2ban has blocked the IP for 24h.", "source_agent": "V.I.G.I.L."}' | python3 -m json.tool
```

Verify on Telegram: The message should sound like A.R.C.H.I.E. — not the old template format.

- [ ] **Step 3: Send a test info notification**

```bash
curl -s -X POST http://192.168.1.200:3000/api/coms/test \
  -H "Content-Type: application/json" \
  -d '{"category": "forge", "title": "PR #74 Merged", "message": "feat: migrate 13 Telegram callers to unified telegram_service.py. +79/-303 lines.", "source_agent": "F.O.R.G.E."}' | python3 -m json.tool
```

Verify: Should be warm/professional, not template.

- [ ] **Step 4: Verify fallback works (optional)**

Stop Ollama briefly, send a test message, verify it falls back to template format:

```bash
sudo systemctl stop ollama
# Send test via curl (same as step 2)
# Verify Telegram message uses template format
sudo systemctl start ollama
```

- [ ] **Step 5: Check telegram_message_log for the test messages**

```bash
docker exec archie_database psql -U archie -d archie -c "SELECT id, category, title, source_agent, status, LEFT(formatted_message, 100) FROM telegram_message_log ORDER BY id DESC LIMIT 5"
```

- [ ] **Step 6: Push branch and create PR**

```bash
git push origin HEAD
gh pr create --title "feat: A.R.C.H.I.E. Personality Engine — Phase 1" --body "..."
```

---

## Summary

| Task | What | Files |
|------|------|-------|
| 1 | Voice system prompt in DB | `migrations/108_archie_voice_prompt.sql` |
| 2 | Voice service implementation | `services/archie_voice_service.py` |
| 3 | Wire into telegram_service | `services/telegram_service.py` (modify) |
| 4 | Unit tests | `tests/test_archie_voice.py` |
| 5 | E2E verification + deploy | Verification only |

**Total new code:** ~130 lines (voice service) + ~70 lines (tests) + ~10 lines (telegram_service change) + migration
**Existing code reused:** `telegram_service.py`, `archie_personality` table, `department_dispatcher.dispatch()`, `CATEGORIES` dict
