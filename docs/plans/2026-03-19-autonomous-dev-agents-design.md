# Autonomous Dev Agents — Code Fix Pipeline Design

**Task**: #1107 | **Date**: 2026-03-19 | **Status**: Design Document
**Author**: Claude (Opus 4.6) + Ky Tran
**Related**: Dev Pipeline module, Code Health scanner, Bridge Dispatcher, Agent Loop

---

## 1. Pipeline Flow

```
Code Health Scan (Job #40 — daily 3:00 AM via _daily_code_metrics_scan)
    │ scans all modules in /platform_v2/tools/, counts lines, checks patterns
    │ stores snapshots in code_metrics_snapshots table
    ▼
Pattern Compliance Check (Job #41 — daily 4:00 AM via _pattern_compliance_check)
    │ flags: direct Ollama calls, missing user_id, bare except, missing admin_required
    │ writes violations to code_audit_log table
    ▼
Improvement Engine (scan_routes.py → improvement_engine.py)
    │ _run_proactive_scan() (Job — every 6h) picks up scan results
    │ calls ImprovementEngine.analyze_and_propose()
    │ deduplication: _has_open_proposal() checks file_path + issue_type
    │ creates proposals in improvement_proposals table (status='proposed')
    │ critical/high → individual proposals, medium → weekly batch (Sunday 02:00)
    ▼
Human or Auto Approval
    │ Tier 1 (auto): pattern fixes, style fixes, simple refactors
    │ Tier 2 (human): security fixes, multi-file changes, architectural changes
    │ Telegram buttons: esc_approve_{id} / esc_deny_{id} / esc_defer_{id}
    │ status transitions: proposed → approved | rejected | deferred
    ▼
Agent Fix Job (NEW Job #48 — every 30 min via _process_approved_fixes)
    │ picks proposals WHERE status='approved' AND assigned_agent_id IS NULL
    │ ordered by: priority DESC, proposed_at ASC
    │ limit: 3 proposals per cycle (avoid overloading agents)
    ▼
Bridge Dispatcher
    │ dispatch(capability='code_fix', prompt=<fix_prompt>, module_id='dev_pipeline')
    │ routes to ENGINEERING station agent (Titan/qwen3-coder-cpu or fleet agent)
    │ creates bridge_job with metadata: {proposal_id, file_path, issue_type}
    ▼
Agent Executes Fix
    │ receives: file content, issue description, fix pattern, example
    │ returns: JSON {modified_code, explanation, confidence, files_changed}
    │ bridge_job updated: completed_steps=1, status='completed'
    ▼
Sandbox Validation (existing SandboxManager)
    │ sandbox_docker.py creates isolated Docker container
    │ sandbox_code_applicator.py applies the agent's modified code
    │ sandbox_test_runner.py runs: syntax check → import check → pattern compliance
    │ proposal updated: sandbox_test_passed, test_results_summary, test_duration_seconds
    ▼
Review Gate
    │ if tests pass AND confidence ≥ 0.8 AND single-file fix:
    │   → auto-queue for deployment (Tier 1)
    │ if tests pass AND (confidence < 0.8 OR multi-file):
    │   → Telegram notification with diff summary (Tier 2 human review)
    │ if tests fail:
    │   → retry_count++ (max 2 retries with refined prompt)
    │   → if still failing → escalation_status='needs_claude'
    ▼
Safe Deployment (existing safe_deployment_protocol.py)
    │ creates backup (backup_name, backup_created_at on proposal)
    │ applies fix to production code
    │ runs health check (health_check_passed, health_check_at)
    │ if health check fails → auto_rollback.py reverts from backup
    ▼
Post-Deploy
    │ proposal status → 'implemented', implemented_at = NOW()
    │ improvement_learning.py records what worked for future fixes
    │ Telegram notification: "Fix deployed: {title} by {agent_name}"
    │ code_audit_log entry with before/after line counts
```

---

## 2. Data Model

### 2.1 Tables Involved (all existing)

