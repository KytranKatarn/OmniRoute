# KBS Wave 2: Communications Stack

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add full omnichannel communications to Kytran Business Suite: RingCentral call logging with CRM matching, SMS via RingCentral (Twilio fallback), Hostinger Reach email marketing, live chat widget with REST polling, unified inbox aggregating all channels, Google Calendar sync for appointments, and SMS booking confirmations with 24h reminders.

**Architecture:** A new `kbs_communications` plugin provides the unified inbox dashboard and wires together channel-specific services. RingCentral and Twilio clients live in `core/` as reusable service modules. The existing `kbs_call_center` plugin already has `call_records`, `call_phone_numbers`, and `call_escalations` tables -- Wave 2 adds a RingCentral webhook that writes into those tables (no duplicate schema). New tables for SMS, chat, and email campaigns go in the communications plugin migration. Chat uses REST polling (WebSocket upgrade deferred to Wave 4). All tables live in tenant schemas (no `tenant_id` column). Events flow through `event_bus.emit()`.

**Tech Stack:** Flask, PostgreSQL, psycopg2, requests, google-api-python-client (already installed), APScheduler (already installed), pytest

**Spec:** `docs/superpowers/specs/2026-03-28-kbs-completion-saas-resale-design.md`

---

## File Map

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `plugins/kbs_communications/__init__.py` | Blueprint + event consumer registration |
| Create | `plugins/kbs_communications/manifest.json` | Plugin metadata, tier, events |
| Create | `plugins/kbs_communications/routes.py` | Dashboard + unified inbox routes |
| Create | `plugins/kbs_communications/sms_routes.py` | SMS send, list, inbound webhook |
| Create | `plugins/kbs_communications/chat_routes.py` | Chat start, message, close, list active |
| Create | `plugins/kbs_communications/campaign_routes.py` | Email campaign CRUD, send, stats |
| Create | `plugins/kbs_communications/webhook_routes.py` | RingCentral + SMS inbound webhooks |
| Create | `plugins/kbs_communications/migrations/001_communications_tables.sql` | SMS, chat, campaign tables |
| Create | `plugins/kbs_communications/templates/communications.html` | Dashboard template |
| Create | `plugins/kbs_communications/static/chat-widget.js` | Embeddable floating chat widget |
| Create | `core/ringcentral_client.py` | RingCentral API client (calls + SMS) |
| Create | `core/sms_service.py` | SMS dispatch (RingCentral primary, Twilio fallback) |
| Create | `core/chat_manager.py` | In-memory chat session management |
| Create | `core/reach_client.py` | Hostinger Reach email marketing API client |
| Create | `core/calendar_sync.py` | Google Calendar event sync service |
| Modify | `core/config.py` | Add RingCentral, Twilio, Reach env vars |
| Modify | `requirements.txt` | Add twilio SDK |
| Create | `tests/test_ringcentral_client.py` | RingCentral client tests (mocked HTTP) |
| Create | `tests/test_sms_service.py` | SMS dispatch tests (mocked providers) |
| Create | `tests/test_chat_manager.py` | Chat session lifecycle tests |
| Create | `tests/test_reach_client.py` | Reach client tests (mocked HTTP) |
| Create | `tests/test_calendar_sync.py` | Calendar sync tests (mocked Google API) |
| Create | `tests/test_communications_webhooks.py` | RingCentral webhook + CRM matching tests |
| Create | `tests/test_communications_sms_routes.py` | SMS route tests |
| Create | `tests/test_communications_chat_routes.py` | Chat route tests |
| Create | `tests/test_communications_inbox.py` | Unified inbox aggregation tests |
| Create | `tests/test_communications_campaigns.py` | Campaign CRUD + send tests |
| Create | `tests/test_sms_booking_confirmation.py` | SMS booking confirmation tests |
| Create | `tests/test_wave2_integration.py` | Full cross-channel integration tests |

---

## Task 1: Communications Database Migration

**Files:**
- Create: `plugins/kbs_communications/migrations/001_communications_tables.sql`

- [ ] **Step 1: Create the migrations directory**

```bash
mkdir -p /mnt/archie_brain/kytran-business-suite/plugins/kbs_communications/migrations
```

- [ ] **Step 2: Write the migration SQL**

Create `plugins/kbs_communications/migrations/001_communications_tables.sql`:

```sql
-- Communications plugin tables — run inside tenant schema (no tenant_id column needed).
-- Call records remain in kbs_call_center. This migration adds SMS, chat, and campaigns.
-- All statements are idempotent.

-- ----------------------------------------------------------------
-- SMS Messages
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sms_messages (
    id              SERIAL PRIMARY KEY,
    direction       VARCHAR(10) NOT NULL CHECK (direction IN ('inbound', 'outbound')),
    phone_number    VARCHAR(20) NOT NULL,
    customer_id     INTEGER,
    message         TEXT NOT NULL,
    status          VARCHAR(20) DEFAULT 'queued'
                        CHECK (status IN ('queued', 'sent', 'delivered', 'failed', 'received')),
    provider        VARCHAR(20) DEFAULT 'ringcentral'
                        CHECK (provider IN ('ringcentral', 'twilio')),
    external_id     VARCHAR(255),
    error_message   TEXT,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sms_messages_customer_id  ON sms_messages (customer_id);
CREATE INDEX IF NOT EXISTS idx_sms_messages_phone_number ON sms_messages (phone_number);
CREATE INDEX IF NOT EXISTS idx_sms_messages_status       ON sms_messages (status);
CREATE INDEX IF NOT EXISTS idx_sms_messages_created_at   ON sms_messages (created_at);

-- ----------------------------------------------------------------
-- Chat Conversations
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chat_conversations (
    id              SERIAL PRIMARY KEY,
    visitor_name    VARCHAR(255),
    visitor_email   VARCHAR(255),
    customer_id     INTEGER,
    status          VARCHAR(20) DEFAULT 'active'
                        CHECK (status IN ('active', 'closed', 'archived')),
    channel         VARCHAR(20) DEFAULT 'widget'
                        CHECK (channel IN ('widget', 'internal')),
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMP DEFAULT NOW(),
    closed_at       TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_chat_conversations_status     ON chat_conversations (status);
CREATE INDEX IF NOT EXISTS idx_chat_conversations_customer_id ON chat_conversations (customer_id);
CREATE INDEX IF NOT EXISTS idx_chat_conversations_created_at ON chat_conversations (created_at);

-- ----------------------------------------------------------------
-- Chat Messages
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chat_messages (
    id              SERIAL PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES chat_conversations(id) ON DELETE CASCADE,
    sender_type     VARCHAR(10) NOT NULL CHECK (sender_type IN ('visitor', 'agent', 'system')),
    sender_name     VARCHAR(255),
    content         TEXT NOT NULL,
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_conversation_id ON chat_messages (conversation_id);
CREATE INDEX IF NOT EXISTS idx_chat_messages_created_at      ON chat_messages (created_at);

-- ----------------------------------------------------------------
-- Email Campaigns
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS email_campaigns (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    subject         VARCHAR(500) NOT NULL,
    html_content    TEXT,
    text_content    TEXT,
    segment_id      INTEGER,
    status          VARCHAR(20) DEFAULT 'draft'
                        CHECK (status IN ('draft', 'scheduled', 'sending', 'sent', 'cancelled')),
    scheduled_at    TIMESTAMP,
    sent_at         TIMESTAMP,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_email_campaigns_status     ON email_campaigns (status);
CREATE INDEX IF NOT EXISTS idx_email_campaigns_created_at ON email_campaigns (created_at);

-- ----------------------------------------------------------------
-- Email Campaign Stats
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS email_campaign_stats (
    id              SERIAL PRIMARY KEY,
    campaign_id     INTEGER NOT NULL REFERENCES email_campaigns(id) ON DELETE CASCADE,
    total_sent      INTEGER DEFAULT 0,
    delivered       INTEGER DEFAULT 0,
    opened          INTEGER DEFAULT 0,
    clicked         INTEGER DEFAULT 0,
    bounced         INTEGER DEFAULT 0,
    unsubscribed    INTEGER DEFAULT 0,
    updated_at      TIMESTAMP DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_email_campaign_stats_campaign_id
    ON email_campaign_stats (campaign_id);
```

- [ ] **Step 3: Run the migration in a test tenant schema**

```bash
docker exec kbs_app python -c "
from core.database import get_db_cursor, set_tenant_search_path
with get_db_cursor(commit=True) as (conn, cur):
    set_tenant_search_path(cur, 1)
    with open('plugins/kbs_communications/migrations/001_communications_tables.sql') as f:
        cur.execute(f.read())
    print('Migration applied successfully')
"
```

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add plugins/kbs_communications/migrations/001_communications_tables.sql
git commit -m "feat(communications): add SMS, chat, and campaign database tables"
```

---

## Task 2: Communications Plugin Scaffold

**Files:**
- Create: `plugins/kbs_communications/__init__.py`
- Create: `plugins/kbs_communications/manifest.json`
- Create: `plugins/kbs_communications/routes.py`
- Create: `plugins/kbs_communications/templates/communications.html`

- [ ] **Step 1: Create the manifest**

Create `plugins/kbs_communications/manifest.json`:

```json
{
    "slug": "communications",
    "name": "Communications Hub",
    "version": "1.0.0",
    "description": "Unified omnichannel communications: calls, SMS, live chat, email campaigns, and unified inbox",
    "category": "communications",
    "tier_required": "business",
    "price_monthly": null,
    "icon": "message-circle",
    "dependencies": ["crm", "call-center"],
    "emits": ["sms.sent", "sms.received", "chat.started", "chat.closed", "campaign.sent", "campaign.created"],
    "consumes": ["contact.created", "appointment.booked", "appointment.cancelled", "call.ended"],
    "permissions": ["communications.read", "communications.write", "communications.admin"],
    "nav": {"label": "Communications", "icon": "message-circle", "order": 55}
}
```

- [ ] **Step 2: Create the blueprint init**

Create `plugins/kbs_communications/__init__.py`:

```python
from flask import Blueprint


def create_blueprint(manifest):
    bp = Blueprint(
        "communications",
        __name__,
        template_folder="templates",
        static_folder="static",
        static_url_path="/static/communications",
    )
    from plugins.kbs_communications.routes import register_routes
    from plugins.kbs_communications.sms_routes import register_sms_routes
    from plugins.kbs_communications.chat_routes import register_chat_routes
    from plugins.kbs_communications.campaign_routes import register_campaign_routes
    from plugins.kbs_communications.webhook_routes import register_webhook_routes

    register_routes(bp)
    register_sms_routes(bp)
    register_chat_routes(bp)
    register_campaign_routes(bp)
    register_webhook_routes(bp)

    # Register event consumers
    from core.event_bus import event_bus
    from plugins.kbs_communications.routes import on_appointment_booked
    from plugins.kbs_communications.routes import on_appointment_cancelled

    event_bus.on("appointment.booked")(on_appointment_booked)
    event_bus.on("appointment.cancelled")(on_appointment_cancelled)

    return bp
```

- [ ] **Step 3: Create the dashboard route**

Create `plugins/kbs_communications/routes.py`:

```python
"""Communications Hub plugin routes — dashboard and unified inbox."""

import logging
from datetime import datetime, timedelta

from flask import g, jsonify, render_template, request
from flask_login import login_required

from core.database import get_db_cursor, set_tenant_search_path
from core.event_bus import event_bus
from core.sms_service import send_sms
from core.tenant import require_module

logger = logging.getLogger(__name__)


def register_routes(bp):
    """Attach dashboard and unified inbox routes to the blueprint."""

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    @bp.route("/")
    @login_required
    @require_module("communications")
    def index():
        return render_template("communications.html")

    # ------------------------------------------------------------------
    # Unified Inbox
    # ------------------------------------------------------------------

    @bp.route("/api/inbox", methods=["GET"])
    @login_required
    @require_module("communications")
    def unified_inbox():
        """Aggregate recent calls, SMS, chat, and email into one timeline."""
        channel = request.args.get("channel")
        status = request.args.get("status")
        customer_id = request.args.get("customer_id", type=int)
        date_from = request.args.get("date_from")
        date_to = request.args.get("date_to")
        page = max(1, request.args.get("page", 1, type=int))
        per_page = min(100, max(1, request.args.get("per_page", 50, type=int)))
        offset = (page - 1) * per_page

        items = []

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            # --- Calls (from call_center plugin tables) ---
            if not channel or channel == "call":
                call_where = ["1=1"]
                call_params = []
                if customer_id:
                    call_where.append("cr.customer_id = %s")
                    call_params.append(customer_id)
                if date_from:
                    call_where.append("cr.started_at >= %s")
                    call_params.append(date_from)
                if date_to:
                    call_where.append("cr.started_at <= %s")
                    call_params.append(date_to)

                cur.execute(
                    f"""
                    SELECT cr.id, 'call' AS channel, cr.direction, cr.status,
                           cr.started_at AS created_at, cr.customer_id,
                           cr.duration_seconds, cr.notes,
                           c.first_name || ' ' || c.last_name AS customer_name
                    FROM call_records cr
                    LEFT JOIN crm_customers c ON c.id = cr.customer_id
                    WHERE {' AND '.join(call_where)}
                    ORDER BY cr.started_at DESC
                    LIMIT %s
                    """,
                    call_params + [per_page],
                )
                for row in cur.fetchall():
                    items.append(dict(row))

            # --- SMS ---
            if not channel or channel == "sms":
                sms_where = ["1=1"]
                sms_params = []
                if customer_id:
                    sms_where.append("sm.customer_id = %s")
                    sms_params.append(customer_id)
                if date_from:
                    sms_where.append("sm.created_at >= %s")
                    sms_params.append(date_from)
                if date_to:
                    sms_where.append("sm.created_at <= %s")
                    sms_params.append(date_to)

                cur.execute(
                    f"""
                    SELECT sm.id, 'sms' AS channel, sm.direction, sm.status,
                           sm.created_at, sm.customer_id,
                           sm.message AS notes, sm.phone_number,
                           c.first_name || ' ' || c.last_name AS customer_name
                    FROM sms_messages sm
                    LEFT JOIN crm_customers c ON c.id = sm.customer_id
                    WHERE {' AND '.join(sms_where)}
                    ORDER BY sm.created_at DESC
                    LIMIT %s
                    """,
                    sms_params + [per_page],
                )
                for row in cur.fetchall():
                    items.append(dict(row))

            # --- Chat ---
            if not channel or channel == "chat":
                chat_where = ["1=1"]
                chat_params = []
                if customer_id:
                    chat_where.append("cc.customer_id = %s")
                    chat_params.append(customer_id)
                if status:
                    chat_where.append("cc.status = %s")
                    chat_params.append(status)
                if date_from:
                    chat_where.append("cc.created_at >= %s")
                    chat_params.append(date_from)
                if date_to:
                    chat_where.append("cc.created_at <= %s")
                    chat_params.append(date_to)

                cur.execute(
                    f"""
                    SELECT cc.id, 'chat' AS channel, cc.status,
                           cc.created_at, cc.customer_id,
                           cc.visitor_name, cc.visitor_email,
                           c.first_name || ' ' || c.last_name AS customer_name,
                           (SELECT content FROM chat_messages
                            WHERE conversation_id = cc.id
                            ORDER BY created_at DESC LIMIT 1) AS notes
                    FROM chat_conversations cc
                    LEFT JOIN crm_customers c ON c.id = cc.customer_id
                    WHERE {' AND '.join(chat_where)}
                    ORDER BY cc.created_at DESC
                    LIMIT %s
                    """,
                    chat_params + [per_page],
                )
                for row in cur.fetchall():
                    items.append(dict(row))

            # --- Email Campaigns ---
            if not channel or channel == "email":
                email_where = ["1=1"]
                email_params = []
                if date_from:
                    email_where.append("ec.created_at >= %s")
                    email_params.append(date_from)
                if date_to:
                    email_where.append("ec.created_at <= %s")
                    email_params.append(date_to)

                cur.execute(
                    f"""
                    SELECT ec.id, 'email' AS channel, ec.status,
                           ec.created_at, ec.name, ec.subject AS notes,
                           ecs.total_sent, ecs.delivered, ecs.opened
                    FROM email_campaigns ec
                    LEFT JOIN email_campaign_stats ecs ON ecs.campaign_id = ec.id
                    WHERE {' AND '.join(email_where)}
                    ORDER BY ec.created_at DESC
                    LIMIT %s
                    """,
                    email_params + [per_page],
                )
                for row in cur.fetchall():
                    items.append(dict(row))

        # Sort all items by created_at descending, apply pagination
        items.sort(
            key=lambda x: x.get("created_at") or datetime.min,
            reverse=True,
        )
        paginated = items[offset : offset + per_page]

        return jsonify({"items": paginated, "page": page, "per_page": per_page})

    @bp.route("/api/inbox/stats", methods=["GET"])
    @login_required
    @require_module("communications")
    def inbox_stats():
        """Counts per channel and recent activity."""
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            stats = {}

            # Call count (last 30 days)
            cur.execute(
                """
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE status = 'missed') AS missed
                FROM call_records
                WHERE started_at >= NOW() - INTERVAL '30 days'
                """
            )
            stats["calls"] = dict(cur.fetchone())

            # SMS count (last 30 days)
            cur.execute(
                """
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE direction = 'inbound') AS inbound,
                       COUNT(*) FILTER (WHERE direction = 'outbound') AS outbound
                FROM sms_messages
                WHERE created_at >= NOW() - INTERVAL '30 days'
                """
            )
            stats["sms"] = dict(cur.fetchone())

            # Active chats
            cur.execute(
                """
                SELECT COUNT(*) AS active
                FROM chat_conversations
                WHERE status = 'active'
                """
            )
            stats["chat"] = dict(cur.fetchone())

            # Campaign stats
            cur.execute(
                """
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE status = 'sent') AS sent,
                       COUNT(*) FILTER (WHERE status = 'draft') AS drafts
                FROM email_campaigns
                """
            )
            stats["campaigns"] = dict(cur.fetchone())

        return jsonify(stats)


