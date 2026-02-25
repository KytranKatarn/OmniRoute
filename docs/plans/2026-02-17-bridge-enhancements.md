# Bridge Enhancements Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add 7 enhancements to BridgeDispatcher: routing mode toggle, escalation process, external AI contractors, Telegram approval flow, bridge learning, agent naming, and dashboard agent display.

**Architecture:** Infrastructure-first — Phase 1 (routing toggle + escalation) unlocks Phase 2 (external AI), which unlocks Phase 3 (Telegram approval + learning), which unlocks Phase 4 (naming + dashboard). Each phase builds on the previous. All changes extend the existing BridgeDispatcher singleton in `ai_bridge/bridge_dispatcher.py`.

**Tech Stack:** Python 3.11, Flask, PostgreSQL, python-telegram-bot, Fernet encryption, OpenAI-compatible APIs (httpx/requests), LCARS CSS theme

---

## Phase 1: Local-Only/Cloud Toggle + Escalation Process

### Task 1: Migration 105 — platform_settings + dispatch_escalation_log

**Files:**
- Create: `database/migrations/105_bridge_escalation.sql`

**Step 1: Write the migration SQL**

```sql
-- Migration 105: Bridge Escalation & Platform Settings
-- Project: Bridge Enhancements — Phase 1

-- Generic platform settings (key-value with typed values)
CREATE TABLE IF NOT EXISTS platform_settings (
    key VARCHAR(100) PRIMARY KEY,
    value TEXT NOT NULL,
    value_type VARCHAR(20) DEFAULT 'string',  -- string, int, bool, json
    description TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Seed routing mode default
INSERT INTO platform_settings (key, value, value_type, description)
VALUES
    ('routing_mode', 'full', 'string', 'Bridge routing mode: local_only, local_cloud, or full'),
    ('escalation_threshold', '3', 'int', 'Consecutive failures before auto-escalation'),
    ('escalation_auto_deny_minutes', '15', 'int', 'Minutes before paid escalation auto-denies')
ON CONFLICT (key) DO NOTHING;

-- Escalation audit log
CREATE TABLE IF NOT EXISTS dispatch_escalation_log (
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
    approval_method VARCHAR(20) DEFAULT 'auto',  -- auto, telegram, timeout
    success BOOLEAN,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_del_created ON dispatch_escalation_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_del_agent ON dispatch_escalation_log(original_agent_id);
```

**Step 2: Run the migration**

Run: `docker exec -i archie_database psql -U archie -d archie < database/migrations/105_bridge_escalation.sql`
Expected: CREATE TABLE, INSERT, CREATE INDEX messages with no errors

**Step 3: Verify tables exist**

Run: `docker exec archie_database psql -U archie -d archie -c "\dt platform_settings" -c "\dt dispatch_escalation_log" -c "SELECT * FROM platform_settings;"`
Expected: Both tables listed, 3 seed rows in platform_settings

**Step 4: Commit**

```bash
git add database/migrations/105_bridge_escalation.sql
git commit -m "feat(bridge): migration 105 — platform_settings + dispatch_escalation_log"
```

---

### Task 2: SmartRouter — get_available_tiers() filter

**Files:**
- Modify: `ai_bridge/smart_router.py:152` (TIER_ORDER constant area)
- Modify: `ai_bridge/smart_router.py:260-288` (suggest_model_by_capability method)

**Step 1: Add get_available_tiers() to SmartRouter**

In `ai_bridge/smart_router.py`, after the `CAPABILITY_ROUTING` dict (line 166), add a module-level helper to read routing_mode from platform_settings:

```python
def _get_routing_mode() -> str:
    """Read routing_mode from platform_settings. Returns 'full' on error."""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT value FROM platform_settings WHERE key = 'routing_mode'")
        row = cur.fetchone()
        cur.close()
        conn.close()
        return row[0] if row else "full"
    except Exception:
        return "full"
```

Then add a method to `SmartRouter` class (after `__init__`, before `_get_model_configs`):

```python
def get_available_tiers(self, routing_mode: str = None) -> list:
    """Filter TIER_ORDER based on routing mode.

    - local_only: only local Ollama tiers (classify, local, local_analysis, vision)
    - local_cloud: local + Ollama cloud (+ minimax_cloud, qwen3_cloud)
    - full: all tiers including paid APIs and Claude
    """
    if routing_mode is None:
        routing_mode = _get_routing_mode()

    local_tiers = {"classify", "local", "local_analysis", "vision"}
    cloud_tiers = {"minimax_cloud", "qwen3_cloud"}

    if routing_mode == "local_only":
        return [t for t in TIER_ORDER if t in local_tiers]
    elif routing_mode == "local_cloud":
        return [t for t in TIER_ORDER if t in local_tiers | cloud_tiers]
    else:  # "full"
        return list(TIER_ORDER)
```

**Step 2: Wire get_available_tiers into suggest_model_by_capability**

In `suggest_model_by_capability` (line 260), add routing_mode filtering. After the capability lookup succeeds (line 276-286), add a check:

```python
def suggest_model_by_capability(self, capability, fallback_task_type="code_simple", **kwargs):
    tier = CAPABILITY_ROUTING.get(capability)
    if tier:
        available = self.get_available_tiers()
        if tier not in available:
            # Tier blocked by routing mode — find next available
            for t in available:
                configs = self._get_model_configs()
                if t in configs:
                    return RoutingRecommendation(
                        tier=configs[t].tier,
                        provider=configs[t].provider,
                        model_name=configs[t].model_name,
                        reason=f"Capability '{capability}' tier '{tier}' blocked by routing mode, using '{t}'",
                    )
        configs = self._get_model_configs()
        config = configs.get(tier)
        if config:
            return RoutingRecommendation(
                tier=config.tier, provider=config.provider,
                model_name=config.model_name,
                reason=f"Capability '{capability}' -> {tier} tier",
            )
    return self.suggest_model(task_type=fallback_task_type, **kwargs)
```

**Step 3: Verify import works**

Run: `docker exec archie_platform python3 -c "from smart_router import SmartRouter; r = SmartRouter(); print(r.get_available_tiers('local_only')); print(r.get_available_tiers('full'))"`
Expected: `['classify', 'local', 'local_analysis']` and full list

**Step 4: Commit**

```bash
git add ai_bridge/smart_router.py
git commit -m "feat(bridge): SmartRouter routing mode filter — get_available_tiers()"
```

---

### Task 3: BridgeDispatcher — Failure Tracker + Escalation Logic

**Files:**
- Modify: `ai_bridge/bridge_dispatcher.py:1-26` (imports)
- Modify: `ai_bridge/bridge_dispatcher.py:170-200` (BridgeDispatcher.__init__ area)
- Modify: `ai_bridge/bridge_dispatcher.py:361-468` (request_work method)

**Step 1: Add failure tracker to BridgeDispatcher.__init__**

In `bridge_dispatcher.py`, add to `__init__` (after the existing cache init):

```python
# Failure tracking for escalation (in-memory, reset on success)
self._failure_tracker = {}  # (agent_id, capability) -> count
self._escalation_threshold = 3  # overridden by platform_settings
```

**Step 2: Add private escalation methods**

After `_log_execution` (line ~355), add:

```python
def _get_escalation_threshold(self) -> int:
    """Read escalation threshold from platform_settings."""
    try:
        conn = self._get_db()
        cur = conn.cursor()
        cur.execute("SELECT value FROM platform_settings WHERE key = 'escalation_threshold'")
        row = cur.fetchone()
        cur.close()
        conn.close()
        return int(row[0]) if row else 3
    except Exception:
        return 3

def _track_failure(self, agent_id: int, capability: str) -> int:
    """Increment failure count, return new count."""
    key = (agent_id, capability)
    self._failure_tracker[key] = self._failure_tracker.get(key, 0) + 1
    return self._failure_tracker[key]

def _reset_failure(self, agent_id: int, capability: str):
    """Reset failure count on success."""
    self._failure_tracker.pop((agent_id, capability), None)

def _get_next_tier(self, current_model: str, capability: str) -> Optional[Dict]:
    """Find the next escalation tier above current model.

    Returns dict with {tier, model, provider, is_paid} or None.
    """
    try:
        from smart_router import SmartRouter, TIER_ORDER
        router = SmartRouter()
        available = router.get_available_tiers()
        configs = router._get_model_configs()

        # Find current tier
        current_tier = None
        for tier_name, config in configs.items():
            if config.model_name == current_model or current_model.startswith(config.model_name.split(":")[0]):
                current_tier = tier_name
                break

        if not current_tier:
            return None

        # Find next available tier
        found_current = False
        for tier in available:
            if tier == current_tier:
                found_current = True
                continue
            if found_current and tier in configs:
                config = configs[tier]
                is_paid = tier in ("haiku", "sonnet", "opus") or config.provider not in ("ollama", "ollama_cloud")
                return {
                    "tier": tier,
                    "model": config.model_name,
                    "provider": config.provider,
                    "is_paid": is_paid,
                }
        return None
    except Exception as e:
        logger.warning(f"[BridgeDispatcher] get_next_tier failed: {e}")
        return None

def _log_escalation(self, original_agent_id, original_model, escalated_model,
                     escalated_provider, capability, module_id, reason,
                     failure_count, approval_method="auto", success=None, cost=0):
    """Log an escalation event to dispatch_escalation_log."""
    try:
        conn = self._get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO dispatch_escalation_log
            (original_agent_id, original_model, escalated_model, escalated_provider,
             capability, module_id, reason, failure_count, cost_usd,
             approved_by, approval_method, success)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (original_agent_id, original_model, escalated_model, escalated_provider,
              capability, module_id, reason, failure_count, cost,
              "system" if approval_method == "auto" else None,
              approval_method, success))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.warning(f"[BridgeDispatcher] Failed to log escalation: {e}")
```

**Step 3: Wire escalation into request_work**

In `request_work` (line 361), after the LLM execution block (line ~444) and before building the result (line ~448), add escalation logic:

```python
        # 4. Execute the LLM call
        llm_result = self._execute_llm(...)
        duration_ms = int((time.time() - start) * 1000)

        # 4b. Escalation on failure
        if not llm_result.get("success", False):
            failure_count = self._track_failure(agent.get("id", 0), capability)
            threshold = self._get_escalation_threshold()

            if failure_count >= threshold:
                next_tier = self._get_next_tier(model, capability)
                if next_tier and not next_tier["is_paid"]:
                    # Auto-escalate to free tier
                    logger.info(
                        f"[BridgeDispatcher] Auto-escalating {capability}: "
                        f"{model} -> {next_tier['model']} (free, {failure_count} failures)"
                    )
                    escalated_result = self._execute_llm(
                        model=next_tier["model"], prompt=prompt,
                        system_prompt=system_prompt, json_mode=json_mode,
                        prefer_gpu=prefer_gpu, timeout=timeout,
                    )
                    if escalated_result.get("success"):
                        self._reset_failure(agent.get("id", 0), capability)
                        self._log_escalation(
                            agent.get("id"), model, next_tier["model"],
                            next_tier["provider"], capability, module_id,
                            f"{failure_count} consecutive failures", failure_count,
                            approval_method="auto", success=True,
                        )
                        llm_result = escalated_result
                        model = next_tier["model"]  # update for result
                        duration_ms = int((time.time() - start) * 1000)
                elif next_tier and next_tier["is_paid"]:
                    # Submit to approval queue for paid tier
                    logger.info(
                        f"[BridgeDispatcher] Paid escalation needed: {model} -> "
                        f"{next_tier['model']} ({next_tier['provider']}). "
                        f"Submitting for approval."
                    )
                    try:
                        from agent_loop import request_approval
                        request_approval(
                            action_type="escalation",
                            action_data={
                                "original_model": model,
                                "escalated_model": next_tier["model"],
                                "escalated_provider": next_tier["provider"],
                                "capability": capability,
                                "module_id": module_id,
                                "failure_count": failure_count,
                                "prompt_preview": prompt[:200],
                            },
                            reason=f"Escalation: {failure_count}x failures on {model} for {capability}",
                            tier=2,
                        )
                    except Exception as esc_err:
                        logger.warning(f"[BridgeDispatcher] Approval submission failed: {esc_err}")
                    self._log_escalation(
                        agent.get("id"), model, next_tier["model"],
                        next_tier["provider"], capability, module_id,
                        f"{failure_count} failures, awaiting approval", failure_count,
                        approval_method="telegram", success=None,
                    )
        else:
            # Success — reset failure tracker
            self._reset_failure(agent.get("id", 0), capability)
```

**Step 4: Verify dispatcher loads without errors**

Run: `docker exec archie_platform python3 -c "from bridge_dispatcher import get_dispatcher; d = get_dispatcher(); print('OK', len(d._failure_tracker))"`
Expected: `OK 0`

**Step 5: Commit**

```bash
git add ai_bridge/bridge_dispatcher.py
git commit -m "feat(bridge): failure tracking + auto-escalation in BridgeDispatcher"
```

---

### Task 4: Bridge API — Routing Mode Endpoints

**Files:**
- Modify: `platform_v2/tools/bridge/routes.py:1-40` (add imports if needed)
- Modify: `platform_v2/tools/bridge/routes.py` (add 2 new endpoints)

**Step 1: Add GET/POST routing-mode endpoints**

Add these endpoints to `bridge/routes.py` (before the template render route):

```python
@bridge_bp.route("/api/routing-mode", methods=["GET"])
@login_required
def get_routing_mode():
    """Get current bridge routing mode."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT value FROM platform_settings WHERE key = 'routing_mode'")
        row = cur.fetchone()
        cur.close()
        conn.close()
        return jsonify({"success": True, "routing_mode": row["value"] if row else "full"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@bridge_bp.route("/api/routing-mode", methods=["POST"])
@login_required
def set_routing_mode():
    """Set bridge routing mode: local_only, local_cloud, or full."""
    data = request.get_json() or {}
    mode = data.get("routing_mode", "full")
    if mode not in ("local_only", "local_cloud", "full"):
        return jsonify({"success": False, "error": f"Invalid mode: {mode}"}), 400
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO platform_settings (key, value, value_type, description, updated_at)
            VALUES ('routing_mode', %s, 'string', 'Bridge routing mode', NOW())
            ON CONFLICT (key) DO UPDATE SET value = %s, updated_at = NOW()
        """, (mode, mode))
        conn.commit()
        cur.close()
        conn.close()
        logger.info(f"[Bridge] Routing mode changed to: {mode}")
        return jsonify({"success": True, "routing_mode": mode})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@bridge_bp.route("/api/escalation-log", methods=["GET"])
@login_required
def get_escalation_log():
    """Get recent escalation events."""
    limit = request.args.get("limit", 20, type=int)
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT del.*, a.name as agent_name
            FROM dispatch_escalation_log del
            LEFT JOIN agents a ON a.id = del.original_agent_id
            ORDER BY del.created_at DESC
            LIMIT %s
        """, (limit,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify({"success": True, "escalations": [dict(r) for r in rows]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
```

**Step 2: Verify endpoints respond**

Run: `docker compose restart archie_platform && sleep 5 && docker logs archie_platform --tail 20 2>&1 | grep -i error`
Expected: No bridge-related import errors

**Step 3: Commit**

