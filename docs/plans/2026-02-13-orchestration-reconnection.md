# Orchestration Reconnection Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reconnect the orchestration engine to Bridge stations, Team Management agents, node routing, and IAAE governance so the entire AI pipeline works as designed.

**Architecture:** Fix local hub infrastructure first (.env, models, agent selection), then wire orchestration into Bridge/Team station assignments with node_router integration, then reconnect .246 as a proper mesh node with hub-approved delegation.

**Tech Stack:** Python/Flask, PostgreSQL, Ollama, Docker

---

## Phase A: Fix Local Orchestration

### Task 1: Fix .env Ollama routing

**Files:**
- Modify: `/mnt/archie_brain/.env:30-32`
- Modify: `/mnt/archie_brain/platform_v2/.env:30-32`

**Step 1: Update root .env**

Replace lines 30-32:
```
# Ollama Servers
OLLAMA_PRIMARY=192.168.1.246:11434
OLLAMA_SECONDARY=192.168.1.245:11434
```
With:
```
# Ollama — local instance on ARCHIE host (accessed from Docker via host.docker.internal)
OLLAMA_PRIMARY=host.docker.internal:11434
OLLAMA_HOST=http://host.docker.internal:11434
ARCHIE_CHAT_MODEL=dolphin3:latest
```

**Step 2: Update platform_v2 .env**

Same replacement in `/mnt/archie_brain/platform_v2/.env` lines 30-32.

**Step 3: Commit**
```bash
git add .env platform_v2/.env
git commit -m "fix(env): point OLLAMA_PRIMARY to local host, remove legacy .246/.245 defaults"
```

---

### Task 2: Fix smart_router default model

**Files:**
- Modify: `/mnt/archie_brain/ai_bridge/smart_router.py:72`

**Step 1: Change default local model**

Replace:
```python
        model_name='deepseek-coder-v2:16b',
```
With:
```python
        model_name='dolphin3:latest',
```

This is line 72 in `DEFAULT_MODEL_CONFIGS`. The node's models (deepseek, etc.) are accessed via node_router when tasks route to nodes.

**Step 2: Commit**
```bash
git add ai_bridge/smart_router.py
git commit -m "fix(smart-router): default local model to dolphin3 (actually installed on hub)"
```

---

### Task 3: Fix intent_parser model and host

**Files:**
- Modify: `/mnt/archie_brain/platform_v2/tools/archie_core/intent_parser.py:32-35`

**Step 1: Fix host default and classification model**

Replace lines 32-35:
```python
        ollama_host = os.getenv('OLLAMA_PRIMARY', '192.168.1.246:11434')
        # Ensure http:// prefix
        self.ollama_url = ollama_host if ollama_host.startswith('http') else f'http://{ollama_host}'
        self.classification_model = 'llama3.2:3b'  # Fast model for classification
```
With:
```python
        ollama_host = os.getenv('OLLAMA_PRIMARY', 'host.docker.internal:11434')
        # Ensure http:// prefix
        self.ollama_url = ollama_host if ollama_host.startswith('http') else f'http://{ollama_host}'
        self.classification_model = 'qwen2.5:7b'  # Installed locally, good for classification
```

**Step 2: Fix the DB function call (type ambiguity)**

In the same file, line 154, replace:
```python
            cur.execute("SELECT * FROM assess_command_complexity(%s)", (text,))
```
With:
```python
            cur.execute("SELECT * FROM assess_command_complexity(%s::TEXT, NULL::VARCHAR)", (text,))
```

This disambiguates between the two function overloads (migration 056 vs 059).

**Step 3: Commit**
```bash
git add platform_v2/tools/archie_core/intent_parser.py
git commit -m "fix(intent-parser): use local qwen2.5:7b, fix host default, disambiguate DB function"
```

---

### Task 4: Fix command_router host and model map

**Files:**
- Modify: `/mnt/archie_brain/platform_v2/tools/archie_core/command_router.py:39-56`

**Step 1: Fix host default and model map**

