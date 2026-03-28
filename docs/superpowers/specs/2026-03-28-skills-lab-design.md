# A.R.C.H.I.E. Skills Lab — Design Spec

**Date:** 2026-03-28
**Status:** Approved
**Scope:** 46+ branded skills across 3 tiers, platform-first architecture, adaptation pipeline, CLI integration

---

## Decisions Made

| Decision | Choice |
|----------|--------|
| Direction | Both — adaptation pipeline + original skills |
| Unique skills | All categories — agent, knowledge, self-healing, department |
| Skill source | Platform-first, CLI adapts (hub is source of truth) |
| Scope | All 3 tiers — 10 core + 20 adapted + 16 department = 46+ skills |
| Architecture | Skills stored in platform_skills table, served via API, executed via Bridge dispatch |

---

## Architecture

### Skill definition (platform_skills table)

```sql
CREATE TABLE platform_skills (
    id SERIAL PRIMARY KEY,
    skill_name VARCHAR(50) UNIQUE NOT NULL,
    display_name VARCHAR(100) NOT NULL,
    description TEXT NOT NULL,
    tier INTEGER NOT NULL,  -- 1=core, 2=adapted, 3=department
    department VARCHAR(100),
    agent_director VARCHAR(50),
    capability VARCHAR(50),
    prompt_template TEXT NOT NULL,
    system_prompt TEXT DEFAULT '',
    requires_file BOOLEAN DEFAULT false,
    requires_context BOOLEAN DEFAULT false,
    source VARCHAR(20) DEFAULT 'platform',  -- platform, github_adapted, department
    github_skill_id INTEGER REFERENCES github_skills(id),
    status VARCHAR(20) DEFAULT 'active',
    usage_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### Execution flow

```
User: /archie-fix "login crashes on submit"
  → Lookup skill "archie-fix" from platform_skills
  → Resolve: department=Engineering, capability=code, agent=F.O.R.G.E.
  → prompt = template.format(input=user_input, context=file_content)
  → Bridge dispatch: request_work(capability, prompt, module_id="skill_executor")
  → Agent generates response → return to user
