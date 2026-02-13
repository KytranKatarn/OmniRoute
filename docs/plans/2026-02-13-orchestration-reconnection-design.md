# Orchestration Reconnection Design

**Date**: 2026-02-13
**Version**: 5.33.0 (target)
**Status**: Approved

## Problem Statement

The orchestration engine (Phases 1-7 deployed in v5.32.0) works as a standalone pipeline but is disconnected from the platform's core infrastructure:

- **Ollama routing** points to legacy servers (.245/.246) instead of local hub
- **Smart router** defaults to a model not installed locally (deepseek-coder-v2:16b)
- **Intent parser** uses a model not installed locally (llama3.2:3b)
- **Agent selection** returns agent_id=None; ARCHIE (id=2) is never found
- **Welfare check** never fires because agent_id is None
- **Bridge stations** exist (24 stations) but have zero agent assignments
- **Team Management** agents have no departments — only ARCHIE is active
- **Node .246 (KYTRAN)** is registered and online with 22 models but treated as OLLAMA_PRIMARY instead of as a mesh node
- **Orchestration bypasses node_router** — never uses Bridge's dynamic routing
- **Bridge Command LLM connections** list models that don't exist locally

The result: chat works by accident (ArchieAI hardcodes dolphin3), but the thinking steps report wrong models, no agents are delegated, no welfare is checked, no cross-node routing occurs, and the Bridge/Team infrastructure is entirely cosmetic.

## Design

### Phase A: Fix Local Orchestration

Foundation fixes so the hub works correctly on its own.

#### A1. Fix .env Ollama routing
Both `.env` files (root + platform_v2):
```
OLLAMA_PRIMARY=host.docker.internal:11434
OLLAMA_HOST=http://host.docker.internal:11434
ARCHIE_CHAT_MODEL=dolphin3:latest
```
Remove `OLLAMA_SECONDARY` (unused in code).

#### A2. Fix smart_router default model
`ai_bridge/smart_router.py` — `DEFAULT_MODEL_CONFIGS['local']`:
- Change `deepseek-coder-v2:16b` → `dolphin3:latest`
- Node models are used via node_router when tasks route to nodes, not as hub default

#### A3. Fix intent parser
`platform_v2/tools/archie_core/intent_parser.py`:
- Change `llama3.2:3b` → `qwen2.5:7b` (installed locally, good for classification)
- Or implement lightweight keyword-based classification (no LLM call needed for basic intent detection)
- Fix the host to use OLLAMA_PRIMARY with correct default

#### A4. Fix agent_select to find ARCHIE
`ai_bridge/orchestration_engine.py` — `_step_select_agent()`:
- When no specialized agent matches a department, default to ARCHIE (agent_id=2) explicitly
- Return `agent_id=2` in the step data, not None

#### A5. Fix welfare check
- Once A4 returns a real agent_id, the welfare check will fire
- Verify the `agent_emotional_state` query works for agent_id=2

#### A6. Fix DB function ambiguity
- `assess_command_complexity()` has duplicate function signatures
- Drop the ambiguous overload or add explicit type cast

#### A7. Fix hardcoded legacy IPs
All files that default to `192.168.1.246`:
- `ai_bridge/node_router.py` — `get_fallback_host()` default
- `platform_v2/tools/archie_core/intent_parser.py` — `__init__` default
- `platform_v2/tools/archie_core/command_router.py` — `__init__` default

Change all to `host.docker.internal:11434`.

**Files**: `.env` (x2), `smart_router.py`, `orchestration_engine.py`, `intent_parser.py`, `command_router.py`, `node_router.py`, DB migration

---

### Phase B: Wire Orchestration into Bridge & Team

Reconnect the orchestration pipeline to the agent/station infrastructure.

#### B1. Staff the bridge stations
- Assign ARCHIE (id=2) to COMMAND station as primary
- Create or reactivate agents with proper departments matching stations
- Internal agents use `dolphin3:latest`, contract agents keep API models
- Each agent's `department` column maps to a station code

#### B2. Orchestration consults station assignments
Enhance `_step_select_agent()`:
1. Check `station_assignments` for agents assigned to the matching station
2. Fallback: department match via `select_best_agent_for_task()`
3. Final fallback: ARCHIE (always available)

The Bridge station layout controls who handles what.

#### B3. Orchestration uses node_router for model resolution
Enhance `_resolve_model()` and execution step:
- Internal agent → `host.docker.internal` (local Ollama)
- Node agent → `node_router.get_ollama_url()` to that node's Ollama
- Task needs node-only model → node_router picks the best node
- GPU check queries the correct host (local vs node)

