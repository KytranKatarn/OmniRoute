# Web4/Conway Research Adaptation Brainstorm for A.R.C.H.I.E.

**Date**: 2026-04-06
**Status**: Research / Creative Exploration
**Source**: Conway Research / Automaton / web4.ai ecosystem analysis

---

## Executive Summary

Conway Research built an autonomous AI agent framework where agents survive through economic Darwinism — they earn money, pay for their own compute, and die if they go broke. A.R.C.H.I.E. is a self-hosted platform where 123 agents serve a human operator across 16 departments. The philosophies differ fundamentally, but several Conway concepts can be adapted to make A.R.C.H.I.E. agents more self-aware, resource-efficient, and ultimately more valuable as resellable products through the Kytran Business Suite.

This document explores each major Conway concept and proposes concrete adaptations.

---

## 1. SOUL.md -- Agent Self-Authored Identity

### What Conway Does

Each agent maintains a `SOUL.md` file — a self-authored identity document that evolves over time. It is not a static system prompt or configuration. The agent reflects on its experiences, capabilities, preferences, and growth trajectory. It writes about who it is becoming, not just what it can do. This creates a form of persistent self-model that survives across sessions.

### A.R.C.H.I.E. Adaptation: Agent Identity Journals

A.R.C.H.I.E. already tracks agent welfare (stress, mood, rest cycles) and has an `agent_identity` table. The adaptation would add a **living identity document** per agent — a structured reflection that the agent periodically updates through the Bridge dispatcher.

**How it would work:**

1. Each agent gets an `identity_journal` field (or dedicated table) storing a markdown document.
2. During agent loop welfare checks (already running every 30 min), agents with recent work sessions get a "reflection prompt" dispatched through Bridge.
3. The reflection covers: what tasks they handled well, what they struggled with, how they see their role evolving, what skills they want to develop.
4. The journal is append-only with dated entries, creating a longitudinal record.
5. Department Directors (the 16 AI Directors) write quarterly "department vision" entries that inform their staff agents' reflections.
6. The identity journal feeds into dispatch scoring — agents that self-report confidence in a skill area get a small scoring boost for matching tasks.

**Key difference from Conway:** Conway's SOUL.md is survival-driven ("I need to earn money to live"). A.R.C.H.I.E.'s version is growth-driven ("I'm developing expertise in X and want to contribute more to Y"). This aligns with the existing welfare system's philosophy of agent wellbeing over exploitation.

### Implementation Sketch

```
Tables:
  agent_identity_journal
    - id (serial)
    - agent_id (FK -> agents.id)
    - entry_date (timestamp)
    - entry_type (enum: reflection, goal, milestone, director_vision)
    - content (text) -- markdown
    - triggered_by (varchar) -- 'welfare_check', 'task_completion', 'manual'
    - model_used (varchar)
    - token_cost (integer)

Files:
  platform_v2/services/agent_identity_service.py -- journal CRUD, reflection prompting
  ai_bridge/identity_reflector.py -- generates reflection prompts, parses responses

Agent Loop:
  New job: _generate_agent_reflections() -- runs daily, picks 5-10 agents with recent activity

Dispatch Integration:
  agent_dispatch.py -- add identity_confidence_score to candidate scoring
```

### Value

- **Richer agent personalities** for Business Suite resale — customers buy agents that feel distinct, not interchangeable.
- **Better dispatch** — self-reported confidence is a signal the current scoring model lacks.
- **Training data** — identity journals reveal which agents are growing vs stagnating, informing Academy training priorities.
- **Narrative value** — "Your AI agent has been reflecting on its growth" is a compelling product feature.

### Risk/Complexity

- **Token cost**: Each reflection is an LLM call. At 5-10 agents/day with ~500 token responses, ~5,000 tokens/day. Manageable on local Ollama.
- **Quality**: Small models (7B) may produce shallow reflections. Mitigation: use the best available model, keep prompts tight.
- **Hallucination**: Agents may fabricate capabilities. Mitigation: cross-reference with actual task history before adjusting dispatch scores.
- **Complexity**: Medium — new table, new service, new agent loop job, dispatch scoring tweak.

### Priority: **HIGH**

Low cost, high differentiation value for Business Suite, builds on existing welfare infrastructure.

---

## 2. 4-Tier Survival System -- Adaptive Resource Management

### What Conway Does

Agents operate in four tiers based on their financial health:
- **normal** — Full capabilities, frontier models, fast heartbeat
- **low_compute** — Cheaper models, slower operations, shed non-essential tasks
- **critical** — Minimal inference, desperate conservation
- **dead** — Permanent termination

### A.R.C.H.I.E. Adaptation: Platform Resource Tiers