| Table | Role | Key Fields |
|-------|------|------------|
| `code_metrics_snapshots` | Daily scan results | module, lines, complexity, scanned_at |
| `code_audit_log` | Pattern violations found | module_name, category, issues_found, issues_fixed |
| `improvement_proposals` | Central tracking record | status, priority, assigned_agent_id, retry_count, escalation_status |
| `bridge_jobs` | Active agent work tracking | job_type='code_fix', agent_name, status, metadata (proposal_id) |
| `task_execution_log` | HR tracking of agent work | FK to bridge_jobs.id |
| `agent_discussions` | Multi-agent review (if needed) | FK to improvement_proposals.id |

### 2.2 Proposal Status Lifecycle

```
proposed ──┬── approved ──── agent_assigned ──── sandbox_testing ──┬── deploy_ready ──── deployed ──── implemented
           │                                                       │
           ├── rejected                                            ├── test_failed ──── retry (max 2) ──── needs_claude
           │                                                       │
           └── deferred                                            └── rollback_failed ──── needs_claude
```

**New statuses to add** (the table already has a varchar(50) status column with no CHECK constraint):
- `agent_assigned` — agent picked up the proposal, bridge_job created
- `sandbox_testing` — code applied to sandbox, tests running
- `deploy_ready` — tests passed, awaiting final approval or auto-deploy
- `test_failed` — sandbox tests failed (check retry_count)
- `needs_claude` — escalated for human/Claude intervention

### 2.3 Linking Agent Work to Proposals

The `improvement_proposals` table already has:
- `assigned_agent_id` (FK → agents.id) — which agent is working on it
- `contractor_agent_id` (FK → agents.id) — for cross-station agents
- `contractor_proposal` (JSONB) — agent's proposed fix details

The `bridge_jobs.metadata` JSONB field stores `proposal_id` to link back:
```json
{
  "proposal_id": 42,
  "file_path": "platform_v2/tools/consciousness/routes.py",
  "issue_type": "direct_ollama_call",
  "fix_pattern": "replace_direct_ollama"
}
```

---

## 3. Agent Prompt Template

### 3.1 System Prompt for Code Fix Agents

```
You are an ENGINEERING station agent on the A.R.C.H.I.E. platform.
Your task is to fix code issues identified by the automated Code Health scanner.

RULES:
1. Return ONLY valid JSON — no markdown, no explanation outside JSON.
2. Preserve the existing code style (indentation, naming conventions).
3. Make the MINIMUM change needed to fix the issue — do not refactor unrelated code.
4. If the fix requires changes to multiple files, list ALL files in files_changed.
5. If you are NOT confident the fix is correct, set confidence below 0.5.
6. ALL LLM calls must go through bridge_dispatcher.dispatch() — never call Ollama directly.
7. ALL database queries must use parameterized queries — never use f-strings for SQL.
```

### 3.2 User Prompt Template

```
FIX REQUEST
===========
Issue Type: {issue_type}
Priority: {priority}
File: {file_path}
Description: {description}

CURRENT CODE (lines {start_line}-{end_line}):
```{language}
{file_content}
```

FIX PATTERN:
{fix_pattern_description}

EXAMPLE (before → after):
```{language}
// BEFORE:
{example_before}

// AFTER:
{example_after}
```

CONTEXT:
- Module: {module_name}
- Related imports: {imports}
- Functions in scope: {functions}

Respond with JSON:
{
  "modified_code": "...full file content with fix applied...",
  "explanation": "...what was changed and why...",
  "confidence": 0.0-1.0,
  "files_changed": ["path/to/file.py"],
  "lines_modified": [45, 46, 47],
  "breaking_changes": false,
  "needs_import_changes": false,
  "suggested_tests": ["description of test to verify fix"]
}
```

### 3.3 Multi-File Fix Handling

For fixes spanning multiple files (e.g., adding admin_required to route + updating rbac.py):

