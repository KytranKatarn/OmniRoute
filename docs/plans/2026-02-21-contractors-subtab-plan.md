# Contractors Sub-Tab Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a "Contractors" sub-tab to the Bridge Crew tab that surfaces external AI providers as contractor firms with per-model worker cards, full inline management, usage stats from `cloud_model_usage`, and IAAE compliance integration.

**Architecture:** The Crew tab already has sub-tabs (Manifest, Training, Lounge). We add a 4th "Contractors" sub-tab. Backend enhances the existing `/api/external-providers` endpoint and adds a stats endpoint. Frontend renders provider firms as collapsible sections with model worker cards matching the internal agent card style. The overview's hardcoded 3-provider display gets replaced with a dynamic query. Everything integrates with the existing smart router tier system, routing mode controls, and IAAE governance.

**Tech Stack:** Flask/Python backend (routes.py), Jinja2/Vanilla JS frontend (bridge.html), PostgreSQL (`external_api_keys`, `cloud_model_usage`, `model_tier_configs` tables), existing smart_router.py + external_providers.py.

**Design doc:** `docs/plans/2026-02-21-contractors-subtab-design.md`

---

### Task 1: Backend — Enhanced `/api/external-providers` with stats + cloud models

**Files:**
- Modify: `platform_v2/tools/bridge/routes.py:6650-6679` (GET endpoint)

**Step 1: Enhance the GET `/api/external-providers` endpoint**

Replace the current simple query (lines 6650-6679) with a comprehensive version that:
- Queries `external_api_keys` for DB-managed providers (OpenAI, Perplexity, xAI)
- Adds MiniMax Cloud and Qwen3 Cloud as virtual providers (from smart_router config, not in DB)
- Joins 24h usage stats from `cloud_model_usage` per provider
- Includes budget percentage calculation
- Includes per-model breakdown with individual 24h stats (dispatch count, avg latency, success rate, cost)
- Includes smart router tier position per model from TIER_ORDER

The enhanced response shape per provider:
```python
{
    "provider": "openai",
    "is_active": True,
    "monthly_budget_usd": 10.0,
    "current_month_cost_usd": 2.10,
    "budget_pct": 21.0,
    "source": "db",  # or "cloud_config" for MiniMax/Qwen3
    "tier_positions": {"gpt-4o-mini": 6, "gpt-4o": 6},
    "stats_24h": {"requests": 142, "cost": 2.10, "success_rate": 98.5, "avg_latency_ms": 1200},
    "models": [
        {
            "name": "gpt-4o-mini",
            "tier": "openai",
            "tier_position": 6,
            "enabled": True,
            "stats_24h": {"requests": 104, "cost": 0.85, "success_rate": 99.0, "avg_latency_ms": 950}
        }
    ]
}
```

For cloud providers (MiniMax, Qwen3), check if the Ollama API key is set via env var `OLLAMA_API_KEY` and query Ollama cloud model availability.

Use this SQL for 24h stats aggregation:
```sql
SELECT model_name, provider,
       COUNT(*) as requests,
       SUM(cost_usd) as cost,
       AVG(EXTRACT(EPOCH FROM (completed_at - created_at))) * 1000 as avg_latency_ms,
       ROUND(100.0 * SUM(CASE WHEN success THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 1) as success_rate
FROM cloud_model_usage
WHERE created_at >= NOW() - INTERVAL '24 hours'
GROUP BY model_name, provider
```

Map providers to models using `PROVIDER_CONFIGS` from `external_providers.py` and `DEFAULT_TIER_CONFIGS` from `smart_router.py`. The model-to-provider mapping:
- openai: gpt-4o-mini, gpt-4o
- perplexity: llama-3.1-sonar-small-128k-online
- xai: grok-2
- ollama_cloud: minimax-m2.5, qwen3-coder-next

TIER_ORDER positions: classify=0, local=1, local_analysis=2, minimax_cloud=3, qwen3_cloud=4, openai=5, perplexity=6, grok=7, haiku=8, sonnet=9, opus=10.

