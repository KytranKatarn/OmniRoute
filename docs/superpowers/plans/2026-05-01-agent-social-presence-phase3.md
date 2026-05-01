# Agent Social Presence Engine — Phase 3: Full Content Studio

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Lifestyle, Selfie, and Announcement generation modes to the Media Studio Generate tab — each type picks a department theme + scene, builds a face-consistent prompt using the agent's identity, refines it via M.U.S.E., generates via P.I.X.E.L., and pre-fills the Social Video builder with the result + S.I.G.N.A.L.-written caption.

**Architecture:** New `lifestyle_service.py` handles prompt building from `social_content_scenes.visual_prompt_template` + agent's `identity_prompt`, M.U.S.E. refinement via DHQ `visual_design` dispatch, and S.I.G.N.A.L. caption writing via existing `generate_themed_caption`. The Generate tab gains Lifestyle/Selfie/Announcement as generation sub-types that unlock a theme+scene picker step. Output stored in `media_library` with `metadata.asset_type` and `metadata.theme_id`. IP-Adapter face consistency is a future enhancement — current approach uses the agent's `identity_prompt` text for visual consistency.

**Tech Stack:** Flask + Jinja2 + vanilla JS, ComfyUI via P.I.X.E.L./DHQ (existing pipeline), LCARS aesthetic. Builds on Phase 1 (social_content_themes/scenes, theme_service.py) and Phase 2 (calendar_service.generate_themed_caption).

---

## Prerequisites (from previous phases)
- `social_content_themes` + `social_content_scenes` tables (migration 363)
- `theme_service.py` — `get_theme()`, `get_scenes_for_theme()`
- `calendar_service.py` — `generate_themed_caption()`
- `submit_generation(user_id, media_type, prompt, negative_prompt, params, owner_type, owner_id)` in `generation_service.py`
- `dispatch()` canonical signature: `dispatch(capability, prompt, module_id=...)`

---

## File Structure

| Action | Path | Purpose |
|--------|------|---------|
| Create | `platform_v2/tools/media_studio/services/lifestyle_service.py` | Prompt build, M.U.S.E. refine, caption generation, queue submit |
| Modify | `platform_v2/tools/media_studio/routes.py` | Add `POST /api/generate/lifestyle` |
| Modify | `platform_v2/tools/media_studio/templates/tools/media_studio/_tab_generate.html` | Lifestyle type card + theme/scene/mode picker step |
| Modify | `platform_v2/tools/media_studio/static/js/ms-generate.js` | Lifestyle flow: theme picker, scene picker, M.U.S.E. refine, caption preview, submit |

---

### Task 1: lifestyle_service.py

**Files:**
- Create: `platform_v2/tools/media_studio/services/lifestyle_service.py`

- [ ] **Step 1: Write the service**