1. **First dispatch**: Agent analyzes primary file, identifies all related files
2. **Response includes** `files_changed` array with all paths
3. **Job #48 detects** multi-file response → creates child proposals linked via `contractor_proposal` JSONB
4. **Each file** gets its own sandbox test cycle
5. **All-or-nothing deployment**: all child fixes must pass before any deploy

If `files_changed` count > 3, automatically escalate to `needs_claude` (too complex for local agent).

---

## 4. Fix Pattern Library

### 4.1 Pattern Format (stored in JSONB, could be a new table or knowledge_base entries)

```json
{
  "pattern_name": "replace_direct_ollama",
  "description": "Replace direct Ollama API calls with Bridge dispatcher",
  "severity": "high",
  "category": "adr_013_compliance",

  "target": {
    "type": "regex",
    "pattern": "requests\\.(post|get)\\(.*(11434|ollama).*(/api/generate|/api/chat)",
    "exclude": "/api/tags|/api/ps|/api/show"
  },

  "fix": {
    "type": "template",
    "template": "from ai_bridge.bridge_dispatcher import dispatch\nresult = dispatch(capability='{capability}', prompt={prompt_var}, module_id='{module_id}')\nresponse_text = result.response if result.success else ''",
    "variables": {
      "capability": "inferred from context (classify, generate, summarize, etc.)",
      "prompt_var": "the variable holding the prompt text",
      "module_id": "the module's blueprint name"
    }
  },

  "validation": {
    "must_not_contain": ["requests.post.*11434", "requests.get.*api/generate"],
    "must_contain": ["from ai_bridge.bridge_dispatcher import", "dispatch("],
    "syntax_check": true,
    "import_check": true
  },

  "example": {
    "before": "resp = requests.post('http://localhost:11434/api/generate', json={'model': 'llama3.2:3b', 'prompt': text})\nanswer = resp.json()['response']",
    "after": "from ai_bridge.bridge_dispatcher import dispatch\nresult = dispatch(capability='generate', prompt=text, module_id='my_module')\nanswer = result.response if result.success else ''"
  }
}
```

### 4.2 Predefined Fix Patterns

| # | Pattern Name | Target | Severity | Auto-fixable |
|---|-------------|--------|----------|-------------|
| 1 | `replace_direct_ollama` | Direct Ollama HTTP calls | High | Yes |
| 2 | `add_admin_required` | Routes missing `@admin_required` | High | Yes (single-file) |
| 3 | `sanitize_error_message` | `str(e)` in HTTP responses | Medium | Yes |
| 4 | `parameterize_sql` | f-string SQL queries | Critical | Yes |
| 5 | `add_user_id_scope` | SaaS queries without user_id filter | High | Needs review |
| 6 | `replace_bare_except` | `except:` without specific exception | Medium | Yes |
| 7 | `extract_inline_css` | `<style>` blocks in templates >50 lines | Low | Needs review |
| 8 | `add_input_validation` | Endpoints without request validation | Medium | Needs review |
| 9 | `fix_connection_leak` | DB connections without try/finally close | High | Yes |
| 10 | `add_rate_limiting` | Public endpoints without rate limits | Medium | Needs review |

### 4.3 Pattern Storage

Store patterns as `knowledge_base` entries with:
- `knowledge_type = 'fix_pattern'`
- `category = 'code_health'`
- `tags = ['fix-pattern', '{pattern_name}', '{severity}']`
- `content` = full JSON pattern definition
- Embedding enabled for semantic search when matching issues to patterns

---

## 5. Job #48 Specification

### 5.1 Registration (in agent_loop.py AgentLoop.start())

```python
self.scheduler.add_job(
    with_app_context(self._process_approved_fixes),
    trigger=IntervalTrigger(minutes=30),
    id="agent_approved_fixes",
    name="Agent Loop: Approved Fix Processor",
    replace_existing=True,
)
```

### 5.2 Implementation