```bash
git add platform_v2/tools/bridge/routes.py
git commit -m "feat(bridge): routing mode + escalation log API endpoints"
```

---

### Task 5: Bridge UI — 3-State Routing Toggle

**Files:**
- Modify: `platform_v2/templates/tools/bridge.html` (add toggle in header area)

**Step 1: Add routing mode toggle to bridge.html**

Find the header/toolbar area of bridge.html (after the opening `<style>` block ends and the main content begins). Add a routing mode control:

```html
<!-- Routing Mode Toggle -->
<div class="routing-mode-control" style="display:flex;align-items:center;gap:12px;padding:8px 16px;background:var(--bridge-panel);border:1px solid var(--bridge-border);border-radius:8px;margin-bottom:12px;">
    <span style="color:var(--bridge-gold);font-family:'Orbitron',sans-serif;font-size:11px;text-transform:uppercase;">Routing Mode</span>
    <div class="btn-group" id="routingModeGroup">
        <button class="routing-btn" data-mode="local_only" title="Local Ollama models only — no network calls">
            Local Only
        </button>
        <button class="routing-btn" data-mode="local_cloud" title="Local + Ollama cloud (free) — no paid APIs">
            Local + Cloud
        </button>
        <button class="routing-btn active" data-mode="full" title="All tiers including paid external APIs and Claude">
            Full
        </button>
    </div>
    <span id="routingModeStatus" style="color:var(--bridge-muted);font-size:11px;"></span>
</div>
```

Add CSS for the routing buttons:

```css
.routing-btn {
    padding: 4px 14px;
    font-size: 11px;
    font-family: 'IBM Plex Mono', monospace;
    background: transparent;
    color: var(--bridge-muted);
    border: 1px solid var(--bridge-border);
    cursor: pointer;
    transition: all 0.2s;
}
.routing-btn:first-child { border-radius: 4px 0 0 4px; }
.routing-btn:last-child { border-radius: 0 4px 4px 0; }
.routing-btn.active {
    background: var(--bridge-gold);
    color: #000;
    border-color: var(--bridge-gold);
}
.routing-btn:hover:not(.active) {
    color: var(--bridge-text);
    border-color: var(--bridge-gold);
}
```

Add JavaScript (use textContent for safe DOM updates):

```javascript
// Routing Mode Toggle
async function loadRoutingMode() {
    try {
        const res = await fetch('/tools/bridge/api/routing-mode');
        const data = await res.json();
        if (data.success) {
            document.querySelectorAll('.routing-btn').forEach(btn => {
                btn.classList.toggle('active', btn.dataset.mode === data.routing_mode);
            });
        }
    } catch (e) { console.error('Failed to load routing mode:', e); }
}

document.querySelectorAll('.routing-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
        const mode = btn.dataset.mode;
        try {
            const res = await fetch('/tools/bridge/api/routing-mode', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({routing_mode: mode}),
            });
            const data = await res.json();
            if (data.success) {
                document.querySelectorAll('.routing-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                document.getElementById('routingModeStatus').textContent = 'Mode: ' + mode;
            }
        } catch (e) { console.error('Failed to set routing mode:', e); }
    });
});

// Load on page init
loadRoutingMode();
```

**Step 2: Verify no syntax errors in template**

Run: `docker exec archie_platform python3 -c "from jinja2 import Environment, FileSystemLoader; e=Environment(loader=FileSystemLoader('/app/templates')); t=e.get_template('tools/bridge.html'); print('Template OK')"`
Expected: `Template OK`

**Step 3: Commit**

```bash
git add platform_v2/templates/tools/bridge.html
git commit -m "feat(bridge): 3-state routing mode toggle in Bridge UI"
```

---

### Task 6: Verify Phase 1 End-to-End

**Step 1: Restart and verify no errors**

Run: `docker compose restart archie_platform && sleep 8 && docker logs archie_platform --tail 30 2>&1 | grep -iE "error|bridge|routing"`
Expected: No errors, bridge imports clean

**Step 2: Verify DB state**

Run: `docker exec archie_database psql -U archie -d archie -c "SELECT * FROM platform_settings;" -c "SELECT count(*) FROM dispatch_escalation_log;"`
Expected: 3 settings rows, 0 escalation rows

**Step 3: Verify SmartRouter filtering**

Run: `docker exec archie_platform python3 -c "from smart_router import SmartRouter; r=SmartRouter(); print('local_only:', r.get_available_tiers('local_only')); print('local_cloud:', r.get_available_tiers('local_cloud')); print('full:', r.get_available_tiers('full'))"`
Expected: Correct filtered lists for each mode

**Step 4: Commit phase tag**

```bash
git add -A
git commit -m "feat(bridge): Phase 1 complete — routing mode toggle + escalation process"
```

---

## Phase 2: External AI Contractors

### Task 7: Migration 106 — external_api_keys + cost tracking

**Files:**
- Create: `database/migrations/106_external_providers.sql`

**Step 1: Write the migration**

```sql
-- Migration 106: External AI Providers
-- API key storage + cost tracking for OpenAI, Perplexity, xAI

CREATE TABLE IF NOT EXISTS external_api_keys (
    id SERIAL PRIMARY KEY,
    provider VARCHAR(50) NOT NULL UNIQUE,  -- openai, perplexity, xai
    api_key_encrypted TEXT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    monthly_budget_usd NUMERIC(10,2) DEFAULT 10.00,
    current_month_cost_usd NUMERIC(10,2) DEFAULT 0.00,
    budget_reset_day INTEGER DEFAULT 1,
    last_reset_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Add cost column to existing cloud_model_usage table
ALTER TABLE cloud_model_usage ADD COLUMN IF NOT EXISTS cost_usd NUMERIC(10,6) DEFAULT 0;

-- Cost summary view
CREATE OR REPLACE VIEW v_external_cost_summary AS
SELECT
    provider,
    date_trunc('day', timestamp) as day,
    COUNT(*) as calls,
    SUM(cost_usd) as daily_cost,
    SUM(prompt_tokens) as total_prompt_tokens,
    SUM(completion_tokens) as total_completion_tokens
FROM cloud_model_usage
WHERE provider NOT IN ('ollama', 'ollama_cloud')
GROUP BY provider, date_trunc('day', timestamp)
ORDER BY day DESC, provider;

-- Add external AI tiers to model_tier_configs
INSERT INTO model_tier_configs (tier_name, provider, model_name, is_active, input_cost_per_1m, output_cost_per_1m, max_tokens)
VALUES
    ('openai', 'openai', 'gpt-4o-mini', TRUE, 0.15, 0.60, 16384),
    ('perplexity', 'perplexity', 'llama-3.1-sonar-small-128k-online', TRUE, 0.20, 0.20, 8192),
    ('grok', 'xai', 'grok-2', TRUE, 2.00, 10.00, 8192)
ON CONFLICT (tier_name) DO UPDATE SET
    provider = EXCLUDED.provider,
    model_name = EXCLUDED.model_name,
    input_cost_per_1m = EXCLUDED.input_cost_per_1m,
    output_cost_per_1m = EXCLUDED.output_cost_per_1m,
    is_active = EXCLUDED.is_active;
```

**Step 2: Run the migration**

Run: `docker exec -i archie_database psql -U archie -d archie < database/migrations/106_external_providers.sql`
Expected: CREATE TABLE, ALTER TABLE, CREATE VIEW, INSERT messages

**Step 3: Verify**

Run: `docker exec archie_database psql -U archie -d archie -c "\dt external_api_keys" -c "SELECT tier_name, provider, model_name FROM model_tier_configs WHERE tier_name IN ('openai','perplexity','grok');"`
Expected: Table exists, 3 new tier rows

**Step 4: Commit**