```python
# platform_v2/tools/media_studio/services/lifestyle_service.py
"""Lifestyle content generation — themed prompt building, M.U.S.E. refinement, caption generation."""
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Generation type style suffixes appended to visual_prompt_template
_TYPE_SUFFIXES = {
    "lifestyle": ", environmental portrait, natural scene, photorealistic, cinematic depth of field",
    "selfie": ", close-crop selfie photo, face-forward, natural expression, soft bokeh background, authentic, photorealistic",
    "announcement": ", professional headshot, confident pose, clean background, sharp focus, photorealistic",
}


def build_lifestyle_prompt(
    agent_id: int,
    scene_id: int,
    generation_type: str = "lifestyle",
) -> Dict:
    """Build a generation prompt from an agent's identity + a scene template.

    Returns dict: prompt, negative_prompt, scene (dict), agent (dict)
    """
    from services.agent_service import get_agent
    from services.agent_social_service import get_writing_voice

    from .theme_service import get_scenes_for_theme

    # Fetch agent + scene
    agent = get_agent(agent_id)
    if not agent:
        return {"error": f"Agent {agent_id} not found"}

    from database import get_db_cursor

    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT s.*, t.name AS theme_name, t.tone AS theme_tone, t.accent_color
               FROM social_content_scenes s
               JOIN social_content_themes t ON t.id = s.theme_id
               WHERE s.id = %s""",
            (scene_id,),
        )
        scene_row = cur.fetchone()
        if not scene_row:
            return {"error": f"Scene {scene_id} not found"}
        scene = dict(scene_row)

        # Fetch agent's identity_prompt from agent_portraits
        cur.execute(
            "SELECT identity_prompt, canonical_image_path FROM agent_portraits WHERE agent_id = %s",
            (agent_id,),
        )
        portrait_row = cur.fetchone()

    identity = portrait_row["identity_prompt"] if portrait_row else ""
    canonical_path = portrait_row["canonical_image_path"] if portrait_row else ""

    # Fill scene template
    agent_description = identity or (
        f"{agent.get('display_name', '')} — {agent.get('department', '')} professional"
    )
    template = scene.get("visual_prompt_template", "{agent_description}")
    base_prompt = template.replace("{agent_description}", agent_description)

    # Append generation-type style
    suffix = _TYPE_SUFFIXES.get(generation_type, _TYPE_SUFFIXES["lifestyle"])
    prompt = base_prompt + suffix

    # Style directive from scene
    if scene.get("style_directive"):
        prompt += f", {scene['style_directive']}"

    negative_prompt = (
        "cartoon, anime, illustration, low quality, blurry, watermark, "
        "text overlay, duplicate faces, disfigured, extra limbs"
    )

    return {
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "agent": {
            "id": agent_id,
            "name": agent.get("display_name") or agent.get("name"),
            "department": agent.get("department"),
            "canonical_path": canonical_path,
        },
        "scene": scene,
        "generation_type": generation_type,
    }


def refine_prompt_with_muse(prompt: str, scene_description: str = "") -> str:
    """Send prompt to M.U.S.E. via DHQ visual_design dispatch for creative refinement.

    Falls back to original prompt on failure (non-blocking).
    """
    from tools.department_hq.services.department_dispatcher import dispatch

    refine_instruction = (
        f"Refine this image generation prompt to make it more vivid and visually specific "
        f"while keeping the same subject and composition. "
        f"Return ONLY the refined prompt, no explanation. "
        f"Original: {prompt}"
    )
    if scene_description:
        refine_instruction += f" Scene context: {scene_description}"

    try:
        result = dispatch("visual_design", refine_instruction, module_id="lifestyle_service")
        if result and result.success and result.response:
            refined = result.response.strip()
            # Sanity check: refined prompt should be longer than original
            if len(refined) > 30:
                return refined
    except Exception as exc:
        logger.warning("[lifestyle] M.U.S.E. refinement failed (using original): %s", exc)
    return prompt


def generate_lifestyle_content(
    user_id: int,
    agent_id: int,
    scene_id: int,
    generation_type: str = "lifestyle",
    refine: bool = True,
) -> Dict:
    """Full pipeline: build prompt → M.U.S.E. refine → submit to queue → generate caption.

    Returns: {queue_id, prompt, refined_prompt, caption, agent, scene, generation_type}
    """
    from .calendar_service import generate_themed_caption
    from .generation_service import submit_generation

    # Step 1: build prompt
    built = build_lifestyle_prompt(agent_id, scene_id, generation_type)
    if "error" in built:
        return built

    prompt = built["prompt"]
    scene = built["scene"]
    agent = built["agent"]

    # Step 2: M.U.S.E. refine (optional)
    refined_prompt = refine_prompt_with_muse(prompt, scene.get("description", "")) if refine else prompt

    # Step 3: submit to generation queue (owner_type=agent so it appears in Gallery)
    result = submit_generation(
        user_id=user_id,
        media_type="image",
        prompt=refined_prompt,
        negative_prompt=built["negative_prompt"],
        params={
            "width": 1024,
            "height": 1024,
            "steps": 30,
            "seed": -1,
            "asset_type": generation_type,
            "theme_id": scene.get("theme_id"),
            "scene_id": scene_id,
        },
        owner_type="agent",
        owner_id=agent_id,
    )

    if "error" in result:
        return result

    # Step 4: S.I.G.N.A.L. generates caption asynchronously (best-effort)
    caption = ""
    try:
        caption = generate_themed_caption(agent_id, scene["theme_id"], scene.get("description", ""))
    except Exception as exc:
        logger.warning("[lifestyle] Caption generation failed (non-blocking): %s", exc)

    return {
        "queue_id": result.get("queue_id"),
        "status": result.get("status", "pending"),
        "prompt": prompt,
        "refined_prompt": refined_prompt,
        "caption": caption,
        "agent": agent,
        "scene": scene,
        "generation_type": generation_type,
    }
```

