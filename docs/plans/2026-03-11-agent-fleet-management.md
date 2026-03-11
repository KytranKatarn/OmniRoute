# Agent Fleet Management System

**Date**: 2026-03-11 | **Status**: Approved | **Approach**: B (Fleet Rotation Engine)

## Problem

Agent dispatch cascades when primary agents exhaust budgets or welfare:
- Budget reset is passive (only fires on dispatch) — exhausted agents stay blocked forever
- Welfare never recovers (only updates on dispatch) — stressed agents stay stressed
- 12 idle agents watch 1 overworked agent drown
- No rotation, no fleet depth, no performance learning

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Handoff style | Graduated (finish job → cooldown → swap) | No dropped work, swap model loads during cooldown |
| Performance learning | Comparative ranking now, reservation later | Need ranking data before building queuing |
| Idle agent behavior | Station first, then volunteer at busy stations | Keeps station identity, solves overload |
| Empty stations | Ignore for now | Focus on 10 active stations first |
| Agent creation | Hybrid (auto-generate reserves, curate onboarding) | Every model dispatchable in emergencies |
| Future phase | Task reservation, predictive scheduling | Tracked as separate project |

## Section 1: Fix Foundations

### 1a. Budget Reset Deadlock
- `_refresh_welfare_cache()` already treats overdue `token_reset_at` as fresh (in progress)
- Add active DB reset: when cache detects overdue reset, fire UPDATE to zero counters
- Unblocks Pixel (1253/1000), Spark (1007/1000), Prism (2314/1000)

### 1b. Automatic Welfare Recovery
- New APScheduler job in agent_loop (every 30 minutes)
- Idle agents (not dispatched in last hour): stress -0.15, energy +0.2
- Resting agents: stress -0.3, energy +0.4 (faster recovery)
- Clamp 0.0-1.0

### 1c. Proactive Idle Volunteering
- New agent loop job (every 5 minutes)
- Scan: agents loaded in RAM + not busy + not resting + under budget
- If any station has pending/failed work with no available primaries, offer idle agent as auxiliary
- Uses existing cross-station dispatch path, triggered proactively

## Section 2: Shift System & Graduated Handoff

### 2a. Shift Lifecycle
```
ACTIVE → WINDING_DOWN → COOLDOWN → OFF_DUTY
```
- **ACTIVE**: Loaded, healthy, full dispatch scoring
- **WINDING_DOWN**: Budget 80%+ or stress 0.7+. 30% score penalty. System identifies replacement
- **COOLDOWN**: Budget exhausted or welfare critical. Finishes current job only. Replacement loading
- **OFF_DUTY**: Model unloaded. Rest cycle. Faster welfare recovery

### 2b. Replacement Selection
When agent enters WINDING_DOWN:
1. Find barracked agents with matching station capabilities
2. Score: skill proficiency (40%), RAM fit (30%), time since last shift (20%), historical performance (10%)
3. Load top candidate's model into RAM
4. Once warm, replacement enters ACTIVE. Original transitions through COOLDOWN → OFF_DUTY

### 2c. New Table: `agent_shifts`
- `agent_id`, `station_id`, `shift_state`
- `started_at`, `ended_at`, `tasks_completed`, `tasks_failed`
- `replaced_by` (agent_id), `reason` (budget_exhausted, welfare_critical, manual, scheduled)

## Section 3: Performance Tracking & Comparative Rankings

### 3a. New Table: `agent_performance_rankings`
- `agent_id`, `capability`, `tasks_completed`, `success_rate`
- `avg_duration_ms`, `avg_tokens_used`, `rank_score`, `rank_position`
- `last_updated`, `sample_size`

### 3b. Rank Score Formula
```
rank_score = (success_rate x 0.5) + (speed_score x 0.3) + (efficiency_score x 0.2)

speed_score = 1.0 - (agent_avg_duration / slowest_agent_avg_duration)
efficiency_score = 1.0 - (agent_avg_tokens / highest_agent_avg_tokens)
```
Minimum 10 tasks for reliable ranking. Below that, blend static proficiency (70%) + early rank (30%).

### 3c. Dispatch Integration
Replace static specialization score in `_score_agent()` with performance ranking.
Gradual transition: new agents start with manual skill ratings, shift to data-driven as tasks accumulate.

## Section 4: Roster Expansion & Agent Identity

### 4a. Talent Pool (50 Agents)
- Expand `model_catalog` to top 50 models from Ollama library
- Auto-generate reserve agent profiles for each (name, background, default skills)
- Flag as "unassigned reserve" until formally onboarded to a station

### 4b. Agent Portraits via ComfyUI
- Pixel generates realistic human portraits for each agent via SDXL
- Prompt template: "Professional headshot portrait of {display_name}, {ethnicity/background}, {age range}, neutral background, photorealistic"
- Maintain diversity matching existing names (Latina, Korean, Eastern European, West African, etc.)

### 4c. Multi-Size Avatars
From each portrait, generate 3 crops:
- **Full portrait** (512x512): Profile modals, detail pages
- **Avatar** (128x128): Crew cards, station panels, job cards
- **Mini icon** (32x32): Station crew dots, inline mentions, alert bar, logs

Storage: `static/img/agents/{agent_name}.png`, `_avatar.png`, `_icon.png`
Fallback: Initial-letter circles with station color until portrait generated.

### 4d. Agent Profile UI Overhaul
- Portrait (large), name, station, model, tier
- Shift state badge (active/winding down/cooldown/off-duty)
- Performance rankings (top 3 capabilities)
- Recent shift history
- Welfare gauges (stress/energy)

## Section 5: Bridge Command Visibility

### 5a. Crew Tab Enhancements
- Agent portrait replaces initial circles
- Shift state indicator (green=active, amber=winding down, red=cooldown, grey=off-duty)
- Welfare bar, current task, performance badge, budget meter

### 5b. Fleet Overview Panel
```
ON DUTY: 13 | WINDING DOWN: 1 | RESTING: 2 | RESERVES: 34 | RAM: 98/103 GB
```
Clickable counts filter the cards below.

### 5c. Rotation Log
Live feed of shift changes from `agent_shifts` table:
```
10:24 Scholar -> OFF_DUTY (welfare critical)
10:24 Athena (reserve) -> ACTIVE at RESEARCH
```

### 5d. Notifications
Rotation events push to: alert bar, Telegram advisories, Crew tab live feed.

## Future Phase (Tracked Separately)
- Task reservation/queuing (hold work for best agent)
- Predictive scheduling (pre-load models before peak hours)
- Self-healing (auto-hire when capability gaps detected)
- Multi-agent task handoff chains

## Modified Systems
- `ai_bridge/bridge_dispatcher.py` — budget reset, shift-aware scoring, performance rankings
- `ai_bridge/agent_loop.py` — welfare decay job, idle volunteering, shift transitions
- `platform_v2/tools/bridge/` — Crew tab UI overhaul, fleet overview, rotation log
- ComfyUI pipeline — portrait generation batch job
- Agent profile modal — full overhaul