**Step 2: Verify endpoint returns all 5 providers**

Run: `curl -s -b <session> 'http://192.168.1.200:3000/tools/bridge/api/external-providers' | python3 -m json.tool`

Expected: 5 providers returned (openai, perplexity, xai, minimax_cloud, qwen3_cloud) each with models array and stats_24h.

**Step 3: Commit**

```bash
git add platform_v2/tools/bridge/routes.py
git commit -m "feat(bridge): enhance external-providers API with stats, cloud models, per-model breakdown"
```

---

### Task 2: Backend — Provider management improvements

**Files:**
- Modify: `platform_v2/tools/bridge/routes.py:6682-6734` (POST + toggle endpoints)

**Step 1: Update POST endpoint to accept cloud providers**

Currently the POST endpoint (line 6695) validates against only `("openai", "perplexity", "xai")`. Expand to also accept `"minimax_cloud"` and `"qwen3_cloud"` — for these, instead of storing an API key in `external_api_keys`, store a config note (they use `OLLAMA_API_KEY` from env).

Also add model toggle capability: accept an optional `models` field in the POST body — a dict of `{model_name: enabled}` — and update `model_tier_configs` accordingly.

**Step 2: Add model-level toggle endpoint**

Add new endpoint:
```python
@bridge_bp.route("/api/external-providers/<provider>/models/<model_name>/toggle", methods=["PUT"])
@login_required
def toggle_provider_model(provider, model_name):
    """Enable/disable a specific model under a provider for routing."""
```

This should update the model's availability in the routing system. For DB-managed providers, update `external_api_keys` metadata. For cloud providers, store toggle state in `platform_settings` (key: `model_disabled:<tier>`, value: `true/false`).

The smart router's `get_available_tiers()` should respect these toggles — but that's already handled by routing mode. Individual model toggles can be stored in `platform_settings` and checked by the enhanced provider list endpoint.

**Step 3: Verify toggle works**

Test: `curl -X PUT -H 'Content-Type: application/json' -d '{"enabled": false}' -b <session> 'http://192.168.1.200:3000/tools/bridge/api/external-providers/openai/models/gpt-4o/toggle'`

Expected: `{"success": true, "model": "gpt-4o", "enabled": false}`

**Step 4: Commit**

```bash
git add platform_v2/tools/bridge/routes.py
git commit -m "feat(bridge): add provider model toggle and expand provider management"
```

---

### Task 3: Frontend — Contractors sub-tab HTML + CSS

**Files:**
- Modify: `platform_v2/templates/tools/bridge.html:4280-4284` (add sub-tab button)
- Modify: `platform_v2/templates/tools/bridge.html:4347` (add sub-panel before crew panel close)
- Modify: `platform_v2/templates/tools/bridge.html` CSS section (add contractor styles)

**Step 1: Add "Contractors" sub-tab button**

After the Lounge button (line 4283), add:
```html
                    <button class="crew-subtab" data-subtab="contractors" onclick="switchCrewSubtab('contractors')">
                        <i data-lucide="building-2"></i>
                        <span data-i18n="bridge.crew.contractors">Contractors</span>
                    </button>
```

**Step 2: Add Contractors sub-panel HTML**

Before `</div><!-- /crew panel -->` (line 4348), insert:
```html
                <!-- Contractors Sub-Panel -->
                <div class="crew-subpanel" data-subpanel="contractors">
                    <div class="briefing-card" style="--card-accent: #a855f7; margin: 0 16px;">
                        <div class="briefing-card-header">
                            <i data-lucide="building-2"></i>
                            <span data-i18n="bridge.crew.external_contractors">External Contractors</span>
                            <span class="briefing-card-link" id="contractors-summary">-- providers</span>
                            <button onclick="openAddProviderModal()" style="background:rgba(168,85,247,0.15);border:1px solid rgba(168,85,247,0.3);color:#a855f7;padding:2px 8px;border-radius:4px;font-size:0.65rem;cursor:pointer;">+ Add Provider</button>
                        </div>
                        <div class="briefing-card-body">
                            <div id="contractors-grid">
                                <span class="briefing-muted">Loading contractors...</span>
                            </div>
                        </div>
                    </div>
                </div>
```