- [ ] **Step 2: Verify import in container**

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0, '/app')
from tools.media_studio.services.lifestyle_service import build_lifestyle_prompt
# Use agent 141 (S.I.G.N.A.L.) and scene 25 (Sunrise Beach from live-dream theme)
result = build_lifestyle_prompt(141, 25, 'lifestyle')
print('OK' if 'prompt' in result else 'ERROR: ' + str(result))
if 'prompt' in result:
    print('Agent:', result['agent']['name'])
    print('Scene:', result['scene']['name'])
    print('Prompt snippet:', result['prompt'][:80])
" 2>&1
```

Expected: `OK`, agent name `S.I.G.N.A.L.`, scene `Sunrise Beach`, prompt starting with the scene template filled with identity.

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/media_studio/services/lifestyle_service.py
git commit -m "feat(social-presence): lifestyle_service.py — prompt build, M.U.S.E. refine, caption, queue submit"
```

---

### Task 2: /api/generate/lifestyle Route

**Files:**
- Modify: `platform_v2/tools/media_studio/routes.py`

> **Context:** `routes.py` already has `POST /api/generate` (plain image generation). Add a new route `POST /api/generate/lifestyle` after the Content Themes section (around the end of the file). Pattern: thin route, calls service, returns JSON.

- [ ] **Step 1: Find insertion point**

```bash
grep -n "api_get_themes\|api_update_theme\|# ─── Content Themes" /mnt/archie_brain/platform_v2/tools/media_studio/routes.py | tail -5
```

Note the line number of the last theme route (the PATCH route), to add after it.

- [ ] **Step 2: Add the route**

After the last `@media_studio_bp.route("/api/themes/...")` block, add:

```python
@media_studio_bp.route("/api/generate/lifestyle", methods=["POST"])
@login_required
def api_generate_lifestyle():
    """Generate a lifestyle/selfie/announcement image for an agent using a theme scene.

    Body: {agent_id, scene_id, generation_type: 'lifestyle'|'selfie'|'announcement', refine: bool}
    Returns: {queue_id, status, prompt, refined_prompt, caption, agent, scene, generation_type}
    """
    from .services.lifestyle_service import generate_lifestyle_content

    data = request.get_json() or {}
    agent_id = data.get("agent_id")
    scene_id = data.get("scene_id")
    generation_type = data.get("generation_type", "lifestyle")
    refine = data.get("refine", True)

    if not agent_id or not scene_id:
        return jsonify({"error": "agent_id and scene_id required"}), 400
    if generation_type not in ("lifestyle", "selfie", "announcement"):
        return jsonify({"error": "generation_type must be lifestyle, selfie, or announcement"}), 400

    result = generate_lifestyle_content(
        user_id=current_user.id,
        agent_id=int(agent_id),
        scene_id=int(scene_id),
        generation_type=generation_type,
        refine=refine,
    )

    if "error" in result:
        return jsonify(result), 400
    return jsonify(result), 201
```

- [ ] **Step 3: Restart and test**

```bash
docker compose restart archie_platform && sleep 4
```

Then test via Playwright evaluate (when logged in):
```javascript
fetch('/tools/media-studio/api/themes', {credentials:'same-origin'}).then(r=>r.json()).then(d=>d.themes[0].id)
```
Use the theme_id to find a scene_id, then:
```javascript
fetch('/tools/media-studio/api/generate/lifestyle', {
  method:'POST', credentials:'same-origin',
  headers:{'Content-Type':'application/json'},
  body: JSON.stringify({agent_id:141, scene_id:25, generation_type:'lifestyle', refine:false})
}).then(r=>r.json()).then(console.log)
```

