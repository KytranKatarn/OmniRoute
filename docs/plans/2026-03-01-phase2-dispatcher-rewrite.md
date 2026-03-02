# Phase 2: Bridge Dispatcher Rewrite — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace all 12 direct `archie_bridge()` calls in Code Sentinel and Improvement Labs with `dispatcher.request_work()` so all AI work flows through the Bridge Command dispatcher pipeline.

**Architecture:** Direct replacement — each `archie_bridge()` call becomes a `dispatcher.request_work()` call with the appropriate capability, module_id, and parameters. The dispatcher handles agent selection, welfare, escalation, HR tracking, and IAAE governance internally. No new abstractions needed.

**Tech Stack:** Python/Flask, `ai_bridge.bridge_dispatcher.get_dispatcher()`, `DispatchResult` dataclass

**Design Doc:** `docs/plans/2026-03-01-phase2-dispatcher-rewrite-design.md`

---

## Files to Modify

| File | archie_bridge calls | Capabilities |
|------|-------------------|--------------|
| `platform_v2/tools/code_sentinel/routes.py` | 3 direct + 2 bridge routing | `code_review` |
| `ai_bridge/code_generation_engine.py` | 4 direct | `code_analysis`, `code` |
| `ai_bridge/team_consensus_orchestrator.py` | 1 direct | `code_review` |
| `ai_bridge/improvement_chat.py` | 3 direct + 2 delegation wrappers | `conversation` |

---

### Task 1: Rewrite Code Sentinel — `scan_file()` (3 calls → 1)

**Files:**
- Modify: `platform_v2/tools/code_sentinel/routes.py` lines 30-40 (imports), 460-575 (scan_file AI section)

**Step 1: Replace imports**

Remove the old bridge routing imports (lines 30-40):
```python
# REMOVE:
try:
    from ai_bridge.archie_bridge import (
        route_task_to_station,
        execute_agent_task,
        get_available_agent_for_station,
    )
    BRIDGE_ROUTING_AVAILABLE = True
except ImportError:
    BRIDGE_ROUTING_AVAILABLE = False
```

Replace with:
```python
# Bridge Command dispatcher — all AI work routes through here
try:
    from ai_bridge.bridge_dispatcher import get_dispatcher
    _dispatcher = get_dispatcher()
    BRIDGE_ROUTING_AVAILABLE = True
except Exception:
    _dispatcher = None
    BRIDGE_ROUTING_AVAILABLE = False
```

**Step 2: Replace the 3-layer AI section in scan_file()**

Replace the entire AI section (lines 456-558) — from `# STEP 2: Try AI analysis` through the fallback `archie_bridge` block — with a single dispatcher call:

```python
        # STEP 2: Try AI analysis via Bridge Command dispatcher
        ai_result = None
        agent_used = None

        if BRIDGE_ROUTING_AVAILABLE and _dispatcher:
            try:
                ai_content = (
                    code_content[:10000] + "\n... (truncated)"
                    if len(code_content) > 10000
                    else code_content
                )

                prompt = f"""Analyze this code for issues. Return a JSON object with:
{{
    "quality_score": 0-100,
    "issues": [
        {{
            "line": line_number or null,
            "type": "security|quality|style|performance",
            "severity": "critical|high|medium|low",
            "message": "description of issue",
            "suggestion": "how to fix it"
        }}
    ],
    "summary": "brief summary"
}}

File: {file_path}
```
{ai_content}
```

Only return valid JSON, no other text."""

                result = _dispatcher.request_work(
                    capability="code_review",
                    prompt=prompt,
                    module_id="code_sentinel",
                    json_mode=True,
                    user_id=user_id,
                )

                if result.success:
                    response_text = result.response
                    if "```json" in response_text:
                        response_text = response_text.split("```json")[1].split("```")[0]
                    elif "```" in response_text:
                        response_text = response_text.split("```")[1].split("```")[0]

                    ai_result = json.loads(response_text.strip())
                    analysis_type = "ai_powered"
                    agent_used = {
                        "name": result.agent_name,
                        "station": result.station_code,
                        "model": result.model_used,
                    }
                    logger.info(
                        f"AI analysis completed for {file_path} via {result.agent_name} ({result.model_used})"
                    )
                else:
                    logger.warning(f"Dispatcher returned failure for {file_path}: {result.error}")

            except json.JSONDecodeError as e:
                logger.warning(f"AI returned invalid JSON for {file_path}: {e}")
            except Exception as e:
                logger.warning(f"AI analysis failed for {file_path}: {e}")