```python
def _process_approved_fixes(self):
    """Job #48: Process approved improvement proposals by dispatching to coding agents."""
    try:
        from database import get_db_cursor
        from ai_bridge.bridge_dispatcher import get_dispatcher

        dispatcher = get_dispatcher()

        with get_db_cursor() as (conn, cur):
            # Pick up approved proposals not yet assigned to an agent
            cur.execute("""
                SELECT id, title, description, category, priority,
                       code_changes, file_path, plan_steps,
                       retry_count, required_skills
                FROM improvement_proposals
                WHERE status = 'approved'
                  AND assigned_agent_id IS NULL
                  AND retry_count < 3
                ORDER BY
                    CASE priority
                        WHEN 'critical' THEN 1
                        WHEN 'high' THEN 2
                        WHEN 'medium' THEN 3
                        WHEN 'low' THEN 4
                    END,
                    proposed_at ASC
                LIMIT 3
            """)
            proposals = cur.fetchall()

        if not proposals:
            logger.debug("[Fix Processor] No approved proposals to process")
            return

        for proposal in proposals:
            try:
                self._dispatch_fix_to_agent(proposal, dispatcher)
            except Exception as e:
                logger.error(f"[Fix Processor] Failed proposal #{proposal['id']}: {e}")
                # Mark as failed, increment retry
                with get_db_cursor(commit=True) as (conn, cur):
                    cur.execute("""
                        UPDATE improvement_proposals
                        SET retry_count = retry_count + 1,
                            last_retry_at = NOW(),
                            status = CASE
                                WHEN retry_count >= 2 THEN 'needs_claude'
                                ELSE 'approved'
                            END,
                            escalation_status = CASE
                                WHEN retry_count >= 2 THEN 'human_only'
                                ELSE escalation_status
                            END
                        WHERE id = %s
                    """, (proposal['id'],))

    except Exception as e:
        logger.error(f"[Fix Processor] Job failed: {e}")
```

### 5.3 Fix Dispatch Method

```python
def _dispatch_fix_to_agent(self, proposal, dispatcher):
    """Dispatch a single fix proposal to a coding agent via Bridge."""
    from database import get_db_cursor
    import json

    proposal_id = proposal['id']
    file_path = proposal.get('file_path') or proposal.get('code_changes', '')

    # 1. Read the target file
    try:
        with open(f"/mnt/archie_brain/{file_path}", 'r') as f:
            file_content = f.read()
    except FileNotFoundError:
        logger.warning(f"[Fix Processor] File not found: {file_path}")
        return

    # 2. Find matching fix pattern from knowledge_base
    fix_pattern = self._find_fix_pattern(proposal['category'])

    # 3. Build the prompt
    prompt = self._build_fix_prompt(proposal, file_content, fix_pattern)

    system_prompt = (
        "You are an ENGINEERING station agent on A.R.C.H.I.E. "
        "Fix the code issue described. Return ONLY valid JSON with keys: "
        "modified_code, explanation, confidence (0-1), files_changed (array), "
        "lines_modified (array of line numbers), breaking_changes (bool)."
    )

    # 4. Mark proposal as assigned
    with get_db_cursor(commit=True) as (conn, cur):
        # Find available ENGINEERING agent
        cur.execute("""
            SELECT a.id, a.name FROM agents a
            JOIN station_assignments sa ON a.id = sa.agent_id
            WHERE sa.station_code = 'ENGINEERING'
              AND a.shift_state = 'active'
              AND sa.is_active = true
            ORDER BY a.name
            LIMIT 1
        """)
        agent = cur.fetchone()

        if not agent:
            logger.warning("[Fix Processor] No active ENGINEERING agent")
            return

        cur.execute("""
            UPDATE improvement_proposals
            SET status = 'agent_assigned',
                assigned_agent_id = %s
            WHERE id = %s
        """, (agent['id'], proposal_id))

    # 5. Dispatch to agent via Bridge
    result = dispatcher.request_work(
        capability='code_fix',
        prompt=prompt,
        module_id='dev_pipeline',
        system_prompt=system_prompt,
        json_mode=True,
    )

    if not result.success:
        logger.error(f"[Fix Processor] Dispatch failed for proposal #{proposal_id}: {result.error}")
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute("""
                UPDATE improvement_proposals
                SET status = 'approved', assigned_agent_id = NULL,
                    retry_count = retry_count + 1,
                    last_retry_at = NOW()
                WHERE id = %s
            """, (proposal_id,))
        return

    # 6. Parse agent response
    try:
        fix_data = json.loads(result.response)
    except json.JSONDecodeError:
        logger.error(f"[Fix Processor] Invalid JSON from agent for proposal #{proposal_id}")
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute("""
                UPDATE improvement_proposals
                SET status = 'approved', assigned_agent_id = NULL,
                    retry_count = retry_count + 1
                WHERE id = %s
            """, (proposal_id,))
        return

    # 7. Store agent's fix in proposal
    with get_db_cursor(commit=True) as (conn, cur):
        from psycopg2.extras import Json
        cur.execute("""
            UPDATE improvement_proposals
            SET contractor_proposal = %s,
                status = 'sandbox_testing'
            WHERE id = %s
        """, (Json(fix_data), proposal_id))

    # 8. Submit to sandbox for testing
    self._submit_to_sandbox(proposal_id, fix_data, file_path)
```

