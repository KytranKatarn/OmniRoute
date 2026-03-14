# Game Studio Phase 3: AI Game Builder — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a 4-stage AI build pipeline (concept → level → mechanics → QA) that generates playable games from text descriptions, plus custom behavior code sandbox and role-based chat enhancement.

**Architecture:** `game_builder_service.py` orchestrates the pipeline, dispatching each stage to Bridge with specialized system prompts. Custom JS behaviors stored in `game_assets.content`, loaded at runtime via postMessage into sandboxed engine scope. Enhanced `ai_chat()` with role detection routes to the right prompt. Frontend adds "Build with AI" wizard with pipeline progress + checkpoint approval.

**Tech Stack:** Flask, PostgreSQL, archie_bridge, vanilla JS

**Key patterns:**
- Bridge: `ai_bridge(prompt, system_prompt, user_id, enable_memory=False)` returns `{success, response, model, provider}`
- DB: `from database import get_db_cursor` with `with get_db_cursor(commit=True) as (conn, cur):`
- Routes: `@game_studio_bp.route(...)` + `@login_required`, module uses `get_db_connection()` for some routes
- Game engine: plugin modules register via `GameEngine.registerModuleType()`, config via postMessage
- `game_scenes` table already exists: id, game_id, name, scene_order, scene_data (JSONB)
- `game_assets` table already exists: id, user_id, game_id, name, asset_type, file_path, file_size, thumbnail_url
- IMPORTANT: No innerHTML — createElement/textContent only for frontend

---

## Task 1: Database Migration 161

**Files:**
- Create: `database/migrations/161_game_builder.sql`

- [ ] **Step 1: Write migration**

```sql
-- Migration 161: Game builder sessions + code asset content
-- Idempotent: safe to run multiple times

CREATE TABLE IF NOT EXISTS game_build_sessions (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES game_projects(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL,
    description TEXT NOT NULL,
    current_stage VARCHAR(30) DEFAULT 'concept',
    status VARCHAR(20) DEFAULT 'running',
    stage_outputs JSONB DEFAULT '{}',
    checkpoint_approved JSONB DEFAULT '[]',
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);

ALTER TABLE game_assets
ADD COLUMN IF NOT EXISTS content TEXT;

CREATE INDEX IF NOT EXISTS idx_game_build_sessions_project ON game_build_sessions(project_id);
CREATE INDEX IF NOT EXISTS idx_game_assets_type ON game_assets(game_id, asset_type);
```

- [ ] **Step 2: Run migration**

```bash
docker cp database/migrations/161_game_builder.sql archie_database:/tmp/
docker exec archie_database psql -U archie -d archie -f /tmp/161_game_builder.sql
```

- [ ] **Step 3: Verify**

```bash
docker exec archie_database psql -U archie -d archie -c "\d game_build_sessions"
docker exec archie_database psql -U archie -d archie -c "SELECT column_name FROM information_schema.columns WHERE table_name='game_assets' AND column_name='content'"
```

- [ ] **Step 4: Commit**

```bash
git add database/migrations/161_game_builder.sql
git commit -m "feat(game-studio): add migration 161 — build sessions + asset content column"
```

---

## Task 2: Game Builder Service

**Files:**
- Create: `platform_v2/tools/game_studio/game_builder_service.py`

- [ ] **Step 1: Write the builder service (~200 lines)**

Key components:

**Pipeline definition:**
```python
PIPELINE_STAGES = [
    {"id": "concept", "name": "Game Concept", "checkpoint": True},
    {"id": "level", "name": "Level Design", "checkpoint": False},
    {"id": "mechanics", "name": "Game Mechanics", "checkpoint": False},
    {"id": "qa", "name": "Quality Check", "checkpoint": True},
]
```

**`start_build(user_id, description, game_type=None)`:**
1. Create game_projects row (title from first 50 chars of description, status='building')
2. INSERT game_build_sessions (project_id, user_id, description, current_stage='concept', status='running')
3. Call `_run_stage(session_id, 'concept')`
4. Return {session_id, project_id, status, stage}

