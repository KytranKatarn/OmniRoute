# Bridge Enhancements Design — 7 Features in 4 Phases

**Project**: Team Management Redesign — Future Enhancements
**Date**: 2026-02-17
**Status**: Approved
**Depends on**: Project #91 (commit 42412c3)

---

## Overview

Seven enhancements to the BridgeDispatcher and team management system, organized into 4 infrastructure-first phases. Each phase unlocks the next.

| Phase | Enhancements | Key Deliverables |
|-------|-------------|-----------------|
| 1 | Local-Only/Cloud Toggle + Escalation Process | Routing mode, failure tracking, auto-escalate free tiers |
| 2 | External AI Contractors | OpenAI/Perplexity/Grok integration, cost tracking, budget enforcement |
| 3 | Telegram Approval Flow + Bridge Learning | Interactive approval buttons, knowledge capture from external calls |
| 4 | Agent Naming + Dashboard Display | Diverse names, dashboard agent indicators |

## Design Decisions

- **Escalation model**: Hybrid — auto-escalate through free tiers, Telegram approval for paid tiers
- **External AI integration**: Direct API keys per provider (OpenAI, Perplexity, xAI). No middleman.
- **Agent naming**: Hand-curated diverse first/last names. Codenames kept as callsigns.
- **Implementation order**: Infrastructure-first (toggle → external AI → approval → visual polish)

---

## Phase 1: Local-Only/Cloud Toggle + Escalation Process

### 1a. Routing Mode Toggle

**Purpose**: Bridge-level setting restricting available model tiers for privacy/cost control.

**Three modes**:
- `local_only` — Only local Ollama models. No network calls.
- `local_cloud` — Local + Ollama cloud (free). No paid APIs.
- `full` (default) — All tiers including paid external APIs and Claude.

**Schema changes**:
- Migration 105: Add `routing_mode VARCHAR(20) DEFAULT 'full'` to new `platform_settings` table (key-value with typed values).
- Alternatively: single row `bridge_config` table with routing_mode + other bridge settings.

**Code changes**:
- `ai_bridge/smart_router.py`: `get_available_tiers(routing_mode)` filters TIER_ORDER.
- `ai_bridge/bridge_dispatcher.py`: Reads routing_mode before dispatch, passes to smart_router.
- `platform_v2/tools/bridge/routes.py`: `GET/POST /api/bridge/routing-mode` endpoints.
- `platform_v2/templates/tools/bridge.html`: 3-state toggle in Bridge UI header.

### 1b. Escalation Process

**Purpose**: Auto-escalate on 3 consecutive failures. Free tiers auto-escalate; paid tiers require Telegram approval.

**Failure tracking**:
- In-memory dict in BridgeDispatcher: `_failure_tracker = {(agent_id, capability): count}`.
- Reset to 0 on success. Incremented on failure.
- Threshold: 3 (configurable via platform_settings).

**Escalation flow**:
1. Dispatch fails → increment failure count.
2. If count >= 3: Query SmartRouter for next available tier (respecting routing_mode).
3. If next tier is free (local/cloud Ollama): auto-dispatch, log escalation.
4. If next tier is paid (external AI/Claude): submit to `autonomy_approval_queue`, send Telegram.
5. On success after escalation: reset tracker, log to `dispatch_escalation_log`.

**Schema changes** (Migration 105):
```sql
CREATE TABLE platform_settings (
    key VARCHAR(100) PRIMARY KEY,
    value TEXT NOT NULL,
    value_type VARCHAR(20) DEFAULT 'string',
    description TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE dispatch_escalation_log (
    id SERIAL PRIMARY KEY,
    original_agent_id INTEGER REFERENCES agents(id),
    original_model VARCHAR(100),
    escalated_model VARCHAR(100),
    escalated_provider VARCHAR(50),
    capability VARCHAR(50),
    module_id VARCHAR(100),
    reason TEXT,
    failure_count INTEGER,
    cost_usd NUMERIC(10,6) DEFAULT 0,
    approved_by VARCHAR(100),
    approval_method VARCHAR(20), -- 'auto', 'telegram', 'timeout'
    success BOOLEAN,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

**Telegram notification** (on paid escalation):
- Message with failure context + ARCHIE recommendation.
- Buttons: Approve / Deny / Defer 1hr.
- 15-minute auto-deny timeout (fail-safe).
- Callback pattern: `esc_approve_{id}`, `esc_deny_{id}`, `esc_defer_{id}`.

---

## Phase 2: External AI Contractors

### 2a. Provider Integration

**New file**: `ai_bridge/external_providers.py`

Three providers, all using OpenAI-compatible chat completions API:

| Provider | API Base | Default Model | Unique Value |
|----------|----------|--------------|-------------|
| OpenAI | api.openai.com | gpt-4o-mini | Reasoning, general purpose |
| Perplexity | api.perplexity.ai | llama-3.1-sonar-small-128k-online | Real-time web search |
| xAI (Grok) | api.x.ai | grok-2 | Real-time data, humor |

Each function signature:
```python
def call_openai(prompt, model=None, system_prompt=None, json_mode=False, timeout=120):
    """Returns {success, response, model, provider, prompt_tokens, completion_tokens}"""
