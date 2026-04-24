# Unified Voice Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make A.R.C.H.I.E. the sole outbound Telegram voice by migrating all direct senders to the director_reports inbox, enforcing a privilege guardrail, and adding a split-pane operational inbox UI in the platform COMs tab.

**Architecture:** All senders call `director_report_service.submit_via_inbox()` which writes to `director_reports` (PostgreSQL). The `archie_triage_consumer` in `archie-comms` is the only codepath that calls the Telegram API. The platform COMs tab and `archie.kytranempowerment.com` both read from the same table — complementary surfaces, shared source of truth.

**Tech Stack:** Python/Flask (platform_v2 + archie-comms), PostgreSQL (`SELECT FOR UPDATE SKIP LOCKED`), Jinja2 templates, vanilla JS (`setInterval` polling), LCARS CSS design system.

**Security note for Task 6:** All dynamic content rendered into the DOM uses the platform's existing `escHtml()` utility (defined in `consciousness.js`, available globally). Never insert raw API data into the DOM without escaping.

---

## Context: What Already Works

The privilege gate in `telegram_service.send()` (line 232) already soft-redirects unprivileged callers to the inbox. `send_security/system/forge/agent/sync` wrappers all pass non-privileged `source_agent` values and are already being redirected. **The migration in Task 2 changes these wrappers to call `submit_via_inbox()` directly** so Task 4's hard error does not break them. The only truly rogue direct caller is `agent_loop._send_approval_telegram()`.

---

## File Map

| File | Task | Change |
|------|------|--------|
| `archie-comms/app_comms.py` | 1, 3 | Add auth to `/api/send`; fix dispatch loop with `FOR UPDATE SKIP LOCKED` |
| `platform_v2/services/telegram_service.py` | 2, 4 | Rewrite send_* wrappers to use inbox directly; harden send() to raise PermissionError |
| `ai_bridge/agent_loop.py` | 2 | Replace `_send_approval_telegram()` with `submit_via_inbox()` |
| `archie-comms/app_comms.py` (triage escalation) | 2 | Add keyboard markup for `approval_request` category on escalation |
| `tests/test_telegram_isolation.py` | 5 | New: grep-based isolation assertion |
| `platform_v2/tools/department_hq/templates/department_hq.html` | 6 | Replace COMs inbox section with split-pane |
| `platform_v2/tools/department_hq/static/css/department-hq.css` | 6 | Add split-pane styles |

---

## Task 1 — #2267: Auth on /api/send

**Files:**
- Modify: `archie-comms/app_comms.py` — add token check to `/api/send`

- [ ] **Step 1: Read the current /api/send route**

  ```bash
  grep -n "api/send\|def api_send" /mnt/archie_brain/archie-comms/app_comms.py
  ```

  Note the line number. The route has no auth check.

- [ ] **Step 2: Read the existing auth pattern**

  ```bash
  grep -n "X-Service-Token\|hmac.compare_digest\|ARCHIE_SERVICE_TOKEN" \
    /mnt/archie_brain/archie-comms/app_comms.py | head -20
  ```

  Pattern in use: `token = request.headers.get("X-Service-Token", "")` then `hmac.compare_digest(token, ARCHIE_SERVICE_TOKEN)`.

- [ ] **Step 3: Add the auth check to api_send()**

  Find `def api_send()` and insert the token check as the first two lines of the function body:

  ```python
  @app.route("/api/send", methods=["POST"])
  def api_send():
      """Platform calls this to send a message through A.R.C.H.I.E.'s voice."""
      token = request.headers.get("X-Service-Token", "")
      if ARCHIE_SERVICE_TOKEN and not hmac.compare_digest(token, ARCHIE_SERVICE_TOKEN):
          return jsonify({"error": "Unauthorized"}), 401

      from services.telegram_service import send

      data = request.get_json() or {}
      result = send(
          category=data.get("category", "info"),
          title=data.get("title", ""),
          message=data.get("message", ""),
          source_agent=data.get("source_agent"),
          source_department=data.get("source_department"),
          source_module=data.get("source_module"),
          force=data.get("force", False),
      )
      return jsonify(result)
  ```

- [ ] **Step 4: Verify ARCHIE_SERVICE_TOKEN is declared in module scope**

  ```bash
  grep -n "ARCHIE_SERVICE_TOKEN" /mnt/archie_brain/archie-comms/app_comms.py | head -5
  ```

  Expected: a line like `ARCHIE_SERVICE_TOKEN = os.getenv("ARCHIE_SERVICE_TOKEN", "")` near the top. If missing, add it.

- [ ] **Step 5: Test — POST without token returns 401**

  ```bash
  docker exec archie_comms curl -s -X POST http://localhost:3002/api/send \
    -H "Content-Type: application/json" \
    -d '{"category":"info","title":"test","message":"no auth"}' | python3 -m json.tool
  ```

  Expected: `{"error": "Unauthorized"}`

- [ ] **Step 6: Test — POST with correct token passes**

  ```bash
  TOKEN=$(docker exec archie_platform printenv ARCHIE_COMMS_SERVICE_TOKEN)
  docker exec archie_comms curl -s -X POST http://localhost:3002/api/send \
    -H "Content-Type: application/json" \
    -H "X-Service-Token: $TOKEN" \
    -d '{"category":"info","title":"auth test","message":"ok","source_agent":"system_bootstrap"}' \
    | python3 -m json.tool
  ```

  Expected: response with `"sent"` key (not a 401).

- [ ] **Step 7: Restart archie_comms and commit**

  ```bash
  cd /mnt/archie_brain && docker compose restart archie_comms
  git add archie-comms/app_comms.py
  git commit -m "fix(comms): add X-Service-Token auth to /api/send endpoint (#2267)"
  ```