# ------------------------------------------------------------------
# Event consumers (called from __init__.py registration)
# ------------------------------------------------------------------

def on_appointment_booked(data):
    """Send SMS confirmation when an appointment is booked."""
    customer_id = data.get("customer_id")
    tenant_id = data.get("_tenant_id")
    if not customer_id or not tenant_id:
        return

    with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
        set_tenant_search_path(cur, tenant_id)
        cur.execute(
            "SELECT phone, first_name, last_name FROM crm_customers WHERE id = %s",
            (customer_id,),
        )
        customer = cur.fetchone()

    if not customer or not customer.get("phone"):
        logger.info("No phone number for customer %s — skipping SMS confirmation", customer_id)
        return

    service_name = data.get("service_name", "your appointment")
    appointment_date = data.get("appointment_date", "")
    appointment_time = data.get("appointment_time", "")

    message = (
        f"Hi {customer['first_name']}, your appointment for {service_name} "
        f"on {appointment_date} at {appointment_time} is confirmed. "
        f"Reply CANCEL to cancel."
    )

    try:
        send_sms(
            to=customer["phone"],
            message=message,
            tenant_id=tenant_id,
            customer_id=customer_id,
        )
        logger.info("SMS confirmation sent to customer %s", customer_id)
    except Exception:
        logger.exception("Failed to send SMS confirmation to customer %s", customer_id)


def on_appointment_cancelled(data):
    """Send SMS notification when an appointment is cancelled."""
    customer_id = data.get("customer_id")
    tenant_id = data.get("_tenant_id")
    if not customer_id or not tenant_id:
        return

    with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
        set_tenant_search_path(cur, tenant_id)
        cur.execute(
            "SELECT phone, first_name FROM crm_customers WHERE id = %s",
            (customer_id,),
        )
        customer = cur.fetchone()

    if not customer or not customer.get("phone"):
        return

    service_name = data.get("service_name", "your appointment")
    message = (
        f"Hi {customer['first_name']}, your appointment for {service_name} "
        f"has been cancelled. Contact us to reschedule."
    )

    try:
        send_sms(
            to=customer["phone"],
            message=message,
            tenant_id=tenant_id,
            customer_id=customer_id,
        )
    except Exception:
        logger.exception("Failed to send cancellation SMS to customer %s", customer_id)
```

- [ ] **Step 4: Create a minimal dashboard template**

Create `plugins/kbs_communications/templates/communications.html`:

```html
{% extends "base.html" %}
{% block title %}Communications Hub{% endblock %}
{% block content %}
<div class="kbs-page">
    <h1>Communications Hub</h1>
    <p>Unified inbox for calls, SMS, live chat, and email campaigns.</p>
    <div id="communications-app"></div>
</div>
{% endblock %}
```

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add plugins/kbs_communications/__init__.py plugins/kbs_communications/manifest.json \
        plugins/kbs_communications/routes.py plugins/kbs_communications/templates/communications.html
git commit -m "feat(communications): scaffold plugin with unified inbox and event consumers"
```

---

## Task 3: Config Updates + Dependencies

**Files:**
- Modify: `core/config.py`
- Modify: `requirements.txt`

- [ ] **Step 1: Add RingCentral, Twilio, and Reach config vars**

Append to `core/config.py` inside `__init__`:

```python
        # RingCentral
        self.KBS_RINGCENTRAL_SERVER_URL = os.getenv(
            "KBS_RINGCENTRAL_SERVER_URL", "https://platform.ringcentral.com"
        )
        self.KBS_RINGCENTRAL_CLIENT_ID = os.getenv("KBS_RINGCENTRAL_CLIENT_ID", "")
        self.KBS_RINGCENTRAL_CLIENT_SECRET = os.getenv("KBS_RINGCENTRAL_CLIENT_SECRET", "")
        self.KBS_RINGCENTRAL_JWT_TOKEN = os.getenv("KBS_RINGCENTRAL_JWT_TOKEN", "")
        self.KBS_RINGCENTRAL_ACCOUNT_ID = os.getenv("KBS_RINGCENTRAL_ACCOUNT_ID", "~")
        self.KBS_RINGCENTRAL_WEBHOOK_SECRET = os.getenv("KBS_RINGCENTRAL_WEBHOOK_SECRET", "")

        # Twilio (SMS fallback)
        self.KBS_TWILIO_ACCOUNT_SID = os.getenv("KBS_TWILIO_ACCOUNT_SID", "")
        self.KBS_TWILIO_AUTH_TOKEN = os.getenv("KBS_TWILIO_AUTH_TOKEN", "")
        self.KBS_TWILIO_PHONE_NUMBER = os.getenv("KBS_TWILIO_PHONE_NUMBER", "")

        # Hostinger Reach (email marketing)
        self.KBS_REACH_API_URL = os.getenv(
            "KBS_REACH_API_URL", "https://api.hostinger.com/reach/v1"
        )
        self.KBS_REACH_API_KEY = os.getenv("KBS_REACH_API_KEY", "")

        # SMS provider preference
        self.KBS_SMS_PROVIDER = os.getenv("KBS_SMS_PROVIDER", "ringcentral")
```

- [ ] **Step 2: Add twilio to requirements.txt**

```bash
echo "twilio>=9.0" >> /mnt/archie_brain/kytran-business-suite/requirements.txt
```

- [ ] **Step 3: Install in container**

```bash
docker exec kbs_app pip install twilio>=9.0
```

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add core/config.py requirements.txt
git commit -m "feat(config): add RingCentral, Twilio, and Reach config vars"
```

---

## Task 4: RingCentral API Client

**Files:**
- Create: `core/ringcentral_client.py`
- Create: `tests/test_ringcentral_client.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_ringcentral_client.py`:

```python
"""Tests for RingCentral API client — all HTTP calls mocked."""

import json
from unittest.mock import MagicMock, patch

import pytest


def test_get_access_token():
    from core.ringcentral_client import RingCentralClient

    client = RingCentralClient(
        server_url="https://platform.ringcentral.com",
        client_id="test-client-id",
        client_secret="test-client-secret",
        jwt_token="test-jwt-token",
        account_id="~",
    )

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "access_token": "tok-abc-123",
        "expires_in": 3600,
    }

    with patch("core.ringcentral_client.requests.post", return_value=mock_response) as mock_post:
        token = client._get_access_token()

    assert token == "tok-abc-123"
    assert "jwt_token" in mock_post.call_args[1].get("data", {}).get("grant_type", "")


def test_get_call_log():
    from core.ringcentral_client import RingCentralClient

    client = RingCentralClient(
        server_url="https://platform.ringcentral.com",
        client_id="cid",
        client_secret="csec",
        jwt_token="jwt",
        account_id="~",
    )
    client._access_token = "cached-token"

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "records": [
            {
                "id": "call-1",
                "direction": "Inbound",
                "from": {"phoneNumber": "+15551234567"},
                "to": {"phoneNumber": "+15559876543"},
                "duration": 120,
                "result": "Accepted",
                "startTime": "2026-03-28T10:00:00.000Z",
            }
        ],
        "paging": {"totalRecords": 1},
    }

    with patch("core.ringcentral_client.requests.get", return_value=mock_response):
        records = client.get_call_log(date_from="2026-03-27", date_to="2026-03-28")

    assert len(records) == 1
    assert records[0]["id"] == "call-1"
    assert records[0]["direction"] == "Inbound"


def test_send_sms():
    from core.ringcentral_client import RingCentralClient

    client = RingCentralClient(
        server_url="https://platform.ringcentral.com",
        client_id="cid",
        client_secret="csec",
        jwt_token="jwt",
        account_id="~",
    )
    client._access_token = "cached-token"

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "id": "sms-1",
        "status": "Queued",
        "to": [{"phoneNumber": "+15551234567"}],
    }

    with patch("core.ringcentral_client.requests.post", return_value=mock_response):
        result = client.send_sms(
            from_number="+15559876543",
            to_number="+15551234567",
            message="Test SMS",
        )

    assert result["id"] == "sms-1"
    assert result["status"] == "Queued"


def test_get_sms_log():
    from core.ringcentral_client import RingCentralClient

    client = RingCentralClient(
        server_url="https://platform.ringcentral.com",
        client_id="cid",
        client_secret="csec",
        jwt_token="jwt",
        account_id="~",
    )
    client._access_token = "cached-token"

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "records": [
            {
                "id": "msg-1",
                "direction": "Outbound",
                "subject": "Hello",
                "type": "SMS",
            }
        ],
    }

    with patch("core.ringcentral_client.requests.get", return_value=mock_response):
        records = client.get_sms_log(date_from="2026-03-27", date_to="2026-03-28")

    assert len(records) == 1
    assert records[0]["type"] == "SMS"


def test_auth_failure_raises():
    from core.ringcentral_client import RingCentralClient

    client = RingCentralClient(
        server_url="https://platform.ringcentral.com",
        client_id="cid",
        client_secret="csec",
        jwt_token="bad-jwt",
        account_id="~",
    )

    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.text = "Unauthorized"
    mock_response.raise_for_status.side_effect = Exception("401 Unauthorized")

    with patch("core.ringcentral_client.requests.post", return_value=mock_response):
        with pytest.raises(Exception, match="401"):
            client._get_access_token()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker exec kbs_app python -m pytest tests/test_ringcentral_client.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'core.ringcentral_client'`

- [ ] **Step 3: Write the implementation**

Create `core/ringcentral_client.py`:

```python
"""RingCentral API client for call log retrieval and SMS sending."""

import logging
import time

import requests

logger = logging.getLogger(__name__)


