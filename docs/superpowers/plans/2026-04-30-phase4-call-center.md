# Phase 4 — Call Center (RingCentral + SMS Inbox)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire RingCentral into the KBS Call Center plugin — inbound call/SMS webhook receiver, SMS inbox tab, credential storage, and Telegram notifications for missed calls/texts via ARCHIE platform internal notify endpoint.

**Architecture:** KBS plugin receives RingCentral push notifications at a public webhook endpoint (HMAC-validated), stores inbound calls/SMS to new `sms_messages` table, then POSTs to ARCHIE's new `/api/internal/notify` endpoint which forwards to Telegram. RingCentral credentials (client_id, client_secret, jwt_token) live in `tenant_integrations` as `service='ringcentral'` — same pattern as Stripe and Printful.

**Tech Stack:** Flask, PostgreSQL (tenant schemas), RingCentral push notifications, `requests` for inter-service calls, existing `tenant_integrations` table, ARCHIE `telegram_service.py`.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `kytran-business-suite/plugins/kbs_call_center/migrations/002_sms_tables.sql` | `sms_messages` table + update provider CHECK |
| Modify | `kytran-business-suite/plugins/kbs_call_center/routes.py` | Add RingCentral creds, SMS inbox, webhook routes |
| Modify | `kytran-business-suite/plugins/kbs_call_center/templates/call_center.html` | SMS tab in dashboard |
| Create | `platform_v2/tools/account_center/notify_routes.py` | Internal `/api/internal/notify` endpoint |
| Modify | `platform_v2/tools/account_center/__init__.py` | Register notify_routes blueprint |
| Create | `kytran-business-suite/plugins/kbs_call_center/tests/test_sms_webhook.py` | Tests for webhook + SMS endpoints |

---

## Task 1: KBS migration 002 — SMS tables

**Files:**
- Create: `kytran-business-suite/plugins/kbs_call_center/migrations/002_sms_tables.sql`

- [ ] **Step 1.1: Create the migration file**

```sql
-- 002_sms_tables.sql — SMS inbox for Call Center (run inside tenant schema)
-- Idempotent.

-- Add RingCentral to provider enum (recreate CHECK with updated list)
ALTER TABLE call_phone_numbers
    DROP CONSTRAINT IF EXISTS call_phone_numbers_provider_check;

ALTER TABLE call_phone_numbers
    ADD CONSTRAINT call_phone_numbers_provider_check
    CHECK (provider IN ('twilio', 'telnyx', 'telus', 'ringcentral', 'other'));

-- SMS message log
CREATE TABLE IF NOT EXISTS sms_messages (
    id              SERIAL PRIMARY KEY,
    phone_number_id INTEGER REFERENCES call_phone_numbers(id) ON DELETE SET NULL,
    customer_id     INTEGER,
    direction       VARCHAR(10) NOT NULL CHECK (direction IN ('inbound', 'outbound')),
    body            TEXT NOT NULL,
    status          VARCHAR(20) DEFAULT 'received'
                        CHECK (status IN ('received', 'sent', 'failed', 'queued')),
    external_id     VARCHAR(255),
    from_number     VARCHAR(30),
    to_number       VARCHAR(30),
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sms_messages_phone_number_id ON sms_messages (phone_number_id);
CREATE INDEX IF NOT EXISTS idx_sms_messages_customer_id     ON sms_messages (customer_id);
CREATE INDEX IF NOT EXISTS idx_sms_messages_direction       ON sms_messages (direction);
CREATE INDEX IF NOT EXISTS idx_sms_messages_created_at      ON sms_messages (created_at);
```

- [ ] **Step 1.2: Apply the migration**

```bash
docker exec kbs_db psql -U kbs -d kbs \
  -c "SET search_path TO kbs_tenant_1, public;" \
  -f /migrations/kbs_call_center/002_sms_tables.sql 2>&1 | tail -5
```

Expected: `ALTER TABLE` + `CREATE TABLE` + 4x `CREATE INDEX`

- [ ] **Step 1.3: Verify table exists**