```

**Step 3: Verify scan_file works**

Run inside container:
```bash
docker exec archie_platform python3 -c "
import requests, json
r = requests.post('http://localhost:3000/tools/code_sentinel/api/health/scan',
    json={'file_path': 'platform_v2/app.py'},
    cookies={'session': 'test'})
print(r.status_code, r.json().get('analysis_type', 'unknown'))
"
```
Expected: 200 with analysis_type "ai_powered" or "static" (either is valid).

**Step 4: Commit**

```bash
git add platform_v2/tools/code_sentinel/routes.py
git commit -m "refactor(code-sentinel): replace scan_file archie_bridge calls with dispatcher.request_work()"
```

---

### Task 2: Rewrite Code Sentinel — `_run_multi_agent_review()` (1 call)

**Files:**
- Modify: `platform_v2/tools/code_sentinel/routes.py` lines 1444-1555

**Step 1: Replace the worker function**

In `_run_multi_agent_review()`, replace the `run_single_agent()` inner function. The key change is replacing lines 1449-1516 (the import + bridge call + manual log_external_call):

Replace the worker's AI section (inside `run_single_agent`, after building the prompt):
```python
            try:
                result = _dispatcher.request_work(
                    capability="code_review",
                    prompt=prompt,
                    module_id="code_sentinel",
                    system_prompt=prompt_prefix,
                    json_mode=True,
                )

                if not result.success:
                    raise RuntimeError(f"Dispatch failed: {result.error}")

                response_text = result.response
                if "```json" in response_text:
                    response_text = response_text.split("```json")[1].split("```")[0]
                elif "```" in response_text:
                    response_text = response_text.split("```")[1].split("```")[0]

                parsed = json.loads(response_text.strip())

                with review_lock:
                    review["agent_reviews"][agent_key] = {
                        "agent_name": agent_name,
                        "model": result.model_used,
                        "issues": parsed.get("issues", []),
                        "summary": parsed.get("summary", ""),
                        "quality_score": parsed.get("quality_score", 0),
                        "completed_at": datetime.now().isoformat(),
                    }
                    for issue in parsed.get("issues", []):
                        all_issues.append({**issue, "found_by": agent_name})

                return parsed
```

Also remove the old imports inside the function:
- Remove line 1449: `sys.path.insert(0, "/mnt/archie_brain/ai_bridge")`
- Remove line 1450: `from archie_bridge import archie_bridge`
- Remove lines 1469-1472: The inner `get_dispatcher` import + model selection (the dispatcher now handles model selection)

**Step 2: Verify multi-agent review works**

Run inside container — trigger a multi-agent review via the API:
```bash
docker exec archie_platform python3 -c "
import requests, json
# This just verifies the function can be imported without errors
from tools.code_sentinel.routes import _run_multi_agent_review
print('Import OK')
"
```

**Step 3: Commit**

```bash
git add platform_v2/tools/code_sentinel/routes.py
git commit -m "refactor(code-sentinel): replace multi-agent review archie_bridge with dispatcher"
```

---

### Task 3: Rewrite code_generation_engine.py (4 calls)

**Files:**
- Modify: `ai_bridge/code_generation_engine.py` lines 22-23 (import), 44-50 (_get_code_model), 509-514, 531-536, 581-586, 929-934

**Step 1: Replace top-level import (line 22-23)**

```python
# REMOVE:
sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
from archie_bridge import archie_bridge

# ADD:
from ai_bridge.bridge_dispatcher import get_dispatcher
_dispatcher = get_dispatcher()
```

**Step 2: Simplify _get_code_model (lines 44-50)**

The method already queries the dispatcher but with bare `from bridge_dispatcher` import. Replace:
```python
    @classmethod
    def _get_code_model(cls):
        """Get the code model from BridgeDispatcher."""
        try:
            return _dispatcher.get_model_for_capability("code") if _dispatcher else "qwen3-coder-cpu:latest"
        except Exception:
            return "qwen3-coder-cpu:latest"
```

**Step 3: Replace Architect call (line 509-514)**

```python
        # BEFORE:
        architect_result = archie_bridge(
            prompt=architect_prompt,
            user_id=4,
            enable_memory=True,
            force_model=model,
        )

        if not architect_result.get("success"):
            return None

        architect_output = architect_result["response"]

        # AFTER:
        architect_result = _dispatcher.request_work(
            capability="code_analysis",
            prompt=architect_prompt,
            module_id="improvement_labs",
            user_id=4,
        )

        if not architect_result.success:
            return None

        architect_output = architect_result.response