Replace lines 39-56:
```python
        ollama_host = os.getenv('OLLAMA_PRIMARY', '192.168.1.246:11434')
        self.ollama_url = ollama_host if ollama_host.startswith('http') else f'http://{ollama_host}'
        self.platform_url = 'http://localhost:3000'
        self.db_config = {
            'host': os.getenv('DB_HOST', 'archie_database'),
            'port': os.getenv('DB_PORT', '5432'),
            'database': os.getenv('DB_NAME', 'archie'),
            'user': os.getenv('DB_USER', 'archie'),
            'password': os.getenv('DB_PASSWORD', '')
        }

        # Model selection based on task complexity
        self.model_map = {
            'fast': 'llama3.2:3b',
            'standard': 'qwen2.5-coder:7b',
            'powerful': 'deepseek-coder-v2:16b',
            'code': 'deepseek-coder:33b'
        }
```
With:
```python
        ollama_host = os.getenv('OLLAMA_PRIMARY', 'host.docker.internal:11434')
        self.ollama_url = ollama_host if ollama_host.startswith('http') else f'http://{ollama_host}'
        self.platform_url = 'http://localhost:3000'
        self.db_config = {
            'host': os.getenv('DB_HOST', 'archie_database'),
            'port': os.getenv('DB_PORT', '5432'),
            'database': os.getenv('DB_NAME', 'archie'),
            'user': os.getenv('DB_USER', 'archie'),
            'password': os.getenv('DB_PASSWORD', '')
        }

        # Model selection based on task complexity (local hub models)
        self.model_map = {
            'fast': 'dolphin3:latest',
            'standard': 'qwen2.5:7b',
            'powerful': 'qwen2.5:7b',
            'code': 'qwen2.5:7b'
        }
```

**Step 2: Commit**
```bash
git add platform_v2/tools/archie_core/command_router.py
git commit -m "fix(command-router): use local host + models actually installed on hub"
```

---

### Task 5: Fix node_router fallback host

**Files:**
- Modify: `/mnt/archie_brain/ai_bridge/node_router.py:40`

**Step 1: Fix hardcoded fallback**

Replace line 40:
```python
    host = os.getenv('OLLAMA_HOST', 'http://192.168.1.246:11434')
```
With:
```python
    host = os.getenv('OLLAMA_HOST', 'http://host.docker.internal:11434')
```

**Step 2: Commit**
```bash
git add ai_bridge/node_router.py
git commit -m "fix(node-router): fallback host to local instead of legacy .246"
```

---

### Task 6: Fix agent_select to always return ARCHIE

**Files:**
- Modify: `/mnt/archie_brain/ai_bridge/orchestration_engine.py:501-551`

**Step 1: Add ARCHIE fallback with agent_id=2**

Replace the `_step_select_agent` method (lines 501-551) with:
```python
    def _step_select_agent(
        self, message: str, intent: Dict, steps: List[ThinkingStep]
    ) -> Optional[Dict]:
        """Step 6: Select the best agent for this task"""
        t0 = time.time()
        agent = None

        try:
            from agent_delegation import select_best_agent_for_task
            intent_type = intent.get('type', 'conversation')

            # Map intent to department preference
            dept_map = {
                'code_task': 'Engineering',
                'team_task': 'Operations',
                'business_task': 'Strategy',
                'knowledge_query': 'Research',
                'creative_task': 'Creative',
                'system_status': 'Operations',
            }
            dept = dept_map.get(intent_type)

            agent = select_best_agent_for_task(message, department_preference=dept)
        except Exception as e:
            logger.warning(f"Agent selection error: {e}")

        # Always fall back to ARCHIE (agent_id=2) if no agent found
        if not agent or not agent.get('agent_id'):
            agent = {
                'agent_id': 2,
                'name': 'ARCHIE',
                'department': 'Command',
                'worker_type': 'internal',
                'model': 'dolphin3:latest',
                'tier': 1,
            }

        duration = int((time.time() - t0) * 1000)

        steps.append(ThinkingStep(
            step_type=StepType.AGENT_SELECT.value,
            label=f"Agent: {agent.get('name', 'Unknown')} ({agent.get('department', '')})",
            data={
                'agent_id': agent.get('agent_id'),
                'name': agent.get('name'),
                'department': agent.get('department'),
                'worker_type': agent.get('worker_type'),
                'tier': agent.get('tier'),
            },
            duration_ms=duration,
            agent_id=agent.get('agent_id'),
        ))

        return agent
```

