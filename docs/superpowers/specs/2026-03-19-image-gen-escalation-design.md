# Image Generation Escalation Chain — Design Spec

**Project**: #164 Image Generation Escalation Chain
**Date**: 2026-03-19
**Status**: Revised (post-review)

## Problem

Image generation currently only routes to hub ComfyUI (Quadro M4000). The fleet node KYTRAN-StarShip has an RTX 3070 with ComfyUI running but the dispatcher never routes image jobs there. Cloud providers exist but aren't wired into the escalation chain.

## Design

### 4-Tier Escalation Chain

```
Image request → Bridge dispatcher (_execute_comfyui)
  1. Fleet node ComfyUI (RTX 3070) → free, Tier 1 auto-approve
     → BUSY? ↓
  2. Hub ComfyUI (M4000) → free, Tier 1 auto-approve
     → BUSY? ↓
  3. Free cloud contractors (HuggingFace, Cloudflare) → free, Tier 1 auto-approve
     → ALL BUSY/FAILED? ↓
  4. Paid cloud contractors (DALL-E 3, Imagen 3) → paid, Tier 2 Telegram approval
     → DENIED → return error "all image generators busy"
```

### Cloud Contractors (registered in contractor_providers table)

| Provider | Tier | Cost | API | Image Quality |
|----------|------|------|-----|---------------|
| HuggingFace Inference | 1 (free) | $0 (rate-limited) | REST | SDXL/Flux |
| Cloudflare Workers AI | 1 (free) | $0 (10K/day) | REST | SDXL |
| OpenAI DALL-E 3 | 2 (paid) | $0.04-0.12/img | REST | Excellent |
| Google Imagen 3 | 2 (paid) | $0.02-0.06/img | REST | Excellent |

Contractors are managed in the Starbase Command → Crew tab. Each has an API key, tier, and enabled status. The escalation iterates through enabled contractors by tier.

### Busy Detection

Query `bridge_jobs.metadata` JSONB for running image_generation jobs:

```sql
SELECT COUNT(*) FROM bridge_jobs
WHERE job_type = 'image_generation'
  AND status = 'running'
  AND metadata->>'target_host' = %s
```

Note: `bridge_jobs` has no `target_host` column. We store it in the existing `metadata` JSONB field (already has a GIN index). Hub jobs use `metadata->>'target_host' = 'hub'`.

### Async Cloud Approval (Tier 2)

Tier 2 approval via Telegram is **asynchronous** — `request_approval()` from `agent_loop.py` returns a queue ID immediately, not a result. The flow is two-phase:

**Phase 1**: All local + free cloud hosts busy → create `bridge_job` with `status = 'pending_approval'` → call `request_approval()` → return immediately with "pending" result.

**Phase 2**: Telegram callback fires → approval handler picks up pending job → calls `generate_media()` → updates job status to completed/failed.

```python
# Phase 1 (in _escalate_image_to_cloud):
from agent_loop import request_approval
job_id = self._create_bridge_job(
    job_type="image_generation", status="pending_approval",
    metadata={"prompt": prompt, "escalation": "cloud", "user_id": user_id}
)
approval_id = request_approval(
    action_type="cloud_throughput_escalation",
    action_data={"job_id": job_id, "prompt": prompt[:100]},
    reason="All local ComfyUI hosts busy — cloud image gen requested",
    tier=2,
)
return DispatchResult(...)  # pending status

# Phase 2 (in approval callback handler):
# When Telegram button pressed → retrieve job → call generate_media() → update job
```

### Files to Modify

#### 1. `ai_bridge/bridge_dispatcher.py` — `_execute_comfyui()` (~Line 1672)

Add escalation at the top of the existing method:

```python
def _execute_comfyui(self, agent_name, agent, image_model, prompt, context,
                     station_code, capability, module_id, user_id=None, job_id=None):
    # --- Escalation: find best available ComfyUI host ---
    comfyui_host, node_db_id = self._select_comfyui_host()

    if comfyui_host is None:
        # All local hosts busy → try free cloud, then paid cloud
        return self._escalate_image_to_cloud(
            agent_name, agent, prompt, context, station_code,
            capability, module_id, user_id, job_id
        )

    # Existing logic continues with comfyui_host and node_db_id...
    # Pass node_db_id to VRAM swap:
    ollama_models_unloaded = self._vram_swap_for_comfyui(node_db_id)
    # Pass comfyui_host to service:
    result = comfyui_service.generate_image(prompt, ..., host=comfyui_host)
    self._vram_restore_after_comfyui(ollama_models_unloaded, node_db_id)
```

