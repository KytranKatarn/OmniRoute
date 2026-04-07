# Agent Expertise Panel — Design Spec

**Date:** 2026-04-05
**Project:** #221 — Agent-Driven Knowledge Intelligence Phase 2
**Task:** #1636 — Agent Expertise Panel — 4th dashboard panel
**Status:** Approved design, pending implementation

---

## Problem

The Consciousness Dashboard shows project-knowledge links, agent contributions (per expanded card), and knowledge gaps — but there's no way to see which agents are most knowledgeable about each project, or which agents *should* be working on a project based on their skills. When a new task needs dispatching, there's no data-driven recommendation for agent selection.

## Goals

1. **Show active contributors** — agents who have actually worked on each project (dispatch history).
2. **Recommend agents** — agents whose skills align with project needs but haven't contributed yet.
3. **4th standalone LCARS panel** — always visible in the Dashboard tab, not nested in card expand.
4. **Follow existing patterns** — same DOM-safe JS, LCARS CSS, dashboard_routes API structure.

---

## Data Sources

### 1. Dispatch History (Active Contributors)

```sql
SELECT agent_name, COUNT(*) as dispatches,
       COUNT(*) FILTER (WHERE status = 'completed') as successes
FROM bridge_jobs
WHERE project_id = :project_id AND agent_name IS NOT NULL
GROUP BY agent_name ORDER BY dispatches DESC
```

**Current state:** `project_id` column was just added (Task #1634). Auto-tagging will populate this over time. Panel gracefully handles empty state.

### 2. Skill Alignment (Recommended Agents)

```sql
SELECT a.id, a.name, a.display_name, a.department, a.is_department_ai,
       s.skill_name, s.skill_category, s.proficiency_level
FROM agent_skills s
JOIN agents a ON a.id = s.agent_id
WHERE a.shift_state IN ('active', 'barracked')
```

Match against project tags: if a project has tag "knowledge" and an agent has skill_category "knowledge" or skill_name containing "knowledge", that's a match. Score = sum of matching proficiency levels.

### 3. Department Relevance

Static mapping of project tags → departments:

| Tag keywords | Department |
|-------------|-----------|
| ui, css, lcars, design, layout | Creative & Design |
| knowledge, consciousness, dashboard | Documentation & Knowledge |
| auth, security, compliance | Security & Compliance |
| business, billing, commercial | Finance & Accounting |
| agents, automation, intelligence | Analytics & Intelligence |
| website, consolidation | Marketing & Communications |
| navigation, i18n | Engineering & Technology |

Agents in matching departments get a relevance boost.

---

## Scoring Algorithm

Each agent receives an **expertise score** (0-100) per project:

| Signal | Weight | Calculation |
|--------|--------|-------------|
| Dispatch history | 50% | `min(dispatches * 5, 50)` — caps at 10+ dispatches |
| Skill alignment | 35% | `min(sum_matched_proficiency * 7, 35)` — caps at 5 proficiency points |
| Department match | 15% | 15 if department matches project tags, 0 otherwise |

**Active Contributors** = agents with dispatch history (score uses all 3 signals)
**Recommended Agents** = agents with skill/department match but NO dispatch history (max score = 50)

Show top 5 active contributors + top 3 recommended per project.

---

## API Endpoint

### `GET /api/dashboard/agent-expertise`

**Query params:**
- `project_id` (optional) — filter to single project. If omitted, returns all active/planning projects.

**Response:**
```json
{
  "success": true,
  "projects": [
    {
      "project_id": 210,
      "name": "LCARS UI Consolidation",
      "contributors": [
        {
          "agent_name": "Pixel",
          "display_name": "Aiko Tanaka (Pixel)",
          "department": "Creative & Design",
          "is_director": false,
          "dispatches": 15,
          "successes": 12,
          "skill_score": 21,
          "dept_match": true,
          "expertise_score": 82
        }
      ],
      "recommended": [
        {
          "agent_name": "M.U.S.E.",
          "display_name": "M.U.S.E.",
          "department": "Creative & Design",
          "is_director": true,
          "matching_skills": ["UI Design", "Visual Design"],
          "skill_score": 28,
          "dept_match": true,
          "expertise_score": 43
        }
      ]
    }
  ]
}
```

---

## Service Layer

### New function in `knowledge_link_service.py`

`get_agent_expertise(project_id=None)` — returns the response structure above.

Steps:
1. Load all active/planning projects (or single project if ID provided)
2. For each project, query `bridge_jobs` for dispatch counts per agent
3. Load all agent skills + departments
4. For each project, compute tag→department mapping
5. Score each agent and split into contributors vs recommended
6. Return sorted results

### Performance

- Agent skills + departments cached at module level (same 5-min TTL pattern as project keywords)
- Tag→department mapping is static dict, no DB query
- bridge_jobs query per project (small result sets — grouped by agent_name)

---

## Dashboard Panel (4th Panel)

### HTML Structure

Inside `panel-dashboard`, after the Knowledge Gaps panel:

```html
<div class="lcars-frame purple" id="cs-agent-expertise-panel">
  <div class="frame-header">AGENT EXPERTISE</div>
  <div class="frame-body" id="cs-agent-expertise-body">
    <!-- Rendered by JS -->
  </div>
</div>
```

### JS Rendering

**Project selector:** Dropdown or clickable project list at top of panel. Selecting a project loads its expertise data.

**Two sections per project:**

1. **Active Contributors** — Table with columns: Agent, Department, Dispatches, Success Rate, Expertise Score. Score shown as colored bar (green 70+, yellow 40-69, red <40).

2. **Recommended Agents** — Compact cards showing: Agent name, department, matching skills (chips), potential score. "No dispatch history yet" label.

**Empty state:** "No dispatch data yet — expertise recommendations will improve as agents work on projects."

### CSS

- Reuse existing `cs-` prefix
- `.cs-expertise-project-selector` — project tabs/buttons
- `.cs-expertise-table` — contributor table (similar to `.cs-contrib-table`)
- `.cs-expertise-score-bar` — colored progress bar
- `.cs-recommended-card` — compact recommendation card
- `.cs-skill-chip` — small skill tag

---

## File Summary

| Action | File |
|--------|------|
| Modify | `platform_v2/services/knowledge_link_service.py` — add `get_agent_expertise()` + tag→dept mapping + skill cache |
| Modify | `platform_v2/tools/consciousness/dashboard_routes.py` — add agent-expertise endpoint |
| Modify | `platform_v2/static/js/consciousness-dashboard-v2.js` — add panel renderer + project selector |
| Modify | `platform_v2/static/css/consciousness-dashboard-v2.css` — add expertise panel styles |
| Modify | `platform_v2/tools/consciousness/templates/consciousness_dashboard.html` — add 4th LCARS frame |