Expected: `{queue_id: N, status: 'pending', prompt: '...', caption: '...', agent: {...}, scene: {...}}`

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/media_studio/routes.py
git commit -m "feat(social-presence): POST /api/generate/lifestyle route — themed lifestyle/selfie/announcement generation"
```

---

### Task 3: Generate Tab — Lifestyle Mode HTML

**Files:**
- Modify: `platform_v2/tools/media_studio/templates/tools/media_studio/_tab_generate.html`

> **Context:** The Generate tab has 3 type cards: Portrait, Brand Asset, Social Content. We need to add Lifestyle/Selfie/Announcement. The cleanest approach: add them as a 2nd row of type cards that appears when "Social Content" is NOT selected and the user wants themed content. Actually, simpler: add a 4th card "Lifestyle / Selfie" that reveals a theme+scene picker step between Step 1 and Step 2 (agent picker).

- [ ] **Step 1: Add "Lifestyle / Selfie" type card**

In `_tab_generate.html`, find the 3-card grid and add a 4th card:

```html
<div class="ms-gen-type-card" data-type="lifestyle" onclick="msGenerate.selectType('lifestyle')">
  <div style="font-size:1.4rem;margin-bottom:6px;">&#x1F304;</div>
  <div style="font-family:'Orbitron',sans-serif;font-size:0.65rem;color:#888;letter-spacing:1px;">LIFESTYLE</div>
  <div style="font-size:0.62rem;color:#666;margin-top:4px;">Scene-based themed social content</div>
</div>
```

Change the grid to `grid-template-columns: 1fr 1fr` (2 rows of 2) or `1fr 1fr 1fr 1fr` (4 across):

The existing grid style is `grid-template-columns:1fr 1fr 1fr`. Change to:
```
grid-template-columns:1fr 1fr;
```

- [ ] **Step 2: Add Lifestyle step — theme + scene + mode picker**

After the existing `#msGenStep2` (agent picker) block, add:

```html
<!-- Step 1b: Lifestyle scene picker (shown when type=lifestyle) -->
<div id="msGenLifestyleStep" style="margin-bottom:24px;display:none;">
  <div style="color:#555;font-size:0.6rem;letter-spacing:2px;text-transform:uppercase;margin-bottom:8px;">
    1b &#x2014; Scene &amp; Mode
  </div>
  <!-- Generation mode -->
  <div style="display:flex;gap:6px;margin-bottom:10px;">
    <button class="ms-gen-mode-btn ms-gen-mode-active" data-mode="lifestyle"
      onclick="msGenerate.selectMode('lifestyle')"
      style="background:rgba(59,130,246,0.12);border:1px solid rgba(59,130,246,0.4);color:#60a5fa;padding:4px 10px;border-radius:3px;font-size:0.6rem;cursor:pointer;">
      &#x1F304; Lifestyle
    </button>
    <button class="ms-gen-mode-btn" data-mode="selfie"
      onclick="msGenerate.selectMode('selfie')"
      style="background:transparent;border:1px solid #333;color:#555;padding:4px 10px;border-radius:3px;font-size:0.6rem;cursor:pointer;">
      &#x1F933; Selfie
    </button>
    <button class="ms-gen-mode-btn" data-mode="announcement"
      onclick="msGenerate.selectMode('announcement')"
      style="background:transparent;border:1px solid #333;color:#555;padding:4px 10px;border-radius:3px;font-size:0.6rem;cursor:pointer;">
      &#x1F4E2; Announcement
    </button>
  </div>
  <!-- Theme picker -->
  <div style="color:#555;font-size:0.58rem;margin-bottom:5px;">Theme:</div>
  <div id="msGenThemePicker" style="display:flex;flex-wrap:wrap;gap:5px;margin-bottom:10px;"></div>
  <!-- Scene picker -->
  <div id="msGenScenePickerWrap" style="display:none;">
    <div style="color:#555;font-size:0.58rem;margin-bottom:5px;">Scene:</div>
    <div id="msGenScenePicker" style="display:flex;flex-wrap:wrap;gap:5px;"></div>
  </div>
</div>

<!-- Lifestyle result preview (shown after generation queued) -->
<div id="msGenLifestylePreview" style="display:none;margin-bottom:16px;padding:12px;background:#0d1117;border:1px solid rgba(59,130,246,0.2);border-radius:5px;">
  <div style="color:#555;font-size:0.58rem;letter-spacing:1px;margin-bottom:8px;">GENERATION QUEUED</div>
  <div id="msGenLifestyleCaptionLabel" style="color:#60a5fa;font-size:0.62rem;margin-bottom:4px;">S.I.G.N.A.L. Caption Draft:</div>
  <div id="msGenLifestyleCaption" style="color:#ccc;font-size:0.7rem;font-family:'IBM Plex Mono',monospace;line-height:1.4;margin-bottom:8px;"></div>
  <div style="display:flex;gap:6px;">
    <button onclick="msGenerate.sendToSocialVideo()"
      style="background:rgba(139,92,246,0.12);border:1px solid rgba(139,92,246,0.4);color:#a78bfa;padding:5px 12px;border-radius:4px;font-size:0.6rem;cursor:pointer;">
      &#x1F3AC; Use in Social Video
    </button>
  </div>
</div>
```

