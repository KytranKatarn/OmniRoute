# Agent Expertise Panel — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a 4th LCARS panel to the Consciousness Dashboard showing active contributors and recommended agents per project, scored by dispatch history + skill alignment + department relevance.

**Architecture:** New `get_agent_expertise()` service function queries bridge_jobs + agent_skills + agents, computes expertise scores per project, returns contributors + recommended agents. New API endpoint exposes it. JS renders a standalone panel with project selector, contributor table, and recommendation cards.

**Tech Stack:** Python (Flask, psycopg2), PostgreSQL, vanilla JS (DOM-safe), CSS (LCARS).

**Spec:** `docs/superpowers/specs/2026-04-05-agent-expertise-panel-design.md`

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `platform_v2/services/knowledge_link_service.py` | Add `get_agent_expertise()`, tag→dept mapping, skill cache |
| Modify | `platform_v2/tools/consciousness/dashboard_routes.py` | Add `/api/dashboard/agent-expertise` endpoint |
| Modify | `platform_v2/static/js/consciousness-dashboard-v2.js` | Add expertise panel renderer + project selector |
| Modify | `platform_v2/static/css/consciousness-dashboard-v2.css` | Add expertise panel styles |
| Modify | `platform_v2/tools/consciousness/templates/consciousness_dashboard.html` | Add 4th LCARS frame |

---

### Task 1: Service Function — `get_agent_expertise()`

**Files:**
- Modify: `platform_v2/services/knowledge_link_service.py`

- [ ] **Step 1: Add tag→department mapping and skill cache constants**

At the top of `knowledge_link_service.py`, after the existing constants (after `GAP_WEIGHTS`), add:

```python
# --- Agent Expertise ---
TAG_TO_DEPARTMENT = {
    "ui": "Creative & Design",
    "css": "Creative & Design",
    "lcars": "Creative & Design",
    "design": "Creative & Design",
    "layout": "Creative & Design",
    "knowledge": "Documentation & Knowledge",
    "consciousness": "Documentation & Knowledge",
    "dashboard": "Documentation & Knowledge",
    "auth": "Security & Compliance",
    "security": "Security & Compliance",
    "compliance": "Security & Compliance",
    "business": "Finance & Accounting",
    "billing": "Finance & Accounting",
    "commercial": "Finance & Accounting",
    "agents": "Analytics & Intelligence",
    "automation": "Analytics & Intelligence",
    "intelligence": "Analytics & Intelligence",
    "analytics": "Analytics & Intelligence",
    "website": "Marketing & Communications",
    "consolidation": "Marketing & Communications",
    "navigation": "Engineering & Technology",
    "i18n": "Engineering & Technology",
    "engineering": "Engineering & Technology",
}

_agent_skill_cache: Dict = {}
_agent_skill_cache_time: float = 0
_AGENT_SKILL_CACHE_TTL = 300  # 5 minutes
```

- [ ] **Step 2: Add `_load_agent_skills()` cached loader**

Add after the cache constants:

```python
import time as _time


def _load_agent_skills() -> Dict:
    """Load all agent skills + department info, cached for 5 minutes.

    Returns {agent_name: {display_name, department, is_director, skills: [{skill_name, skill_category, proficiency_level}]}}
    """
    global _agent_skill_cache, _agent_skill_cache_time

    now = _time.time()
    if now - _agent_skill_cache_time < _AGENT_SKILL_CACHE_TTL and _agent_skill_cache:
        return _agent_skill_cache

    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT a.id, a.name, a.display_name, a.department, a.is_department_ai
                   FROM agents a
                   WHERE a.shift_state IN ('active', 'barracked')"""
            )
            agents = {row["name"]: {
                "display_name": row["display_name"] or row["name"],
                "department": row["department"] or "",
                "is_director": bool(row["is_department_ai"]),
                "skills": [],
            } for row in cur.fetchall()}

            cur.execute(
                """SELECT a.name, s.skill_name, s.skill_category, s.proficiency_level
                   FROM agent_skills s
                   JOIN agents a ON a.id = s.agent_id
                   WHERE a.shift_state IN ('active', 'barracked')"""
            )
            for row in cur.fetchall():
                agent_name = row["name"]
                if agent_name in agents:
                    agents[agent_name]["skills"].append({
                        "skill_name": row["skill_name"],
                        "skill_category": row["skill_category"] or "",
                        "proficiency_level": row["proficiency_level"] or 1,
                    })

        _agent_skill_cache = agents
        _agent_skill_cache_time = now
        return agents
    except Exception as e:
        logger.error("[AgentExpertise] _load_agent_skills failed: %s", e)
        return _agent_skill_cache or {}
```