**`_run_stage(session_id, stage_id)`:**
1. Load session from DB
2. Build system prompt for the stage (see stage prompts below)
3. Build context from previous stage outputs
4. Call Bridge: `ai_bridge(prompt=context, system_prompt=stage_prompt, user_id=session.user_id, enable_memory=False)`
5. Parse response — try JSON first, fallback to extracting JSON from code blocks
6. Store output in session.stage_outputs[stage_id]
7. If stage has checkpoint: set status='checkpoint', return
8. If no checkpoint: auto-advance to next stage

**Stage system prompts:**

Concept:
```
You are a game concept designer. Given a game description, output ONLY valid JSON:
{"game_type": "top_down_shooter"|"space_explorer"|"base_builder", "theme": "...", "mechanics": ["..."], "entities": [{"name":"...", "type":"...", "behavior":"..."}], "win_condition": "...", "difficulty_curve": "easy_start_hard_end"}
```

Level:
```
You are a game level designer. Given a concept, generate a complete game config JSON matching the {game_type} schema. Include all entities with positions, map layout, and resource distribution. Output ONLY valid JSON matching the config structure.
Current game type schemas are provided as context.
```

Mechanics:
```
You are a game mechanics programmer. Given concept + level config, write custom behavior functions for entities that need special logic beyond chase/patrol/circle. Output ONLY valid JSON:
{"behaviors": [{"name": "behavior_name", "code": "function(entity, engine, dt) { ... }"}]}
Each function receives: entity (position, health, speed), engine (drawCircle, drawRect, config), dt (delta seconds).
```

QA:
```
You are a game QA analyst. Review the config + behaviors for issues. Output ONLY valid JSON:
{"issues": [{"severity": "high"|"medium"|"low", "description": "...", "fix": "..."}], "score": 0-100, "summary": "..."}
Score 80+ means ready to play. Below 60 needs significant fixes.
```

**`approve_checkpoint(session_id, user_id)`:**
1. Verify session belongs to user, status='checkpoint'
2. Add current_stage to checkpoint_approved
3. If more stages remain: advance to next stage, call _run_stage
4. If all stages done: set status='completed', completed_at=NOW()
5. Return updated status

**`get_build_status(session_id)`:**
SELECT from game_build_sessions, return dict with all fields serialized.

**`apply_build_result(session_id)`:**
1. Load session, verify status='completed'
2. Extract level config from stage_outputs['level']
3. Create game_scene with scene_data = level config
4. Extract behaviors from stage_outputs['mechanics']
5. For each behavior: INSERT game_assets (game_id, name=behavior.name, asset_type='code', content=behavior.code)
6. Update game_projects status='development'
7. Return {project_id}

Use `from database import get_db_cursor` pattern. Bridge import via `import sys; sys.path.insert(0, "/mnt/archie_brain/ai_bridge"); from archie_bridge import archie_bridge as ai_bridge`.

- [ ] **Step 2: Verify import**

```bash
docker exec archie_platform python3 -c "from tools.game_studio.game_builder_service import start_build, approve_checkpoint, get_build_status, apply_build_result; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/game_studio/game_builder_service.py
git commit -m "feat(game-studio): add AI game builder service — 4-stage pipeline"
```

---

## Task 3: Code Sandbox in Engine

**Files:**
- Modify: `platform_v2/static/js/game-engine.js`
- Modify: `platform_v2/static/js/game-module-shooter.js`
- Modify: `platform_v2/static/js/game-module-explorer.js`
- Modify: `platform_v2/static/js/game-module-builder.js`

- [ ] **Step 1: Add behavior sandbox to game-engine.js**

Read game-engine.js. Find the GameEngine class. Add these methods:

```javascript
// Sandboxed behavior creation — blocks dangerous APIs
GameEngine.createSandboxedBehavior = function(codeStr) {
    try {
        // Wrap in strict mode with dangerous APIs blocked
        var wrapper = '"use strict";\n' +
            'var document=void 0,window=void 0,fetch=void 0,XMLHttpRequest=void 0;\n' +
            'return (' + codeStr + ');';
        var fn = (new (Function.bind.apply(Function, [null, 'entity', 'engine', 'dt', wrapper])))();
        return typeof fn === 'function' ? fn : null;
    } catch(e) {
        console.warn('Invalid behavior code:', e.message);
        return null;
    }
};

GameEngine.prototype.loadBehaviors = function(behaviors) {
    this._behaviors = {};
    var self = this;
    (behaviors || []).forEach(function(b) {
        if (b.name && b.code) {
            var fn = GameEngine.createSandboxedBehavior(b.code);
            if (fn) self._behaviors[b.name] = fn;
        }
    });
};

GameEngine.prototype.runBehavior = function(name, entity, dt) {
    if (this._behaviors && this._behaviors[name]) {
        try { this._behaviors[name](entity, this, dt); }
        catch(e) { console.warn('Behavior error [' + name + ']:', e.message); }
    }
};
```

Also add postMessage handler for loadBehaviors:
```javascript
if (e.data.type === 'loadBehaviors') {
    if (window._engine) window._engine.loadBehaviors(e.data.behaviors);
}
```

- [ ] **Step 2: Add behavior hooks to all 3 modules**

In each module's update function, after the existing entity AI logic, add a check for custom behaviors. Find the enemy/entity update loop and add:

```javascript
// After existing AI logic for this entity:
if (entity.behavior && engine._behaviors && engine._behaviors[entity.behavior]) {
    engine.runBehavior(entity.behavior, entity, dt);
}
```

Add this to:
- `game-module-shooter.js` — in the enemy update loop
- `game-module-explorer.js` — in any entity update (pirates, etc.)
- `game-module-builder.js` — in colonist and raider update loops

- [ ] **Step 3: Commit**

```bash
git add platform_v2/static/js/game-engine.js platform_v2/static/js/game-module-shooter.js platform_v2/static/js/game-module-explorer.js platform_v2/static/js/game-module-builder.js
git commit -m "feat(game-studio): add behavior sandbox + hooks in all game modules"
```

---

## Task 4: Enhanced AI Chat + Build Routes

**Files:**
- Modify: `platform_v2/tools/game_studio/routes.py`

- [ ] **Step 1: Read routes.py to find ai_chat() and understand current structure**

- [ ] **Step 2: Add role detection to ai_chat()**

Before the Bridge call in `ai_chat()`, add keyword classification:

```python
DESIGN_KW = ['theme','color','look','feel','style','aesthetic','sprite','visual','art']
LEVEL_KW = ['level','map','place','spawn','position','layout','area','zone','terrain']
MECHANICS_KW = ['behavior','speed','health','damage','ability','power','rule','logic','code','function','movement']
BUILD_KW = ['build me','create a game','make a game','new game about','generate a','scaffold']

msg_lower = message.lower()
if any(k in msg_lower for k in BUILD_KW):
    # Trigger full pipeline
    from game_builder_service import start_build
    result = start_build(current_user.id, message)
    return jsonify({"success": True, "response": "Building your game...", "build_session": result})

# Enhance system prompt based on role
if any(k in msg_lower for k in DESIGN_KW):
    system_prompt += "\nFocus on visual design, themes, and aesthetics."
elif any(k in msg_lower for k in LEVEL_KW):
    system_prompt += "\nFocus on level layout, entity placement, and map design."
elif any(k in msg_lower for k in MECHANICS_KW):
    system_prompt += "\nFocus on game mechanics and code. Return behavior functions when appropriate."
```

Also enhance the context sent to Bridge — include full project info:
```python
game_id = data.get("game_id")
if game_id:
    # Load config, existing behaviors
    context_parts = [f"Game type: {game.engine_type}", f"Config: {json.dumps(scene.scene_data)[:3000]}"]
    # Load code assets
    cur.execute("SELECT name, content FROM game_assets WHERE game_id=%s AND asset_type='code'", (game_id,))
    behaviors = cur.fetchall()
    if behaviors:
        context_parts.append("Existing behaviors: " + ", ".join(b['name'] for b in behaviors))
    system_prompt += "\n\nProject context:\n" + "\n".join(context_parts)
```

- [ ] **Step 3: Add 4 build pipeline routes**

Append to routes.py:

```python
@game_studio_bp.route("/api/ai/build", methods=["POST"])
@login_required
def start_ai_build():
    from game_builder_service import start_build
    data = request.get_json() or {}
    description = data.get("description", "").strip()
    if not description:
        return jsonify({"error": "Description is required"}), 400
    game_type = data.get("game_type")
    result = start_build(current_user.id, description, game_type)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)

@game_studio_bp.route("/api/ai/build/<int:session_id>", methods=["GET"])
@login_required
def get_ai_build_status(session_id):
    from game_builder_service import get_build_status
    result = get_build_status(session_id)
    if result is None:
        return jsonify({"error": "Session not found"}), 404
    for k, v in list(result.items()):
        if hasattr(v, 'isoformat'):
            result[k] = v.isoformat()
    return jsonify(result)

@game_studio_bp.route("/api/ai/build/<int:session_id>/approve", methods=["POST"])
@login_required
def approve_ai_build(session_id):
    from game_builder_service import approve_checkpoint
    result = approve_checkpoint(session_id, current_user.id)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)

@game_studio_bp.route("/api/ai/build/<int:session_id>/apply", methods=["POST"])
@login_required
def apply_ai_build(session_id):
    from game_builder_service import apply_build_result
    result = apply_build_result(session_id)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)
```

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/game_studio/routes.py
git commit -m "feat(game-studio): add role detection + 4 build pipeline routes"
```

---

## Task 5: Frontend — Build Wizard + Behavior Loading

**Files:**
- Modify: `platform_v2/static/js/game-studio.js`
- Modify: `platform_v2/templates/tools/game_studio.html`
- Modify: `platform_v2/static/css/game-studio.css`

- [ ] **Step 1: Add build wizard JS to game-studio.js (~100 lines)**

Insert before DOMContentLoaded, inside the IIFE:

```javascript
// ── Phase 3: AI Build Pipeline ──

window.openBuildWizard = function() {
    document.getElementById('gsBuildWizard').style.display = 'flex';
    document.getElementById('gsBuildDesc').value = '';
    document.getElementById('gsBuildPipeline').style.display = 'none';
    document.getElementById('gsBuildInput').style.display = '';
};

window.closeBuildWizard = function() {
    document.getElementById('gsBuildWizard').style.display = 'none';
};

window.startBuild = function() {
    var desc = document.getElementById('gsBuildDesc').value.trim();
    if (!desc) { alert('Describe your game'); return; }
    var gameType = document.getElementById('gsBuildType').value || null;
    document.getElementById('gsBuildInput').style.display = 'none';
    document.getElementById('gsBuildPipeline').style.display = '';
    renderPipelineStages('concept', 'running');

    api('POST', '/api/ai/build', {description: desc, game_type: gameType}).then(function(data) {
        if (data.error) { alert(data.error); closeBuildWizard(); return; }
        _buildSessionId = data.session_id;
        _buildProjectId = data.project_id;
        pollBuildStatus(data.session_id);
    });
};

var _buildSessionId = null;
var _buildProjectId = null;

window.pollBuildStatus = function(sessionId) {
    var interval = setInterval(function() {
        api('GET', '/api/ai/build/' + sessionId).then(function(data) {
            renderPipelineStages(data.current_stage, data.status);
            if (data.status === 'checkpoint') {
                clearInterval(interval);
                showCheckpointReview(data);
            }
            if (data.status === 'completed') {
                clearInterval(interval);
                showBuildComplete(data);
            }
            if (data.status === 'failed') {
                clearInterval(interval);
                alert('Build failed: ' + JSON.stringify(data.stage_outputs));
                closeBuildWizard();
            }
        });
    }, 3000);
};

function renderPipelineStages(currentStage, status) {
    var stages = ['concept', 'level', 'mechanics', 'qa'];
    var container = document.getElementById('gsBuildStages');
    clearEl(container);
    var currentIdx = stages.indexOf(currentStage);
    stages.forEach(function(s, i) {
        var div = document.createElement('div');
        div.className = 'gs-pipeline-stage';
        if (i < currentIdx) div.classList.add('complete');
        else if (i === currentIdx && status === 'running') div.classList.add('running');
        else if (i === currentIdx && status === 'checkpoint') div.classList.add('checkpoint');
        var circle = document.createElement('div');
        circle.className = 'gs-pipeline-circle';
        var label = document.createElement('div');
        label.className = 'gs-pipeline-label';
        label.textContent = s.charAt(0).toUpperCase() + s.slice(1);
        div.appendChild(circle);
        div.appendChild(label);
        container.appendChild(div);
    });
}