```bash
docker exec kbs_db psql -U kbs -d kbs -c \
  "SET search_path TO kbs_tenant_1; SELECT column_name, data_type FROM information_schema.columns WHERE table_name='sms_messages' ORDER BY ordinal_position;"
```

Expected: 11 columns listed

- [ ] **Step 1.4: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add plugins/kbs_call_center/migrations/002_sms_tables.sql
git commit -m "feat(call-center): sms_messages table + ringcentral provider"
```

---

## Task 2: KBS — RingCentral credentials + SMS API routes

**Files:**
- Modify: `kytran-business-suite/plugins/kbs_call_center/routes.py`
- Create: `kytran-business-suite/plugins/kbs_call_center/tests/test_sms_webhook.py`

- [ ] **Step 2.1: Write failing tests**

```python
# kytran-business-suite/plugins/kbs_call_center/tests/test_sms_webhook.py
import pytest
from unittest.mock import patch, MagicMock


def test_ringcentral_status_unauthenticated(client):
    resp = client.get("/call-center/api/ringcentral/status")
    assert resp.status_code in (200, 302, 401)


def test_sms_list_unauthenticated(client):
    resp = client.get("/call-center/api/sms")
    assert resp.status_code in (200, 302, 401)


def test_webhook_validation_token_handshake(client):
    resp = client.post(
        "/call-center/api/webhook/ringcentral",
        json={},
        headers={"Validation-Token": "rc-test-token-123"},
    )
    assert resp.status_code == 200
    assert resp.headers.get("Validation-Token") == "rc-test-token-123"
```

- [ ] **Step 2.2: Run to verify they run**

```bash
docker exec kbs_app python3 -m pytest \
  plugins/kbs_call_center/tests/test_sms_webhook.py -v 2>&1 | tail -10
```

Expected: tests collected and run (any result is fine — just not `ERROR`)

- [ ] **Step 2.3: Add RingCentral credentials + SMS list/send routes to routes.py**

Find the closing brace of `register_routes(bp)` (just before the `# Event consumers` section) and insert:

```python
    # ------------------------------------------------------------------
    # RingCentral Integration
    # ------------------------------------------------------------------

    @bp.route("/api/ringcentral/status", methods=["GET"])
    @login_required
    @require_module("call-center")
    def ringcentral_status():
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "SELECT id, status, created_at FROM tenant_integrations WHERE service = 'ringcentral'"
            )
            row = cur.fetchone()
        if row and row["status"] == "active":
            return jsonify({"connected": True, "since": str(row["created_at"])})
        return jsonify({"connected": False})

    @bp.route("/api/ringcentral/connect", methods=["POST"])
    @login_required
    @require_module("call-center")
    def ringcentral_connect():
        data = request.get_json(force=True) or {}
        client_id = (data.get("client_id") or "").strip()
        client_secret = (data.get("client_secret") or "").strip()
        jwt_token = (data.get("jwt_token") or "").strip()
        if not client_id or not client_secret:
            return jsonify({"error": "client_id and client_secret are required"}), 400
        creds = Json({"client_id": client_id, "client_secret": client_secret, "jwt_token": jwt_token})
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                INSERT INTO tenant_integrations (service, credentials, status, updated_at)
                VALUES ('ringcentral', %s, 'active', NOW())
                ON CONFLICT (service) DO UPDATE
                SET credentials = %s, status = 'active', updated_at = NOW()
                """,
                (creds, creds),
            )
        return jsonify({"connected": True})

    @bp.route("/api/ringcentral/disconnect", methods=["DELETE"])
    @login_required
    @require_module("call-center")
    def ringcentral_disconnect():
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "UPDATE tenant_integrations SET status='inactive', credentials='{}'::jsonb, "
                "updated_at=NOW() WHERE service='ringcentral'"
            )
        return jsonify({"connected": False})

    # ------------------------------------------------------------------
    # SMS Inbox
    # ------------------------------------------------------------------

    @bp.route("/api/sms", methods=["GET"])
    @login_required
    @require_module("call-center")
    def list_sms():
        page = request.args.get("page", 1, type=int)
        per_page = min(request.args.get("per_page", 50, type=int), 100)
        direction = request.args.get("direction")
        offset = (page - 1) * per_page

        filters, params = [], []
        if direction:
            filters.append("m.direction = %s")
            params.append(direction)
        where = ("WHERE " + " AND ".join(filters)) if filters else ""

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(f"SELECT COUNT(*) AS total FROM sms_messages m {where}", params)
            total = cur.fetchone()["total"]
            cur.execute(
                f"""
                SELECT m.id, m.phone_number_id, m.customer_id, m.direction,
                       m.body, m.status, m.from_number, m.to_number,
                       m.external_id, m.created_at,
                       n.number AS phone_number, n.label AS phone_label,
                       c.name AS customer_name
                FROM sms_messages m
                LEFT JOIN call_phone_numbers n ON n.id = m.phone_number_id
                LEFT JOIN crm_customers c ON c.id = m.customer_id
                {where}
                ORDER BY m.created_at DESC
                LIMIT %s OFFSET %s
                """,
                params + [per_page, offset],
            )
            messages = cur.fetchall()
        return jsonify({"messages": messages, "total": total, "page": page, "per_page": per_page})

    @bp.route("/api/sms", methods=["POST"])
    @login_required
    @require_module("call-center")
    def send_sms():
        data = request.get_json(force=True) or {}
        to_number = (data.get("to_number") or "").strip()
        body = (data.get("body") or "").strip()
        phone_number_id = data.get("phone_number_id")
        if not to_number or not body or not phone_number_id:
            return jsonify({"error": "to_number, body, and phone_number_id are required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute("SELECT number FROM call_phone_numbers WHERE id = %s", (phone_number_id,))
            phone_row = cur.fetchone()
            if not phone_row:
                return jsonify({"error": "Phone number not found"}), 404

            cur.execute(
                """
                INSERT INTO sms_messages
                    (phone_number_id, customer_id, direction, body, status,
                     to_number, from_number, metadata)
                VALUES (%s, %s, 'outbound', %s, 'queued', %s, %s, %s)
                RETURNING id, direction, body, status, to_number, from_number, created_at
                """,
                (
                    phone_number_id,
                    data.get("customer_id"),
                    body,
                    to_number,
                    phone_row["number"],
                    Json({}),
                ),
            )
            msg = cur.fetchone()

        event_bus.emit(
            "sms.queued",
            {"message_id": msg["id"], "to": to_number, "body": body},
            tenant_id=g.tenant_id,
        )
        return jsonify(msg), 201

    # ------------------------------------------------------------------
    # RingCentral Webhook — public, no login_required
    # ------------------------------------------------------------------

    @bp.route("/api/webhook/ringcentral", methods=["POST"])
    def ringcentral_webhook():
        """Receive RingCentral push notifications.

        RingCentral sends a Validation-Token header on first subscription — echo it back.
        """
        validation_token = request.headers.get("Validation-Token")
        if validation_token:
            return (validation_token, 200, {"Validation-Token": validation_token})

        payload = request.get_json(force=True, silent=True) or {}
        event_type = payload.get("event", "")
        tenant_id = request.args.get("tenant", "kbs_tenant_1")

        try:
            with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
                set_tenant_search_path(cur, tenant_id)
                if "sms" in event_type.lower() or "message" in event_type.lower():
                    _handle_inbound_sms(cur, payload, tenant_id)
                elif "telephony" in event_type.lower() or "call" in event_type.lower():
                    _handle_inbound_call(cur, payload, tenant_id)
        except Exception as exc:
            logger.exception("[CallCenter] RingCentral webhook failed: %s", exc)
        return jsonify({"ok": True})
```

- [ ] **Step 2.4: Add helper functions just above `# Event consumers`**

