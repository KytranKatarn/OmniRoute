# Dispatch Triage Pipeline Upgrade — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make Bridge dispatch skill-aware, workload-enforcing, and capable of requesting new agent creation when no suitable agent exists.

**Architecture:** Enhance `_select_agent()` in bridge_dispatcher.py with a scoring system that considers skills (from `agent_skills` table), welfare state, and budget limits. Add hard-block gates for resting/exhausted agents. Add a creation-request flow via Telegram when skill gaps are detected.

**Tech Stack:** Python/Flask, PostgreSQL, existing Telegram approval flow (`agent_loop.request_approval`)

---

### Task 1: Enhance Agent Cache with Skills + Welfare Data

**Files:**
- Modify: `ai_bridge/bridge_dispatcher.py` (lines 217-262, `_refresh_agent_cache()`)

**What to do:**

Expand `_refresh_agent_cache()` to also load each agent's skills and current welfare state. Add a separate welfare cache with 30s TTL.

**Step 1: Add welfare cache infrastructure**

Add to `__init__()` (after line 197):
```python
self._welfare_cache = {}  # agent_id → {stress, energy, mood, in_rest, budget_remaining}
self._welfare_cache_time = 0
self._welfare_cache_ttl = 30  # 30s TTL, same as Ollama cache pattern
```

**Step 2: Expand agent cache query to include skills**

In `_refresh_agent_cache()`, after building the agent cache dict (line 258), add a second query to load skills:
```python
cur.execute("""
    SELECT agent_id, skill_name, skill_category, proficiency_level
    FROM agent_skills
    WHERE agent_id IN (SELECT id FROM agents WHERE status = 'active')
""")
skills = cur.fetchall()
# Build skills lookup: {agent_id: {skill_name: proficiency_level}}
skills_by_agent = {}
for s in skills:
    aid = s["agent_id"] if isinstance(s, dict) else s[0]
    sname = s["skill_name"] if isinstance(s, dict) else s[1]
    prof = s["proficiency_level"] if isinstance(s, dict) else s[3]
    skills_by_agent.setdefault(aid, {})[sname] = prof

# Attach to agent cache entries
for name, info in self._agent_cache.items():
    info["skills"] = skills_by_agent.get(info["id"], {})
```

**Step 3: Add `_refresh_welfare_cache()` method**

New method that loads welfare + budget + rest state for all active agents:
```python
def _refresh_welfare_cache(self):
    """Load agent welfare state, budgets, and rest cycles. 30s TTL."""
    now = time.time()
    if self._welfare_cache and (now - self._welfare_cache_time) < self._welfare_cache_ttl:
        return
    try:
        from psycopg2.extras import RealDictCursor
        conn = self._get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        # Welfare state
        cur.execute("""
            SELECT DISTINCT ON (agent_id) agent_id, stress_level, energy_level, current_mood
            FROM agent_emotional_state
            ORDER BY agent_id, timestamp DESC
        """)
        welfare = {r["agent_id"]: r for r in cur.fetchall()}

        # Active rest cycles
        cur.execute("""
            SELECT agent_id FROM agent_rest_cycles WHERE ended_at IS NULL
        """)
        resting = {r["agent_id"] for r in cur.fetchall()}

        # Budget state
        cur.execute("""
            SELECT agent_id, current_task_count, task_queue_limit, tokens_used_today, token_limit_per_day
            FROM agent_budgets
        """)
        budgets = {r["agent_id"]: r for r in cur.fetchall()}

        self._welfare_cache = {}
        for agent_id in set(list(welfare.keys()) + list(budgets.keys())):
            w = welfare.get(agent_id, {})
            b = budgets.get(agent_id, {})
            self._welfare_cache[agent_id] = {
                "stress": float(w.get("stress_level", 0.2)),
                "energy": float(w.get("energy_level", 0.8)),
                "mood": w.get("current_mood", "neutral"),
                "in_rest": agent_id in resting,
                "tasks_today": b.get("current_task_count", 0),
                "task_limit": b.get("task_queue_limit", 10),
                "tokens_today": b.get("tokens_used_today", 0),
                "token_limit": b.get("token_limit_per_day", 100000),
            }
        self._welfare_cache_time = now
        cur.close()
        conn.close()
    except Exception as e:
        logger.debug(f"[BridgeDispatcher] Welfare cache refresh skipped: {e}")
```