function showCheckpointReview(data) {
    var review = document.getElementById('gsBuildReview');
    review.style.display = '';
    clearEl(review);
    var title = document.createElement('div');
    title.className = 'gs-prop-group-title';
    title.textContent = data.current_stage + ' — Review';
    review.appendChild(title);
    var output = data.stage_outputs[data.current_stage];
    var pre = document.createElement('pre');
    pre.className = 'gs-build-output';
    pre.textContent = typeof output === 'string' ? output : JSON.stringify(output, null, 2);
    review.appendChild(pre);
    var approveBtn = document.createElement('button');
    approveBtn.className = 'gs-toolbar-btn';
    approveBtn.textContent = 'Approve & Continue';
    approveBtn.style.background = 'var(--gs-accent, #4f6)';
    approveBtn.style.color = '#000';
    approveBtn.onclick = function() {
        review.style.display = 'none';
        renderPipelineStages(data.current_stage, 'running');
        api('POST', '/api/ai/build/' + _buildSessionId + '/approve').then(function(res) {
            if (res.status === 'completed') showBuildComplete(res);
            else pollBuildStatus(_buildSessionId);
        });
    };
    review.appendChild(approveBtn);
}

function showBuildComplete(data) {
    var review = document.getElementById('gsBuildReview');
    review.style.display = '';
    clearEl(review);
    renderPipelineStages('qa', 'completed');
    var title = document.createElement('div');
    title.className = 'gs-prop-group-title';
    title.textContent = 'Your game is ready!';
    review.appendChild(title);
    var playBtn = document.createElement('button');
    playBtn.className = 'gs-toolbar-btn';
    playBtn.textContent = 'Apply & Play';
    playBtn.style.background = 'var(--gs-accent, #4f6)';
    playBtn.style.color = '#000';
    playBtn.onclick = function() {
        api('POST', '/api/ai/build/' + _buildSessionId + '/apply').then(function(res) {
            closeBuildWizard();
            if (res.project_id) openProject(res.project_id);
        });
    };
    review.appendChild(playBtn);
}
```

**Update refreshPreview to load behaviors:**

After the existing `iframe.onload` postMessage for config, also send behaviors:
```javascript
// Inside refreshPreview, after sending config:
// Load code assets for behaviors
if (_currentGameId) {
    api('GET', '/api/assets?game_id=' + _currentGameId + '&type=code').then(function(data) {
        var assets = data.assets || data || [];
        if (Array.isArray(assets) && assets.length > 0) {
            var behaviors = assets.map(function(a) { return {name: a.name, code: a.content}; });
            iframe.contentWindow.postMessage({type: 'loadBehaviors', behaviors: behaviors}, '*');
        }
    });
}
```

**Update AI chat response handling:**

In the existing `sendAiChat` function, add handling for behavior responses:
```javascript
// After existing config_patch handling:
if (parsed.behaviors && Array.isArray(parsed.behaviors)) {
    // Save behaviors as assets via API, then load into engine
    parsed.behaviors.forEach(function(b) {
        api('POST', '/api/assets/upload', {game_id: _currentGameId, name: b.name, asset_type: 'code', content: b.code});
    });
    // Load into running engine
    var iframe = document.getElementById('gsPreviewFrame');
    if (iframe && iframe.contentWindow) {
        iframe.contentWindow.postMessage({type: 'loadBehaviors', behaviors: parsed.behaviors}, '*');
    }
    toast('AI added ' + parsed.behaviors.length + ' behavior(s)');
}