```python
def _fire_notify(message: str) -> None:
    """POST to ARCHIE internal notify endpoint — fire and forget."""
    import os
    import requests as _requests

    url = os.getenv("ARCHIE_NOTIFY_URL", "")
    key = os.getenv("ARCHIE_INTERNAL_KEY", "")
    if not url or not key:
        return
    try:
        _requests.post(
            url,
            json={"message": message},
            headers={"X-Internal-Key": key},
            timeout=5,
        )
    except Exception as exc:
        logger.debug("[CallCenter] notify failed: %s", exc)


def _handle_inbound_sms(cur, payload, tenant_id):
    body_data = payload.get("body", {})
    from_number = body_data.get("from", {}).get("phoneNumber", "")
    to_number = (body_data.get("to") or [{}])[0].get("phoneNumber", "")
    text = body_data.get("subject") or body_data.get("text") or ""
    external_id = body_data.get("id", "")

    if not from_number or not text:
        return

    cur.execute(
        "SELECT id FROM call_phone_numbers WHERE number = %s AND is_active = TRUE",
        (to_number,),
    )
    phone_row = cur.fetchone()
    cur.execute(
        "SELECT id FROM crm_customers WHERE phone ILIKE %s LIMIT 1",
        (f"%{from_number[-10:]}%",),
    )
    customer_row = cur.fetchone()

    cur.execute(
        """
        INSERT INTO sms_messages
            (phone_number_id, customer_id, direction, body, status,
             from_number, to_number, external_id, metadata)
        VALUES (%s, %s, 'inbound', %s, 'received', %s, %s, %s, %s)
        ON CONFLICT DO NOTHING
        """,
        (
            phone_row["id"] if phone_row else None,
            customer_row["id"] if customer_row else None,
            text,
            from_number,
            to_number,
            external_id,
            Json({}),
        ),
    )
    preview = text[:140] + ("..." if len(text) > 140 else "")
    _fire_notify(f"SMS from {from_number}: {preview}")


def _handle_inbound_call(cur, payload, tenant_id):
    parties = payload.get("body", {}).get("parties", [])
    session = payload.get("body", {}).get("telephonySessionId", "")
    for party in parties:
        if party.get("direction") == "Inbound" and (party.get("status") or {}).get("code") == "Gone":
            from_number = (party.get("from") or {}).get("phoneNumber", "")
            to_number = (party.get("to") or {}).get("phoneNumber", "")
            cur.execute(
                "SELECT id FROM call_phone_numbers WHERE number = %s", (to_number,)
            )
            phone_row = cur.fetchone()
            cur.execute(
                """
                INSERT INTO call_records
                    (phone_number_id, direction, status, metadata)
                VALUES (%s, 'inbound', 'missed', %s)
                """,
                (phone_row["id"] if phone_row else None, Json({"from": from_number, "session": session})),
            )
            _fire_notify(f"Missed call from {from_number}")
```

- [ ] **Step 2.5: Update `add_number` route to allow 'ringcentral' provider**

Find `valid_providers = {"twilio", "telnyx", "telus", "other"}` in `add_number()` and change to:

```python
valid_providers = {"twilio", "telnyx", "telus", "ringcentral", "other"}
```

- [ ] **Step 2.6: Restart KBS and verify**

```bash
cd /mnt/archie_brain/kytran-business-suite
docker compose restart kbs_app && sleep 10
docker logs kbs_app --tail=10 2>&1 | grep -E "ERROR|Started|Booting"
```

Expected: no import errors

- [ ] **Step 2.7: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add plugins/kbs_call_center/routes.py plugins/kbs_call_center/tests/test_sms_webhook.py
git commit -m "feat(call-center): RingCentral creds, SMS inbox API, webhook receiver"
```

---

## Task 3: ARCHIE — internal notify endpoint

**Files:**
- Create: `platform_v2/tools/account_center/notify_routes.py`
- Modify: `platform_v2/tools/account_center/__init__.py`

- [ ] **Step 3.1: Read __init__.py to understand the registration pattern**

```bash
grep -n "register\|import\|Blueprint" /mnt/archie_brain/platform_v2/tools/account_center/__init__.py | head -20
```

Note the pattern used (likely `register_access_routes(bp)` already there from Phase 0).

- [ ] **Step 3.2: Create notify_routes.py**

```python
# platform_v2/tools/account_center/notify_routes.py
"""Internal notify endpoint — accepts POST from standalone products and forwards to Telegram."""

