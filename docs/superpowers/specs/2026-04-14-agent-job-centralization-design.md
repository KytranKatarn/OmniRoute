# Agent & Job Centralization — Department HQ as Single Source of Truth

**Date:** 2026-04-14
**Status:** Approved (brainstorm complete)
**Projects:** #261 (LLM Resource Management), #240 (Load Spike Investigation)
**Priority:** 9

---

## Problem Statement

The platform has 131 agents, 90+ scheduled jobs, and 10 loaded LLM models consuming ~107GB RAM. These are scattered across multiple files, tables, and modules with no single point of visibility or control. Result: 227 failed jobs/day, load average 22+, swap maxed at 8GB/8GB, MCP timeouts, and no clear ownership of what's working vs broken.

## Core Principle

**Department HQ is the single source of truth for everything agent-related.** If it's about an agent — profile, model, system prompt, portrait, jobs, performance — it lives in Department HQ and is managed from the Roster Tab.

---

## Section 1: Roster as Single Source of Truth

The `agents` table + Roster Tab becomes the ONE place all agent data lives.

### Data Ownership

| Data | Current Location | After |
|------|-----------------|-------|
| Profile (name, role, personality) | `agents` table | `agents` table (no change) |
| Portrait/sprites | Filesystem + scattered refs | `agents.portrait_url` + Roster UI upload |
| Modelfile/system prompt | `/mnt/llm_drive/ollama/Modelfile.*` files | `agents.system_prompt` column (DB) → auto-exported to Modelfile on save |
| Model assignment | `agents.model_id` (often stale) | `agents.model_name` — validated against Ollama tags |
| Department/skills | `agents` table | No change — already there |
| Org Chart | Separate rendering logic | Generated dynamically from Roster query (directors → staff by department) |
| Website directory | Hardcoded or separate data | API endpoint `/api/agents/public-roster` pulls from `agents` table |
| C.R.E.E.D. welfare badge | Not shown in Roster | Small green/yellow/red badge per agent from welfare tables |

### LLM Sharing Model

Agents share LLMs by department/skill type, differentiated by system prompts (Modelfiles):

- **Code tasks** (ENGINEERING, F.O.R.G.E.) → `qwen2.5-coder:7b` or `deepseek-coder-v2:16b`
- **Writing/creative** (CREATIVE, M.U.S.E.) → `gemma2:9b`
- **Analysis/reasoning** (ANALYTICS, SECURITY) → `mistral:7b` or `phi3.5`
- **Lightweight/fast** (notifications, HR, wellness) → `smollm2:1.7b` or `llama3.2:3b`
- **Embeddings** (all) → `arctic-embed-cpu` (always loaded)

Agent Academy benchmarks determine which model performs best per skill category. Results stored in Roster.

### Modelfile Management

- System prompts stored in `agents.system_prompt` (DB column, TEXT)
- On save in Roster UI, auto-export to `/mnt/llm_drive/ollama/Modelfile.{agent_name}`
- Ollama `create` command runs to register the Modelfile
- Version history via `agents` audit trail

### Consumers (Read-Only from Roster)

- **Org Chart Tab** — queries agents by department, renders hierarchy
- **Website directory** — `/api/agents/public-roster` returns display_name, role, department, portrait for public pages
- **kytranempowerment.com directors page** — same API
- **C.R.E.E.D. standalone** — agent count + department stats via API
- **Dispatcher** — reads agent skills, model, department for capability matching

---

## Section 2: C.R.E.E.D. + Wellness Data Model

### Separation of Concerns

- **Roster (Department HQ)** = "Who the agent IS" — identity, static/slow-changing
- **C.R.E.E.D.** = "How the agent is DOING" — runtime, continuous monitoring
- **Dispatcher** = checks BOTH — "Is this agent qualified (Roster) AND healthy (C.R.E.E.D.)?"

### C.R.E.E.D. Tables (Runtime/Behavioral Data)

| Table | Purpose | Key Fields |
|-------|---------|------------|
| `agent_emotional_state` | Current welfare snapshot | stress_level, mood_intensity, fatigue (exists) |
| `agent_rest_cycles` | Work/rest compliance | shift duration, breaks taken (exists) |
| `agent_ethics_log` | Governance audit trail | agent_id, event_type, decision, outcome |
| `agent_welfare_alerts` | Threshold breach notifications | agent_id, alert_type, severity, resolved_at |
| `agent_performance_metrics` | Dispatch outcomes | success_rate, error_rate, avg_response_time |
| `agent_workload_history` | Load over time | agent_id, jobs_hour, concurrent_tasks, timestamp |

### Wellness Features to Add

- **Burnout detection** — if error rate climbs over 3 days, flag agent + notify department director
- **Workload balancing** — dispatcher prefers idle agents in same department over overloaded ones
- **Recovery tracking** — after rest cycle, verify metrics improved before returning to active shift
- **Ethics compliance score** — per-agent C.R.E.E.D. score (0-100) visible as badge in Roster
- **Department health score** — aggregate welfare across department, visible in Department HQ overview