This ensures:
- ARCHIE (agent_id=2) is always the fallback
- `agent_id` is never None in the step data
- Welfare check will now fire (it checks `if selected_agent and selected_agent.get('agent_id')`)

**Step 2: Commit**
```bash
git add ai_bridge/orchestration_engine.py
git commit -m "fix(orchestration): always fall back to ARCHIE (agent_id=2) in agent selection"
```

---

### Task 7: Drop ambiguous DB function overload

**Files:**
- Create: `/mnt/archie_brain/database/migrations/086_fix_complexity_function.sql`

**Step 1: Create migration**

```sql
-- Migration 086: Fix assess_command_complexity function ambiguity
-- Date: 2026-02-13
-- Problem: Migration 056 created assess_command_complexity(TEXT) and
--          migration 059 created assess_command_complexity(TEXT, VARCHAR DEFAULT NULL)
--          Both match single-argument calls, causing "function is not unique" errors.
-- Fix: Drop the old single-parameter version, keep the newer two-parameter one.

DROP FUNCTION IF EXISTS assess_command_complexity(TEXT);

COMMENT ON FUNCTION assess_command_complexity(TEXT, VARCHAR) IS
    'Assess command complexity - single-arg calls match via DEFAULT NULL';
```

**Step 2: Apply migration**
```bash
docker exec -i archie_database psql -U archie -d archie < database/migrations/086_fix_complexity_function.sql
```

**Step 3: Commit**
```bash
git add database/migrations/086_fix_complexity_function.sql
git commit -m "fix(db): drop ambiguous single-param assess_command_complexity overload"
```

---

### Task 8: Test Phase A — Restart and verify

**Step 1: Restart platform**
```bash
docker compose restart archie_platform
```
Wait for healthy status.

**Step 2: Run orchestration test**
```bash
docker exec archie_platform python3 -c "
import sys
sys.path.insert(0, '/app')
sys.path.insert(0, '/mnt/archie_brain')
from ai_bridge.orchestration_engine import OrchestrationEngine

engine = OrchestrationEngine()
result = engine.orchestrate(
    message='Hey ARCHIE, how are you doing today?',
    user_id=2, conversation_id='test-phase-a'
)
print(f'Success: {result.success}')
print(f'Agent: {result.agent_used} (id={result.agent_id})')
print(f'Model: {result.model_used}')
for step in result.thinking_steps:
    print(f'  {step.step_type}: {step.label} ({step.duration_ms}ms)')
"
```

**Expected results:**
- `Agent: ARCHIE (id=2)` — not None
- `Model: dolphin3:latest` — not deepseek-coder-v2:16b
- Intent parse completes without DB function error
- Welfare check step appears (because agent_id=2 is now returned)
- All steps show correct labels

---

## Phase B: Wire Orchestration into Bridge & Team

### Task 9: Assign ARCHIE to COMMAND station

**Step 1: Insert station assignment**
```bash
docker exec -i archie_database psql -U archie -d archie <<'SQL'
-- Assign ARCHIE (agent_id=2) to COMMAND station (station_id=1) as primary
INSERT INTO station_assignments (station_id, agent_id, assignment_type, priority, is_active)
VALUES (1, 2, 'primary', 1, true)
ON CONFLICT DO NOTHING;

-- Set ARCHIE's department to Command
UPDATE agents SET department = 'Command' WHERE id = 2 AND department IS NULL;
SQL
```

**Step 2: Verify**
```bash
docker exec archie_database psql -U archie -d archie -c "
SELECT bs.station_code, a.name, a.department, sa.assignment_type
FROM station_assignments sa
JOIN bridge_stations bs ON sa.station_id = bs.id
JOIN agents a ON sa.agent_id = a.id
WHERE sa.is_active = true;"
```

**Step 3: Commit**
```bash
git commit -m "feat(bridge): assign ARCHIE to COMMAND station, set department"
```

---

### Task 10: Enhance agent_select to consult station assignments

**Files:**
- Modify: `/mnt/archie_brain/ai_bridge/orchestration_engine.py` — `_step_select_agent()` method

**Step 1: Add station-aware agent lookup**