#### 2. New method: `_select_comfyui_host()`

```python
def _select_comfyui_host(self):
    """
    Find the best available ComfyUI host.
    Returns (comfyui_url, node_db_id) or (None, None) if all busy.
    """
    # Check fleet nodes first (faster GPUs)
    from ai_bridge.node_router import select_best_image_node
    node_info = select_best_image_node("comfyui")

    if node_info:
        node_hostname = node_info.get("hostname") or node_info.get("vpn_ip")
        node_port = node_info.get("comfyui_port", 8188)
        node_db_id = node_info.get("id")
        if not self._is_image_host_busy(node_hostname):
            return f"http://{node_hostname}:{node_port}", node_db_id

    # Fall back to hub ComfyUI
    hub_host = os.getenv("COMFYUI_HOST", "http://archie_comfyui:8188")
    if not self._is_image_host_busy("hub"):
        return hub_host, None

    return None, None
```

Note: Uses `select_best_image_node()` directly (returns full node dict) instead of `get_comfyui_url()` (returns string node_id).

#### 3. New method: `_is_image_host_busy()`

```python
def _is_image_host_busy(self, target_host):
    """Check bridge_jobs metadata for running image_generation jobs on this host."""
    try:
        from ai_bridge.db import get_db
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM bridge_jobs
            WHERE job_type = 'image_generation'
              AND status = 'running'
              AND metadata->>'target_host' = %s
        """, (target_host,))
        count = cur.fetchone()[0]
        cur.close()
        conn.close()
        return count > 0
    except Exception:
        return False
```

#### 4. New method: `_escalate_image_to_cloud()`

```python
def _escalate_image_to_cloud(self, agent_name, agent, prompt, context,
                              station_code, capability, module_id,
                              user_id=None, job_id=None):
    """Try free cloud contractors (Tier 1), then paid (Tier 2 async approval)."""
    from ai_bridge.external_providers import generate_media

    # --- Tier 1: Free cloud contractors (auto-approve) ---
    free_providers = self._get_enabled_contractors(tier=1, capability="image_gen")
    for provider in free_providers:
        try:
            result = generate_media(provider["provider_key"], {
                "type": "image",
                "prompt": prompt,
                "params": context.get("image_params", {})
            })
            if result.get("success"):
                return self._build_dispatch_result(
                    success=True, agent_name=agent_name, agent=agent,
                    response=f"Image generated via {provider['name']}",
                    station_code=station_code, capability=capability,
                    metadata={"file_path": result["file_path"],
                              "provider": provider["provider_key"]}
                )
        except Exception as e:
            logger.warning("Free cloud provider %s failed: %s", provider["name"], e)

    # --- Tier 2: Paid cloud contractors (async Telegram approval) ---
    from agent_loop import request_approval

    # Create pending job
    pending_job_id = self._create_bridge_job(
        job_type="image_generation",
        agent_name=agent_name,
        status="pending_approval",
        station_code=station_code,
        metadata={
            "target_host": "cloud",
            "prompt": prompt,
            "escalation": "paid_cloud",
            "user_id": user_id,
            "image_params": context.get("image_params", {}),
        }
    )

    # Submit async approval
    request_approval(
        action_type="cloud_throughput_escalation",
        action_data={"job_id": pending_job_id, "prompt": prompt[:100]},
        reason="All local + free cloud image generators busy. Paid cloud requested.",
        tier=2,
    )

    return self._build_dispatch_result(
        success=False, agent_name=agent_name, agent=agent,
        response="Image generation queued — awaiting cloud approval via Telegram",
        station_code=station_code, capability=capability,
        metadata={"escalation": "pending_approval", "job_id": pending_job_id}
    )
```

#### 5. New method: `_get_enabled_contractors()`

```python
def _get_enabled_contractors(self, tier=1, capability="image_gen"):
    """Get enabled contractor providers from DB, filtered by tier and capability."""
    try:
        from ai_bridge.db import get_db
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT provider_key, name, api_key, tier, capabilities
            FROM contractor_providers
            WHERE is_enabled = true AND tier = %s
              AND capabilities ? %s
            ORDER BY priority ASC
        """, (tier, capability))
        providers = [dict(r) for r in cur.fetchall()]
        cur.close()
        conn.close()
        return providers
    except Exception:
        return []
```