### 5.4 Sandbox Submission

```python
def _submit_to_sandbox(self, proposal_id, fix_data, file_path):
    """Apply agent's fix to sandbox and run tests."""
    from database import get_db_cursor
    from psycopg2.extras import Json

    try:
        # Use existing SandboxDocker to create isolated environment
        from tools.dev_pipeline.services.sandbox_docker import SandboxDocker
        from tools.dev_pipeline.services.sandbox_test_runner import SandboxTestRunner

        sandbox = SandboxDocker()
        container_id = sandbox.create_sandbox(proposal_id)

        # Apply the modified code
        sandbox.write_file(container_id, file_path, fix_data['modified_code'])

        # Run tests
        runner = SandboxTestRunner()
        test_results = runner.run_tests(container_id, [
            'syntax_check',      # Python syntax validation
            'import_check',      # All imports resolve
            'pattern_compliance', # ADR-013, admin_required, etc.
            'unit_tests',        # If module has tests
        ])

        passed = all(r['passed'] for r in test_results)
        confidence = fix_data.get('confidence', 0.0)
        files_changed = fix_data.get('files_changed', [file_path])

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute("""
                UPDATE improvement_proposals
                SET sandbox_test_passed = %s,
                    test_results_summary = %s,
                    test_duration_seconds = %s,
                    status = CASE
                        WHEN %s AND %s >= 0.8 AND array_length(%s, 1) <= 1
                            THEN 'deploy_ready'
                        WHEN %s
                            THEN 'deploy_ready'
                        ELSE 'test_failed'
                    END
                WHERE id = %s
            """, (
                passed,
                Json(test_results),
                sum(r.get('duration_ms', 0) for r in test_results) // 1000,
                passed, confidence, files_changed,  # auto-deploy criteria
                passed,  # manual review criteria
                proposal_id,
            ))

        # Clean up sandbox
        sandbox.destroy_sandbox(container_id)

        # Notify via Telegram
        if passed:
            self._notify_fix_ready(proposal_id, fix_data, confidence)
        else:
            # Retry with failure context
            self._handle_test_failure(proposal_id, test_results)

    except Exception as e:
        logger.error(f"[Fix Processor] Sandbox failed for proposal #{proposal_id}: {e}")
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute("""
                UPDATE improvement_proposals
                SET status = 'test_failed',
                    retry_count = retry_count + 1,
                    test_failure_context = %s
                WHERE id = %s
            """, (Json({'error': str(e)}), proposal_id))
```

### 5.5 Failure Handling