```

**Step 4: Replace Editor call (line 531-536)**

```python
        # AFTER:
        editor_result = _dispatcher.request_work(
            capability="code",
            prompt=editor_prompt,
            module_id="improvement_labs",
            user_id=4,
        )

        if not editor_result.success:
            return None

        changes = self._parse_code_changes_from_response(
            editor_result.response, category="general"
        )
```

**Step 5: Replace Retry call (line 581-586)**

```python
        # AFTER:
        result = _dispatcher.request_work(
            capability="code",
            prompt=retry_prompt,
            module_id="improvement_labs",
            user_id=4,
        )

        if not result.success:
            return None

        changes = self._parse_code_changes_from_response(
            result.response, category="general"
        )
```

**Step 6: Replace Legacy V1 call (line 929-934)**

```python
        # AFTER:
        result = _dispatcher.request_work(
            capability="code",
            prompt=prompt,
            module_id="improvement_labs",
            user_id=4,
        )

        if not result.success:
            return {
                "success": False,
                "error": result.error or "Code generation failed",
            }

        ai_response = result.response
```

**Step 7: Verify import works**

```bash
docker exec archie_platform python3 -c "
from ai_bridge.code_generation_engine import CodeGenerationEngine
print('Import OK, model:', CodeGenerationEngine._get_code_model())
"
```

**Step 8: Commit**

```bash
git add ai_bridge/code_generation_engine.py
git commit -m "refactor(code-gen-engine): replace 4 archie_bridge calls with dispatcher.request_work()"
```

---

### Task 4: Rewrite team_consensus_orchestrator.py (1 call)

**Files:**
- Modify: `ai_bridge/team_consensus_orchestrator.py` lines 257, 355-364

**Step 1: Replace the import and call**

Replace line 257 (inside `_real_evaluation`):
```python
            # REMOVE:
            from ai_bridge.archie_bridge import archie_bridge

            # ADD:
            from ai_bridge.bridge_dispatcher import get_dispatcher
            _dispatcher = get_dispatcher()
```

Replace lines 355-364 (the archie_bridge call):
```python
            # BEFORE:
            result = archie_bridge(
                prompt=eval_prompt,
                system_prompt=eval_system_prompt,
                agent_id=agent_id,
                user_id=user_id,
                force_model=model,
                try_local_first=True,
                task_type="evaluation",
                enable_memory=False,
            )

            if not result.get("success"):

            # AFTER:
            result = _dispatcher.request_work(
                capability="code_review",
                prompt=eval_prompt,
                module_id="improvement_labs",
                system_prompt=eval_system_prompt,
                user_id=user_id,
                prefer_agent=agent_name,
            )

            if not result.success:
```

Also update the response parsing (line 375):
```python
            # BEFORE:
            response_text = result.get("response", "")

            # AFTER:
            response_text = result.response or ""
```

**Step 2: Update docstrings/comments referencing archie_bridge**

Replace occurrences of "archie_bridge" in docstrings (lines 244, 350, 368, 406, 553, 563, 818) with "Bridge dispatcher".

**Step 3: Verify import works**

```bash
docker exec archie_platform python3 -c "
from ai_bridge.team_consensus_orchestrator import TeamConsensusOrchestrator
print('Import OK')
"
```

**Step 4: Commit**

```bash
git add ai_bridge/team_consensus_orchestrator.py
git commit -m "refactor(team-consensus): replace archie_bridge eval with dispatcher.request_work()"
```

---

### Task 5: Rewrite improvement_chat.py (3 calls + 2 delegation wrappers)

**Files:**
- Modify: `ai_bridge/improvement_chat.py` lines 84-86, 704, 818-823, 392-401

**Step 1: Add dispatcher import at top of file**

Add near other imports:
```python
from ai_bridge.bridge_dispatcher import get_dispatcher

