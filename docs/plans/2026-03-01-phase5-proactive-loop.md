# Phase 5: Proactive Self-Improvement Loop — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close the autonomous self-improvement loop: scheduled scans → auto-proposals → tier-based approval → auto-execution → deploy notification.

**Architecture:** Add a proactive scan job to the agent_loop (every 6h), route auto-generated proposals through the existing Tier 1/2 approval queue, and add an `improvement_approve` execution handler that triggers the Phase 4 auto-execution pipeline.

**Tech Stack:** Python, psycopg2, APScheduler, existing agent_loop + scan_pipeline + Code Sentinel infrastructure

---

### Task 1: Add approval queue integration to scan_pipeline

**Files:**
- Modify: `platform_v2/services/scan_pipeline.py`

**Step 1: Add approval queue submission to _create_proposal_for_issue()**

After the proposal is created and committed (around the `logger.info(f"Created proposal...")` line), add a call to `request_approval()` to route the proposal through the tier system.

Insert AFTER the `logger.info(...)` line and BEFORE the `return proposal_id`:

```python
            # Route through autonomy approval queue
            try:
                import sys
                sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
                from agent_loop import request_approval

                # Low/medium risk → Tier 1 (auto-approve)
                # High/critical risk → Tier 2 (human via Telegram)
                is_low_risk = risk_level in ("low", "medium") and priority in (
                    "low",
                    "medium",
                )
                approval_tier = 1 if is_low_risk else 2
                approval_priority = (
                    3 if priority == "critical" else 5 if priority == "high" else 7
                )

                request_approval(
                    action_type="improvement_approve",
                    action_data={
                        "proposal_id": proposal_id,
                        "title": title,
                        "file_path": file_path,
                        "severity": severity,
                        "risk_level": risk_level,
                    },
                    reason=f"Auto-generated from Code Sentinel scan: {message[:100]}",
                    requested_by="scan_pipeline",
                    priority=approval_priority,
                    tier=approval_tier,
                )
            except Exception as approval_err:
                logger.warning(
                    f"Approval queue submission failed for proposal #{proposal_id}: {approval_err}"
                )
```

**Step 2: Commit**

```bash
git add platform_v2/services/scan_pipeline.py
git commit -m "feat(scan_pipeline): route proposals through autonomy approval queue"
```

---

### Task 2: Add improvement_approve execution handler to agent_loop

**Files:**
- Modify: `ai_bridge/agent_loop.py`

**Step 1: Add the handler in _execute_approved_action()**

Find the `_execute_approved_action()` method (line 1411). Inside it, find the `elif action_type == "create_agent":` block (line 1591). AFTER that block's closing `except` (line 1603) and BEFORE the `else:` fallback (line 1605), insert:

```python
        elif action_type == "improvement_approve":
            # Approved improvement proposal — trigger the approve endpoint logic
            proposal_id = data.get("proposal_id")
            if not proposal_id:
                return {"executed": False, "error": "No proposal_id in action_data"}

            try:
                # Update proposal status to approved
                cur.execute(
                    """
                    UPDATE improvement_proposals
                    SET status = 'approved',
                        approved_at = NOW(),
                        reviewed_at = NOW()
                    WHERE id = %s AND status IN ('pending', 'proposed', 'pending_approval')
                    RETURNING id
                    """,
                    (proposal_id,),
                )
                result = cur.fetchone()
                conn.commit()

                if not result:
                    return {
                        "executed": False,
                        "error": f"Proposal #{proposal_id} not found or already processed",
                    }

                # Trigger Phase 4 auto-execution in background thread
                import threading
                import importlib

                def _run_auto_execute():
                    try:
                        import sys

                        sys.path.insert(0, "/mnt/archie_brain/platform_v2")
                        mod = importlib.import_module(
                            "tools.improvements.routes"
                        )
                        mod._auto_execute_proposal(proposal_id)
                    except Exception as exec_err:
                        logger.error(
                            f"Auto-execution failed for proposal #{proposal_id}: {exec_err}"
                        )

                thread = threading.Thread(
                    target=_run_auto_execute, daemon=True
                )
                thread.start()

                logger.info(
                    f"Improvement proposal #{proposal_id} approved via autonomy queue, "
                    f"auto-execution started"
                )
                return {"executed": True, "proposal_id": proposal_id}

            except Exception as imp_err:
                logger.error(f"Improvement approval execution failed: {imp_err}")
                return {"executed": False, "error": str(imp_err)}
```

**Step 2: Commit**

```bash
git add ai_bridge/agent_loop.py
git commit -m "feat(agent_loop): add improvement_approve execution handler"
```

---

### Task 3: Add proactive scan job to agent_loop