| Retry # | Action |
|---------|--------|
| 0 (first attempt) | Dispatch to agent with original prompt |
| 1 | Re-dispatch with test failure context appended to prompt |
| 2 | Re-dispatch with explicit hint: "Previous attempts failed because: {reasons}" |
| 3+ | Set `escalation_status='needs_claude'`, stop retrying |

On retry, the prompt includes:
```
PREVIOUS ATTEMPT FAILED
========================
Test Results: {test_results_summary}
Failure Reason: {test_failure_context}

Please fix the code again, addressing these specific test failures.
```

### 5.6 Reporting

After each Job #48 cycle, if any proposals were processed:

```python
# Telegram summary
summary = f"🔧 Fix Processor: {processed} proposals processed\n"
summary += f"✅ Passed: {passed_count} | ❌ Failed: {failed_count}\n"
summary += f"⏳ Pending sandbox: {sandbox_count}\n"
for p in completed:
    summary += f"  • #{p['id']} {p['title']} → {p['status']}\n"
```

---

## 6. Escalation to Claude

### 6.1 When to Escalate

| Condition | Action |
|-----------|--------|
| `retry_count >= 3` | Auto-escalate: `escalation_status = 'needs_claude'` |
| `files_changed` count > 3 | Auto-escalate: too many files for local agent |
| Agent confidence < 0.3 | Auto-escalate: agent is unsure |
| Architectural change detected | Auto-escalate: keywords like "move", "rename module", "new table" |
| `category = 'security'` and `priority = 'critical'` | Always escalate: security-critical fixes need human review |

### 6.2 How Claude Picks It Up

**Option A — Dashboard (Dev HQ)**:
- Dev Pipeline → Proposals tab shows `needs_claude` proposals with red badge
- Filter: `?status=needs_claude` in URL
- One-click to view full context: issue, agent attempts, test failures, diff

**Option B — MCP Tool (next session)**:
```
mcp get_my_tasks → shows tasks linked to needs_claude proposals
mcp search_knowledge "needs_claude proposals" → finds the proposals
```

**Option C — Session Start Auto-Brief**:
- Agent Loop Job #47 (briefing generator) includes `needs_claude` count in daily brief
- Claude's first action in each session: check for escalated proposals
- Query: `SELECT * FROM improvement_proposals WHERE escalation_status = 'needs_claude' ORDER BY priority, proposed_at`

### 6.3 Claude Resolution Flow

1. Claude reads proposal + all agent attempts (stored in `contractor_proposal` JSONB)
2. Claude makes the fix directly (file edits)
3. Claude runs sandbox tests manually or commits directly
4. Claude updates proposal: `status = 'implemented'`, `escalation_status = 'resolved'`
5. Claude calls `mcp complete_task` with notes on what the local agent couldn't handle
6. Optionally: Claude creates a new fix pattern in knowledge_base so the agent can handle similar issues next time

---

## 7. Security

### 7.1 Sandbox Isolation

- **Docker containers**: Each sandbox runs in an isolated Docker container (existing `SandboxDocker` class)
- **No network access**: Sandbox containers have no network (prevents data exfiltration)
- **Read-only mounts**: Production code mounted read-only; agent writes to sandbox copy
- **Time limit**: Sandbox auto-destroyed after 5 minutes (existing timeout in SandboxDocker)
- **Resource limits**: CPU=1 core, RAM=512MB per sandbox container

### 7.2 Approval Gates

| Fix Type | Approval Level | Who Approves |
|----------|---------------|--------------|
| Style/lint fixes (low severity) | Tier 1 (auto) | Agent Loop auto-approves if tests pass + confidence ≥ 0.9 |
| Pattern compliance (medium) | Tier 1.5 | Auto-deploy if tests pass, Telegram notification after |
| Security fixes (high/critical) | Tier 2 (human) | Admin via Telegram or Dashboard — must approve before deploy |
| Multi-file changes | Tier 2 (human) | Admin reviews full diff |
| New imports or dependencies | Tier 2 (human) | Could introduce vulnerabilities |

### 7.3 Rollback Mechanism