#### 6. `ai_bridge/comfyui_service.py` — Accept custom host

Add `host` parameter to `generate_image()`:

```python
def generate_image(self, prompt, model=None, steps=20, width=1024, height=1024,
                   negative_prompt="", seed=-1, workflow_path=None, cfg=7.0,
                   sampler="euler", host=None):
    comfyui_host = host or self.comfyui_host
    # ... rest unchanged, use comfyui_host everywhere ...
```

#### 7. `ai_bridge/external_providers.py` — Add free provider adapters

Add HuggingFace and Cloudflare adapters:

```python
def _huggingface_image_adapter(request):
    """Generate image via HuggingFace Inference API (free tier)."""
    # POST to https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-xl-base-1.0
    # Headers: Authorization: Bearer {HF_TOKEN}
    # Body: {"inputs": prompt}
    # Returns: image bytes

def _cloudflare_image_adapter(request):
    """Generate image via Cloudflare Workers AI (free tier)."""
    # POST to https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/@cf/stabilityai/stable-diffusion-xl-base-1.0
    # Headers: Authorization: Bearer {CF_TOKEN}
    # Body: {"prompt": prompt}
    # Returns: image bytes
```

Register in adapter map:
```python
MEDIA_ADAPTERS = {
    "openai": _openai_image_adapter,
    "gemini": _gemini_image_adapter,
    "huggingface": _huggingface_image_adapter,
    "cloudflare": _cloudflare_image_adapter,
}
```

#### 8. `bridge_jobs` metadata — Store target_host

When creating image generation jobs, always include `target_host` in metadata:

```python
metadata = {
    "target_host": node_hostname or "hub",
    "comfyui_host": comfyui_url,
    ...
}
```

#### 9. Approval callback handler

In `agent_loop.py`, when a Tier 2 image gen approval fires:

```python
def _handle_image_approval(approval_id, job_id):
    """Called when Telegram approval is granted for paid cloud image gen."""
    # Retrieve pending job from bridge_jobs
    # Get prompt + params from job metadata
    # Iterate paid providers: ["openai", "gemini"]
    # Call generate_media() for each until success
    # Update bridge_job status to completed/failed
```

### What NOT to Change

- **node_router.py** — `select_best_image_node()` works as-is
- **Telegram approval system** — Tier 2 mechanism works as-is
- **Media Studio UI** — triggers through Bridge dispatch, no changes needed
- **Starbase jobs panel** — already shows bridge_jobs, will show queue automatically
- **Starbase crew tab** — already manages contractor_providers

### Contractor Setup (Crew Tab)

Register these in `contractor_providers` table via Starbase Crew tab:

```sql
INSERT INTO contractor_providers (provider_key, name, tier, capabilities, is_enabled, priority)
VALUES
  ('huggingface', 'HuggingFace Inference API', 1, '["image_gen"]'::jsonb, true, 1),
  ('cloudflare', 'Cloudflare Workers AI', 1, '["image_gen"]'::jsonb, true, 2),
  ('openai', 'OpenAI DALL-E 3', 2, '["image_gen"]'::jsonb, true, 1),
  ('gemini', 'Google Imagen 3', 2, '["image_gen"]'::jsonb, true, 2);
```

API keys stored in contractor_providers or .env.

### Error Handling

| Scenario | Behavior |
|----------|----------|
| Node ComfyUI down | `select_best_image_node()` returns None, skip to hub |
| Hub ComfyUI down | Service call fails, skip to free cloud |
| Free cloud rate-limited | Try next free provider, then escalate to paid |
| Both local busy | Try free cloud first (Tier 1 auto) |
| All free fail | Tier 2 Telegram approval for paid cloud |
| Paid approval denied | Return error: "All image generators busy" |
| No API keys configured | Skip that provider, try next |

### Testing Plan

1. **Node path**: Generate agent profile picture → routes to node RTX 3070
2. **Hub fallback**: Occupy node with a generation, trigger another → falls back to hub M4000
3. **Free cloud**: Occupy both local hosts, trigger another → auto-routes to HuggingFace/Cloudflare
4. **Paid cloud**: All free fail, trigger → Telegram approval sent → approve → DALL-E generates
5. **Media Studio**: Use Media Studio UI → same escalation chain via Bridge dispatch
6. **Queue visibility**: Check Starbase jobs panel shows all active image gen jobs with target_host
