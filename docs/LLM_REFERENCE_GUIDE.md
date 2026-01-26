# A.R.C.H.I.E. LLM Reference Guide

**Last Updated:** January 20, 2026
**Total Models:** 21 Local LLMs + 2 Vision Models + 1 Image Generator + 7 External

---

## Local Ollama Models (21 models)

All internal staff agents use local Ollama LLMs for cost-free, low-latency, private processing.

### Code & Engineering Models

| Model | Size | VRAM | Best For | Agents Using |
|-------|------|------|----------|--------------|
| **deepseek-coder-v2:16b** | 8.9 GB | 10GB | Complex code generation, engineering tasks | 13 agents |
| **deepseek-coder:33b** | 18 GB | 20GB | Very complex code, architecture, security analysis | 3 agents |
| **codellama:latest** | 3.8 GB | 5GB | Quick code generation, simple tasks | Available |
| **starcoder2:7b** | 4.0 GB | 5GB | IDE-style code completion, autocomplete | 2 agents |
| **qwen2.5-coder:7b** | 4.7 GB | 6GB | Operations code, QA automation | Available |

### General Reasoning Models

| Model | Size | VRAM | Best For | Agents Using |
|-------|------|------|----------|--------------|
| **yi:34b** | 19 GB | 22GB | Complex reasoning, legal analysis, finance | 4 agents |
| **mixtral:8x7b** | 26 GB | 28GB | Multi-domain analysis, expert reasoning | 2 agents |
| **solar:10.7b** | 6.1 GB | 8GB | Instruction following, operations, project mgmt | 4 agents |
| **qwen2.5:7b** | 4.5 GB | 6GB | General reasoning, QA, business tasks | 3 agents |
| **llama3.1:8b** | 4.9 GB | 6GB | General tasks, HR, product | 4 agents |
| **llama3:latest** | 4.7 GB | 6GB | General tasks, backup | Available |
| **llama3.2:3b** | 2.0 GB | 3GB | Ultra-fast quick tasks, simple queries | 4 agents |

### Specialized Models

| Model | Size | VRAM | Best For | Agents Using |
|-------|------|------|----------|--------------|
| **dolphin3:latest** | 4.9 GB | 6GB | Creative content, marketing, uncensored | 7 agents |
| **nous-hermes2:latest** | 6.1 GB | 8GB | Empathy, medical, wellness, customer support | 6 agents |
| **mistral:latest** | 4.4 GB | 6GB | Sales, communication, business development | 3 agents |
| **command-r:latest** | 18 GB | 20GB | RAG, documentation, technical writing | 2 agents |

### Utility Models

| Model | Size | VRAM | Best For | Status |
|-------|------|------|----------|--------|
| **phi3:mini** | 2.2 GB | 3GB | Quick tasks, low resource | Available |
| **gemma2:2b** | 1.6 GB | 2GB | Light tasks, routing | Available |
| **aya:8b** | 4.8 GB | 6GB | Multilingual support | Available |
| **deepseek-coder:latest** | 776 MB | 1GB | Quick code snippets | Available |
| **deepseek-coder-v2:latest** | 8.9 GB | 10GB | Same as 16b (alias) | Available |

---

## Vision & Image Generation Models (Phase 51)

### Local Image Generation

| Model | Platform | VRAM | Cost | Status | Agent |
|-------|----------|------|------|--------|-------|
| **Fooocus SDXL** | Fooocus API | ~6GB | **FREE** | Active | Parker Artwood (Pixel) |

**Fooocus Configuration:**
- Server: `192.168.1.246:8888`
- API: `/v1/generation/text-to-image`
- Styles: realistic, anime, artistic, cinematic, digital-art
- Sizes: 1024x1024, 1024x1792, 1792x1024
- Generation Time: ~30-60 seconds

### Local Vision Models (Ollama)

| Model | Size | VRAM | Best For | Agent |
|-------|------|------|----------|-------|
| **minicpm-v:8b** | 5.5 GB | 8GB | OCR, multi-image analysis, document understanding | Victoria Seer (Vision) |
| **llava:7b** | 4.5 GB | 6GB | Quick image descriptions, general vision tasks | Iris Chen (Iris) |

