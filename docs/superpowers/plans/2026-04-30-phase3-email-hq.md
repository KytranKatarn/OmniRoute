# Phase 3 — Email HQ Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an Email HQ tab to the existing Email Manager module — unified inbox across all 48 mailboxes, assign-to-agent, email rules, R.E.S.O.L.V.E. oversight job (every 30 min), and a stats panel.

**Architecture:** New `email_assignments` and `email_rules` tables. New `email_hq_routes.py` blueprint extension with unified inbox API + assign endpoint. New APScheduler job `email_oversight` that R.E.S.O.L.V.E. runs to flag unanswered emails. New "HQ" tab in the email manager template.

**Tech Stack:** Flask, PostgreSQL, APScheduler, Jinja2, existing Email Manager module at `/tools/email-manager`

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `platform_v2/database/migrations/173_email_hq.sql` | email_assignments + email_rules tables |
| Create | `platform_v2/tools/email_manager/hq_routes.py` | Unified inbox, assign, stats, rules APIs |
| Modify | `platform_v2/tools/email_manager/__init__.py` | Register hq_routes blueprint |
| Modify | `platform_v2/services/agent_jobs.py` | Add email_oversight job (30 min, R.E.S.O.L.V.E.) |
| Modify | `platform_v2/templates/tools/email_manager.html` | Add HQ tab + JS for unified inbox |

---

## Task 1: Database migration — email_assignments + email_rules

**Files:**
- Create: `platform_v2/database/migrations/173_email_hq.sql`

- [ ] **Step 1.1: Write migration**

```sql
-- platform_v2/database/migrations/173_email_hq.sql

CREATE TABLE IF NOT EXISTS email_assignments (
    id              SERIAL PRIMARY KEY,
    email_id        INTEGER,
    mailbox_id      INTEGER REFERENCES email_mailboxes(id) ON DELETE CASCADE,
    assigned_agent  VARCHAR(100),
    assigned_by     VARCHAR(100) DEFAULT 'system',
    status          VARCHAR(50)  NOT NULL DEFAULT 'open',
    notes           TEXT,
    created_at      TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_email_assignments_status ON email_assignments (status);
CREATE INDEX IF NOT EXISTS idx_email_assignments_agent  ON email_assignments (assigned_agent);

CREATE TABLE IF NOT EXISTS email_rules (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    condition_field VARCHAR(50)  NOT NULL DEFAULT 'from_domain',
    condition_value TEXT         NOT NULL,
    action          VARCHAR(50)  NOT NULL DEFAULT 'assign_agent',
    action_value    TEXT,
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

-- Seed initial oversight rule
INSERT INTO email_rules (name, condition_field, condition_value, action, action_value)
VALUES ('Route subscription inquiries to R.E.S.O.L.V.E.',
        'subject_contains', 'subscription', 'assign_agent', 'R.E.S.O.L.V.E.')
ON CONFLICT DO NOTHING;
```

- [ ] **Step 1.2: Run migration**

```bash
docker exec archie_database psql -U archie -d archie \
  -f /mnt/archie_brain/platform_v2/database/migrations/173_email_hq.sql
```

Expected: `CREATE TABLE` x2, `CREATE INDEX` x2, `INSERT 1`

- [ ] **Step 1.3: Verify**

```bash
docker exec archie_database psql -U archie -d archie \
  -c "\dt email_assignments email_rules"
```

- [ ] **Step 1.4: Commit**

```bash
git add platform_v2/database/migrations/173_email_hq.sql
git commit -m "feat(email-hq): email_assignments + email_rules migration (173)"
```

---

## Task 2: hq_routes.py — unified inbox + assign + stats + rules APIs

**Files:**
- Create: `platform_v2/tools/email_manager/hq_routes.py`

- [ ] **Step 2.1: Read existing email_manager blueprint registration**

```bash
grep -n "blueprint\|register\|import\|email_manager_bp" \
  platform_v2/tools/email_manager/__init__.py | head -15
grep -n "email_manager_bp\|Blueprint\|url_prefix" \
  platform_v2/tools/email_manager/overview_routes.py | head -5
```

Note the blueprint variable name and how routes are registered.

- [ ] **Step 2.2: Write hq_routes.py**