**Step 3: Add contractor CSS**

In the CSS section (after crew card styles, around line 1065), add styles for:
- `.contractor-firm` — collapsible firm container with purple border
- `.contractor-firm-header` — clickable header with flex layout, firm name, status dot, budget bar, actions
- `.contractor-firm-body` — hidden by default, shown when `.expanded` class toggled
- `.contractor-models-grid` — auto-fill grid for model cards (minmax 220px)
- `.contractor-model-card` — matches `crew-agent-card` style but with purple (#a855f7) left-border accent
- `.contractor-model-card.disabled` — 50% opacity for disabled models
- `.provider-modal-overlay` and `.provider-modal` — modal for add/edit provider
- Light mode overrides for all contractor elements

Use the same border-radius (8px), padding patterns, and transition timing as existing crew cards.

**Step 4: Verify HTML renders**

Restart container, navigate to Bridge, Crew, Contractors tab appears. Loading message shows.

**Step 5: Commit**

```bash
git add platform_v2/templates/tools/bridge.html
git commit -m "feat(bridge): add Contractors sub-tab HTML + CSS to crew panel"
```

---

### Task 4: Frontend — Contractors JavaScript (load + render)

**Files:**
- Modify: `platform_v2/templates/tools/bridge.html` (JS section, after crew manifest code ~line 7900+)

**Step 1: Add loadContractors and rendering functions**

After the crew manifest JS section, add the following functions:

- `loadContractors()` — fetches `/api/external-providers`, calls `renderContractors()`
- `renderContractors(providers)` — builds firm cards with collapsible headers and model worker cards underneath. Uses safe DOM methods (`createElement`, `textContent`, `appendChild`) for user data. Uses `escapeHtml()` (the global helper at line ~6862) for any values inserted via template strings in static structural markup.
- `toggleProvider(provider)` — POSTs to toggle endpoint, reloads contractors
- `toggleContractorModel(provider, model, enabled)` — PUTs to model toggle endpoint
- `openAddProviderModal()` — creates modal overlay with provider select, API key input, budget input
- `editProvider(provider)` — opens modal pre-filled for editing
- `saveProvider()` — POSTs to save endpoint, closes modal, reloads

Each firm header shows: chevron icon, firm name, tier position, status badge (Active/Inactive/Over Budget), budget bar with percentage fill, Edit and Toggle buttons.

Each model card shows: model name, "Contract Worker - Tier N" subtitle, 4-stat grid (tasks/24h, success%, avg latency, cost/24h), IAAE compliant badge, enable/disable checkbox toggle.

**Step 2: Hook into tab switching + initial load**

Update `switchCrewSubtab` (line 7745) to trigger `loadContractors()` when the contractors sub-tab is selected:

```javascript
function switchCrewSubtab(name) {
    // existing code...
    if (name === 'contractors') loadContractors();
}
```

**Step 3: Verify rendering**

Restart container, navigate to Bridge, Crew, Contractors. Provider cards should render with collapsible firm headers and model worker cards.

**Step 4: Commit**

```bash
git add platform_v2/templates/tools/bridge.html
git commit -m "feat(bridge): add Contractors sub-tab JS — load, render, manage providers"
```

---

### Task 5: Fix Bridge Overview — dynamic provider display

**Files:**
- Modify: `platform_v2/tools/bridge/routes.py:2403-2452` (llm/status endpoint)
- Modify: `platform_v2/templates/tools/bridge.html:4816-4866` (overview status card JS)

**Step 1: Enhance `/api/llm/status` to return all providers dynamically**

Currently (line 2449-2456) the endpoint checks 3 hardcoded `conn_id` values: `claude_api`, `openai_api`, `grok_api`. Replace with a dynamic query that:
1. Queries `external_api_keys` table for all providers + their `is_active` status
2. Checks Ollama cloud models (MiniMax, Qwen3) via `OLLAMA_API_KEY` env var
3. Returns all providers with status: `active`, `configured` (has key but inactive), `no_key`

**Step 2: Update overview JS to render dynamic provider list**

Replace the hardcoded external provider rendering (lines 4851-4864) in the overview status card JavaScript. The new rendering should iterate over `data.external` and show all returned providers with appropriate status dots and budget info.

**Step 3: Verify overview shows all providers**

Restart, check Bridge Overview AI Bridge Status card shows all configured providers (not just 3).

**Step 4: Commit**

```bash
git add platform_v2/tools/bridge/routes.py platform_v2/templates/tools/bridge.html
git commit -m "fix(bridge): overview AI status shows all providers dynamically"
```

---

### Task 6: Integration — routing mode reflects in contractor cards

**Files:**
- Modify: `platform_v2/templates/tools/bridge.html` (contractors JS)

**Step 1: Pass routing mode to contractor display**

When rendering contractor cards, fetch the current routing mode (already available from `loadRoutingMode`). If `local_only`, show all contractor firms as grayed out with "Routing: Local Only" overlay. If `local_cloud`, gray out paid API providers (OpenAI, Perplexity, Grok) but keep cloud providers (MiniMax, Qwen3) active.

Add to `loadContractors()`:
```javascript
// Fetch routing mode alongside providers
const [provResp, modeResp] = await Promise.all([
    fetch('/tools/bridge/api/external-providers'),
    fetch('/tools/bridge/api/routing-mode')
]);
```

Pass `routing_mode` to `renderContractors()` and use it to determine visual state of each firm card.

**Step 2: Verify routing mode visual feedback**

Toggle routing mode in overview controls. Switch to Contractors tab — paid providers should gray out in local_cloud mode, all contractors gray out in local_only.

**Step 3: Commit**

```bash
git add platform_v2/templates/tools/bridge.html
git commit -m "feat(bridge): contractors reflect routing mode state"
```

---

### Task 7: Integration — IAAE compliance on contractor cards

**Files:**
- Modify: `platform_v2/tools/bridge/routes.py` (enhance external-providers with IAAE data)

**Step 1: Add IAAE governance count to provider stats**

In the enhanced `/api/external-providers` endpoint, also query `governance_audit_log` for events related to external model dispatches in the last 24h. Add `iaae_events_24h` and `iaae_blocked_24h` counts per provider to the response.

```sql
SELECT COUNT(*) as total,
       SUM(CASE WHEN outcome = 'blocked' THEN 1 ELSE 0 END) as blocked
FROM governance_audit_log
WHERE timestamp >= NOW() - INTERVAL '24 hours'
  AND details::text LIKE '%provider_name%'
```

**Step 2: Update contractor model cards to show IAAE status**

If `iaae_blocked_24h > 0`, show "IAAE: X blocked" in yellow instead of "IAAE: Compliant" in green.

**Step 3: Commit**

```bash
git add platform_v2/tools/bridge/routes.py platform_v2/templates/tools/bridge.html
git commit -m "feat(bridge): IAAE compliance data on contractor cards"
```

---

### Task 8: Final polish + restart + verify

**Files:**
- All modified files

**Step 1: Full restart and visual verification**

```bash
docker compose restart archie_platform
```

Navigate to Bridge, Crew, Contractors:
- All 5 providers render as collapsible firm cards
- Model worker cards show under each firm
- Budget bars reflect actual spend
- Toggles work for enable/disable
- Add Provider modal works
- IAAE badges show on each model card

Check Bridge Overview:
- AI Bridge Status card shows all providers (not just 3)
- Status dots reflect actual configuration

Check routing mode integration:
- Switch to "Local Only" then contractors gray out
- Switch to "Local + Cloud" then only free cloud providers active
- Switch to "Full" then all contractors available

**Step 2: Commit any final adjustments**

**Step 3: Push**

```bash
git push
```