Replace the `_step_select_agent` method with station-aware version:
```python
    def _step_select_agent(
        self, message: str, intent: Dict, steps: List[ThinkingStep]
    ) -> Optional[Dict]:
        """Step 6: Select the best agent for this task via Bridge stations"""
        t0 = time.time()
        agent = None

        intent_type = intent.get('type', 'conversation')

        # Map intent to station code preference
        station_map = {
            'code_task': ['ENGINEERING', 'ENGINEERING_CODE', 'ENGINEERING_BUILD'],
            'team_task': ['OPERATIONS', 'OPERATIONS_CORE', 'HR'],
            'business_task': ['OPERATIONS', 'FINANCE'],
            'knowledge_query': ['CONSCIOUSNESS', 'RND', 'RND_AI'],
            'creative_task': ['CREATIVE', 'CREATIVE_MEDIA', 'CREATIVE_CONTENT'],
            'system_status': ['OPERATIONS', 'INFRASTRUCTURE', 'SECURITY'],
            'conversation': ['COMMAND'],
        }
        preferred_stations = station_map.get(intent_type, ['COMMAND'])

        # Try 1: Find agent assigned to a matching Bridge station
        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("""
                SELECT a.id as agent_id, a.name, a.department, a.worker_type,
                       a.model, a.tier, bs.station_code
                FROM station_assignments sa
                JOIN bridge_stations bs ON sa.station_id = bs.id
                JOIN agents a ON sa.agent_id = a.id
                WHERE sa.is_active = true
                  AND a.status = 'active'
                  AND bs.station_code = ANY(%s)
                ORDER BY sa.priority ASC, sa.assignment_type = 'primary' DESC
                LIMIT 1
            """, (preferred_stations,))
            row = cur.fetchone()
            if row:
                agent = dict(row)
            cur.close()
            conn.close()
        except Exception as e:
            logger.warning(f"Station assignment lookup error: {e}")

        # Try 2: Fall back to agent_delegation department match
        if not agent:
            try:
                from agent_delegation import select_best_agent_for_task
                dept_map = {
                    'code_task': 'Engineering',
                    'team_task': 'Operations',
                    'business_task': 'Strategy',
                    'knowledge_query': 'Research',
                    'creative_task': 'Creative',
                    'system_status': 'Operations',
                }
                dept = dept_map.get(intent_type)
                agent = select_best_agent_for_task(message, department_preference=dept)
            except Exception as e:
                logger.warning(f"Agent delegation fallback error: {e}")

        # Try 3: Always fall back to ARCHIE (agent_id=2)
        if not agent or not agent.get('agent_id'):
            agent = {
                'agent_id': 2,
                'name': 'ARCHIE',
                'department': 'Command',
                'worker_type': 'internal',
                'model': 'dolphin3:latest',
                'tier': 1,
            }

        duration = int((time.time() - t0) * 1000)

        source = 'station' if agent.get('station_code') else 'delegation' if agent.get('reason') else 'default'
        steps.append(ThinkingStep(
            step_type=StepType.AGENT_SELECT.value,
            label=f"Agent: {agent.get('name', 'Unknown')} ({agent.get('department', '')}) [{source}]",
            data={
                'agent_id': agent.get('agent_id'),
                'name': agent.get('name'),
                'department': agent.get('department'),
                'worker_type': agent.get('worker_type'),
                'tier': agent.get('tier'),
                'source': source,
                'station': agent.get('station_code'),
            },
            duration_ms=duration,
            agent_id=agent.get('agent_id'),
        ))

        return agent
```

**Step 2: Commit**
```bash
git add ai_bridge/orchestration_engine.py
git commit -m "feat(orchestration): station-aware agent selection via Bridge assignments"
```

---

### Task 11: Wire node_router into orchestration execution

**Files:**
- Modify: `/mnt/archie_brain/ai_bridge/orchestration_engine.py` — `_execute_ollama()` method (lines 814-851)

**Step 1: Add node-aware Ollama execution**

