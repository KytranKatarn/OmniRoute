---
name: archie-agent
description: A.R.C.H.I.E. agent lifecycle operations — propose hire (reactivate or new), inspect welfare/budget, list agents by capability, retire. ALL new hires require explicit Kytran approval per session rule. Invoke when the user asks to "hire", "reactivate", "decommission", "add an agent", check who can do X, or investigate an agent's health.
---

# A.R.C.H.I.E. Agent Lifecycle

All agent mutations go through `services.agent_service` — never raw SQL on `agents` table. K.I.N. single-writer guardrail enforces this.

## Hard rule — no auto-hire

**NEVER create or reactivate an agent without explicit Kytran approval in-session.** Propose candidates via this skill → get approval → execute via migration. Dept HQ UI at task #2102 will eventually gate this formally.

## Inspect

### Who has a capability
```python
from services.agent_service import match_capability
candidates = match_capability("translate")
# Returns list of {id, name, display_name, department, model, shift_state, proficiency_level}
# Ordered by proficiency DESC. Decommissioned agents included — filter on shift_state.
```

### Who would the coordinator pick
```python
from services.department_coordinator import get_coordinator
coord = get_coordinator()
# Per-agent score breakdown for a capability in a department:
for name in ("CODEX", "ROSETTA", ...):
    info = agent_cache.get(name)
    score, blocked = coord.score_agent(name, info, "translate", "Documentation & Knowledge")
```

### Welfare + budget snapshot
```sql
SELECT a.name, a.shift_state, a.model,
       ab.current_task_count, ab.task_queue_limit, ab.tokens_used_today,
       emo.stress_level, emo.energy, emo.mood_intensity
FROM agents a
LEFT JOIN agent_budgets ab ON ab.agent_id = a.id
LEFT JOIN agent_emotional_state emo ON emo.agent_id = a.id
WHERE a.name = '<agent>';
```

(Remember: `agent_emotional_state` is SINGULAR, `current_mood` not `mood`, `skill_category` not `category`.)

## Propose hire (the hard rule path)

### Reactivation (preferred — uses existing persona)
1. Find a decommissioned agent with matching skills:
   ```sql
   SELECT a.name, a.display_name, a.model, a.shift_state, string_agg(s.skill_name || ':' || s.proficiency_level, ', ') AS skills
   FROM agents a LEFT JOIN agent_skills s ON s.agent_id = a.id
   WHERE a.shift_state = 'decommissioned'
     AND s.skill_name = '<capability>'
     AND s.proficiency_level >= 4
   GROUP BY a.id, a.name, a.display_name, a.model, a.shift_state;
   ```
2. Propose to user: name, skills, current model, recommended new model (CPU vs GPU)
3. Get approval
4. Write migration (see `324_rosetta_reactivation.sql` for template)

### New acronym agent
1. Design acronym + backronym matching platform convention (4-6 letters; see R.O.S.E.T.T.A., C.O.D.E.X., V.I.G.I.L., etc.)
2. Propose profile:
   - `name`, `display_name`, `title`, `acronym`, `acronym_expansion`
   - `department`, `floor`, `model` (CPU vs GPU tier)
   - Skills with proficiency levels
   - `task_queue_limit` (10 default, match peers)
   - `system_prompt` (persona + role description)
   - Human persona (first_name/last_name/bio) — thoughtful diversity, not stereotyped
3. Get approval
4. Write migration inserting into `agents`, `agent_skills`, `agent_budgets`
5. Create portrait placeholder at `/static/media/portraits/<name>.png`

## Model assignment — GPU vs CPU

Per the dual-lane pattern (CODEX/ROSETTA):

| Tier | When | Pattern |
|---|---|---|
| GPU | Low-latency capability, department director | `mistral:7b`, `qwen2.5-coder:7b`, `gemma2:9b` (all ~5-6GB VRAM fit on M4000 8GB) |
| CPU | Overflow/peer, rarely-hit capability, big model not viable on GPU | `mistral-cpu` (Modelfile variant `num_gpu 0`), `phi3.5`, `llama3.2:3b` |
| Cloud | Exotic capability, contract work | `:cloud` suffix — skips local load |

One department should NOT have two GPU agents sharing the same model — they'll evict each other.

## Decommission

```sql
UPDATE agents
SET shift_state = 'decommissioned',
    status = 'inactive',
    updated_at = NOW()
WHERE name = '<agent>';
```

NEVER delete. Decommissioned agents stay in DB for history, reactivation, audit.

## Welfare triage

Agent in `shift_state = 'winding_down'` or `'cooldown'`:
- Dispatcher deprioritizes them (score -0.3 for winding_down)
- Transitions auto-happen via `agent_loop` job (check `agent_rest_cycles` for recent entries)
- Don't manually force back to active — let the natural cycle complete

## Related

- `/archie-budget` — check counter drift across the roster
- `/archie-patterns` — budget increment/decrement pair (mandatory)
- `/archie-status` — platform-level view including translate pair

## Rules

- **No auto-hire** — every new agent = Kytran approval via UI (#2102) or in-session explicit yes
- **Agent mutations through agent_service only** — K.I.N. guardrail blocks raw SQL on `agents` in new files
- **Acronyms are not optional** — new agents get full acronym + backronym + profile makeover
- **Preserve personas on reactivation** — the human persona is painstakingly designed; only rename/retitle, don't overwrite bio