- [ ] **Step 3: Restart and verify HTML renders**

```bash
docker compose restart archie_platform
```

Navigate to Media Studio → Generate tab. Should see 4 type cards (2×2 layout). Clicking "Lifestyle / Selfie" should make the card highlight but Step 1b won't appear yet (that's wired in Task 4).

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/media_studio/templates/tools/media_studio/_tab_generate.html
git commit -m "feat(social-presence): Generate tab — Lifestyle type card + scene/mode picker HTML"
```

---

### Task 4: ms-generate.js — Lifestyle Flow

**Files:**
- Modify: `platform_v2/tools/media_studio/static/js/ms-generate.js`

> **Context:** Current ms-generate.js has: `_type`, `_agentId` variables; `selectType(type)`, `selectAgent(agentId)`, `submit()` methods. We add: `_mode`, `_themeId`, `_sceneId` variables; `selectMode(mode)`, `_loadThemesForLifestyle()`, `selectThemeForScene(themeId)`, `selectScene(sceneId)`, `submitLifestyle()`, `sendToSocialVideo()` methods.

- [ ] **Step 1: Add new module-level variables**

After `var _agentId = null;` add:

```javascript
  var _mode = 'lifestyle';
  var _themeId = null;
  var _sceneId = null;
  var _lifestyleResult = null;
```

- [ ] **Step 2: Update `selectType()` to handle lifestyle**

In the existing `selectType(type)` method, add a case before the `var step2` section:

```javascript
      if (type === 'lifestyle') {
        var step2 = _el('msGenStep2');
        if (step2) step2.style.display = 'block';
        var lifestyleStep = _el('msGenLifestyleStep');
        if (lifestyleStep) lifestyleStep.style.display = 'block';
        var step3 = _el('msGenStep3');
        if (step3) step3.style.display = 'none';
        msGenerate._loadThemesForLifestyle();
        return;
      }
      // hide lifestyle step for other types
      var lifestyleStep = _el('msGenLifestyleStep');
      if (lifestyleStep) lifestyleStep.style.display = 'none';