---

## Task 2 — #2225: Migrate Direct Senders

**Files:**
- Modify: `platform_v2/services/telegram_service.py` (lines 435-474)
- Modify: `ai_bridge/agent_loop.py` (`_send_approval_telegram`)
- Modify: `archie-comms/app_comms.py` (escalation — keyboard for approval_request)

### Part A: Rewrite send_* wrappers

- [ ] **Step 1: Read lines 435-474 of telegram_service.py**

  ```bash
  sed -n '432,475p' /mnt/archie_brain/platform_v2/services/telegram_service.py
  ```

  Currently: `send_forge/system/security/agent/sync` each call `send()` which soft-redirects them.
  After this task: each calls `submit_via_inbox()` directly.
  `send_info()` stays unchanged — it passes `source_agent="A.R.C.H.I.E."` which is privileged.

- [ ] **Step 2: Replace the five unprivileged wrappers**

  In `platform_v2/services/telegram_service.py`, replace the convenience shortcuts section (keep the module-level comment `# Convenience shortcuts`):

  ```python
  # ---------------------------------------------------------------------------
  # Convenience shortcuts — route to director_reports inbox (not Telegram directly)
  # ---------------------------------------------------------------------------
  def send_security(title: str, message: str, **kwargs) -> dict:
      """Critical security alert via V.I.G.I.L. — writes to director_reports inbox."""
      from services.director_report_service import submit_via_inbox
      return submit_via_inbox(
          category="security",
          title=title,
          message=message,
          source_agent=kwargs.get("source_agent", "V.I.G.I.L."),
          severity="critical",
          department=kwargs.get("source_department", "Security & Compliance"),
      )


  def send_system(title: str, message: str, **kwargs) -> dict:
      """Infrastructure alert via B.A.S.E. — writes to director_reports inbox."""
      from services.director_report_service import submit_via_inbox
      return submit_via_inbox(
          category="system",
          title=title,
          message=message,
          source_agent=kwargs.get("source_agent", "B.A.S.E."),
          severity="warning",
          department=kwargs.get("source_department", "Operations & Infrastructure"),
      )


  def send_forge(title: str, message: str, **kwargs) -> dict:
      """F.O.R.G.E. pipeline notification — writes to director_reports inbox."""
      from services.director_report_service import submit_via_inbox
      return submit_via_inbox(
          category="forge",
          title=title,
          message=message,
          source_agent=kwargs.get("source_agent", "F.O.R.G.E."),
          severity="info",
          department=kwargs.get("source_department", "Engineering & Technology"),
      )


  def send_agent(title: str, message: str, **kwargs) -> dict:
      """Agent lifecycle notification via K.I.N. — writes to director_reports inbox."""
      from services.director_report_service import submit_via_inbox
      return submit_via_inbox(
          category="agent",
          title=title,
          message=message,
          source_agent=kwargs.get("source_agent", "K.I.N."),
          severity="info",
          department=kwargs.get("source_department", "Human Resources & Culture"),
      )


  def send_sync(title: str, message: str, **kwargs) -> dict:
      """Background sync notification via C.O.D.E.X. — writes to director_reports inbox."""
      from services.director_report_service import submit_via_inbox
      return submit_via_inbox(
          category="sync",
          title=title,
          message=message,
          source_agent=kwargs.get("source_agent", "C.O.D.E.X."),
          severity="info",
          department=kwargs.get("source_department", "Documentation & Knowledge"),
      )


  def send_info(title: str, message: str, **kwargs) -> dict:
      """Informational notification from A.R.C.H.I.E. directly (privileged — bypasses inbox)."""
      kwargs.setdefault("source_agent", "A.R.C.H.I.E.")
      kwargs.setdefault("source_department", "Executive Office")
      return send("info", title, message, **kwargs)
  ```

- [ ] **Step 3: Test send_forge routes to inbox, not Telegram**

  ```bash
  docker exec archie_platform python3 -c "
  from services.telegram_service import send_forge
  result = send_forge('Test inbox route', 'Should appear in director_reports only')
  print(result)
  "
  ```

  Then verify the row exists:

  ```bash
  docker exec archie_database psql -U archie -d archie -c \
    "SELECT id, director_agent, title, triage_status FROM director_reports ORDER BY id DESC LIMIT 3;"
  ```

  Expected: a row with `director_agent='F.O.R.G.E.'` and `triage_status='pending'`.

- [ ] **Step 4: Commit Part A**

  ```bash
  git add platform_v2/services/telegram_service.py
  git commit -m "refactor(telegram): send_* wrappers now write to inbox directly (#2225a)"
  ```

### Part B: Migrate agent_loop approval telegram

- [ ] **Step 5: Read _send_approval_telegram**

  ```bash
  grep -n "_send_approval_telegram\|def _send_approval" /mnt/archie_brain/ai_bridge/agent_loop.py
  ```

  Read the function (60 lines from the line found):

  ```bash
  START=$(grep -n "def _send_approval_telegram" /mnt/archie_brain/ai_bridge/agent_loop.py | cut -d: -f1)
  sed -n "${START},$((START+60))p" /mnt/archie_brain/ai_bridge/agent_loop.py
  ```

