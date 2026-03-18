# Multi-Agent Orchestration Frameworks vs ARCHIE

**Research Date**: 2026-03-16
**Purpose**: Compare leading multi-agent frameworks with ARCHIE's Bridge dispatch system to identify adoptable improvements.

---

## Framework Summaries

### 1. CrewAI
- **Architecture**: Role-based agent teams ("Crews") + event-driven workflows ("Flows"). Two complementary layers: Crews for autonomous collaboration, Flows for production control.
- **Agent Specialization**: Agents defined with `role`, `goal`, `backstory`. Each agent gets a persona and expertise domain. Tasks explicitly assigned to agents.
- **Task Routing**: Sequential or hierarchical process modes. Flows add `@start`, `@listen`, `@router` decorators for event-driven conditional branching (`or_`, `and_` logical operators).
- **Agent Communication**: Agents in a Crew share context and can delegate tasks to each other. Task outputs flow as context to downstream tasks.
- **Error Handling**: Task retry mechanisms, verbose logging. Crews support `max_retry_limit` per task. Flow routers enable conditional fallback paths.
- **Novel Patterns**: **Flows + Crews hybrid** — wrapping autonomous agent teams inside deterministic workflow graphs. Router-based conditional branching on agent output confidence.

### 2. Microsoft AutoGen
- **Architecture**: 3-layer design — Core API (message passing, event-driven, distributed runtime), AgentChat API (rapid prototyping), Extensions API (pluggable capabilities). Supports local AND distributed runtimes.
- **Agent Specialization**: Agents defined with `system_message` and `description`. `AgentTool` wraps agents as callable tools for other agents. Group chat patterns with speaker selection.
- **Task Routing**: Orchestrator agent delegates to specialist agents via `AgentTool`. Group chat with configurable speaker selection strategies (round-robin, auto, manual, custom function).
- **Agent Communication**: **Message-passing architecture** — agents communicate through typed messages on topics. Supports pub/sub patterns. Group chats enable multi-turn conversations between agents.
- **Error Handling**: `max_tool_iterations` limits. Termination conditions (text match, token limit, max messages). Core API supports distributed fault tolerance.
- **Novel Patterns**: **Agents-as-tools** — any agent can be wrapped as a tool for another agent, enabling hierarchical delegation. **Distributed runtime** — agents can run across processes/machines. Cross-language support (.NET + Python).

### 3. LangGraph
- **Architecture**: State machine / directed graph. Agents are **nodes**, communication is **edges**. State is explicitly managed and passed between nodes. Built for long-running, stateful workflows.
- **Agent Specialization**: Nodes can be any function or agent. Specialization via graph topology — different nodes handle different concerns.
- **Task Routing**: Conditional edges route between nodes based on state. Supports cycles (loops), branches, and parallel execution. Graph structure IS the routing logic.
- **Agent Communication**: Via shared **state object** passed through the graph. Each node reads/writes to state. Checkpointing enables persistence across failures.
- **Error Handling**: **Durable execution** — automatic resume from checkpoints after failures. Human-in-the-loop interrupts at any node. State rollback capabilities.
- **Novel Patterns**: **Checkpointed state graphs** — execution persists through crashes and can resume exactly where it left off. **Sub-graphs** — composable agent graphs that can be nested. Deep observability via LangSmith tracing.

### 4. MetaGPT
- **Architecture**: Software company simulation. Agents play organizational roles (Product Manager, Architect, Project Manager, Engineer). Core philosophy: `Code = SOP(Team)`.
- **Agent Specialization**: Predefined roles mimicking a software company hierarchy. Each role has structured output requirements (PRDs, design docs, code).
- **Task Routing**: **SOP-driven pipeline** — work flows through defined stages matching a real software development lifecycle. Output of each role is input to the next.
- **Agent Communication**: Structured artifacts (documents, schemas, code) passed between roles. Publish-subscribe message bus for inter-role communication.
- **Error Handling**: Role-based review cycles. Architect reviews PM output, Engineer reviews Architect output.
- **Novel Patterns**: **SOP materialization** — encoding real-world organizational processes as agent workflows. Structured intermediate artifacts as the communication medium rather than free-form messages.

### 5. OpenAI Swarm (now replaced by Agents SDK)
- **Architecture**: Minimal, educational framework. Two primitives only: **Agents** (instructions + functions) and **Handoffs** (agent-to-agent transfer). Stateless between calls.
- **Agent Specialization**: Each agent has `instructions` (system prompt) and `functions` (tools). Lightweight, function-level definition.
- **Task Routing**: Agents return other agents from functions to **hand off** conversations. Context variables persist across handoffs. Last handoff wins if multiple triggered.
- **Agent Communication**: Via **context_variables** dict shared across all agents. Agents read/write shared state. Conversation history carries across handoffs.
- **Error Handling**: Minimal — relies on the LLM's function calling. No built-in retry or escalation.
- **Novel Patterns**: **Function-based handoffs** — agents transfer control by returning another agent from a tool call. Extreme simplicity — entire orchestration in ~200 lines. **Context variable propagation** across agent boundaries.