- [ ] **Step 3: Add `_compute_expertise_score()` helper**

Add after `_load_agent_skills()`:

```python
def _compute_expertise_score(
    dispatches: int, successes: int,
    agent_info: Dict, project_tags: list
) -> Dict:
    """Compute expertise score (0-100) from 3 signals.

    Dispatch history: 50% weight, caps at 10 dispatches.
    Skill alignment: 35% weight, sum of matching proficiency levels, caps at 5 points.
    Department match: 15% weight, binary match against project tags.
    """
    # Dispatch score (0-50)
    dispatch_score = min(dispatches * 5, 50)

    # Skill alignment score (0-35)
    skill_score = 0
    matching_skills = []
    tags_lower = [t.lower() for t in (project_tags or [])]
    for skill in agent_info.get("skills", []):
        skill_name_lower = (skill["skill_name"] or "").lower()
        skill_cat_lower = (skill["skill_category"] or "").lower()
        matched = False
        for tag in tags_lower:
            if tag in skill_name_lower or tag in skill_cat_lower or skill_name_lower in tag:
                matched = True
                break
        if matched:
            skill_score += skill["proficiency_level"]
            matching_skills.append(skill["skill_name"])
    skill_score = min(skill_score * 7, 35)

    # Department match score (0-15)
    dept_match = False
    agent_dept = agent_info.get("department", "")
    for tag in tags_lower:
        if TAG_TO_DEPARTMENT.get(tag) == agent_dept:
            dept_match = True
            break
    dept_score = 15 if dept_match else 0

    total = dispatch_score + skill_score + dept_score

    return {
        "dispatches": dispatches,
        "successes": successes,
        "skill_score": skill_score,
        "dept_match": dept_match,
        "matching_skills": matching_skills,
        "expertise_score": total,
    }
```

- [ ] **Step 4: Add `get_agent_expertise()` main function**

Add after `_compute_expertise_score()`:

```python
def get_agent_expertise(project_id: Optional[int] = None) -> List[Dict]:
    """Get agent expertise data per project — active contributors + recommended agents.

    Args:
        project_id: Optional single project filter. If None, returns all active/planning projects.

    Returns:
        List of {project_id, name, contributors: [...], recommended: [...]}
    """
    try:
        # Get projects
        with get_db_cursor() as (conn, cur):
            if project_id:
                cur.execute(
                    "SELECT id, name, tags FROM unified_projects WHERE id = %s",
                    (project_id,),
                )
            else:
                cur.execute(
                    "SELECT id, name, tags FROM unified_projects WHERE status IN ('active', 'planning') ORDER BY priority DESC"
                )
            projects = cur.fetchall()

        if not projects:
            return []

        # Load agent skills (cached)
        all_agents = _load_agent_skills()

        results = []
        for proj in projects:
            pid = proj["id"]
            pname = proj["name"]
            ptags = proj["tags"] if isinstance(proj["tags"], list) else []

            # Get dispatch history for this project
            dispatch_data = {}
            try:
                with get_db_cursor() as (conn, cur):
                    cur.execute(
                        """SELECT agent_name, COUNT(*) as dispatches,
                                  COUNT(*) FILTER (WHERE status = 'completed') as successes
                           FROM bridge_jobs
                           WHERE project_id = %s AND agent_name IS NOT NULL
                           GROUP BY agent_name
                           ORDER BY dispatches DESC""",
                        (pid,),
                    )
                    for row in cur.fetchall():
                        dispatch_data[row["agent_name"]] = {
                            "dispatches": row["dispatches"],
                            "successes": row["successes"],
                        }
            except Exception:
                pass

            contributors = []
            recommended = []

            for agent_name, agent_info in all_agents.items():
                disp = dispatch_data.get(agent_name, {})
                dispatches = disp.get("dispatches", 0)
                successes = disp.get("successes", 0)

                score_data = _compute_expertise_score(dispatches, successes, agent_info, ptags)

                if score_data["expertise_score"] == 0:
                    continue

                entry = {
                    "agent_name": agent_name,
                    "display_name": agent_info["display_name"],
                    "department": agent_info["department"],
                    "is_director": agent_info["is_director"],
                    **score_data,
                }

                if dispatches > 0:
                    contributors.append(entry)
                else:
                    recommended.append(entry)

            contributors.sort(key=lambda x: x["expertise_score"], reverse=True)
            recommended.sort(key=lambda x: x["expertise_score"], reverse=True)

            results.append({
                "project_id": pid,
                "name": pname,
                "contributors": contributors[:5],
                "recommended": recommended[:3],
            })

        return results

    except Exception as e:
        logger.error("[AgentExpertise] get_agent_expertise failed: %s", e)
        return []
```

- [ ] **Step 5: Verify syntax**

```bash
docker exec archie_platform python3 -c "import ast; ast.parse(open('/app/services/knowledge_link_service.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add platform_v2/services/knowledge_link_service.py
git commit -m "feat: add get_agent_expertise() with 3-signal scoring (dispatch+skills+dept)"
```

---

### Task 2: API Endpoint

**Files:**
- Modify: `platform_v2/tools/consciousness/dashboard_routes.py`

- [ ] **Step 1: Add agent-expertise route**

Inside the `register_dashboard_routes(bp, admin_required)` function, after the `api_generate_docs` route (at the end of the function), add:

```python
    @bp.route("/api/dashboard/agent-expertise")
    @login_required
    @admin_required
    def api_agent_expertise():
        """Get agent expertise scores per project — contributors + recommendations."""
        from services.knowledge_link_service import get_agent_expertise

        project_id = request.args.get("project_id", type=int)
        projects = get_agent_expertise(project_id=project_id)
        return jsonify({"success": True, "projects": projects})
```

- [ ] **Step 2: Verify syntax**

```bash
docker exec archie_platform python3 -c "import ast; ast.parse(open('/app/tools/consciousness/dashboard_routes.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/consciousness/dashboard_routes.py
git commit -m "feat: add /api/dashboard/agent-expertise endpoint"
```

---

### Task 3: Dashboard HTML — 4th LCARS Frame

**Files:**
- Modify: `platform_v2/tools/consciousness/templates/consciousness_dashboard.html`

- [ ] **Step 1: Add 4th LCARS frame after Knowledge Gaps panel**