- [ ] **Step 6: Replace _send_approval_telegram**

  Replace the entire function with:

  ```python
  def _send_approval_telegram(
      approval_id: int, action_type: str, action_data: dict, reason: str
  ):
      """Route an approval request through the director_reports inbox.

      The triage consumer detects category='approval_request' and escalates
      immediately with Approve/Deny/Defer inline keyboard markup.
      """
      import sys as _sys
      import os as _os

      platform_path = _os.path.join(_os.path.dirname(__file__), "..", "platform_v2")
      if platform_path not in _sys.path:
          _sys.path.insert(0, platform_path)
      try:
          from services.director_report_service import submit_via_inbox

          lines = [f"Approval #{approval_id} required for: {action_type}"]
          if reason:
              lines.append(f"Reason: {reason}")
          if action_data:
              for k, v in list(action_data.items())[:3]:
                  lines.append(f"{k}: {v}")

          submit_via_inbox(
              category="approval_request",
              title=f"Approval Required — {action_type} #{approval_id}",
              message="\n".join(lines),
              source_agent="A.R.C.H.I.E.",
              severity="critical",
              department="Executive Office",
          )
          logger.info(
              "Approval #%s submitted to director_reports inbox (category=approval_request)",
              approval_id,
          )
      except Exception as exc:
          logger.error("Failed to submit approval #%s to inbox: %s", approval_id, exc)
  ```

- [ ] **Step 7: Add keyboard markup for approval_request escalations in archie_comms**

  In `archie-comms/app_comms.py`, find the function that sends an escalated report to Telegram (search for `sendMessage` + `escalate`). Inside that function, after building the message text, add keyboard markup for approval_request reports:

  ```python
  import re as _re

  # Build base payload
  payload = {
      "chat_id": chat_id,
      "text": text,
      "parse_mode": "Markdown",
      "disable_web_page_preview": True,
  }

  # Approval requests get Approve/Deny/Defer buttons
  if report.get("category") == "approval_request":
      m = _re.search(r"#(\d+)", report.get("title", ""))
      if m:
          aid = m.group(1)
          payload["reply_markup"] = {
              "inline_keyboard": [[
                  {"text": "Approve", "callback_data": f"esc_approve_{aid}"},
                  {"text": "Deny",    "callback_data": f"esc_deny_{aid}"},
                  {"text": "Defer 1hr", "callback_data": f"esc_defer_{aid}"},
              ]]
          }
  ```

- [ ] **Step 8: Restart services and commit Part B**

  ```bash
  cd /mnt/archie_brain
  docker compose restart archie_comms
  docker compose restart archie_platform
  git add ai_bridge/agent_loop.py archie-comms/app_comms.py
  git commit -m "refactor(agent-loop): route approval requests through inbox (#2225b)"
  ```

---

## Task 3 — #2234: Gunicorn Race Condition Fix

**Files:**
- Modify: `archie-comms/app_comms.py` — triage consumer dispatch loop

- [ ] **Step 1: Find the dispatch loop**

  ```bash
  grep -n "triage_status.*pending\|pending.*triage_status\|dispatch.*report\|_dispatch" \
    /mnt/archie_brain/archie-comms/app_comms.py | head -20
  ```

  Find the function that reads pending director_reports and processes them. Read it:

  ```bash
  START=$(grep -n "def _dispatch\|def dispatch_pending\|def process_pending" \
    /mnt/archie_brain/archie-comms/app_comms.py | head -1 | cut -d: -f1)
  sed -n "${START},$((START+60))p" /mnt/archie_brain/archie-comms/app_comms.py
  ```

- [ ] **Step 2: Replace the pending query with FOR UPDATE SKIP LOCKED**

  The fetch and status update must happen inside the same transaction. Replace the existing pending SELECT with:

  ```python
  def _dispatch_pending_reports():
      """Fetch and process pending reports atomically.

      FOR UPDATE SKIP LOCKED ensures two gunicorn workers never process the
      same row — whichever worker acquires the lock first processes the row;
      the other skips it silently.
      """
      from database import get_db_cursor

      with get_db_cursor(commit=True) as (conn, cur):
          cur.execute(
              """
              SELECT id, department, director_agent, severity, category,
                     title, summary, created_at
              FROM director_reports
              WHERE triage_status = 'pending'
              ORDER BY
                  CASE severity
                      WHEN 'critical' THEN 1
                      WHEN 'high'     THEN 2
                      WHEN 'warning'  THEN 3
                      ELSE 4
                  END,
                  created_at ASC
              FOR UPDATE SKIP LOCKED
              LIMIT 10
              """
          )
          reports = cur.fetchall()

          for report in reports:
              action, reason = _classify_report(report)
              if action == "escalate":
                  _send_escalation_telegram(report)
                  new_status = "escalated"
              else:
                  new_status = action

              cur.execute(
                  """
                  UPDATE director_reports
                  SET triage_status       = %s,
                      triage_action       = %s,
                      triage_reason       = %s,
                      triaged_at          = NOW(),
                      escalated           = %s,
                      escalation_channel  = %s
                  WHERE id = %s
                  """,
                  (
                      new_status,
                      action,
                      reason,
                      action == "escalate",
                      "telegram" if action == "escalate" else None,
                      report["id"],
                  ),
              )
  ```

  **Note on get_db_cursor**: If `get_db_cursor` auto-commits between statements, use a raw psycopg2 connection instead to keep SELECT and UPDATE in the same transaction. Check `archie-comms/database.py` — if it yields `(conn, cur)` with `commit=True` at context-manager exit, it is safe to use as shown above.