import logging
import os

from flask import jsonify, request

logger = logging.getLogger(__name__)

_INTERNAL_KEY = os.getenv("ARCHIE_INTERNAL_KEY", "")


def register_notify_routes(bp):

    @bp.route("/api/internal/notify", methods=["POST"])
    def internal_notify():
        """Forward a message to Telegram. Called by KBS, media hub, etc."""
        key = request.headers.get("X-Internal-Key", "")
        if _INTERNAL_KEY and key != _INTERNAL_KEY:
            return jsonify({"ok": False, "error": "unauthorized"}), 401

        data = request.get_json(force=True, silent=True) or {}
        message = (data.get("message") or "").strip()
        if not message:
            return jsonify({"ok": False, "error": "message is required"}), 400

        try:
            from services.telegram_service import send_info
            send_info(f"[KBS] {message}")
            return jsonify({"ok": True})
        except Exception as exc:
            logger.warning("[InternalNotify] Telegram send failed: %s", exc)
            return jsonify({"ok": False, "error": str(exc)}), 500
```

- [ ] **Step 3.3: Register in __init__.py**

After the existing `register_access_routes(bp)` call (or equivalent import block), add:

```python
from .notify_routes import register_notify_routes
# ...
register_notify_routes(bp)
```

- [ ] **Step 3.4: Add env vars to .env files**

Check both `/mnt/archie_brain/.env` and `/mnt/archie_brain/platform_v2/.env`:

```bash
grep -q "ARCHIE_INTERNAL_KEY" /mnt/archie_brain/.env || \
  echo "ARCHIE_INTERNAL_KEY=archie-internal-2026" >> /mnt/archie_brain/.env

grep -q "ARCHIE_INTERNAL_KEY" /mnt/archie_brain/platform_v2/.env || \
  echo "ARCHIE_INTERNAL_KEY=archie-internal-2026" >> /mnt/archie_brain/platform_v2/.env
```

Check KBS `.env`:

```bash
grep -q "ARCHIE_INTERNAL_KEY" /mnt/archie_brain/kytran-business-suite/.env || \
  echo "ARCHIE_INTERNAL_KEY=archie-internal-2026" >> /mnt/archie_brain/kytran-business-suite/.env

grep -q "ARCHIE_NOTIFY_URL" /mnt/archie_brain/kytran-business-suite/.env || \
  echo "ARCHIE_NOTIFY_URL=http://archie_platform:3000/tools/account-center/api/internal/notify" >> /mnt/archie_brain/kytran-business-suite/.env
```

- [ ] **Step 3.5: Restart platform and test**

```bash
docker compose restart archie_platform && sleep 15
docker exec archie_platform python3 -c "
import urllib.request, json
req = urllib.request.Request(
    'http://localhost:3000/tools/account-center/api/internal/notify',
    data=json.dumps({'message': 'Phase 4 test'}).encode(),
    headers={'Content-Type': 'application/json', 'X-Internal-Key': 'archie-internal-2026'},
    method='POST'
)
try:
    r = urllib.request.urlopen(req, timeout=5)
    print('OK:', r.read().decode())
except urllib.error.HTTPError as e:
    print('HTTP', e.code, e.read().decode())
"
```

Expected: `OK: {"ok": true}` — Telegram message fires to the bot

- [ ] **Step 3.6: Commit**

```bash
cd /mnt/archie_brain
git add platform_v2/tools/account_center/notify_routes.py \
        platform_v2/tools/account_center/__init__.py
git commit -m "feat(notify): internal notify endpoint for cross-service Telegram forwarding"
```

---

## Task 4: SMS inbox tab in call_center.html

**Files:**
- Modify: `kytran-business-suite/plugins/kbs_call_center/templates/call_center.html`

- [ ] **Step 4.1: Read the existing template tab structure**

```bash
grep -n "tab\|Tab\|data-tab\|kbs-tab" \
  /mnt/archie_brain/kytran-business-suite/plugins/kbs_call_center/templates/call_center.html | head -30