Find the closing `</div>` of the Knowledge Gaps panel (the `</div>` after `id="cs-knowledge-gaps-body"`'s parent frame). The Knowledge Gaps panel ends around line 2783. Right after it (before the `</div>` that closes `panel-dashboard`), add:

```html
            <!-- Agent Expertise -->
            <div style="--frame-color: #8b5cf6; --frame-rgb: 139,92,246; margin-bottom: 20px;">
              <div class="lcars-frame">
                <div class="lcars-sidebar">
                  <div style="background:#8b5cf6;flex:2;border-radius:8px 0 0 0"></div>
                  <div style="background:#6d28d9;flex:1"></div>
                  <div style="background:#8b5cf6;flex:1;border-radius:0 0 0 8px"></div>
                </div>
                <div class="lcars-content">
                  <div class="lcars-bar" style="background:#8b5cf6">
                    <span class="lcars-bar-text">AGENT EXPERTISE</span>
                  </div>
                  <div class="lcars-body">
                    <div class="cs-expertise-project-tabs" id="cs-expertise-project-tabs"></div>
                    <div id="cs-agent-expertise-body">
                      <p style="color:#94a3b8">Loading agent expertise...</p>
                    </div>
                  </div>
                  <div class="lcars-footer-bar" style="background:#8b5cf6"></div>
                </div>
              </div>
            </div>
```

The exact insertion point is after this block:

```html
                  <div class="lcars-footer-bar" style="background:#8b5cf6"></div>
                </div>
              </div>
            </div>

        </div>
```

Insert BEFORE the `</div>` that closes `panel-dashboard` (the one with the blank line before `<!-- ════════`).

- [ ] **Step 2: Verify the template renders**

```bash
docker compose restart archie_platform && sleep 3 && docker logs --tail 5 archie_platform
```

Expected: No template errors in logs.

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/consciousness/templates/consciousness_dashboard.html
git commit -m "feat: add Agent Expertise LCARS frame to consciousness dashboard"
```

---

### Task 4: CSS Styles

**Files:**
- Modify: `platform_v2/static/css/consciousness-dashboard-v2.css`

- [ ] **Step 1: Add expertise panel styles**

At the end of `consciousness-dashboard-v2.css` (before the `@media` queries), add:

```css
/* --- Agent Expertise Panel --- */

.cs-expertise-project-tabs {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
    margin-bottom: 16px;
}

.cs-expertise-tab {
    padding: 4px 12px;
    border-radius: 4px;
    border: 1px solid rgba(139, 92, 246, 0.3);
    background: transparent;
    color: #94a3b8;
    cursor: pointer;
    font-size: 0.75rem;
    font-family: 'Antonio', sans-serif;
    text-transform: uppercase;
    transition: all 0.2s;
}

.cs-expertise-tab.active {
    background: rgba(139, 92, 246, 0.2);
    color: #8b5cf6;
    border-color: #8b5cf6;
}

.cs-expertise-tab:hover:not(.active) {
    border-color: rgba(139, 92, 246, 0.5);
    color: #cbd5e1;
}

.cs-expertise-section-title {
    font-family: 'Antonio', sans-serif;
    font-size: 0.85rem;
    color: #8b5cf6;
    text-transform: uppercase;
    margin: 16px 0 8px 0;
    letter-spacing: 0.5px;
}

.cs-expertise-section-title:first-child {
    margin-top: 0;
}

.cs-expertise-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.85rem;
    margin-bottom: 12px;
}

.cs-expertise-table th {
    text-align: left;
    padding: 8px 12px;
    color: #8b5cf6;
    font-family: 'Antonio', sans-serif;
    text-transform: uppercase;
    font-size: 0.8rem;
    border-bottom: 1px solid rgba(139, 92, 246, 0.25);
}