---

## Comparison Table

| Feature | CrewAI | AutoGen | LangGraph | MetaGPT | Swarm | **ARCHIE** |
|---------|--------|---------|-----------|---------|-------|------------|
| **Architecture** | Crews + Flows | 3-layer (Core/AgentChat/Ext) | State graph (DAG) | SOP pipeline | Agents + Handoffs | Station-based dispatch |
| **Agent Definition** | Role/goal/backstory | System message + tools | Graph nodes | Org roles (PM/Arch/Eng) | Instructions + functions | DB-defined with model, capabilities, station |
| **Specialization** | YAML config per agent | AgentTool wrapping | Node function | Organizational hierarchy | Per-agent functions | Capability map → station → agent scoring |
| **Task Routing** | Sequential/hierarchical + Flow routers | Group chat speaker selection | Conditional edges on state | SOP stage pipeline | Function return handoff | `CAPABILITY_STATION_MAP` + multi-factor scoring |
| **Communication** | Shared task context | Message passing / pub-sub | Shared state object | Structured artifacts | Context variables | Bridge jobs + task_execution_log |
| **State Management** | Flow state (Pydantic) | Core runtime state | Checkpointed graph state | Document artifacts | Stateless (context_vars) | PostgreSQL (agents, jobs, welfare) |
| **Error Handling** | Task retry + flow routing | Max iterations + termination | Durable execution + checkpoints | Role-based review | Minimal | 5-step escalation chain |
| **Scalability** | Single process | Distributed runtime | Checkpoint-based persistence | Single process | Stateless client | Single Docker + cross-station assists |
| **Human-in-Loop** | Supported | Supported | First-class (interrupts) | Limited | None | Telegram approval (Tier 2) |
| **Observability** | Telemetry + verbose | AutoGen Studio GUI | LangSmith tracing | Logging | None | Bridge Command UI + audit logs |
| **Agent Welfare** | None | None | None | None | None | **IAAE governance, stress/energy tracking** |
| **GPU Awareness** | None | None | None | None | None | **VRAM-aware routing, model swap mgmt** |
| **Production Ready** | Yes (Flows) | Yes (Core API) | Yes | Experimental | No (educational) | Yes (running 24/7) |

---

## Which Framework Is Closest to ARCHIE?

**CrewAI** is the closest match to ARCHIE's approach:

1. **Station-based specialization** maps to CrewAI's role-based agent teams
2. **Capability routing** maps to CrewAI's task-to-agent assignment
3. Both separate "autonomous work" (Crews/dispatch) from "controlled workflows" (Flows/orchestration engine)
4. Both support sequential and delegated execution modes

However, ARCHIE is **more advanced** in several areas:
- GPU/VRAM-aware routing (no framework has this)
- Agent welfare tracking (IAAE governance is unique)
- Cross-station auxiliary dispatch (dynamic team composition)
- Persistent agent state in PostgreSQL (vs in-memory)
- 5-step escalation with cloud fallback

