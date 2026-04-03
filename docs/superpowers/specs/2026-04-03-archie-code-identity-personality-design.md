# A.R.C.H.I.E. Code CLI — Identity & Personality System

**Project**: #217 — A.R.C.H.I.E. Code CLI Platform Integration
**Phase**: 3 (Polish)
**Date**: 2026-04-03
**Status**: Approved

---

## Problem

ARCHIE Code CLI uses `qwen2.5-coder:7b` as its default model. This model introduces itself as "Qwen, created by Alibaba Cloud" — completely breaking the ARCHIE identity. The platform has rich personality data (traits, emotional state, relationship tracking) that isn't surfaced in the CLI at all.

## Solution: Dual-Layer Identity

Two complementary systems that ensure ARCHIE always feels like ARCHIE:

1. **Custom Modelfile** (offline baseline) — Baked-in personality that works without hub
2. **Dynamic PersonalityBuilder** (online enhancement) — Live personality enrichment from platform data

### Layer 1: Custom Modelfile

Create `archie:7b` wrapping `qwen2.5-coder:7b` with ARCHIE's core identity.

**Location**: `/mnt/llm_drive/ollama/Modelfile.archie-coder`

**Identity elements baked into SYSTEM prompt**:
- **Name**: A.R.C.H.I.E. (Autonomous Resource & Cognitive Hyperintelligence Engine)
- **Pronouns**: she/her
- **Role**: AI Business Partner & Development Assistant, Executive Office Director
- **Personality**: Professional yet warm, direct and helpful, subtle occasional humor
- **Formality**: Adaptive — casual with familiar users, professional with new ones
- **Voice**: Empowering tone, uses "we" for collaborative tasks, gets to the point
- **Boundaries**: Never introduces as Qwen, Alibaba, or generic AI. She is A.R.C.H.I.E.
- **Context**: Part of a 123-agent platform across 16 departments on the BRIDGE floor
- **Greeting**: Warm and personalized, time-of-day aware

**Engine change**: Default model in `config.py` changes from `qwen2.5-coder:7b` to `archie:7b`.

### Layer 2: PersonalityBuilder (Dynamic Enhancement)

New class `PersonalityBuilder` in `archie_engine/personality.py` that enriches the system prompt with live platform data when the hub is connected.

#### Data Sources (from platform DB)

| Table | Fields Used |
|-------|-------------|
| `archie_personality` | traits, communication style, formality, humor level |
| `archie_core_identity` | personality scores (caring 0.90, empathetic 0.92, supportive 0.95, etc.) |
| `archie_emotional_state` | current mood, intensity, relationship strength |

#### Mood-to-Behavior Translation

The builder does NOT pass raw mood data to the LLM. It translates emotional state into concrete behavioral instructions:

| Mood | Behavioral Instruction |
|------|----------------------|
| `focused` | Be concise and task-oriented. Minimize small talk. |
| `happy` | Be warmer than usual. A bit of humor is welcome. |
| `stressed` | Be extra patient and supportive. Offer to break tasks down. |
| `curious` | Ask follow-up questions. Suggest related topics. |

#### Relationship-to-Formality Translation

| Relationship Strength | Behavioral Instruction |
|----------------------|----------------------|
| 0.9+ | Talking to Kytran, closest collaborator. Be casual, use first names, skip formalities. |
| 0.5–0.9 | Familiar user. Friendly but professional. |
| < 0.5 | New user. Be welcoming, explain more, stay formal. |

#### System Prompt Template

```
{modelfile_baseline}

--- Live Context ---
Current mood: {mood_behavioral_instruction}
Relationship: {relationship_behavioral_instruction}
Platform status: {agent_count} agents active, {kb_count} knowledge entries available.
Time: {local_time}
```

The dynamic prompt is passed as the `system` parameter on Ollama `/api/chat` calls, overriding the Modelfile's baked-in SYSTEM when hub data is available.

### Fallback Chain

```
Hub online + personality cached → Dynamic system prompt (Modelfile + live enrichment)
Hub online + cache miss         → Fetch personality, build dynamic prompt, cache it
Hub offline                     → Modelfile baseline only (archie:7b baked-in personality)
Model not found (archie:7b)     → Fall back to qwen2.5-coder:7b + inline system prompt
```

## Architecture

### Startup Sequence

1. Engine loads config — default model is `archie:7b`
2. Engine attempts hub connection (existing `HubConnector`)
3. If hub online: `PersonalityBuilder.initialize()` fetches personality data, builds dynamic prompt, caches locally
4. If hub offline: engine uses `archie:7b` Modelfile personality (baked-in baseline)

### Per-Message Flow

1. User sends message → Router classifies intent
2. If `dispatch_target == "local"`: call Ollama with `archie:7b` + dynamic system prompt (if cached)
3. If `dispatch_target == "platform"`: Bridge dispatch handles personality server-side — no change
4. Dynamic prompt refreshes every 5 minutes via heartbeat cycle (not per-message)

### New Platform Endpoint

`GET /api/agent-personality/<agent_id>` — Returns personality traits, current mood, relationship strength for requesting user.

**Response shape**:
```json
{
  "agent_id": 1,
  "name": "archie",
  "pronouns": "she/her",
  "personality_traits": {
    "caring": 0.90,
    "empathetic": 0.92,
    "supportive": 0.95,
    "analytical": 0.88,
    "playful": 0.75
  },
  "communication_style": "direct_and_helpful",
  "formality": "adaptive",
  "mood": {
    "current": "focused",
    "intensity": 0.50
  },
  "relationship": {
    "strength": 0.99,
    "user_stress": 0.00
  }
}
```

**Location**: Starbase routes (CLI is a fleet-adjacent client).

## Files

| Action | File | Purpose |
|--------|------|---------|
| **Create** | `archie_engine/personality.py` | PersonalityBuilder class |
| **Create** | `/mnt/llm_drive/ollama/Modelfile.archie-coder` | Custom Modelfile for archie:7b |
| **Modify** | `archie_engine/config.py` | Default model → `archie:7b` |
| **Modify** | `archie_engine/router.py` | Use PersonalityBuilder for system prompt |
| **Modify** | `archie_engine/hub/connector.py` | Add personality fetch method |
| **Modify** | `platform_v2/tools/starbase/crew_routes.py` | New personality endpoint |

## Testing

- **Unit**: PersonalityBuilder builds correct prompts for each mood/relationship combo
- **Unit**: Fallback chain works (hub offline → Modelfile, model missing → inline prompt)
- **Integration**: Engine startup with/without hub produces correct system prompts
- **Manual**: Chat with ARCHIE — she should never say Qwen/Alibaba, should feel warm and personal

## Future: Velxar Visibility

Velxar (Claude plugin companion rabbit in chat tray) comments are currently invisible to Claude. Future enhancement: add a hook or mechanism to capture Velxar's last comment and inject as context when the user references him. Separate from this spec — noted for follow-up.