**Step 4: Commit**
```bash
git add ai_bridge/bridge_dispatcher.py
git commit -m "feat(dispatch): load agent skills and welfare into cache"
```

---

### Task 2: Replace _select_agent() with Scoring System

**Files:**
- Modify: `ai_bridge/bridge_dispatcher.py` (lines 264-280, `_select_agent()`)

**What to do:**

Replace the simple lookup with a scoring + filtering system. Keep `_select_agent()` as the public method name but rewrite its internals.

**Step 1: Add scoring weights constant**

After `AGENT_SPECIALIZATION` dict (after line 143):
```python
# Agent selection scoring weights
SELECTION_WEIGHTS = {
    "skills": 0.35,
    "specialization": 0.25,
    "welfare": 0.20,
    "availability": 0.15,
    "budget": 0.05,
}
```

**Step 2: Add `_score_agent()` method**

```python
def _score_agent(self, agent_name: str, agent_info: dict, capability: str, station_code: str) -> tuple:
    """Score an agent for a capability. Returns (score, block_reason or None)."""
    agent_id = agent_info.get("id")
    welfare = self._welfare_cache.get(agent_id, {})

    # --- Hard blocks (return score=0 with reason) ---
    if welfare.get("in_rest"):
        return (0.0, "in_rest_cycle")
    if welfare.get("tasks_today", 0) >= welfare.get("task_limit", 10):
        return (0.0, "budget_exhausted")
    stress = welfare.get("stress", 0.2)
    energy = welfare.get("energy", 0.8)
    if stress >= 0.9 and energy <= 0.15:
        return (0.0, "critical_welfare")

    # --- Skills score (0-1) ---
    skills = agent_info.get("skills", {})
    proficiency = skills.get(capability, 0)
    if proficiency > 0:
        skills_score = proficiency / 5.0
    else:
        # No explicit skill row — generous default (agent may still handle it)
        skills_score = 0.3

    # --- Specialization bonus (0 or 1) ---
    station_specs = AGENT_SPECIALIZATION.get(station_code, {})
    expected = station_specs.get(capability, station_specs.get("default"))
    spec_score = 1.0 if agent_name == expected else 0.0

    # --- Welfare score ---
    welfare_score = (1.0 - stress) * energy

    # --- Availability score ---
    busy_job = self._check_agent_busy(agent_name)
    avail_score = 0.2 if busy_job else 1.0

    # --- Budget score ---
    tasks_today = welfare.get("tasks_today", 0)
    task_limit = welfare.get("task_limit", 10)
    if task_limit > 0:
        usage_ratio = tasks_today / task_limit
        budget_score = max(1.0 - usage_ratio, 0.0)
    else:
        budget_score = 1.0

    # --- Composite ---
    w = SELECTION_WEIGHTS
    composite = (
        w["skills"] * skills_score
        + w["specialization"] * spec_score
        + w["welfare"] * welfare_score
        + w["availability"] * avail_score
        + w["budget"] * budget_score
    )
    return (round(composite, 4), None)
```

**Step 3: Rewrite `_select_agent()`**

Replace lines 264-280:
```python
def _select_agent(self, capability: str, station_code: str) -> Optional[Dict]:
    """Select the best agent for a capability within a station using scoring."""
    self._refresh_agent_cache()
    self._refresh_welfare_cache()

    # Gather candidates at this station
    candidates = []
    for name, info in self._agent_cache.items():
        if info.get("station_code") == station_code:
            score, block_reason = self._score_agent(name, info, capability, station_code)
            candidates.append((score, block_reason, name, info))

    if not candidates:
        return None

    # Sort by score descending
    candidates.sort(key=lambda x: x[0], reverse=True)

    # Log selection reasoning
    top = candidates[0]
    if top[0] > 0:
        logger.info(
            f"[BridgeDispatcher] Agent selection for '{capability}' at {station_code}: "
            f"chose '{top[2]}' (score={top[0]:.3f}), "
            f"{len([c for c in candidates if c[0] > 0])}/{len(candidates)} eligible"
        )
        return {**top[3], "name": top[2]}

    # All agents blocked — log reasons
    reasons = [(c[2], c[1]) for c in candidates if c[1]]
    logger.warning(
        f"[BridgeDispatcher] All agents blocked for '{capability}' at {station_code}: "
        f"{reasons}"
    )
    return None
```