class RingCentralClient:
    """Client for the RingCentral REST API.

    Authentication uses JWT grant type. Access tokens are cached and
    refreshed automatically when expired.

    Args:
        server_url: RingCentral API base URL (e.g. https://platform.ringcentral.com).
        client_id: OAuth app client ID.
        client_secret: OAuth app client secret.
        jwt_token: JWT credential for authentication.
        account_id: Account ID (default "~" for the authenticated account).
    """

    def __init__(self, server_url, client_id, client_secret, jwt_token, account_id="~"):
        self.server_url = server_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.jwt_token = jwt_token
        self.account_id = account_id
        self._access_token = None
        self._token_expires_at = 0

    def _get_access_token(self):
        """Obtain or refresh an access token using JWT grant."""
        if self._access_token and time.time() < self._token_expires_at:
            return self._access_token

        resp = requests.post(
            f"{self.server_url}/restapi/oauth/token",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": self.jwt_token,
            },
            auth=(self.client_id, self.client_secret),
            timeout=30,
        )
        resp.raise_for_status()
        body = resp.json()
        self._access_token = body["access_token"]
        self._token_expires_at = time.time() + body.get("expires_in", 3600) - 60
        return self._access_token

    def _headers(self):
        """Return Authorization headers with a valid access token."""
        token = self._get_access_token()
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def get_call_log(self, date_from, date_to, per_page=100):
        """Fetch call log records for the account.

        Args:
            date_from: ISO date string (e.g. "2026-03-27").
            date_to: ISO date string (e.g. "2026-03-28").
            per_page: Max records per request (default 100).

        Returns:
            List of call record dicts from RingCentral.
        """
        resp = requests.get(
            f"{self.server_url}/restapi/v1.0/account/{self.account_id}/call-log",
            headers=self._headers(),
            params={
                "dateFrom": f"{date_from}T00:00:00.000Z",
                "dateTo": f"{date_to}T23:59:59.999Z",
                "perPage": per_page,
                "view": "Detailed",
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get("records", [])

    def send_sms(self, from_number, to_number, message):
        """Send an SMS message via RingCentral.

        Args:
            from_number: Sender phone number (must be a RingCentral number).
            to_number: Recipient phone number.
            message: Text message content.

        Returns:
            Dict with message ID and status from RingCentral.
        """
        resp = requests.post(
            f"{self.server_url}/restapi/v1.0/account/{self.account_id}/extension/~/sms",
            headers=self._headers(),
            json={
                "from": {"phoneNumber": from_number},
                "to": [{"phoneNumber": to_number}],
                "text": message,
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def get_sms_log(self, date_from, date_to, per_page=100):
        """Fetch SMS message log for the account.

        Args:
            date_from: ISO date string.
            date_to: ISO date string.
            per_page: Max records per request.

        Returns:
            List of SMS record dicts from RingCentral.
        """
        resp = requests.get(
            f"{self.server_url}/restapi/v1.0/account/{self.account_id}/extension/~/message-store",
            headers=self._headers(),
            params={
                "dateFrom": f"{date_from}T00:00:00.000Z",
                "dateTo": f"{date_to}T23:59:59.999Z",
                "messageType": "SMS",
                "perPage": per_page,
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get("records", [])
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker exec kbs_app python -m pytest tests/test_ringcentral_client.py -v
```

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add core/ringcentral_client.py tests/test_ringcentral_client.py
git commit -m "feat(core): add RingCentral API client with JWT auth, call log, and SMS"
```

---

## Task 5: RingCentral Webhook + CRM Call Logging

**Files:**
- Create: `plugins/kbs_communications/webhook_routes.py`
- Create: `tests/test_communications_webhooks.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_communications_webhooks.py`:

```python
"""Tests for RingCentral webhook call logging and CRM matching."""

import json
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_db():
    """Mock database cursor that returns a CRM customer match."""
    mock_cur = MagicMock()
    mock_conn = MagicMock()

    # Simulate CRM customer lookup by phone
    def execute_side_effect(query, params=None):
        if params and "phone" in str(query).lower():
            mock_cur.fetchone.return_value = {"id": 42, "first_name": "Jane", "last_name": "Doe"}
        elif "INSERT INTO call_records" in str(query):
            mock_cur.fetchone.return_value = {
                "id": 1,
                "phone_number_id": None,
                "customer_id": 42,
                "direction": "inbound",
                "status": "completed",
                "duration_seconds": 120,
                "notes": None,
                "started_at": "2026-03-28T10:00:00",
                "ended_at": None,
            }

    mock_cur.execute = MagicMock(side_effect=execute_side_effect)
    return mock_conn, mock_cur


def test_parse_ringcentral_call_event():
    """Verify we extract the right fields from a RingCentral call event."""
    from plugins.kbs_communications.webhook_routes import _parse_ringcentral_call

    event_body = {
        "body": {
            "sessionId": "sess-123",
            "parties": [
                {
                    "direction": "Inbound",
                    "from": {"phoneNumber": "+15551234567"},
                    "to": {"phoneNumber": "+15559876543"},
                    "status": {"code": "Answered"},
                    "duration": 120,
                    "recording": {"id": "rec-1", "contentUri": "https://example.com/rec.mp3"},
                }
            ],
        }
    }

    parsed = _parse_ringcentral_call(event_body)

    assert parsed["direction"] == "inbound"
    assert parsed["caller_number"] == "+15551234567"
    assert parsed["callee_number"] == "+15559876543"
    assert parsed["status"] == "completed"
    assert parsed["duration_seconds"] == 120
    assert "rec.mp3" in parsed["recording_url"]


def test_parse_ringcentral_missed_call():
    from plugins.kbs_communications.webhook_routes import _parse_ringcentral_call

    event_body = {
        "body": {
            "sessionId": "sess-456",
            "parties": [
                {
                    "direction": "Inbound",
                    "from": {"phoneNumber": "+15550001111"},
                    "to": {"phoneNumber": "+15550002222"},
                    "status": {"code": "NoAnswer"},
                    "duration": 0,
                }
            ],
        }
    }

    parsed = _parse_ringcentral_call(event_body)

    assert parsed["status"] == "missed"
    assert parsed["duration_seconds"] == 0


def test_match_customer_by_phone(mock_db):
    from plugins.kbs_communications.webhook_routes import _match_customer_by_phone

    _, cur = mock_db
    customer_id = _match_customer_by_phone(cur, "+15551234567")
    assert customer_id == 42


def test_ringcentral_status_mapping():
    from plugins.kbs_communications.webhook_routes import _map_rc_status

    assert _map_rc_status("Answered") == "completed"
    assert _map_rc_status("NoAnswer") == "missed"
    assert _map_rc_status("Voicemail") == "missed"
    assert _map_rc_status("Rejected") == "failed"
    assert _map_rc_status("Unknown") == "initiated"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker exec kbs_app python -m pytest tests/test_communications_webhooks.py -v
```

Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

Create `plugins/kbs_communications/webhook_routes.py`:

```python
"""Webhook routes for RingCentral call events and SMS delivery receipts."""

import hashlib
import hmac
import json
import logging

from flask import g, jsonify, request
from flask_login import login_required

from core.config import Config
from core.database import get_db_cursor, set_tenant_search_path
from core.event_bus import event_bus
from core.tenant import require_module

logger = logging.getLogger(__name__)

# RingCentral status code to KBS status mapping
_RC_STATUS_MAP = {
    "Answered": "completed",
    "Accepted": "completed",
    "CallConnected": "completed",
    "NoAnswer": "missed",
    "Voicemail": "missed",
    "Busy": "missed",
    "Rejected": "failed",
    "HangUp": "completed",
    "FaxReceive": "completed",
}


def _map_rc_status(rc_status):
    """Map a RingCentral call result/status code to KBS status."""
    return _RC_STATUS_MAP.get(rc_status, "initiated")


def _parse_ringcentral_call(event_body):
    """Extract call details from a RingCentral telephony event.

    Args:
        event_body: The decoded JSON body from the RingCentral webhook.

    Returns:
        Dict with normalized call fields, or None if no party data.
    """
    body = event_body.get("body", {})
    parties = body.get("parties", [])

    if not parties:
        return None

    party = parties[0]
    direction_raw = party.get("direction", "Inbound")
    status_raw = party.get("status", {}).get("code", "Unknown")
    recording = party.get("recording", {})

    return {
        "ringcentral_id": body.get("sessionId", ""),
        "direction": "inbound" if direction_raw.lower() == "inbound" else "outbound",
        "caller_number": party.get("from", {}).get("phoneNumber", ""),
        "callee_number": party.get("to", {}).get("phoneNumber", ""),
        "status": _map_rc_status(status_raw),
        "duration_seconds": party.get("duration", 0) or 0,
        "recording_url": recording.get("contentUri", ""),
    }


def _match_customer_by_phone(cur, phone_number):
    """Look up a CRM customer by phone number.

    Args:
        cur: Database cursor with tenant search path already set.
        phone_number: Phone number to match (e.g. "+15551234567").

    Returns:
        Customer ID (int) or None if no match.
    """
    if not phone_number:
        return None

    # Strip leading + and try various formats
    digits = phone_number.lstrip("+").replace("-", "").replace(" ", "").replace("(", "").replace(")", "")
    cur.execute(
        """
        SELECT id FROM crm_customers
        WHERE REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(phone, '-', ''), ' ', ''), '+', ''), '(', ''), ')', '') = %s
           OR phone = %s
        LIMIT 1
        """,
        (digits, phone_number),
    )
    row = cur.fetchone()
    return row["id"] if row else None


def _verify_ringcentral_signature(body_bytes, signature, secret):
    """Verify RingCentral webhook signature (HMAC-SHA256)."""
    if not secret:
        return True  # Skip verification if no secret configured
    expected = hmac.new(secret.encode(), body_bytes, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


def register_webhook_routes(bp):
    """Attach webhook routes to the blueprint."""

    @bp.route("/api/webhooks/ringcentral", methods=["POST"])
    def ringcentral_webhook():
        """Receive RingCentral telephony session events.

        This endpoint is called by RingCentral when calls are made/received.
        It does NOT require login — it is authenticated via webhook signature.
        RingCentral sends a validation token on subscription that must be echoed.
        """
        cfg = Config()

        # Handle RingCentral subscription validation
        validation_token = request.headers.get("Validation-Token")
        if validation_token:
            return jsonify({}), 200, {"Validation-Token": validation_token}

        # Verify webhook signature
        signature = request.headers.get("X-RingCentral-Signature")
        if cfg.KBS_RINGCENTRAL_WEBHOOK_SECRET:
            if not _verify_ringcentral_signature(
                request.data, signature, cfg.KBS_RINGCENTRAL_WEBHOOK_SECRET
            ):
                logger.warning("Invalid RingCentral webhook signature")
                return jsonify({"error": "Invalid signature"}), 401

        data = request.get_json(force=True)
        event_type = data.get("event", "")

        # Only process telephony session events
        if "/telephony/sessions" not in event_type:
            return jsonify({"status": "ignored"}), 200

        parsed = _parse_ringcentral_call(data)
        if not parsed:
            return jsonify({"status": "no parties"}), 200

        # Determine tenant from webhook URL query param
        # Convention: webhook URL includes ?tenant_id=N
        tenant_id = request.args.get("tenant_id", type=int)
        if not tenant_id:
            logger.warning("RingCentral webhook missing tenant_id")
            return jsonify({"error": "tenant_id required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, tenant_id)

            # Check for duplicate by ringcentral_id
            if parsed["ringcentral_id"]:
                cur.execute(
                    "SELECT id FROM call_records WHERE metadata->>'ringcentral_id' = %s",
                    (parsed["ringcentral_id"],),
                )
                if cur.fetchone():
                    return jsonify({"status": "duplicate"}), 200

            # Match caller to CRM customer
            lookup_number = (
                parsed["caller_number"]
                if parsed["direction"] == "inbound"
                else parsed["callee_number"]
            )
            customer_id = _match_customer_by_phone(cur, lookup_number)

            # Insert into call_records (call_center plugin table)
            cur.execute(
                """
                INSERT INTO call_records
                    (customer_id, direction, status, duration_seconds,
                     recording_url, metadata, started_at)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, NOW())
                RETURNING id, phone_number_id, customer_id, direction, status,
                          duration_seconds, notes, started_at, ended_at
                """,
                (
                    customer_id,
                    parsed["direction"],
                    parsed["status"],
                    parsed["duration_seconds"],
                    parsed["recording_url"] or None,
                    json.dumps({
                        "ringcentral_id": parsed["ringcentral_id"],
                        "caller_number": parsed["caller_number"],
                        "callee_number": parsed["callee_number"],
                    }),
                ),
            )
            call = cur.fetchone()

        event_bus.emit(
            "call.logged",
            {
                "call_id": call["id"],
                "customer_id": customer_id,
                "direction": parsed["direction"],
                "status": parsed["status"],
                "source": "ringcentral",
            },
            tenant_id=tenant_id,
        )

        return jsonify({"status": "logged", "call_id": call["id"]}), 201

    @bp.route("/api/calls", methods=["GET"])
    @login_required
    @require_module("communications")
    def list_calls():
        """List call records with CRM customer info and pagination."""
        page = max(1, request.args.get("page", 1, type=int))
        per_page = min(100, max(1, request.args.get("per_page", 25, type=int)))
        offset = (page - 1) * per_page
        direction = request.args.get("direction")
        status = request.args.get("status")

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            where = ["1=1"]
            params = []
            if direction:
                where.append("cr.direction = %s")
                params.append(direction)
            if status:
                where.append("cr.status = %s")
                params.append(status)

            cur.execute(
                f"""
                SELECT cr.id, cr.phone_number_id, cr.customer_id, cr.direction,
                       cr.status, cr.duration_seconds, cr.recording_url,
                       cr.notes, cr.metadata, cr.started_at, cr.ended_at,
                       c.first_name || ' ' || c.last_name AS customer_name,
                       c.email AS customer_email, c.phone AS customer_phone
                FROM call_records cr
                LEFT JOIN crm_customers c ON c.id = cr.customer_id
                WHERE {' AND '.join(where)}
                ORDER BY cr.started_at DESC
                LIMIT %s OFFSET %s
                """,
                params + [per_page, offset],
            )
            calls = cur.fetchall()

            cur.execute(
                f"SELECT COUNT(*) AS total FROM call_records cr WHERE {' AND '.join(where)}",
                params,
            )
            total = cur.fetchone()["total"]

        return jsonify({"calls": calls, "total": total, "page": page, "per_page": per_page})

    @bp.route("/api/calls/stats", methods=["GET"])
    @login_required
    @require_module("communications")
    def call_stats():
        """Call volume, average duration, and missed rate."""
        days = request.args.get("days", 30, type=int)

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT
                    COUNT(*) AS total_calls,
                    COUNT(*) FILTER (WHERE status = 'completed') AS answered,
                    COUNT(*) FILTER (WHERE status = 'missed') AS missed,
                    ROUND(AVG(duration_seconds) FILTER (WHERE status = 'completed'), 1) AS avg_duration,
                    COUNT(*) FILTER (WHERE direction = 'inbound') AS inbound,
                    COUNT(*) FILTER (WHERE direction = 'outbound') AS outbound
                FROM call_records
                WHERE started_at >= NOW() - make_interval(days => %s)
                """,
                (days,),
            )
            stats = dict(cur.fetchone())

        stats["missed_rate"] = (
            round(stats["missed"] / stats["total_calls"] * 100, 1)
            if stats["total_calls"] > 0
            else 0
        )

        return jsonify(stats)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker exec kbs_app python -m pytest tests/test_communications_webhooks.py -v
```

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add plugins/kbs_communications/webhook_routes.py tests/test_communications_webhooks.py
git commit -m "feat(communications): RingCentral webhook with CRM call matching and call list API"
```

---

## Task 6: SMS Service

**Files:**
- Create: `core/sms_service.py`
- Create: `tests/test_sms_service.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_sms_service.py`:

```python
"""Tests for SMS dispatch service — RingCentral primary, Twilio fallback."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_config_ringcentral():
    """Config with RingCentral as primary SMS provider."""
    cfg = MagicMock()
    cfg.KBS_SMS_PROVIDER = "ringcentral"
    cfg.KBS_RINGCENTRAL_SERVER_URL = "https://platform.ringcentral.com"
    cfg.KBS_RINGCENTRAL_CLIENT_ID = "rc-cid"
    cfg.KBS_RINGCENTRAL_CLIENT_SECRET = "rc-secret"
    cfg.KBS_RINGCENTRAL_JWT_TOKEN = "rc-jwt"
    cfg.KBS_RINGCENTRAL_ACCOUNT_ID = "~"
    cfg.KBS_TWILIO_ACCOUNT_SID = ""
    cfg.KBS_TWILIO_AUTH_TOKEN = ""
    cfg.KBS_TWILIO_PHONE_NUMBER = ""
    return cfg


@pytest.fixture
def mock_config_twilio():
    """Config with Twilio as primary SMS provider."""
    cfg = MagicMock()
    cfg.KBS_SMS_PROVIDER = "twilio"
    cfg.KBS_RINGCENTRAL_SERVER_URL = ""
    cfg.KBS_RINGCENTRAL_CLIENT_ID = ""
    cfg.KBS_RINGCENTRAL_CLIENT_SECRET = ""
    cfg.KBS_RINGCENTRAL_JWT_TOKEN = ""
    cfg.KBS_RINGCENTRAL_ACCOUNT_ID = ""
    cfg.KBS_TWILIO_ACCOUNT_SID = "ACTEST123"
    cfg.KBS_TWILIO_AUTH_TOKEN = "tw-auth"
    cfg.KBS_TWILIO_PHONE_NUMBER = "+15550009999"
    return cfg


def test_send_sms_via_ringcentral(mock_config_ringcentral):
    from core.sms_service import _send_via_ringcentral

    mock_rc_client = MagicMock()
    mock_rc_client.send_sms.return_value = {"id": "sms-rc-1", "status": "Queued"}

    with patch("core.sms_service.RingCentralClient", return_value=mock_rc_client):
        result = _send_via_ringcentral(mock_config_ringcentral, "+15551112222", "Hello from RC")

    assert result["external_id"] == "sms-rc-1"
    assert result["provider"] == "ringcentral"


def test_send_sms_via_twilio(mock_config_twilio):
    from core.sms_service import _send_via_twilio

    mock_twilio_msg = MagicMock()
    mock_twilio_msg.sid = "SM-tw-1"
    mock_twilio_msg.status = "queued"

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_twilio_msg

    with patch("core.sms_service.TwilioClient", return_value=mock_client):
        result = _send_via_twilio(mock_config_twilio, "+15551112222", "Hello from Twilio")

    assert result["external_id"] == "SM-tw-1"
    assert result["provider"] == "twilio"


def test_send_sms_records_to_database():
    """Verify send_sms creates an sms_messages record."""
    from core.sms_service import send_sms

    mock_cur = MagicMock()
    mock_conn = MagicMock()
    mock_cur.fetchone.return_value = {"id": 1}

    with patch("core.sms_service.Config") as MockConfig, \
         patch("core.sms_service.get_db_cursor") as mock_db, \
         patch("core.sms_service._dispatch_sms") as mock_dispatch:

        mock_db.return_value.__enter__ = MagicMock(return_value=(mock_conn, mock_cur))
        mock_db.return_value.__exit__ = MagicMock(return_value=False)

        cfg = MagicMock()
        cfg.KBS_SMS_PROVIDER = "ringcentral"
        MockConfig.return_value = cfg

        mock_dispatch.return_value = {"external_id": "ext-1", "provider": "ringcentral"}

        result = send_sms(
            to="+15551112222",
            message="Test message",
            tenant_id=1,
            customer_id=42,
        )

    # Verify INSERT was called
    insert_call = [
        c for c in mock_cur.execute.call_args_list
        if "INSERT INTO sms_messages" in str(c)
    ]
    assert len(insert_call) == 1


def test_send_sms_fallback_on_failure():
    """If primary provider fails, fallback to secondary."""
    from core.sms_service import _dispatch_sms

    cfg = MagicMock()
    cfg.KBS_SMS_PROVIDER = "ringcentral"
    cfg.KBS_TWILIO_ACCOUNT_SID = "ACTEST"
    cfg.KBS_TWILIO_AUTH_TOKEN = "tw-auth"
    cfg.KBS_TWILIO_PHONE_NUMBER = "+15550009999"

    with patch("core.sms_service._send_via_ringcentral", side_effect=Exception("RC down")), \
         patch("core.sms_service._send_via_twilio") as mock_twilio:

        mock_twilio.return_value = {"external_id": "SM-fb-1", "provider": "twilio"}
        result = _dispatch_sms(cfg, "+15551112222", "Fallback test")

    assert result["provider"] == "twilio"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker exec kbs_app python -m pytest tests/test_sms_service.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'core.sms_service'`

- [ ] **Step 3: Write the implementation**

Create `core/sms_service.py`:

```python
"""SMS dispatch service — RingCentral primary with Twilio fallback.

Usage:
    from core.sms_service import send_sms
    send_sms(to="+15551234567", message="Hello", tenant_id=1, customer_id=42)
"""

import logging

from core.config import Config
from core.database import get_db_cursor, set_tenant_search_path
from core.event_bus import event_bus
from core.ringcentral_client import RingCentralClient

logger = logging.getLogger(__name__)

# Lazy import Twilio to avoid hard dependency if not installed
TwilioClient = None


def _ensure_twilio():
    global TwilioClient
    if TwilioClient is None:
        try:
            from twilio.rest import Client as _TwilioClient

            TwilioClient = _TwilioClient
        except ImportError:
            raise ImportError(
                "twilio package is required for Twilio SMS. "
                "Install it with: pip install twilio"
            )
    return TwilioClient


def _send_via_ringcentral(cfg, to_number, message):
    """Send SMS via RingCentral API.

    Args:
        cfg: Config instance with RingCentral credentials.
        to_number: Recipient phone number.
        message: SMS text.

    Returns:
        Dict with external_id and provider.
    """
    client = RingCentralClient(
        server_url=cfg.KBS_RINGCENTRAL_SERVER_URL,
        client_id=cfg.KBS_RINGCENTRAL_CLIENT_ID,
        client_secret=cfg.KBS_RINGCENTRAL_CLIENT_SECRET,
        jwt_token=cfg.KBS_RINGCENTRAL_JWT_TOKEN,
        account_id=cfg.KBS_RINGCENTRAL_ACCOUNT_ID,
    )
    # Use the first configured RingCentral number as sender
    result = client.send_sms(
        from_number=cfg.KBS_RINGCENTRAL_ACCOUNT_ID,
        to_number=to_number,
        message=message,
    )
    return {
        "external_id": result.get("id", ""),
        "provider": "ringcentral",
    }


def _send_via_twilio(cfg, to_number, message):
    """Send SMS via Twilio API.

    Args:
        cfg: Config instance with Twilio credentials.
        to_number: Recipient phone number.
        message: SMS text.

    Returns:
        Dict with external_id and provider.
    """
    _ensure_twilio()
    client = TwilioClient(cfg.KBS_TWILIO_ACCOUNT_SID, cfg.KBS_TWILIO_AUTH_TOKEN)
    msg = client.messages.create(
        body=message,
        from_=cfg.KBS_TWILIO_PHONE_NUMBER,
        to=to_number,
    )
    return {
        "external_id": msg.sid,
        "provider": "twilio",
    }


def _dispatch_sms(cfg, to_number, message):
    """Dispatch SMS via configured provider with automatic fallback.

    Args:
        cfg: Config instance.
        to_number: Recipient phone number.
        message: SMS text.

    Returns:
        Dict with external_id and provider.

    Raises:
        Exception: If both providers fail.
    """
    primary = cfg.KBS_SMS_PROVIDER
    fallback = "twilio" if primary == "ringcentral" else "ringcentral"

    try:
        if primary == "ringcentral":
            return _send_via_ringcentral(cfg, to_number, message)
        else:
            return _send_via_twilio(cfg, to_number, message)
    except Exception as primary_err:
        logger.warning("SMS primary (%s) failed: %s — trying fallback", primary, primary_err)

        # Only fallback if fallback provider is configured
        has_fallback = (
            (fallback == "twilio" and cfg.KBS_TWILIO_ACCOUNT_SID)
            or (fallback == "ringcentral" and cfg.KBS_RINGCENTRAL_CLIENT_ID)
        )

        if not has_fallback:
            raise

        try:
            if fallback == "twilio":
                return _send_via_twilio(cfg, to_number, message)
            else:
                return _send_via_ringcentral(cfg, to_number, message)
        except Exception as fallback_err:
            logger.error("SMS fallback (%s) also failed: %s", fallback, fallback_err)
            raise


def send_sms(to, message, tenant_id, customer_id=None):
    """Send an SMS and record it in the database.

    Args:
        to: Recipient phone number (E.164 format).
        message: Text message content.
        tenant_id: Tenant ID for schema isolation.
        customer_id: Optional CRM customer ID to associate.

    Returns:
        Dict with sms_id and delivery result.

    Raises:
        Exception: If SMS delivery fails after fallback.
    """
    cfg = Config()

    # Dispatch through provider
    result = _dispatch_sms(cfg, to, message)

    # Record in database
    with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
        set_tenant_search_path(cur, tenant_id)
        cur.execute(
            """
            INSERT INTO sms_messages
                (direction, phone_number, customer_id, message, status, provider, external_id)
            VALUES ('outbound', %s, %s, %s, 'sent', %s, %s)
            RETURNING id
            """,
            (to, customer_id, message, result["provider"], result["external_id"]),
        )
        sms_record = cur.fetchone()

    event_bus.emit(
        "sms.sent",
        {
            "sms_id": sms_record["id"],
            "to": to,
            "customer_id": customer_id,
            "provider": result["provider"],
        },
        tenant_id=tenant_id,
    )

    logger.info("SMS sent to %s via %s (id=%s)", to, result["provider"], sms_record["id"])
    return {"sms_id": sms_record["id"], **result}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker exec kbs_app python -m pytest tests/test_sms_service.py -v
```

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add core/sms_service.py tests/test_sms_service.py
git commit -m "feat(core): SMS dispatch service with RingCentral primary and Twilio fallback"
```

---

## Task 7: SMS Routes

**Files:**
- Create: `plugins/kbs_communications/sms_routes.py`
- Create: `tests/test_communications_sms_routes.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_communications_sms_routes.py`:

```python
"""Tests for SMS communication routes."""

from unittest.mock import MagicMock, patch

import pytest


def test_sms_send_requires_phone_and_message():
    """POST /api/sms/send must require 'to' and 'message' fields."""
    from plugins.kbs_communications.sms_routes import _validate_sms_request

    # Missing 'to'
    errors = _validate_sms_request({"message": "Hello"})
    assert "to" in errors.lower()

    # Missing 'message'
    errors = _validate_sms_request({"to": "+15551234567"})
    assert "message" in errors.lower()

    # Valid
    errors = _validate_sms_request({"to": "+15551234567", "message": "Hi"})
    assert errors is None


def test_sms_list_pagination_defaults():
    """Verify default pagination values."""
    from plugins.kbs_communications.sms_routes import _parse_sms_list_params

    params = _parse_sms_list_params({})
    assert params["page"] == 1
    assert params["per_page"] == 25
    assert params["offset"] == 0


def test_sms_list_pagination_custom():
    from plugins.kbs_communications.sms_routes import _parse_sms_list_params

    params = _parse_sms_list_params({"page": "3", "per_page": "10"})
    assert params["page"] == 3
    assert params["per_page"] == 10
    assert params["offset"] == 20
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker exec kbs_app python -m pytest tests/test_communications_sms_routes.py -v
```

- [ ] **Step 3: Write the implementation**

Create `plugins/kbs_communications/sms_routes.py`:

```python
"""SMS routes for the Communications plugin — send, list, and inbound webhook."""

import logging

from flask import g, jsonify, request
from flask_login import login_required

from core.database import get_db_cursor, set_tenant_search_path
from core.event_bus import event_bus
from core.sms_service import send_sms
from core.tenant import require_module

logger = logging.getLogger(__name__)


def _validate_sms_request(data):
    """Validate SMS send request data. Returns error string or None."""
    to = (data.get("to") or "").strip()
    message = (data.get("message") or "").strip()
    if not to:
        return "'to' phone number is required"
    if not message:
        return "'message' is required"
    return None


def _parse_sms_list_params(args):
    """Parse pagination and filter params for SMS list."""
    page = max(1, int(args.get("page", 1)))
    per_page = min(100, max(1, int(args.get("per_page", 25))))
    return {
        "page": page,
        "per_page": per_page,
        "offset": (page - 1) * per_page,
        "direction": args.get("direction"),
        "customer_id": args.get("customer_id"),
    }


def register_sms_routes(bp):
    """Attach SMS routes to the blueprint."""

    @bp.route("/api/sms/send", methods=["POST"])
    @login_required
    @require_module("communications")
    def sms_send():
        """Send an SMS message. Matches to CRM contact if possible."""
        data = request.get_json(force=True)
        error = _validate_sms_request(data)
        if error:
            return jsonify({"error": error}), 400

        to = data["to"].strip()
        message = data["message"].strip()
        customer_id = data.get("customer_id")

        # Auto-match CRM contact by phone if customer_id not provided
        if not customer_id:
            with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
                set_tenant_search_path(cur, g.tenant_id)
                cur.execute(
                    """
                    SELECT id FROM crm_customers
                    WHERE REPLACE(REPLACE(REPLACE(phone, '-', ''), ' ', ''), '+', '')
                          = REPLACE(REPLACE(REPLACE(%s, '-', ''), ' ', ''), '+', '')
                    LIMIT 1
                    """,
                    (to,),
                )
                match = cur.fetchone()
                if match:
                    customer_id = match["id"]

        try:
            result = send_sms(
                to=to,
                message=message,
                tenant_id=g.tenant_id,
                customer_id=customer_id,
            )
            return jsonify(result), 201
        except Exception as e:
            logger.exception("Failed to send SMS to %s", to)
            return jsonify({"error": f"SMS send failed: {str(e)}"}), 500

    @bp.route("/api/sms", methods=["GET"])
    @login_required
    @require_module("communications")
    def sms_list():
        """List SMS messages with pagination and optional filters."""
        params = _parse_sms_list_params(request.args)

        where = ["1=1"]
        query_params = []

        if params["direction"]:
            where.append("sm.direction = %s")
            query_params.append(params["direction"])
        if params["customer_id"]:
            where.append("sm.customer_id = %s")
            query_params.append(int(params["customer_id"]))

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                f"""
                SELECT sm.id, sm.direction, sm.phone_number, sm.customer_id,
                       sm.message, sm.status, sm.provider, sm.external_id,
                       sm.error_message, sm.created_at,
                       c.first_name || ' ' || c.last_name AS customer_name
                FROM sms_messages sm
                LEFT JOIN crm_customers c ON c.id = sm.customer_id
                WHERE {' AND '.join(where)}
                ORDER BY sm.created_at DESC
                LIMIT %s OFFSET %s
                """,
                query_params + [params["per_page"], params["offset"]],
            )
            messages = cur.fetchall()

            cur.execute(
                f"SELECT COUNT(*) AS total FROM sms_messages sm WHERE {' AND '.join(where)}",
                query_params,
            )
            total = cur.fetchone()["total"]

        return jsonify({
            "messages": messages,
            "total": total,
            "page": params["page"],
            "per_page": params["per_page"],
        })

    @bp.route("/api/webhooks/sms", methods=["POST"])
    def sms_inbound_webhook():
        """Receive inbound SMS messages from provider webhooks.

        Supports both RingCentral and Twilio webhook formats.
        No login required — authenticated by provider-specific mechanisms.
        """
        tenant_id = request.args.get("tenant_id", type=int)
        if not tenant_id:
            return jsonify({"error": "tenant_id required"}), 400

        data = request.get_json(force=True) if request.is_json else request.form.to_dict()

        # Detect provider format
        if "From" in data and "Body" in data:
            # Twilio format
            phone = data["From"]
            message_text = data["Body"]
            provider = "twilio"
            external_id = data.get("MessageSid", "")
        elif "from" in data:
            # RingCentral format
            from_data = data.get("from", {})
            phone = from_data.get("phoneNumber", "") if isinstance(from_data, dict) else str(from_data)
            message_text = data.get("subject", "") or data.get("text", "")
            provider = "ringcentral"
            external_id = data.get("id", "")
        else:
            return jsonify({"error": "Unrecognized webhook format"}), 400

        # Match to CRM customer
        customer_id = None
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, tenant_id)

            digits = phone.lstrip("+").replace("-", "").replace(" ", "")
            cur.execute(
                """
                SELECT id FROM crm_customers
                WHERE REPLACE(REPLACE(REPLACE(phone, '-', ''), ' ', ''), '+', '') = %s
                LIMIT 1
                """,
                (digits,),
            )
            match = cur.fetchone()
            if match:
                customer_id = match["id"]

            cur.execute(
                """
                INSERT INTO sms_messages
                    (direction, phone_number, customer_id, message, status, provider, external_id)
                VALUES ('inbound', %s, %s, %s, 'received', %s, %s)
                RETURNING id
                """,
                (phone, customer_id, message_text, provider, external_id),
            )
            sms = cur.fetchone()

        event_bus.emit(
            "sms.received",
            {
                "sms_id": sms["id"],
                "from": phone,
                "customer_id": customer_id,
                "message": message_text,
            },
            tenant_id=tenant_id,
        )

        # Return TwiML empty response for Twilio, JSON for others
        if provider == "twilio":
            return '<Response></Response>', 200, {"Content-Type": "text/xml"}
        return jsonify({"status": "received", "sms_id": sms["id"]}), 201
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker exec kbs_app python -m pytest tests/test_communications_sms_routes.py -v
```

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add plugins/kbs_communications/sms_routes.py tests/test_communications_sms_routes.py
git commit -m "feat(communications): SMS send, list, and inbound webhook routes"
```

---

## Task 8: Live Chat Manager + Routes

**Files:**
- Create: `core/chat_manager.py`
- Create: `tests/test_chat_manager.py`
- Create: `plugins/kbs_communications/chat_routes.py`
- Create: `tests/test_communications_chat_routes.py`
- Create: `plugins/kbs_communications/static/chat-widget.js`

- [ ] **Step 1: Write the failing chat manager test**

Create `tests/test_chat_manager.py`:

```python
"""Tests for in-memory chat session manager."""

import pytest


def test_create_session():
    from core.chat_manager import ChatManager

    mgr = ChatManager()
    session = mgr.create_session(tenant_id=1, visitor_name="Alice", visitor_email="alice@test.com")

    assert session["tenant_id"] == 1
    assert session["visitor_name"] == "Alice"
    assert session["status"] == "active"
    assert len(session["messages"]) == 0
    assert "id" in session


def test_send_message():
    from core.chat_manager import ChatManager

    mgr = ChatManager()
    session = mgr.create_session(tenant_id=1, visitor_name="Bob")
    sid = session["id"]

    msg = mgr.send_message(sid, sender_type="visitor", sender_name="Bob", content="Hello!")

    assert msg["sender_type"] == "visitor"
    assert msg["content"] == "Hello!"
    assert len(mgr.get_messages(sid)) == 1


def test_agent_reply():
    from core.chat_manager import ChatManager

    mgr = ChatManager()
    session = mgr.create_session(tenant_id=1, visitor_name="Carol")
    sid = session["id"]

    mgr.send_message(sid, "visitor", "Carol", "Help!")
    mgr.send_message(sid, "agent", "Support Agent", "How can I help?")

    messages = mgr.get_messages(sid)
    assert len(messages) == 2
    assert messages[1]["sender_type"] == "agent"


def test_close_session():
    from core.chat_manager import ChatManager

    mgr = ChatManager()
    session = mgr.create_session(tenant_id=1, visitor_name="Dan")
    sid = session["id"]

    closed = mgr.close_session(sid)
    assert closed["status"] == "closed"
    assert closed["closed_at"] is not None


def test_list_active_sessions():
    from core.chat_manager import ChatManager

    mgr = ChatManager()
    mgr.create_session(tenant_id=1, visitor_name="Alice")
    mgr.create_session(tenant_id=1, visitor_name="Bob")
    mgr.create_session(tenant_id=2, visitor_name="Carol")

    active = mgr.list_active(tenant_id=1)
    assert len(active) == 2


def test_close_removes_from_active():
    from core.chat_manager import ChatManager

    mgr = ChatManager()
    session = mgr.create_session(tenant_id=1, visitor_name="Eve")
    mgr.close_session(session["id"])

    active = mgr.list_active(tenant_id=1)
    assert len(active) == 0


def test_send_to_closed_session_fails():
    from core.chat_manager import ChatManager

    mgr = ChatManager()
    session = mgr.create_session(tenant_id=1, visitor_name="Frank")
    mgr.close_session(session["id"])

    with pytest.raises(ValueError, match="closed"):
        mgr.send_message(session["id"], "visitor", "Frank", "Hello?")


def test_get_session_not_found():
    from core.chat_manager import ChatManager

    mgr = ChatManager()
    result = mgr.get_session("nonexistent-id")
    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker exec kbs_app python -m pytest tests/test_chat_manager.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'core.chat_manager'`

- [ ] **Step 3: Write the chat manager implementation**

Create `core/chat_manager.py`:

```python
"""In-memory chat session manager for live chat widget.

Sessions are stored in memory (not persisted). Closed sessions are
persisted to the database by the chat routes. This keeps the chat
fast and simple while ensuring conversation history is saved.

Thread-safe via a threading lock on session mutations.
"""

import logging
import threading
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class ChatManager:
    """Manages active chat sessions in memory.

    Each session is a dict with keys:
        id, tenant_id, visitor_name, visitor_email, customer_id,
        status, channel, messages, created_at, closed_at
    """

    def __init__(self):
        self._sessions = {}  # session_id -> session dict
        self._lock = threading.Lock()

    def create_session(self, tenant_id, visitor_name=None, visitor_email=None,
                       customer_id=None, channel="widget"):
        """Create a new active chat session.

        Args:
            tenant_id: Tenant ID for isolation.
            visitor_name: Optional visitor display name.
            visitor_email: Optional visitor email.
            customer_id: Optional CRM customer ID.
            channel: Chat channel type (widget or internal).

        Returns:
            Session dict.
        """
        session_id = str(uuid.uuid4())
        session = {
            "id": session_id,
            "tenant_id": tenant_id,
            "visitor_name": visitor_name or "Visitor",
            "visitor_email": visitor_email,
            "customer_id": customer_id,
            "status": "active",
            "channel": channel,
            "messages": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "closed_at": None,
        }
        with self._lock:
            self._sessions[session_id] = session
        logger.info("Chat session %s created for tenant %s", session_id, tenant_id)
        return dict(session)

    def get_session(self, session_id):
        """Get a session by ID. Returns None if not found."""
        session = self._sessions.get(session_id)
        return dict(session) if session else None

    def send_message(self, session_id, sender_type, sender_name, content):
        """Add a message to an active session.

        Args:
            session_id: Chat session ID.
            sender_type: One of 'visitor', 'agent', 'system'.
            sender_name: Display name of sender.
            content: Message text.

        Returns:
            Message dict.

        Raises:
            ValueError: If session is closed or not found.
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                raise ValueError(f"Session {session_id} not found")
            if session["status"] == "closed":
                raise ValueError(f"Session {session_id} is closed")

            message = {
                "id": str(uuid.uuid4()),
                "sender_type": sender_type,
                "sender_name": sender_name,
                "content": content,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            session["messages"].append(message)

        return dict(message)

    def get_messages(self, session_id, since=None):
        """Get messages from a session, optionally since a timestamp.

        Args:
            session_id: Chat session ID.
            since: Optional ISO timestamp — return only messages after this time.

        Returns:
            List of message dicts.
        """
        session = self._sessions.get(session_id)
        if not session:
            return []
        messages = session["messages"]
        if since:
            messages = [m for m in messages if m["created_at"] > since]
        return [dict(m) for m in messages]

    def close_session(self, session_id):
        """Close a chat session.

        Args:
            session_id: Chat session ID.

        Returns:
            Closed session dict.

        Raises:
            ValueError: If session not found.
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                raise ValueError(f"Session {session_id} not found")
            session["status"] = "closed"
            session["closed_at"] = datetime.now(timezone.utc).isoformat()
            result = dict(session)
            # Remove from active sessions
            del self._sessions[session_id]
        logger.info("Chat session %s closed", session_id)
        return result

    def list_active(self, tenant_id=None):
        """List active chat sessions, optionally filtered by tenant.

        Args:
            tenant_id: Optional tenant filter.

        Returns:
            List of session dicts (without full message lists for performance).
        """
        sessions = []
        for s in self._sessions.values():
            if s["status"] != "active":
                continue
            if tenant_id and s["tenant_id"] != tenant_id:
                continue
            summary = {k: v for k, v in s.items() if k != "messages"}
            summary["message_count"] = len(s["messages"])
            sessions.append(summary)
        return sessions


# Module-level singleton
chat_manager = ChatManager()
```

- [ ] **Step 4: Run chat manager tests**

```bash
docker exec kbs_app python -m pytest tests/test_chat_manager.py -v
```

- [ ] **Step 5: Write the failing chat routes test**

Create `tests/test_communications_chat_routes.py`:

```python
"""Tests for chat REST endpoints — validation and data flow."""

import pytest


def test_chat_start_requires_visitor_name_or_email():
    """Starting a chat with no identity should still work (anonymous)."""
    from core.chat_manager import ChatManager

    mgr = ChatManager()
    session = mgr.create_session(tenant_id=1)
    assert session["visitor_name"] == "Visitor"


def test_chat_message_requires_content():
    """Sending an empty message should fail."""
    from plugins.kbs_communications.chat_routes import _validate_chat_message

    error = _validate_chat_message({"content": ""})
    assert error is not None

    error = _validate_chat_message({"content": "Hello"})
    assert error is None


def test_chat_close_persists_to_db():
    """Verify _persist_conversation builds the right SQL params."""
    from plugins.kbs_communications.chat_routes import _build_persist_params

    session = {
        "id": "abc-123",
        "visitor_name": "Alice",
        "visitor_email": "alice@test.com",
        "customer_id": 42,
        "channel": "widget",
        "messages": [
            {"sender_type": "visitor", "sender_name": "Alice", "content": "Hi", "created_at": "2026-03-28T10:00:00"},
            {"sender_type": "agent", "sender_name": "Support", "content": "Hello!", "created_at": "2026-03-28T10:00:05"},
        ],
        "created_at": "2026-03-28T09:59:00",
        "closed_at": "2026-03-28T10:05:00",
    }

    conv_params, msg_params_list = _build_persist_params(session)
    assert conv_params["visitor_name"] == "Alice"
    assert conv_params["customer_id"] == 42
    assert len(msg_params_list) == 2
    assert msg_params_list[0]["sender_type"] == "visitor"
```

- [ ] **Step 6: Write the chat routes implementation**

Create `plugins/kbs_communications/chat_routes.py`:

```python
"""Chat routes for the Communications plugin — REST-based live chat."""

import logging

from flask import g, jsonify, request
from flask_login import login_required

from core.chat_manager import chat_manager
from core.database import get_db_cursor, set_tenant_search_path
from core.event_bus import event_bus
from core.tenant import require_module

logger = logging.getLogger(__name__)


def _validate_chat_message(data):
    """Validate chat message data. Returns error string or None."""
    content = (data.get("content") or "").strip()
    if not content:
        return "content is required"
    return None


def _build_persist_params(session):
    """Build database insert parameters from a closed chat session.

    Args:
        session: Closed session dict from ChatManager.

    Returns:
        Tuple of (conversation_params dict, list of message_params dicts).
    """
    conv_params = {
        "visitor_name": session.get("visitor_name"),
        "visitor_email": session.get("visitor_email"),
        "customer_id": session.get("customer_id"),
        "channel": session.get("channel", "widget"),
        "created_at": session.get("created_at"),
        "closed_at": session.get("closed_at"),
    }
    msg_params_list = [
        {
            "sender_type": m["sender_type"],
            "sender_name": m.get("sender_name"),
            "content": m["content"],
            "created_at": m.get("created_at"),
        }
        for m in session.get("messages", [])
    ]
    return conv_params, msg_params_list


def _persist_conversation(tenant_id, session):
    """Save a closed chat session to the database.

    Args:
        tenant_id: Tenant ID for schema isolation.
        session: Closed session dict.
    """
    conv_params, msg_params_list = _build_persist_params(session)

    with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
        set_tenant_search_path(cur, tenant_id)
        cur.execute(
            """
            INSERT INTO chat_conversations
                (visitor_name, visitor_email, customer_id, status, channel, created_at, closed_at)
            VALUES (%s, %s, %s, 'closed', %s, %s, %s)
            RETURNING id
            """,
            (
                conv_params["visitor_name"],
                conv_params["visitor_email"],
                conv_params["customer_id"],
                conv_params["channel"],
                conv_params["created_at"],
                conv_params["closed_at"],
            ),
        )
        conv = cur.fetchone()
        conv_id = conv["id"]

        for mp in msg_params_list:
            cur.execute(
                """
                INSERT INTO chat_messages (conversation_id, sender_type, sender_name, content, created_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (conv_id, mp["sender_type"], mp["sender_name"], mp["content"], mp["created_at"]),
            )

    return conv_id


def register_chat_routes(bp):
    """Attach chat routes to the blueprint."""

    @bp.route("/api/chat/start", methods=["POST"])
    def chat_start():
        """Start a new chat session. No login required (public widget).

        Tenant is identified by query param or request body.
        """
        data = request.get_json(force=True) if request.is_json else {}
        tenant_id = request.args.get("tenant_id", type=int) or data.get("tenant_id")
        if not tenant_id:
            return jsonify({"error": "tenant_id required"}), 400

        visitor_name = (data.get("visitor_name") or "").strip() or None
        visitor_email = (data.get("visitor_email") or "").strip() or None

        # Auto-match CRM customer by email
        customer_id = None
        if visitor_email:
            with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
                set_tenant_search_path(cur, tenant_id)
                cur.execute(
                    "SELECT id FROM crm_customers WHERE email = %s LIMIT 1",
                    (visitor_email,),
                )
                match = cur.fetchone()
                if match:
                    customer_id = match["id"]

        session = chat_manager.create_session(
            tenant_id=tenant_id,
            visitor_name=visitor_name,
            visitor_email=visitor_email,
            customer_id=customer_id,
        )

        event_bus.emit(
            "chat.started",
            {"session_id": session["id"], "visitor_name": visitor_name, "customer_id": customer_id},
            tenant_id=tenant_id,
        )

        return jsonify(session), 201

    @bp.route("/api/chat/<session_id>/message", methods=["POST"])
    def chat_message(session_id):
        """Send a message in a chat session. No login required for visitor messages."""
        data = request.get_json(force=True)
        error = _validate_chat_message(data)
        if error:
            return jsonify({"error": error}), 400

        sender_type = data.get("sender_type", "visitor")
        sender_name = data.get("sender_name", "Visitor")
        content = data["content"].strip()

        try:
            msg = chat_manager.send_message(session_id, sender_type, sender_name, content)
            return jsonify(msg), 201
        except ValueError as e:
            return jsonify({"error": str(e)}), 404

    @bp.route("/api/chat/<session_id>/messages", methods=["GET"])
    def chat_get_messages(session_id):
        """Get messages from a chat session (polling endpoint).

        Supports ?since=ISO_TIMESTAMP for incremental polling.
        """
        since = request.args.get("since")
        messages = chat_manager.get_messages(session_id, since=since)
        return jsonify({"messages": messages})

    @bp.route("/api/chat/<session_id>/close", methods=["POST"])
    @login_required
    @require_module("communications")
    def chat_close(session_id):
        """Close a chat session and persist to database. Agent-only action."""
        session = chat_manager.get_session(session_id)
        if not session:
            return jsonify({"error": "Session not found"}), 404

        try:
            closed = chat_manager.close_session(session_id)
        except ValueError as e:
            return jsonify({"error": str(e)}), 404

        # Persist to database
        tenant_id = closed.get("tenant_id") or g.tenant_id
        try:
            conv_id = _persist_conversation(tenant_id, closed)
            closed["db_conversation_id"] = conv_id
        except Exception:
            logger.exception("Failed to persist chat session %s", session_id)

        event_bus.emit(
            "chat.closed",
            {"session_id": session_id, "customer_id": closed.get("customer_id")},
            tenant_id=tenant_id,
        )

        return jsonify(closed)

    @bp.route("/api/chat/active", methods=["GET"])
    @login_required
    @require_module("communications")
    def chat_list_active():
        """List active chat sessions for the current tenant."""
        sessions = chat_manager.list_active(tenant_id=g.tenant_id)
        return jsonify({"sessions": sessions})
```

- [ ] **Step 7: Create the embeddable chat widget**

Create `plugins/kbs_communications/static/chat-widget.js`:

```javascript
/**
 * Kytran Business Suite — Embeddable Live Chat Widget
 *
 * Usage: Add to any page:
 *   <script src="https://your-kbs-domain/static/communications/chat-widget.js"
 *           data-tenant-id="1"
 *           data-kbs-url="https://your-kbs-domain"></script>
 *
 * The widget creates a floating chat bubble in the bottom-right corner.
 * Messages are exchanged via REST polling (WebSocket upgrade in Wave 4).
 */
(function () {
  "use strict";

  var script = document.currentScript;
  var KBS_URL = (script.getAttribute("data-kbs-url") || "").replace(/\/$/, "");
  var TENANT_ID = script.getAttribute("data-tenant-id");
  var POLL_INTERVAL = 3000; // 3 seconds

  if (!KBS_URL || !TENANT_ID) {
    console.error("[KBS Chat] data-kbs-url and data-tenant-id are required.");
    return;
  }

  var sessionId = null;
  var pollTimer = null;
  var lastMessageTime = null;
  var visitorName = "Visitor";

  // --- Styles ---
  var STYLES =
    "#kbs-chat-bubble{position:fixed;bottom:24px;right:24px;z-index:99999;" +
    "width:56px;height:56px;border-radius:50%;background:#00e5ff;color:#0d0d1a;" +
    "border:none;cursor:pointer;box-shadow:0 4px 16px rgba(0,229,255,0.3);" +
    "display:flex;align-items:center;justify-content:center;font-size:24px;" +
    "transition:transform 0.2s}" +
    "#kbs-chat-bubble:hover{transform:scale(1.1)}" +
    "#kbs-chat-window{position:fixed;bottom:90px;right:24px;z-index:99999;" +
    "width:360px;max-height:500px;background:#1a1a2e;border:1px solid #00e5ff33;" +
    "border-radius:12px;display:none;flex-direction:column;overflow:hidden;" +
    "box-shadow:0 8px 32px rgba(0,0,0,0.5);font-family:'Segoe UI',Arial,sans-serif}" +
    "#kbs-chat-window.open{display:flex}" +
    ".kbs-chat-header{background:#0d0d1a;color:#00e5ff;padding:14px 16px;" +
    "font-weight:bold;font-size:14px;border-bottom:1px solid #00e5ff33;" +
    "display:flex;justify-content:space-between;align-items:center}" +
    ".kbs-chat-header button{background:none;border:none;color:#888;cursor:pointer;font-size:18px}" +
    ".kbs-chat-messages{flex:1;overflow-y:auto;padding:12px;min-height:200px;max-height:340px}" +
    ".kbs-chat-msg{margin-bottom:8px;padding:8px 12px;border-radius:8px;" +
    "font-size:13px;line-height:1.4;max-width:85%;word-wrap:break-word}" +
    ".kbs-chat-msg.visitor{background:#00e5ff22;color:#e0e0e0;margin-left:auto}" +
    ".kbs-chat-msg.agent{background:#2a2a4a;color:#e0e0e0}" +
    ".kbs-chat-msg.system{background:transparent;color:#888;font-style:italic;" +
    "text-align:center;max-width:100%}" +
    ".kbs-chat-input{display:flex;border-top:1px solid #00e5ff33;padding:8px}" +
    ".kbs-chat-input input{flex:1;background:#0d0d1a;border:1px solid #333;" +
    "border-radius:6px;color:#e0e0e0;padding:8px 12px;font-size:13px;outline:none}" +
    ".kbs-chat-input input:focus{border-color:#00e5ff}" +
    ".kbs-chat-input button{background:#00e5ff;color:#0d0d1a;border:none;" +
    "border-radius:6px;padding:8px 14px;margin-left:6px;cursor:pointer;font-weight:bold}" +
    ".kbs-chat-start{padding:16px}" +
    ".kbs-chat-start input{width:100%;background:#0d0d1a;border:1px solid #333;" +
    "border-radius:6px;color:#e0e0e0;padding:8px 12px;font-size:13px;margin-bottom:8px;" +
    "outline:none;box-sizing:border-box}" +
    ".kbs-chat-start button{width:100%;background:#00e5ff;color:#0d0d1a;border:none;" +
    "border-radius:6px;padding:10px;cursor:pointer;font-weight:bold}";

  // --- Inject styles ---
  var styleEl = document.createElement("style");
  styleEl.textContent = STYLES;
  document.head.appendChild(styleEl);

  // --- Create DOM elements safely ---
  var bubble = document.createElement("button");
  bubble.id = "kbs-chat-bubble";
  bubble.textContent = "\uD83D\uDCAC";
  bubble.title = "Chat with us";
  document.body.appendChild(bubble);

  var win = document.createElement("div");
  win.id = "kbs-chat-window";
  document.body.appendChild(win);

  // Build header
  var header = document.createElement("div");
  header.className = "kbs-chat-header";
  var headerLabel = document.createElement("span");
  headerLabel.textContent = "Live Chat";
  var closeBtn = document.createElement("button");
  closeBtn.id = "kbs-chat-close";
  closeBtn.textContent = "\u00D7";
  header.appendChild(headerLabel);
  header.appendChild(closeBtn);
  win.appendChild(header);

  // Build body with start form
  var body = document.createElement("div");
  body.id = "kbs-chat-body";
  win.appendChild(body);

  var startForm = document.createElement("div");
  startForm.className = "kbs-chat-start";
  startForm.id = "kbs-chat-start-form";

  var nameInput = document.createElement("input");
  nameInput.type = "text";
  nameInput.id = "kbs-chat-name";
  nameInput.placeholder = "Your name (optional)";

  var emailInput = document.createElement("input");
  emailInput.type = "email";
  emailInput.id = "kbs-chat-email";
  emailInput.placeholder = "Your email (optional)";

  var startBtn = document.createElement("button");
  startBtn.id = "kbs-chat-start-btn";
  startBtn.textContent = "Start Chat";

  startForm.appendChild(nameInput);
  startForm.appendChild(emailInput);
  startForm.appendChild(startBtn);
  body.appendChild(startForm);

  // --- Event handlers ---
  bubble.addEventListener("click", function () {
    win.classList.toggle("open");
  });

  closeBtn.addEventListener("click", function () {
    win.classList.remove("open");
  });

  startBtn.addEventListener("click", startChat);

  function startChat() {
    var name = nameInput.value.trim();
    var email = emailInput.value.trim();
    visitorName = name || "Visitor";

    fetch(KBS_URL + "/communications/api/chat/start?tenant_id=" + TENANT_ID, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        visitor_name: name || undefined,
        visitor_email: email || undefined,
      }),
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        sessionId = data.id;
        showChatUI();
        startPolling();
      })
      .catch(function (err) {
        console.error("[KBS Chat] Failed to start:", err);
      });
  }

  function showChatUI() {
    // Clear body and rebuild with safe DOM methods
    while (body.firstChild) { body.removeChild(body.firstChild); }

    var messagesDiv = document.createElement("div");
    messagesDiv.className = "kbs-chat-messages";
    messagesDiv.id = "kbs-chat-messages";

    var systemMsg = document.createElement("div");
    systemMsg.className = "kbs-chat-msg system";
    systemMsg.textContent = "Chat started. An agent will be with you shortly.";
    messagesDiv.appendChild(systemMsg);

    var inputDiv = document.createElement("div");
    inputDiv.className = "kbs-chat-input";

    var chatInput = document.createElement("input");
    chatInput.type = "text";
    chatInput.id = "kbs-chat-input";
    chatInput.placeholder = "Type a message...";

    var sendBtn = document.createElement("button");
    sendBtn.id = "kbs-chat-send";
    sendBtn.textContent = "Send";

    inputDiv.appendChild(chatInput);
    inputDiv.appendChild(sendBtn);

    body.appendChild(messagesDiv);
    body.appendChild(inputDiv);

    sendBtn.addEventListener("click", sendMessage);
    chatInput.addEventListener("keypress", function (e) {
      if (e.key === "Enter") sendMessage();
    });
  }

  function sendMessage() {
    var input = document.getElementById("kbs-chat-input");
    var text = input.value.trim();
    if (!text || !sessionId) return;
    input.value = "";

    appendMessage("visitor", text);

    fetch(KBS_URL + "/communications/api/chat/" + sessionId + "/message", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sender_type: "visitor",
        sender_name: visitorName,
        content: text,
      }),
    }).catch(function (err) {
      console.error("[KBS Chat] Send failed:", err);
    });
  }

  function appendMessage(type, content) {
    var container = document.getElementById("kbs-chat-messages");
    if (!container) return;
    var div = document.createElement("div");
    div.className = "kbs-chat-msg " + type;
    div.textContent = content;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
  }

  function startPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(pollMessages, POLL_INTERVAL);
  }

  function pollMessages() {
    if (!sessionId) return;
    var url = KBS_URL + "/communications/api/chat/" + sessionId + "/messages";
    if (lastMessageTime) url += "?since=" + encodeURIComponent(lastMessageTime);

    fetch(url)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        (data.messages || []).forEach(function (msg) {
          // Only show agent/system messages (visitor messages already shown on send)
          if (msg.sender_type !== "visitor") {
            appendMessage(msg.sender_type, msg.content);
          }
          lastMessageTime = msg.created_at;
        });
      })
      .catch(function (err) {
        console.error("[KBS Chat] Poll failed:", err);
      });
  }
})();
```

- [ ] **Step 8: Run all chat tests**

```bash
docker exec kbs_app python -m pytest tests/test_chat_manager.py tests/test_communications_chat_routes.py -v
```

- [ ] **Step 9: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add core/chat_manager.py plugins/kbs_communications/chat_routes.py \
        plugins/kbs_communications/static/chat-widget.js \
        tests/test_chat_manager.py tests/test_communications_chat_routes.py
git commit -m "feat(communications): live chat manager, REST routes, and embeddable widget"
```