---

## Section 3: C.R.E.E.D. Standalone as Live Lab + Public Dashboard

### Architecture

```
ARCHIE Platform (hub:3000)               C.R.E.E.D. Standalone (hub:8086)
┌─────────────────────┐                  ┌──────────────────────────┐
│ Department HQ       │                  │ Public Dashboard         │
│  └─ Roster (agents) │──── API ────────▶│  └─ Agent welfare stats  │
│  └─ Jobs (by dept)  │                  │  └─ Ethics compliance    │
│                     │                  │  └─ Governance scores    │
│ C.R.E.E.D. Tables   │                  │  └─ Live workload viz    │
│  └─ welfare data    │──── API ────────▶│  └─ Burnout detection    │
│  └─ ethics log      │                  │  └─ Decision audit trail │
│  └─ performance     │                  │                          │
│                     │                  │ Research / Programs      │
│ Dispatcher          │                  │  └─ How it works (docs)  │
│  └─ job outcomes    │──── API ────────▶│  └─ Live case studies    │
└─────────────────────┘                  └──────────────────────────┘
                                                    │
                                         creed-ai.org ──▶ links here
                                         kytranempowerment.com ──▶ links here
```

### Public Dashboard Data (Read-Only API)

Endpoint: `GET /api/creed/public-stats` (no auth, aggregate/anonymized)

- **Live agent count** — total, active, barracked (real numbers)
- **Welfare dashboard** — aggregate stress/fatigue/mood by department (not individual)
- **Ethics compliance score** — platform-wide C.R.E.E.D. grade (A+ to F)
- **Workload balance** — department load distribution visualization
- **Decision audit trail** — recent governance decisions (flagged, approved, denied)
- **Job health** — success rate, failure rate, recovery actions by department

### Benefits

1. **Live test subject** — welfare improvements tested against real production data
2. **Brand credibility** — creed-ai.org shows REAL metrics, not marketing copy
3. **Differentiation** — no other AI platform shows live governance dashboards
4. **Feedback loop** — visible problems force fixes

### Caching

- Standalone polls platform API every 5 minutes
- Caches locally so it doesn't depend on platform uptime
- Stale data shows "last updated X minutes ago" indicator

---

## Section 4: Roster Cleanup

### Cleanup Rules

| Action | Criteria |
|--------|----------|
| **Keep** | All acronym agents (directors + branded staff) |
| **Keep** | Human Lawyer, Human Doctor (specialized roles) |
| **Keep** | Any agent with dispatches in last 30 days |
| **Remove** | Generic human agents with 0 dispatches in 30+ days |
| **Remove** | Duplicate agents doing same job in same department |
| **Remove** | Agents with no skills, no department, no model assigned |
| **Barrack** | Agents that might be useful but aren't currently needed |

### Expected Result

- **Before:** 131 agents (66 active, 62 barracked, 3 winding down)
- **After:** ~60-70 total (50-55 active, 10-15 barracked reserve, 0 dead weight)

---

## Section 5: Job Centralization

### Current State (Scattered)

| Location | Jobs | Problems |
|----------|------|----------|
| `ai_bridge/agent_loop.py` | 17+ | Email, approvals, briefings — no department ownership |
| `security_network/jobs.py` | 20+ | Device tracking, DNS, compliance — V.I.G.I.L.'s domain but registered separately |
| `department_hq/jobs.py` | Some | Only partial — not all departments represented |
| Other module `jobs.py` | Unknown | Completely invisible to Department HQ |

### After: Department HQ Job Registry

ALL jobs registered through `department_hq/jobs.py`, organized by department:

```
Department HQ Job Registry
├── BRIDGE (A.R.C.H.I.E. — Executive)
│   ├── approvals — approval queue processing
│   ├── briefings — daily briefing generation
│   └── anomaly_detection — platform anomaly alerts
│
├── OPERATIONS (B.A.S.E.)
│   ├── stale_job_reaper — clean stuck jobs
│   ├── stuck_job_watchdog — detect hung processes
│   ├── ddns_monitor — public IP tracking
│   └── fleet_health — node heartbeat checks
│
├── ENGINEERING (F.O.R.G.E.)
│   ├── proactive_scan — code quality scanning (6h)
│   ├── dependency_audit — CVE checking (6h)
│   ├── code_health_audit — module audit pipeline
│   └── github_repo_analysis — repo health checks
│
├── SECURITY (V.I.G.I.L.)
│   ├── device_presence — ARP spoof detection (5m)
│   ├── dns_history — DNS change tracking (5m)
│   ├── traffic_stats — ntopng collection (5m)
│   ├── compliance_scan — STIG/CIS/HIPAA (6h)
│   ├── auto_remediation — fix compliance failures (6h)
│   ├── ssl_expiry — certificate monitoring (24h)
│   ├── threat_intel_sync — threat feed updates (6h)
│   ├── auto_block — block malicious IPs (15m)
│   ├── network_discovery — device scanning (5m)
│   └── camera_anomaly — motion detection (1h)
│
├── CREATIVE (M.U.S.E.)
│   └── (future: media generation queue, content scheduling)
│
├── DOCUMENTATION (C.O.D.E.X.)
│   ├── knowledge_auto_link — KB cross-linking
│   └── embedding_loop — vector embedding generation
│
├── SERVICES (R.E.S.O.L.V.E.)
│   ├── email_queue — outbound email processing
│   ├── email_inbox — inbound email checking
│   ├── telegram_notify — notification forwarding
│   └── email_analyze — AI email triage
│
├── ANALYTICS (S.P.E.C.T.R.A.)
│   ├── training_tick — agent training progression
│   └── skill_adaptation — skill refinement
│
├── HR (K.I.N.)
│   ├── crew_wellness — welfare threshold checks
│   ├── hr_tracker — shift/workload tracking
│   ├── idle_volunteering — idle agent task pickup
│   └── ethics_monitoring — C.R.E.E.D. compliance
│
└── FLEET (A.R.M.A.D.A.)
    ├── fleet_health — node online/offline detection
    └── model_state_save — persist loaded models (5m)
```