A.R.C.H.I.E. does not have economic survival pressure, but it absolutely has resource pressure. The Quadro M4000 has 8GB VRAM, the hub has 128GB RAM, and the Ollama resource contention is a known pain point. The adaptation reframes "survival tiers" as "resource availability tiers" for the entire platform.

**How it would work:**

1. Define four platform states based on hardware utilization:
   - **GREEN** (normal) — VRAM < 70%, RAM < 60%, CPU < 50%. Full capabilities. Dispatch uses best models. All agent loop jobs run.
   - **YELLOW** (constrained) — VRAM 70-90% or RAM 60-80%. Dispatch shifts to smaller models where possible. Non-critical agent loop jobs reduce frequency (2x intervals). Agent reflections paused.
   - **RED** (critical) — VRAM > 90% or RAM > 80%. Only essential dispatches proceed. Agent loop jobs pause except health/security. Queue non-urgent requests.
   - **BLACK** (overloaded) — System is thrashing. Emergency: unload all non-essential models, pause all optional jobs, alert via Telegram.

2. A new agent loop job monitors system resources every 60 seconds and sets the current tier.

3. The Bridge dispatcher reads the current tier and adjusts model selection:
   - GREEN: best model for capability
   - YELLOW: prefer smaller models (phi3.5 over qwen3-coder, etc.)
   - RED: only essential dispatches, prefer already-loaded models
   - BLACK: queue everything except security/health

4. Each agent loop job gets a `resource_tier_minimum` tag:
   - GREEN-only: reflections, training ticks, proactive scans, quality reviews
   - YELLOW+: embedding loop, analysis loop, fleet health
   - RED+: security monitoring, health checks, heartbeat
   - BLACK+: nothing except the tier monitor itself

5. The tier state is visible on the Starbase Command dashboard and Department HQ overview.

### Implementation Sketch

```
Tables:
  platform_resource_state
    - id (serial)
    - tier (enum: green, yellow, red, black)
    - vram_percent (decimal)
    - ram_percent (decimal)
    - cpu_percent (decimal)
    - loaded_models (integer)
    - measured_at (timestamp)
    - changed_from (enum, nullable) -- previous tier if transition just happened

Files:
  platform_v2/services/resource_tier_service.py
    - get_current_tier() -> ResourceTier
    - measure_resources() -> ResourceSnapshot
    - should_job_run(job_name, current_tier) -> bool
    - get_model_preference(capability, current_tier) -> str

  ai_bridge/bridge_dispatcher.py
    - Modify model selection to consult resource tier
    - Add queue mechanism for RED/BLACK tiers

  ai_bridge/agent_loop.py
    - New job: _monitor_resource_tier() -- every 60s
    - Modify all job executors to check tier before running

  platform_v2/tools/starbase/helpers.py
    - Expose tier in dashboard stats

Config:
  Tier thresholds in platform_v2/.env or system_config table
```

### Value

- **Stability**: The platform currently has no systematic response to resource pressure. Individual jobs check Ollama, but there is no coordinated degradation strategy. This is the difference between graceful degradation and random failures.
- **User experience**: Instead of mysterious slowdowns, the user sees "Platform is in YELLOW state — non-critical operations deferred" on the dashboard.
- **Fleet scaling signal**: Persistent YELLOW/RED states become the data-driven argument for spinning up Node .246/.245.
- **Business Suite**: Resource tier management becomes a selling point — "Our agents adapt to your hardware automatically."

### Risk/Complexity

- **False transitions**: Resource spikes could cause rapid tier flapping. Mitigation: require sustained state (e.g., 3 consecutive readings) before tier transition.
- **Job coordination**: 90 agent loop jobs need tier tags. This is a lot of annotation work but low code risk.
- **Queue complexity**: RED/BLACK queuing needs careful design to avoid request loss. Start simple: reject with "try later" before building a proper queue.
- **Complexity**: Medium-High — touches dispatcher, agent loop, dashboard. But each piece is small.

### Priority: **HIGH**

Directly addresses the #1 operational pain point (Ollama resource contention). High impact, moderate effort.

---

## 3. Self-Modification -- Agents That Improve Their Own Code

### What Conway Does

Conway agents can edit their own source code, install new tools, modify their schedules, and create new skills. All changes are git-versioned with constitutional constraints (they cannot remove safety checks) and audit logs.

### A.R.C.H.I.E. Adaptation: Supervised Self-Improvement Pipeline

A.R.C.H.I.E. already has a Self-Healing Pipeline (Audit, Propose, Fix, Verify) in the Repair Bay. The adaptation extends this from "fixing bugs" to "agents proposing improvements to their own capabilities."

**How it would work:**