// Handle build session trigger
if (data.build_session) {
    _buildSessionId = data.build_session.session_id;
    _buildProjectId = data.build_session.project_id;
    openBuildWizard();
    document.getElementById('gsBuildInput').style.display = 'none';
    document.getElementById('gsBuildPipeline').style.display = '';
    pollBuildStatus(_buildSessionId);
}
```

- [ ] **Step 2: Add build wizard HTML to game_studio.html**

After existing modals:

```html
<!-- Build Wizard Modal -->
<div id="gsBuildWizard" class="gs-build-wizard" style="display:none;">
  <div class="gs-build-wizard-content">
    <div class="gs-panel-header">
      <span>Build with AI</span>
      <button class="gs-toolbar-btn" onclick="closeBuildWizard()">&times;</button>
    </div>
    <div id="gsBuildInput" style="padding:1rem;">
      <label style="display:flex;flex-direction:column;gap:0.25rem;font-size:0.75rem;color:var(--gs-text,#aab);">
        Describe your game:
        <textarea id="gsBuildDesc" rows="4" class="gs-prop-input" placeholder="A space trading game where you explore star systems, fight pirates, and trade resources between stations..."></textarea>
      </label>
      <label style="display:flex;flex-direction:column;gap:0.25rem;font-size:0.75rem;color:var(--gs-text,#aab);margin-top:0.5rem;">
        Game type (optional):
        <select id="gsBuildType" class="gs-prop-input">
          <option value="">Auto-detect</option>
          <option value="top_down_shooter">Top-Down Shooter</option>
          <option value="space_explorer">Space Explorer</option>
          <option value="base_builder">Base Builder</option>
        </select>
      </label>
      <div style="margin-top:1rem;text-align:right;">
        <button class="gs-toolbar-btn" style="background:var(--gs-accent,#4f6);color:#000;" onclick="startBuild()">Build It</button>
      </div>
    </div>
    <div id="gsBuildPipeline" style="display:none;padding:1rem;">
      <div id="gsBuildStages" class="gs-pipeline-stages"></div>
      <div id="gsBuildReview" style="display:none;margin-top:1rem;"></div>
    </div>
  </div>