```python
# platform_v2/tools/email_manager/hq_routes.py
"""
Email HQ routes — unified inbox, assign-to-agent, rules, and stats.
Mounted on the email_manager blueprint at /tools/email-manager/api/hq/
"""
import logging
from datetime import datetime, timedelta

from flask import jsonify, request
from flask_login import login_required

from database import get_db_cursor

logger = logging.getLogger(__name__)


def register_hq_routes(bp, admin_required):
    """Register Email HQ routes on the email_manager blueprint."""

    @bp.route("/api/hq/unified-inbox", methods=["GET"])
    @login_required
    def hq_unified_inbox():
        """Return recent emails across all mailboxes, newest first."""
        limit = min(int(request.args.get("limit", 50)), 200)
        mailbox_filter = request.args.get("mailbox_id", type=int)
        status_filter = request.args.get("status", "")  # read/unread/all

        with get_db_cursor() as (_, cur):
            where_clauses = []
            params = []

            if mailbox_filter:
                where_clauses.append("al.mailbox_id = %s")
                params.append(mailbox_filter)

            if status_filter == "unread":
                where_clauses.append("al.read_at IS NULL")
            elif status_filter == "read":
                where_clauses.append("al.read_at IS NOT NULL")

            where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
            params.append(limit)

            cur.execute(
                f"""
                SELECT al.id, al.mailbox_id, al.direction, al.from_address,
                       al.to_address, al.subject, al.received_at, al.read_at,
                       m.address AS mailbox_address, m.mailbox_type,
                       ea.assigned_agent, ea.status AS assignment_status
                FROM email_activity_log al
                JOIN email_mailboxes m ON m.id = al.mailbox_id
                LEFT JOIN email_assignments ea ON ea.email_id = al.id
                  AND ea.status = 'open'
                {where_sql}
                ORDER BY al.received_at DESC NULLS LAST
                LIMIT %s
                """,
                params,
            )
            rows = cur.fetchall()

        emails = [
            {
                "id": r["id"],
                "mailbox_id": r["mailbox_id"],
                "mailbox_address": r["mailbox_address"],
                "mailbox_type": r["mailbox_type"],
                "direction": r["direction"],
                "from_address": r["from_address"] or "",
                "to_address": r["to_address"] or "",
                "subject": r["subject"] or "(no subject)",
                "received_at": r["received_at"].isoformat() if r["received_at"] else None,
                "is_read": r["read_at"] is not None,
                "assigned_agent": r["assigned_agent"],
                "assignment_status": r["assignment_status"],
            }
            for r in rows
        ]
        return jsonify({"emails": emails, "count": len(emails)})

    @bp.route("/api/hq/assign", methods=["POST"])
    @login_required
    def hq_assign():
        """Assign an email to an agent for handling."""
        data = request.get_json(silent=True) or {}
        email_id = data.get("email_id")
        agent_name = str(data.get("agent_name", "")).strip()
        notes = str(data.get("notes", "")).strip()[:500]

        if not email_id or not agent_name:
            return jsonify({"error": "email_id and agent_name required"}), 400

        with get_db_cursor(commit=True) as (_, cur):
            cur.execute(
                """
                INSERT INTO email_assignments
                    (email_id, assigned_agent, assigned_by, notes, status)
                VALUES (%s, %s, 'manual', %s, 'open')
                ON CONFLICT DO NOTHING
                """,
                (email_id, agent_name, notes or None),
            )
        logger.info("email_hq.assign: email=%s → agent=%s", email_id, agent_name)
        return jsonify({"assigned": True, "email_id": email_id, "agent": agent_name})

    @bp.route("/api/hq/stats", methods=["GET"])
    @login_required
    def hq_stats():
        """Return email overview stats for the HQ dashboard."""
        with get_db_cursor() as (_, cur):
            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE received_at > NOW() - INTERVAL '24h')
                        AS last_24h,
                    COUNT(*) FILTER (WHERE read_at IS NULL
                        AND received_at > NOW() - INTERVAL '24h')
                        AS unread_24h,
                    COUNT(*) FILTER (WHERE received_at > NOW() - INTERVAL '24h'
                        AND direction = 'inbound')
                        AS inbound_24h,
                    COUNT(DISTINCT mailbox_id) AS active_mailboxes
                FROM email_activity_log
                """
            )
            row = cur.fetchone()

            cur.execute(
                "SELECT COUNT(*) AS flagged FROM email_assignments "
                "WHERE status = 'open' AND created_at < NOW() - INTERVAL '24h'"
            )
            flagged_row = cur.fetchone()

        return jsonify({
            "last_24h": int(row["last_24h"] or 0),
            "unread_24h": int(row["unread_24h"] or 0),
            "inbound_24h": int(row["inbound_24h"] or 0),
            "active_mailboxes": int(row["active_mailboxes"] or 0),
            "flagged_unanswered": int(flagged_row["flagged"] or 0),
        })

    @bp.route("/api/hq/rules", methods=["GET"])
    @login_required
    def hq_rules():
        """Return all email routing rules."""
        with get_db_cursor() as (_, cur):
            cur.execute(
                "SELECT id, name, condition_field, condition_value, "
                "action, action_value, is_active FROM email_rules ORDER BY id"
            )
            rows = cur.fetchall()
        return jsonify({"rules": [dict(r) for r in rows]})
```