Existing `auto_rollback.py` and `safe_deployment_protocol.py` handle this:

1. **Pre-deploy backup**: `safe_deployment_protocol.py` creates file backup, records in proposal (`backup_name`, `backup_created_at`)
2. **Health check**: After deploy, run health check endpoint. If `health_check_passed = false`:
   - `auto_rollback.py` reverts files from backup
   - Proposal status → `rollback_completed`
   - Telegram alert: "Rollback triggered for proposal #{id}: {reason}"
3. **Git safety**: All deploys create a git commit with message `[auto-fix] {proposal_title} (proposal #{id})`
   - Rollback = `git revert {commit_hash}` (non-destructive)
4. **Cooldown**: After any rollback, disable auto-deploy for 1 hour (require human approval for all fixes)

### 7.4 Audit Trail

Every step is logged:
- `improvement_proposals` tracks full lifecycle with timestamps
- `bridge_jobs` tracks agent dispatch and execution
- `task_execution_log` records tokens used, duration, agent performance
- `code_audit_log` records before/after metrics
- `governance_audit_log` records approval decisions (IAAE compliance)

---

## 8. Capability Registration

Add `code_fix` to the Bridge dispatcher's capability → station mapping:

```python
# In bridge_dispatcher.py CAPABILITY_STATION_MAP
'code_fix': 'ENGINEERING',
'code_review': 'ENGINEERING',
'code_analysis': 'ENGINEERING',
```

Ensure ENGINEERING station agents (currently: Titan with qwen3-coder-cpu) have the `code_fix` skill registered in the `agent_skills` table.

---

## 9. New Components Summary

| Component | Type | Location | Description |
|-----------|------|----------|-------------|
| `_process_approved_fixes()` | Agent Loop Job #48 | `ai_bridge/agent_loop.py` | Main job: picks approved proposals, dispatches to agents |
| `_dispatch_fix_to_agent()` | Helper method | `ai_bridge/agent_loop.py` | Builds prompt, dispatches via Bridge |
| `_submit_to_sandbox()` | Helper method | `ai_bridge/agent_loop.py` | Applies fix to sandbox, runs tests |
| `_find_fix_pattern()` | Helper method | `ai_bridge/agent_loop.py` | Looks up fix pattern from knowledge_base |
| `_build_fix_prompt()` | Helper method | `ai_bridge/agent_loop.py` | Constructs agent prompt from template |
| `_handle_test_failure()` | Helper method | `ai_bridge/agent_loop.py` | Manages retry logic and escalation |
| `_notify_fix_ready()` | Helper method | `ai_bridge/agent_loop.py` | Sends Telegram notification with diff |
| Fix patterns | Knowledge entries | `knowledge_base` table | 10 predefined fix patterns (type='fix_pattern') |
| `code_fix` capability | Config | `bridge_dispatcher.py` | Maps code_fix → ENGINEERING station |

### Estimated Implementation Effort

| Phase | Work | Estimate |
|-------|------|----------|
| Phase 1 | Job #48 + dispatch + sandbox integration | 2-3 sessions |
| Phase 2 | Fix pattern library (10 patterns in KB) | 1 session |
| Phase 3 | Telegram notifications + dashboard UI | 1 session |
| Phase 4 | Auto-deploy for Tier 1 fixes | 1 session |
| Phase 5 | Escalation to Claude workflow | 1 session |
| **Total** | | **6-7 sessions** |

---

## 10. Success Criteria

- [ ] Job #48 runs every 30 min, picks up approved proposals
- [ ] Agent successfully fixes at least 3 pattern types (direct Ollama, bare except, str(e))
- [ ] Sandbox catches broken fixes before they reach production
- [ ] Auto-rollback triggers within 60s if health check fails
- [ ] Escalation to Claude works: needs_claude proposals visible in Dev HQ
- [ ] Full audit trail: every fix traceable from scan → proposal → agent → sandbox → deploy
- [ ] Zero production incidents caused by agent-applied fixes (sandbox catches all)