```bash
git add database/migrations/106_external_providers.sql
git commit -m "feat(bridge): migration 106 — external_api_keys + cost tracking + new tiers"
```

---

### Task 8: External Providers Module

**Files:**
- Create: `ai_bridge/external_providers.py`

**Step 1: Write the external providers module**

```python
"""
External AI Provider Integration
Supports OpenAI, Perplexity, and xAI (Grok) via OpenAI-compatible APIs.

All functions return: {success, response, model, provider, prompt_tokens, completion_tokens, cost_usd}
"""

import json
import logging
import os
import time
import requests
from typing import Optional, Dict

logger = logging.getLogger(__name__)

# Cost per 1K tokens (updated Feb 2026)
COST_PER_1K_TOKENS = {
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "gpt-4o": {"input": 0.0025, "output": 0.01},
    "llama-3.1-sonar-small-128k-online": {"input": 0.0002, "output": 0.0002},
    "grok-2": {"input": 0.002, "output": 0.01},
}

PROVIDER_CONFIGS = {
    "openai": {"base_url": "https://api.openai.com/v1", "default_model": "gpt-4o-mini"},
    "perplexity": {"base_url": "https://api.perplexity.ai", "default_model": "llama-3.1-sonar-small-128k-online"},
    "xai": {"base_url": "https://api.x.ai/v1", "default_model": "grok-2"},
}


def _get_api_key(provider: str) -> Optional[str]:
    """Get API key for provider — from env var or DB fallback."""
    env_map = {"openai": "OPENAI_API_KEY", "perplexity": "PERPLEXITY_API_KEY", "xai": "XAI_API_KEY"}
    key = os.getenv(env_map.get(provider, ""))
    if key:
        return key

    try:
        from database import get_db
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT api_key_encrypted FROM external_api_keys WHERE provider = %s AND is_active = TRUE",
            (provider,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row and row[0]:
            return row[0]
    except Exception as e:
        logger.debug(f"DB key lookup failed for {provider}: {e}")
    return None


def _check_budget(provider: str) -> bool:
    """Check if provider is within monthly budget. Returns True if OK."""
    try:
        from database import get_db
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT monthly_budget_usd, current_month_cost_usd FROM external_api_keys WHERE provider = %s",
            (provider,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            return True
        return float(row[1] or 0) < float(row[0] or 10)
    except Exception:
        return True


def _calculate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Calculate cost in USD."""
    rates = COST_PER_1K_TOKENS.get(model, {"input": 0.001, "output": 0.001})
    return (prompt_tokens * rates["input"] / 1000) + (completion_tokens * rates["output"] / 1000)


def _update_cost(provider: str, cost: float):
    """Add cost to current month tracking."""
    try:
        from database import get_db
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "UPDATE external_api_keys SET current_month_cost_usd = current_month_cost_usd + %s, updated_at = NOW() WHERE provider = %s",
            (cost, provider),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.warning(f"Failed to update cost for {provider}: {e}")


def _log_usage(provider: str, model: str, prompt_tokens: int, completion_tokens: int, cost: float):
    """Log to cloud_model_usage table."""
    try:
        from database import get_db
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO cloud_model_usage (model_name, provider, prompt_tokens, completion_tokens, cost_usd, timestamp)
            VALUES (%s, %s, %s, %s, %s, NOW())
        """, (model, provider, prompt_tokens, completion_tokens, cost))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.debug(f"Failed to log usage: {e}")


def _call_openai_compatible(
    provider: str,
    prompt: str,
    model: str = None,
    system_prompt: str = None,
    json_mode: bool = False,
    timeout: int = 120,
) -> Dict:
    """Generic OpenAI-compatible API call."""
    config = PROVIDER_CONFIGS.get(provider)
    if not config:
        return {"success": False, "error": f"Unknown provider: {provider}", "provider": provider}

    api_key = _get_api_key(provider)
    if not api_key:
        return {"success": False, "error": f"No API key for {provider}", "provider": provider}

    if not _check_budget(provider):
        return {"success": False, "error": f"Monthly budget exceeded for {provider}", "provider": provider}

    model = model or config["default_model"]
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = {"model": model, "messages": messages}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    try:
        start = time.time()
        resp = requests.post(
            f"{config['base_url']}/chat/completions",
            headers=headers,
            json=payload,
            timeout=timeout,
        )
        duration_ms = int((time.time() - start) * 1000)
        resp.raise_for_status()

        data = resp.json()
        choice = data["choices"][0]
        usage = data.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        cost = _calculate_cost(model, prompt_tokens, completion_tokens)

        _update_cost(provider, cost)
        _log_usage(provider, model, prompt_tokens, completion_tokens, cost)

        return {
            "success": True,
            "response": choice["message"]["content"],
            "model": model,
            "provider": provider,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cost_usd": cost,
            "duration_ms": duration_ms,
        }

    except requests.exceptions.Timeout:
        return {"success": False, "error": f"Timeout after {timeout}s", "model": model, "provider": provider}
    except requests.exceptions.HTTPError as e:
        return {"success": False, "error": f"HTTP {e.response.status_code}: {e.response.text[:200]}", "model": model, "provider": provider}
    except Exception as e:
        return {"success": False, "error": str(e), "model": model, "provider": provider}


def call_openai(prompt, model=None, system_prompt=None, json_mode=False, timeout=120):
    """Call OpenAI API."""
    return _call_openai_compatible("openai", prompt, model, system_prompt, json_mode, timeout)


def call_perplexity(prompt, model=None, system_prompt=None, json_mode=False, timeout=120):
    """Call Perplexity API (with web search)."""
    return _call_openai_compatible("perplexity", prompt, model, system_prompt, json_mode, timeout)


def call_grok(prompt, model=None, system_prompt=None, json_mode=False, timeout=120):
    """Call xAI Grok API."""
    return _call_openai_compatible("xai", prompt, model, system_prompt, json_mode, timeout)
```

**Step 2: Verify module imports**

Run: `docker exec archie_platform python3 -c "from external_providers import call_openai, call_perplexity, call_grok, COST_PER_1K_TOKENS; print('OK, providers:', list(COST_PER_1K_TOKENS.keys()))"`
Expected: `OK, providers: ['gpt-4o-mini', 'gpt-4o', 'llama-3.1-sonar-small-128k-online', 'grok-2']`

**Step 3: Commit**

```bash
git add ai_bridge/external_providers.py
git commit -m "feat(bridge): external AI providers — OpenAI, Perplexity, xAI (Grok)"
```

---

### Task 9: Update SmartRouter TIER_ORDER + BridgeDispatcher Routing

**Files:**
- Modify: `ai_bridge/smart_router.py:152` (TIER_ORDER)
- Modify: `ai_bridge/bridge_dispatcher.py:264-310` (_execute_llm)

**Step 1: Extend TIER_ORDER**

In `smart_router.py` line 152, update:

```python
TIER_ORDER = [
    "classify", "local", "local_analysis",
    "minimax_cloud", "qwen3_cloud",
    "openai", "perplexity", "grok",
    "haiku", "sonnet", "opus",
]
```

**Step 2: Extend BridgeDispatcher._execute_llm for external providers**

In `bridge_dispatcher.py`, in `_execute_llm` (line 264), add routing to external providers after the import line but before the cloud model check:

```python
def _execute_llm(self, model, prompt, system_prompt=None, json_mode=False,
                 prefer_gpu=True, temperature=0.5, timeout=300):
    try:
        from archie_bridge import call_ollama, call_ollama_json, call_ollama_cloud

        # Route to external providers
        if model in ("gpt-4o-mini", "gpt-4o"):
            from external_providers import call_openai
            return call_openai(prompt, model=model, system_prompt=system_prompt,
                             json_mode=json_mode, timeout=timeout)
        if model.startswith("llama-3.1-sonar"):
            from external_providers import call_perplexity
            return call_perplexity(prompt, model=model, system_prompt=system_prompt,
                                  json_mode=json_mode, timeout=timeout)
        if model.startswith("grok"):
            from external_providers import call_grok
            return call_grok(prompt, model=model, system_prompt=system_prompt,
                           json_mode=json_mode, timeout=timeout)

        # Route cloud models (existing)
        if ":cloud" in model or model in ("minimax-m2.5", "qwen3-coder-next"):
            return call_ollama_cloud(prompt, model=model, system_prompt=system_prompt)

        # ... rest of existing code unchanged
```

**Step 3: Verify routing works**

Run: `docker exec archie_platform python3 -c "from smart_router import TIER_ORDER; print(TIER_ORDER); assert 'openai' in TIER_ORDER; assert TIER_ORDER.index('openai') < TIER_ORDER.index('haiku'); print('OK')"`
Expected: Full tier list printed, OK

**Step 4: Commit**

```bash
git add ai_bridge/smart_router.py ai_bridge/bridge_dispatcher.py
git commit -m "feat(bridge): external AI tiers in SmartRouter + dispatcher routing"
```

---

### Task 10: Bridge API — External Provider Key Management

**Files:**
- Modify: `platform_v2/tools/bridge/routes.py` (add key management endpoints)

**Step 1: Add API key CRUD endpoints**

```python
@bridge_bp.route("/api/external-providers", methods=["GET"])
@login_required
def get_external_providers():
    """List external AI providers and their status (keys masked)."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT id, provider, is_active, monthly_budget_usd, current_month_cost_usd,
                   budget_reset_day, created_at, updated_at,
                   CASE WHEN api_key_encrypted IS NOT NULL AND api_key_encrypted != ''
                        THEN '****' || RIGHT(api_key_encrypted, 4) ELSE NULL END as key_hint
            FROM external_api_keys
            ORDER BY provider
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify({"success": True, "providers": [dict(r) for r in rows]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@bridge_bp.route("/api/external-providers", methods=["POST"])
@login_required
def upsert_external_provider():
    """Add or update an external AI provider API key."""
    data = request.get_json() or {}
    provider = data.get("provider", "").strip().lower()
    api_key = data.get("api_key", "").strip()

    if provider not in ("openai", "perplexity", "xai"):
        return jsonify({"success": False, "error": f"Unknown provider: {provider}"}), 400
    if not api_key:
        return jsonify({"success": False, "error": "API key required"}), 400

    budget = data.get("monthly_budget_usd", 10.0)
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            INSERT INTO external_api_keys (provider, api_key_encrypted, monthly_budget_usd, is_active)
            VALUES (%s, %s, %s, TRUE)
            ON CONFLICT (provider) DO UPDATE SET
                api_key_encrypted = %s, monthly_budget_usd = %s, is_active = TRUE, updated_at = NOW()
            RETURNING id, provider, is_active, monthly_budget_usd
        """, (provider, api_key, budget, api_key, budget))
        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"success": True, "provider": dict(row)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@bridge_bp.route("/api/external-providers/<provider>/toggle", methods=["POST"])
@login_required
def toggle_external_provider(provider):
    """Enable/disable an external provider."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "UPDATE external_api_keys SET is_active = NOT is_active, updated_at = NOW() WHERE provider = %s",
            (provider,),
        )
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
```

**Step 2: Restart and verify no errors**

Run: `docker compose restart archie_platform && sleep 5 && docker logs archie_platform --tail 10 2>&1 | grep -i error`
Expected: No errors

**Step 3: Commit**

```bash
git add platform_v2/tools/bridge/routes.py
git commit -m "feat(bridge): external provider key management API endpoints"
```

---

### Task 11: Verify Phase 2 End-to-End

**Step 1: Verify all new tiers in DB**

Run: `docker exec archie_database psql -U archie -d archie -c "SELECT tier_name, provider, model_name, is_active FROM model_tier_configs ORDER BY tier_name;"`
Expected: openai, perplexity, grok rows present

**Step 2: Verify external_providers import chain**

Run: `docker exec archie_platform python3 -c "from bridge_dispatcher import get_dispatcher; d = get_dispatcher(); from external_providers import PROVIDER_CONFIGS; print('Providers:', list(PROVIDER_CONFIGS.keys())); print('Dispatch OK')"`
Expected: `Providers: ['openai', 'perplexity', 'xai']` and `Dispatch OK`

**Step 3: Verify cost tracking view**

Run: `docker exec archie_database psql -U archie -d archie -c "SELECT * FROM v_external_cost_summary LIMIT 5;"`
Expected: Empty result (no external calls yet) but no error

**Step 4: Commit phase tag**

```bash
git add -A
git commit -m "feat(bridge): Phase 2 complete — external AI contractors with cost tracking"
```

---

## Phase 3: Telegram Approval Flow + Bridge Learning

### Task 12: Telegram Escalation Callbacks

**Files:**
- Modify: `ai_bridge/telegram_gateway.py:104-115` (handler registration)
- Modify: `ai_bridge/telegram_gateway.py:435-454` (_callback_handler)

**Step 1: Add escalation callback handler**

In `telegram_gateway.py`, register a new callback handler for escalation patterns. In `_run_bot` (line ~104), add before the generic callback handler (line 115):

```python
app.add_handler(
    CallbackQueryHandler(self._escalation_callback, pattern=r"^esc_")
)
```

**Step 2: Add _escalation_callback method**

After `_callback_handler` (line ~454), add:

```python
async def _escalation_callback(self, update, context):
    """Handle escalation approval/denial/defer buttons."""
    query = update.callback_query
    await query.answer()

    tg_user = query.from_user
    user_info = self._get_authorized_user(tg_user.id)
    if not user_info:
        await query.edit_message_text("Unauthorized.")
        return

    data = query.data  # e.g. "esc_approve_47" or "esc_deny_47" or "esc_defer_47"
    parts = data.split("_", 2)
    if len(parts) < 3:
        await query.edit_message_text("Invalid escalation action")
        return

    action = parts[1]  # approve, deny, defer
    try:
        approval_id = int(parts[2])
    except ValueError:
        await query.edit_message_text("Invalid escalation ID")
        return

    try:
        from database import get_db
        from psycopg2.extras import RealDictCursor
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        if action == "approve":
            cur.execute("""
                UPDATE autonomy_approval_queue
                SET status = 'approved', approved_by = %s, approved_at = NOW(), updated_at = NOW()
                WHERE id = %s AND status = 'pending'
                RETURNING action_data
            """, (user_info["user_id"], approval_id))
            row = cur.fetchone()
            conn.commit()
            if row:
                action_data = row["action_data"] if isinstance(row["action_data"], dict) else json.loads(row["action_data"])
                await query.edit_message_text(
                    f"Approved escalation #{approval_id}\n"
                    f"Model: {action_data.get('escalated_model', '?')}\n"
                    f"Will execute on next dispatch cycle."
                )
            else:
                await query.edit_message_text(f"Escalation #{approval_id} not found or already processed.")

        elif action == "deny":
            cur.execute("""
                UPDATE autonomy_approval_queue
                SET status = 'rejected', approved_by = %s,
                    rejected_reason = 'Denied via Telegram', updated_at = NOW()
                WHERE id = %s AND status = 'pending'
            """, (user_info["user_id"], approval_id))
            conn.commit()
            await query.edit_message_text(f"Denied escalation #{approval_id}")

        elif action == "defer":
            cur.execute("""
                UPDATE autonomy_approval_queue
                SET expires_at = NOW() + INTERVAL '1 hour', updated_at = NOW()
                WHERE id = %s AND status = 'pending'
            """, (approval_id,))
            conn.commit()
            await query.edit_message_text(f"Deferred escalation #{approval_id} for 1 hour")

        cur.close()
        conn.close()

    except Exception as e:
        logger.error(f"Escalation callback error: {e}")
        await query.edit_message_text(f"Error processing escalation: {e}")
```