### Job Monitoring in Department HQ UI

- **Jobs Tab** in Department HQ — all jobs by department
- Per-job: status (running/failed/disabled), last run, failure count, error message
- Per-department: job health summary (X running, Y failed, Z disabled)
- One-click disable/enable per job
- Failure trend — "track_device_presence failed 120x in 24h" immediately visible
- Department director notified when their jobs fail repeatedly

### Cloud Contractor Escalation

- If a department's jobs fail 5+ times in an hour → dispatcher escalates to cloud models
- Department director agent gets welfare alert
- C.R.E.E.D. logs the escalation as a governance event
- Cloud usage tracked for cost reporting

---

## Section 6: LLM Lifecycle Management

### Model Loading Strategy

- **On-demand loading** — model loads when dispatcher needs it for a job
- **KEEP_ALIVE: 5m** — model unloads 5 minutes after last use (down from 24h)
- **RAM budget: 80% (102GB)** — before loading, check if budget allows; if not, evict LRU model
- **Always loaded:** `arctic-embed-cpu` (embeddings, 0.3GB) — essential for KB operations
- **Warm pool:** Top 2-3 most-dispatched models kept warm during business hours

### Model Assignment (from Roster)

Each agent's Roster entry specifies their model. Dispatcher reads this when assigning work:

```
Agent dispatched → Read agent.model_name from Roster
  → Is model loaded?
    → Yes: dispatch immediately
    → No: check RAM budget
      → Budget allows: load model, dispatch
      → Budget exceeded: evict LRU, load model, dispatch
      → Cannot evict (all active): queue job, retry in 60s
```

### Agent Academy Integration

- Academy A/B tests run benchmarks: same task, different models, compare quality
- Results stored per agent in `agent_benchmark_results`
- Best-performing model written to `agents.model_name` in Roster
- Periodic re-evaluation (monthly) to catch model improvements

---

## Implementation Order

### Phase 1: Immediate Relief (This Session)
- Reduce Ollama KEEP_ALIVE from 24h to 5m
- Fix/disable 3 broken jobs (track_device_presence, health_probe, email_inbox)
- Quick roster audit — identify removable agents

### Phase 2: Job Centralization (1-2 sessions)
- Move all job registrations to `department_hq/jobs.py`
- Add department ownership to `autonomy_loop_log`
- Build job monitoring view in Department HQ UI
- Remove old registration points (agent_loop.py, security_network/jobs.py, etc.)

### Phase 3: Roster Consolidation (1-2 sessions)
- Add `system_prompt` column to `agents` table
- Build Modelfile sync (DB → disk on save)
- Roster cleanup — remove dead agents
- Add C.R.E.E.D. badge to Roster cards
- Build `/api/agents/public-roster` endpoint

### Phase 4: C.R.E.E.D. Live Dashboard (1-2 sessions)
- Build `/api/creed/public-stats` on platform
- Update C.R.E.E.D. standalone to poll + display live data
- Add welfare dashboard, ethics scores, job health
- Connect creed-ai.org + kytranempowerment.com

### Phase 5: LLM Lifecycle + Academy (1-2 sessions)
- Implement RAM budget enforcer in dispatcher
- Model LRU eviction logic
- Academy benchmark → Roster model assignment pipeline
- Department-aware model warm pool

---

## Success Criteria

1. **One place to manage agents** — Roster Tab in Department HQ
2. **One place to monitor jobs** — Jobs view in Department HQ, organized by department
3. **Zero scattered registrations** — all jobs flow through department_hq/jobs.py
4. **RAM under control** — models load/unload within 80% budget, no swap pressure
5. **Visible failures** — broken jobs immediately obvious per department
6. **Live governance** — creed.kytranempowerment.com shows real agent welfare data
7. **Clean roster** — no dead weight agents, every agent has purpose + model + department