**Step 4: Commit**
```bash
git add ai_bridge/bridge_dispatcher.py
git commit -m "feat(dispatch): scoring-based agent selection with welfare gates"
```

---

### Task 3: Add Dynamic Agent Creation Request Flow

**Files:**
- Modify: `ai_bridge/bridge_dispatcher.py` (add new methods, modify `request_work()`)

**What to do:**

Add methods to detect skill gaps, check for duplicates, and request agent creation via Telegram approval.

**Step 1: Add `_check_creation_duplicates()` method**

```python
def _check_creation_duplicates(self, capability: str, station_code: str) -> Optional[str]:
    """Check if an agent creation for this capability is already pending or recent.
    Returns reason string if duplicate found, None if safe to create."""
    try:
        conn = self._get_db()
        cur = conn.cursor()
        # Check pending creation requests
        cur.execute("""
            SELECT id FROM autonomy_approval_queue
            WHERE action_type = 'create_agent'
              AND status = 'pending'
              AND action_data->>'capability' = %s
              AND action_data->>'station_code' = %s
        """, (capability, station_code))
        if cur.fetchone():
            cur.close()
            conn.close()
            return f"Pending creation request already exists for {capability} at {station_code}"

        # Check recent creations (24h)
        cur.execute("""
            SELECT ace.id, a.name FROM agent_creation_events ace
            JOIN agents a ON a.id = ace.child_agent_id
            WHERE ace.capabilities_requested ? %s
              AND ace.station_requested = %s
              AND ace.created_at > NOW() - INTERVAL '24 hours'
            LIMIT 1
        """, (capability, station_code))
        recent = cur.fetchone()
        cur.close()
        conn.close()
        if recent:
            return f"Agent '{recent[1]}' was recently created for this capability (id={recent[0]})"
        return None
    except Exception as e:
        logger.debug(f"[BridgeDispatcher] Dedup check error: {e}")
        return None
```

**Step 2: Add `_request_agent_creation()` method**

```python
def _request_agent_creation(self, capability: str, station_code: str, reason: str) -> bool:
    """Request agent creation via Telegram approval. Returns True if request submitted."""
    # Dedup check
    dup_reason = self._check_creation_duplicates(capability, station_code)
    if dup_reason:
        logger.info(f"[BridgeDispatcher] Skipping creation request: {dup_reason}")
        return False

    # Build suggested agent profile
    station_names = {
        "COMMAND": "Command", "ANALYTICS": "Analytics", "ENGINEERING": "Engineering",
        "OPERATIONS": "Operations", "CREATIVE": "Creative", "RESEARCH": "Research",
    }
    station_name = station_names.get(station_code, station_code)
    suggested_name = f"{station_name}-{capability.replace('_', '-').title()}"

    action_data = {
        "capability": capability,
        "station_code": station_code,
        "suggested_name": suggested_name,
        "suggested_skills": [capability],
        "suggested_model": "dolphin3-8k:latest",
        "reason": reason,
    }

    try:
        from agent_loop import request_approval
        request_approval(
            action_type="create_agent",
            action_data=action_data,
            reason=f"Skill gap: no agent with '{capability}' at {station_code}. {reason}",
            tier=2,
        )
        logger.info(
            f"[BridgeDispatcher] Agent creation request submitted: "
            f"{suggested_name} for {capability} at {station_code}"
        )
        return True
    except Exception as e:
        logger.warning(f"[BridgeDispatcher] Failed to submit creation request: {e}")
        return False
```

**Step 3: Add `_create_agent_from_approval()` method**

