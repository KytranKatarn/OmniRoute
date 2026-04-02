# Department HQ Coordination System — Design Spec

**Date:** 2026-04-02
**Project:** #215 Context Engineering + Department HQ Migration
**Decision:** #369 (Consciousness fixes), #370 (Agent benchmarks)
**Status:** Design — pending implementation plan

---

## Problem Statement

The platform has three disconnected systems that should be one:
- **AI Bridge** (622K across 4 files) handles dispatch, model loading, routing, job lifecycle
- **Department HQ** manages agents, skills, departments but has no coordination
- **Autonomy** runs loops that compete for Ollama resources with no traffic management

Result: agents get budget-exhausted, models fight for RAM (117.9GB on 128GB), consciousness loops timeout, and the crew coordination that worked in Starbase's manifest tab was lost during the department reorg.

## Architecture

### Three Systems, Clean Separation

```
Autonomy Module — WHEN things run
  └── agent_loop.py (58+ scheduled jobs)
  └── Triggers jobs on intervals
  └── Calls: dept_coordinator.request_agent(capability)

Department HQ — WHO does WHAT, with WHICH model, on WHICH hardware
  └── Services:
      ├── agent_service.py        — Agent CRUD, skills, shifts (exists)
      ├── department_coordinator.py — Scheduling, admission control, resource mgmt (NEW)
      ├── model_service.py        — Warmboot, load/unload, RAM tracking, eviction (NEW)
      └── dispatch_service.py     — LLM execution, job lifecycle (NEW)
  └── Routes:
      ├── roster_routes.py        — Agent roster + live model/job status (enhanced)
      ├── model_routes.py         — Model control UI (exists)
      ├── skill_routes.py         — Skill management (exists)
      └── work_routes.py          — Job tracking, performance (exists)

Starbase Command — WHAT hardware is available
  └── Fleet nodes, mesh network, hardware resources only
  └── No agent management, no model management
```

### What Moves Where

| Responsibility | Currently In | Moves To |
|---------------|-------------|----------|
| Agent selection & scoring | bridge_dispatcher.py | dept_coordinator.py |
| Model warmboot/load/unload | bridge_dispatcher.py | model_service.py |
| RAM budget & eviction | bridge_dispatcher.py | model_service.py |
| Hardware tier routing | smart_router.py | model_service.py |
| Job create/track/complete | bridge_dispatcher.py | dispatch_service.py |
| LLM call execution | archie_bridge.py | dispatch_service.py |
| Intent parsing | orchestration_engine.py | dispatch_service.py |
| Agent budget tracking | bridge_dispatcher.py | dept_coordinator.py |
| Crew manifest cache | bridge_dispatcher.py | dept_coordinator.py |
| Fleet node dispatch | bridge_dispatcher.py | Starbase (hardware routing only) |

### What Stays as Utilities

The `ai_bridge/` directory becomes standalone tools that agents USE (not agent management):

| File | Purpose | Status |
|------|---------|--------|
| embedding_service.py | Vector generation (arctic-embed-cpu) | Stays as utility |
| knowledge_analyzer.py | Knowledge extraction from content | Stays as utility |
| knowledge_cards.py | Card storage | Stays as utility |
| telegram_gateway.py | Notifications | Stays as utility |
| consciousness_scheduler.py | Legacy scheduler functions | Retire gradually |
| comfyui_service.py | Image generation | Stays as utility |
| voice_synthesis.py | Audio generation | Stays as utility |
| semantic_search.py | Search functions | Stays as utility |

### Files Retired (absorbed into Department HQ)

| File | Size | Absorbed By |
|------|------|-------------|
| archie_bridge.py | 164K | dispatch_service.py |
| bridge_dispatcher.py | 316K | dept_coordinator.py + model_service.py + dispatch_service.py |
| orchestration_engine.py | 106K | dispatch_service.py |
| smart_router.py | 36K | model_service.py |

---

## New Services

### 1. department_coordinator.py — The Traffic Cop + Shift Manager

**Proactive scheduling (shift manager):**
- Track agent shift states: active, busy, resting, off-duty
- Stagger consciousness loops based on resource availability
- Pre-load models for scheduled work (predictable loops)
- Reset agent budgets on schedule