Replace `_execute_ollama()` with node-aware version:
```python
    def _execute_ollama(
        self, message: str, model_name: str, user_id: int,
        conversation_id: str, voice_mode: bool, user_context: Optional[Dict],
        agent: Optional[Dict] = None
    ) -> tuple:
        """Execute via Ollama — local hub or remote node via node_router"""
        try:
            # Determine the correct Ollama host
            ollama_host = None
            node_id = None

            # If agent specifies a model, use node_router to find it
            try:
                from node_router import get_ollama_url
                ollama_host, node_id = get_ollama_url(model_name)
            except ImportError:
                pass

            if node_id:
                # Cross-node execution — use direct Ollama call (no personality)
                logger.info(f"Routing to node {node_id} for model {model_name}")
                from archie_bridge import call_ollama
                system_prompt = "You are A.R.C.H.I.E., a helpful AI assistant."
                if voice_mode:
                    system_prompt += " Keep responses concise and conversational. No markdown."
                result = call_ollama(
                    message, model=model_name,
                    system_prompt=system_prompt, ollama_host=ollama_host
                )
                if result.get('success'):
                    return result['response'], result.get('model', model_name)
                else:
                    raise RuntimeError(result.get('error', 'Node Ollama call failed'))
            else:
                # Local execution — use ArchieAI for personality-enriched responses
                sys.path.insert(0, os.path.join(
                    os.path.dirname(__file__), '..', 'platform_v2', 'tools', 'archie_core'
                ))
                from ai_chat import ArchieAI

                ai = ArchieAI()
                context = user_context or {}
                if voice_mode:
                    context['voice_mode'] = True

                history = self._load_conversation_history(user_id, conversation_id)
                result = ai.chat(message, context, history)
                if result.get('success'):
                    return result['response'], result.get('model', model_name)
                else:
                    raise RuntimeError(result.get('error', 'ArchieAI chat failed'))

        except ImportError:
            # Fall back to direct Ollama call on local
            from archie_bridge import call_ollama
            system_prompt = "You are A.R.C.H.I.E., a helpful AI assistant."
            if voice_mode:
                system_prompt += " Keep responses concise and conversational. No markdown."
            result = call_ollama(message, model=model_name, system_prompt=system_prompt)
            if result.get('success'):
                return result['response'], result.get('model', model_name)
            else:
                raise RuntimeError(result.get('error', 'Ollama call failed'))
```

Note: This requires verifying that `call_ollama` in `archie_bridge.py` accepts an `ollama_host` parameter. If not, a small addition is needed there.

**Step 2: Update `_step_execute()` to pass agent to `_execute_ollama()`**

In `_step_execute()` (line 638), change:
```python
                response_text, actual_model = self._execute_ollama(
                    message, model_name, user_id, conversation_id,
                    voice_mode, user_context
                )
```
To:
```python
                response_text, actual_model = self._execute_ollama(
                    message, model_name, user_id, conversation_id,
                    voice_mode, user_context, agent
                )
```

Also update the `_step_execute` signature to accept `agent` parameter.

**Step 3: Commit**
```bash
git add ai_bridge/orchestration_engine.py
git commit -m "feat(orchestration): node-aware execution via node_router for cross-node delegation"
```

---

### Task 12: Update Bridge Command LLM connections

**Files:**
- Modify: `/mnt/archie_brain/platform_v2/tools/bridge/routes.py:153-194`

**Step 1: Fix LLM_CONNECTIONS to reflect actual local models**

Replace lines 153-194:
```python
LLM_CONNECTIONS = {
    "ollama_local": {
        "name": "Ollama (Local Hub)",
        "type": "local",
        "host": "host.docker.internal",
        "port": 11434,
        "models": ["dolphin3:latest", "qwen2.5:7b", "nomic-embed-text:latest"],
        "cost": "FREE",
    },
    "claude_api": {
        "name": "Claude API",
        "type": "api",
        "host": "api.anthropic.com",
        "port": 443,
        "models": ["claude-sonnet-4", "claude-opus-4"],
        "cost": "PAID",
    },
    "openai_api": {
        "name": "OpenAI API",
        "type": "api",
        "host": "api.openai.com",
        "port": 443,
        "models": ["gpt-4", "gpt-4-turbo", "gpt-4o"],
        "cost": "PAID",
    },
    "grok_api": {
        "name": "Grok API",
        "type": "api",
        "host": "api.x.ai",
        "port": 443,
        "models": ["grok-beta"],
        "cost": "PAID",
    },
    "gemini_api": {
        "name": "Gemini API",
        "type": "api",
        "host": "generativelanguage.googleapis.com",
        "port": 443,
        "models": ["gemini-2.0-flash"],
        "cost": "PAID",
    },
}
```