.cs-expertise-table td {
    padding: 8px 12px;
    color: #cbd5e1;
    border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

.cs-expertise-score-bar {
    display: inline-block;
    width: 60px;
    height: 6px;
    background: rgba(255, 255, 255, 0.1);
    border-radius: 3px;
    overflow: hidden;
    vertical-align: middle;
    margin-right: 6px;
}

.cs-expertise-score-fill {
    height: 100%;
    border-radius: 3px;
    transition: width 0.4s ease;
}

.cs-expertise-score-fill.high { background: #10b981; }
.cs-expertise-score-fill.mid { background: #fbbf24; }
.cs-expertise-score-fill.low { background: #ef4444; }

.cs-expertise-score-num {
    font-size: 0.8rem;
    font-weight: 600;
    color: #e2e8f0;
}

.cs-recommended-card {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 10px 12px;
    background: rgba(139, 92, 246, 0.06);
    border: 1px solid rgba(139, 92, 246, 0.15);
    border-radius: 6px;
    margin-bottom: 8px;
}

.cs-recommended-info {
    flex: 1;
}

.cs-recommended-name {
    font-size: 0.9rem;
    color: #e2e8f0;
    font-weight: 500;
}

.cs-recommended-dept {
    font-size: 0.75rem;
    color: #64748b;
    margin-top: 2px;
}

.cs-skill-chips {
    display: flex;
    gap: 4px;
    flex-wrap: wrap;
}

.cs-skill-chip {
    font-size: 0.65rem;
    padding: 2px 6px;
    border-radius: 3px;
    background: rgba(0, 229, 255, 0.12);
    color: #00e5ff;
    text-transform: uppercase;
    font-weight: 600;
}

.cs-director-badge {
    font-size: 0.6rem;
    padding: 1px 5px;
    border-radius: 3px;
    background: rgba(251, 191, 36, 0.15);
    color: #fbbf24;
    font-weight: 700;
    margin-left: 6px;
    vertical-align: middle;
}
```

- [ ] **Step 2: Add responsive rules inside existing media queries**

Find `@media (max-width: 768px) {` and add inside it:

```css
    .cs-expertise-project-tabs {
        gap: 4px;
    }
    .cs-expertise-table {
        font-size: 0.8rem;
    }
    .cs-recommended-card {
        flex-direction: column;
        align-items: flex-start;
        gap: 6px;
    }
```

Find `@media (max-width: 480px) {` and add inside it:

```css
    .cs-expertise-tab {
        font-size: 0.7rem;
        padding: 3px 8px;
    }
    .cs-expertise-score-bar {
        width: 40px;
    }
```

- [ ] **Step 3: Verify CSS loads**

```bash
docker compose restart archie_platform && sleep 2
```

No verification needed beyond restart — CSS doesn't cause runtime errors.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/static/css/consciousness-dashboard-v2.css
git commit -m "feat: add Agent Expertise panel CSS styles"
```

---

### Task 5: JavaScript Panel Renderer

**Files:**
- Modify: `platform_v2/static/js/consciousness-dashboard-v2.js`

- [ ] **Step 1: Add expertise data variable and loader**

Inside the IIFE (after `var _contribProjectId = null;` at line 10), add:

```javascript
  var _expertiseData = null;
```

- [ ] **Step 2: Add `renderExpertiseScoreBar()` helper**

After `renderCompletenessRing()` function (after line 45), add:

```javascript
  function renderExpertiseScoreBar(score) {
    var wrap = document.createElement("span");
    wrap.style.display = "inline-flex";
    wrap.style.alignItems = "center";
    wrap.style.gap = "4px";

    var bar = document.createElement("span");
    bar.className = "cs-expertise-score-bar";
    var fill = document.createElement("span");
    fill.className = "cs-expertise-score-fill " + (score >= 70 ? "high" : score >= 40 ? "mid" : "low");
    fill.style.width = Math.min(score, 100) + "%";
    bar.appendChild(fill);
    wrap.appendChild(bar);

    var num = document.createElement("span");
    num.className = "cs-expertise-score-num";
    num.textContent = String(score);
    wrap.appendChild(num);

    return wrap;
  }
```

- [ ] **Step 3: Add `renderExpertisePanel()` function**

After `renderExpertiseScoreBar()`, add:

```javascript
  function renderExpertisePanel(data) {
    if (!data || !data.success) return;

    _expertiseData = data.projects || [];

    var tabsEl = document.getElementById("cs-expertise-project-tabs");
    if (!tabsEl) return;

    tabsEl.textContent = "";

    if (_expertiseData.length === 0) {
      var body = document.getElementById("cs-agent-expertise-body");
      if (body) {
        body.textContent = "";
        var p = document.createElement("p");
        p.style.color = "#94a3b8";
        p.textContent = "No active projects found.";
        body.appendChild(p);
      }
      return;
    }

    _expertiseData.forEach(function (proj, idx) {
      var tab = document.createElement("button");
      tab.className = "cs-expertise-tab" + (idx === 0 ? " active" : "");
      tab.textContent = proj.name.length > 25 ? proj.name.substring(0, 25) + "..." : proj.name;
      tab.title = proj.name;
      tab.addEventListener("click", function () {
        tabsEl.querySelectorAll(".cs-expertise-tab").forEach(function (t) {
          t.classList.remove("active");
        });
        tab.classList.add("active");
        renderExpertiseProject(proj);
      });
      tabsEl.appendChild(tab);
    });

    renderExpertiseProject(_expertiseData[0]);
  }

  function renderExpertiseProject(proj) {
    var container = document.getElementById("cs-agent-expertise-body");
    if (!container) return;

    container.textContent = "";

    var contributors = proj.contributors || [];
    var recommended = proj.recommended || [];

    if (contributors.length === 0 && recommended.length === 0) {
      var p = document.createElement("p");
      p.style.color = "#94a3b8";
      p.textContent = "No expertise data yet — scores will build as agents work on this project.";
      container.appendChild(p);
      return;
    }

    // Active Contributors
    if (contributors.length > 0) {
      var title1 = document.createElement("div");
      title1.className = "cs-expertise-section-title";
      title1.textContent = "Active Contributors";
      container.appendChild(title1);

      var table = document.createElement("table");
      table.className = "cs-expertise-table";

      var thead = document.createElement("thead");
      var headRow = document.createElement("tr");
      ["Agent", "Department", "Dispatches", "Success", "Score"].forEach(function (h) {
        var th = document.createElement("th");
        th.textContent = h;
        headRow.appendChild(th);
      });
      thead.appendChild(headRow);
      table.appendChild(thead);

      var tbody = document.createElement("tbody");
      contributors.forEach(function (c) {
        var tr = document.createElement("tr");

        var tdName = document.createElement("td");
        tdName.textContent = c.display_name;
        if (c.is_director) {
          var badge = document.createElement("span");
          badge.className = "cs-director-badge";
          badge.textContent = "DIR";
          tdName.appendChild(badge);
        }
        tr.appendChild(tdName);

        var tdDept = document.createElement("td");
        tdDept.textContent = c.department;
        tdDept.style.fontSize = "0.8rem";
        tr.appendChild(tdDept);

        var tdDisp = document.createElement("td");
        tdDisp.textContent = String(c.dispatches);
        tr.appendChild(tdDisp);

        var tdSucc = document.createElement("td");
        var rate = c.dispatches > 0 ? Math.round(c.successes / c.dispatches * 100) : 0;
        tdSucc.textContent = rate + "%";
        tdSucc.style.color = rate >= 80 ? "#10b981" : rate >= 50 ? "#fbbf24" : "#ef4444";
        tr.appendChild(tdSucc);

        var tdScore = document.createElement("td");
        tdScore.appendChild(renderExpertiseScoreBar(c.expertise_score));
        tr.appendChild(tdScore);

        tbody.appendChild(tr);
      });
      table.appendChild(tbody);
      container.appendChild(table);
    }

    // Recommended Agents
    if (recommended.length > 0) {
      var title2 = document.createElement("div");
      title2.className = "cs-expertise-section-title";
      title2.textContent = "Recommended Agents";
      container.appendChild(title2);

      recommended.forEach(function (r) {
        var card = document.createElement("div");
        card.className = "cs-recommended-card";

        var info = document.createElement("div");
        info.className = "cs-recommended-info";

        var nameEl = document.createElement("div");
        nameEl.className = "cs-recommended-name";
        nameEl.textContent = r.display_name;
        if (r.is_director) {
          var dirBadge = document.createElement("span");
          dirBadge.className = "cs-director-badge";
          dirBadge.textContent = "DIR";
          nameEl.appendChild(dirBadge);
        }
        info.appendChild(nameEl);

        var deptEl = document.createElement("div");
        deptEl.className = "cs-recommended-dept";
        deptEl.textContent = r.department + (r.dept_match ? " • Department Match" : "");
        info.appendChild(deptEl);

        card.appendChild(info);

        if (r.matching_skills && r.matching_skills.length > 0) {
          var chips = document.createElement("div");
          chips.className = "cs-skill-chips";
          r.matching_skills.forEach(function (sk) {
            var chip = document.createElement("span");
            chip.className = "cs-skill-chip";
            chip.textContent = sk;
            chips.appendChild(chip);
          });
          card.appendChild(chips);
        }

        card.appendChild(renderExpertiseScoreBar(r.expertise_score));
        container.appendChild(card);
      });
    }
  }
```

- [ ] **Step 4: Hook into `loadDashboardV2Panels()`**

Find the existing `window.loadDashboardV2Panels` function (around line 326):

```javascript
  window.loadDashboardV2Panels = function () {
    api("/api/dashboard/knowledge-gaps").then(function (data) {
      renderProjectKnowledgeMap(data);
      renderKnowledgeGaps(data);
    });
  };
```

Replace it with:

```javascript
  window.loadDashboardV2Panels = function () {
    api("/api/dashboard/knowledge-gaps").then(function (data) {
      renderProjectKnowledgeMap(data);
      renderKnowledgeGaps(data);
    });
    api("/api/dashboard/agent-expertise").then(function (data) {
      renderExpertisePanel(data);
    });
  };
```

- [ ] **Step 5: Verify syntax (no parse errors)**

Open browser dev tools and check for JS errors, or:

```bash
docker exec archie_platform node -e "try { require('fs').readFileSync('/app/static/js/consciousness-dashboard-v2.js', 'utf8'); console.log('File readable'); } catch(e) { console.error(e); }"
```

- [ ] **Step 6: Commit**

```bash
git add platform_v2/static/js/consciousness-dashboard-v2.js
git commit -m "feat: add Agent Expertise panel JS renderer with project selector"
```

---

### Task 6: Deploy, Verify, Complete

**Files:** None (verification only)

- [ ] **Step 1: Restart platform**

```bash
docker compose restart archie_platform
```

- [ ] **Step 2: Verify API endpoint returns data**

```bash
curl -s -b /tmp/archie_cookies http://192.168.1.200:3000/tools/consciousness/api/dashboard/agent-expertise | python3 -m json.tool | head -40
```

If auth is needed, test via Docker:

```bash
docker exec archie_platform python3 -c "
import sys
sys.path.insert(0, '/app')
from services.knowledge_link_service import get_agent_expertise
results = get_agent_expertise()
for p in results:
    contribs = len(p.get('contributors', []))
    recs = len(p.get('recommended', []))
    print(f\"{p['name'][:40]}: {contribs} contributors, {recs} recommended\")
    for c in p.get('contributors', [])[:2]:
        print(f\"  Contributor: {c['display_name']} (score={c['expertise_score']})\")
    for r in p.get('recommended', [])[:2]:
        print(f\"  Recommended: {r['display_name']} (score={r['expertise_score']}, skills={r['matching_skills']})\")
"
```

Expected: Each project should show recommended agents based on skill/department alignment. Contributors will be empty until bridge_jobs get project_id data.

- [ ] **Step 3: Browser verify — Dashboard tab loads 4 panels**

Open `http://192.168.1.200:3000/tools/consciousness` → Dashboard tab.

Verify:
1. Panel 1: Project-Knowledge Map (existing) ✓
2. Panel 2: Agent Contributions (existing) ✓
3. Panel 3: Knowledge Gaps (existing) ✓
4. Panel 4: Agent Expertise (NEW) — project tabs, recommended agents with skill chips

- [ ] **Step 4: Test project tab switching**

Click different project tabs in the Expertise panel. Verify the contributor table and recommendation cards update without errors.

- [ ] **Step 5: Complete MCP task**

```
mcp complete_task 1636 "Agent Expertise Panel: 4th LCARS dashboard panel with 3-signal scoring (dispatch history 50% + skill alignment 35% + department match 15%). Shows active contributors table and recommended agents with skill chips. Project tab selector. Cached agent skills (5-min TTL)."
```