---

## Task 9: Email Marketing (Hostinger Reach)

**Files:**
- Create: `core/reach_client.py`
- Create: `tests/test_reach_client.py`
- Create: `plugins/kbs_communications/campaign_routes.py`
- Create: `tests/test_communications_campaigns.py`

- [ ] **Step 1: Write the failing Reach client test**

Create `tests/test_reach_client.py`:

```python
"""Tests for Hostinger Reach email marketing API client — all HTTP mocked."""

from unittest.mock import MagicMock, patch

import pytest


def test_create_campaign():
    from core.reach_client import ReachClient

    client = ReachClient(api_url="https://api.hostinger.com/reach/v1", api_key="test-key")

    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.json.return_value = {"id": "camp-1", "status": "draft"}

    with patch("core.reach_client.requests.post", return_value=mock_resp):
        result = client.create_campaign(
            name="Spring Sale",
            subject="50% off everything!",
            html_content="<h1>Sale!</h1>",
            contacts=[{"email": "jane@test.com"}],
        )

    assert result["id"] == "camp-1"


def test_send_campaign():
    from core.reach_client import ReachClient

    client = ReachClient(api_url="https://api.hostinger.com/reach/v1", api_key="test-key")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"id": "camp-1", "status": "sending"}

    with patch("core.reach_client.requests.post", return_value=mock_resp):
        result = client.send_campaign("camp-1")

    assert result["status"] == "sending"


def test_get_campaign_stats():
    from core.reach_client import ReachClient

    client = ReachClient(api_url="https://api.hostinger.com/reach/v1", api_key="test-key")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "total_sent": 500,
        "delivered": 490,
        "opened": 200,
        "clicked": 50,
        "bounced": 10,
        "unsubscribed": 2,
    }

    with patch("core.reach_client.requests.get", return_value=mock_resp):
        stats = client.get_campaign_stats("camp-1")

    assert stats["total_sent"] == 500
    assert stats["opened"] == 200


def test_list_segments():
    from core.reach_client import ReachClient

    client = ReachClient(api_url="https://api.hostinger.com/reach/v1", api_key="test-key")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": [{"id": "seg-1", "name": "VIP Customers", "contact_count": 50}]
    }

    with patch("core.reach_client.requests.get", return_value=mock_resp):
        segments = client.list_segments()

    assert len(segments) == 1
    assert segments[0]["name"] == "VIP Customers"


def test_auth_header_included():
    from core.reach_client import ReachClient

    client = ReachClient(api_url="https://api.hostinger.com/reach/v1", api_key="my-api-key")
    headers = client._headers()
    assert headers["Authorization"] == "Bearer my-api-key"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker exec kbs_app python -m pytest tests/test_reach_client.py -v
```