```

### 2b. API Key Storage

**Schema** (Migration 106):
```sql
CREATE TABLE external_api_keys (
    id SERIAL PRIMARY KEY,
    provider VARCHAR(50) NOT NULL UNIQUE,
    api_key_encrypted TEXT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    monthly_budget_usd NUMERIC(10,2) DEFAULT 10.00,
    current_month_cost_usd NUMERIC(10,2) DEFAULT 0.00,
    budget_reset_day INTEGER DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

Keys encrypted with Fernet (same as smtp_password_encrypted pattern).

### 2c. Cost Tracking

**Schema changes** (Migration 106):
- Add `cost_usd NUMERIC(10,6)` to `cloud_model_usage` table.
- New view `v_external_cost_summary`: daily/weekly/monthly cost per provider.

**Rate tables** (in external_providers.py):
```python
COST_PER_1K_TOKENS = {
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "gpt-4o": {"input": 0.0025, "output": 0.01},
    "llama-3.1-sonar-small-128k-online": {"input": 0.0002, "output": 0.0002},
    "grok-2": {"input": 0.002, "output": 0.01},
}
```

**Budget enforcement**: Before dispatching to external provider, check `current_month_cost_usd < monthly_budget_usd`. If exceeded, skip to next tier.

### 2d. SmartRouter Integration

New tiers in `model_tier_configs`:
```
Tier order: local → classify → vision → local_analysis → minimax_cloud → qwen3_cloud
            → openai → perplexity → grok → haiku → sonnet → opus
```

BridgeDispatcher's `_execute_llm()` extended to route to `external_providers.call_*()` based on provider field.

---

## Phase 3: Telegram Approval Flow + Bridge Learning

### 3a. Interactive Telegram Approvals

**Trigger**: Phase 1 escalation to paid tier submits to approval queue.

**Message format**:
```
🔄 Escalation Request #47
Agent: CodeSmith (ENGINEERING)
Capability: code_review
Failed 3x on: qwen3-coder-cpu → minimax-m2.5 → qwen3-coder-next
Next tier: OpenAI gpt-4o-mini (~$0.003)
Module: code_sentinel

ARCHIE recommends: Approve — code review requires reasoning beyond local capacity.

[✅ Approve] [❌ Deny] [⏸ Defer 1hr]
```

**Implementation**:
- Extend `autonomy_approval_queue` with `escalation_context JSONB`.
- New callback handlers in `telegram_routes.py` for `esc_*` patterns.
- On approve: BridgeDispatcher retries with approved tier. On deny: return failure. On defer: requeue with 1hr delay.
- ARCHIE recommendation: Sentinel agent evaluates via `dispatcher.request_work('governance', ...)`.
- Auto-deny timeout: 15 minutes (configurable in platform_settings).

### 3b. Bridge Learning

**Purpose**: When external AI succeeds where local agents failed, capture knowledge to improve local agents over time.

**New file**: `ai_bridge/bridge_learning.py`

**Learning pipeline**:
1. After successful escalation, `capture_learning(failed_result, success_result, capability)` runs.
2. Uses local model to compare responses and extract what the local agent missed.
3. Stores as `knowledge_base` entry with `source_type='agent_learning'`, tagged `[agent-learning, {agent_name}, {capability}]`.
4. Importance score based on failure frequency (more failures = higher importance).

**Context injection**:
- `inject_learnings(agent_name, capability, prompt)` searches knowledge_base for relevant learning cards.
- BridgeDispatcher calls this before every dispatch. If learnings exist, they're prepended to system prompt.
- Max 3 learning cards per dispatch (most relevant, based on embedding similarity).

**Learning card schema** (uses existing knowledge_base table):
```json
{
    "source_type": "agent_learning",
    "title": "CodeSmith learning: code_review — null pointer patterns",
    "content": "When reviewing for null safety, check optional chaining...",
    "tags": ["agent-learning", "CodeSmith", "code_review"],
    "importance_score": 0.7,
    "ai_analysis": {
        "agent_name": "CodeSmith",
        "capability": "code_review",
        "failure_count": 3,
        "external_model": "gpt-4o-mini",
        "learning_type": "pattern_recognition"
    }
}
```

---

## Phase 4: Agent Naming + Dashboard Display

### 4a. Agent Identity

**Name assignment**: Hand-curated diverse first/last names for all 10 agents.

| Codename | Station | Suggested Name Style |
|----------|---------|---------------------|
| ARCHIE | COMMAND | Keep as-is (the platform itself) |
| Sentinel | COMMAND | Strong, protective feel |
| CodeSmith | ENGINEERING | Technical, precise |
| Architect | ENGINEERING | Visionary, structural |
| OpsMaster | OPERATIONS | Reliable, operational |
| CommRelay | OPERATIONS | Communicative, bridging |
| DataMind | ANALYTICS | Analytical, curious |
| Nexus | ANALYTICS | Connected, multifaceted |
| Wordsmith | CREATIVE | Artistic, expressive |
| Scholar | RESEARCH | Academic, thorough |

**Display format**: `"{first_name} {last_name}"` in UI, codename in technical logs.
Badge format: `"Aria (CodeSmith)"` — first name + codename.

**Migration**: UPDATE agents SET first_name, last_name WHERE id IN (2-11).

### 4b. Dashboard Agent Display

**Purpose**: Show assigned agent on each module card in the main dashboard grid.

**API**: `GET /api/dashboard/module-agents` returns mapping of module_id → agent info.

**UI changes**:
- Dashboard template: Add agent line below module description in each card.
- Format: Status dot (green/amber/grey) + first name + codename in parens.
- LCARS-styled, station-colored text.
- Polls every 30s.

---

## File Summary

| Phase | New Files | Modified Files | Migrations |
|-------|-----------|---------------|------------|
| 1 | — | bridge_dispatcher.py, smart_router.py, bridge/routes.py, bridge.html, telegram_routes.py | 105 |
| 2 | external_providers.py | bridge_dispatcher.py, smart_router.py, bridge/routes.py | 106 |
| 3 | bridge_learning.py | bridge_dispatcher.py, telegram_routes.py, agent_loop.py | — |
| 4 | — | agents table (data), dashboard template, agent-badge.js | 107 (data) |

**Total**: ~3 new files, ~10 edited files, 3 migrations