### Vision/Media Team (CREATIVE Station)

| Agent | Human Name | Model | Role | Cost |
|-------|------------|-------|------|------|
| **Pixel** | Parker Artwood | fooocus-sdxl | Image Generation Specialist | FREE |
| **Vision** | Victoria Seer | minicpm-v:8b | Visual Intelligence Specialist | FREE |
| **Iris** | Iris Chen | llava:7b | Visual Analysis Assistant | FREE |

### Image Generation Routing

```
Image Request → generate_image_smart()
                      │
              ┌───────┴───────┐
              │ prefer_local? │
              └───────┬───────┘
                      │
          ┌───Yes─────┼─────No───┐
          │           │          │
          ▼           │          ▼
  ┌───────────────┐   │   ┌──────────────┐
  │ Try Fooocus   │   │   │ Use DALL-E   │
  │ (FREE, ~45s)  │   │   │ ($0.04-0.12) │
  └───────┬───────┘   │   └──────────────┘
          │           │
     ┌────┴────┐      │
     │ Success?│      │
     └────┬────┘      │
          │           │
     Yes──┼──No───────┘
          │      │
          ▼      ▼
      Return   Fallback to DALL-E
```

### Usage in Code

```python
from archie_bridge import (
    generate_image_smart,    # Smart routing (local first)
    generate_image_local,    # Force Fooocus
    analyze_image,           # Vision analysis
    enhance_image_prompt,    # Prompt enhancement
    check_fooocus_health     # Health check
)

# Generate image (local first, FREE)
result = generate_image_smart(
    prompt="Professional headshot of a software developer",
    style="realistic",
    prefer_local=True
)

# Analyze image (FREE)
result = analyze_image(
    image_url="https://...",
    prompt="Extract text from this document",
    model="minicpm-v:8b"
)
```

---

## External API Contractors (7 models)

External API models are used ONLY for escalation when local models cannot handle the task. These incur costs.

| Contractor | Provider | Model | Monthly Budget | Specialty |
|------------|----------|-------|----------------|-----------|
| **ChatGPT Contractor** | OpenAI | gpt-4o | $50 | Complex code generation, analysis |
| **Claude Contractor** | Anthropic | claude-sonnet-4 | $50 | Complex reasoning, long-form writing |
| **Gemini Contractor** | Google | gemini-pro | $50 | Research, multimodal (images) |
| **CoPilot Contractor** | Microsoft | copilot | $50 | IDE integration, code assistance |
| **Deepseek Contractor** | Deepseek | deepseek-chat | $50 | Specialized code, Chinese markets |
| **Grok Contractor** | xAI | grok-beta | $50 | Real-time info, X/Twitter integration |
| **Perplexity Contractor** | Perplexity | pplx-online | $50 | Web research, citations |

---

## Model Selection by Task Type

### When to Use Which Model

| Task Type | Primary Model | Backup Model | Notes |
|-----------|--------------|--------------|-------|
| **Code Generation** | deepseek-coder-v2:16b | starcoder2:7b | Complex → deepseek-coder:33b |
| **Code Completion** | starcoder2:7b | codellama:latest | IDE-style autocomplete |
| **Image Generation** | fooocus-sdxl | dall-e-3 | Local FREE → Paid fallback |
| **Image Analysis** | minicpm-v:8b | llava:7b | OCR, description, quality |
| **Avatar Generation** | fooocus-sdxl | dall-e-3 | Agent/profile avatars |
| **Security Analysis** | deepseek-coder:33b | deepseek-coder-v2:16b | Needs large context |
| **Legal/Compliance** | yi:34b | mixtral:8x7b | Complex reasoning required |
| **Finance/Tax** | yi:34b | mixtral:8x7b | Analytical reasoning |
| **Marketing/Creative** | dolphin3:latest | mistral:latest | Uncensored creativity |
| **Documentation** | command-r:latest | llama3.1:8b | RAG-optimized |
| **Healthcare/Wellness** | nous-hermes2 | llama3.1:8b | Empathetic responses |
| **Customer Support** | nous-hermes2 | llama3.2:3b | Empathy + speed |
| **Sales/BD** | mistral:latest | llama3.1:8b | Communication focus |
| **Operations/PM** | solar:10.7b | qwen2.5:7b | Instruction following |
| **QA/Testing** | qwen2.5:7b | llama3.1:8b | Test reasoning |
| **Quick Tasks** | llama3.2:3b | phi3:mini | Speed priority |
| **General** | llama3.1:8b | llama3:latest | Versatile |