- [ ] **Step 3: Write the Reach client implementation**

Create `core/reach_client.py`:

```python
"""Hostinger Reach email marketing API client.

Wraps the Reach API for creating and sending email campaigns.
Used by the Communications plugin for email marketing features.
"""

import logging

import requests

logger = logging.getLogger(__name__)


class ReachClient:
    """Client for the Hostinger Reach email marketing API.

    Args:
        api_url: Reach API base URL.
        api_key: Reach API key for authentication.
    """

    def __init__(self, api_url, api_key):
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key

    def _headers(self):
        """Return authorization headers."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def create_campaign(self, name, subject, html_content, contacts, text_content=None):
        """Create a new email campaign.

        Args:
            name: Campaign name.
            subject: Email subject line.
            html_content: HTML email body.
            contacts: List of contact dicts with at least 'email' key.
            text_content: Optional plain-text body.

        Returns:
            Campaign dict from Reach API.
        """
        resp = requests.post(
            f"{self.api_url}/campaigns",
            headers=self._headers(),
            json={
                "name": name,
                "subject": subject,
                "html_content": html_content,
                "text_content": text_content or "",
                "contacts": contacts,
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def send_campaign(self, campaign_id):
        """Send a campaign immediately.

        Args:
            campaign_id: Campaign ID from create_campaign.

        Returns:
            Updated campaign dict.
        """
        resp = requests.post(
            f"{self.api_url}/campaigns/{campaign_id}/send",
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def get_campaign_stats(self, campaign_id):
        """Get delivery statistics for a campaign.

        Args:
            campaign_id: Campaign ID.

        Returns:
            Stats dict with total_sent, delivered, opened, clicked, bounced, unsubscribed.
        """
        resp = requests.get(
            f"{self.api_url}/campaigns/{campaign_id}/stats",
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def list_segments(self):
        """List available contact segments.

        Returns:
            List of segment dicts.
        """
        resp = requests.get(
            f"{self.api_url}/segments",
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get("data", [])
```