```python
def _create_agent_from_approval(self, approval_data: dict) -> Optional[int]:
    """Execute an approved agent creation. Returns new agent_id or None."""
    try:
        conn = self._get_db()
        cur = conn.cursor()

        name = approval_data.get("suggested_name", "NewAgent")
        capability = approval_data.get("capability", "general")
        station_code = approval_data.get("station_code", "COMMAND")
        model = approval_data.get("suggested_model", "dolphin3-8k:latest")
        skills = approval_data.get("suggested_skills", [])

        # Create the agent
        cur.execute("""
            INSERT INTO agents (name, department, title, model, status, worker_type,
                                cost_tier, agent_generation, created_at)
            VALUES (%s, %s, %s, %s, 'active', 'internal', 'free', 1, NOW())
            RETURNING id
        """, (name, station_code, f"{capability} Specialist", model))
        agent_id = cur.fetchone()[0]

        # Add skills
        for skill in skills:
            cur.execute("""
                INSERT INTO agent_skills (agent_id, skill_name, skill_category, proficiency_level)
                VALUES (%s, %s, 'technical', 3)
                ON CONFLICT (agent_id, skill_name) DO NOTHING
            """, (agent_id, skill))

        # Initialize budget
        cur.execute("""
            INSERT INTO agent_budgets (agent_id, token_limit_per_day, task_queue_limit)
            VALUES (%s, 100000, 10)
            ON CONFLICT (agent_id) DO NOTHING
        """, (agent_id,))

        # Initialize welfare state
        cur.execute("""
            INSERT INTO agent_emotional_state (agent_id, current_mood, stress_level, energy_level)
            VALUES (%s, 'neutral', 0.2, 0.8)
        """, (agent_id,))

        # Assign to station
        cur.execute("""
            SELECT id FROM bridge_stations WHERE station_code = %s AND is_active = TRUE LIMIT 1
        """, (station_code,))
        station_row = cur.fetchone()
        if station_row:
            cur.execute("""
                INSERT INTO station_assignments (agent_id, station_id, is_active, priority)
                VALUES (%s, %s, TRUE, 50)
                ON CONFLICT DO NOTHING
            """, (agent_id, station_row[0]))

        # Log creation event
        cur.execute("""
            INSERT INTO agent_creation_events
                (parent_agent_id, child_agent_id, creation_reason, creation_source,
                 capabilities_requested, station_requested, is_approved, approved_at)
            VALUES (2, %s, %s, 'dispatch_gap', %s, %s, TRUE, NOW())
        """, (agent_id, f"Skill gap: {capability}", json.dumps(skills), station_code))

        # Governance audit
        cur.execute("""
            INSERT INTO governance_audit_log (event_type, event_category, agent_id, details)
            VALUES ('agent_created', 'autonomy', %s, %s)
        """, (agent_id, json.dumps({"source": "dispatch_triage", "capability": capability,
                                     "station": station_code, "name": name})))

        conn.commit()
        cur.close()
        conn.close()

        # Invalidate cache so new agent is picked up
        self._cache_time = 0

        logger.info(f"[BridgeDispatcher] Created agent '{name}' (id={agent_id}) for {capability}")
        return agent_id
    except Exception as e:
        logger.error(f"[BridgeDispatcher] Agent creation failed: {e}")
        return None
```

**Step 4: Wire creation into `request_work()`**

In `request_work()`, after the existing fallback block (lines 898-911), add creation request logic:

Replace the current fallback block:
```python
if not agent:
    # No agent available — check if this is a skill gap vs transient block
    # Try creation request for persistent gaps
    self._request_agent_creation(
        capability=capability,
        station_code=station_code,
        reason=f"No eligible agent for '{capability}' at {station_code} (module: {module_id})"
    )
    # Still fall back to ARCHIE for this request
    logger.warning(
        f"[BridgeDispatcher] No agent for capability='{capability}' "
        f"station='{station_code}', falling back to COMMAND"
    )
    agent = self._agent_cache.get("ARCHIE", {
        "id": 2,
        "model": "dolphin3-8k:latest",
        "system_prompt": None,
        "temperature": 0.5,
        "station_code": "COMMAND",
    })
    station_code = "COMMAND"
```

**Step 5: Commit**
```bash
git add ai_bridge/bridge_dispatcher.py
git commit -m "feat(dispatch): dynamic agent creation request with Telegram approval"
```

---

### Task 4: Add Budget Increment on Dispatch