Node .246's models are loaded dynamically from `node_ollama_models` table, not hardcoded.

**Step 2: Commit**
```bash
git add platform_v2/tools/bridge/routes.py
git commit -m "fix(bridge): LLM connections reflect actual local hub models"
```

---

### Task 13: Test Phase B — Station-aware delegation

**Step 1: Restart platform**
```bash
docker compose restart archie_platform
```

**Step 2: Test orchestration with station routing**
```bash
docker exec archie_platform python3 -c "
import sys
sys.path.insert(0, '/app')
sys.path.insert(0, '/mnt/archie_brain')
from ai_bridge.orchestration_engine import OrchestrationEngine

engine = OrchestrationEngine()

# Test 1: Conversation → should route to COMMAND station → ARCHIE
result = engine.orchestrate(message='Hey ARCHIE!', user_id=2, conversation_id='test-b1')
print(f'Test 1 (conversation): agent={result.agent_used}, source=', end='')
for s in result.thinking_steps:
    if s.step_type == 'agent_select':
        print(s.data.get('source', 'unknown'))

# Test 2: Code task → ENGINEERING station (or ARCHIE if no agent assigned there)
result = engine.orchestrate(message='Can you review this Python function?', user_id=2, conversation_id='test-b2')
print(f'Test 2 (code): agent={result.agent_used}, model={result.model_used}')
for s in result.thinking_steps:
    if s.step_type == 'agent_select':
        print(f'  source={s.data.get(\"source\")}, station={s.data.get(\"station\")}')

# Test 3: Welfare check fires
for s in result.thinking_steps:
    if s.step_type == 'welfare_check':
        print(f'Test 3 (welfare): healthy={s.data.get(\"healthy\")}, agent_id={s.data.get(\"agent_id\")}')
        break
else:
    print('Test 3 (welfare): MISSING — welfare check did not fire')
"
```

**Expected:**
- Test 1: agent=ARCHIE, source=station (COMMAND)
- Test 2: agent=ARCHIE, source=default (no Engineering agent assigned yet)
- Test 3: welfare check fires with agent_id=2

---

## Phase C: Fix .246 Node & Mesh Cluster

### Task 14: Verify and fix node .246 flags

**Step 1: Check and update node registration**
```bash
docker exec -i archie_database psql -U archie -d archie <<'SQL'
-- Ensure node .246 has correct flags for mesh participation
UPDATE remote_nodes
SET bridge_enabled = true,
    iaae_compliant = true,
    bridge_priority = 5
WHERE vpn_ip = '192.168.1.246'
  AND (bridge_enabled IS NOT true OR iaae_compliant IS NOT true);

-- Verify
SELECT id, node_name, vpn_ip, status, approval_status, bridge_enabled, iaae_compliant, bridge_priority
FROM remote_nodes WHERE vpn_ip = '192.168.1.246';
SQL
```

**Step 2: Verify model sync is accurate**
```bash
docker exec archie_platform python3 -c "
import urllib.request, json
# Query actual models on .246
try:
    resp = urllib.request.urlopen('http://192.168.1.246:11434/api/tags', timeout=10)
    actual = [m['name'] for m in json.loads(resp.read()).get('models', [])]
    print(f'Models on .246: {len(actual)}')
    for m in sorted(actual):
        print(f'  {m}')
except Exception as e:
    print(f'Cannot reach .246: {e}')
"
```

---

### Task 15: Add cross-node governance logging to orchestration

**Files:**
- Modify: `/mnt/archie_brain/ai_bridge/orchestration_engine.py` — `_execute_ollama()` method

**Step 1: Log governance event for cross-node delegation**

After the `if node_id:` branch in `_execute_ollama()`, add governance logging:
```python
            if node_id:
                # Log cross-node delegation as governance event
                self._log_governance_event(
                    event_type='cross_node_delegation',
                    action='delegate_to_node',
                    agent_id=agent.get('agent_id') if agent else None,
                    reason=f"Routing model '{model_name}' to node {node_id}",
                    outcome='delegated'
                )
```