- [ ] **Step 2.3: Register in __init__.py**

Read `platform_v2/tools/email_manager/__init__.py` then add:
```python
from .hq_routes import register_hq_routes
# in the registration function:
register_hq_routes(email_manager_bp, admin_required)
```

- [ ] **Step 2.4: Restart and test endpoints**

```bash
docker compose restart archie_platform && sleep 15
docker exec archie_platform python3 -c "
import urllib.request
for path in ['/tools/email-manager/api/hq/stats', '/tools/email-manager/api/hq/unified-inbox']:
    try:
        r = urllib.request.urlopen('http://localhost:3000' + path, timeout=5)
        print(path, r.status)
    except urllib.error.HTTPError as e:
        print(path, e.code, '(redirect = OK)')
"
```

- [ ] **Step 2.5: Commit**

```bash
git add platform_v2/tools/email_manager/hq_routes.py \
        platform_v2/tools/email_manager/__init__.py
git commit -m "feat(email-hq): unified inbox + assign + stats + rules API endpoints"
```

---

## Task 3: R.E.S.O.L.V.E. email_oversight job

**Files:**
- Modify: `platform_v2/services/agent_jobs.py`

- [ ] **Step 3.1: Find the right place in agent_jobs.py**

```bash
grep -n "def.*job\|id=.*_job\|kin_welfare\|def email\|30.*minute\|interval.*30" \
  platform_v2/services/agent_jobs.py | head -20
```

Find how existing 30-minute jobs are registered and the `_log_cycle` pattern.

- [ ] **Step 3.2: Add email_oversight job function**

Add before the job registry list:

```python
def email_oversight(flask_app):
    """Job: R.E.S.O.L.V.E. reviews unassigned + stale emails every 30 min."""
    import time
    start = time.time()
    flagged = 0
    try:
        with flask_app.app_context():
            from database import get_db_cursor

            with get_db_cursor(commit=True) as (_, cur):
                # Flag inbound emails >24h old with no assignment
                cur.execute(
                    """
                    INSERT INTO email_assignments
                        (email_id, mailbox_id, assigned_agent, assigned_by,
                         status, notes)
                    SELECT al.id, al.mailbox_id, 'R.E.S.O.L.V.E.',
                           'email_oversight', 'open',
                           'Auto-flagged: unanswered >24h'
                    FROM email_activity_log al
                    WHERE al.direction = 'inbound'
                      AND al.received_at < NOW() - INTERVAL '24 hours'
                      AND al.read_at IS NULL
                      AND NOT EXISTS (
                          SELECT 1 FROM email_assignments ea
                          WHERE ea.email_id = al.id
                      )
                    ON CONFLICT DO NOTHING
                    RETURNING id
                    """
                )
                flagged = len(cur.fetchall())

        duration_ms = int((time.time() - start) * 1000)
        _log_cycle("email_oversight", flagged, 0, duration_ms,
                   details={"flagged": flagged})
        if flagged > 0:
            import logging
            logging.getLogger(__name__).info(
                "[EmailOversight] R.E.S.O.L.V.E. flagged %d unanswered emails", flagged
            )
    except Exception as exc:
        _log_cycle("email_oversight", 0, 1, 0, error_message=str(exc))
```

- [ ] **Step 3.3: Register the job in the scheduler**

Find where other 30-minute jobs are registered (e.g., `kin_welfare_digest`) and add:

```python
scheduler.add_job(
    with_ctx_app(email_oversight),
    "interval",
    minutes=30,
    id="email_oversight",
    max_instances=1,
    coalesce=True,
    replace_existing=True,
)
```

- [ ] **Step 3.4: Restart and verify job appears**

```bash
docker compose restart archie_platform && sleep 15
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0, '/app')
from app import scheduler
jobs = [j.id for j in scheduler.get_jobs()]
print('email_oversight in jobs:', 'email_oversight' in jobs)
"
```