**Files:**
- Modify: `ai_bridge/bridge_dispatcher.py` (in `_log_execution()` or after successful dispatch in `request_work()`)

**What to do:**

After a successful dispatch, increment `agent_budgets.current_task_count` so the workload enforcement actually tracks usage.

**Step 1: Add `_increment_agent_budget()` method**

```python
def _increment_agent_budget(self, agent_id: Optional[int], tokens_used: int = 0):
    """Increment agent's daily task count and token usage."""
    if not agent_id:
        return
    try:
        conn = self._get_db()
        cur = conn.cursor()
        cur.execute("""
            UPDATE agent_budgets
            SET current_task_count = current_task_count + 1,
                tokens_used_today = tokens_used_today + %s,
                updated_at = NOW()
            WHERE agent_id = %s
        """, (tokens_used, agent_id))
        # Reset if past the reset time
        cur.execute("""
            UPDATE agent_budgets
            SET current_task_count = 1, tokens_used_today = %s, token_reset_at = NOW() + INTERVAL '1 day'
            WHERE agent_id = %s AND token_reset_at < NOW()
        """, (tokens_used, agent_id))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.debug(f"[BridgeDispatcher] Budget increment skipped: {e}")
```

**Step 2: Call in request_work()**

After `_log_execution()` (line 1107), add:
```python
# 6b. Increment agent budget tracking
if result.success:
    self._increment_agent_budget(
        agent.get("id"),
        tokens_used=result.prompt_tokens + result.completion_tokens
    )
```

**Step 3: Commit**
```bash
git add ai_bridge/bridge_dispatcher.py
git commit -m "feat(dispatch): track daily task count and token usage per agent"
```

---

### Task 5: Add Bridge UI Endpoints for Skill Gaps

**Files:**
- Modify: `platform_v2/tools/bridge/routes.py` (add 2 new endpoints)

**What to do:**

Add endpoints so the Bridge UI can show recent skill gaps and allow manual agent creation triggers.

**Step 1: Add `/api/dispatch/agent-gaps` endpoint**

```python
@bridge_bp.route("/api/dispatch/agent-gaps")
@login_required
def get_agent_gaps():
    """List recent agent creation requests (skill gaps)."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT id, action_data, status, reason, created_at, approved_at, rejected_reason
            FROM autonomy_approval_queue
            WHERE action_type = 'create_agent'
            ORDER BY created_at DESC
            LIMIT 20
        """)
        gaps = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify({"gaps": [{
            "id": g["id"],
            "capability": g["action_data"].get("capability", "unknown") if isinstance(g["action_data"], dict) else "unknown",
            "station": g["action_data"].get("station_code", "unknown") if isinstance(g["action_data"], dict) else "unknown",
            "suggested_name": g["action_data"].get("suggested_name", "") if isinstance(g["action_data"], dict) else "",
            "status": g["status"],
            "reason": g["reason"],
            "created_at": g["created_at"].isoformat() if g["created_at"] else None,
        } for g in gaps]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
```

**Step 2: Add `/api/agents/create-from-gap` endpoint**

```python
@bridge_bp.route("/api/agents/create-from-gap", methods=["POST"])
@login_required
def create_agent_from_gap():
    """Manually approve and create an agent from a skill gap request."""
    if not current_user.is_admin:
        return jsonify({"error": "Admin only"}), 403
    data = request.get_json() or {}
    approval_id = data.get("approval_id")
    if not approval_id:
        return jsonify({"error": "approval_id required"}), 400
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT id, action_data, status FROM autonomy_approval_queue
            WHERE id = %s AND action_type = 'create_agent'
        """, (approval_id,))
        row = cur.fetchone()
        if not row:
            cur.close()
            conn.close()
            return jsonify({"error": "Request not found"}), 404
        if row["status"] != "pending":
            cur.close()
            conn.close()
            return jsonify({"error": f"Request already {row['status']}"}), 400

        # Execute creation via dispatcher
        from ai_bridge.bridge_dispatcher import get_dispatcher
        dispatcher = get_dispatcher()
        agent_id = dispatcher._create_agent_from_approval(row["action_data"])

        if agent_id:
            cur.execute("""
                UPDATE autonomy_approval_queue
                SET status = 'approved', approved_by = %s, approved_at = NOW()
                WHERE id = %s
            """, (current_user.id, approval_id))
            conn.commit()
            cur.close()
            conn.close()
            return jsonify({"success": True, "agent_id": agent_id})
        else:
            cur.close()
            conn.close()
            return jsonify({"error": "Agent creation failed"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500
```