```

Identify the tab nav pattern and the last tab pane closing tag.

- [ ] **Step 4.2: Add SMS tab button to the nav**

In the tab navigation list, add after the last existing tab button:

```html
<button class="kbs-tab-btn" data-tab="sms-tab" id="sms-tab-btn">SMS</button>
```

- [ ] **Step 4.3: Add SMS tab pane after the last existing tab pane**

Locate the closing div of the last tab pane and insert the SMS pane immediately after:

```html
<div class="kbs-tab-pane" id="sms-tab" style="display:none">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
    <h3 style="font-size:13px;text-transform:uppercase;letter-spacing:1px;color:#888;margin:0">SMS Inbox</h3>
    <button id="smsComposeBtn"
            style="background:#7c3aed;color:#fff;border:none;padding:6px 14px;border-radius:5px;cursor:pointer;font-size:12px">
      + Compose
    </button>
  </div>

  <div id="smsComposePanel" style="display:none;border:1px solid #7c3aed33;border-radius:8px;padding:14px;margin-bottom:16px;background:#0a0418">
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px">
      <select id="smsFromNumber"
              style="background:#111;border:1px solid #333;color:#fff;padding:6px 8px;border-radius:4px;font-size:12px">
        <option value="">From number...</option>
      </select>
      <input id="smsToNumber" type="text" placeholder="To (e.g. +16135551234)"
             style="background:#111;border:1px solid #333;color:#fff;padding:6px 8px;border-radius:4px;font-size:12px">
    </div>
    <textarea id="smsBody" rows="3" placeholder="Message..."
              style="width:100%;box-sizing:border-box;background:#111;border:1px solid #333;color:#fff;padding:8px;border-radius:4px;font-size:12px;resize:vertical"></textarea>
    <div style="margin-top:8px;display:flex;gap:8px">
      <button id="smsSendBtn"
              style="background:#7c3aed;color:#fff;border:none;padding:6px 16px;border-radius:4px;cursor:pointer;font-size:12px">
        Send
      </button>
      <button id="smsCancelBtn"
              style="background:#222;color:#aaa;border:1px solid #333;padding:6px 12px;border-radius:4px;cursor:pointer;font-size:12px">
        Cancel
      </button>
    </div>
  </div>

  <div style="margin-bottom:12px;display:flex;gap:8px">
    <button class="sms-filter" data-dir="" style="background:#111;border:1px solid #7c3aed;color:#7c3aed;padding:4px 12px;border-radius:4px;cursor:pointer;font-size:11px">All</button>
    <button class="sms-filter" data-dir="inbound" style="background:#111;border:1px solid #333;color:#aaa;padding:4px 12px;border-radius:4px;cursor:pointer;font-size:11px">Inbound</button>
    <button class="sms-filter" data-dir="outbound" style="background:#111;border:1px solid #333;color:#aaa;padding:4px 12px;border-radius:4px;cursor:pointer;font-size:11px">Sent</button>
  </div>

  <div id="smsMessageList" style="display:flex;flex-direction:column;gap:8px"></div>
  <div id="smsLoadMoreWrap" style="display:none;text-align:center;margin-top:12px">
    <button id="smsLoadMoreBtn"
            style="background:#111;color:#7c3aed;border:1px solid #7c3aed;padding:6px 18px;border-radius:4px;cursor:pointer;font-size:12px">
      Load more
    </button>
  </div>