- [ ] **Step 3: Test — two concurrent workers, one delivery**

  ```bash
  # Insert a test row
  docker exec archie_database psql -U archie -d archie -c "
  INSERT INTO director_reports (department, director_agent, severity, category, title, summary, triage_status)
  VALUES ('Test', 'TEST', 'info', 'test', 'Race test $(date +%s)', 'Should only be processed once', 'pending')
  RETURNING id;"

  # Simulate two workers firing simultaneously
  docker exec archie_comms python3 -c "
  import threading
  from app_comms import _dispatch_pending_reports
  threads = [threading.Thread(target=_dispatch_pending_reports) for _ in range(2)]
  [t.start() for t in threads]
  [t.join() for t in threads]
  print('done')
  "

  # Verify processed exactly once
  docker exec archie_database psql -U archie -d archie -c \
    "SELECT id, triage_status, triage_action FROM director_reports WHERE title LIKE 'Race test%' ORDER BY id DESC LIMIT 1;"
  ```

  Expected: `triage_status` is not `'pending'`, exactly one value.

- [ ] **Step 4: Restart and commit**

  ```bash
  cd /mnt/archie_brain && docker compose restart archie_comms
  git add archie-comms/app_comms.py
  git commit -m "fix(comms): FOR UPDATE SKIP LOCKED prevents gunicorn double-send (#2234)"
  ```

---

## Task 4 — #2224: Privilege Guardrail (Hard Error)

**Files:**
- Modify: `platform_v2/services/telegram_service.py` — lines 228-249 (privilege check)

**Dependency**: Tasks 1 and 2 must be complete. All unprivileged send_* callers now use submit_via_inbox() directly.

- [ ] **Step 1: Read lines 228-250 of telegram_service.py**

  ```bash
  sed -n '228,250p' /mnt/archie_brain/platform_v2/services/telegram_service.py
  ```

  Current: logs a warning then redirects to inbox.
  After: raises PermissionError immediately.

- [ ] **Step 2: Replace the soft redirect with a hard PermissionError**

  Find the block starting with `# ── Privilege check` and ending after the `_audit_send` + `return result` lines. Replace the entire `if not caller_is_privileged:` block:

  ```python
  # ── Privilege check ──────────────────────────────────────────────────────
  # Only A.R.C.H.I.E. / archie_triage_consumer / system_bootstrap may call
  # send() directly. All other callers MUST use submit_via_inbox().
  caller_is_privileged = _privileged or (source_agent in _PRIVILEGED_SOURCES)

  if not caller_is_privileged:
      raise PermissionError(
          f"telegram_service.send() called by unprivileged source '{source_agent}'. "
          f"Use director_report_service.submit_via_inbox() instead. "
          f"Add to _PRIVILEGED_SOURCES only if this caller IS A.R.C.H.I.E.'s voice."
      )
  # ─────────────────────────────────────────────────────────────────────────
  ```

- [ ] **Step 3: Test privileged caller (send_info) still works**

  ```bash
  docker exec archie_platform python3 -c "
  from services.telegram_service import send_info
  try:
      result = send_info('Guardrail test', 'Privileged — should not raise')
      print('OK — no PermissionError:', list(result.keys()))
  except PermissionError as e:
      print('FAIL — raised for privileged caller:', str(e)[:80])
  "
  ```

  Expected: `OK — no PermissionError: [...]`

- [ ] **Step 4: Test unprivileged direct call raises PermissionError**

  ```bash
  docker exec archie_platform python3 -c "
  from services.telegram_service import send
  try:
      send('info', 'test', 'test', source_agent='V.I.G.I.L.')
      print('FAIL — should have raised')
  except PermissionError as e:
      print('OK:', str(e)[:100])
  "
  ```

  Expected: `OK: telegram_service.send() called by unprivileged source 'V.I.G.I.L.'...`

- [ ] **Step 5: Restart and commit**

  ```bash
  cd /mnt/archie_brain && docker compose restart archie_platform
  git add platform_v2/services/telegram_service.py
  git commit -m "feat(telegram): hard PermissionError for unprivileged send() callers (#2224)"
  ```

---

## Task 5 — #2265: Final Routing Enforcement

**Files:**
- Create: `tests/test_telegram_isolation.py`

- [ ] **Step 1: Grep for remaining direct Telegram API usage**

  ```bash
  grep -rn "api.telegram.org\|sendMessage" \
    /mnt/archie_brain/platform_v2/ \
    /mnt/archie_brain/ai_bridge/ \
    --include="*.py"
  ```

  Expected: zero results. If any appear, migrate them using the `submit_via_inbox()` pattern from Task 2.

- [ ] **Step 2: Grep for raw TELEGRAM_BOT_TOKEN usage in requests**

  ```bash
  grep -rn "TELEGRAM_BOT_TOKEN" \
    /mnt/archie_brain/platform_v2/ \
    /mnt/archie_brain/ai_bridge/ \
    --include="*.py" \
    | grep -v "os.getenv\|getenv\|#"
  ```

  Expected: zero results (references should only be `os.getenv(...)` declarations, not active usage).

- [ ] **Step 3: Fix any violations found in Steps 1-2**

  For each match, replace the direct Telegram call with:

  ```python
  from services.director_report_service import submit_via_inbox
  submit_via_inbox(
      category="<appropriate_category>",
      title="<message_title>",
      message="<message_body>",
      source_agent="<agent_name>",
      severity="<critical|warning|info>",
      department="<department_name>",
  )
  ```