```

- [ ] **Step 3: Add `selectMode()`, `_loadThemesForLifestyle()`, `selectThemeForScene()`, `selectScene()`, `submitLifestyle()`, `sendToSocialVideo()`**

Add to `window.msGenerate`:

```javascript
    selectMode: function (mode) {
      _mode = mode;
      document.querySelectorAll('.ms-gen-mode-btn').forEach(function (b) {
        var active = b.dataset.mode === mode;
        b.classList.toggle('ms-gen-mode-active', active);
        b.style.background = active ? 'rgba(59,130,246,0.12)' : 'transparent';
        b.style.borderColor = active ? 'rgba(59,130,246,0.4)' : '#333';
        b.style.color = active ? '#60a5fa' : '#555';
      });
    },

    _loadThemesForLifestyle: function () {
      var picker = _el('msGenThemePicker');
      if (!picker || picker.childElementCount > 0) return;
      _get('/api/themes').then(function (data) {
        picker.textContent = '';
        (data.themes || []).forEach(function (theme) {
          var btn = document.createElement('button');
          btn.dataset.themeId = theme.id;
          btn.style.cssText = 'background:#0d1117;border:1px solid ' + (theme.accent_color||'#333') + '44;' +
            'color:' + (theme.accent_color||'#888') + ';padding:4px 10px;border-radius:3px;font-size:0.58rem;cursor:pointer;';
          btn.textContent = theme.name;
          btn.onclick = (function (t) { return function () { msGenerate.selectThemeForScene(t.id, t.accent_color); }; })(theme);
          picker.appendChild(btn);
        });
      }).catch(function (err) { console.warn('[msGen] loadThemes failed:', err); });
    },

    selectThemeForScene: function (themeId, accentColor) {
      _themeId = themeId;
      _sceneId = null;
      document.querySelectorAll('#msGenThemePicker button').forEach(function (b) {
        var active = String(b.dataset.themeId) === String(themeId);
        b.style.background = active ? (accentColor||'#3b82f6') + '22' : '#0d1117';
        b.style.borderColor = active ? (accentColor||'#3b82f6') : (accentColor||'#333') + '44';
      });
      var wrap = _el('msGenScenePickerWrap');
      var scenePicker = _el('msGenScenePicker');
      if (wrap) wrap.style.display = 'none';
      if (scenePicker) scenePicker.textContent = '';
      _get('/api/themes/' + themeId + '/scenes').then(function (data) {
        if (!scenePicker) return;
        (data.scenes || []).forEach(function (scene) {
          var btn = document.createElement('button');
          btn.dataset.sceneId = scene.id;
          btn.style.cssText = 'background:#0d1117;border:1px solid #1a2a3a;color:#888;padding:5px 10px;' +
            'border-radius:3px;font-size:0.6rem;cursor:pointer;text-align:left;';
          btn.textContent = scene.name + (scene.generation_type === 'selfie' ? ' 🤳' : '');
          btn.onclick = (function (s) { return function () { msGenerate.selectScene(s); }; })(scene);
          scenePicker.appendChild(btn);
        });
        if (wrap) wrap.style.display = 'block';
      }).catch(function (err) { console.warn('[msGen] loadScenes failed:', err); });
    },

    selectScene: function (scene) {
      _sceneId = scene.id;
      document.querySelectorAll('#msGenScenePicker button').forEach(function (b) {
        var active = String(b.dataset.sceneId) === String(scene.id);
        b.style.background = active ? 'rgba(59,130,246,0.12)' : '#0d1117';
        b.style.borderColor = active ? '#3b82f6' : '#1a2a3a';
        b.style.color = active ? '#60a5fa' : '#888';
      });
      // Auto-select mode from scene generation_type
      if (scene.generation_type && window.msGenerate) {
        msGenerate.selectMode(scene.generation_type);
      }
    },

    submitLifestyle: function () {
      var statusEl = _el('msGenStatus');
      if (!_agentId) {
        if (statusEl) { statusEl.style.color = 'rgba(239,68,68,.9)'; statusEl.textContent = '⚠ Select an agent first.'; }
        return;
      }
      if (!_sceneId) {
        if (statusEl) { statusEl.style.color = 'rgba(239,68,68,.9)'; statusEl.textContent = '⚠ Select a scene first.'; }
        return;
      }
      var btn = _el('msGenBtn');
      if (btn) btn.disabled = true;
      if (statusEl) { statusEl.style.color = '#888'; statusEl.textContent = '⏳ M.U.S.E. refining → P.I.X.E.L. generating…'; }

      _post('/api/generate/lifestyle', {
        agent_id: _agentId,
        scene_id: _sceneId,
        generation_type: _mode,
        refine: true,
      }).then(function (data) {
        _lifestyleResult = data;
        if (btn) btn.disabled = false;
        if (statusEl) { statusEl.style.color = 'rgba(34,197,94,.9)'; statusEl.textContent = '✓ Queued #' + data.queue_id + ' — check Queue tab'; }
        var preview = _el('msGenLifestylePreview');
        var captionEl = _el('msGenLifestyleCaption');
        if (preview) preview.style.display = 'block';
        if (captionEl) captionEl.textContent = data.caption || '(S.I.G.N.A.L. generating caption…)';
        setTimeout(function () { switchMsTab('queue'); }, 2000);
      }).catch(function (err) {
        if (btn) btn.disabled = false;
        if (statusEl) { statusEl.style.color = 'rgba(239,68,68,.9)'; statusEl.textContent = '⚠ Failed: ' + err.message; }
      });
    },

    sendToSocialVideo: function () {
      if (!_lifestyleResult) return;
      switchMsTab('social-video');
      setTimeout(function () {
        if (_themeId && window.msSocialVideo) msSocialVideo.selectThemeById(_themeId);
        var quoteEl = document.getElementById('msSvQuote');
        if (quoteEl && _lifestyleResult.caption) quoteEl.value = _lifestyleResult.caption;
      }, 350);
    },