**Step 3: Add escalation notification method**

Add a method to send escalation requests via Telegram:

```python
def send_escalation_notification(self, approval_id: int, context: dict):
    """Send escalation approval request to linked Telegram users."""
    if not self._running or not self._loop:
        return

    text = (
        f"Escalation Request #{approval_id}\n"
        f"Agent: {context.get('agent_name', '?')} ({context.get('station', '?')})\n"
        f"Capability: {context.get('capability', '?')}\n"
        f"Failed {context.get('failure_count', '?')}x on: {context.get('original_model', '?')}\n"
        f"Next tier: {context.get('escalated_model', '?')} (~${context.get('est_cost', 0):.4f})\n"
        f"Module: {context.get('module_id', '?')}\n\n"
        f"ARCHIE recommends: {context.get('recommendation', 'Approve')}"
    )

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Approve", callback_data=f"esc_approve_{approval_id}"),
            InlineKeyboardButton("Deny", callback_data=f"esc_deny_{approval_id}"),
            InlineKeyboardButton("Defer 1hr", callback_data=f"esc_defer_{approval_id}"),
        ]
    ])

    async def _send():
        try:
            from database import get_db
            conn = get_db()
            cur = conn.cursor()
            cur.execute("SELECT telegram_user_id FROM telegram_linked_accounts WHERE is_active = TRUE")
            rows = cur.fetchall()
            cur.close()
            conn.close()

            for row in rows:
                try:
                    await self._application.bot.send_message(
                        chat_id=row[0], text=text, reply_markup=keyboard
                    )
                except Exception as e:
                    logger.warning(f"Failed to notify {row[0]}: {e}")
        except Exception as e:
            logger.error(f"Escalation notification failed: {e}")

    asyncio.run_coroutine_threadsafe(_send(), self._loop)
```

**Step 4: Verify import and handler registration**

Run: `docker exec archie_platform python3 -c "from telegram_gateway import TelegramGateway; print('OK')"`
Expected: `OK`

**Step 5: Commit**

```bash
git add ai_bridge/telegram_gateway.py
git commit -m "feat(bridge): Telegram escalation approval flow — approve/deny/defer"
```

---

### Task 13: Bridge Learning Module

**Files:**
- Create: `ai_bridge/bridge_learning.py`

**Step 1: Write the bridge learning module**

```python
"""
Bridge Learning — Capture knowledge from external AI successes.

When an external AI provider succeeds where local agents failed,
this module extracts what the local agent missed and stores it
as knowledge_base entries for future context injection.
"""

import json
import logging
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)


def capture_learning(
    failed_result: dict,
    success_result: dict,
    capability: str,
    agent_name: str,
    module_id: str,
    failure_count: int = 3,
):
    """
    Compare failed local result with successful external result.
    Extract what the local agent missed and store as knowledge card.
    """
    try:
        from bridge_dispatcher import get_dispatcher

        dispatcher = get_dispatcher()

        # Use local model to analyze the difference
        failed_text = (failed_result.get('response', '') or failed_result.get('error', 'No response'))[:500]
        success_text = success_result.get('response', '')[:1000]
        prompt = (
            f"Compare these two AI responses for a '{capability}' task.\n\n"
            f"FAILED RESPONSE (local agent):\n{failed_text}\n\n"
            f"SUCCESSFUL RESPONSE (external AI):\n{success_text}\n\n"
            f"What key insight or pattern did the external AI use that the local agent missed?\n"
            f"Respond in 2-3 sentences focusing on the actionable learning."
        )

        analysis = dispatcher.request_work(
            capability="summarize",
            prompt=prompt,
            module_id="bridge_learning",
            timeout=60,
        )

        if not analysis.success:
            logger.warning("[BridgeLearning] Analysis failed, storing raw comparison")
            learning_content = (
                f"External AI ({success_result.get('model', '?')}) succeeded where "
                f"{agent_name} failed on {capability}. Review the successful approach."
            )
        else:
            learning_content = analysis.response

        # Store as knowledge_base entry
        title = f"{agent_name} learning: {capability} -- {module_id}"
        tags = ["agent-learning", agent_name, capability, module_id]
        importance = min(0.9, 0.5 + (failure_count * 0.1))

        ai_analysis = {
            "agent_name": agent_name,
            "capability": capability,
            "failure_count": failure_count,
            "external_model": success_result.get("model", "unknown"),
            "external_provider": success_result.get("provider", "unknown"),
            "learning_type": "pattern_recognition",
            "module_id": module_id,
        }

        from database import get_db
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO knowledge_base (title, content, source_type, tags, importance_score, ai_analysis)
            VALUES (%s, %s, 'agent_learning', %s, %s, %s)
            ON CONFLICT ON CONSTRAINT idx_kb_title_unique DO UPDATE SET
                content = EXCLUDED.content, importance_score = EXCLUDED.importance_score,
                ai_analysis = EXCLUDED.ai_analysis, updated_at = NOW()
        """, (title, learning_content, tags, importance, json.dumps(ai_analysis)))
        conn.commit()
        cur.close()
        conn.close()

        logger.info(f"[BridgeLearning] Captured learning: {title}")

    except Exception as e:
        logger.warning(f"[BridgeLearning] capture_learning failed: {e}")


def inject_learnings(agent_name: str, capability: str, prompt: str, max_cards: int = 3) -> str:
    """
    Search knowledge_base for relevant learning cards and prepend to prompt.

    Returns the enhanced prompt with learning context prepended,
    or the original prompt if no learnings found.
    """
    try:
        from database import get_db
        from psycopg2.extras import RealDictCursor

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("""
            SELECT title, content, importance_score
            FROM knowledge_base
            WHERE source_type = 'agent_learning'
              AND %s = ANY(tags) AND %s = ANY(tags)
              AND is_archived = FALSE
            ORDER BY importance_score DESC, updated_at DESC
            LIMIT %s
        """, (agent_name, capability, max_cards))

        cards = cur.fetchall()
        cur.close()
        conn.close()

        if not cards:
            return prompt

        learning_context = "--- LEARNING CONTEXT (from previous escalations) ---\n"
        for card in cards:
            learning_context += f"- {card['content']}\n"
        learning_context += "--- END LEARNING CONTEXT ---\n\n"

        return learning_context + prompt

    except Exception as e:
        logger.debug(f"[BridgeLearning] inject_learnings failed: {e}")
        return prompt
```

**Step 2: Wire learning into BridgeDispatcher**

In `bridge_dispatcher.py`, in `request_work` -- after selecting the agent (step 2) and before executing (step 4), add learning injection:

```python
        # 3b. Inject learnings if available
        try:
            from bridge_learning import inject_learnings
            prompt = inject_learnings(agent_name, capability, prompt)
        except ImportError:
            pass
```

Also wire `capture_learning` into the escalation success path (in the auto-escalate block):

```python
                    if escalated_result.get("success"):
                        # ... existing reset + log code ...
                        try:
                            from bridge_learning import capture_learning
                            capture_learning(
                                failed_result=llm_result,
                                success_result=escalated_result,
                                capability=capability,
                                agent_name=agent_name,
                                module_id=module_id,
                                failure_count=failure_count,
                            )
                        except ImportError:
                            pass
```

**Step 3: Verify imports**

Run: `docker exec archie_platform python3 -c "from bridge_learning import capture_learning, inject_learnings; print('OK')"`
Expected: `OK`