ARCHIE is **less advanced** in:
- No graph-based workflow definition (LangGraph's strength)
- No durable execution / checkpoint-resume (LangGraph)
- No agents-as-tools pattern (AutoGen)
- No structured inter-agent communication protocol (MetaGPT/AutoGen)
- No event-driven conditional routing in orchestration (CrewAI Flows)

---

## Top 5 Improvements ARCHIE Could Adopt

### 1. Durable Execution with Checkpointing (from LangGraph)

**What**: Save orchestration state at each pipeline step so multi-step jobs can resume after failures instead of restarting from scratch.

**Why**: ARCHIE's orchestration engine runs an 8-step pipeline (intent → IAAE → welfare → route → agent → GPU → execute → log). If step 6 fails due to GPU contention, the entire pipeline reruns. Checkpointing would let it resume from step 6.

**Implementation**:
- Add `orchestration_checkpoints` table: `(job_id, step_type, state_json, created_at)`
- Before each step in `OrchestrationEngine.orchestrate()`, save state
- On failure, check for existing checkpoint and resume from last successful step
- Garbage-collect checkpoints after job completion

**Effort**: Medium (2-3 days). Mostly DB schema + orchestration engine modifications.

---

### 2. Agents-as-Tools Pattern (from AutoGen)

**What**: Allow any ARCHIE agent to be invoked as a "tool" by another agent during execution, enabling hierarchical delegation within a single job.

**Why**: Currently, ARCHIE dispatches one agent per job. Complex tasks (e.g., "analyze this code and write documentation") would benefit from the Engineering agent calling the Creative agent mid-task, rather than requiring two separate Bridge jobs.

**Implementation**:
- Add `agent_tool_call` function to `bridge_dispatcher.py` that wraps `request_work()` as an Ollama tool definition
- When dispatching to an agent, include sibling agents' capabilities as available tools
- Agent's LLM response with tool calls triggers sub-dispatches
- Track parent-child job relationships in `bridge_jobs.metadata`

**Effort**: High (4-5 days). Requires Ollama tool-calling support verification, dispatcher recursion guards, and UI updates to show job trees.

---

### 3. Event-Driven Flow Router (from CrewAI Flows)

**What**: Add conditional routing in the orchestration pipeline based on intermediate results, enabling branching workflows instead of linear pipelines.

**Why**: ARCHIE's mission profiles (being designed) need this. Example: "If sentiment analysis returns negative, route to Communications station for response drafting; if positive, just log it." Currently, each decision point requires a separate Bridge job.

**Implementation**:
- Define `MissionProfile` class with steps, conditions, and branches (similar to CrewAI's `@router`)
- Add `mission_profiles` table: `(id, name, steps_json, trigger_conditions)`
- Orchestration engine evaluates conditions after each step to determine next step
- Reuse existing `CAPABILITY_STATION_MAP` for step routing

**Effort**: High (5-7 days). New subsystem, but builds on existing orchestration engine architecture.

---

### 4. Structured Inter-Agent Communication (from MetaGPT)

**What**: Define typed, structured output schemas for each station/capability so agents pass structured artifacts (not just raw text) between pipeline stages.

**Why**: When an Analytics agent classifies content and passes results to a Creative agent for writing, the handoff is currently unstructured text. Structured schemas (JSON with defined fields) would reduce misinterpretation and enable validation.

**Implementation**:
- Define `CapabilitySchema` per capability in `bridge_dispatcher.py`: `{"classify": {"labels": list, "confidence": float, "reasoning": str}}`
- Use Ollama's JSON mode (`format: "json"`) with schema enforcement
- Validate agent output against schema before passing to next stage
- Store structured outputs in `bridge_jobs.metadata` for downstream consumption

**Effort**: Medium (3-4 days). Schema definitions + JSON mode integration + validation layer.

---

### 5. Sub-Graph Composition / Nested Crews (from LangGraph + CrewAI)

**What**: Allow station teams to operate as composable sub-units that can be nested within larger workflows. A "Security Audit" mission could invoke the Security station crew as a sub-graph, then feed results to the Engineering station crew.

**Why**: ARCHIE's cross-station assists are currently ad-hoc (auxiliary slot). Formal composition would enable predefined multi-station workflows like "Full System Audit" = Security scan → Engineering fix → Operations deploy → Analytics verify.

**Implementation**:
- Add `workflow_templates` table: `(id, name, steps: [{station, capability, depends_on}])`
- `WorkflowExecutor` class that runs steps respecting dependency order
- Each step is a standard `dispatcher.request_work()` call
- Results from upstream steps injected as context to downstream steps
- Parallel execution for independent steps (no dependency)

**Effort**: Medium-High (4-5 days). Builds on existing dispatcher but needs dependency resolution and parallel execution.

---

## Effort Summary

| Improvement | Source Framework | Effort | Impact |
|-------------|-----------------|--------|--------|
| 1. Durable Execution + Checkpoints | LangGraph | 2-3 days | High — reliability for long jobs |
| 2. Agents-as-Tools | AutoGen | 4-5 days | High — enables complex single-job delegation |
| 3. Event-Driven Flow Router | CrewAI Flows | 5-7 days | High — unlocks mission profiles |
| 4. Structured Inter-Agent Schemas | MetaGPT | 3-4 days | Medium — better handoff quality |
| 5. Composable Station Workflows | LangGraph + CrewAI | 4-5 days | High — multi-station automation |

**Recommended priority order**: 1 → 4 → 3 → 5 → 2
(Start with reliability, then structured communication, then workflow capabilities)

---

## Key Insight

ARCHIE is already more sophisticated than most frameworks in **runtime concerns** (GPU awareness, agent welfare, model lifecycle management, persistent state). Where ARCHIE falls behind is in **workflow composition** — the ability to define complex multi-step, multi-agent workflows with branching, checkpointing, and structured handoffs. The five improvements above address exactly this gap, transforming ARCHIE from a capable single-dispatch system into a full workflow orchestration platform.

---

*Research conducted by analyzing GitHub READMEs and documentation for CrewAI, AutoGen, LangGraph, MetaGPT, and OpenAI Swarm, compared against ARCHIE's `bridge_dispatcher.py` and `orchestration_engine.py`.*