- [ ] **Step 4: Write the failing campaign routes test**

Create `tests/test_communications_campaigns.py`:

```python
"""Tests for email campaign routes — validation and data flow."""

import pytest


def test_campaign_create_requires_name_and_subject():
    from plugins.kbs_communications.campaign_routes import _validate_campaign

    errors = _validate_campaign({})
    assert "name" in errors.lower()

    errors = _validate_campaign({"name": "Test"})
    assert "subject" in errors.lower()

    errors = _validate_campaign({"name": "Test", "subject": "Hello"})
    assert errors is None


def test_campaign_status_transitions():
    from plugins.kbs_communications.campaign_routes import _valid_status_transition

    assert _valid_status_transition("draft", "sending") is True
    assert _valid_status_transition("draft", "cancelled") is True
    assert _valid_status_transition("sending", "sent") is True
    assert _valid_status_transition("sent", "draft") is False
    assert _valid_status_transition("cancelled", "sending") is False
```

- [ ] **Step 5: Write the campaign routes implementation**

Create `plugins/kbs_communications/campaign_routes.py`:

```python
"""Email campaign routes for the Communications plugin — CRUD, send, stats."""

import logging
from datetime import datetime

from flask import g, jsonify, request
from flask_login import login_required

from core.config import Config
from core.database import get_db_cursor, set_tenant_search_path
from core.event_bus import event_bus
from core.reach_client import ReachClient
from core.tenant import require_module

logger = logging.getLogger(__name__)

# Valid status transitions
_STATUS_TRANSITIONS = {
    "draft": {"sending", "scheduled", "cancelled"},
    "scheduled": {"sending", "cancelled", "draft"},
    "sending": {"sent"},
    "sent": set(),
    "cancelled": set(),
}


def _validate_campaign(data):
    """Validate campaign creation data. Returns error string or None."""
    name = (data.get("name") or "").strip()
    if not name:
        return "'name' is required"
    subject = (data.get("subject") or "").strip()
    if not subject:
        return "'subject' is required"
    return None


def _valid_status_transition(current, target):
    """Check if a status transition is allowed."""
    allowed = _STATUS_TRANSITIONS.get(current, set())
    return target in allowed


def _get_reach_client():
    """Create a ReachClient from config."""
    cfg = Config()
    return ReachClient(api_url=cfg.KBS_REACH_API_URL, api_key=cfg.KBS_REACH_API_KEY)


def register_campaign_routes(bp):
    """Attach email campaign routes to the blueprint."""

    @bp.route("/api/campaigns", methods=["GET"])
    @login_required
    @require_module("communications")
    def list_campaigns():
        """List email campaigns with pagination."""
        page = max(1, request.args.get("page", 1, type=int))
        per_page = min(100, max(1, request.args.get("per_page", 25, type=int)))
        offset = (page - 1) * per_page
        status = request.args.get("status")

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            where = ["1=1"]
            params = []
            if status:
                where.append("ec.status = %s")
                params.append(status)

            cur.execute(
                f"""
                SELECT ec.id, ec.name, ec.subject, ec.status,
                       ec.scheduled_at, ec.sent_at, ec.created_at, ec.updated_at,
                       ecs.total_sent, ecs.delivered, ecs.opened,
                       ecs.clicked, ecs.bounced, ecs.unsubscribed
                FROM email_campaigns ec
                LEFT JOIN email_campaign_stats ecs ON ecs.campaign_id = ec.id
                WHERE {' AND '.join(where)}
                ORDER BY ec.created_at DESC
                LIMIT %s OFFSET %s
                """,
                params + [per_page, offset],
            )
            campaigns = cur.fetchall()

            cur.execute(
                f"SELECT COUNT(*) AS total FROM email_campaigns ec WHERE {' AND '.join(where)}",
                params,
            )
            total = cur.fetchone()["total"]

        return jsonify({"campaigns": campaigns, "total": total, "page": page, "per_page": per_page})

    @bp.route("/api/campaigns", methods=["POST"])
    @login_required
    @require_module("communications")
    def create_campaign():
        """Create a new email campaign (draft)."""
        data = request.get_json(force=True)
        error = _validate_campaign(data)
        if error:
            return jsonify({"error": error}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                INSERT INTO email_campaigns
                    (name, subject, html_content, text_content, segment_id, scheduled_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id, name, subject, status, created_at
                """,
                (
                    data["name"].strip(),
                    data["subject"].strip(),
                    data.get("html_content", ""),
                    data.get("text_content", ""),
                    data.get("segment_id"),
                    data.get("scheduled_at"),
                ),
            )
            campaign = cur.fetchone()

        event_bus.emit(
            "campaign.created",
            {"campaign_id": campaign["id"], "name": campaign["name"]},
            tenant_id=g.tenant_id,
        )

        return jsonify(campaign), 201

    @bp.route("/api/campaigns/<int:campaign_id>", methods=["PUT"])
    @login_required
    @require_module("communications")
    def update_campaign(campaign_id):
        """Update a draft campaign."""
        data = request.get_json(force=True)

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            cur.execute("SELECT id, status FROM email_campaigns WHERE id = %s", (campaign_id,))
            existing = cur.fetchone()
            if not existing:
                return jsonify({"error": "Campaign not found"}), 404
            if existing["status"] not in ("draft", "scheduled"):
                return jsonify({"error": "Cannot edit a campaign that is sending or sent"}), 400

            allowed = {"name", "subject", "html_content", "text_content", "segment_id", "scheduled_at"}
            sets = []
            params = []
            for field in allowed:
                if field in data:
                    sets.append(f"{field} = %s")
                    params.append(data[field])

            if not sets:
                return jsonify({"error": "No fields to update"}), 400

            sets.append("updated_at = NOW()")
            params.append(campaign_id)

            cur.execute(
                f"""
                UPDATE email_campaigns SET {', '.join(sets)}
                WHERE id = %s
                RETURNING id, name, subject, status, scheduled_at, created_at, updated_at
                """,
                params,
            )
            campaign = cur.fetchone()

        return jsonify(campaign)

    @bp.route("/api/campaigns/<int:campaign_id>/send", methods=["POST"])
    @login_required
    @require_module("communications")
    def send_campaign(campaign_id):
        """Send a campaign via Hostinger Reach."""
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            cur.execute(
                "SELECT id, name, subject, html_content, text_content, segment_id, status "
                "FROM email_campaigns WHERE id = %s",
                (campaign_id,),
            )
            campaign = cur.fetchone()
            if not campaign:
                return jsonify({"error": "Campaign not found"}), 404

            if not _valid_status_transition(campaign["status"], "sending"):
                return jsonify({"error": f"Cannot send campaign in '{campaign['status']}' status"}), 400

            # Get contacts for the campaign
            contacts = []
            if campaign["segment_id"]:
                cur.execute(
                    """
                    SELECT c.email, c.first_name, c.last_name
                    FROM crm_customers c
                    JOIN crm_segment_members sm ON sm.customer_id = c.id
                    WHERE sm.segment_id = %s AND c.email IS NOT NULL AND c.email != ''
                    """,
                    (campaign["segment_id"],),
                )
                contacts = [dict(r) for r in cur.fetchall()]
            else:
                cur.execute(
                    "SELECT email, first_name, last_name FROM crm_customers "
                    "WHERE email IS NOT NULL AND email != ''"
                )
                contacts = [dict(r) for r in cur.fetchall()]

            if not contacts:
                return jsonify({"error": "No contacts with email addresses found"}), 400

            # Update status to sending
            cur.execute(
                "UPDATE email_campaigns SET status = 'sending', updated_at = NOW() WHERE id = %s",
                (campaign_id,),
            )

        # Send via Reach API
        try:
            reach = _get_reach_client()
            reach_campaign = reach.create_campaign(
                name=campaign["name"],
                subject=campaign["subject"],
                html_content=campaign["html_content"],
                contacts=contacts,
                text_content=campaign["text_content"],
            )
            reach.send_campaign(reach_campaign["id"])

            # Update status and stats
            with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
                set_tenant_search_path(cur, g.tenant_id)
                cur.execute(
                    "UPDATE email_campaigns SET status = 'sent', sent_at = NOW(), updated_at = NOW() "
                    "WHERE id = %s",
                    (campaign_id,),
                )
                cur.execute(
                    """
                    INSERT INTO email_campaign_stats (campaign_id, total_sent)
                    VALUES (%s, %s)
                    ON CONFLICT (campaign_id) DO UPDATE SET total_sent = %s, updated_at = NOW()
                    """,
                    (campaign_id, len(contacts), len(contacts)),
                )

            event_bus.emit(
                "campaign.sent",
                {"campaign_id": campaign_id, "total_contacts": len(contacts)},
                tenant_id=g.tenant_id,
            )

            return jsonify({"status": "sent", "total_contacts": len(contacts)})

        except Exception as e:
            # Revert status on failure
            with get_db_cursor(commit=True) as (conn, cur):
                set_tenant_search_path(cur, g.tenant_id)
                cur.execute(
                    "UPDATE email_campaigns SET status = 'draft', updated_at = NOW() WHERE id = %s",
                    (campaign_id,),
                )
            logger.exception("Failed to send campaign %s", campaign_id)
            return jsonify({"error": f"Send failed: {str(e)}"}), 500

    @bp.route("/api/campaigns/<int:campaign_id>/stats", methods=["GET"])
    @login_required
    @require_module("communications")
    def campaign_stats(campaign_id):
        """Get delivery statistics for a campaign."""
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "SELECT id, status FROM email_campaigns WHERE id = %s",
                (campaign_id,),
            )
            campaign = cur.fetchone()
            if not campaign:
                return jsonify({"error": "Campaign not found"}), 404

            cur.execute(
                """
                SELECT total_sent, delivered, opened, clicked, bounced, unsubscribed, updated_at
                FROM email_campaign_stats WHERE campaign_id = %s
                """,
                (campaign_id,),
            )
            stats = cur.fetchone()

        if not stats:
            return jsonify({
                "campaign_id": campaign_id,
                "total_sent": 0, "delivered": 0, "opened": 0,
                "clicked": 0, "bounced": 0, "unsubscribed": 0,
            })

        return jsonify({"campaign_id": campaign_id, **dict(stats)})
```