- [ ] **Step 4: Create isolation test**

  Create `tests/test_telegram_isolation.py`:

  ```python
  """
  Asserts no code outside archie-comms/ calls the Telegram API directly.
  Run: pytest tests/test_telegram_isolation.py -v
  """
  import subprocess
  from pathlib import Path

  REPO_ROOT = Path(__file__).parent.parent
  SCAN_DIRS = ["platform_v2", "ai_bridge"]


  def _grep(pattern: str) -> list:
      results = []
      for d in SCAN_DIRS:
          target = REPO_ROOT / d
          if not target.exists():
              continue
          proc = subprocess.run(
              ["grep", "-rn", "--include=*.py", pattern, str(target)],
              capture_output=True,
              text=True,
          )
          if proc.stdout.strip():
              results.extend(proc.stdout.strip().splitlines())
      return results


  def test_no_direct_telegram_api():
      """No code in platform_v2 or ai_bridge should call api.telegram.org."""
      violations = _grep("api.telegram.org")
      assert violations == [], (
          "Direct Telegram API calls found outside archie-comms/.\n"
          "Use director_report_service.submit_via_inbox() instead.\n\n"
          + "\n".join(violations)
      )


  def test_no_raw_bot_token_requests():
      """TELEGRAM_BOT_TOKEN should only appear in os.getenv() declarations, not active requests."""
      all_refs = _grep("TELEGRAM_BOT_TOKEN")
      violations = [
          line for line in all_refs
          if "os.getenv" not in line and "getenv" not in line and not line.strip().startswith("#")
      ]
      assert violations == [], (
          "Active TELEGRAM_BOT_TOKEN usage found outside archie-comms/.\n\n"
          + "\n".join(violations)
      )
  ```

- [ ] **Step 5: Run tests**

  ```bash
  cd /mnt/archie_brain && python3 -m pytest tests/test_telegram_isolation.py -v
  ```

  Expected:
  ```
  PASSED tests/test_telegram_isolation.py::test_no_direct_telegram_api
  PASSED tests/test_telegram_isolation.py::test_no_raw_bot_token_requests
  ```

- [ ] **Step 6: Commit**

  ```bash
  git add tests/test_telegram_isolation.py
  git commit -m "test: Telegram isolation assertions — zero direct API calls outside archie-comms (#2265)"
  ```

---

## Task 6 — #2268: Unified Inbox UI (Split Pane)

**Files:**
- Modify: `platform_v2/tools/department_hq/static/css/department-hq.css`
- Modify: `platform_v2/tools/department_hq/templates/department_hq.html`

**Security:** All dynamic content MUST be passed through the platform's `escHtml()` utility before DOM insertion. This function is available globally — do not skip it for any field from the API response.

### Part A: CSS

- [ ] **Step 1: Append split-pane styles to department-hq.css**

  Append to `/mnt/archie_brain/platform_v2/tools/department_hq/static/css/department-hq.css`:

  ```css
  /* ── COMs Unified Inbox Split Pane (#2268) ──────────────────────────── */
  .coms-inbox-header {
    display: flex; align-items: center; gap: 12px;
    padding: 10px 16px;
    border-bottom: 1px solid var(--archie-border, #1e293b);
    background: var(--archie-surface, #0f172a);
  }
  .coms-pending-badge {
    background: #ef4444; color: #fff;
    border-radius: 10px; padding: 1px 8px;
    font-size: 11px; font-weight: bold; min-width: 20px; text-align: center;
  }
  .coms-pending-badge.empty { background: #374151; }
  .coms-show-all-label {
    margin-left: auto; display: flex; align-items: center; gap: 6px;
    font-size: 12px; color: var(--archie-muted, #64748b); cursor: pointer;
  }
  .coms-mark-all-btn {
    padding: 4px 12px; background: transparent;
    border: 1px solid var(--archie-border, #1e293b);
    color: var(--archie-muted, #64748b);
    border-radius: 4px; font-size: 11px; cursor: pointer;
    transition: border-color .15s, color .15s;
  }
  .coms-mark-all-btn:hover { border-color: #00d4ff; color: #00d4ff; }

  .coms-inbox-split {
    display: flex; height: 420px;
    border: 1px solid var(--archie-border, #1e293b);
    border-radius: 6px; overflow: hidden;
  }
  .coms-inbox-list {
    width: 280px; flex-shrink: 0; overflow-y: auto;
    border-right: 1px solid var(--archie-border, #1e293b);
    background: var(--archie-surface, #0f172a);
  }
  .coms-inbox-list::-webkit-scrollbar { width: 4px; }
  .coms-inbox-list::-webkit-scrollbar-thumb { background: #1e293b; border-radius: 2px; }

  .coms-inbox-row {
    padding: 10px 14px;
    border-bottom: 1px solid var(--archie-border, #1e293b);
    cursor: pointer; transition: background .1s;
  }
  .coms-inbox-row:hover { background: #1e293b33; }
  .coms-inbox-row.active { background: #1e3a5f; border-left: 3px solid #00d4ff; }
  .coms-inbox-row .cir-severity { font-size: 10px; font-weight: bold; margin-bottom: 2px; }
  .coms-inbox-row .cir-title {
    font-size: 12px; color: var(--archie-text, #e2e8f0);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .coms-inbox-row .cir-meta { font-size: 10px; color: var(--archie-muted, #64748b); margin-top: 2px; }

  .coms-inbox-detail {
    flex: 1; overflow-y: auto; padding: 20px;
    background: var(--archie-bg, #0a0e1a);
  }
  .coms-inbox-detail.empty {
    display: flex; align-items: center; justify-content: center;
    color: var(--archie-muted, #64748b); font-size: 13px;
  }
  .coms-detail-severity { font-size: 11px; font-weight: bold; margin-bottom: 8px; }
  .coms-detail-title { font-size: 16px; font-weight: 600; color: var(--archie-text, #e2e8f0); margin-bottom: 12px; }
  .coms-detail-meta {
    display: grid; grid-template-columns: auto 1fr; gap: 4px 12px;
    font-size: 12px; color: var(--archie-muted, #64748b); margin-bottom: 14px;
  }
  .coms-detail-meta span:nth-child(even) { color: var(--archie-text, #e2e8f0); }
  .coms-detail-summary {
    font-size: 13px; color: var(--archie-text-dim, #94a3b8);
    line-height: 1.6; margin-bottom: 20px; white-space: pre-wrap;
  }
  .coms-detail-actions { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
  .coms-action-btn {
    padding: 6px 16px; border-radius: 4px; font-size: 12px; font-weight: 500;
    cursor: pointer; border: 1px solid; transition: opacity .15s; background: transparent;
  }
  .coms-action-btn:hover { opacity: 0.8; }
  .coms-action-btn.escalate   { border-color: #ef4444; color: #ef4444; }
  .coms-action-btn.suppress   { border-color: #f59e0b; color: #f59e0b; }
  .coms-action-btn.resolve    { border-color: #22c55e; color: #22c55e; }
  .coms-action-btn.consolidate { border-color: #7eb8f7; color: #7eb8f7; }
  .coms-open-archie-link {
    display: inline-flex; align-items: center; gap: 4px;
    font-size: 12px; color: #00d4ff; text-decoration: none;
    border-bottom: 1px solid transparent; transition: border-color .15s;
  }
  .coms-open-archie-link:hover { border-bottom-color: #00d4ff; }
  .coms-inbox-empty-state {
    padding: 40px 14px; text-align: center;
    color: var(--archie-muted, #64748b); font-size: 12px;
  }
  .sev-critical { color: #ef4444; }
  .sev-high     { color: #f97316; }
  .sev-warning  { color: #f59e0b; }
  .sev-info, .sev-low { color: #64748b; }
  ```