---

## Model-to-Department Mapping

### Current Assignments (January 2026)

| Department | Primary Model | Agent Count |
|------------|--------------|-------------|
| **Creative (Media)** | fooocus-sdxl, minicpm-v:8b, llava:7b | 3 |
| Engineering | deepseek-coder-v2:16b, starcoder2:7b | 6 |
| Infrastructure | deepseek-coder-v2:16b | 4 |
| Security | deepseek-coder:33b | 2 |
| Marketing | dolphin3:latest | 7 |
| Operations | solar:10.7b, deepseek-coder-v2:16b | 4 |
| Finance | yi:34b, mixtral:8x7b | 3 |
| Legal | yi:34b | 1 |
| Compliance | yi:34b, deepseek-coder-v2:16b | 2 |
| Documentation | command-r:latest | 2 |
| Healthcare | nous-hermes2 | 2 |
| Wellness | nous-hermes2 | 2 |
| Customer Support | nous-hermes2 | 1 |
| Customer Success | nous-hermes2 | 2 |
| Sales | mistral:latest | 3 |
| Business Development | yi:34b, llama3.1:8b | 2 |
| Human Resources | llama3.1:8b | 2 |
| Administration | llama3.2:3b, qwen2.5:7b | 3 |
| General | llama3.2:3b | 2 |
| Quality Assurance | qwen2.5:7b | 2 |
| Product | solar:10.7b | 1 |
| Knowledge Management | deepseek-coder-v2:16b | 2 |
| Executive Leadership | deepseek-coder-v2:16b | 1 |
| Ethics & Governance | deepseek-coder-v2:16b | 1 |

---

## Escalation Workflow

### Local-First Routing

```
Task Received
    │
    ▼
┌───────────────────────┐
│ Check Task Type       │
│ → Select Local LLM    │
└───────────────────────┘
    │
    ▼
┌───────────────────────┐
│ Local LLM Processing  │
│ (FREE, Fast, Private) │
└───────────────────────┘
    │
    ├── Success → Return Result
    │
    └── Failure (after 3 retries)
            │
            ▼
    ┌───────────────────────┐
    │ Escalate to Contractor│
    │ (Paid, External API)  │
    └───────────────────────┘
            │
            ▼
    ┌───────────────────────┐
    │ Log Escalation        │
    │ Track Costs           │
    └───────────────────────┘
```

### Auto-Escalation Triggers

| Trigger | Contractor | Reason |
|---------|-----------|--------|
| Legal document review | Claude Contractor | Complex reasoning |
| Real-time web search | Perplexity Contractor | Live data needed |
| Complex image analysis | Gemini Contractor | Advanced multimodal (local handles most) |
| Image generation (local unavailable) | DALL-E 3 | Fooocus fallback |
| X/Twitter integration | Grok Contractor | Platform access |
| IDE-based coding | CoPilot Contractor | Tool integration |

**Note:** Image analysis and generation are now primarily handled by local models (minicpm-v, llava, Fooocus) at $0 cost. External APIs are only used as fallback.

---

## Hardware Requirements

### Recommended Setup

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| **GPU VRAM** | 8 GB | 16+ GB |
| **System RAM** | 32 GB | 64 GB |
| **Storage** | 100 GB SSD | 500 GB NVMe |
| **CPU** | 8 cores | 16+ cores |

### Current Server (A.R.C.H.I.E.)