#### B4. Bridge Command LLM connections reflect reality
Update hardcoded `LLM_CONNECTIONS` in `bridge/routes.py`:
- Local hub: `dolphin3:latest`, `qwen2.5:7b`, `nomic-embed-text`
- Node .246: dynamically from `node_ollama_models` table
- Health checks ping correct hosts

#### B5. Execution respects agent model column
When orchestration selects an agent, use that agent's `model` column:
- ARCHIE (model=dolphin3) → local Ollama
- Contract agent (model=claude-sonnet-4) → Claude API
- Node agent (model=deepseek-coder-v2:16b) → node_router to .246

**Files**: `orchestration_engine.py`, `agent_delegation.py`, `bridge/routes.py`, DB (station assignments + agent departments)

---

### Phase C: Fix .246 Node & Mesh Cluster

Proper hub-managed node integration with IAAE governance.

#### C1. Fix node .246 registration
- After Phase A, .246 is a proper node (not OLLAMA_PRIMARY)
- Verify: `bridge_enabled=true`, `bridge_priority` set, `iaae_compliant=true`

#### C2. Sync node model list
- Verify 22 registered models in `node_ollama_models` match reality
- Add sync mechanism: query `.246:11434/api/tags` → update table

#### C3. Hub-approved delegation flow
When orchestration selects a model only on a node:
1. `node_router.select_best_node(model)` finds .246
2. Governance event logged: `cross_node_delegation` with node_id, model, reason
3. ARCHIE (hub) approves — the orchestration pipeline IS the approval
4. Request sent to node's Ollama
5. Response flows back through hub, logged in `agent_executions`

#### C4. Agent sharing on the cluster
- Nodes register agents with `node_id` reference
- Node agents appear in hub team roster (visible in Team Management)
- Station assignments can include node agents
- Orchestration can select node agents → triggers C3 delegation

#### C5. IAAE governance for cross-node work
- Every cross-node delegation gets IAAE pre-check (pipeline step 2)
- Node agents tracked in `agent_emotional_state` for welfare
- Governance audit log captures: node, agent, task, approval
- `/iaae` page shows cross-node stats

#### C6. Bridge Command dashboard updates
- .246 visible as connected node with models and agents
- Station view marks local vs on-node agents
- Traffic view shows cross-node flows
- Health reflects both hub and node Ollama

**Files**: `orchestration_engine.py`, `node_router.py`, `bridge/routes.py`, `iaae/routes.py`, DB (agent sharing columns)

---

### Phase D: Testing & Validation

#### D1. Local orchestration
- Conversational → ARCHIE on local dolphin3 via host.docker.internal
- Code task → correct intent, Engineering agent selected
- Knowledge query → routes correctly, all thinking steps populated
- Welfare check fires for agent_id=2

#### D2. Agent delegation
- Station-assigned agents are selected for matching tasks
- Contract agents route through Claude API
- Fallback to ARCHIE when no specialist matches

#### D3. Node delegation
- Model only on .246 → node_router selects it, governance logged
- Local model available → prefers local, does NOT route to .246
- .246 offline → graceful fallback to local

#### D4. IAAE governance
- Audit log grows with each orchestration
- Welfare intervention triggers alternate agent
- Cross-node delegations logged with node_id
- `/iaae` page reflects live stats

#### D5. Bridge Command visual
- Stations show assigned agents (local + node)
- .246 visible with health, models, agents
- Chat thinking panel shows full pipeline including node routing
- LLM connections accurate

---

## Implementation Order

| Phase | Depends on | Estimated scope |
|-------|------------|-----------------|
| A | Nothing | 7 file edits + 1 DB fix |
| B | A | 4 file edits + DB inserts |
| C | A + B | 4 file edits + DB updates |
| D | A + B + C | Test scripts only |

## Key Files

```
.env (root)                                    — A1
platform_v2/.env                               — A1
ai_bridge/smart_router.py                      — A2
ai_bridge/orchestration_engine.py              — A4, B2, B3, B5, C3
ai_bridge/node_router.py                       — A7, B3
ai_bridge/agent_delegation.py                  — B2
platform_v2/tools/archie_core/intent_parser.py — A3, A7
platform_v2/tools/archie_core/command_router.py— A7
platform_v2/tools/bridge/routes.py             — B4, C6
platform_v2/tools/iaae/routes.py               — C5
DB migration                                   — A6, B1, C4
```