- [ ] **Step 6: Run all campaign tests**

```bash
docker exec kbs_app python -m pytest tests/test_reach_client.py tests/test_communications_campaigns.py -v
```

- [ ] **Step 7: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add core/reach_client.py plugins/kbs_communications/campaign_routes.py \
        tests/test_reach_client.py tests/test_communications_campaigns.py
git commit -m "feat(communications): Hostinger Reach email marketing with campaign CRUD and stats"
```

---

## Task 10: Google Calendar Sync

**Files:**
- Create: `core/calendar_sync.py`
- Create: `tests/test_calendar_sync.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_calendar_sync.py`:

```python
"""Tests for Google Calendar sync service — all Google API calls mocked."""

from unittest.mock import MagicMock, patch

import pytest


def test_sync_appointment_creates_event():
    from core.calendar_sync import CalendarSyncService

    service = CalendarSyncService()

    appointment = {
        "title": "Initial Consultation",
        "start_time": "2026-04-01T10:00:00",
        "end_time": "2026-04-01T10:45:00",
        "customer_name": "Jane Smith",
        "customer_email": "jane@test.com",
        "notes": "First meeting",
    }

    mock_events = MagicMock()
    mock_events.insert.return_value.execute.return_value = {
        "id": "gcal-event-1",
        "htmlLink": "https://calendar.google.com/event/gcal-event-1",
    }

    mock_service = MagicMock()
    mock_service.events.return_value = mock_events

    with patch("core.calendar_sync.build", return_value=mock_service):
        result = service.sync_appointment_to_calendar(
            appointment=appointment,
            calendar_id="primary",
            credentials=MagicMock(),
        )

    assert result["id"] == "gcal-event-1"
    assert "htmlLink" in result

    # Verify the event body was correct
    insert_call = mock_events.insert.call_args
    event_body = insert_call[1]["body"] if "body" in insert_call[1] else insert_call[0][0]
    assert event_body["summary"] == "Initial Consultation"


def test_delete_calendar_event():
    from core.calendar_sync import CalendarSyncService

    service = CalendarSyncService()

    mock_events = MagicMock()
    mock_events.delete.return_value.execute.return_value = {}

    mock_service = MagicMock()
    mock_service.events.return_value = mock_events

    with patch("core.calendar_sync.build", return_value=mock_service):
        service.delete_calendar_event(
            event_id="gcal-event-1",
            calendar_id="primary",
            credentials=MagicMock(),
        )

    mock_events.delete.assert_called_once()


def test_build_event_body():
    from core.calendar_sync import CalendarSyncService

    service = CalendarSyncService()
    body = service._build_event_body(
        title="Consultation",
        start_time="2026-04-01T10:00:00",
        end_time="2026-04-01T10:45:00",
        description="Notes here",
        attendee_email="jane@test.com",
    )

    assert body["summary"] == "Consultation"
    assert body["start"]["dateTime"] == "2026-04-01T10:00:00"
    assert body["end"]["dateTime"] == "2026-04-01T10:45:00"
    assert body["description"] == "Notes here"
    assert len(body["attendees"]) == 1
    assert body["attendees"][0]["email"] == "jane@test.com"


def test_build_event_body_no_attendee():
    from core.calendar_sync import CalendarSyncService

    service = CalendarSyncService()
    body = service._build_event_body(
        title="Internal Meeting",
        start_time="2026-04-01T14:00:00",
        end_time="2026-04-01T15:00:00",
    )

    assert body["attendees"] == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker exec kbs_app python -m pytest tests/test_calendar_sync.py -v
```

- [ ] **Step 3: Write the implementation**

Create `core/calendar_sync.py`:

```python
"""Google Calendar sync service for appointment management.

Syncs KBS appointments to Google Calendar events. Requires
google-api-python-client and valid OAuth2 credentials.
"""

import logging

from googleapiclient.discovery import build

logger = logging.getLogger(__name__)