**Files:**
- Modify: `ai_bridge/agent_loop.py`

**Step 1: Add _run_proactive_scan() method**

Add this method to the `AgentLoop` class. Insert it BEFORE the `_run_ethics_monitoring()` method (around line 1613).

```python
    def _run_proactive_scan(self):
        """Proactive Code Sentinel scan — runs every 6h.

        Scans recently changed files, falls back to key platform files.
        Phase 4 hooks auto-create proposals from findings.
        """
        start = time.time()
        try:
            import subprocess

            # Get recently changed Python files (last 5 commits)
            try:
                result = subprocess.run(
                    ["git", "diff", "--name-only", "HEAD~5"],
                    capture_output=True,
                    text=True,
                    cwd="/mnt/archie_brain",
                    timeout=10,
                )
                changed_files = [
                    f
                    for f in result.stdout.strip().split("\n")
                    if f.endswith(".py")
                    and f.startswith("platform_v2/")
                    and not f.startswith("platform_v2/tools/_deprecated")
                ]
            except Exception:
                changed_files = []

            # Fallback: key platform files on rotation
            if not changed_files:
                import hashlib
                from datetime import datetime

                key_files = [
                    "platform_v2/app.py",
                    "ai_bridge/bridge_dispatcher.py",
                    "ai_bridge/agent_loop.py",
                    "platform_v2/tools/consciousness/routes.py",
                    "platform_v2/tools/dev_hq/routes.py",
                    "platform_v2/tools/improvements/routes.py",
                    "ai_bridge/code_generation_engine.py",
                    "ai_bridge/improvement_chat.py",
                ]
                # Rotate: pick 2 files based on current day
                day_hash = int(
                    hashlib.md5(
                        datetime.now().strftime("%Y-%m-%d").encode()
                    ).hexdigest()[:8],
                    16,
                )
                start_idx = day_hash % len(key_files)
                changed_files = [
                    key_files[start_idx % len(key_files)],
                    key_files[(start_idx + 1) % len(key_files)],
                ]

            # Limit to 3 files per run
            scan_files = changed_files[:3]

            scanned = 0
            for file_path in scan_files:
                try:
                    full_path = f"/mnt/archie_brain/{file_path}"
                    import os

                    if not os.path.exists(full_path):
                        continue

                    with open(full_path, "r") as f:
                        code_content = f.read()

                    # Use Code Sentinel's static analysis
                    import sys

                    sys.path.insert(0, "/mnt/archie_brain/platform_v2")
                    from tools.code_sentinel.routes import basic_static_analysis

                    analysis = basic_static_analysis(code_content, file_path)
                    issues = analysis.get("issues", [])

                    if not issues:
                        continue

                    # Store scan + issues in DB
                    conn = get_db()
                    cur = conn.cursor(cursor_factory=RealDictCursor)

                    cur.execute(
                        """
                        INSERT INTO code_scans (file_path, scan_type, issues_found,
                            security_issues, quality_score, scan_result, scanned_by)
                        VALUES (%s, 'proactive_scan', %s, %s, %s, %s, 'agent_loop')
                        RETURNING id
                        """,
                        (
                            file_path,
                            len(issues),
                            len(
                                [
                                    i
                                    for i in issues
                                    if i.get("type") == "security"
                                ]
                            ),
                            analysis.get("quality_score", 0),
                            json.dumps(analysis),
                        ),
                    )
                    scan_id = cur.fetchone()["id"]

                    for issue in issues:
                        cur.execute(
                            """
                            INSERT INTO code_issues (scan_id, file_path, line_number,
                                issue_type, severity, message, suggestion)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            """,
                            (
                                scan_id,
                                file_path,
                                issue.get("line"),
                                issue.get("type", "quality"),
                                issue.get("severity", "medium"),
                                issue.get("message", ""),
                                issue.get("suggestion", ""),
                            ),
                        )
                    conn.commit()
                    cur.close()
                    conn.close()

                    # Phase 4 pipeline hook
                    from services.scan_pipeline import process_scan_results

                    process_scan_results(scan_id, issues, file_path)
                    scanned += 1

                except Exception as scan_err:
                    logger.warning(
                        f"Proactive scan failed for {file_path}: {scan_err}"
                    )

            duration_ms = int((time.time() - start) * 1000)
            if scanned > 0:
                logger.info(
                    f"Proactive scan: {scanned}/{len(scan_files)} files scanned "
                    f"({duration_ms}ms)"
                )

        except Exception as e:
            logger.error(f"Proactive scan job failed: {e}")
```

**Step 2: Register the job in start()**

In the `start()` method, find the last `add_job` call (the training tick job, around line 353-358). AFTER it and BEFORE `self._running = True` (line 361), add:

```python
        self.scheduler.add_job(
            with_app_context(self._run_proactive_scan),
            trigger=IntervalTrigger(hours=6),
            id="agent_proactive_scan",
            name="Agent Loop: Proactive Code Scan",
            replace_existing=True,
        )
```

**Step 3: Add the job ID to the stop() cleanup list**

In `stop()`, find the list of job IDs (line 366-383). Add `"agent_proactive_scan"` to the list.

**Step 4: Update the job count log message**

Find `logger.info("Agent loop started with 16 jobs")` (line 362) and change `16` to `17`.

**Step 5: Commit**

```bash
git add ai_bridge/agent_loop.py
git commit -m "feat(agent_loop): add proactive code scan job (every 6h)"
```

---

### Task 4: Seed improvement_approve in tier1_auto_approve config

**Files:**
- Create: `database/migrations/XXX_add_improvement_approve_tier1.sql`

**Step 1: Create the migration**

```sql
-- Add improvement_approve to Tier 1 auto-approve types
-- This allows low-risk auto-generated improvement proposals to be approved automatically
UPDATE autonomy_config
SET config_value = jsonb_set(
    config_value,
    '{types}',
    (config_value->'types') || '["improvement_approve"]'::jsonb
),
    updated_at = NOW()
WHERE config_key = 'tier1_auto_approve'
  AND NOT (config_value->'types' @> '"improvement_approve"'::jsonb);
```

**Step 2: Run the migration**

```bash
docker exec -i archie_database psql -U archie -d archie < database/migrations/XXX_add_improvement_approve_tier1.sql
```

**Step 3: Commit**

```bash
git add database/migrations/
git commit -m "feat(db): add improvement_approve to tier1 auto-approve types"
```

---

### Task 5: Integration verification

**Step 1: Syntax check all modified files**

```bash
python3 -c "import ast; ast.parse(open('platform_v2/services/scan_pipeline.py').read()); print('scan_pipeline: OK')"
python3 -c "import ast; ast.parse(open('ai_bridge/agent_loop.py').read()); print('agent_loop: OK')"
```

**Step 2: Restart platform and verify startup**

```bash
docker compose restart archie_platform
sleep 15
docker logs archie_platform --tail 20 2>&1 | grep -i "proactive\|17 jobs\|Code Scan"
```

Expected: `Agent Loop: Proactive Code Scan` in scheduler output, `Agent loop started with 17 jobs`.

**Step 3: Test approval queue integration**

```bash
docker exec archie_platform python3 -c "
import sys
sys.path.insert(0, '/app')
from agent_loop import request_approval

# Test Tier 1 (low-risk) — should auto-approve
result = request_approval(
    action_type='improvement_approve',
    action_data={'proposal_id': 0, 'title': 'Test', 'severity': 'medium'},
    reason='Integration test',
    requested_by='test',
    priority=7,
    tier=1,
)
print('Tier-1 approval ID:', result)
"
```

Expected: prints an approval ID with `Tier-1 auto-approved` in logs.

**Step 4: Verify tier1 config**

```bash
docker exec archie_database psql -U archie -d archie -c \
  "SELECT config_value->'types' FROM autonomy_config WHERE config_key = 'tier1_auto_approve'"
```

Expected: list includes `improvement_approve`.

**Step 5: Test proactive scan directly**

```bash
docker exec archie_platform python3 -c "
import sys, os
sys.path.insert(0, '/app')
os.chdir('/mnt/archie_brain')
from agent_loop import AgentLoop
loop = AgentLoop.__new__(AgentLoop)
loop._run_proactive_scan()
print('Proactive scan completed')
"
```

**Step 6: Verify all modules load**

```bash
curl -s -b /tmp/archie_cookies.txt -w '%{http_code}' http://192.168.1.200:3000/dev-hq/ -o /dev/null
curl -s -b /tmp/archie_cookies.txt -w '%{http_code}' http://192.168.1.200:3000/tools/code_sentinel/ -o /dev/null
curl -s -b /tmp/archie_cookies.txt -w '%{http_code}' http://192.168.1.200:3000/tools/improvements-lab/ -o /dev/null
```

All should return 200.

**Step 7: Clean up test data and push**

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0, '/app')
from database import get_db_connection
with get_db_connection() as conn:
    cur = conn.cursor()
    cur.execute(\"DELETE FROM autonomy_approval_queue WHERE requested_by = 'test'\")
    print(f'Cleaned {cur.rowcount} test approvals')
    conn.commit()
    cur.close()
"

git add -A
git push
```

**Step 8: Update Dev HQ**

- Complete task #711
- Log ADR for the proactive loop
- Update project understanding for #101