- [ ] **Step 2: Verify CSS loaded (restart + spot check)**

  ```bash
  cd /mnt/archie_brain && docker compose restart archie_platform
  ```

  Open http://192.168.1.200:3000/tools/department-hq → COMs tab. Existing UI should look unchanged (new classes not in use yet).

### Part B: HTML markup

- [ ] **Step 3: Find the COMs inbox container in department_hq.html**

  ```bash
  grep -n "coms-inbox\|loadComsInbox\|comsInbox\|director-report" \
    /mnt/archie_brain/platform_v2/tools/department_hq/templates/department_hq.html | head -20
  ```

  Identify the HTML block that holds the current director-reports inbox output (the element that `loadComsInbox()` populates).

- [ ] **Step 4: Read that section**

  ```bash
  START=$(grep -n "loadComsInbox\|coms-inbox" \
    /mnt/archie_brain/platform_v2/tools/department_hq/templates/department_hq.html \
    | head -1 | cut -d: -f1)
  sed -n "$((START-5)),$((START+40))p" \
    /mnt/archie_brain/platform_v2/tools/department_hq/templates/department_hq.html
  ```

- [ ] **Step 5: Replace the inbox section HTML**

  Find the existing inbox container element and replace it (keep the surrounding tab wrapper and the policies section below it):

  ```html
  <!-- COMs Unified Inbox — split pane (#2268) -->
  <div class="coms-inbox-header">
    <span style="font-size:12px;color:var(--archie-muted)">INBOX</span>
    <span class="coms-pending-badge empty" id="coms-pending-count">0</span>
    <label class="coms-show-all-label">
      <input type="checkbox" id="coms-show-all" onchange="window.loadComsInbox()">
      Show resolved
    </label>
    <button class="coms-mark-all-btn" onclick="window.comsMarkAllResolved()">
      Mark all resolved
    </button>
  </div>
  <div class="coms-inbox-split">
    <div class="coms-inbox-list" id="coms-inbox-list">
      <div class="coms-inbox-empty-state">Loading...</div>
    </div>
    <div class="coms-inbox-detail empty" id="coms-inbox-detail">
      Select a report to view details
    </div>
  </div>
  ```

### Part C: JavaScript

- [ ] **Step 6: Read the existing loadComsInbox function**

  ```bash
  START=$(grep -n "loadComsInbox\|window.loadComsInbox" \
    /mnt/archie_brain/platform_v2/tools/department_hq/templates/department_hq.html \
    | grep -v "html" | head -1 | cut -d: -f1)
  sed -n "${START},$((START+70))p" \
    /mnt/archie_brain/platform_v2/tools/department_hq/templates/department_hq.html
  ```

  Note the API URL pattern used (e.g. `/api/department-hq/api/coms/director-reports/pending`).