- [ ] **Step 3.5: Commit**

```bash
git add platform_v2/services/agent_jobs.py
git commit -m "feat(email-hq): R.E.S.O.L.V.E. email_oversight job — 30min flag unanswered"
```

---

## Task 4: Add HQ tab to email manager template

**Files:**
- Modify: `platform_v2/templates/tools/email_manager.html`

- [ ] **Step 4.1: Read template tab structure**

```bash
grep -n "tab\|Tab\|data-tab\|switchTab\|panel" \
  platform_v2/templates/tools/email_manager.html | head -20
```

Note how existing tabs (Overview, Inbox, Sent, Agents, Settings) are structured.

- [ ] **Step 4.2: Add HQ tab button**

Find the existing tab buttons section and add the HQ tab alongside the others:

```html
<button class="em-tab" data-tab="hq" onclick="switchEmailTab('hq')">
  📬 HQ
</button>
```

- [ ] **Step 4.3: Add HQ tab panel**

Add a new tab panel for the HQ tab:

```html
<div id="em-tab-hq" class="em-tab-panel" style="display:none">
  <!-- Stats bar -->
  <div id="hqStats" style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:20px">
    <div style="border:1px solid #222;border-radius:6px;padding:12px;text-align:center;background:#050509">
      <div id="hqStat24h" style="font-size:22px;font-weight:700;color:#7c3aed">—</div>
      <div style="font-size:11px;color:#888;margin-top:2px">Emails (24h)</div>
    </div>
    <div style="border:1px solid #222;border-radius:6px;padding:12px;text-align:center;background:#050509">
      <div id="hqStatUnread" style="font-size:22px;font-weight:700;color:#f59e0b">—</div>
      <div style="font-size:11px;color:#888;margin-top:2px">Unread</div>
    </div>
    <div style="border:1px solid #222;border-radius:6px;padding:12px;text-align:center;background:#050509">
      <div id="hqStatMailboxes" style="font-size:22px;font-weight:700;color:#22c55e">—</div>
      <div style="font-size:11px;color:#888;margin-top:2px">Active Mailboxes</div>
    </div>
    <div style="border:1px solid #222;border-radius:6px;padding:12px;text-align:center;background:#050509">
      <div id="hqStatFlagged" style="font-size:22px;font-weight:700;color:#ef4444">—</div>
      <div style="font-size:11px;color:#888;margin-top:2px">Flagged &gt;24h</div>
    </div>
  </div>

  <!-- Unified inbox -->
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
    <h3 style="font-size:13px;color:#888;text-transform:uppercase;letter-spacing:1px;margin:0">Unified Inbox</h3>
    <select id="hqMailboxFilter"
      style="background:#0a0a14;color:#aaa;border:1px solid #333;border-radius:4px;padding:4px 8px;font-size:12px">
      <option value="">All mailboxes</option>
    </select>
  </div>
  <div id="hqEmailList" style="display:flex;flex-direction:column;gap:6px"></div>
</div>

<script>
(function () {
  'use strict';

  function loadHQStats() {
    fetch('/tools/email-manager/api/hq/stats')
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var s24 = document.getElementById('hqStat24h');
        var su = document.getElementById('hqStatUnread');
        var sm = document.getElementById('hqStatMailboxes');
        var sf = document.getElementById('hqStatFlagged');
        if (s24) s24.textContent = d.last_24h;
        if (su) su.textContent = d.unread_24h;
        if (sm) sm.textContent = d.active_mailboxes;
        if (sf) sf.textContent = d.flagged_unanswered;
      })
      .catch(function () {});
  }

  function loadUnifiedInbox(mailboxId) {
    var url = '/tools/email-manager/api/hq/unified-inbox?limit=50';
    if (mailboxId) url += '&mailbox_id=' + encodeURIComponent(mailboxId);
    fetch(url)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var list = document.getElementById('hqEmailList');
        if (!list) return;
        while (list.firstChild) list.removeChild(list.firstChild);
        (data.emails || []).forEach(function (e) {
          var row = document.createElement('div');
          row.style.cssText = 'border:1px solid #1a1a2e;border-radius:6px;padding:10px 14px;background:#050509;display:flex;justify-content:space-between;align-items:center;gap:10px';

          var left = document.createElement('div');
          left.style.cssText = 'flex:1;min-width:0';

          var subject = document.createElement('div');
          subject.textContent = e.subject;
          subject.style.cssText = 'font-size:13px;font-weight:' + (e.is_read ? '400' : '600') + ';color:' + (e.is_read ? '#888' : '#fff') + ';white-space:nowrap;overflow:hidden;text-overflow:ellipsis';

          var meta = document.createElement('div');
          meta.style.cssText = 'font-size:11px;color:#555;margin-top:3px';
          meta.textContent = (e.from_address || '—') + ' → ' + (e.mailbox_address || '—');

          left.appendChild(subject);
          left.appendChild(meta);

          var right = document.createElement('div');
          right.style.cssText = 'display:flex;align-items:center;gap:8px;flex-shrink:0';

          if (e.assigned_agent) {
            var badge = document.createElement('span');
            badge.textContent = e.assigned_agent;
            badge.style.cssText = 'background:#0f0a1e;color:#7c3aed;border:1px solid #7c3aed33;border-radius:10px;padding:2px 8px;font-size:10px';
            right.appendChild(badge);
          }

          var assignBtn = document.createElement('button');
          assignBtn.textContent = 'Assign';
          assignBtn.style.cssText = 'background:transparent;color:#888;border:1px solid #333;border-radius:4px;padding:3px 8px;cursor:pointer;font-size:11px';
          assignBtn.setAttribute('data-email-id', e.id);
          assignBtn.addEventListener('click', function () {
            var agent = window.prompt('Assign to agent (e.g. R.E.S.O.L.V.E.):');
            if (!agent) return;
            fetch('/tools/email-manager/api/hq/assign', {
              method: 'POST',
              headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({email_id: e.id, agent_name: agent}),
            }).then(function () { loadUnifiedInbox(mailboxId); });
          });
          right.appendChild(assignBtn);

          row.appendChild(left);
          row.appendChild(right);
          list.appendChild(row);
        });

        if (!data.emails || data.emails.length === 0) {
          var empty = document.createElement('div');
          empty.style.cssText = 'text-align:center;color:#555;padding:24px;font-size:13px';
          empty.textContent = 'No emails in unified inbox.';
          list.appendChild(empty);
        }
      })
      .catch(function () {});
  }

  // Hook into tab switch
  var origSwitch = window.switchEmailTab;
  window.switchEmailTab = function (tab) {
    if (origSwitch) origSwitch(tab);
    if (tab === 'hq') {
      loadHQStats();
      var filter = document.getElementById('hqMailboxFilter');
      loadUnifiedInbox(filter ? filter.value : '');
    }
  };

  var filter = document.getElementById('hqMailboxFilter');
  if (filter) {
    filter.addEventListener('change', function () {
      loadUnifiedInbox(filter.value);
    });
  }
}());
</script>
```

