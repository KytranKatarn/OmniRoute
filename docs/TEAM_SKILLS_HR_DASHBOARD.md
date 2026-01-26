# Phase 17: Team Skills & HR Dashboard

**Created:** 2026-01-15
**Status:** Complete
**Location:** Team Management Module (`/tools/team-management/`)

---

## Overview

Phase 17 implements skill-based routing and HR analytics for A.R.C.H.I.E.'s Team Management system. This enables intelligent model selection based on agent skills and provides comprehensive HR metrics for monitoring team performance.

### Key Features

| Feature | Description |
|---------|-------------|
| **Skills Database** | 959 skill records across 75 agents |
| **Model-to-Skill Mapping** | 18 AI models mapped to their strengths |
| **Skills Matrix** | Visual agents x skills proficiency view |
| **HR Dashboard** | Model performance comparison & analytics |
| **Skill-Based Selection** | V2 Code Generation uses skills for routing |

---

## Database Schema

### agent_skills Table

```sql
CREATE TABLE agent_skills (
    id UUID PRIMARY KEY,
    agent_id INTEGER REFERENCES agents(id),
    skill_name VARCHAR(255) NOT NULL,
    skill_category VARCHAR(100),
    proficiency_level INTEGER CHECK (proficiency_level >= 1 AND proficiency_level <= 5),
    can_escalate_to INTEGER REFERENCES agents(id),
    notes TEXT,
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    UNIQUE (agent_id, skill_name)
);
```

**Proficiency Levels:**
- 5 = Expert
- 4 = Advanced
- 3 = Proficient
- 2 = Familiar
- 1 = Basic

### Statistics (as of 2026-01-15)

| Metric | Value |
|--------|-------|
| Total skill records | 959 |
| Agents with skills | 75 |
| Unique skills | 201 |
| Skill categories | 12 |

---

## Model-to-Skill Mappings

### Internal Models (FREE)

| Model | Primary Skills | Proficiency |
|-------|---------------|-------------|
| `qwen2.5-coder:7b` | python, quick_fixes, syntax_correction | 5 |
| `deepseek-coder-v2:16b` | architecture, algorithm_design, complex_reasoning | 5 |
| `deepseek-coder:33b` | system_design, refactoring, multi_file_changes | 5 |
| `codellama:latest` | simple_edits, quick_fixes, bug_fixing | 4-5 |
| `llama3.1:8b` | general_tasks, summarization, communication | 4 |

### Contractor Models (PAID)

| Model | Primary Skills | Proficiency |
|-------|---------------|-------------|
| `claude-sonnet-4-20250514` | security_analysis, api_design, documentation, technical_writing | 5 |
| `claude-opus-4-20250514` | architecture, complex_security, strategic_planning, technical_leadership | 5 |
| `gpt-4` / `gpt-4o` | analysis, creative_solutions, technical_writing | 5 |
| `grok-beta` | real_time_info, trend_analysis, creative_solutions | 4-5 |

---

## API Endpoints

### Skills Management

```
GET  /tools/team-management/api/skills
     Query params: category (optional)
     Returns: All skills with agent counts and proficiency stats

GET  /tools/team-management/api/skills/matrix
     Query params: category (optional)
     Returns: Agents x skills matrix for visual display

GET  /tools/team-management/api/skills/categories
     Returns: All categories with counts and task mappings

GET  /tools/team-management/api/skills/gaps
     Query params: threshold (default: 3)
     Returns: Skills with low coverage or low proficiency

GET  /tools/team-management/api/skills/recommendations
     Query params: task_type (optional)
     Returns: Best agents per category, internal vs contractor
```

### Agent Skills

```
GET  /tools/team-management/api/agents/<id>/skills
     Returns: All skills for a specific agent

POST /tools/team-management/api/agents/<id>/skills
     Body: { skill_name, proficiency_level, skill_category, notes }
     Returns: Created/updated skill

PUT  /tools/team-management/api/agents/<id>/skills/<skill_id>
     Body: { proficiency_level, skill_category, notes }
     Returns: Updated skill

DELETE /tools/team-management/api/agents/<id>/skills/<skill_id>
     Returns: Success message
```

### HR Dashboard