**Step 4: Commit**

```bash
git add ai_bridge/bridge_learning.py ai_bridge/bridge_dispatcher.py
git commit -m "feat(bridge): bridge learning — capture + inject knowledge from escalations"
```

---

### Task 14: Verify Phase 3 End-to-End

**Step 1: Restart and verify**

Run: `docker compose restart archie_platform && sleep 8 && docker logs archie_platform --tail 20 2>&1 | grep -iE "error|bridge|telegram|learning"`
Expected: No errors

**Step 2: Verify Telegram handler count**

Run: `docker exec archie_platform python3 -c "from telegram_gateway import TelegramGateway; g = TelegramGateway.__new__(TelegramGateway); print('Escalation callback exists:', hasattr(g, '_escalation_callback'))"`
Expected: `Escalation callback exists: True`

**Step 3: Verify learning module**

Run: `docker exec archie_platform python3 -c "from bridge_learning import inject_learnings; p = inject_learnings('CodeSmith', 'code_review', 'Review this code'); print('Prompt length:', len(p), '(should be >= original)'); print('OK')"`
Expected: Prompt length printed, OK

**Step 4: Commit phase tag**

```bash
git add -A
git commit -m "feat(bridge): Phase 3 complete — Telegram approval flow + bridge learning"
```

---

## Phase 4: Agent Naming + Dashboard Display

### Task 15: Migration 107 — Agent Names

**Files:**
- Create: `database/migrations/107_agent_names.sql`

**Step 1: Write the naming migration**

```sql
-- Migration 107: Agent Identity — Diverse Names
-- Hand-curated first/last names for team member agents

-- Add name columns if not present
ALTER TABLE agents ADD COLUMN IF NOT EXISTS first_name VARCHAR(50);
ALTER TABLE agents ADD COLUMN IF NOT EXISTS last_name VARCHAR(50);
ALTER TABLE agents ADD COLUMN IF NOT EXISTS display_name VARCHAR(100);

-- Assign names to existing agents (update by codename)
UPDATE agents SET first_name = 'Sentinel', last_name = '', display_name = 'Sentinel'
    WHERE name = 'Sentinel' AND first_name IS NULL;
UPDATE agents SET first_name = 'Aria', last_name = 'Chen', display_name = 'Aria Chen'
    WHERE name = 'Code-Architect' AND first_name IS NULL;
UPDATE agents SET first_name = 'Marcus', last_name = 'Rivera', display_name = 'Marcus Rivera'
    WHERE name = 'Code-Reviewer' AND first_name IS NULL;
UPDATE agents SET first_name = 'Priya', last_name = 'Sharma', display_name = 'Priya Sharma'
    WHERE name = 'Test-Runner' AND first_name IS NULL;
UPDATE agents SET first_name = 'Kenji', last_name = 'Tanaka', display_name = 'Kenji Tanaka'
    WHERE name = 'Debug-Specialist' AND first_name IS NULL;
UPDATE agents SET first_name = 'Amara', last_name = 'Osei', display_name = 'Amara Osei'
    WHERE name = 'Data-Analyst' AND first_name IS NULL;
UPDATE agents SET first_name = 'Liam', last_name = 'O''Brien', display_name = 'Liam O''Brien'
    WHERE name = 'Sys-Admin' AND first_name IS NULL;
UPDATE agents SET first_name = 'Sofia', last_name = 'Petrov', display_name = 'Sofia Petrov'
    WHERE name = 'Knowledge-Miner' AND first_name IS NULL;
UPDATE agents SET first_name = 'Dante', last_name = 'Morales', display_name = 'Dante Morales'
    WHERE name = 'Content-Writer' AND first_name IS NULL;
UPDATE agents SET first_name = 'Yuki', last_name = 'Sato', display_name = 'Yuki Sato'
    WHERE name = 'Threat-Scanner' AND first_name IS NULL;
UPDATE agents SET first_name = 'Nia', last_name = 'Williams', display_name = 'Nia Williams'
    WHERE name = 'Email-Handler' AND first_name IS NULL;
UPDATE agents SET first_name = 'Omar', last_name = 'Hassan', display_name = 'Omar Hassan'
    WHERE name = 'Health-Monitor' AND first_name IS NULL;
UPDATE agents SET first_name = 'Elena', last_name = 'Volkov', display_name = 'Elena Volkov'
    WHERE name = 'Report-Builder' AND first_name IS NULL;
UPDATE agents SET first_name = 'Tariq', last_name = 'Mansour', display_name = 'Tariq Mansour'
    WHERE name = 'API-Builder' AND first_name IS NULL;
UPDATE agents SET first_name = 'Ingrid', last_name = 'Larsson', display_name = 'Ingrid Larsson'
    WHERE name = 'Doc-Analyzer' AND first_name IS NULL;
UPDATE agents SET first_name = 'Jin', last_name = 'Park', display_name = 'Jin Park'
    WHERE name = 'Anomaly-Detector' AND first_name IS NULL;
UPDATE agents SET first_name = 'Zara', last_name = 'Mbeki', display_name = 'Zara Mbeki'
    WHERE name = 'Wellness-Monitor' AND first_name IS NULL;
UPDATE agents SET first_name = 'Rafael', last_name = 'Santos', display_name = 'Rafael Santos'
    WHERE name = 'Schema-Designer' AND first_name IS NULL;
UPDATE agents SET first_name = 'Mai', last_name = 'Nguyen', display_name = 'Mai Nguyen'
    WHERE name = 'Compliance-Checker' AND first_name IS NULL;
UPDATE agents SET first_name = 'Kofi', last_name = 'Asante', display_name = 'Kofi Asante'
    WHERE name = 'Deploy-Engineer' AND first_name IS NULL;

-- For any remaining unnamed agents, set display_name = name
UPDATE agents SET display_name = name WHERE display_name IS NULL;
```

**Step 2: Run the migration**

Run: `docker exec -i archie_database psql -U archie -d archie < database/migrations/107_agent_names.sql`
Expected: ALTER TABLE and UPDATE messages

**Step 3: Verify names assigned**

Run: `docker exec archie_database psql -U archie -d archie -c "SELECT name, first_name, last_name, display_name FROM agents WHERE first_name IS NOT NULL AND first_name != '' ORDER BY id LIMIT 25;"`
Expected: Named agents with diverse first/last names

**Step 4: Commit**

```bash
git add database/migrations/107_agent_names.sql
git commit -m "feat(bridge): migration 107 — diverse agent names"
```

---

### Task 16: Dashboard Agent Badge API

**Files:**
- Modify: `platform_v2/tools/bridge/routes.py` (add module-agent mapping endpoint)

**Step 1: Add the dashboard agent API**

```python
@bridge_bp.route("/api/dashboard/module-agents", methods=["GET"])
@login_required
def get_module_agents():
    """Get assigned agent info for all active modules (for dashboard badges)."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT
                bs.station_code,
                UNNEST(bs.modules) as module_id,
                a.name as agent_codename,
                a.first_name,
                a.display_name,
                a.model,
                a.status as agent_status
            FROM bridge_stations bs
            JOIN station_assignments sa ON sa.station_id = bs.id AND sa.is_active = TRUE
            JOIN agents a ON a.id = sa.agent_id AND a.status = 'active'
            WHERE bs.is_active = TRUE
            ORDER BY bs.station_code
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()

        module_agents = {}
        for row in rows:
            mid = row["module_id"]
            if mid not in module_agents:
                module_agents[mid] = {
                    "agent_codename": row["agent_codename"],
                    "first_name": row["first_name"] or row["agent_codename"],
                    "display_name": row["display_name"] or row["agent_codename"],
                    "station_code": row["station_code"],
                    "status": row["agent_status"],
                }

        return jsonify({"success": True, "module_agents": module_agents})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
```