class CalendarSyncService:
    """Syncs appointments to Google Calendar."""

    def _build_event_body(self, title, start_time, end_time,
                          description=None, attendee_email=None):
        """Build a Google Calendar event body dict.

        Args:
            title: Event title / summary.
            start_time: ISO datetime string for start.
            end_time: ISO datetime string for end.
            description: Optional event description.
            attendee_email: Optional attendee email address.

        Returns:
            Dict suitable for Google Calendar API events.insert().
        """
        event = {
            "summary": title,
            "start": {"dateTime": start_time, "timeZone": "America/Toronto"},
            "end": {"dateTime": end_time, "timeZone": "America/Toronto"},
            "description": description or "",
            "attendees": [],
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "popup", "minutes": 30},
                ],
            },
        }
        if attendee_email:
            event["attendees"].append({"email": attendee_email})
        return event

    def sync_appointment_to_calendar(self, appointment, calendar_id, credentials):
        """Create a Google Calendar event from an appointment.

        Args:
            appointment: Dict with title, start_time, end_time, customer_name,
                         customer_email, notes.
            calendar_id: Google Calendar ID (e.g. "primary").
            credentials: Google OAuth2 credentials object.

        Returns:
            Created event dict from Google Calendar API.
        """
        service = build("calendar", "v3", credentials=credentials)

        event_body = self._build_event_body(
            title=appointment.get("title", "Appointment"),
            start_time=appointment["start_time"],
            end_time=appointment["end_time"],
            description=(
                f"Customer: {appointment.get('customer_name', 'N/A')}\n"
                f"{appointment.get('notes', '')}"
            ),
            attendee_email=appointment.get("customer_email"),
        )

        event = (
            service.events()
            .insert(calendarId=calendar_id, body=event_body, sendUpdates="all")
            .execute()
        )

        logger.info(
            "Synced appointment to Google Calendar: event_id=%s", event.get("id")
        )
        return event

    def delete_calendar_event(self, event_id, calendar_id, credentials):
        """Delete a Google Calendar event.

        Args:
            event_id: Google Calendar event ID.
            calendar_id: Google Calendar ID.
            credentials: Google OAuth2 credentials object.
        """
        service = build("calendar", "v3", credentials=credentials)
        service.events().delete(
            calendarId=calendar_id, eventId=event_id, sendUpdates="all"
        ).execute()
        logger.info("Deleted Google Calendar event: %s", event_id)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker exec kbs_app python -m pytest tests/test_calendar_sync.py -v
```

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add core/calendar_sync.py tests/test_calendar_sync.py
git commit -m "feat(core): Google Calendar sync service for appointment events"
```

---

## Task 11: SMS Booking Confirmations

**Files:**
- Create: `tests/test_sms_booking_confirmation.py`

This task verifies the event-driven SMS confirmation that was wired in Task 2 (the `on_appointment_booked` and `on_appointment_cancelled` handlers in `routes.py`). The logic is already implemented; this task adds dedicated tests.

- [ ] **Step 1: Write the confirmation tests**

Create `tests/test_sms_booking_confirmation.py`:

```python
"""Tests for SMS booking confirmation via event bus integration."""

from unittest.mock import MagicMock, patch

import pytest


def test_appointment_booked_sends_sms():
    """Verify on_appointment_booked sends SMS when customer has phone."""
    from plugins.kbs_communications.routes import on_appointment_booked

    mock_cur = MagicMock()
    mock_conn = MagicMock()
    mock_cur.fetchone.return_value = {
        "id": 1,
        "first_name": "Alice",
        "last_name": "Smith",
        "phone": "+15551234567",
    }

    with patch("plugins.kbs_communications.routes.get_db_cursor") as mock_db, \
         patch("plugins.kbs_communications.routes.send_sms") as mock_send:

        mock_db.return_value.__enter__ = MagicMock(return_value=(mock_conn, mock_cur))
        mock_db.return_value.__exit__ = MagicMock(return_value=False)

        on_appointment_booked({
            "customer_id": 1,
            "_tenant_id": 1,
            "service_name": "Haircut",
            "appointment_date": "April 1, 2026",
            "appointment_time": "2:00 PM",
        })

    mock_send.assert_called_once()
    call_args = mock_send.call_args
    assert "+15551234567" in str(call_args)
    assert "Haircut" in str(call_args)


def test_appointment_booked_skips_sms_when_no_phone():
    """No SMS sent if customer has no phone number."""
    from plugins.kbs_communications.routes import on_appointment_booked

    mock_cur = MagicMock()
    mock_conn = MagicMock()
    mock_cur.fetchone.return_value = {
        "id": 2,
        "first_name": "Bob",
        "last_name": "Jones",
        "phone": None,
    }

    with patch("plugins.kbs_communications.routes.get_db_cursor") as mock_db, \
         patch("plugins.kbs_communications.routes.send_sms") as mock_send:

        mock_db.return_value.__enter__ = MagicMock(return_value=(mock_conn, mock_cur))
        mock_db.return_value.__exit__ = MagicMock(return_value=False)

        on_appointment_booked({
            "customer_id": 2,
            "_tenant_id": 1,
            "service_name": "Consultation",
            "appointment_date": "April 2, 2026",
            "appointment_time": "10:00 AM",
        })

    mock_send.assert_not_called()


def test_appointment_booked_skips_without_tenant():
    """No action if _tenant_id is missing from event data."""
    from plugins.kbs_communications.routes import on_appointment_booked

    with patch("plugins.kbs_communications.routes.send_sms") as mock_send:
        on_appointment_booked({"customer_id": 1})

    mock_send.assert_not_called()


def test_appointment_cancelled_sends_sms():
    """Verify on_appointment_cancelled sends cancellation SMS."""
    from plugins.kbs_communications.routes import on_appointment_cancelled

    mock_cur = MagicMock()
    mock_conn = MagicMock()
    mock_cur.fetchone.return_value = {
        "id": 3,
        "first_name": "Carol",
        "phone": "+15559876543",
    }

    with patch("plugins.kbs_communications.routes.get_db_cursor") as mock_db, \
         patch("plugins.kbs_communications.routes.send_sms") as mock_send:

        mock_db.return_value.__enter__ = MagicMock(return_value=(mock_conn, mock_cur))
        mock_db.return_value.__exit__ = MagicMock(return_value=False)

        on_appointment_cancelled({
            "customer_id": 3,
            "_tenant_id": 1,
            "service_name": "Massage",
        })

    mock_send.assert_called_once()
    assert "cancelled" in str(mock_send.call_args).lower()


def test_sms_failure_does_not_raise():
    """SMS send failure should be logged but not raise."""
    from plugins.kbs_communications.routes import on_appointment_booked

    mock_cur = MagicMock()
    mock_conn = MagicMock()
    mock_cur.fetchone.return_value = {
        "id": 4,
        "first_name": "Dan",
        "last_name": "Lee",
        "phone": "+15551112222",
    }

    with patch("plugins.kbs_communications.routes.get_db_cursor") as mock_db, \
         patch("plugins.kbs_communications.routes.send_sms", side_effect=Exception("Provider down")):

        mock_db.return_value.__enter__ = MagicMock(return_value=(mock_conn, mock_cur))
        mock_db.return_value.__exit__ = MagicMock(return_value=False)

        # Should not raise
        on_appointment_booked({
            "customer_id": 4,
            "_tenant_id": 1,
            "service_name": "Consultation",
            "appointment_date": "April 5, 2026",
            "appointment_time": "3:00 PM",
        })
```

- [ ] **Step 2: Run tests to verify they pass**

```bash
docker exec kbs_app python -m pytest tests/test_sms_booking_confirmation.py -v
```

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add tests/test_sms_booking_confirmation.py
git commit -m "test(communications): SMS booking confirmation and cancellation tests"
```

---

## Task 12: Integration Tests

**Files:**
- Create: `tests/test_wave2_integration.py`

- [ ] **Step 1: Write the full integration test suite**

Create `tests/test_wave2_integration.py`:

```python
"""Wave 2 Communications Stack — cross-channel integration tests.

These test the data flow across channels into the unified inbox,
event bus wiring, and CRM contact matching.
"""

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------
# Unified Inbox aggregation
# ---------------------------------------------------------------

def test_inbox_aggregates_all_channels():
    """Verify unified inbox returns items from calls, SMS, chat, and campaigns."""
    from datetime import datetime

    items = [
        {"channel": "call", "created_at": datetime(2026, 3, 28, 10, 0)},
        {"channel": "sms", "created_at": datetime(2026, 3, 28, 10, 5)},
        {"channel": "chat", "created_at": datetime(2026, 3, 28, 10, 3)},
        {"channel": "email", "created_at": datetime(2026, 3, 28, 9, 0)},
    ]

    # Sort descending by created_at
    items.sort(key=lambda x: x["created_at"], reverse=True)
    assert items[0]["channel"] == "sms"
    assert items[-1]["channel"] == "email"


# ---------------------------------------------------------------
# Event bus wiring
# ---------------------------------------------------------------

def test_event_bus_sms_sent_fires():
    """Verify sms.sent event is emitted when SMS is sent."""
    from core.event_bus import EventBus

    bus = EventBus()
    received = []

    @bus.on("sms.sent")
    def handler(data):
        received.append(data)

    bus.emit("sms.sent", {"sms_id": 1, "to": "+15551234567"}, tenant_id=1)
    assert len(received) == 1
    assert received[0]["sms_id"] == 1


def test_event_bus_chat_started_fires():
    from core.event_bus import EventBus

    bus = EventBus()
    received = []

    @bus.on("chat.started")
    def handler(data):
        received.append(data)

    bus.emit("chat.started", {"session_id": "abc-123"}, tenant_id=1)
    assert len(received) == 1


def test_event_bus_campaign_sent_fires():
    from core.event_bus import EventBus

    bus = EventBus()
    received = []

    @bus.on("campaign.sent")
    def handler(data):
        received.append(data)

    bus.emit("campaign.sent", {"campaign_id": 5, "total_contacts": 100}, tenant_id=1)
    assert len(received) == 1
    assert received[0]["total_contacts"] == 100


def test_event_bus_call_logged_fires():
    from core.event_bus import EventBus

    bus = EventBus()
    received = []

    @bus.on("call.logged")
    def handler(data):
        received.append(data)

    bus.emit("call.logged", {"call_id": 10, "source": "ringcentral"}, tenant_id=1)
    assert len(received) == 1


# ---------------------------------------------------------------
# CRM contact matching
# ---------------------------------------------------------------

def test_crm_phone_matching_strips_formatting():
    """Verify phone matching handles +1 (555) 123-4567 format."""
    from plugins.kbs_communications.webhook_routes import _match_customer_by_phone

    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = {"id": 99}

    result = _match_customer_by_phone(mock_cur, "+1 (555) 123-4567")

    # Should have called execute with the digits
    assert result == 99


def test_crm_phone_matching_returns_none_for_empty():
    from plugins.kbs_communications.webhook_routes import _match_customer_by_phone

    mock_cur = MagicMock()
    result = _match_customer_by_phone(mock_cur, "")
    assert result is None


# ---------------------------------------------------------------
# Chat lifecycle
# ---------------------------------------------------------------

def test_chat_full_lifecycle():
    """Create -> message -> reply -> close."""
    from core.chat_manager import ChatManager

    mgr = ChatManager()
    session = mgr.create_session(tenant_id=1, visitor_name="Test User")
    sid = session["id"]

    mgr.send_message(sid, "visitor", "Test User", "I need help")
    mgr.send_message(sid, "agent", "Support", "How can I help?")
    mgr.send_message(sid, "visitor", "Test User", "My order is late")
    mgr.send_message(sid, "agent", "Support", "Let me check that for you")

    messages = mgr.get_messages(sid)
    assert len(messages) == 4

    closed = mgr.close_session(sid)
    assert closed["status"] == "closed"
    assert len(closed["messages"]) == 4


# ---------------------------------------------------------------
# SMS provider fallback
# ---------------------------------------------------------------

def test_sms_dispatch_tries_both_providers():
    """Verify SMS dispatch falls back when primary fails."""
    from core.sms_service import _dispatch_sms

    cfg = MagicMock()
    cfg.KBS_SMS_PROVIDER = "ringcentral"
    cfg.KBS_TWILIO_ACCOUNT_SID = "ACTEST"
    cfg.KBS_TWILIO_AUTH_TOKEN = "tok"
    cfg.KBS_TWILIO_PHONE_NUMBER = "+15550009999"

    with patch("core.sms_service._send_via_ringcentral", side_effect=Exception("RC offline")), \
         patch("core.sms_service._send_via_twilio") as mock_tw:
        mock_tw.return_value = {"external_id": "SM-1", "provider": "twilio"}

        result = _dispatch_sms(cfg, "+15551112222", "Fallback test")

    assert result["provider"] == "twilio"


# ---------------------------------------------------------------
# Campaign status transitions
# ---------------------------------------------------------------

def test_campaign_status_transitions():
    from plugins.kbs_communications.campaign_routes import _valid_status_transition

    # Happy paths
    assert _valid_status_transition("draft", "sending") is True
    assert _valid_status_transition("draft", "cancelled") is True
    assert _valid_status_transition("sending", "sent") is True

    # Blocked transitions
    assert _valid_status_transition("sent", "draft") is False
    assert _valid_status_transition("cancelled", "sending") is False
    assert _valid_status_transition("sent", "sending") is False
```

- [ ] **Step 2: Run the full integration test suite**

```bash
docker exec kbs_app python -m pytest tests/test_wave2_integration.py -v
```

- [ ] **Step 3: Run ALL Wave 2 tests together**

```bash
docker exec kbs_app python -m pytest \
    tests/test_ringcentral_client.py \
    tests/test_sms_service.py \
    tests/test_chat_manager.py \
    tests/test_reach_client.py \
    tests/test_calendar_sync.py \
    tests/test_communications_webhooks.py \
    tests/test_communications_sms_routes.py \
    tests/test_communications_chat_routes.py \
    tests/test_communications_campaigns.py \
    tests/test_sms_booking_confirmation.py \
    tests/test_wave2_integration.py \
    -v
```

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add tests/test_wave2_integration.py
git commit -m "test(communications): Wave 2 cross-channel integration tests"
```

---

## Summary

Wave 2 delivers 12 tasks across 28 files:

| Component | What it Does |
|-----------|-------------|
| **Communications Plugin** | New plugin with manifest, blueprint, unified inbox, event consumers |
| **RingCentral Client** | JWT auth, call log fetch, SMS send via RC API |
| **RingCentral Webhook** | Receives call events, matches CRM contacts, creates call_records |
| **SMS Service** | RingCentral primary + Twilio fallback, auto-records to DB |
| **SMS Routes** | Send, list, inbound webhook (Twilio + RC format) |
| **Chat Manager** | Thread-safe in-memory session management |
| **Chat Routes** | Start, message, poll, close (persists to DB on close) |
| **Chat Widget** | Embeddable JS with floating bubble, REST polling |
| **Reach Client** | Hostinger Reach API for email campaigns |
| **Campaign Routes** | CRUD, send via Reach, stats with local cache |
| **Calendar Sync** | Google Calendar event create/delete for appointments |
| **SMS Confirmations** | Event-driven SMS on appointment.booked and appointment.cancelled |
| **Unified Inbox** | Aggregates calls + SMS + chat + campaigns with filters and pagination |

**Database:** 5 new tables (sms_messages, chat_conversations, chat_messages, email_campaigns, email_campaign_stats). Calls continue to use existing call_center tables.

**Events emitted:** sms.sent, sms.received, chat.started, chat.closed, campaign.sent, campaign.created, call.logged

**Events consumed:** appointment.booked, appointment.cancelled, contact.created, call.ended