**Reactive coordination (traffic cop):**
- `request_agent(capability, module_source, priority)` — find best available agent
- Check resource capacity before admitting a job
- Reserve agent (prevent double-booking)
- Queue jobs when resources are insufficient
- `release_agent(agent_id, job_id)` — free agent, trigger queued work

**Resource awareness:**
- Query Ollama `/api/ps` for loaded models + RAM
- Track which agents have active jobs (prevent eviction mid-job)
- Admission control: can this job run without destabilizing the system?

```python
class DepartmentCoordinator:
    def request_agent(self, capability, module_source, priority='normal'):
        """Main entry point — Autonomy and all callers use this."""
        # 1. Check resource capacity
        capacity = self.model_service.check_capacity()
        
        # 2. Find best agent with required skill
        agent = self._find_best_agent(capability, priority)
        if not agent:
            return QueuedResult(reason="no agent available")
        
        # 3. Ensure model is loaded
        ready = self.model_service.ensure_ready(agent.model, capacity)
        if not ready:
            return QueuedResult(reason="insufficient resources")
        
        # 4. Reserve agent
        self._reserve_agent(agent.id)
        
        return Assignment(agent_id=agent.id, model=agent.model, host=ready.host)
    
    def release_agent(self, agent_id, job_result):
        """Called when job completes — frees agent, triggers queue."""
        self._unreserve_agent(agent_id)
        self._process_queue()  # start next waiting job if capacity exists
```

### 2. model_service.py — Model Lifecycle Manager

**Moved from bridge_dispatcher.py:**
- `ensure_ready(model, capacity)` — 3-tier check (GPU/CPU/cold), warmboot
- `load_model(model, host)` — Ollama keep_alive=24h
- `unload_model(model, host)` — Ollama keep_alive=0
- `save_model_state()` / `restore_model_state()` — persist across restarts

**New — eviction cascade:**
```python
def ensure_capacity(self, needed_gb):
    """Free RAM using 3-step cascade."""
    available = self.get_available_ram()
    if available >= needed_gb:
        return True
    
    # Step 1: Evict idle models (no active jobs)
    idle = self.get_idle_models()
    for model in idle:
        self.unload_model(model)
        if self.get_available_ram() >= needed_gb:
            return True
    
    # Step 2: Evict lowest priority models
    low_priority = self.get_models_by_priority(ascending=True)
    for model in low_priority:
        if not self.has_active_job(model):
            self.unload_model(model)
            if self.get_available_ram() >= needed_gb:
                return True
    
    # Step 3: Queue — can't free enough without killing active work
    return False

def get_model_priority(self, model):
    """Priority ranking for eviction decisions."""
    if self.has_active_job(model):
        return PROTECTED  # never evict
    if model in CONSCIOUSNESS_MODELS:
        return HIGH  # arctic-embed, mistral for analysis
    if self.last_used_within(model, hours=1):
        return MEDIUM
    return LOW  # eviction candidate
```

### 3. dispatch_service.py — LLM Execution

**Simplified — just executes:**
```python
def dispatch(self, assignment, prompt, options=None):
    """Execute LLM call on assigned agent's model."""
    # Assignment comes from department_coordinator
    response = self._call_ollama(
        model=assignment.model,
        prompt=prompt,
        host=assignment.host,
        options=options
    )
    
    # Report completion
    self.coordinator.release_agent(assignment.agent_id, response)
    
    return response
```

No agent selection, no model loading, no routing — all handled by coordinator.

---

## Autonomy Integration

### How Loops Call Department HQ

Current (broken):
```python
# processing_routes.py
dispatcher = get_dispatcher()
job_id = dispatcher.create_job(capability='embedding', ...)
# → dispatcher caches skills, picks agent, may timeout
```

New:
```python
# processing_routes.py  
from services.department_coordinator import get_coordinator

coordinator = get_coordinator()
assignment = coordinator.request_agent('embedding', 'consciousness', priority='high')

if assignment.queued:
    logger.info(f"[ServerLoop] embedding queued — waiting for capacity")
    return  # will be retriggered when resources free up

# Execute with assigned agent
result = coordinator.dispatch(assignment, items)
# → coordinator handles model loading, execution, agent release
```