**Step 3: Commit**
```bash
git add platform_v2/tools/bridge/routes.py
git commit -m "feat(bridge): add skill gap visibility and manual creation endpoints"
```

---

### Task 6: Add Skill Gap Indicator to Dispatch Tab UI

**Files:**
- Modify: `platform_v2/templates/tools/bridge.html` (DSPCH tab area + JS)

**What to do:**

Add a small "Skill Gaps" indicator to the dispatch tab that shows pending creation requests, with an approve/reject button for admins. Use safe DOM methods (textContent, createElement) — no innerHTML.

**Step 1: Add skill gap section HTML to DSPCH panel**

After the dispatch list container in the LCARS console, add:
```html
<div id="console-skill-gaps" class="console-skill-gaps" style="display:none;">
    <div class="console-section-header" style="display:flex;justify-content:space-between;align-items:center;">
        <span>SKILL GAPS</span>
        <span id="gap-count-badge" class="badge badge-warning" style="display:none;">0</span>
    </div>
    <div id="gap-list" class="console-gap-list"></div>
</div>
```

**Step 2: Add JS to load and display gaps (safe DOM only, no innerHTML)**

```javascript
async function loadSkillGaps() {
    try {
        const resp = await fetch('/tools/bridge/api/dispatch/agent-gaps');
        const data = await resp.json();
        const gaps = (data.gaps || []).filter(g => g.status === 'pending');
        const container = document.getElementById('gap-list');
        const badge = document.getElementById('gap-count-badge');
        const section = document.getElementById('console-skill-gaps');

        if (gaps.length === 0) {
            section.style.display = 'none';
            return;
        }
        section.style.display = '';
        badge.style.display = '';
        badge.textContent = gaps.length;

        // Clear old content safely
        while (container.firstChild) container.removeChild(container.firstChild);

        gaps.forEach(g => {
            const div = document.createElement('div');
            div.className = 'console-gap-item';
            div.style.cssText = 'padding:8px;border:1px solid var(--lcars-border,#444);border-radius:8px;margin-bottom:6px;';

            const info = document.createElement('div');
            info.textContent = g.capability + ' @ ' + g.station + ' → ' + g.suggested_name;
            info.style.fontWeight = 'bold';
            div.appendChild(info);

            const reason = document.createElement('div');
            reason.textContent = g.reason || '';
            reason.style.cssText = 'font-size:0.85em;opacity:0.7;margin-top:2px;';
            div.appendChild(reason);

            const btn = document.createElement('button');
            btn.className = 'btn btn-sm btn-outline-success mt-1';
            btn.textContent = 'Approve & Create';
            btn.addEventListener('click', function() { approveGap(g.id, btn); });
            div.appendChild(btn);

            container.appendChild(div);
        });
    } catch (e) {
        console.debug('Skill gaps load error:', e);
    }
}

async function approveGap(approvalId, btn) {
    btn.disabled = true;
    btn.textContent = 'Creating...';
    try {
        const resp = await fetch('/tools/bridge/api/agents/create-from-gap', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({approval_id: approvalId})
        });
        const data = await resp.json();
        if (data.success) {
            btn.textContent = 'Created';
            btn.className = 'btn btn-sm btn-success mt-1';
            setTimeout(loadSkillGaps, 2000);
        } else {
            btn.textContent = data.error || 'Failed';
            btn.disabled = false;
        }
    } catch (e) {
        btn.textContent = 'Error';
        btn.disabled = false;
    }
}
```

**Step 3: Hook into dispatch tab load**

In the `loadConsoleDispatch()` function, add a call to `loadSkillGaps()` after the SSE setup.

**Step 4: Commit**
```bash
git add platform_v2/templates/tools/bridge.html
git commit -m "feat(bridge): skill gap indicator in dispatch tab with approve button"
```