```

### Two runtimes

| | Claude Code | A.R.C.H.I.E. CLI |
|---|---|---|
| Skill source | Hub API or local cache | Hub API (/api/skills/list) |
| Execution | Claude reads prompt, uses tools | CLI sends to Bridge via API gateway |
| LLM | Claude (cloud) | Local Ollama via agent |
| Agent selection | Bridge dispatcher | Bridge dispatcher (same) |

### API endpoints

```
GET  /api/skills/list           → all active skills with metadata
GET  /api/skills/{name}         → single skill definition
POST /api/skills/{name}/execute → execute skill via Bridge dispatch
GET  /api/skills/departments    → skills grouped by department
```

---

## Tier 1 — Core Branded Skills (10)

| Skill | Department | Director | Capability | What it does |
|-------|-----------|---------|-----------|-------------|
| /archie-fix | Engineering & Technology | F.O.R.G.E. | code | Dispatch bug fix with file context |
| /archie-review | Engineering & Technology | F.O.R.G.E. | code_review | Code review with quality analysis |
| /archie-secure | Security & Compliance | V.I.G.I.L. | vulnerability_scan | Security scan + recommendations |
| /archie-research | Research & Development | D.A.R.W.I.N. | research | KB-powered research with RAG context |
| /archie-audit | Engineering & Technology | F.O.R.G.E. | code_review | Run code health audit, show severity |
| /archie-repair | Engineering & Technology | F.O.R.G.E. | code | Trigger repair pipeline on findings |
| /archie-recall | Documentation & Knowledge | C.O.D.E.X. | knowledge_analysis | Semantic search + RAG across 19K KB entries |
| /archie-learn | Documentation & Knowledge | C.O.D.E.X. | knowledge_analysis | Store knowledge/decisions/mistakes to KB |
| /archie-health | Operations & Infrastructure | B.A.S.E. | monitoring | Platform health, agent status, fleet report |
| /archie-deploy | Operations & Infrastructure | B.A.S.E. | deployment | Safe deployment checklist + verification |

---

## Tier 2 — Adapted GitHub Skills (20)

| Skill | Source | Department | What it does |
|-------|--------|-----------|-------------|
| /archie-test | TDD skills | Engineering & Technology | Generate tests for code |
| /archie-refactor | refactoring | Engineering & Technology | Suggest refactoring improvements |
| /archie-debug | debugging | Engineering & Technology | Systematic debugging workflow |
| /archie-doc | documentation | Documentation & Knowledge | Generate docs for functions/modules |
| /archie-explain | code explanation | Documentation & Knowledge | Explain complex code clearly |
| /archie-optimize | performance | Engineering & Technology | Performance analysis + suggestions |
| /archie-translate | i18n | Creative & Design | Translate content/strings |
| /archie-summarize | summarization | Research & Development | Summarize docs/code/conversations |
| /archie-classify | classification | Analytics & Intelligence | Classify/categorize content |
| /archie-plan | planning | Engineering & Technology | Create implementation plans |
| /archie-commit | git | Engineering & Technology | Smart commit messages |
| /archie-pr | PR | Engineering & Technology | Draft PR descriptions |
| /archie-changelog | changelog | Documentation & Knowledge | Generate changelogs from commits |
| /archie-api | API design | Engineering & Technology | Generate/review API endpoints |
| /archie-schema | DB design | Engineering & Technology | Analyze/suggest DB schema changes |
| /archie-prompt | prompt engineering | Research & Development | Refine/optimize prompts |
| /archie-legal | compliance | Legal & Regulatory | Check license/compliance issues |
| /archie-estimate | estimation | Analytics & Intelligence | Estimate effort for tasks |
| /archie-monitor | monitoring | Operations & Infrastructure | Check service health/logs |
| /archie-backup | backup | Operations & Infrastructure | Trigger/verify backup status |

### Adaptation process
1. Read source GitHub skill content from KB
2. Extract core prompt/instructions
3. Wrap in A.R.C.H.I.E. template (department routing, agent assignment, branding)
4. Register in platform_skills with source='github_adapted'
5. Auto-assign to department agents

---

## Tier 3 — Department Director Skills (16)

One signature skill per AI Director — invokes full department capabilities.

| Skill | Director | What it does |
|-------|---------|-------------|
| /archie-command | A.R.C.H.I.E. | Executive orchestration — multi-agent tasks |
| /archie-ops | B.A.S.E. | Infrastructure operations — checks, restarts, resources |
| /archie-ship | C.A.R.G.O. | Logistics — track deployments, delivery pipelines |
| /archie-budget | L.E.D.G.E.R. | Cost analysis — tokens, API costs, resource budgets |
| /archie-build | F.O.R.G.E. | Full build pipeline — scaffold, implement, test, deploy |
| /archie-guard | V.I.G.I.L. | Security posture — compliance, threats, STIG checks |
| /archie-discover | D.A.R.W.I.N. | Deep research — multi-source investigation + synthesis |
| /archie-create | M.U.S.E. | Creative generation — images, designs, content concepts |
| /archie-broadcast | S.I.G.N.A.L. | Communications — announcements, social posts, newsletters |
| /archie-catalog | C.O.D.E.X. | Knowledge management — index, organize, cross-reference |
| /archie-support | R.E.S.O.L.V.E. | Customer support — responses, ticket analysis, FAQ |
| /archie-team | K.I.N. | Team management — agent welfare, shifts, training |
| /archie-diagnose | V.I.T.A.L. | System diagnostics — deep health, root cause analysis |
| /archie-comply | G.A.V.E.L. | Legal/regulatory — license, policy, compliance review |
| /archie-negotiate | A.C.C.O.R.D. | Diplomatic — proposals, comparisons, mediation |
| /archie-insight | S.P.E.C.T.R.A. | Analytics — data analysis, patterns, trend reports |

### Director skills vs Tier 1/2
- Tier 1/2: task-focused (do one thing)
- Tier 3: agent-focused (invoke Director's full capabilities, can orchestrate sub-agents)

---

## Adaptation Pipeline (Job #61)

New agent loop job — daily, processes github_skills with status='registered':
1. Read source skill content from KB
2. Match to department + capability using CAPABILITY_DEPARTMENT_MAP
3. Generate branded prompt template wrapping source instructions
4. Insert into platform_skills with source='github_adapted'
5. Update github_skills status to 'adapted'

---

## CLI Integration

### Hub skill loader (archie_engine/skills/hub_loader.py)

```python
def fetch_skills(hub_url):
    """Pull skill definitions from hub."""
    # GET /api/skills/list → cache locally

def execute_skill(skill_name, user_input, hub_url):
    """Execute skill via hub Bridge dispatch."""
    # POST /api/skills/{name}/execute → return response
```

### CLI skill picker
User types `/` → shows available skills pulled from hub. Select → executes via Bridge.

---

## Implementation Order

1. DB migration — create platform_skills table
2. Seed Tier 1 skills (10 core) with prompt templates
3. API endpoints — list, get, execute
4. Seed Tier 3 skills (16 department directors)
5. Adaptation pipeline (Job #61) — auto-convert 20 GitHub skills for Tier 2
6. CLI hub_loader integration
7. Usage tracking (increment usage_count on execute)
