# Contractors Sub-Tab Design — Bridge Crew Integration

**Date**: 2026-02-21
**Project**: Platform UI Overhaul (#94)
**Status**: Design Approved

---

## Problem

The smart router already dispatches to 5+ external AI providers (OpenAI, MiniMax Cloud, Qwen3 Cloud, Perplexity, xAI/Grok) with cost tracking in `cloud_model_usage`. But:

1. Bridge Overview only shows 3 hardcoded providers (Claude, OpenAI, Grok) — misses MiniMax, Perplexity, Qwen3
2. No crew profiles for external providers — internal agents have cards with stats, contractors are invisible
3. No way to manage provider configs from Bridge (API keys, budgets, model toggles)
4. Routing mode dropdown controls dispatch scope but contractor status isn't visible
5. IAAE compliance tracks internal agents but external provider usage isn't surfaced
6. `cloud_model_usage` data exists but isn't displayed per-provider/model

## Design

### Identity Model: Provider = Firm, Model = Worker

Each external provider is a **contractor firm**. Each model under that provider is a **contract worker**.

| Provider Firm | Worker Models | Source |
|---|---|---|
| OpenAI | gpt-4o-mini, gpt-4o | `external_api_keys` + `external_providers.py` |
| MiniMax Cloud | minimax-m2.5 | Ollama cloud (`OLLAMA_API_KEY`) |
| Qwen3 Cloud | qwen3-coder-next | Ollama cloud (`OLLAMA_API_KEY`) |
| Perplexity | llama-3.1-sonar-small-128k-online | `external_api_keys` + `external_providers.py` |
| xAI (Grok) | grok-2 | `external_api_keys` + `external_providers.py` |

### Location: Crew Tab → Sub-Tabs

The Crew tab gains sub-tab navigation:

- **Active Roster** — existing internal agent cards (unchanged)
- **Contractors** — external provider firms with model worker cards

### Integration Points (Existing Systems)

| System | How It Connects |
|---|---|
| **Smart Router** (`smart_router.py`) | TIER_ORDER defines dispatch priority. Routing mode (local_only/local_cloud/full) gates which contractors are reachable. Contractors sub-tab reads tier position per model. |
| **Bridge Dispatcher** (`bridge_dispatcher.py`) | Already dispatches to external models. Cost logged to `cloud_model_usage`. Contractor cards read these stats. |
| **External Providers** (`external_providers.py`) | Provider configs (base_url, models, cost rates). Contractor management UI writes to `external_api_keys` table; dispatcher reads from it. |
| **Overview Controls** | Routing mode dropdown already controls local_only/local_cloud/full scope. Contractor cards show enabled/disabled state that reflects current routing mode. |
| **IAAE Pipeline** (`orchestration_engine.py`) | Every dispatch goes through IAAE governance check. Contractor cards show IAAE-compliant badge. Governance events logged per dispatch (including external). |
| **System Operations** | Hardware data (GPU/CPU/memory) available via SysOps APIs. Referenced for local resource context alongside contractor capacity. |
| **`cloud_model_usage` table** | Per-request logs: model_name, provider, prompt_tokens, completion_tokens, cost_usd, agent_id, success. Source for all contractor stats. |
| **`external_api_keys` table** | provider, api_key_encrypted, is_active, monthly_budget_usd, current_month_cost_usd, budget_reset_day. Source for firm status and budget. |

### Contractor Firm Card (Collapsible Header)

```
▼ OpenAI ─────────────── 🟢 Active ── Tier 6 ── $2.10 / $10.00
  Budget: ████████░░░░░░░░ 21%    │  24h: 142 requests  │  [Edit] [Toggle]
```

Shows:
- **Provider name** + status dot (green=active+budget OK, yellow=approaching budget, red=budget exceeded or key invalid)
- **Smart router tier** position (from TIER_ORDER)
- **Monthly budget bar** — `current_month_cost_usd / monthly_budget_usd` with color thresholds
- **24h request count** — aggregated from `cloud_model_usage`
- **Actions**: Edit (API key, budget), Toggle active/inactive

### Model Worker Cards (Under Each Firm)

Styled like internal agent cards with purple left-border accent:

```
┌──────────────────────────┐
│ 🟣 GPT-4o-mini           │
│ Contract Worker · Tier 6  │
│                           │
│ ● Active     142 tasks/24h│
│ Avg: 1.2s    98% success  │
│ Cost: $0.85/24h           │
│ IAAE: ✓ Compliant         │
│                           │
│ [Enable/Disable Toggle]   │
└──────────────────────────┘
```

Shows:
- **Model name** + tier position
- **Status**: active (routing enabled) / disabled / budget-blocked
- **24h stats** from `cloud_model_usage`: dispatch count, avg latency, success rate
- **24h cost** from `cloud_model_usage`
- **IAAE compliant** badge — all external dispatches pass IAAE governance
- **Toggle** — enable/disable this model in routing (updates `model_tier_configs` or `external_api_keys`)

### Management Actions

**Add Provider** button opens modal:
- Provider name (dropdown: OpenAI, Perplexity, xAI, Custom)
- Base URL (pre-filled for known providers)
- API key (password field)
- Monthly budget ($)
- Model list (checkboxes for known models, text input for custom)

**Edit Provider** — same modal pre-filled from DB

**Toggle Model** — enable/disable individual model for routing without removing the provider

**Remove Provider** — confirmation dialog, sets `is_active = false`

### Backend Changes

#### 1. Enhanced `/api/external-providers` endpoint

Currently returns basic provider list. Enhance to include:
- ALL providers including MiniMax Cloud and Qwen3 Cloud (currently missing)
- 24h usage stats per provider from `cloud_model_usage`
- Budget percentage and threshold status
- Smart router tier position per model
- Per-model breakdown with individual stats

#### 2. New `/api/external-providers/stats` endpoint

Aggregated contractor dashboard data:
- Total monthly spend across all providers
- Per-provider 24h request counts, success rates, avg latency
- Per-model breakdown within each provider
- IAAE governance event count for external dispatches

#### 3. Model toggle endpoint

`PUT /api/external-providers/<provider>/models/<model>/toggle`
- Enable/disable specific model in routing
- Updates `model_tier_configs` is_active or equivalent flag
- Returns updated model status

#### 4. Fix Bridge Overview status card

Replace hardcoded 3-provider check with dynamic query:
- Read all providers from `external_api_keys` + Ollama cloud configs
- Show actual count and status per provider
- Budget health indicator

### Frontend Changes

#### 1. Crew tab sub-tab navigation

```html
<div class="crew-subtab-nav">
    <button class="crew-subtab active" data-subtab="roster">Active Roster</button>
    <button class="crew-subtab" data-subtab="contractors">Contractors</button>
</div>
```

#### 2. Contractor firm cards

Collapsible sections per provider with budget bar, status, and actions.

#### 3. Model worker cards

Purple-accented cards matching internal agent card dimensions and layout.

#### 4. Add/Edit Provider modal

Form with API key, budget, model selection. Writes to `/api/external-providers`.

#### 5. Budget summary header

Total spend across all contractors at top of Contractors sub-tab.

### IAAE Compliance Integration

- Every external dispatch already passes through orchestration_engine.py IAAE step
- Contractor cards display IAAE compliant badge (all external calls are governed)
- If IAAE blocks an external dispatch, it's logged in `governance_audit_log`
- IAAE overview endpoint already counts all governance events (internal + external)
- Contractor stats feed into the Bridge Overview IAAE compliance percentage

### Routing Mode Integration

The overview tab's routing mode dropdown controls contractor availability:

| Mode | Contractors |
|---|---|
| `local_only` | All contractors disabled (grayed out in UI) |
| `local_cloud` | MiniMax + Qwen3 Cloud enabled, paid APIs disabled |
| `full` | All contractors available per their individual toggle state |

Contractor cards visually reflect this — grayed out with "Routing: Local Only" label when mode restricts them.

### Data Flow

```
User Request
    → Orchestration Engine (IAAE check)
    → Smart Router (tier selection based on routing mode + model availability)
    → Bridge Dispatcher
        → Internal Agent (free, local) → logs to task_execution_log + agent_emotional_state
        → External Provider (cost, cloud) → logs to cloud_model_usage + governance_audit_log
    → Contractors sub-tab reads cloud_model_usage for stats
    → Agent cards read task_execution_log for stats
    → Both feed into Bridge Overview IAAE compliance
```

### No New Tables Needed

All data sources already exist:
- `external_api_keys` — provider config + budget
- `cloud_model_usage` — per-request tracking
- `model_tier_configs` — router tier settings
- `governance_audit_log` — IAAE events
- Smart router config — tier order, routing modes

### Future Enhancements (Not in this phase)

- Contract lifecycle (start/end dates, renewal reminders)
- Per-contractor SLA monitoring (latency thresholds, uptime)
- Auto-scaling between providers based on load/budget
- Contractor performance comparison dashboard