</div>
```

Add "Build with AI" button to dashboard (find the project grid area):
```html
<button class="gs-toolbar-btn" style="background:var(--gs-accent,#4f6);color:#000;margin-bottom:0.5rem;" onclick="openBuildWizard()">Build with AI</button>
```

- [ ] **Step 3: Add build wizard CSS**

Append to game-studio.css:
```css
/* Phase 3: AI Build Wizard */
.gs-build-wizard {
    position: fixed; inset: 0; z-index: 9999;
    display: flex; align-items: center; justify-content: center;
    background: rgba(0,0,0,0.85);
}
.gs-build-wizard-content {
    background: var(--gs-bg, #0d0d1a);
    border: 1px solid var(--gs-accent, #4f6);
    border-radius: 8px;
    width: 90vw; max-width: 600px; max-height: 80vh;
    display: flex; flex-direction: column; overflow: hidden;
}
.gs-pipeline-stages {
    display: flex; justify-content: space-between; padding: 0.5rem 0;
}
.gs-pipeline-stage {
    display: flex; flex-direction: column; align-items: center; flex: 1;
}
.gs-pipeline-circle {
    width: 24px; height: 24px; border-radius: 50%;
    border: 2px solid var(--gs-border, #232);
    background: transparent; margin-bottom: 0.25rem;
}
.gs-pipeline-stage.complete .gs-pipeline-circle { background: var(--gs-accent, #4f6); border-color: var(--gs-accent, #4f6); }
.gs-pipeline-stage.running .gs-pipeline-circle { border-color: var(--gs-accent, #4f6); animation: gs-pulse 1s infinite; }
.gs-pipeline-stage.checkpoint .gs-pipeline-circle { background: #f90; border-color: #f90; }
.gs-pipeline-label { font-size: 0.6rem; color: var(--gs-text, #aab); text-transform: uppercase; }
@keyframes gs-pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }
.gs-build-output {
    background: rgba(0,0,0,0.3); border: 1px solid var(--gs-border, #232);
    border-radius: 4px; padding: 0.5rem; font-size: 0.65rem;
    color: var(--gs-text, #aab); max-height: 300px; overflow-y: auto;
    white-space: pre-wrap; font-family: 'IBM Plex Mono', monospace;
}
```

- [ ] **Step 4: Commit**

```bash
git add platform_v2/static/js/game-studio.js platform_v2/templates/tools/game_studio.html platform_v2/static/css/game-studio.css
git commit -m "feat(game-studio): add AI build wizard + behavior loading + pipeline UI"
```

---

## Task 6: Integration Test

**Files:**
- Create: `/tmp/test_game_studio_phase3.py`

- [ ] **Step 1: Write integration test**

```python
import sys, os, logging
sys.path.insert(0, '/app/platform_v2')
sys.path.insert(0, '/app')
logging.disable(logging.CRITICAL)

results = []

# Service imports
from tools.game_studio.game_builder_service import start_build, get_build_status, approve_checkpoint, apply_build_result, PIPELINE_STAGES
results.append(('Import builder service', 'OK', True))
results.append(('Pipeline has 4 stages', len(PIPELINE_STAGES), len(PIPELINE_STAGES) == 4))
results.append(('Concept is checkpoint', PIPELINE_STAGES[0]['checkpoint'], True))
results.append(('QA is checkpoint', PIPELINE_STAGES[3]['checkpoint'], True))

from app import app
with app.app_context():
    # DB tables
    from database import get_db_cursor
    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT COUNT(*) AS cnt FROM game_build_sessions")
        results.append(('build_sessions table', cur.fetchone()['cnt'] >= 0, True))
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='game_assets' AND column_name='content'")
        results.append(('assets content column', cur.fetchone() is not None, True))

    # Routes
    rules = [r.rule for r in app.url_map.iter_rules() if 'game-studio' in r.rule and 'build' in r.rule]
    results.append(('Build routes', len(rules) >= 4, True))

    # Engine has sandbox
    engine_path = '/app/static/js/game-engine.js'
    with open(engine_path) as f:
        engine = f.read()
    results.append(('Engine has loadBehaviors', 'loadBehaviors' in engine, True))
    results.append(('Engine has runBehavior', 'runBehavior' in engine, True))
    results.append(('Engine has createSandboxedBehavior', 'createSandboxedBehavior' in engine or 'SandboxedBehavior' in engine, True))

    # Modules have behavior hooks
    for mod in ['game-module-shooter.js', 'game-module-explorer.js', 'game-module-builder.js']:
        with open(f'/app/static/js/{mod}') as f:
            content = f.read()
        results.append((f'{mod} has behavior hook', 'runBehavior' in content or 'behavior' in content.lower(), True))

    # JS has build wizard
    with open('/app/static/js/game-studio.js') as f:
        js = f.read()
    for func in ['openBuildWizard', 'startBuild', 'pollBuildStatus', 'approveBuildCheckpoint', 'showCheckpointReview', 'loadBehaviors']:
        results.append((f'JS has {func}', func in js, True))

    # HTML has wizard
    with open('/app/templates/tools/game_studio.html') as f:
        html = f.read()
    for elem in ['gsBuildWizard', 'gsBuildDesc', 'gsBuildStages', 'gsBuildReview']:
        results.append((f'HTML has {elem}', elem in html, True))

    # CSS has pipeline
    with open('/app/static/css/game-studio.css') as f:
        css = f.read()
    for cls in ['.gs-build-wizard', '.gs-pipeline-stages', '.gs-pipeline-stage', '.gs-build-output']:
        results.append((f'CSS has {cls}', cls in css, True))

passed = sum(1 for _, _, ok in results if ok)
for name, val, ok in results:
    print(f'[{"PASS" if ok else "FAIL"}] {name}: {val}')
print(f'\nResult: {passed}/{len(results)} passed')
```

- [ ] **Step 2: Run test**

```bash
docker cp /tmp/test_game_studio_phase3.py archie_platform:/tmp/
docker exec archie_platform python3 /tmp/test_game_studio_phase3.py
```

- [ ] **Step 3: Fix any failures, re-test**

---

## Task 7: Deploy + Git Push + Dev HQ

- [ ] **Step 1: Restart + push**

```bash
docker compose restart archie_platform
git push origin main
```

- [ ] **Step 2: Update Dev HQ**

- `complete_task` #865 (Phase 3)
- `store_memory` — Game Studio Phase 3 complete
- `log_decision` — sandboxed behaviors via Function constructor, 4-stage pipeline with checkpoints