- **GPU**: NVIDIA RTX 3070 (8GB VRAM)
- **CPU**: Intel i9-12900K (16 cores)
- **RAM**: 64 GB
- **Storage**: NVMe SSD

### Model Loading Strategy

1. **Always Loaded**: phi3:mini, llama3.2:3b (quick routing)
2. **On-Demand**: Larger models loaded when needed
3. **Cached**: Recently used models stay in memory
4. **Swapped**: Least-used models unloaded for space

---

## Cost Comparison

### Local vs External (Text LLMs)

| Metric | Local Ollama | External API |
|--------|-------------|--------------|
| **Cost per request** | $0.00 | $0.01-$0.10 |
| **Monthly cost (1000 requests)** | $0.00 | $10-$100 |
| **Latency** | 50-500ms | 500-3000ms |
| **Privacy** | Data stays local | Data sent externally |
| **Availability** | 100% (local) | Depends on provider |

### Local vs External (Image Generation)

| Metric | Local Fooocus | DALL-E 3 |
|--------|--------------|----------|
| **Cost per image** | $0.00 | $0.04-$0.12 |
| **Generation time** | 30-60s | 5-15s |
| **Quality** | Excellent (SDXL) | Excellent |
| **Styles** | 5 presets | 2 (vivid/natural) |
| **Privacy** | Local | Cloud |

### Local vs External (Vision Analysis)

| Metric | Local (minicpm-v) | External API |
|--------|-------------------|--------------|
| **Cost per image** | $0.00 | $0.01-$0.05 |
| **OCR quality** | Excellent | Excellent |
| **Multi-image** | Yes | Varies |
| **Privacy** | Local | Cloud |

### Estimated Monthly Savings

With 60 agents using local LLMs (including 3 new media agents):
- **Before optimization**: ~$1,500/month (external APIs)
- **After optimization**: ~$350/month (7 contractors only)
- **Monthly savings**: ~$1,150 (77% reduction)

**Image Generation Savings (estimated 500 images/month):**
- DALL-E only: $20-$60/month
- Local Fooocus: $0/month
- **Savings**: $20-$60/month

---

## Adding New Models

### Download via Ollama

```bash
# Example: Add a new model
ollama pull <model-name>

# List available models
ollama list

# Remove unused model
ollama rm <model-name>
```

### Recommended Future Models

| Model | Size | Purpose | When to Add |
|-------|------|---------|-------------|
| **codestral** | 22GB | Advanced code | When VRAM available |
| **llama3.3:70b** | 40GB | Enterprise reasoning | For complex analysis |
| **qwen2.5:14b** | 8GB | Better general | Upgrade from 7b |

---

## Monitoring & Metrics

### Track via HR Module

The HR Module (`/tools/hr-management`) shows:
- Model distribution by department
- Internal vs contractor usage
- LLM performance metrics

### Key Metrics

| Metric | Target | Current |
|--------|--------|---------|
| Local LLM usage | >90% | 90% (60/67) |
| External API usage | <10% | 10% (7/67) |
| Monthly API cost | <$500 | ~$350 |
| Local image generation | >80% | 100% (Fooocus active) |
| Local vision analysis | >90% | 100% (minicpm-v/llava) |

---

## API Endpoints (Media/Vision)

### Media Studio (`/tools/media-studio/api/`)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/generate` | POST | Generate image (auto/fooocus/dall-e-3) |
| `/analyze` | POST | Analyze image with vision model |
| `/enhance-prompt` | POST | Enhance prompt using AI |
| `/models` | GET | Get available models and status |

### Team Management (`/tools/team-management/api/`)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/agents/<id>/generate-avatar` | POST | Generate avatar for agent |
| `/agents/<id>/avatar-status` | GET | Check avatar generation status |
| `/agents/bulk-generate-avatars` | POST | Bulk avatar generation |

---

*Generated: January 20, 2026*
*Migrations: 051_local_llm_staffing_optimization.sql, 052_optimize_staff_new_llms.sql, 051_media_vision_agents.py*