(Verify `_log_governance_event` method exists — if not, add it.)

**Step 2: Commit**
```bash
git add ai_bridge/orchestration_engine.py
git commit -m "feat(orchestration): log cross-node delegations as IAAE governance events"
```

---

### Task 16: Test Phase C — Cross-node routing

**Step 1: Test model routing to .246**
```bash
docker exec archie_platform python3 -c "
import sys
sys.path.insert(0, '/mnt/archie_brain')
from ai_bridge.node_router import get_ollama_url

# Test: model only on .246
url, node = get_ollama_url('deepseek-coder-v2:16b')
print(f'deepseek-coder-v2:16b → url={url}, node={node}')

# Test: model on both hub and .246
url, node = get_ollama_url('dolphin3:latest')
print(f'dolphin3:latest → url={url}, node={node}')

# Test: model only on hub
url, node = get_ollama_url('nomic-embed-text:latest')
print(f'nomic-embed-text → url={url}, node={node}')
"
```

**Expected:**
- deepseek-coder-v2:16b → routes to .246 node
- dolphin3:latest → prefers local (None node) or routes to .246 with lower priority
- nomic-embed-text → local fallback (None node)

---

## Phase D: Final Validation

### Task 17: Full end-to-end test suite

**Step 1: Run comprehensive test**
```bash
docker exec archie_platform python3 -c "
import sys, json
sys.path.insert(0, '/app')
sys.path.insert(0, '/mnt/archie_brain')
from ai_bridge.orchestration_engine import OrchestrationEngine

engine = OrchestrationEngine()
tests = [
    ('Conversation', 'Hey ARCHIE, how are you?'),
    ('Code task', 'Review the database schema for knowledge_base'),
    ('Knowledge query', 'What do you know about Voice DNA?'),
    ('Voice mode', 'What time is it?'),
]

for name, msg in tests:
    result = engine.orchestrate(
        message=msg, user_id=2,
        conversation_id=f'test-final-{name.lower().replace(\" \",\"-\")}',
        voice_mode=(name == 'Voice mode')
    )
    print(f'=== {name} ===')
    print(f'  Success: {result.success}')
    print(f'  Agent: {result.agent_used} (id={result.agent_id})')
    print(f'  Model: {result.model_used}')
    print(f'  Duration: {result.total_duration_ms}ms')
    print(f'  Steps: {len(result.thinking_steps)}')
    for s in result.thinking_steps:
        print(f'    {s.step_type}: {s.label}')
    print()
"
```

**Expected for all tests:**
- agent_id = 2 (not None)
- model = dolphin3:latest (not deepseek-coder-v2:16b)
- No DB function errors in intent_parse step
- Welfare check step present
- 7 thinking steps (intent, iaae, route, gpu, agent_select, welfare, execute)

**Step 2: Verify IAAE page shows updated data**
```bash
curl -s http://192.168.1.200:3000/iaae/api/stats | python3 -m json.tool
```

Should show increased `total_governance_events` count.

**Step 3: Final commit and version bump**
```bash
git add -A
git commit -m "feat: orchestration reconnection — Bridge/Team/Node pipeline (v5.33.0)"
```

---

## Files Modified Summary

| File | Tasks | Changes |
|------|-------|---------|
| `.env` | 1 | OLLAMA_PRIMARY → local, add OLLAMA_HOST + ARCHIE_CHAT_MODEL |
| `platform_v2/.env` | 1 | Same as root .env |
| `ai_bridge/smart_router.py` | 2 | Local model → dolphin3:latest |
| `ai_bridge/orchestration_engine.py` | 6, 10, 11, 15 | Agent select (station-aware), node-aware execution, governance |
| `ai_bridge/node_router.py` | 5 | Fallback host → host.docker.internal |
| `platform_v2/tools/archie_core/intent_parser.py` | 3 | Host + model fix, DB function cast |
| `platform_v2/tools/archie_core/command_router.py` | 4 | Host + model map fix |
| `platform_v2/tools/bridge/routes.py` | 12 | LLM_CONNECTIONS → actual local models |
| `database/migrations/086_fix_complexity_function.sql` | 7 | Drop ambiguous function overload |