```
GET  /tools/team-management/api/hr/dashboard
     Returns: {
       agent_statistics: { total, internal, contractors, models },
       skill_statistics: { total_skills, agents_with_skills, categories },
       model_performance: [ { model, success_rate, tasks, cost_type } ],
       skills_by_category: [ { category, skill_count, agent_count } ],
       top_performers: [ { name, model, skill_count, avg_proficiency } ]
     }
```

---

## UI Components

### Skills Tab

**Location:** Team Management > SKILLS tab

Features:
- Skills list sorted by agent count
- Top skills chart (horizontal bar)
- Skill gaps warning panel
- Category filter dropdown
- Skills matrix modal (agents x skills grid)

### HR Dashboard Tab

**Location:** Team Management > HR DASHBOARD tab

Features:
- Agent statistics (total, internal, contractors)
- Model performance comparison with success rates
- Top performers leaderboard (by skill score)
- Skills by category distribution
- Skill-based recommendations (internal vs contractor)

---

## V2 Code Generation Integration

The V2 Code Generation Engine now uses skills for intelligent model selection:

```python
def _select_model_for_task(self, category: str, prefer_contractor: bool) -> str:
    """
    V2 Selection Strategy (Phase 17):
    1. Map category to required skills
    2. Query agent_skills for best matching agent
    3. Prefer internal agents (FREE) unless prefer_contractor=True
    4. Fall back to Team Management or default model
    """
```

### Category-to-Skills Mapping

| Category | Required Skills |
|----------|----------------|
| security | security_analysis, complex_security, code_review |
| performance | performance_optimization, algorithm_design, profiling |
| architecture | architecture, system_design, technical_leadership |
| database | database_optimization, sql, database_design |
| ui | javascript, frontend_development, ui_design |
| api | api_design, python, rest_api |
| code_quality | code_review, best_practices, syntax_correction |
| refactoring | refactoring, code_review, best_practices |

---

## Migration Script

**File:** `/mnt/archie_brain/database/migrations/012_populate_agent_skills.py`

The migration:
1. Maps 18 AI models to their inherent skill strengths
2. Extracts skills from agent capabilities (specialties, expertise)
3. Populates agent_skills table with proficiency levels

Run:
```bash
python3 /mnt/archie_brain/database/migrations/012_populate_agent_skills.py
```

Verify:
```bash
python3 /mnt/archie_brain/database/migrations/012_populate_agent_skills.py --verify
```

---

## Skill Categories

| Category | Skills | Description |
|----------|--------|-------------|
| security | 7 | Security analysis, penetration testing |
| development | 8 | Python, JavaScript, TypeScript, React |
| architecture | 6 | System design, API design, database design |
| code_quality | 7 | Code review, refactoring, best practices |
| performance | 4 | Optimization, profiling, algorithms |
| documentation | 3 | Technical writing, summarization |
| analysis | 4 | Complex reasoning, creative solutions |
| operations | 5 | DevOps, CI/CD, multi-file changes |
| communication | 2 | Customer service, call handling |
| business | 6 | Marketing, sales, finance, compliance |
| general | 155+ | Various agent-specific skills |
| specialized | 4 | Multilingual, translation, uncensored |

---

## Success Criteria

- [x] `agent_skills` table populated with 500+ records (achieved: 959)
- [x] Skills tab functional in Team Management UI
- [x] Skills matrix view shows agents x skills with proficiency
- [x] HR Dashboard shows model performance comparison
- [x] V2 code generation uses skills for model selection
- [x] Skill gaps identified and displayed
- [x] Top performers tracked by skill score

---

## Related Documentation

- `/docs/CODE_GENERATION_ENGINE_V2.md` - V2 Engine documentation
- `/docs/AGENT_DELEGATION_SYSTEM.md` - Team Management system
- `/docs/MASTER_STATUS_AND_ROADMAP_2026.md` - Project roadmap
- `/docs/IMPROVEMENTS_LAB_WORKFLOW.md` - Full improvement workflow

---

## Changelog

### v1.0.0 (2026-01-15)
- Initial implementation of Phase 17
- Created agent_skills migration (959 records)
- Added 8 Skills API endpoints
- Added Skills tab to Team Management UI
- Added HR Dashboard tab with model comparison
- Integrated skills with V2 code generation
- Updated A.R.C.H.I.E. Blueprints with Phase 16/17

---

**Document Status:** Active
**Last Updated:** 2026-01-15