- [ ] **Step 7: Replace loadComsInbox and add supporting functions**

  Find the `loadComsInbox` function in the `<script>` section and replace it. Also add the supporting functions after it. All dynamic content uses `escHtml()`:

  ```javascript
  /* ── COMs Unified Inbox — split pane (#2268) ──────────────────────── */
  window._comsSelectedId = null;
  window._comsInboxTimer = null;

  // Severity CSS class helper
  function _comsSevClass(s) {
    if (s === 'critical') return 'sev-critical';
    if (s === 'high') return 'sev-high';
    if (s === 'warning') return 'sev-warning';
    return 'sev-info';
  }

  // Relative time helper
  function _comsRelTime(ts) {
    if (!ts) return '—';
    const diff = Math.floor((Date.now() - new Date(ts).getTime()) / 1000);
    if (diff < 60) return diff + 's ago';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    return Math.floor(diff / 86400) + 'd ago';
  }

  window.loadComsInbox = function() {
    const showAll = document.getElementById('coms-show-all') &&
                    document.getElementById('coms-show-all').checked;
    const url = showAll
      ? '/api/department-hq/api/coms/director-reports'
      : '/api/department-hq/api/coms/director-reports/pending';

    fetch(url)
      .then(function(r) { return r.json(); })
      .then(function(data) {
        const reports = data.reports || data || [];
        const listEl = document.getElementById('coms-inbox-list');
        const badge  = document.getElementById('coms-pending-count');
        const pending = reports.filter(function(r) {
          return r.triage_status === 'pending' || !r.triage_status;
        });

        if (badge) {
          badge.textContent = pending.length;
          badge.className = 'coms-pending-badge' + (pending.length === 0 ? ' empty' : '');
        }

        if (!listEl) return;

        if (reports.length === 0) {
          listEl.innerHTML = '';
          var empty = document.createElement('div');
          empty.className = 'coms-inbox-empty-state';
          empty.textContent = 'Inbox clear ✓';
          listEl.appendChild(empty);
          return;
        }

        // Build list using DOM — no dynamic HTML injection
        listEl.innerHTML = '';
        reports.forEach(function(r) {
          var row = document.createElement('div');
          row.className = 'coms-inbox-row' +
            (r.id === window._comsSelectedId ? ' active' : '');
          row.dataset.id = r.id;
          row.onclick = function() { window.comsSelectReport(r.id, reports); };

          var sev = document.createElement('div');
          sev.className = 'cir-severity ' + _comsSevClass(r.severity);
          sev.textContent = '● ' + (r.severity || 'info').toUpperCase() +
            '  ·  ' + (r.director_agent || r.source_agent || '?');

          var title = document.createElement('div');
          title.className = 'cir-title';
          title.textContent = r.title || '';

          var meta = document.createElement('div');
          meta.className = 'cir-meta';
          meta.textContent = _comsRelTime(r.created_at);

          row.appendChild(sev);
          row.appendChild(title);
          row.appendChild(meta);
          listEl.appendChild(row);
        });

        // Re-render detail pane if a report is still selected
        if (window._comsSelectedId) {
          var sel = reports.find(function(r) { return r.id === window._comsSelectedId; });
          if (sel) window._comsRenderDetail(sel);
        }
      })
      .catch(function(err) { console.error('[COMs inbox]', err); });
  };

  window.comsSelectReport = function(id, reports) {
    window._comsSelectedId = id;
    document.querySelectorAll('.coms-inbox-row').forEach(function(el) {
      el.classList.toggle('active', parseInt(el.dataset.id, 10) === id);
    });
    var report = (reports || []).find(function(r) { return r.id === id; });
    if (report) {
      window._comsRenderDetail(report);
    }
  };

  window._comsRenderDetail = function(r) {
    var el = document.getElementById('coms-inbox-detail');
    if (!el) return;
    el.className = 'coms-inbox-detail';
    el.innerHTML = ''; // clear

    // Severity badge
    var sev = document.createElement('div');
    sev.className = 'coms-detail-severity ' + _comsSevClass(r.severity);
    sev.textContent = '● ' + (r.severity || 'INFO').toUpperCase();
    el.appendChild(sev);

    // Title
    var title = document.createElement('div');
    title.className = 'coms-detail-title';
    title.textContent = r.title || '';
    el.appendChild(title);

    // Meta grid
    var meta = document.createElement('div');
    meta.className = 'coms-detail-meta';
    var metaFields = [
      ['Agent', r.director_agent || r.source_agent || '—'],
      ['Department', r.department || '—'],
      ['Received', _comsRelTime(r.created_at)],
      ['Status', r.triage_status || 'pending'],
    ];
    metaFields.forEach(function(pair) {
      var label = document.createElement('span');
      label.textContent = pair[0];
      var value = document.createElement('span');
      value.textContent = pair[1];
      meta.appendChild(label);
      meta.appendChild(value);
    });
    el.appendChild(meta);

    // Summary
    var summary = document.createElement('div');
    summary.className = 'coms-detail-summary';
    summary.textContent = r.summary || r.message || '—';
    el.appendChild(summary);

    // Action buttons
    var actions = document.createElement('div');
    actions.className = 'coms-detail-actions';
    var btns = [
      {action: 'escalate',   label: 'Escalate →', cls: 'escalate'},
      {action: 'suppress',   label: 'Suppress',         cls: 'suppress'},
      {action: 'resolve',    label: 'Resolve ✓',   cls: 'resolve'},
      {action: 'consolidate',label: 'Consolidate',      cls: 'consolidate'},
    ];
    btns.forEach(function(b) {
      var btn = document.createElement('button');
      btn.className = 'coms-action-btn ' + b.cls;
      btn.textContent = b.label;
      btn.onclick = function() { window.comsAck(r.id, b.action); };
      actions.appendChild(btn);
    });
    el.appendChild(actions);

    // Open in A.R.C.H.I.E. link
    var link = document.createElement('a');
    link.className = 'coms-open-archie-link';
    link.href = 'https://archie.kytranempowerment.com';
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.textContent = 'Open in A.R.C.H.I.E. ↗';
    el.appendChild(link);
  };

  window.comsAck = function(id, action) {
    fetch('/api/department-hq/api/coms/director-reports/' + id + '/ack', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({action: action, reason: 'Manual ' + action + ' from platform inbox'}),
    })
    .then(function(r) { return r.json(); })
    .then(function() {
      window._comsSelectedId = null;
      var detail = document.getElementById('coms-inbox-detail');
      if (detail) {
        detail.className = 'coms-inbox-detail empty';
        detail.innerHTML = '';
        detail.textContent = 'Select a report to view details';
      }
      window.loadComsInbox();
    })
    .catch(function(err) { console.error('[COMs ack]', err); });
  };

  window.comsMarkAllResolved = function() {
    if (!confirm('Mark all pending reports as resolved?')) return;
    fetch('/api/department-hq/api/coms/director-reports/pending')
      .then(function(r) { return r.json(); })
      .then(function(data) {
        var reports = data.reports || data || [];
        var pending = reports.filter(function(r) {
          return r.triage_status === 'pending' || !r.triage_status;
        });
        return Promise.all(pending.map(function(r) {
          return fetch('/api/department-hq/api/coms/director-reports/' + r.id + '/ack', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({action: 'resolve', reason: 'Bulk resolve from platform inbox'}),
          });
        }));
      })
      .then(function() { window.loadComsInbox(); })
      .catch(function(err) { console.error('[COMs mark-all]', err); });
  };

  window._startComsInboxPoll = function() {
    window.loadComsInbox();
    clearInterval(window._comsInboxTimer);
    window._comsInboxTimer = setInterval(window.loadComsInbox, 10000);
  };

  window._stopComsInboxPoll = function() {
    clearInterval(window._comsInboxTimer);
  };
  /* ─────────────────────────────────────────────────────────────────── */
  ```