```

- [ ] **Step 4: Update `submit()` to dispatch to `submitLifestyle()` when type is lifestyle**

In the existing `submit: function ()` method, add at the very top:

```javascript
      if (_type === 'lifestyle') { msGenerate.submitLifestyle(); return; }
```

- [ ] **Step 5: Restart and test full flow**

```bash
docker compose restart archie_platform
```

Navigate to Generate tab:
1. Click "Lifestyle / Selfie" card → agent picker + lifestyle step appear
2. Select agent (e.g. S.I.G.N.A.L.)
3. Click "Live the Dream" theme → 3 scene buttons appear
4. Click "Sunrise Beach" scene → highlights
5. Click "⚡ GENERATE via P.I.X.E.L." → status shows "M.U.S.E. refining…" then "Queued #N"
6. Caption preview appears below
7. "Use in Social Video" button → switches to Social Video tab with caption pre-filled

- [ ] **Step 6: Commit**

```bash
git add platform_v2/tools/media_studio/static/js/ms-generate.js
git commit -m "feat(social-presence): ms-generate.js — lifestyle mode: theme/scene picker, M.U.S.E. refine, caption preview, Social Video routing"
```

---

### Task 5: Push + End-to-End Verification

- [ ] **Step 1: Push all commits**

```bash
git push origin main
```

- [ ] **Step 2: Verify service**

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0, '/app')
from tools.media_studio.services.lifestyle_service import build_lifestyle_prompt
r = build_lifestyle_prompt(141, 25, 'selfie')
print('OK' if 'prompt' in r else 'ERROR:', r.get('error',''))
print('Type suffix in prompt:', 'selfie photo' in r.get('prompt',''))
" 2>&1
```

Expected: `OK`, `True`

- [ ] **Step 3: Verify route responds**

In Playwright (logged in):
```javascript
fetch('/tools/media-studio/api/generate/lifestyle', {
  method:'POST', credentials:'same-origin',
  headers:{'Content-Type':'application/json'},
  body: JSON.stringify({agent_id:141, scene_id:25, generation_type:'lifestyle', refine:false})
}).then(r=>r.status + ' ' + r.url)
```

Expected: `201 http://192.168.1.200:3000/tools/media-studio/api/generate/lifestyle`

- [ ] **Step 4: Full browser flow**

Navigate to Media Studio → Generate tab:
- [ ] 4 type cards visible (2×2 layout)
- [ ] Click "Lifestyle" → Step 1b (mode buttons + theme picker) appears
- [ ] Select agent → agent picker highlights
- [ ] Click a theme → scene buttons appear
- [ ] Click a scene → scene highlights, mode auto-sets
- [ ] Click Generate → queues successfully, caption preview shows
- [ ] Click "Use in Social Video" → Social Video tab opens with caption

---

## IP-Adapter (Future Enhancement)

When ComfyUI IP-Adapter nodes are confirmed installed:
1. Create `static/workflows/lifestyle-ipadapter.json` — workflow that loads `ip_adapter_plus_face_sd15.bin`, uses canonical portrait as face reference, merges with scene prompt
2. In `generate_lifestyle_content()`, pass `params={"workflow": "lifestyle-ipadapter", "face_reference_path": agent["canonical_path"]}` to `submit_generation()`
3. The media_generation_worker picks up the workflow from params and routes to ComfyUI accordingly

Current text-prompt approach already delivers strong consistency via `identity_prompt` — IP-Adapter is an upgrade, not a blocker.

---

## What This Completes

With Phase 3 shipped, the full Agent Social Presence Engine pipeline is live:

| Phase | What it delivers |
|-------|-----------------|
| Phase 1 | 9 department themes + scene library + Social Video Step 0 theme picker |
| Phase 2 | Content Calendar week grid + auto-suggest worker (daily 8am) |
| Phase 3 | Full content studio — lifestyle/selfie generation from themes + scenes, M.U.S.E. refine, S.I.G.N.A.L. caption, Social Video routing |

Per-agent social accounts (Task #2511) layers on top with zero architecture changes — just a `posted_as` field in the posting step.
