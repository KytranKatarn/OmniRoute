# Media Studio - Local-First Image Generation Plan

**Date:** January 20, 2026
**Status:** PLANNING
**Priority:** HIGH - Aligns with A.R.C.H.I.E.'s local-first philosophy

---

## Current State

| Feature | Status | Provider |
|---------|--------|----------|
| Image Generation | ⚠️ Partial | DALL-E 3 only (paid) |
| Video Generation | ❌ Placeholder | None |
| Shorts Creation | ❌ Placeholder | None |

**Problem:** Currently only uses paid DALL-E 3 API, no local option.

---

## Proposed Architecture: Local-First with Contractor Fallback

```
User Request → Media Studio API
                    ↓
            ┌───────────────┐
            │ Smart Router  │
            └───────┬───────┘
                    ↓
    ┌───────────────┼───────────────┐
    ↓               ↓               ↓
┌───────┐     ┌───────────┐   ┌──────────┐
│ LOCAL │     │ LOCAL ALT │   │CONTRACTOR│
│ (Free)│     │  (Free)   │   │  (Paid)  │
└───────┘     └───────────┘   └──────────┘
ComfyUI/      Fooocus/        DALL-E 3/
Automatic1111 Ollama+SD       Midjourney

Priority: 1 (try first) → 2 (fallback) → 3 (last resort)
```

---

## Option 1: ComfyUI (Recommended)

**Pros:**
- Most flexible/powerful
- Node-based workflow
- Great for consistent avatar generation
- Can save workflows for repeatable results
- Supports SDXL, SD 1.5, Flux

**Cons:**
- More complex to set up
- Higher VRAM requirements

**Docker Setup:**
```yaml
# Add to docker-compose.yml
comfyui:
  image: ghcr.io/ai-dock/comfyui:latest
  container_name: archie_comfyui
  ports:
    - "8188:8188"
  volumes:
    - ./comfyui/models:/opt/ComfyUI/models
    - ./comfyui/output:/opt/ComfyUI/output
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            count: 1
            capabilities: [gpu]
  restart: unless-stopped
```

**Integration:**
```python
# archie_bridge.py addition
def generate_image_local(prompt, workflow='avatar', ...):
    """Generate via local ComfyUI"""
    response = requests.post(
        'http://archie_comfyui:8188/prompt',
        json={'prompt': workflow_with_prompt}
    )
```

---

## Option 2: Fooocus (Simpler Alternative)

**Pros:**
- One-click setup
- Good defaults (no tuning needed)
- Lower learning curve
- Optimized for portraits/people

**Cons:**
- Less flexible than ComfyUI
- Fewer advanced options

**Docker Setup:**
```yaml
fooocus:
  image: ghcr.io/lllyasviel/fooocus:main
  container_name: archie_fooocus
  ports:
    - "7865:7865"
  volumes:
    - ./fooocus/outputs:/app/outputs
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            count: 1
            capabilities: [gpu]
```

---

## Option 3: Ollama + Image Models (Future)

Ollama is adding image generation support. When available:
- Would integrate seamlessly with existing Ollama setup
- Same "local-first" pattern as text generation
- Currently: LLaVA can describe images but not generate

---

## Implementation Plan

### Phase 1: Local ComfyUI Setup (1-2 hours)
1. Add ComfyUI to docker-compose.yml
2. Download SDXL model (~6GB)
3. Create avatar generation workflow
4. Test locally

### Phase 2: archie_bridge Integration (2-3 hours)
1. Add `generate_image_local()` function
2. Create smart router that tries:
   - ComfyUI first (free)
   - DALL-E fallback (if local fails or unavailable)
3. Log both local and API usage

### Phase 3: Media Studio API Update (1 hour)
1. Add provider selection: "auto", "local", "dalle"
2. Default to "auto" (local-first)
3. Show which provider was used in response

### Phase 4: Avatar Workflow (1 hour)
1. Create optimized ComfyUI workflow for corporate headshots
2. Save as reusable workflow
3. Test consistency across generations

---

## Smart Router Logic

```python
def generate_image_smart(prompt, prefer_local=True, ...):
    """Local-first image generation with contractor fallback"""

    if prefer_local:
        # Try local first
        local_result = generate_image_local(prompt, ...)
        if local_result['success']:
            return local_result

        print(f"Local generation failed: {local_result['error']}")
        print("Falling back to DALL-E contractor...")

    # Fallback to DALL-E (contractor)
    return generate_image_dalle(prompt, ...)
```

---

## Cost Comparison

| Provider | Cost per Image | Speed | Quality |
|----------|---------------|-------|---------|
| Local SDXL | $0.00 | 20-60s | High |
| Local SD 1.5 | $0.00 | 10-30s | Good |
| DALL-E 3 | $0.04-0.12 | 10-20s | Excellent |
| Midjourney | $0.01-0.04 | 30-60s | Excellent |

**At 100 avatars:**
- Local: $0
- DALL-E 3: $4-12

---

## Hardware Requirements

**Minimum (SD 1.5):**
- 8GB VRAM GPU (RTX 3060, RTX 4060)
- 16GB RAM
- 20GB disk space

**Recommended (SDXL):**
- 12GB+ VRAM GPU (RTX 3080, RTX 4070)
- 32GB RAM
- 50GB disk space

---

## Questions for User

1. **GPU Available?** Do you have an NVIDIA GPU with 8GB+ VRAM for local generation?
2. **Preferred Option?** ComfyUI (flexible) vs Fooocus (simple)?
3. **Fallback Behavior?** Always try local first, or let user choose?
4. **Avatar Style?** Corporate headshot, illustrated, or both options?

---

## Next Steps

- [ ] Confirm GPU availability
- [ ] Choose ComfyUI vs Fooocus
- [ ] Add to docker-compose.yml
- [ ] Download base model
- [ ] Create avatar workflow
- [ ] Integrate with archie_bridge
- [ ] Update Media Studio API
- [ ] Test end-to-end

---

**Note:** Until local is set up, DALL-E 3 remains available as contractor option.