_dispatcher = get_dispatcher()
```

**Step 2: Replace fallback delegation wrapper (lines 84-86)**

```python
    # BEFORE:
    def execute_with_delegation(task, user_id=None, **kwargs):
        result = archie_bridge(task, user_id=user_id, enable_memory=True)
        return {
            "success": result.get("success", False),
            "response": result.get("response", ""),

    # AFTER:
    def execute_with_delegation(task, user_id=None, **kwargs):
        if _dispatcher:
            dr = _dispatcher.request_work(
                capability="conversation",
                prompt=task,
                module_id="improvement_labs",
                user_id=user_id,
            )
            return {"success": dr.success, "response": dr.response or ""}
        return {"success": False, "response": "Dispatcher unavailable"}
```

**Step 3: Replace discuss_proposal() call (line 704)**

```python
    # BEFORE:
    result = archie_bridge(prompt=context_prompt, user_id=user_id, enable_memory=True)

    if not result.get("success"):
        return result

    # AFTER:
    result = _dispatcher.request_work(
        capability="conversation",
        prompt=context_prompt,
        module_id="improvement_labs",
        user_id=user_id,
    )

    if not result.success:
        return {"success": False, "error": result.error or "Dispatch failed"}
```

Also update subsequent references from `result.get("response")` / `result["response"]` to `result.response`.

**Step 4: Replace self_reflection_chat() call (lines 818-823)**

```python
    # BEFORE:
    result = archie_bridge(
        prompt=reflection_prompt,
        user_id=user_id,
        enable_memory=True,
        force_model=_default_conversation_model(),
    )

    # AFTER:
    result = _dispatcher.request_work(
        capability="conversation",
        prompt=reflection_prompt,
        module_id="improvement_labs",
        user_id=user_id,
    )
```

Also update subsequent `result.get(...)` to `result.success` / `result.response`.

**Step 5: Remove the archie_bridge import**

Find and remove:
```python
from archie_bridge import archie_bridge
```

**Step 6: Verify import works**

```bash
docker exec archie_platform python3 -c "
from ai_bridge.improvement_chat import chat_about_improvements
print('Import OK')
"
```

**Step 7: Commit**

```bash
git add ai_bridge/improvement_chat.py
git commit -m "refactor(improvement-chat): replace 3 archie_bridge calls with dispatcher.request_work()"
```

---

### Task 6: Integration Verification & Cleanup

**Files:**
- Verify: All 4 modified files
- Check: No remaining `archie_bridge` imports in modified files

**Step 1: Grep for remaining archie_bridge usage in modified files**

```bash
grep -n "archie_bridge" platform_v2/tools/code_sentinel/routes.py ai_bridge/code_generation_engine.py ai_bridge/team_consensus_orchestrator.py ai_bridge/improvement_chat.py
```
Expected: Only docstrings/comments, no function calls or imports.

**Step 2: Restart platform and verify all modules load**

```bash
docker compose restart archie_platform
# Wait 10s for startup
docker logs --tail 5 archie_platform | grep "Loaded module"
```
Expected: All 34 modules load successfully.

**Step 3: Test each module loads in browser**

```bash
# Login and test
curl -s -c /tmp/cookies.txt -X POST http://192.168.1.200:3000/login \
  -d "username=admin&password=Kyt%2413ran2025" -o /dev/null

for route in "/tools/code_sentinel/" "/tools/improvements-lab/"; do
  STATUS=$(curl -s -b /tmp/cookies.txt -o /dev/null -w "%{http_code}" "http://192.168.1.200:3000$route")
  echo "$route → $STATUS"
done
```
Expected: Both return 200.

**Step 4: Run a Code Sentinel scan to verify end-to-end**

```bash
curl -s -b /tmp/cookies.txt -X POST http://192.168.1.200:3000/tools/code_sentinel/api/health/scan \
  -H "Content-Type: application/json" \
  -d '{"file_path": "platform_v2/database.py"}' | python3 -m json.tool | head -20
```
Expected: JSON response with `analysis_type` field.

**Step 5: Commit final state**

```bash
git add -A
git commit -m "refactor(phase2): complete dispatcher rewrite for Code Sentinel + Improvement Labs

Replaces 12 direct archie_bridge() calls across 4 files with
dispatcher.request_work() for unified Bridge Command pipeline routing.

Files: code_sentinel/routes.py, code_generation_engine.py,
team_consensus_orchestrator.py, improvement_chat.py

Project #101 Tasks #705, #706"
```

**Step 6: Update Dev HQ**

Use MCP tools:
- `complete_task` for #705 (Code Sentinel) and #706 (Improvement Labs)
- `log_decision` for ADR-074 documenting the rewrite
- `update_project_understanding` for Project #101
