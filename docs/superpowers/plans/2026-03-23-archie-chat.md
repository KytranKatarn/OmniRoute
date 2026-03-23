# ARCHIE Chat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build ARCHIE Chat — a tier-gated chat module with full orchestration pipeline visibility, global admin overlay, and REST API for Claude CLI/node integration.

**Architecture:** Thin HTTP layer over existing OrchestrationEngine. Chat service manages conversations/sessions, passes conversation_uuid to engine's existing history mechanism, stores messages with thinking_steps for flight deck replay. Three interfaces (module UI, overlay, API) share one backend.

**Tech Stack:** Flask Blueprint, PostgreSQL (psycopg2), vanilla JS, LCARS CSS, existing OrchestrationEngine + BridgeDispatcher

**Spec:** `docs/superpowers/specs/2026-03-23-archie-chat-design.md`

---

## File Map

### New Files (Create)
| File | Responsibility |
|------|---------------|
| `database/migrations/add_chat_tables.sql` | DB schema: chat_conversations, chat_messages, chat_api_keys |
| `platform_v2/tools/archie_chat/__init__.py` | Blueprint definition + ADR-045 route registration |
| `platform_v2/tools/archie_chat/routes.py` | Page route (render template) + admin_required export |
| `platform_v2/tools/archie_chat/api_routes.py` | REST API endpoints: /api/v1/chat/* |
| `platform_v2/tools/archie_chat/chat_service.py` | Business logic: conversation CRUD, message storage, tier-gating, history |
| `platform_v2/tools/archie_chat/auth_middleware.py` | Dual auth: session cookie + bearer token |
| `platform_v2/tools/archie_chat/templates/archie_chat.html` | LCARS module template: sidebar + chat + flight deck |
| `platform_v2/static/css/archie-chat.css` | Chat + flight deck + overlay styles |
| `platform_v2/static/js/archie-chat.js` | Module UI: messages, conversations, flight deck, agent targeting |
| `platform_v2/static/js/archie-chat-overlay.js` | Global overlay widget: bubble, expand/collapse, compact chat |
| `tests/test_chat_service.py` | Unit tests for chat_service.py |
| `tests/test_chat_api.py` | Integration tests for API endpoints |

### Modify Files
| File | Change |
|------|--------|
| `ai_bridge/orchestration_engine.py:210-217` | Add `agent_target` parameter to `orchestrate()` |
| `platform_v2/tools/archie_core/routes.py` | Remove old archie_chat_bp (line ~40) — replaced by new module |
| `platform_v2/module_registry.py` | Update archie_chat entry to point to new blueprint |
| `platform_v2/rbac.py` | Verify/update ARCHIE_CHAT permission + tier mapping |
| `platform_v2/app.py` | Update archie_chat blueprint import to new module |
| `platform_v2/templates/base.html` | Inject overlay JS for admin/Kytran users |

---

## Phase 0 — Prep: Deprecate Old Chat Module

### Task 0: Remove Old archie_core Chat Blueprint

**Files:**
- Modify: `platform_v2/tools/archie_core/routes.py` (remove old archie_chat_bp)
- Modify: `platform_v2/module_registry.py` (update blueprint_import)
- Modify: `platform_v2/app.py` (remove old blueprint registration)

The existing `tools/archie_core/routes.py` defines `archie_chat_bp = Blueprint("archie_chat", ...)` at line ~40, and `module_registry.py` registers it as `blueprint_import="tools.archie_core.routes:archie_chat_bp"`. This must be removed before creating the new module.

- [ ] **Step 1: Read the old archie_core chat code**

Read `platform_v2/tools/archie_core/routes.py` — identify the `archie_chat_bp` Blueprint and all routes attached to it. Note any functionality we need to preserve.

- [ ] **Step 2: Remove archie_chat_bp from archie_core/routes.py**

Delete the Blueprint definition and all routes attached to `archie_chat_bp`. Keep everything else in archie_core (it handles other functionality like AI chat helpers).

- [ ] **Step 3: Update module_registry.py**

Change the archie_chat entry's `blueprint_import` to point to the new module: `"tools.archie_chat:archie_chat_bp"`. If there's a health check function already defined, preserve it or note that Task 6 will replace it.

- [ ] **Step 4: Update app.py**

Remove the old `archie_chat_bp` import from `archie_core`. The new import will be added in Task 6.

- [ ] **Step 5: Verify platform starts without chat**

Run: `docker compose restart archie_platform && sleep 5 && docker logs archie_platform 2>&1 | tail -20`
Expected: Platform starts, archie-chat route returns 404 (module not yet rebuilt)

- [ ] **Step 6: Commit**

```bash
git add platform_v2/tools/archie_core/routes.py platform_v2/module_registry.py platform_v2/app.py
git commit -m "refactor(chat): remove old archie_chat_bp from archie_core — preparing for rebuild"
```

---

## Phase 1 — Foundation (Backend)

### Task 1: Database Migration

**Files:**
- Create: `database/migrations/add_chat_tables.sql`

- [ ] **Step 1: Write migration SQL**

```sql
-- database/migrations/add_chat_tables.sql
-- ARCHIE Chat tables (Project #178)
-- Idempotent: safe to re-run

-- Conversations
CREATE TABLE IF NOT EXISTS chat_conversations (
    id SERIAL PRIMARY KEY,
    conversation_uuid UUID DEFAULT gen_random_uuid() NOT NULL UNIQUE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    team_id INTEGER,
    title VARCHAR(255),
    agent_target VARCHAR(100),
    is_archived BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_conversations_user ON chat_conversations(user_id);
CREATE INDEX IF NOT EXISTS idx_chat_conversations_team ON chat_conversations(team_id) WHERE team_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_chat_conversations_updated ON chat_conversations(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_conversations_uuid ON chat_conversations(conversation_uuid);

-- Messages
CREATE TABLE IF NOT EXISTS chat_messages (
    id SERIAL PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES chat_conversations(id),
    role VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    thinking_steps JSONB,
    agent_used VARCHAR(100),
    model_used VARCHAR(100),
    station_code VARCHAR(20),
    governance_events JSONB,
    duration_ms INTEGER,
    token_count INTEGER,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_conversation ON chat_messages(conversation_id, created_at);

-- API Keys
CREATE TABLE IF NOT EXISTS chat_api_keys (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    key_hash VARCHAR(64) NOT NULL,
    key_prefix VARCHAR(8) NOT NULL,
    name VARCHAR(100) NOT NULL,
    scopes JSONB DEFAULT '["chat"]'::jsonb,
    rate_limit INTEGER DEFAULT 30,
    is_active BOOLEAN DEFAULT TRUE,
    last_used_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_api_keys_hash ON chat_api_keys(key_hash) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_chat_api_keys_user ON chat_api_keys(user_id);
```

- [ ] **Step 2: Run migration**

Run: `docker exec -i archie_database psql -U archie -d archie < database/migrations/add_chat_tables.sql`
Expected: CREATE TABLE / CREATE INDEX messages (no errors)

- [ ] **Step 3: Verify tables exist**

Run: `docker exec archie_database psql -U archie -d archie -c "\dt chat_*"`
Expected: 3 tables listed (chat_conversations, chat_messages, chat_api_keys)

- [ ] **Step 4: Commit**

```bash
git add database/migrations/add_chat_tables.sql
git commit -m "feat(chat): add database tables for conversations, messages, and API keys"
```

---

### Task 2: Chat Service — Core Business Logic

**Files:**
- Create: `platform_v2/tools/archie_chat/chat_service.py`
- Create: `tests/test_chat_service.py`

- [ ] **Step 1: Write failing tests for conversation CRUD**

```python
# tests/test_chat_service.py
"""Tests for ARCHIE Chat service layer."""
import uuid
import pytest
from unittest.mock import patch, MagicMock


class TestCreateConversation:
    """Test conversation creation."""

    @patch("tools.archie_chat.chat_service.get_db_cursor")
    def test_creates_conversation_with_uuid(self, mock_cursor):
        from tools.archie_chat.chat_service import create_conversation

        mock_ctx = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = {
            "id": 1,
            "conversation_uuid": str(uuid.uuid4()),
            "title": None,
        }
        mock_ctx.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur))
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_cursor.return_value = mock_ctx

        result = create_conversation(user_id=1)
        assert result["success"] is True
        assert "conversation_uuid" in result

    @patch("tools.archie_chat.chat_service.get_db_cursor")
    def test_creates_team_conversation_for_kytran(self, mock_cursor):
        from tools.archie_chat.chat_service import create_conversation

        mock_ctx = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = {
            "id": 1,
            "conversation_uuid": str(uuid.uuid4()),
            "title": None,
            "team_id": 1,
        }
        mock_ctx.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur))
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_cursor.return_value = mock_ctx

        result = create_conversation(user_id=1, team_id=1)
        assert result["success"] is True


class TestSaveMessage:
    """Test message persistence."""

    @patch("tools.archie_chat.chat_service.get_db_cursor")
    def test_saves_user_message(self, mock_cursor):
        from tools.archie_chat.chat_service import save_message

        mock_ctx = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = {"id": 42}
        mock_ctx.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur))
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_cursor.return_value = mock_ctx

        result = save_message(
            conversation_id=1,
            role="user",
            content="Hello ARCHIE",
        )
        assert result["id"] == 42

    @patch("tools.archie_chat.chat_service.get_db_cursor")
    def test_saves_assistant_message_with_thinking_steps(self, mock_cursor):
        from tools.archie_chat.chat_service import save_message

        mock_ctx = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = {"id": 43}
        mock_ctx.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur))
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_cursor.return_value = mock_ctx

        steps = [{"step_type": "intent_parse", "label": "Intent", "duration_ms": 12}]
        result = save_message(
            conversation_id=1,
            role="assistant",
            content="Here is the analysis...",
            thinking_steps=steps,
            agent_used="Nexus",
            model_used="dolphin3-8k:latest",
            station_code="ANALYTICS",
            duration_ms=1230,
        )
        assert result["id"] == 43


class TestGetConversationHistory:
    """Test history retrieval."""

    @patch("tools.archie_chat.chat_service.get_db_cursor")
    def test_returns_messages_in_order(self, mock_cursor):
        from tools.archie_chat.chat_service import get_conversation_messages

        mock_ctx = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [
            {"id": 1, "role": "user", "content": "Hello"},
            {"id": 2, "role": "assistant", "content": "Hi there"},
        ]
        mock_ctx.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur))
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_cursor.return_value = mock_ctx

        messages = get_conversation_messages(conversation_id=1)
        assert len(messages) == 2
        assert messages[0]["role"] == "user"


class TestTierGating:
    """Test subscription tier access control."""

    @patch("tools.archie_chat.chat_service.get_db_cursor")
    def test_kytran_tier_allowed(self, mock_cursor):
        from tools.archie_chat.chat_service import check_chat_access

        mock_ctx = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = {"tier_name": "kytran"}
        mock_ctx.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur))
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_cursor.return_value = mock_ctx

        assert check_chat_access(user_id=1) is True

    @patch("tools.archie_chat.chat_service.get_db_cursor")
    def test_free_tier_denied(self, mock_cursor):
        from tools.archie_chat.chat_service import check_chat_access

        mock_ctx = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = {"tier_name": "free"}
        mock_ctx.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur))
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_cursor.return_value = mock_ctx

        assert check_chat_access(user_id=2) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /mnt/archie_brain && python -m pytest tests/test_chat_service.py -v 2>&1 | head -30`
Expected: FAIL — ModuleNotFoundError (chat_service doesn't exist yet)

- [ ] **Step 3: Create module directory structure**

```bash
mkdir -p platform_v2/tools/archie_chat/templates
touch platform_v2/tools/archie_chat/__init__.py
```

- [ ] **Step 4: Write chat_service.py**

```python
# platform_v2/tools/archie_chat/chat_service.py
"""
ARCHIE Chat Service — Business logic for conversations, messages, and tier-gating.

All DB access uses get_db_cursor(commit=True) with try/finally pattern.
Conversations are scoped by user_id (SaaS) or team_id (Kytran tier).
"""

import json
import logging
from typing import Optional, Dict, List, Any
from psycopg2.extras import Json

from database import get_db_cursor

logger = logging.getLogger(__name__)

# Tiers allowed to use ARCHIE Chat
ALLOWED_TIERS = {"kytran", "enterprise", "pro"}


def check_chat_access(user_id: int) -> bool:
    """Check if user's subscription tier allows chat access."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT st.name as tier_name
            FROM users u
            JOIN user_subscriptions us ON us.user_id = u.id AND us.is_active = TRUE
            JOIN subscription_tiers st ON st.id = us.tier_id
            WHERE u.id = %s
            ORDER BY us.created_at DESC LIMIT 1
            """,
            (user_id,),
        )
        row = cur.fetchone()
        if not row:
            return False
        return row["tier_name"].lower() in ALLOWED_TIERS


def get_user_team_id(user_id: int) -> Optional[int]:
    """Get team_id for Kytran-tier users. Returns None for SaaS users."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT st.name as tier_name
            FROM users u
            JOIN user_subscriptions us ON us.user_id = u.id AND us.is_active = TRUE
            JOIN subscription_tiers st ON st.id = us.tier_id
            WHERE u.id = %s
            ORDER BY us.created_at DESC LIMIT 1
            """,
            (user_id,),
        )
        row = cur.fetchone()
        if row and row["tier_name"].lower() == "kytran":
            return 1  # Kytran team namespace
        return None


def create_conversation(
    user_id: int,
    team_id: Optional[int] = None,
    title: Optional[str] = None,
    agent_target: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a new conversation thread."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO chat_conversations (user_id, team_id, title, agent_target)
            VALUES (%s, %s, %s, %s)
            RETURNING id, conversation_uuid, title, created_at
            """,
            (user_id, team_id, title, agent_target),
        )
        row = cur.fetchone()
        return {
            "success": True,
            "id": row["id"],
            "conversation_uuid": str(row["conversation_uuid"]),
            "title": row["title"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        }


def get_conversations(
    user_id: int,
    team_id: Optional[int] = None,
    page: int = 1,
    limit: int = 20,
    archived: bool = False,
) -> Dict[str, Any]:
    """List conversations for a user or team."""
    offset = (page - 1) * limit
    with get_db_cursor() as (conn, cur):
        if team_id:
            # Kytran tier: show all team conversations
            cur.execute(
                """
                SELECT id, conversation_uuid, user_id, title, agent_target,
                       is_archived, created_at, updated_at
                FROM chat_conversations
                WHERE team_id = %s AND is_archived = %s
                ORDER BY updated_at DESC
                LIMIT %s OFFSET %s
                """,
                (team_id, archived, limit, offset),
            )
        else:
            # SaaS tier: show only user's conversations
            cur.execute(
                """
                SELECT id, conversation_uuid, user_id, title, agent_target,
                       is_archived, created_at, updated_at
                FROM chat_conversations
                WHERE user_id = %s AND team_id IS NULL AND is_archived = %s
                ORDER BY updated_at DESC
                LIMIT %s OFFSET %s
                """,
                (user_id, archived, limit, offset),
            )
        rows = cur.fetchall()
        return {
            "conversations": [
                {
                    "id": r["id"],
                    "conversation_uuid": str(r["conversation_uuid"]),
                    "title": r["title"],
                    "agent_target": r["agent_target"],
                    "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                    "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
                }
                for r in rows
            ],
            "page": page,
            "limit": limit,
        }


def get_conversation_by_uuid(
    conversation_uuid: str, user_id: int, team_id: Optional[int] = None
) -> Optional[Dict]:
    """Load a conversation by UUID, enforcing ownership."""
    with get_db_cursor() as (conn, cur):
        if team_id:
            cur.execute(
                "SELECT * FROM chat_conversations WHERE conversation_uuid = %s AND team_id = %s",
                (conversation_uuid, team_id),
            )
        else:
            cur.execute(
                "SELECT * FROM chat_conversations WHERE conversation_uuid = %s AND user_id = %s",
                (conversation_uuid, user_id),
            )
        row = cur.fetchone()
        if not row:
            return None
        return dict(row)


def save_message(
    conversation_id: int,
    role: str,
    content: str,
    thinking_steps: Optional[List] = None,
    agent_used: Optional[str] = None,
    model_used: Optional[str] = None,
    station_code: Optional[str] = None,
    governance_events: Optional[List] = None,
    duration_ms: Optional[int] = None,
    token_count: Optional[int] = None,
) -> Dict[str, Any]:
    """Save a message to a conversation."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO chat_messages
                (conversation_id, role, content, thinking_steps, agent_used,
                 model_used, station_code, governance_events, duration_ms, token_count)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, created_at
            """,
            (
                conversation_id,
                role,
                content,
                Json(thinking_steps) if thinking_steps else None,
                agent_used,
                model_used,
                station_code,
                Json(governance_events) if governance_events else None,
                duration_ms,
                token_count,
            ),
        )
        row = cur.fetchone()
        # Update conversation timestamp
        cur.execute(
            "UPDATE chat_conversations SET updated_at = NOW() WHERE id = %s",
            (conversation_id,),
        )
        return {"id": row["id"], "created_at": row["created_at"].isoformat()}


def get_conversation_messages(
    conversation_id: int,
    include_thinking: bool = True,
    limit: int = 50,
    before_id: Optional[int] = None,
) -> List[Dict]:
    """Get messages for a conversation, ordered by created_at."""
    with get_db_cursor() as (conn, cur):
        if before_id:
            cur.execute(
                """
                SELECT id, role, content, thinking_steps, agent_used, model_used,
                       station_code, governance_events, duration_ms, token_count, created_at
                FROM chat_messages
                WHERE conversation_id = %s AND id < %s
                ORDER BY created_at ASC
                LIMIT %s
                """,
                (conversation_id, before_id, limit),
            )
        else:
            cur.execute(
                """
                SELECT id, role, content, thinking_steps, agent_used, model_used,
                       station_code, governance_events, duration_ms, token_count, created_at
                FROM chat_messages
                WHERE conversation_id = %s
                ORDER BY created_at ASC
                LIMIT %s
                """,
                (conversation_id, limit),
            )
        rows = cur.fetchall()
        messages = []
        for r in rows:
            msg = {
                "id": r["id"],
                "role": r["role"],
                "content": r["content"],
                "agent_used": r["agent_used"],
                "model_used": r["model_used"],
                "station_code": r["station_code"],
                "duration_ms": r["duration_ms"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            if include_thinking:
                msg["thinking_steps"] = r["thinking_steps"]
                msg["governance_events"] = r["governance_events"]
            messages.append(msg)
        return messages


def archive_conversation(conversation_id: int, user_id: int) -> bool:
    """Soft-delete a conversation."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            UPDATE chat_conversations SET is_archived = TRUE, updated_at = NOW()
            WHERE id = %s AND user_id = %s AND is_archived = FALSE
            """,
            (conversation_id, user_id),
        )
        return cur.rowcount > 0


def auto_title_conversation(conversation_id: int, first_message: str) -> None:
    """Set conversation title from first message (truncated to 100 chars)."""
    title = first_message[:100].strip()
    if len(first_message) > 100:
        title += "..."
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE chat_conversations SET title = %s WHERE id = %s AND title IS NULL",
            (title, conversation_id),
        )
```

- [ ] **Step 5: Run tests**

Run: `cd /mnt/archie_brain && python -m pytest tests/test_chat_service.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add platform_v2/tools/archie_chat/ tests/test_chat_service.py
git commit -m "feat(chat): add chat service with conversation CRUD, messaging, and tier-gating"
```

---

### Task 3: Auth Middleware — Dual Authentication

**Files:**
- Create: `platform_v2/tools/archie_chat/auth_middleware.py`

- [ ] **Step 1: Write auth_middleware.py**

```python
# platform_v2/tools/archie_chat/auth_middleware.py
"""
Dual authentication middleware for ARCHIE Chat.

Supports two auth paths:
1. Session cookie (browser) — existing Flask login_required
2. Bearer token (API) — chat_api_keys table

Usage:
    @chat_auth_required
    def my_endpoint():
        user = get_chat_user()  # works for both auth paths
"""

import hashlib
import secrets
import logging
from functools import wraps
from flask import request, jsonify, g
from flask_login import current_user

from database import get_db_cursor

logger = logging.getLogger(__name__)


def _check_bearer_token() -> dict | None:
    """Validate bearer token from Authorization header. Returns user dict or None."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None

    token = auth_header[7:]
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            SELECT k.id, k.user_id, k.scopes, k.rate_limit, u.username, u.is_admin
            FROM chat_api_keys k
            JOIN users u ON u.id = k.user_id
            WHERE k.key_hash = %s AND k.is_active = TRUE
            """,
            (token_hash,),
        )
        row = cur.fetchone()
        if not row:
            return None

        # Update last_used_at
        cur.execute(
            "UPDATE chat_api_keys SET last_used_at = NOW() WHERE id = %s",
            (row["id"],),
        )
        return {
            "id": row["user_id"],
            "username": row["username"],
            "is_admin": row["is_admin"],
            "auth_method": "api_key",
            "key_id": row["id"],
            "scopes": row["scopes"] or ["chat"],
            "rate_limit": row["rate_limit"],
        }


def chat_auth_required(f):
    """Decorator: require either session cookie or valid API key."""

    @wraps(f)
    def decorated(*args, **kwargs):
        # Try bearer token first
        api_user = _check_bearer_token()
        if api_user:
            g.chat_user = api_user
            return f(*args, **kwargs)

        # Fall back to session cookie
        if current_user.is_authenticated:
            g.chat_user = {
                "id": current_user.id,
                "username": current_user.username,
                "is_admin": current_user.is_admin,
                "auth_method": "session",
                "scopes": ["chat", "admin"] if current_user.is_admin else ["chat"],
                "rate_limit": 0,  # unlimited for session users
            }
            return f(*args, **kwargs)

        return jsonify({"success": False, "error": {"code": "AUTH_FAILED", "message": "Authentication required"}}), 401

    return decorated


def get_chat_user() -> dict:
    """Get the authenticated chat user (set by chat_auth_required)."""
    return getattr(g, "chat_user", None)


def generate_api_key(user_id: int, name: str, rate_limit: int = 30) -> dict:
    """Generate a new API key for a user. Returns the raw key (shown once)."""
    raw_key = f"archie_{secrets.token_hex(24)}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_prefix = raw_key[:12]

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO chat_api_keys (user_id, key_hash, key_prefix, name, rate_limit)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, created_at
            """,
            (user_id, key_hash, key_prefix, name, rate_limit),
        )
        row = cur.fetchone()
        return {
            "id": row["id"],
            "key": raw_key,  # shown once, never stored
            "prefix": key_prefix,
            "name": name,
            "rate_limit": rate_limit,
        }
```

- [ ] **Step 2: Commit**

```bash
git add platform_v2/tools/archie_chat/auth_middleware.py
git commit -m "feat(chat): add dual auth middleware for session cookie and API key"
```

---

### Task 4: Add agent_target to OrchestrationEngine

**Files:**
- Modify: `ai_bridge/orchestration_engine.py:210-217`

- [ ] **Step 1: Read the current orchestrate() method signature and agent selection logic**

Read `ai_bridge/orchestration_engine.py` lines 210-240 (signature) and find the agent selection step (search for `agent_select` or `_select_agent`).

- [ ] **Step 2: Add agent_target parameter to orchestrate()**

In `ai_bridge/orchestration_engine.py`, modify the `orchestrate` method signature:

```python
# Change from:
def orchestrate(
    self,
    message: str,
    user_id: int,
    conversation_id: Optional[str] = None,
    voice_mode: bool = False,
    user_context: Optional[Dict] = None,
) -> OrchestrationResult:

# Change to:
def orchestrate(
    self,
    message: str,
    user_id: int,
    conversation_id: Optional[str] = None,
    voice_mode: bool = False,
    user_context: Optional[Dict] = None,
    agent_target: Optional[str] = None,
) -> OrchestrationResult:
```

- [ ] **Step 3: Add agent_target override logic in the pipeline**

Find the agent selection step in the orchestrate method body. Before the existing agent selection logic, add the override:

```python
# Add before the existing agent/station selection logic:
if agent_target:
    # Check if it's a station code (uppercase) or agent name
    from bridge_dispatcher import get_dispatcher
    dispatcher = get_dispatcher()

    if agent_target.upper() in (
        "COMMAND", "ANALYTICS", "CREATIVE", "ENGINEERING",
        "COMMUNICATIONS", "RESEARCH", "SECURITY", "LOGISTICS",
        "DIPLOMATIC", "OPERATIONS",
    ):
        # Station targeting: override routing, select best agent from station
        target_station = agent_target.upper()
        steps.append(ThinkingStep(
            step_type=StepType.AGENT_SELECT.value,
            label="Agent Target (Station)",
            data={"station_override": target_station},
        ))
    else:
        # Agent name targeting: skip routing + selection entirely
        steps.append(ThinkingStep(
            step_type=StepType.AGENT_SELECT.value,
            label="Agent Target (Direct)",
            data={"agent_override": agent_target},
        ))
```

Note: The exact insertion point depends on the current code structure. Read the full orchestrate() method body to find where agent selection happens and insert the override just before it.

- [ ] **Step 4: Test manually**

Run: `docker exec archie_platform python3 -c "from ai_bridge.orchestration_engine import OrchestrationEngine; e = OrchestrationEngine(); print(e.orchestrate.__code__.co_varnames[:7])"`
Expected: Should include 'agent_target' in the parameter names

- [ ] **Step 5: Commit**

```bash
git add ai_bridge/orchestration_engine.py
git commit -m "feat(chat): add agent_target parameter to OrchestrationEngine.orchestrate()"
```

---

### Task 5: API Routes — Chat Endpoints

**Files:**
- Create: `platform_v2/tools/archie_chat/api_routes.py`
- Create: `tests/test_chat_api.py`

- [ ] **Step 1: Write api_routes.py**

```python
# platform_v2/tools/archie_chat/api_routes.py
"""
ARCHIE Chat API endpoints.

All endpoints use chat_auth_required for dual auth (session + API key).
Conversations are scoped by user_id or team_id based on tier.
"""

import logging
from flask import request, jsonify

from .auth_middleware import chat_auth_required, get_chat_user, generate_api_key
from .chat_service import (
    check_chat_access,
    get_user_team_id,
    create_conversation,
    get_conversations,
    get_conversation_by_uuid,
    save_message,
    get_conversation_messages,
    archive_conversation,
    auto_title_conversation,
)

logger = logging.getLogger(__name__)


def register_routes(bp, admin_required):
    """Register chat API routes on the blueprint."""

    @bp.route("/api/v1/chat/message", methods=["POST"])
    @chat_auth_required
    def chat_message():
        """Send a message and get orchestrated response."""
        user = get_chat_user()
        user_id = user["id"]

        # Tier check
        if not check_chat_access(user_id):
            return jsonify({
                "success": False,
                "error": {"code": "TIER_REQUIRED", "message": "Chat requires Kytran, Enterprise, or Pro tier"}
            }), 403

        data = request.get_json()
        if not data or not data.get("message", "").strip():
            return jsonify({
                "success": False,
                "error": {"code": "VALIDATION_ERROR", "message": "Message is required"}
            }), 400

        message = data["message"].strip()
        conversation_uuid = data.get("conversation_id")
        agent_target = data.get("agent_target")
        include_thinking = data.get("include_thinking", True)
        include_knowledge = data.get("include_knowledge", False)

        team_id = get_user_team_id(user_id)

        # Load or create conversation
        if conversation_uuid:
            conv = get_conversation_by_uuid(conversation_uuid, user_id, team_id)
            if not conv:
                return jsonify({
                    "success": False,
                    "error": {"code": "CONVERSATION_NOT_FOUND", "message": "Conversation not found"}
                }), 404
        else:
            conv_result = create_conversation(
                user_id=user_id,
                team_id=team_id,
                agent_target=agent_target,
            )
            conv = {
                "id": conv_result["id"],
                "conversation_uuid": conv_result["conversation_uuid"],
            }

        # Save user message
        save_message(conversation_id=conv["id"], role="user", content=message)

        # Auto-title from first message
        auto_title_conversation(conv["id"], message)

        # Rate limit check (API key users only)
        from .auth_middleware import check_rate_limit
        if user.get("rate_limit", 0) > 0:
            if not check_rate_limit(user["id"], user["rate_limit"]):
                return jsonify({
                    "success": False,
                    "error": {"code": "RATE_LIMITED", "message": "Too many requests. Try again shortly."}
                }), 429

        # Run orchestration pipeline
        # Note: ai_bridge is already on sys.path via app.py startup
        try:
            from ai_bridge.orchestration_engine import OrchestrationEngine

            engine = OrchestrationEngine()  # Lightweight — no cached state to preserve
            result = engine.orchestrate(
                message=message,
                user_id=user_id,
                conversation_id=str(conv.get("conversation_uuid", conv.get("id"))),
                agent_target=agent_target,
                user_context={"username": user.get("username", "")},
            )
        except Exception as e:
            logger.error("Orchestration failed: %s", e)
            return jsonify({
                "success": False,
                "error": {"code": "ORCHESTRATION_FAILED", "message": str(e)[:200]},
                "conversation_id": conv.get("conversation_uuid"),
            }), 500

        if not result.success:
            return jsonify({
                "success": False,
                "error": {"code": "ORCHESTRATION_FAILED", "message": result.error or "Unknown error"},
                "conversation_id": conv.get("conversation_uuid"),
            }), 500

        # Resolve agent display_name and station from DB
        agent_display_name = result.agent_used
        agent_station = None
        if result.agent_used:
            try:
                from database import get_db_cursor as _get_cursor
                with _get_cursor() as (conn, cur):
                    cur.execute(
                        """SELECT a.display_name, sa.station_code
                           FROM agents a
                           LEFT JOIN station_assignments sa ON sa.agent_id = a.id AND sa.is_active = TRUE
                           WHERE a.name = %s LIMIT 1""",
                        (result.agent_used,),
                    )
                    row = cur.fetchone()
                    if row:
                        agent_display_name = row["display_name"] or result.agent_used
                        agent_station = row["station_code"]
            except Exception:
                pass

        # Save assistant message
        result_dict = result.to_dict() if hasattr(result, "to_dict") else {}
        saved_msg = save_message(
            conversation_id=conv["id"],
            role="assistant",
            content=result.response,
            thinking_steps=result_dict.get("thinking_steps"),
            agent_used=result.agent_used,
            model_used=result.model_used,
            station_code=agent_station,
            governance_events=result_dict.get("governance_events"),
            duration_ms=result.total_duration_ms,
        )

        # Build response
        response = {
            "success": True,
            "conversation_id": conv.get("conversation_uuid"),
            "message_id": saved_msg["id"],
            "response": result.response,
            "agent": {
                "name": result.agent_used,
                "display_name": agent_display_name,
                "station": agent_station,
            },
            "model_used": result.model_used,
            "duration_ms": result.total_duration_ms,
        }

        if include_thinking:
            response["thinking_steps"] = result_dict.get("thinking_steps", [])
            response["governance_events"] = result_dict.get("governance_events", [])

        return jsonify(response)

    @bp.route("/api/v1/chat/conversations", methods=["GET"])
    @chat_auth_required
    def list_conversations():
        """List user's conversations."""
        user = get_chat_user()
        team_id = get_user_team_id(user["id"])
        page = request.args.get("page", 1, type=int)
        limit = min(request.args.get("limit", 20, type=int), 50)
        archived = request.args.get("archived", "false").lower() == "true"

        result = get_conversations(
            user_id=user["id"], team_id=team_id, page=page, limit=limit, archived=archived,
        )
        return jsonify({"success": True, **result})

    @bp.route("/api/v1/chat/conversations", methods=["POST"])
    @chat_auth_required
    def create_new_conversation():
        """Create a new conversation explicitly."""
        user = get_chat_user()
        data = request.get_json() or {}
        team_id = get_user_team_id(user["id"])

        result = create_conversation(
            user_id=user["id"],
            team_id=team_id,
            title=data.get("title"),
            agent_target=data.get("agent_target"),
        )
        return jsonify(result), 201

    @bp.route("/api/v1/chat/conversations/<conversation_uuid>/messages", methods=["GET"])
    @chat_auth_required
    def get_messages(conversation_uuid):
        """Get messages for a conversation."""
        user = get_chat_user()
        team_id = get_user_team_id(user["id"])

        conv = get_conversation_by_uuid(conversation_uuid, user["id"], team_id)
        if not conv:
            return jsonify({
                "success": False,
                "error": {"code": "CONVERSATION_NOT_FOUND", "message": "Not found"}
            }), 404

        include_thinking = request.args.get("include_thinking", "true").lower() == "true"
        limit = min(request.args.get("limit", 50, type=int), 200)
        before_id = request.args.get("before", None, type=int)

        messages = get_conversation_messages(
            conversation_id=conv["id"],
            include_thinking=include_thinking,
            limit=limit,
            before_id=before_id,
        )
        return jsonify({"success": True, "messages": messages})

    @bp.route("/api/v1/chat/conversations/<int:conv_id>", methods=["DELETE"])
    @chat_auth_required
    def delete_conversation(conv_id):
        """Archive a conversation (soft delete)."""
        user = get_chat_user()
        success = archive_conversation(conv_id, user["id"])
        if not success:
            return jsonify({
                "success": False,
                "error": {"code": "CONVERSATION_NOT_FOUND", "message": "Not found or already archived"}
            }), 404
        return jsonify({"success": True})

    @bp.route("/api/v1/chat/agents", methods=["GET"])
    @chat_auth_required
    def list_agents():
        """List available agents for targeting."""
        from database import get_db_cursor as _get_cursor

        with _get_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT a.id, a.name, a.display_name, sa.station_code,
                       a.shift_state, a.model
                FROM agents a
                LEFT JOIN station_assignments sa ON sa.agent_id = a.id AND sa.is_active = TRUE
                WHERE a.status = 'active' AND a.shift_state IN ('active', 'deployed')
                ORDER BY sa.station_code, a.display_name
                """
            )
            agents = [
                {
                    "name": r["name"],
                    "display_name": r["display_name"],
                    "station": r["station_code"],
                    "model": r["model"],
                    "shift_state": r["shift_state"],
                }
                for r in cur.fetchall()
            ]
        return jsonify({"success": True, "agents": agents})

    @bp.route("/api/v1/chat/stations", methods=["GET"])
    @chat_auth_required
    def list_stations():
        """List stations with their capabilities."""
        stations = [
            {"code": "COMMAND", "color": "#00e5ff", "capabilities": ["conversation", "dispatch", "governance"]},
            {"code": "ANALYTICS", "color": "#8b5cf6", "capabilities": ["classify", "sentiment", "embedding", "vision"]},
            {"code": "CREATIVE", "color": "#f472b6", "capabilities": ["image", "design", "content"]},
            {"code": "ENGINEERING", "color": "#fbbf24", "capabilities": ["code", "code_review", "testing", "debugging"]},
            {"code": "COMMUNICATIONS", "color": "#22d3ee", "capabilities": ["translate", "social", "email"]},
            {"code": "RESEARCH", "color": "#10b981", "capabilities": ["research", "summarize", "knowledge"]},
            {"code": "SECURITY", "color": "#ef4444", "capabilities": ["vulnerability_scan", "threat_analysis"]},
            {"code": "LOGISTICS", "color": "#f97316", "capabilities": ["scheduling", "inventory", "operations"]},
            {"code": "DIPLOMATIC", "color": "#818cf8", "capabilities": ["negotiation", "crm", "outreach"]},
            {"code": "OPERATIONS", "color": "#a3e635", "capabilities": ["system_monitoring", "backup", "health_check"]},
        ]
        return jsonify({"success": True, "stations": stations})

    @bp.route("/api/v1/chat/keys", methods=["POST"])
    @chat_auth_required
    def create_api_key():
        """Generate a new API key. Admin only."""
        user = get_chat_user()
        if not user.get("is_admin"):
            return jsonify({
                "success": False,
                "error": {"code": "AUTH_FAILED", "message": "Admin access required"}
            }), 403

        data = request.get_json() or {}
        name = data.get("name", "API Key")
        rate_limit = data.get("rate_limit", 30)

        result = generate_api_key(user["id"], name, rate_limit)
        return jsonify({"success": True, **result}), 201
```

- [ ] **Step 2: Commit**

```bash
git add platform_v2/tools/archie_chat/api_routes.py
git commit -m "feat(chat): add REST API endpoints for chat, conversations, agents, and API keys"
```

---

### Task 6: Blueprint Registration + Module Registry

**Files:**
- Create: `platform_v2/tools/archie_chat/routes.py`
- Modify: `platform_v2/tools/archie_chat/__init__.py`
- Modify: `platform_v2/module_registry.py`
- Modify: `platform_v2/rbac.py`
- Modify: `platform_v2/app.py`

- [ ] **Step 1: Write routes.py (page routes)**

```python
# platform_v2/tools/archie_chat/routes.py
"""Page routes for ARCHIE Chat module."""

from flask import render_template
from flask_login import login_required
from rbac import admin_required


def register_routes(bp, _admin_required):
    """Register page-rendering routes."""

    @bp.route("/")
    @login_required
    def chat_page():
        # Blueprint has template_folder="templates", so path is relative to that
        return render_template("archie_chat.html")
```

- [ ] **Step 2: Write __init__.py (ADR-045 pattern)**

```python
# platform_v2/tools/archie_chat/__init__.py
"""
ARCHIE Chat Module — Chat with ARCHIE's agent fleet.

Uses ADR-045 route registration pattern (same as dev_pipeline, starbase).
Chat routes use chat_auth_required (dual auth) instead of admin_required.
"""

from flask import Blueprint

archie_chat_bp = Blueprint(
    "archie_chat",
    __name__,
    url_prefix="/tools/archie-chat",
    template_folder="templates",
)

from .routes import register_routes as register_page_routes  # noqa: E402
from .api_routes import register_routes as register_api_routes  # noqa: E402

# Chat uses its own chat_auth_required decorator (not admin_required)
# so we pass None here — the register functions don't use it for API routes.
# Page routes use login_required directly.
register_page_routes(archie_chat_bp, None)
register_api_routes(archie_chat_bp, None)
```

- [ ] **Step 3: Add module to module_registry.py**

Find the AI_COMMAND modules section and add the archie_chat entry. Search for `"archie_core"` or `"dev_pipeline"` to find the right section. Add:

```python
ModuleConfig(
    module_id="archie_chat",
    name="ARCHIE Chat",
    description="Chat with ARCHIE's agent fleet — full orchestration pipeline with flight deck visibility",
    category=ModuleCategory.AI_COMMAND,
    route="/tools/archie-chat",
    blueprint_import="tools.archie_chat:archie_chat_bp",
    required_permissions=[],
    health_check=_check_archie_chat_health,
),
```

Also add the health check function nearby:

```python
def _check_archie_chat_health():
    try:
        from database import get_db_cursor
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT status FROM service_status WHERE service_name = 'ai_bridge'")
            row = cur.fetchone()
            bridge_online = row and row["status"] == "online"
            cur.execute("SELECT COUNT(*) as cnt FROM agents WHERE status = 'active'")
            agent_count = cur.fetchone()["cnt"]
        if bridge_online and agent_count > 0:
            return {"healthy": True, "module_id": "archie_chat", "message": f"Chat operational, {agent_count} agents", "status": "healthy"}
        return {"healthy": False, "module_id": "archie_chat", "message": f"Bridge: {'online' if bridge_online else 'offline'}, Agents: {agent_count}", "status": "degraded"}
    except Exception as e:
        return {"healthy": False, "module_id": "archie_chat", "message": str(e)[:100], "status": "error"}
```

- [ ] **Step 4: Add permission to rbac.py**

Find the permission enum and add:

```python
ADMIN_ARCHIE_CHAT = "admin:archie_chat"
```

Add `"archie_chat"` to the tier permission mappings for kytran, enterprise, and pro tiers.

- [ ] **Step 5: Register blueprint in app.py**

Find where other blueprints are registered (search for `dev_pipeline_bp` or `register_blueprint`). Add:

```python
from tools.archie_chat import archie_chat_bp
app.register_blueprint(archie_chat_bp)
```

- [ ] **Step 6: Test module loads**

Run: `docker compose restart archie_platform && sleep 5 && docker logs archie_platform 2>&1 | tail -20`
Expected: No import errors, platform starts successfully

- [ ] **Step 7: Commit**

```bash
git add platform_v2/tools/archie_chat/ platform_v2/module_registry.py platform_v2/rbac.py platform_v2/app.py
git commit -m "feat(chat): register ARCHIE Chat module with blueprint, module_registry, and rbac"
```

---

## Phase 2 — Module UI

### Task 7: LCARS Chat Template

**Files:**
- Create: `platform_v2/tools/archie_chat/templates/archie_chat.html`

- [ ] **Step 1: Write the LCARS chat template**

Create a three-panel layout extending `base.html`:
- Left: conversation sidebar (240px) with new chat button, conversation list, agent target dropdown
- Center: message area with input
- Right: flight deck panel (260px, collapsible)

Use the same LCARS styling patterns as consciousness module (`cs-` prefix pattern → use `ac-` prefix for archie chat). Include:
- `{% extends "base.html" %}`
- `{% block title %}ARCHIE Chat{% endblock %}`
- CSS link to `archie-chat.css`
- JS link to `archie-chat.js`
- Container divs for sidebar, chat area, flight deck
- Message input form with send button
- Agent target dropdown (auto-route + stations)

Reference `platform_v2/tools/consciousness/templates/consciousness.html` for the LCARS layout pattern.

- [ ] **Step 2: Verify template renders**

Run: `docker compose restart archie_platform && sleep 3`
Then visit: http://192.168.1.200:3000/tools/archie-chat
Expected: Page loads (even if empty/unstyled)

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/archie_chat/templates/archie_chat.html
git commit -m "feat(chat): add LCARS chat template with three-panel layout"
```

---

### Task 8: Chat CSS

**Files:**
- Create: `platform_v2/static/css/archie-chat.css`

- [ ] **Step 1: Write archie-chat.css**

LCARS-styled CSS with `ac-` prefix. Include:
- Three-panel flex layout (sidebar 240px, chat flex-1, flight deck 260px)
- `.ac-sidebar` — conversation list, new chat button, agent dropdown
- `.ac-chat` — message area with auto-scroll
- `.ac-message-user` — right-aligned, cyan tint
- `.ac-message-assistant` — left-aligned with agent avatar, grey bg
- `.ac-agent-badge` — agent name + station color dot
- `.ac-flight-deck` — collapsible right panel
- `.ac-step-card` — thinking step card with color-coded left border
- `.ac-input-area` — input bar at bottom
- Responsive breakpoints: 480px (stack), 768px (hide flight deck), 1024px (full)
- Station colors matching the 10 canonical colors from starbase rules

- [ ] **Step 2: Commit**

```bash
git add platform_v2/static/css/archie-chat.css
git commit -m "feat(chat): add LCARS chat styles with flight deck and responsive layout"
```

---

### Task 9: Chat JavaScript

**Files:**
- Create: `platform_v2/static/js/archie-chat.js`

- [ ] **Step 1: Write archie-chat.js**

Vanilla JS module handling:
- `ArchieChatUI` class with methods:
  - `init()` — load conversations, bind events
  - `sendMessage()` — POST to `/api/v1/chat/message`, render response
  - `loadConversations()` — GET conversations, render sidebar
  - `switchConversation(uuid)` — load messages for selected conversation
  - `renderMessage(msg)` — create DOM node for user/assistant message
  - `renderThinkingSteps(steps)` — populate flight deck panel
  - `toggleFlightDeck()` — show/hide right panel
  - `setAgentTarget(target)` — update agent dropdown selection
- API helper: `async chatApi(endpoint, options)` — handles fetch + error display
- Auto-scroll on new messages
- Enter key to send (Shift+Enter for newline)
- Loading state during orchestration (show spinner + "Thinking..." in flight deck)

Reference `platform_v2/static/js/consciousness.js` for the `api()` helper pattern and `escHtml()`/`setHtml()` utilities.

- [ ] **Step 2: Test end-to-end**

Run: `docker compose restart archie_platform`
Visit: http://192.168.1.200:3000/tools/archie-chat
Test: Send a message, verify response appears with flight deck steps

- [ ] **Step 3: Commit**

```bash
git add platform_v2/static/js/archie-chat.js
git commit -m "feat(chat): add chat UI with message handling, flight deck, and conversation management"
```

---

## Phase 3 — Global Overlay

### Task 10: Overlay Widget

**Files:**
- Create: `platform_v2/static/js/archie-chat-overlay.js`
- Modify: `platform_v2/templates/base.html`

- [ ] **Step 1: Write archie-chat-overlay.js**

Self-contained widget that:
- Creates floating bubble (bottom-right, 48px circle, ARCHIE cyan)
- Expands to 360x400px compact chat window on click
- Has header (ARCHIE status + expand/minimize buttons)
- Scrollable message area (no flight deck)
- Compact input + send
- "Expand to full" icon links to `/tools/archie-chat?conversation={uuid}`
- Uses same `/api/v1/chat/message` API endpoint
- Persists expanded/minimized state in localStorage
- `ArchieOverlay.init()` called on DOMContentLoaded

- [ ] **Step 2: Inject in base.html for Kytran/admin users**

Find the `</body>` tag area in `platform_v2/templates/base.html`. Add:

```html
{% if current_user.is_authenticated and current_user.is_admin %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/archie-chat.css') }}">
<script src="{{ url_for('static', filename='js/archie-chat-overlay.js') }}"></script>
{% endif %}
```

The overlay CSS should be included in `archie-chat.css` with `.ac-overlay-*` prefixed classes.

- [ ] **Step 3: Test overlay**

Run: `docker compose restart archie_platform`
Visit: http://192.168.1.200:3000/dashboard (or any page)
Expected: Floating bubble visible (admin user), expands to chat on click

- [ ] **Step 4: Commit**

```bash
git add platform_v2/static/js/archie-chat-overlay.js platform_v2/templates/base.html
git commit -m "feat(chat): add global overlay widget for Kytran/admin users"
```

---

## Phase 4 — API & Integration

### Task 11: API Key Management UI

**Files:**
- Modify: `platform_v2/tools/archie_chat/api_routes.py` (add list/delete key endpoints)

- [ ] **Step 1: Add list and delete key endpoints**

Add to `api_routes.py` in the `register_routes` function:

```python
@bp.route("/api/v1/chat/keys", methods=["GET"])
@chat_auth_required
def list_api_keys():
    """List user's API keys (without the actual key)."""
    user = get_chat_user()
    from database import get_db_cursor as _get_cursor
    with _get_cursor() as (conn, cur):
        cur.execute(
            """SELECT id, key_prefix, name, rate_limit, is_active, last_used_at, created_at
               FROM chat_api_keys WHERE user_id = %s ORDER BY created_at DESC""",
            (user["id"],),
        )
        keys = [
            {
                "id": r["id"],
                "prefix": r["key_prefix"],
                "name": r["name"],
                "rate_limit": r["rate_limit"],
                "is_active": r["is_active"],
                "last_used_at": r["last_used_at"].isoformat() if r["last_used_at"] else None,
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in cur.fetchall()
        ]
    return jsonify({"success": True, "keys": keys})

@bp.route("/api/v1/chat/keys/<int:key_id>", methods=["DELETE"])
@chat_auth_required
def revoke_api_key(key_id):
    """Revoke an API key."""
    user = get_chat_user()
    from database import get_db_cursor as _get_cursor
    with _get_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE chat_api_keys SET is_active = FALSE WHERE id = %s AND user_id = %s",
            (key_id, user["id"]),
        )
        if cur.rowcount == 0:
            return jsonify({"success": False, "error": {"code": "NOT_FOUND", "message": "Key not found"}}), 404
    return jsonify({"success": True})
```

- [ ] **Step 2: Commit**

```bash
git add platform_v2/tools/archie_chat/api_routes.py
git commit -m "feat(chat): add API key list and revoke endpoints"
```

---

### Task 12: Rate Limiting

**Files:**
- Modify: `platform_v2/tools/archie_chat/auth_middleware.py`

- [ ] **Step 1: Add rate limit check to auth middleware**

Add a rate limit check function using a simple in-memory counter (or DB-based for persistence):

```python
import time
from collections import defaultdict

# Simple in-memory rate limiter (resets on restart, good enough for v1)
_rate_counters = defaultdict(list)

def check_rate_limit(user_id: int, limit: int) -> bool:
    """Check if user is within rate limit. Returns True if allowed."""
    if limit <= 0:
        return True  # unlimited
    now = time.time()
    window = 60  # 1 minute
    key = f"chat:{user_id}"
    # Clean old entries
    _rate_counters[key] = [t for t in _rate_counters[key] if now - t < window]
    if len(_rate_counters[key]) >= limit:
        return False
    _rate_counters[key].append(now)
    return True
```

Then use in the `chat_auth_required` decorator (or at the start of the `chat_message` endpoint).

- [ ] **Step 2: Commit**

```bash
git add platform_v2/tools/archie_chat/auth_middleware.py
git commit -m "feat(chat): add in-memory rate limiting for API key users"
```

---

## Phase 5 — Memory & Polish

### Task 13: Cross-Session Memory

**Files:**
- Modify: `platform_v2/tools/archie_chat/api_routes.py`

- [ ] **Step 1: Add conversation_ingest integration**

After saving the assistant message in the `chat_message` endpoint, call `ingest_conversation` to store in KB for cross-session recall:

```python
# After save_message for assistant response:
try:
    from ai_bridge.conversation_ingest import ingest_conversation
    ingest_conversation(
        user_message=message,
        ai_response=result.response,
        user_id=user_id,
        source="archie_chat",
        model=result.model_used or "",
        provider="orchestration",
    )
except Exception as e:
    logger.debug("Conversation ingest skipped: %s", e)
```

- [ ] **Step 2: Commit**

```bash
git add platform_v2/tools/archie_chat/api_routes.py
git commit -m "feat(chat): add cross-session memory via conversation_ingest"
```

---

### Task 14: KB Augmentation Display

**Files:**
- Modify: `platform_v2/tools/archie_chat/api_routes.py`

- [ ] **Step 1: Add knowledge_used to response**

Before calling `orchestrate()`, capture KB context and include in response when `include_knowledge=true`:

```python
if include_knowledge:
    try:
        from ai_bridge.knowledge_retrieval import get_relevant_knowledge
        kb_context = get_relevant_knowledge(message, max_results=3)
        response["knowledge_used"] = kb_context if isinstance(kb_context, list) else []
    except Exception:
        response["knowledge_used"] = []
```

- [ ] **Step 2: Commit**

```bash
git add platform_v2/tools/archie_chat/api_routes.py
git commit -m "feat(chat): add KB augmentation display in API response"
```

---

### Task 15: Conversation Search

**Files:**
- Modify: `platform_v2/tools/archie_chat/chat_service.py`
- Modify: `platform_v2/tools/archie_chat/api_routes.py`

- [ ] **Step 1: Add search function to chat_service.py**

```python
def search_conversations(user_id: int, query: str, team_id: Optional[int] = None, limit: int = 20) -> List[Dict]:
    """Search conversations by title or message content."""
    # Escape ILIKE wildcards in user input
    safe_query = query.replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{safe_query}%"
    with get_db_cursor() as (conn, cur):
        if team_id:
            cur.execute(
                """
                SELECT DISTINCT c.id, c.conversation_uuid, c.title, c.updated_at
                FROM chat_conversations c
                LEFT JOIN chat_messages m ON m.conversation_id = c.id
                WHERE c.team_id = %s AND c.is_archived = FALSE
                  AND (c.title ILIKE %s OR m.content ILIKE %s)
                ORDER BY c.updated_at DESC LIMIT %s
                """,
                (team_id, pattern, pattern, limit),
            )
        else:
            cur.execute(
                """
                SELECT DISTINCT c.id, c.conversation_uuid, c.title, c.updated_at
                FROM chat_conversations c
                LEFT JOIN chat_messages m ON m.conversation_id = c.id
                WHERE c.user_id = %s AND c.team_id IS NULL AND c.is_archived = FALSE
                  AND (c.title ILIKE %s OR m.content ILIKE %s)
                ORDER BY c.updated_at DESC LIMIT %s
                """,
                (user_id, pattern, pattern, limit),
            )
        return [
            {
                "conversation_uuid": str(r["conversation_uuid"]),
                "title": r["title"],
                "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
            }
            for r in cur.fetchall()
        ]
```

- [ ] **Step 2: Add search endpoint to api_routes.py**

```python
@bp.route("/api/v1/chat/conversations/search", methods=["GET"])
@chat_auth_required
def search_convos():
    user = get_chat_user()
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "message": "Query required"}}), 400
    team_id = get_user_team_id(user["id"])
    from .chat_service import search_conversations
    results = search_conversations(user["id"], query, team_id)
    return jsonify({"success": True, "results": results})
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/archie_chat/chat_service.py platform_v2/tools/archie_chat/api_routes.py
git commit -m "feat(chat): add conversation search by title and message content"
```

---

### Task 16: Direct KB Search Endpoint

**Files:**
- Modify: `platform_v2/tools/archie_chat/api_routes.py`

- [ ] **Step 1: Add KB search endpoint**

Add to `register_routes` in `api_routes.py`:

```python
@bp.route("/api/v1/chat/knowledge/search", methods=["GET"])
@chat_auth_required
def search_knowledge():
    """Direct KB search without chat — returns relevant entries."""
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"success": False, "error": {"code": "VALIDATION_ERROR", "message": "Query required"}}), 400
    limit = min(request.args.get("limit", 10, type=int), 50)
    try:
        from ai_bridge.knowledge_retrieval import get_relevant_knowledge
        results = get_relevant_knowledge(query, max_results=limit)
        return jsonify({"success": True, "query": query, "results": results if isinstance(results, list) else []})
    except Exception as e:
        logger.error("KB search failed: %s", e)
        return jsonify({"success": False, "error": {"code": "ORCHESTRATION_FAILED", "message": str(e)[:200]}}), 500
```

- [ ] **Step 2: Commit**

```bash
git add platform_v2/tools/archie_chat/api_routes.py
git commit -m "feat(chat): add direct KB search endpoint"
```

---

## Final Checklist

After all tasks complete:

- [ ] **Verify module loads**: Visit http://192.168.1.200:3000/tools/archie-chat
- [ ] **Verify overlay**: Visit any page as admin, check floating bubble
- [ ] **Test API with curl**:
  ```bash
  # Generate API key via UI, then:
  curl -X POST http://192.168.1.200:3000/tools/archie-chat/api/v1/chat/message \
    -H "Authorization: Bearer archie_xxxx" \
    -H "Content-Type: application/json" \
    -d '{"message": "Hello ARCHIE", "include_thinking": true}'
  ```
- [ ] **Update Dev HQ**: `mcp complete_task` for task #1273, `mcp log_decision` for architecture choice
- [ ] **Deploy**: `docker compose restart archie_platform`