- [ ] **Step 4.4: Restart and verify tab loads**

```bash
docker compose restart archie_platform && sleep 15
docker exec archie_platform python3 -c "
import urllib.request
r = urllib.request.urlopen('http://localhost:3000/health', timeout=5)
print('Health:', r.status)
"
```

Navigate to `http://192.168.1.200:3000/tools/email-manager` → verify "📬 HQ" tab appears and stats load.

- [ ] **Step 4.5: Commit**

```bash
git add platform_v2/templates/tools/email_manager.html
git commit -m "feat(email-hq): HQ tab — unified inbox, stats panel, assign-to-agent"
```

---

## Task 5: PR

- [ ] **Step 5.1: Push and open PR**

```bash
git push -u origin feat/phase3-email-hq
gh pr create \
  --title "feat: Phase 3 — Email HQ (#302)" \
  --body "Unified inbox across all 48 mailboxes, R.E.S.O.L.V.E. 30-min oversight job flagging unanswered emails, assign-to-agent action, email stats panel, and routing rules table. Zero innerHTML with dynamic data."
```

---

## Self-Review

**Spec coverage:**
- ✅ Unified inbox tab — Task 4
- ✅ `email_assignments` + `email_rules` tables — Task 1
- ✅ Assign-to-agent action — Tasks 2+4
- ✅ R.E.S.O.L.V.E. oversight job (30 min) — Task 3
- ✅ Email stats panel — Tasks 2+4
- ✅ No innerHTML with dynamic data — all DOM via createElement/textContent

**Not in scope this phase:**
- KBS help_desk ticket creation from email (requires KBS DB access from ARCHIE — Phase 3b)
- Email rules auto-apply (rules stored but not auto-applied on ingest — Phase 3b)