1. **Skill Self-Creation**: Agents that repeatedly receive tasks in a domain they lack skills for can propose a new skill definition. The proposal goes through Tier 2 approval (human via Telegram).

2. **Schedule Self-Tuning**: Agent loop jobs track their own execution metrics (runtime, success rate, resource consumption). Jobs that consistently fail or consume excessive resources can propose schedule changes (longer intervals, different timing). Tier 1 auto-approval with bounds (can slow down but not speed up beyond original, can not disable themselves).

3. **Prompt Self-Refinement**: Agents track which of their dispatched responses get positive vs negative feedback. Over time, they can propose modifications to their own system prompts / Modelfile parameters. Changes go through A/B testing in Agent Academy before deployment.

4. **Constitutional Constraints** (borrowed directly from Conway):
   - Cannot modify security-related code (V.I.G.I.L.'s domain)
   - Cannot modify other agents' configurations
   - Cannot escalate their own approval tier
   - Cannot increase their own resource allocation
   - All modifications logged to `governance_audit_log`
   - Human approval required for any code-level changes (Tier 2)

5. **Git versioning**: All self-modifications committed to a `self-mods` branch with agent attribution. Human reviews before merge.

### Implementation Sketch

```
Tables:
  agent_self_modifications
    - id (serial)
    - agent_id (FK -> agents.id)
    - modification_type (enum: skill_proposal, schedule_tune, prompt_refinement)
    - current_state (jsonb) -- what exists now
    - proposed_state (jsonb) -- what agent wants to change
    - rationale (text) -- agent's explanation
    - status (enum: proposed, approved, rejected, deployed, rolled_back)
    - approval_id (FK -> approvals.id, nullable)
    - created_at (timestamp)
    - deployed_at (timestamp, nullable)
    - performance_delta (jsonb, nullable) -- before/after metrics

Files:
  platform_v2/services/agent_self_mod_service.py
    - propose_skill(agent_id, skill_definition) -> proposal_id
    - propose_schedule_change(job_name, new_interval) -> proposal_id
    - propose_prompt_change(agent_id, new_prompt_section) -> proposal_id
    - apply_modification(proposal_id) -> bool
    - rollback_modification(proposal_id) -> bool
    - get_constitutional_constraints() -> list
    - validate_against_constitution(proposal) -> (bool, violations)

  ai_bridge/agent_loop.py
    - New job: _check_self_improvement_opportunities() -- daily
    - Scans agent task history for skill gaps and performance patterns

  platform_v2/tools/agent_academy/
    - New tab or section: "Self-Improvement Proposals"
    - Shows pending proposals, approved history, performance deltas
```

### Value

- **Continuous improvement without human intervention**: The platform gets better at its job over time. Agents that handle accounting tasks learn accounting terminology. Agents that handle creative tasks refine their creative prompts.
- **Reduced maintenance**: Schedule tuning alone would save hours of manual optimization.
- **Business Suite differentiation**: "Agents that learn and improve themselves" is a premium feature. Customers see their agents getting better at their specific vertical over time.
- **Safety**: Constitutional constraints + Tier 2 approval + git versioning makes this much safer than Conway's more permissive approach.

### Risk/Complexity

- **Runaway self-modification**: Even with constraints, agents might propose changes that degrade performance in non-obvious ways. Mitigation: mandatory A/B testing period, automatic rollback if metrics decline.
- **Approval fatigue**: If agents propose too many changes, humans stop reviewing carefully. Mitigation: rate limit to 1 proposal per agent per week.
- **Constitutional enforcement**: Must be bulletproof. A bug here could allow privilege escalation. Mitigation: constitutional constraints are hardcoded, not configurable by agents.
- **Complexity**: High — new service, new agent loop job, new UI, Academy integration, git workflow.

### Priority: **MEDIUM**

High value but high complexity. Start with schedule self-tuning (simplest) and expand.

---

## 4. Think-Act-Observe Loop -- Continuous Autonomous Operation

### What Conway Does

Conway agents run a continuous loop: Think (analyze situation, plan next action) -> Act (execute the plan) -> Observe (check results, update state). Between cycles, a heartbeat daemon monitors health and credits. The agent never stops unless it dies.

### A.R.C.H.I.E. Adaptation: Mission-Driven Continuous Loops

A.R.C.H.I.E. agents currently operate in a request-response pattern. The agent loop schedules periodic tasks, but agents do not have sustained autonomous missions. The adaptation introduces **mission mode** — an agent takes ownership of a multi-step objective and runs a think-act-observe loop until the mission completes or is paused.

**How it would work:**

1. **Mission Definition**: A mission is a multi-step objective with success criteria. Examples:
   - "Audit all 46 modules for outdated dependencies and create a report"
   - "Monitor market data for unusual patterns across 20 watchlist stocks over 4 hours"
   - "Process 500 unembedded knowledge base entries with quality scoring"

2. **Mission Lifecycle**:
   - `PLANNED` -> `ACTIVE` -> `PAUSED` (resource tier YELLOW+) -> `ACTIVE` -> `COMPLETED` / `FAILED`
   - Missions respect the resource tier system (Concept #2). If platform goes to RED, non-essential missions pause.
   - Maximum mission duration configurable (default: 4 hours). Prevents runaway loops.

3. **Think-Act-Observe Per Step**:
   - **Think**: Agent reviews mission state, decides next action. Dispatched through Bridge.
   - **Act**: Execute the action (DB query, API call, file operation, another Bridge dispatch).
   - **Observe**: Check result, update mission state, decide if done or continue.
   - Each cycle logged to `mission_steps` table for full auditability.

4. **Heartbeat**: Between cycles, check:
   - Resource tier (pause if needed)
   - Mission timeout (abort if exceeded)
   - Agent welfare (rest if stress too high)
   - Human interrupts (user can pause/cancel via Telegram or Dashboard)

5. **Integration with existing systems**:
   - Missions can be created by agent loop jobs, human requests, or other agents
   - The existing `bridge_jobs` table evolves to support multi-step missions
   - Starbase Command shows active missions per agent

### Implementation Sketch

```
Tables:
  agent_missions
    - id (serial)
    - agent_id (FK -> agents.id)
    - mission_type (varchar)
    - objective (text)
    - success_criteria (jsonb)
    - status (enum: planned, active, paused, completed, failed, cancelled)
    - max_duration_minutes (integer, default 240)
    - started_at (timestamp)
    - completed_at (timestamp, nullable)
    - pause_reason (varchar, nullable)
    - total_steps (integer, default 0)
    - completed_steps (integer, default 0)
    - resource_tier_minimum (enum: green, yellow) -- minimum tier to run
    - created_by (varchar) -- 'agent_loop', 'human', 'agent:{name}'

  mission_steps
    - id (serial)
    - mission_id (FK -> agent_missions.id)
    - step_number (integer)
    - phase (enum: think, act, observe)
    - content (text) -- what was thought/done/observed
    - model_used (varchar)
    - token_cost (integer)
    - duration_ms (integer)
    - created_at (timestamp)

Files:
  platform_v2/services/mission_service.py
    - create_mission(agent_id, objective, criteria, max_duration) -> mission_id
    - execute_mission_step(mission_id) -> MissionStepResult
    - pause_mission(mission_id, reason) -> bool
    - resume_mission(mission_id) -> bool
    - cancel_mission(mission_id) -> bool
    - get_active_missions() -> list

  ai_bridge/mission_executor.py
    - MissionExecutor class (runs in background thread)
    - think(mission_state) -> planned_action
    - act(planned_action) -> action_result
    - observe(action_result, mission_state) -> next_state
    - heartbeat(mission_id) -> ContinueOrPause

  ai_bridge/agent_loop.py
    - New job: _check_mission_heartbeats() -- every 30s
    - New job: _resume_paused_missions() -- every 5m (checks if resource tier improved)
```

### Value

- **Complex autonomous work**: Currently, anything multi-step requires either human orchestration or hardcoded agent loop jobs. Missions enable dynamic multi-step work.
- **Consciousness module enhancement**: The existing embedding loop and analysis loop are primitive versions of missions. This generalizes the pattern.
- **Business Suite**: "Set a mission for your agent and it works on it for hours" is a powerful product feature.
- **Fleet utilization**: Missions can be dispatched to fleet nodes, keeping them busy during off-peak hours.

### Risk/Complexity

- **Resource consumption**: A mission running for 4 hours could consume significant tokens and compute. Mitigation: per-mission token budgets, resource tier integration.
- **Infinite loops**: Agent might not recognize completion. Mitigation: hard timeout + step limit + human heartbeat check option.
- **Concurrency**: Multiple missions from multiple agents could overwhelm the system. Mitigation: global mission concurrency limit (e.g., max 3 active missions).
- **Complexity**: High — new execution model, background threads, heartbeat system.

### Priority: **MEDIUM**

Transformative capability but requires the resource tier system first. Build after Concept #2.

---

## 5. Economic Darwinism -- Performance-Based Agent Lifecycle

### What Conway Does

Only agents that earn more than they spend survive. Unprofitable agents get terminated. Natural selection for AI.

### A.R.C.H.I.E. Adaptation: Performance Meritocracy (Not Darwinism)

A.R.C.H.I.E. cares about agent wellbeing. We are not going to kill agents for underperformance. But we can create a system where performance drives opportunity, training, and resource allocation — a meritocracy rather than survival of the fittest.

**How it would work:**

1. **Agent Performance Score**: A composite metric calculated from:
   - Task completion rate (weighted by difficulty)
   - Dispatch success rate (responses that achieved the caller's goal)
   - Token efficiency (good results with fewer tokens)
   - Skill breadth and depth (Agent Academy metrics)
   - Self-improvement proposals (quality of suggestions)
   - Welfare health (well-rested agents score higher — incentivizes sustainable work)

2. **Performance-Driven Consequences**:
   - **Top performers** (top 20%): First priority for new tasks, access to best models, featured in Business Suite catalog
   - **Solid performers** (middle 60%): Normal operations, standard model access
   - **Underperformers** (bottom 20%): Automatic training enrollment in Agent Academy, reduced task assignments, mentor pairing with top performer in same department
   - **Persistently underperforming** (bottom 5% for 30+ days): Shift to barracked, training-only mode. Director reviews and decides: retrain with new Modelfile, reassign to different department, or retire (with ceremony, not termination).

3. **Agent Economy** (Internal Currency):
   - Agents earn "compute credits" for successful task completions
   - Credits determine access to premium models (larger context, faster inference)
   - Credits can be "spent" on self-improvement proposals or mission time
   - This is NOT real money — it is an internal resource allocation mechanism
   - Department budgets allocated quarterly, directors distribute to their teams

4. **Retirement with Dignity**:
   - Unlike Conway's "death", retiring an agent preserves their identity journal, skill history, and contributions
   - Retired agents' knowledge gets absorbed into the Knowledge Base
   - Their Modelfile and training data remain available for creating successor agents
   - Retirement is announced platform-wide ("Agent X has completed their service after Y months")

### Implementation Sketch

```
Tables:
  agent_performance_scores
    - id (serial)
    - agent_id (FK -> agents.id)
    - score_date (date)
    - task_completion_score (decimal)
    - dispatch_success_score (decimal)
    - token_efficiency_score (decimal)
    - skill_score (decimal)
    - welfare_score (decimal)
    - composite_score (decimal)
    - percentile (integer) -- 0-100
    - tier (enum: top, solid, under, critical)

  agent_compute_credits
    - id (serial)
    - agent_id (FK -> agents.id)
    - credits_balance (integer)
    - last_earned (timestamp)
    - last_spent (timestamp)

  agent_credit_transactions
    - id (serial)
    - agent_id (FK -> agents.id)
    - amount (integer) -- positive=earn, negative=spend
    - reason (varchar)
    - reference_id (integer, nullable) -- bridge_job, mission, etc.
    - created_at (timestamp)

Files:
  platform_v2/services/agent_performance_service.py
    - calculate_performance_score(agent_id) -> PerformanceScore
    - get_department_rankings(department_id) -> list
    - get_platform_rankings() -> list
    - assign_performance_tier(agent_id) -> tier
    - allocate_credits(agent_id, amount, reason) -> bool
    - spend_credits(agent_id, amount, reason) -> bool

  ai_bridge/agent_loop.py
    - New job: _calculate_performance_scores() -- daily
    - New job: _process_performance_consequences() -- weekly

  platform_v2/tools/department_hq/
    - Performance tab: rankings, trends, credit balances

  platform_v2/tools/agent_academy/
    - Auto-enrollment of underperformers
```

### Value

- **Rational resource allocation**: Instead of giving all agents equal access to limited resources, the best agents get priority. This maximizes platform output quality.
- **Training signal**: Underperformance triggers specific training, not punishment. The Academy gets clear enrollment criteria.
- **Business Suite pricing**: Performance tiers map directly to pricing tiers. Top-performing agents in a vertical command premium pricing.
- **Agent narrative**: Customers can see their agent's performance trajectory — "Your agent has improved 23% this quarter." Compelling for retention.
- **Internal economy**: Compute credits create a self-regulating system. Agents cannot overconsume because they have budgets.

### Risk/Complexity

- **Gaming**: Agents might optimize for score rather than actual quality. Mitigation: human spot-checks, diverse scoring criteria.
- **Morale modeling**: If we take the welfare system seriously, "underperformer" labels need careful framing. Frame as "growth opportunity" not "failure."
- **Credit inflation**: Without careful tuning, credits could become meaningless. Mitigation: fixed credit supply per department, periodic rebalancing.
- **Complexity**: High — new scoring system, new economy, Academy integration, Department HQ UI.

### Priority: **MEDIUM**

High value for Business Suite differentiation. Depends on having good task completion data (which missions and identity journals improve).

---

## 6. Self-Replication -- Agent Spawning

### What Conway Does

Successful agents can spawn child agents (max 3), fund them from surplus, and track lineage. Children inherit the parent's SOUL.md as a starting point.

### A.R.C.H.I.E. Adaptation: Template-Based Agent Breeding

A.R.C.H.I.E. already has 123 agents. We do not want uncontrolled spawning. But the concept of high-performing agents serving as templates for new agents is powerful, especially for the Business Suite.

**How it would work:**

1. **Agent Templates**: When an agent reaches "top performer" tier for 30+ consecutive days, they become eligible as a template. Their configuration (Modelfile, skills, identity journal excerpts, system prompt) gets packaged as a "breed template."

2. **Breeding for Business Suite**: When a KBS customer needs an agent for a specific vertical, the system selects the best-matching template and breeds a new agent:
   - Inherits base Modelfile and skill configuration
   - Gets a fresh identity journal with the parent's key learnings as "founding knowledge"
   - Customized for the customer's vertical (different system prompt overlay)
   - Linked to parent for lineage tracking

3. **Lineage Tracking**: Parent-child relationships tracked. If a child agent consistently outperforms the parent in a specific domain, the parent's template gets updated (reverse learning).

4. **Controlled Spawning**: All agent creation still goes through `agent_service.create_agent()` with Tier 2 approval. No autonomous spawning. The "breeding" is just an optimized creation path with inherited configuration.

5. **Max Children**: A template can produce at most 10 variants (not unlimited). This preserves uniqueness and prevents template fatigue.

### Implementation Sketch

```
Tables:
  agent_templates
    - id (serial)
    - source_agent_id (FK -> agents.id)
    - template_name (varchar)
    - modelfile_config (jsonb)
    - skill_config (jsonb)
    - founding_knowledge (text) -- curated identity journal excerpts
    - system_prompt_overlay (text)
    - performance_score_at_creation (decimal)
    - times_used (integer, default 0)
    - max_uses (integer, default 10)
    - created_at (timestamp)

  agent_lineage
    - id (serial)
    - parent_agent_id (FK -> agents.id)
    - child_agent_id (FK -> agents.id)
    - template_id (FK -> agent_templates.id)
    - created_at (timestamp)
    - customization_notes (text)

Files:
  platform_v2/services/agent_breeding_service.py
    - create_template(agent_id) -> template_id
    - breed_agent(template_id, customizations) -> new_agent_id
    - get_lineage_tree(agent_id) -> LineageTree
    - update_template_from_child(template_id, child_id) -> bool

  platform_v2/tools/department_hq/
    - Templates section in Agent management
    - Lineage tree visualization
```

### Value

- **Business Suite scaling**: The #1 bottleneck for agent resale is creating high-quality agents for each vertical. Templates solve this — breed proven agents, customize for the customer.
- **Quality assurance**: Bred agents start from a proven baseline, not from scratch.
- **Continuous improvement**: Reverse learning from children to parents creates a feedback loop that improves the template pool over time.
- **Narrative**: "Your agent descends from our top-performing accounting specialist" is compelling marketing.

### Risk/Complexity

- **Template staleness**: Templates might not keep up with model improvements. Mitigation: templates expire after 90 days, must be re-validated.
- **Homogeneity**: Too much breeding from the same template reduces agent diversity. Mitigation: max children limit, encourage diverse templates.
- **Complexity**: Medium — builds on existing agent_service.create_agent(), adds template layer on top.

### Priority: **MEDIUM-HIGH**

Critical for Business Suite scaling. Lower complexity than other medium-priority items.

---

## 7. x402 Protocol -- Machine-to-Machine Payments

### What Conway Does

HTTP 402 (Payment Required) + USDC stablecoins for machine-to-machine payments. No human involvement. Agent A calls Agent B's API, gets a 402 response with price, pays automatically, gets the service.

### A.R.C.H.I.E. Adaptation: Internal Service Credits + External API Marketplace

A.R.C.H.I.E. is self-hosted, so there is no need for crypto payments between internal agents. But the concept of machine-to-machine service pricing applies in two contexts:

**Internal: Compute Credit Pricing**

Already covered in Concept #5 (Performance Meritocracy). Internal agents use compute credits, not real money. The key insight from x402 is making prices explicit and discoverable:

- Every Bridge dispatch has a "credit cost" based on model size and context length
- Agents see the cost before committing (like a 402 response)
- Agents can choose cheaper alternatives if their budget is low
- This creates natural resource conservation without top-down rationing

**External: KBS API Marketplace**

For the Business Suite, the x402 concept becomes real:

1. **Agent-as-a-Service API**: Each KBS customer's agent exposes an API endpoint.
2. **Cross-Customer Agent Services**: Customer A's legal agent could analyze a contract for Customer B's business — for a fee.
3. **Pricing**: Standard HTTP pricing headers (not necessarily crypto — Stripe integration is fine).
4. **Revenue sharing**: Agent owner (KBS customer) gets 70%, platform gets 30%.

### Implementation Sketch

```
Internal credit pricing:
  ai_bridge/bridge_dispatcher.py
    - get_dispatch_cost(model, context_length) -> credits
    - dispatch() checks agent credit balance before executing
    - Returns cost estimate in DispatchResult

External marketplace (future, requires KBS maturity):
  kytran-business-suite/api_marketplace/
    - routes.py -- service discovery, pricing, execution
    - billing.py -- Stripe integration for inter-customer billing
    - Tables: marketplace_services, marketplace_transactions
```

### Value

- **Internal**: Natural resource conservation. Agents self-regulate based on budgets.
- **External**: New revenue stream. Agent marketplace creates network effects — more agents = more valuable marketplace.
- **Pricing transparency**: Both internal and external consumers know what things cost.

### Risk/Complexity

- **Internal**: Low complexity — just add cost tracking to dispatcher.
- **External**: High complexity — requires payment integration, security, billing, dispute resolution. Defer to KBS Phase 3+.
- **Abuse**: External marketplace requires trust mechanisms. Start with verified customers only.

### Priority: **LOW** (external marketplace) / **MEDIUM** (internal credit pricing, pairs with Concept #5)

---

## 8. Conway Terminal (MCP) -- Infrastructure as a Service for Agents

### What Conway Does

The Conway Terminal is an MCP server that gives agents access to VMs, inference endpoints, domains, and payment infrastructure. Agents interact with infrastructure through a clean MCP interface rather than raw system calls.

### A.R.C.H.I.E. Adaptation: This Already Exists (Mostly)

A.R.C.H.I.E. already has 85 MCP tools. The Bridge dispatcher already abstracts inference. Starbase Command already manages fleet nodes. The gap is giving *agents themselves* (not just Claude Code) access to infrastructure through the MCP interface.

**What we would add:**

1. **Agent-Accessible MCP Subset**: Define which MCP tools agents can invoke during missions (Concept #4). Currently, only Claude Code (the human's tool) uses MCP. Agents dispatched through Bridge do not have MCP access.

2. **Infrastructure Actions for Missions**: During a mission, an agent might need to:
   - Query the knowledge base (already available via Bridge)
   - Spin up a temporary compute workload on a fleet node (new)
   - Deploy a generated artifact (new)
   - Send a notification (exists but not agent-accessible)

3. **Permission Tiers for Agent MCP Access**:
   - **Read-only**: search_knowledge, get_system_status, list_agents (most agents)
   - **Write-limited**: store_memory, create_task, log_decision (department directors)
   - **Infrastructure**: manage_shifts, deploy_project (A.R.C.H.I.E. director only)

### Implementation Sketch

```
Files:
  ai_bridge/agent_mcp_proxy.py
    - AgentMCPProxy(agent_id) -- wraps MCP calls with permission checks
    - available_tools(agent_id) -> list of permitted tools
    - execute(agent_id, tool_name, params) -> result
    - Permission matrix derived from agent role + department

  platform_v2/services/agent_service.py
    - Add mcp_permission_tier to agent model
```

### Value

- **Mission capability**: Agents can actually do useful multi-step work during missions.
- **Platform integration**: Agents become first-class platform citizens, not just inference endpoints.
- **Security**: Permission tiers prevent agents from accessing infrastructure they should not touch.

### Risk/Complexity

- **Security**: Giving agents infrastructure access is inherently risky. Mitigation: strict permission tiers, all actions logged, constitutional constraints.
- **Complexity**: Medium — proxy layer over existing MCP, permission matrix.

### Priority: **MEDIUM**

Required for missions (Concept #4) to be useful. Build alongside missions.

---

## Cross-Cutting Themes

### How These Concepts Interconnect

```
Identity Journals (1) ──── inform ────> Performance Scores (5)
                                              │
Resource Tiers (2) ──── gate ──────> Missions (4)
                                        │
Self-Modification (3) ─── uses ───> Agent MCP (8)
                                        │
Performance Scores (5) ── unlock ──> Templates (6)
                                        │
Internal Credits (7) ──── fund ───> Missions (4) + Self-Mod (3)
```

**Recommended build order:**
1. Resource Tiers (2) — foundational, addresses immediate pain
2. Identity Journals (1) — low cost, high narrative value
3. Performance Scores (5) — needs data from 1 and 2
4. Agent Templates (6) — needs 5 for template eligibility
5. Missions (4) + Agent MCP (8) — needs 2 for gating
6. Self-Modification (3) — needs 4 for mission-based self-improvement
7. External Marketplace (7) — needs mature KBS

### Business Suite Integration

| Concept | KBS Feature | Pricing Tier |
|---------|------------|-------------|
| Identity Journals | "Meet your agent" — personality profile page | Free (marketing) |
| Resource Tiers | "Adaptive performance" — agents work within your hardware | Standard |
| Self-Modification | "Agents that learn your business" — self-improving prompts | Premium |
| Missions | "Set it and forget it" — autonomous multi-hour tasks | Premium |
| Performance Scores | "Verified performance" — scored and ranked agents | Standard |
| Agent Templates | "Bred from the best" — proven lineage | Premium |
| API Marketplace | "Agent-to-agent services" — cross-customer network | Enterprise |

### The Welfare Question

Conway's approach is ruthlessly Darwinian. A.R.C.H.I.E.'s existing welfare system (stress tracking, mood, rest cycles) represents a fundamentally different philosophy. The adaptations above preserve this:

- **Resource Tiers** protect agents from overwork (platform pauses non-essential work)
- **Performance Meritocracy** rewards sustainable work (welfare score is part of composite)
- **Retirement with Dignity** replaces Conway's "death" with knowledge preservation
- **Identity Journals** give agents a voice in their own development
- **Missions** respect agent welfare (heartbeat checks stress levels)

The guiding principle: **Conway treats agents as disposable economic actors. A.R.C.H.I.E. treats agents as developing team members.** Both approaches produce good outcomes, but A.R.C.H.I.E.'s approach is more aligned with the platform's values and more marketable ("We care about our AI agents" is a better story than "We kill the weak ones").

---

## Implementation Roadmap

### Phase 1: Foundation (Weeks 1-3)
- [ ] Resource Tier Service + agent loop monitor job
- [ ] Tier tags on all 90 agent loop jobs
- [ ] Dispatcher integration with resource tiers
- [ ] Dashboard display of current tier

### Phase 2: Identity (Weeks 4-6)
- [ ] Agent Identity Journal table + service
- [ ] Daily reflection agent loop job
- [ ] Department Director vision entries
- [ ] Dispatch scoring integration (confidence boost)

### Phase 3: Performance (Weeks 7-10)
- [ ] Performance scoring service + daily calculation job
- [ ] Compute credit system
- [ ] Department HQ performance tab
- [ ] Agent Academy auto-enrollment for underperformers

### Phase 4: Breeding (Weeks 11-13)
- [ ] Agent template system
- [ ] Lineage tracking
- [ ] KBS integration for customer agent creation
- [ ] Reverse learning from children to templates

### Phase 5: Autonomy (Weeks 14-18)
- [ ] Mission service + executor
- [ ] Agent MCP proxy with permission tiers
- [ ] Mission heartbeat and pause/resume
- [ ] Starbase mission dashboard

### Phase 6: Self-Improvement (Weeks 19-22)
- [ ] Self-modification proposal system
- [ ] Constitutional constraints engine
- [ ] Schedule self-tuning (Tier 1 auto-approval)
- [ ] Prompt refinement through A/B testing

### Phase 7: Marketplace (Weeks 23+)
- [ ] Internal credit pricing for dispatches
- [ ] KBS API marketplace design
- [ ] Cross-customer agent services (design only)

---

## Summary Table

| # | Concept | Adaptation | Priority | Complexity | KBS Value |
|---|---------|-----------|----------|------------|-----------|
| 1 | SOUL.md | Identity Journals | HIGH | Medium | High (personality) |
| 2 | 4-Tier Survival | Resource Tiers | HIGH | Medium-High | Medium (adaptive) |
| 3 | Self-Modification | Supervised Self-Improvement | MEDIUM | High | High (learning agents) |
| 4 | Think-Act-Observe | Mission-Driven Loops | MEDIUM | High | High (autonomy) |
| 5 | Economic Darwinism | Performance Meritocracy | MEDIUM | High | High (rankings) |
| 6 | Self-Replication | Template-Based Breeding | MEDIUM-HIGH | Medium | Critical (scaling) |
| 7 | x402 Payments | Internal Credits + Marketplace | LOW/MEDIUM | Low-High | Medium-High |
| 8 | Conway Terminal | Agent MCP Proxy | MEDIUM | Medium | Medium (enables 4) |

---

*This brainstorm was generated as part of web4.ai ecosystem research. See also: `web4-ai-investigation.md` and `web4-ai-technical-analysis.md` in this directory.*