### Loop Scheduling

Department HQ coordinator manages loop admission:

```
Embedding loop fires → coordinator.request_agent('embedding')
  → Checks: Ollama has 2GB free? arctic-embed-cpu loaded?
  → Yes: proceed, reserve SPECTRA
  → No: queue, wait for current analysis job to finish

Analysis loop fires → coordinator.request_agent('knowledge_analysis')  
  → Checks: mistral:7b loaded? DARWIN available?
  → Yes: proceed, reserve DARWIN
  → No: DARWIN busy → try CODEX → try Oracle → queue if all busy

Translate loop fires → coordinator.request_agent('translate')
  → Checks: agent available? model loaded?
  → Yes: proceed, reserve Polyglot
  → No: queue behind higher priority work
```

---

## UI Enhancement — Agents Tab

The existing Agents tab in Department HQ gets enhanced with live status:

**Per-agent card shows:**
- Agent name, department, skills (exists)
- **Model status**: loaded/cold/warmbooting (NEW)
- **Current job**: what they're working on right now (NEW)  
- **RAM usage**: how much their model consumes (NEW)
- **Budget**: tasks today / daily limit (NEW)
- **Queue depth**: jobs waiting for this agent (NEW)

**Dashboard header shows:**
- Total Ollama RAM: used / available
- Active jobs count
- Queued jobs count
- Models loaded count

---

## Migration Strategy — Incremental Phases

### Phase 1: Build New Services (no breaking changes)
- Create `department_coordinator.py` with `request_agent()` / `release_agent()`
- Create `model_service.py` with eviction cascade
- Create `dispatch_service.py` with simplified LLM execution
- All three call existing dispatcher functions internally (wrapper approach)
- Consciousness loops updated to call coordinator instead of dispatcher directly
- **Test**: all 3 consciousness loops work through new coordinator

### Phase 2: Move Logic Out of Dispatcher
- Move warmboot/load/unload from `bridge_dispatcher.py` → `model_service.py`
- Move agent selection/scoring from `bridge_dispatcher.py` → `department_coordinator.py`
- Move job CRUD from `bridge_dispatcher.py` → `dispatch_service.py`
- `bridge_dispatcher.py` becomes a thin wrapper calling Department HQ services
- **Test**: all existing dispatch callers still work

### Phase 3: Retire Old Files
- Merge `archie_bridge.py` + `orchestration_engine.py` + `smart_router.py` into `dispatch_service.py`
- `bridge_dispatcher.py` retired (all logic now in Department HQ)
- `ai_bridge/` directory becomes utilities-only (embedding, knowledge, telegram, etc.)
- **Test**: full platform regression

### Phase 4: UI Enhancement
- Enhance Agents tab with live model/job/RAM status
- Remove crew/manifest from Starbase (replaced by Department HQ)
- **Test**: browser verification of live status updates

---

## Success Criteria

1. No more agent budget exhaustion (coordinator prevents over-assignment)
2. No more model contention timeouts (resource-aware admission control)
3. No more silent loop failures (coordinator queues instead of failing)
4. All 3 consciousness loops run smoothly without competing
5. Single module (Department HQ) owns all agent + model + dispatch logic
6. Starbase only manages fleet hardware
7. Autonomy only triggers jobs — doesn't decide who/how

---

## Risks

1. **316K dispatcher refactor** — incremental phases mitigate this
2. **Breaking existing callers** — Phase 1 wraps existing code, no breaking changes
3. **Performance** — coordinator adds a layer; keep it fast (in-memory cache + DB fallback)
4. **Model eviction wrong** — eviction cascade protects active jobs; worst case is queuing

---

## Out of Scope

- AI Bridge + Dispatcher full merge (Phase 3 — separate implementation cycle)
- Fleet node dispatch redesign (Starbase keeps this)
- Agent Academy integration (works independently, feeds skills to Department HQ)
- Consciousness module changes beyond calling coordinator instead of dispatcher