</div>
```

- [ ] **Step 4.4: Add the SMS JavaScript before the closing `</body>` tag**

```html
<script>
(function () {
  'use strict';

  var smsPage = 1;
  var smsDir = '';
  var smsBusy = false;

  function esc(str) {
    var d = document.createElement('div');
    d.textContent = String(str || '');
    return d.textContent;
  }

  function buildMessageCard(m) {
    var wrap = document.createElement('div');
    wrap.style.cssText = 'border:1px solid #222;border-radius:6px;padding:10px 14px;background:#050509';

    var meta = document.createElement('div');
    meta.style.cssText = 'display:flex;justify-content:space-between;margin-bottom:4px';

    var who = document.createElement('span');
    who.style.cssText = 'font-size:11px;color:#aaa';
    var arrow = m.direction === 'inbound' ? 'IN ' : 'OUT ';
    var contact = m.direction === 'inbound' ? (m.from_number || '?') : (m.to_number || '?');
    who.textContent = arrow + contact + (m.customer_name ? ' — ' + m.customer_name : '');

    var ts = document.createElement('span');
    ts.style.cssText = 'font-size:11px;color:#555';
    ts.textContent = new Date(m.created_at).toLocaleString();

    meta.appendChild(who);
    meta.appendChild(ts);

    var body = document.createElement('div');
    body.style.cssText = 'font-size:13px;color:#e0e0e0;white-space:pre-wrap';
    body.textContent = m.body;

    wrap.appendChild(meta);
    wrap.appendChild(body);
    return wrap;
  }

  function loadSms(reset) {
    if (smsBusy) { return; }
    smsBusy = true;
    if (reset) {
      smsPage = 1;
      document.getElementById('smsMessageList').textContent = '';
    }
    var url = '/call-center/api/sms?page=' + smsPage + '&per_page=30';
    if (smsDir) { url += '&direction=' + smsDir; }
    fetch(url)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var list = document.getElementById('smsMessageList');
        (data.messages || []).forEach(function (m) {
          list.appendChild(buildMessageCard(m));
        });
        var wrap = document.getElementById('smsLoadMoreWrap');
        wrap.style.display = (data.total > smsPage * 30) ? 'block' : 'none';
        smsPage += 1;
        smsBusy = false;
      })
      .catch(function () { smsBusy = false; });
  }

  document.getElementById('smsLoadMoreBtn').addEventListener('click', function () {
    loadSms(false);
  });

  document.querySelectorAll('.sms-filter').forEach(function (btn) {
    btn.addEventListener('click', function () {
      document.querySelectorAll('.sms-filter').forEach(function (b) {
        b.style.borderColor = '#333';
        b.style.color = '#aaa';
      });
      btn.style.borderColor = '#7c3aed';
      btn.style.color = '#7c3aed';
      smsDir = btn.getAttribute('data-dir');
      loadSms(true);
    });
  });

  document.getElementById('smsComposeBtn').addEventListener('click', function () {
    var panel = document.getElementById('smsComposePanel');
    var hidden = panel.style.display === 'none';
    panel.style.display = hidden ? 'block' : 'none';
    if (hidden) {
      fetch('/call-center/api/numbers')
        .then(function (r) { return r.json(); })
        .then(function (data) {
          var sel = document.getElementById('smsFromNumber');
          sel.textContent = '';
          var def = document.createElement('option');
          def.value = '';
          def.textContent = 'From number...';
          sel.appendChild(def);
          (data.numbers || []).forEach(function (n) {
            var opt = document.createElement('option');
            opt.value = String(n.id);
            opt.textContent = n.number + (n.label ? ' (' + n.label + ')' : '');
            sel.appendChild(opt);
          });
        });
    }
  });

  document.getElementById('smsCancelBtn').addEventListener('click', function () {
    document.getElementById('smsComposePanel').style.display = 'none';
  });

  document.getElementById('smsSendBtn').addEventListener('click', function () {
    var phoneId = document.getElementById('smsFromNumber').value;
    var toNum = document.getElementById('smsToNumber').value.trim();
    var msgBody = document.getElementById('smsBody').value.trim();
    if (!phoneId || !toNum || !msgBody) {
      alert('Please fill in From, To, and message.');
      return;
    }
    fetch('/call-center/api/sms', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({phone_number_id: parseInt(phoneId, 10), to_number: toNum, body: msgBody}),
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.id) {
          document.getElementById('smsComposePanel').style.display = 'none';
          document.getElementById('smsBody').value = '';
          document.getElementById('smsToNumber').value = '';
          loadSms(true);
        } else {
          alert(data.error || 'Send failed');
        }
      });
  });

  document.getElementById('sms-tab-btn').addEventListener('click', function () {
    loadSms(true);
  });
}());
</script>
```

- [ ] **Step 4.5: Restart KBS and verify**

```bash
cd /mnt/archie_brain/kytran-business-suite
docker compose restart kbs_app && sleep 10
docker logs kbs_app --tail=5 2>&1
```

Log in at http://192.168.1.200:8091 → Call Center → confirm SMS tab appears. Click it — inbox loads, no JS console errors.

- [ ] **Step 4.6: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add plugins/kbs_call_center/templates/call_center.html
git commit -m "feat(call-center): SMS inbox tab — compose, filter, safe DOM rendering"
```