**Step 2: Verify endpoint**

Run: `docker compose restart archie_platform && sleep 5 && docker logs archie_platform --tail 5 2>&1 | grep -i error`
Expected: No errors

**Step 3: Commit**

```bash
git add platform_v2/tools/bridge/routes.py
git commit -m "feat(bridge): dashboard module-agents API for agent badges"
```

---

### Task 17: Dashboard Agent Badge UI

**Files:**
- Create: `platform_v2/static/css/agent-badge.css`
- Create: `platform_v2/static/js/agent-badge.js`
- Modify: `platform_v2/templates/dashboard_dynamic.html` (link CSS/JS + badge container)

**Step 1: Create agent-badge.css**

```css
/* Agent Badge — shown on module cards in dashboard grid */
.agent-badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 10px;
    font-family: 'IBM Plex Mono', monospace;
    background: rgba(255, 215, 0, 0.08);
    border: 1px solid rgba(255, 215, 0, 0.2);
    color: #aaa;
    white-space: nowrap;
    margin-top: 4px;
}

.agent-badge .status-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    display: inline-block;
    flex-shrink: 0;
}

.agent-badge .status-dot.active { background: #00ff41; box-shadow: 0 0 4px #00ff41; }
.agent-badge .status-dot.working { background: #FFAA00; box-shadow: 0 0 4px #FFAA00; }
.agent-badge .status-dot.resting { background: #8B5CF6; }
.agent-badge .status-dot.offline { background: #555; }

.agent-badge .agent-name {
    color: #c9d1d9;
    font-weight: 500;
}

.agent-badge .agent-codename {
    color: #6e7681;
    font-size: 9px;
}
```

**Step 2: Create agent-badge.js**

Use safe DOM methods (textContent, createElement) instead of innerHTML:

```javascript
/**
 * Agent Badge System — Fetches and displays agent assignments on module cards.
 * Polls every 30s for updates.
 */
(function() {
    let moduleAgents = {};

    async function fetchModuleAgents() {
        try {
            const res = await fetch('/tools/bridge/api/dashboard/module-agents');
            const data = await res.json();
            if (data.success) {
                moduleAgents = data.module_agents;
                renderBadges();
            }
        } catch (e) {
            console.debug('Agent badge fetch failed:', e);
        }
    }

    function renderBadges() {
        document.querySelectorAll('[data-module-id]').forEach(function(card) {
            const moduleId = card.dataset.moduleId;
            const agent = moduleAgents[moduleId];

            // Remove existing badge
            const existing = card.querySelector('.agent-badge');
            if (existing) existing.remove();

            if (!agent) return;

            var statusClass = agent.status === 'active' ? 'active' :
                              agent.status === 'working' ? 'working' :
                              agent.status === 'resting' ? 'resting' : 'offline';

            var badge = document.createElement('div');
            badge.className = 'agent-badge';

            var dot = document.createElement('span');
            dot.className = 'status-dot ' + statusClass;
            badge.appendChild(dot);

            var nameSpan = document.createElement('span');
            nameSpan.className = 'agent-name';
            nameSpan.textContent = agent.first_name || agent.agent_codename;
            badge.appendChild(nameSpan);

            var codeSpan = document.createElement('span');
            codeSpan.className = 'agent-codename';
            codeSpan.textContent = '(' + agent.agent_codename + ')';
            badge.appendChild(codeSpan);

            // Insert at top of card content
            var cardBody = card.querySelector('.module-card-body, .card-content, .module-info');
            if (cardBody) {
                cardBody.insertBefore(badge, cardBody.firstChild);
            } else if (card.children.length > 1) {
                card.insertBefore(badge, card.children[1]);
            } else {
                card.appendChild(badge);
            }
        });
    }

    // Initial fetch + polling
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', fetchModuleAgents);
    } else {
        fetchModuleAgents();
    }
    setInterval(fetchModuleAgents, 30000);
})();
```

**Step 3: Link CSS/JS in dashboard template**

In `platform_v2/templates/dashboard_dynamic.html`, add in the `<head>` or extra_head block:

```html
<link rel="stylesheet" href="{{ url_for('static', filename='css/agent-badge.css') }}">
```

And before `</body>` or in extra_scripts block:

```html
<script src="{{ url_for('static', filename='js/agent-badge.js') }}"></script>
```

**Step 4: Add data-module-id attributes to module cards**

In the dashboard template, find where module cards are rendered and ensure each card has `data-module-id="{{ module.id }}"` attribute. This is likely in a Jinja loop. Add the attribute to the card's root element.

**Step 5: Verify files created and template valid**

Run: `ls -la /mnt/archie_brain/platform_v2/static/css/agent-badge.css /mnt/archie_brain/platform_v2/static/js/agent-badge.js`
Expected: Both files exist

Run: `docker exec archie_platform python3 -c "from jinja2 import Environment, FileSystemLoader; e=Environment(loader=FileSystemLoader('/app/templates')); t=e.get_template('dashboard_dynamic.html'); print('Template OK')"`
Expected: `Template OK`

**Step 6: Commit**

```bash
git add platform_v2/static/css/agent-badge.css platform_v2/static/js/agent-badge.js platform_v2/templates/dashboard_dynamic.html
git commit -m "feat(bridge): dashboard agent badges — CSS + JS + template integration"
```

---

### Task 18: Verify Phase 4 End-to-End

**Step 1: Restart and check for errors**

Run: `docker compose restart archie_platform && sleep 8 && docker logs archie_platform --tail 20 2>&1 | grep -iE "error|badge|agent"`
Expected: No errors

**Step 2: Verify agent names in DB**

Run: `docker exec archie_database psql -U archie -d archie -c "SELECT id, name, first_name, display_name, model, status FROM agents WHERE status='active' ORDER BY id LIMIT 20;"`
Expected: Named agents with diverse names

**Step 3: Verify module-agents API**

Run: `docker exec archie_platform python3 -c "
from bridge_dispatcher import get_dispatcher
d = get_dispatcher()
status = d.get_dispatch_status()
print('Agents:', status['total_agents'], 'Stations:', status['total_stations'])
print('OK')
"`
Expected: Agent and station counts, OK

**Step 4: Final commit**

```bash
git add -A
git commit -m "feat(bridge): Phase 4 complete — agent naming + dashboard display

Bridge Enhancements — all 4 phases:
- Phase 1: Routing mode toggle (local_only/local_cloud/full) + escalation process
- Phase 2: External AI contractors (OpenAI/Perplexity/Grok) + cost tracking
- Phase 3: Telegram approval flow + bridge learning capture/injection
- Phase 4: Agent naming (diverse) + dashboard agent badges"
```

---

## Post-Implementation Checklist

After all 4 phases are complete, verify:

1. **Migration 105** -- platform_settings + dispatch_escalation_log tables exist
2. **Migration 106** -- external_api_keys table + new model_tier_configs rows
3. **Migration 107** -- agents table has first_name/last_name/display_name columns
4. **SmartRouter** -- TIER_ORDER includes openai/perplexity/grok between cloud and Claude
5. **BridgeDispatcher** -- failure tracking, escalation, learning injection all wired
6. **External providers** -- call_openai/call_perplexity/call_grok importable
7. **Bridge learning** -- capture_learning + inject_learnings importable
8. **Telegram** -- esc_approve/deny/defer callback handler registered
9. **Bridge UI** -- routing mode toggle renders, responds to clicks
10. **Dashboard** -- agent badges visible on module cards with names + status dots
11. **No import errors** -- `docker logs archie_platform --tail 50 2>&1 | grep -i "error\|traceback"` clean
12. **Dev HQ updated** -- project created, tasks completed, decisions logged