- [ ] **Step 8: Wire poll start/stop to COMs tab activation**

  Find where the COMs tab is activated in the template (look for a tab click handler or a `switchComTab`/`loadComsTab` function). Add poll start/stop:

  ```javascript
  // When COMs tab becomes active — add this line:
  window._startComsInboxPoll();

  // When another tab is selected — add this line to the existing tab-hide logic:
  window._stopComsInboxPoll();
  ```

- [ ] **Step 9: Restart and browser test**

  ```bash
  cd /mnt/archie_brain && docker compose restart archie_platform
  ```

  Open http://192.168.1.200:3000/tools/department-hq → COMs tab.

  Check all of:
  - Split pane renders with list on left, empty detail pane on right
  - Clicking a report shows full detail in right pane
  - Escalate / Suppress / Resolve / Consolidate buttons work — row disappears after action
  - "Open in A.R.C.H.I.E." link opens archie.kytranempowerment.com in new tab
  - Pending count badge updates every 10s
  - "Mark all resolved" clears the pending list
  - "Show resolved" checkbox toggles to show triaged reports
  - Triage policies section below the split pane is unchanged

- [ ] **Step 10: Commit**

  ```bash
  git add platform_v2/tools/department_hq/templates/department_hq.html \
          platform_v2/tools/department_hq/static/css/department-hq.css
  git commit -m "feat(coms): split-pane unified inbox + Open-in-A.R.C.H.I.E. bridge (#2268)"
  ```

---

## Final: PR and Dev HQ

- [ ] **Step 1: Push and open PR**

  ```bash
  git push -u origin feat/unified-voice-completion-2277
  gh pr create \
    --title "feat(unified-voice): complete Telegram isolation — #2267 #2225 #2234 #2224 #2265 #2268" \
    --body "$(cat <<'EOF'
  ## Summary
  - **#2267**: X-Service-Token auth on /api/send endpoint
  - **#2225**: send_* wrappers + agent_loop approvals migrated to submit_via_inbox()
  - **#2234**: SELECT FOR UPDATE SKIP LOCKED — no more gunicorn double-sends
  - **#2224**: Hard PermissionError for unprivileged telegram_service.send() callers
  - **#2265**: Isolation test — zero direct Telegram API calls outside archie-comms
  - **#2268**: Split-pane COMs inbox with Open-in-A.R.C.H.I.E. bridge link

  ## Architecture
  All senders now write to director_reports via submit_via_inbox().
  archie_triage_consumer is the sole Telegram exit point.
  Platform COMs tab (ops) + archie.kytranempowerment.com (conversational) share the same table.

  ## Test plan
  - [ ] POST /api/send without token returns 401
  - [ ] send_forge() creates director_reports row — no direct Telegram send
  - [ ] Concurrent dispatch workers — single delivery per report
  - [ ] Unprivileged send() call raises PermissionError
  - [ ] pytest tests/test_telegram_isolation.py passes (2 tests)
  - [ ] COMs split pane: load, select, triage actions, mark all, toggle, Open in A.R.C.H.I.E.

  🤖 Generated with [Claude Code](https://claude.ai/claude-code)
  EOF
  )"
  ```

- [ ] **Step 2: Update Dev HQ**

  ```
  mcp complete_task #2267 — "Auth added to /api/send. Tested: 401 without token, passes with ARCHIE_COMMS_SERVICE_TOKEN"
  mcp complete_task #2225 — "send_* wrappers rewritten to submit_via_inbox(). agent_loop approval routed via inbox with keyboard markup in escalation."
  mcp complete_task #2234 — "FOR UPDATE SKIP LOCKED prevents double-send. Concurrent worker test passed."
  mcp complete_task #2224 — "Hard PermissionError enforced. Privileged callers unaffected. Unprivileged direct call raises correctly."
  mcp complete_task #2265 — "Zero direct Telegram API violations. Isolation test passes."
  mcp complete_task #2268 — "Split-pane inbox live in COMs tab. DOM-safe (no raw API data in HTML). Open-in-A.R.C.H.I.E. bridge working."
  mcp log_decision — "A.R.C.H.I.E. is the sole Telegram voice. FOR UPDATE SKIP LOCKED for race safety. Hard PermissionError for privilege enforcement. Platform COMs (ops) + archie.kytranempowerment.com (conversational) share director_reports — complementary surfaces."
  mcp update_project_understanding #277
  ```