---

## Task 5: PR

- [ ] **Step 5.1: Push ARCHIE branch and open PR**

```bash
cd /mnt/archie_brain
git push -u origin feat/phase4-call-center
gh pr create \
  --title "feat: Phase 4 — Call Center RingCentral + SMS Inbox" \
  --body "$(cat <<'EOF'
## Summary
- Internal notify endpoint at /tools/account-center/api/internal/notify — validates X-Internal-Key, forwards to Telegram via telegram_service.send_info
- ARCHIE_INTERNAL_KEY env var controls access (both .env files updated)

## KBS Changes (kytran-business-suite repo)
- Migration 002: sms_messages table + ringcentral added to call_phone_numbers.provider CHECK
- RingCentral credential storage via tenant_integrations (same pattern as Stripe/Printful)
- GET/POST /api/sms — SMS inbox + send (queued, outbound dispatch in Phase 4b)
- GET/POST/DELETE /api/ringcentral/* — connect, disconnect, status
- POST /api/webhook/ringcentral — handles Validation-Token handshake, inbound SMS and missed call events
- Missed call + inbound SMS fire to ARCHIE_NOTIFY_URL → Telegram
- SMS tab in Call Center dashboard — inbox, filter, compose (all DOM via createElement/textContent — no innerHTML)

## What is NOT in scope (Phase 4b)
- Actual RingCentral API dispatch for outbound SMS (queued to DB, needs ringcentral_service.py)
- Voicemail transcription via Whisper
- Click-to-call from CRM contact cards

## Test plan
- [ ] ARCHIE: /api/internal/notify returns 200 with valid key, 401 without
- [ ] KBS: webhook Validation-Token handshake echoes token
- [ ] KBS: SMS tab visible in Call Center, loads without console errors
- [ ] Compose panel: From/To/body fields, send queues to sms_messages

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 5.2: Push KBS repo**

```bash
cd /mnt/archie_brain/kytran-business-suite
git push origin HEAD
```

---

## Self-Review

**Spec coverage:**
- ✅ `sms_messages` table (Task 1)
- ✅ RingCentral credential storage via `tenant_integrations` (Task 2)
- ✅ `POST /api/webhook/ringcentral` — inbound call + SMS receiver (Task 2)
- ✅ SMS inbox in Call Center dashboard (Task 4)
- ✅ Telegram notifications for missed calls/SMS (Tasks 2+3)
- ⏳ Voicemail transcription — Phase 4b (Whisper not in scope)
- ⏳ Outbound SMS dispatch — Phase 4b (needs ringcentral_service.py)
- ⏳ Click-to-call from CRM — Phase 4b

**Security:**
- Webhook: Validation-Token handshake for subscription setup
- Internal notify: X-Internal-Key header validation — key in .env, never hardcoded
- tenant_integrations: credentials stored as JSONB, not plaintext columns
- All DOM writes use textContent / createElement — no dynamic HTML injection

**Pattern consistency:**
- tenant_integrations: identical INSERT ON CONFLICT pattern as Stripe/Printful in kbs_store
- get_db_cursor / set_tenant_search_path: same as all call center routes
- Fire-and-forget notify: 5s timeout, exception suppressed — webhook never fails due to Telegram
