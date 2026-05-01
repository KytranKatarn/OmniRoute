# Agent Social Presence Engine — Phase 1: Theme & Scene Engine

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Kytran Empowerment's Social Video builder a department-themed content system — 9 themes (one per agent department), each with 3-5 visual scenes, auto-filling the Social Video builder and browsable from the Gallery Brand section.

**Architecture:** New `social_content_themes` and `social_content_scenes` DB tables seeded with 9 department themes and 27 scenes. `theme_service.py` handles all DB access. Media Studio Social Video tab gains a Step 0 theme picker. Gallery Brand section becomes a theme library. DHQ S.I.G.N.A.L. tab gains a Themes sub-tab for management.

**Tech Stack:** Flask + Jinja2 + vanilla JS, PostgreSQL, LCARS aesthetic. Pattern: thin routes call service functions, no inline SQL in routes. All innerHTML in plan code samples is for trusted internal data (agent names, theme names from DB) — not user input.

---

## Curator Agent IDs (confirmed from DB)

| Theme | Curator | Agent ID |
|-------|---------|----------|
| Faith & Strength | F.A.I.T.H. | 352 |
| Wellness & Healing | V.I.T.A.L. | 148 |
| Legal Empowerment | G.A.V.E.L. | 147 |
| Build & Innovate | F.O.R.G.E. | 136 |
| Financial Freedom | L.E.D.G.E.R. | 144 |
| Protect & Serve | V.I.G.I.L. | 3 |
| Culture & People | K.I.N. | 145 |
| Create Without Limits | M.U.S.E. | 138 |
| Live the Dream | S.I.G.N.A.L. | 141 |

---

## File Structure

| Action | Path | Purpose |
|--------|------|---------|
| Create | `database/migrations/363_social_content_themes.sql` | Tables + seed 9 themes + 27 scenes |
| Create | `platform_v2/tools/media_studio/services/theme_service.py` | CRUD for themes and scenes |
| Modify | `platform_v2/tools/media_studio/routes.py` | 3 theme API routes |
| Modify | `platform_v2/tools/media_studio/templates/tools/media_studio/_tab_social_video.html` | Step 0 theme picker HTML |
| Modify | `platform_v2/tools/media_studio/static/js/ms-social-video.js` | Theme loading + auto-fill |
| Modify | `platform_v2/tools/media_studio/templates/tools/media_studio/_tab_gallery.html` | Brand theme library panel |
| Modify | `platform_v2/tools/media_studio/static/js/ms-gallery.js` | Brand subject → theme cards |
| Create | `platform_v2/tools/department_hq/theme_routes.py` | DHQ S.I.G.N.A.L. Themes API |
| Modify | `platform_v2/tools/department_hq/__init__.py` | Register theme_routes |

---

### Task 1: DB Migration — social_content_themes + social_content_scenes

**Files:**
- Create: `database/migrations/363_social_content_themes.sql`

- [ ] **Step 1: Write the migration file**

```sql
-- database/migrations/363_social_content_themes.sql
CREATE TABLE IF NOT EXISTS social_content_themes (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    slug VARCHAR(50) UNIQUE NOT NULL,
    department VARCHAR(100),
    curator_agent_id INTEGER REFERENCES agents(id),
    tone TEXT,
    hashtags TEXT[] DEFAULT '{}',
    music_mood VARCHAR(50) DEFAULT 'uplifting',
    accent_color VARCHAR(7) DEFAULT '#8b5cf6',
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS social_content_scenes (
    id SERIAL PRIMARY KEY,
    theme_id INTEGER REFERENCES social_content_themes(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    visual_prompt_template TEXT NOT NULL,
    style_directive TEXT,
    image_aspect VARCHAR(10) DEFAULT 'square',
    generation_type VARCHAR(20) DEFAULT 'lifestyle',
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sct_slug ON social_content_themes(slug);
CREATE INDEX IF NOT EXISTS idx_scs_theme ON social_content_scenes(theme_id);

INSERT INTO social_content_themes
    (name, slug, department, curator_agent_id, tone, hashtags, music_mood, accent_color)
VALUES
('Faith & Strength',      'faith-strength',     'Medical & Wellness',         352, 'Spiritual, hopeful, believe in yourself',     ARRAY['#FaithAndStrength','#KytranEmpowerment','#BelieveInYourself'], 'ambient',      '#f59e0b'),
('Wellness & Healing',    'wellness-healing',   'Medical & Wellness',         148, 'Nurturing, grounding, health-forward',        ARRAY['#WellnessJourney','#KytranEmpowerment','#HealingVibes'],       'calm',         '#22c55e'),
('Legal Empowerment',     'legal-empowerment',  'Legal & Regulatory',         147, 'Bold, empowering, know your rights',          ARRAY['#LegalEmpowerment','#KytranEmpowerment','#KnowYourRights'],     'professional', '#ef4444'),
('Build & Innovate',      'build-innovate',     'Engineering & Technology',   136, 'Forward-thinking, ambitious, maker energy',   ARRAY['#BuildAndInnovate','#KytranEmpowerment','#Innovation'],         'uplifting',    '#3b82f6'),
('Financial Freedom',     'financial-freedom',  'Finance & Accounting',       144, 'Smart, strategic, build legacy',              ARRAY['#FinancialFreedom','#KytranEmpowerment','#BuildWealth'],         'professional', '#10b981'),
('Protect & Serve',       'protect-serve',      'Security & Compliance',        3, 'Protective, trustworthy, safety-first',       ARRAY['#ProtectAndServe','#KytranEmpowerment','#SecurityFirst'],       'calm',         '#6366f1'),
('Culture & People',      'culture-people',     'Human Resources & Culture',  145, 'Warm, inclusive, our people are our power',   ARRAY['#CultureAndPeople','#KytranEmpowerment','#TeamWork'],           'uplifting',    '#f97316'),
('Create Without Limits', 'create-limits',      'Creative & Design',          138, 'Expressive, vibrant, create without limits',  ARRAY['#CreateWithoutLimits','#KytranEmpowerment','#CreativeLife'],    'ambient',      '#a855f7'),
('Live the Dream',        'live-dream',         'Marketing & Communications', 141, 'Aspirational, personal, relatable, live fully', ARRAY['#LiveTheDream','#KytranEmpowerment','#MondayMotivation'],   'uplifting',    '#ec4899')
ON CONFLICT (slug) DO NOTHING;

-- 3 scenes per theme (27 total)
INSERT INTO social_content_scenes
    (theme_id, name, description, visual_prompt_template, style_directive, generation_type, sort_order)
SELECT t.id, s.name, s.description, s.prompt, s.style, s.gtype, s.sorder
FROM social_content_themes t
JOIN (VALUES
  ('faith-strength',    'Sunrise Prayer',         'Golden hour, meditative',         '{agent_description}, standing at sunrise, arms open, golden light, peaceful, spiritual atmosphere, photorealistic, cinematic', 'warm golden tones, soft bokeh, devotional', 'lifestyle', 1),
  ('faith-strength',    'Candlelight Reflection', 'Intimate, warm, contemplative',   '{agent_description}, seated near candles, eyes closed, peaceful, warm amber light, photorealistic',                           'warm amber, intimate, sacred',              'selfie',    2),
  ('faith-strength',    'Community Gathering',    'Group energy, spiritual',          '{agent_description}, smiling warmly in diverse community gathering, natural light, authentic, photorealistic',                  'joyful, communal, natural light',           'lifestyle', 3),
  ('wellness-healing',  'Morning Yoga',           'Peaceful, sunrise, outdoors',      '{agent_description}, in yoga pose outdoors at sunrise, serene, nature background, photorealistic',                            'soft morning light, greens and golds',      'lifestyle', 1),
  ('wellness-healing',  'Nature Walk',            'Forest path, grounded, candid',    '{agent_description}, walking on forest path, candid shot, dappled sunlight, relaxed smile, photorealistic',                   'green tones, natural light, candid energy', 'selfie',    2),
  ('wellness-healing',  'Mindful Meal',           'Healthy food, cozy, intentional',  '{agent_description}, at bright table with colorful healthy food, warm smile, natural light kitchen, photorealistic',          'bright airy, wellness colors, intentional', 'lifestyle', 3),
  ('legal-empowerment', 'Confident at Desk',      'Professional, powerful, focused',  '{agent_description}, at professional desk with books and documents, confident posture, warm office lighting, photorealistic',  'deep wood tones, powerful, sharp',          'lifestyle', 1),
  ('legal-empowerment', 'Advocacy Moment',        'Speaking up, community, passion',  '{agent_description}, speaking passionately to small group outdoors, gesturing, diverse crowd, natural light, photorealistic', 'natural light, community energy, determined','lifestyle', 2),
  ('legal-empowerment', 'Victory Celebration',    'Achievement, joy, milestone',      '{agent_description}, celebrating with arms raised, bright background, big smile, confetti, photorealistic',                   'bright celebratory, high energy, triumph',  'selfie',    3),
  ('build-innovate',    'Late Night Build',       'Tech, focused, maker energy',      '{agent_description}, at workstation with multiple screens, focused, blue screen glow, late night, photorealistic',             'cool blue light, tech atmosphere, intense', 'lifestyle', 1),
  ('build-innovate',    'Tech Conference',        'Networking, ideas, energy',         '{agent_description}, at tech conference, engaged in conversation, bright event lighting, professional casual, photorealistic', 'modern event space, professional, energetic','lifestyle', 2),
  ('build-innovate',    'Maker Moment',           'Creating, hands-on, proud',         '{agent_description}, holding finished project, proud smile, workshop background, natural light, photorealistic',               'warm workshop light, authentic pride',      'selfie',    3),
  ('financial-freedom', 'Growth Mindset',         'Confident, professional, forward',  '{agent_description}, standing in modern office with city view, confident pose, sharp attire, photorealistic',                 'corporate clean, upward energy, sharp',     'lifestyle', 1),
  ('financial-freedom', 'Vision Board',           'Intentional, planning, ambitious',  '{agent_description}, reviewing whiteboard or planning wall, focused, bright modern space, photorealistic',                    'bright modern space, strategic, clean',     'lifestyle', 2),
  ('financial-freedom', 'Legacy Moment',          'Milestone, reflection, pride',      '{agent_description}, looking out floor-to-ceiling window at city skyline, reflective, golden hour, photorealistic',           'golden hour, aspirational, contemplative',  'selfie',    3),
  ('protect-serve',     'Vigilant Professional',  'Alert, trustworthy, composed',      '{agent_description}, in data center or secure facility, composed, professional attire, blue LED lighting, photorealistic',    'cool blue tones, secure atmosphere',        'lifestyle', 1),
  ('protect-serve',     'Community Watch',        'Community, caring, protective',     '{agent_description}, outdoors in neighborhood, friendly but alert, natural daylight, approachable, photorealistic',            'natural daylight, community warmth',        'lifestyle', 2),
  ('protect-serve',     'Safety Awareness',       'Educational, clear, direct',        '{agent_description}, at workshop or briefing, presenting to small group, engaged audience, professional, photorealistic',      'clean professional lighting, authoritative','lifestyle', 3),
  ('culture-people',    'Team Celebration',       'Joy, togetherness, milestone',      '{agent_description}, celebrating with diverse team, arms around colleagues, big smiles, confetti, photorealistic',             'warm celebratory, diverse, joyful',         'lifestyle', 1),
  ('culture-people',    'Welcoming Moment',       'Onboarding, inclusive, warm',       '{agent_description}, warmly welcoming someone new, handshake or open gesture, bright modern office, photorealistic',          'bright welcoming, inclusive, warm tones',   'lifestyle', 2),
  ('culture-people',    'Our People',             'Candid, authentic, human',           '{agent_description}, candid shot laughing with colleagues, office or outdoor casual, genuine moment, photorealistic',          'candid natural light, authentic warmth',    'selfie',    3),
  ('create-limits',     'Art Studio',             'Creative, expressive, process',     '{agent_description}, in vibrant art studio surrounded by creative work, engaged in process, paint or design tools, photorealistic', 'colorful studio, vibrant palette',       'lifestyle', 1),
  ('create-limits',     'Inspiration Board',      'Ideas, vision, artistic',            '{agent_description}, reviewing mood board or inspiration wall, thoughtful, creative space, photorealistic',                   'artistic space, warm creative light',       'lifestyle', 2),
  ('create-limits',     'Finished Piece',         'Pride, achievement, artistic',       '{agent_description}, holding or beside finished creative work, proud genuine smile, studio backdrop, photorealistic',         'gallery or studio lighting, pride',         'selfie',    3),
  ('live-dream',        'Sunrise Beach',          'Golden hour, horizon, hopeful',      '{agent_description}, at sunrise beach, looking toward horizon, golden light, casual attire, cinematic depth, photorealistic', 'golden hour, cinematic, aspirational',      'lifestyle', 1),
  ('live-dream',        'City Rooftop',           'Urban, reflective, evening',          '{agent_description}, on rooftop with city skyline at dusk, relaxed pose, city lights, casual stylish attire, photorealistic','dusk city glow, aspirational, cool tones',  'lifestyle', 2),
  ('live-dream',        'Candid Selfie',          'Real, spontaneous, relatable',        '{agent_description}, casual selfie, natural genuine smile, outdoor soft bokeh, daylight, authentic, photorealistic',         'natural daylight, candid energy, warm',    'selfie',    3)
) AS s(slug, name, description, prompt, style, gtype, sorder)
ON t.slug = s.slug
ON CONFLICT DO NOTHING;
```

- [ ] **Step 2: Run the migration**

```bash
docker exec archie_database psql -U archie -d archie -f /app/database/migrations/363_social_content_themes.sql
```

Expected: `CREATE TABLE`, `CREATE TABLE`, `CREATE INDEX x2`, `INSERT 0 9`, `INSERT 0 27`

- [ ] **Step 3: Verify**

```bash
docker exec archie_database psql -U archie -d archie -c "
SELECT t.name, t.accent_color, COUNT(s.id) AS scenes
FROM social_content_themes t
LEFT JOIN social_content_scenes s ON s.theme_id = t.id
GROUP BY t.name, t.accent_color ORDER BY t.name;"
```

Expected: 9 rows, each with `scenes = 3`

- [ ] **Step 4: Commit**

```bash
git add database/migrations/363_social_content_themes.sql
git commit -m "feat(social-presence): migration 363 — 9 department themes + 27 scenes seeded"
```

---

### Task 2: theme_service.py

**Files:**
- Create: `platform_v2/tools/media_studio/services/theme_service.py`

- [ ] **Step 1: Write the service**

```python
# platform_v2/tools/media_studio/services/theme_service.py
"""Theme & Scene service — CRUD for social_content_themes and social_content_scenes."""
from typing import Dict, List, Optional

from database import get_db_cursor


def get_all_themes(active_only: bool = True) -> List[Dict]:
    """Return all themes with curator agent display_name and scene count."""
    where = "WHERE t.is_active = true" if active_only else ""
    with get_db_cursor() as (conn, cur):
        cur.execute(f"""
            SELECT t.*, a.display_name AS curator_name,
                   COUNT(s.id) AS scene_count
            FROM social_content_themes t
            LEFT JOIN agents a ON a.id = t.curator_agent_id
            LEFT JOIN social_content_scenes s ON s.theme_id = t.id
            {where}
            GROUP BY t.id, a.display_name
            ORDER BY t.name
        """)
        return [dict(r) for r in cur.fetchall()]


def get_theme(theme_id: int) -> Optional[Dict]:
    with get_db_cursor() as (conn, cur):
        cur.execute("""
            SELECT t.*, a.display_name AS curator_name
            FROM social_content_themes t
            LEFT JOIN agents a ON a.id = t.curator_agent_id
            WHERE t.id = %s
        """, (theme_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def get_scenes_for_theme(theme_id: int) -> List[Dict]:
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT * FROM social_content_scenes WHERE theme_id = %s ORDER BY sort_order, id",
            (theme_id,),
        )
        return [dict(r) for r in cur.fetchall()]


def update_theme(theme_id: int, **kwargs) -> Optional[Dict]:
    allowed = {"name", "tone", "hashtags", "music_mood", "accent_color", "is_active"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return None
    set_clauses = ", ".join(f"{k} = %s" for k in fields)
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            f"UPDATE social_content_themes SET {set_clauses} WHERE id = %s RETURNING *",
            list(fields.values()) + [theme_id],
        )
        row = cur.fetchone()
        return dict(row) if row else None


def upsert_scene(theme_id: int, scene_id: Optional[int], **kwargs) -> Dict:
    allowed = {"name", "description", "visual_prompt_template", "style_directive",
               "image_aspect", "generation_type", "sort_order"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    with get_db_cursor(commit=True) as (conn, cur):
        if scene_id:
            set_clauses = ", ".join(f"{k} = %s" for k in fields)
            cur.execute(
                f"UPDATE social_content_scenes SET {set_clauses} WHERE id = %s RETURNING *",
                list(fields.values()) + [scene_id],
            )
        else:
            fields["theme_id"] = theme_id
            cols = ", ".join(fields.keys())
            placeholders = ", ".join(["%s"] * len(fields))
            cur.execute(
                f"INSERT INTO social_content_scenes ({cols}) VALUES ({placeholders}) RETURNING *",
                list(fields.values()),
            )
        return dict(cur.fetchone())
```

- [ ] **Step 2: Verify import in container**

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0, '/app')
from tools.media_studio.services.theme_service import get_all_themes
themes = get_all_themes()
print(f'OK: {len(themes)} themes')
for t in themes[:3]:
    print(f'  {t[\"name\"]} ({t[\"scene_count\"]} scenes)')
"
```

Expected: `OK: 9 themes`, then first 3 theme names with `3` scenes each.

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/media_studio/services/theme_service.py
git commit -m "feat(social-presence): theme_service.py — get_all_themes, get_theme, get_scenes_for_theme, update_theme, upsert_scene"
```

---

### Task 3: Media Studio Theme API Routes

**Files:**
- Modify: `platform_v2/tools/media_studio/routes.py`

- [ ] **Step 1: Add 3 routes after the social-video routes**

Search for `@media_studio_bp.route("/api/social-video/queue/<int:item_id>/status"` in routes.py and add after the entire social-video block:

```python
# ─── Content Themes ─────────────────────────────────────────────────


@media_studio_bp.route("/api/themes")
@login_required
def api_get_themes():
    from .services.theme_service import get_all_themes
    return jsonify({"themes": get_all_themes()})


@media_studio_bp.route("/api/themes/<int:theme_id>/scenes")
@login_required
def api_get_theme_scenes(theme_id):
    from .services.theme_service import get_theme, get_scenes_for_theme
    theme = get_theme(theme_id)
    if not theme:
        return jsonify({"error": "not found"}), 404
    return jsonify({"theme": theme, "scenes": get_scenes_for_theme(theme_id)})


@media_studio_bp.route("/api/themes/<int:theme_id>", methods=["PATCH"])
@login_required
def api_update_theme(theme_id):
    from .services.theme_service import update_theme
    data = request.get_json() or {}
    updated = update_theme(theme_id, **data)
    if not updated:
        return jsonify({"error": "not found or no valid fields"}), 400
    return jsonify(updated)
```

- [ ] **Step 2: Restart and test**

```bash
docker compose restart archie_platform
```

Navigate to `http://192.168.1.200:3000/tools/media-studio/api/themes` (logged in) — expect JSON with `{"themes": [...9 items...]}`.

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/media_studio/routes.py
git commit -m "feat(social-presence): 3 theme API routes — GET /api/themes, /api/themes/:id/scenes, PATCH /api/themes/:id"
```

---

### Task 4: Social Video Step 0 — Theme Picker HTML

**Files:**
- Modify: `platform_v2/tools/media_studio/templates/tools/media_studio/_tab_social_video.html`

- [ ] **Step 1: Add Step 0 before Step 1**

In `_tab_social_video.html`, find `<!-- Step 1: Text/Quote -->` and insert immediately before it:

```html
<!-- Step 0: Theme picker -->
<div id="msSvThemeStep" style="margin-bottom:14px;">
  <div style="color:#555;font-size:0.58rem;letter-spacing:1px;margin-bottom:6px;">
    0 &#x2014; CONTENT THEME
    <span style="color:#444;font-size:0.55rem;margin-left:4px;">(optional)</span>
  </div>
  <div id="msSvThemeGrid"
    style="display:grid;grid-template-columns:repeat(auto-fill,minmax(90px,1fr));gap:5px;"></div>
  <div id="msSvThemeSelected"
    style="display:none;margin-top:6px;padding:5px 10px;border-radius:4px;
           background:rgba(139,92,246,0.08);border:1px solid rgba(139,92,246,0.3);
           display:flex;align-items:center;justify-content:space-between;">
    <span id="msSvThemeSelectedName"
      style="color:#a78bfa;font-size:0.62rem;font-family:'Orbitron',sans-serif;"></span>
    <button onclick="msSocialVideo.clearTheme()"
      style="background:transparent;border:none;color:#555;cursor:pointer;font-size:0.65rem;padding:0 4px;">
      &#x2715;
    </button>
  </div>
</div>
```

- [ ] **Step 2: Restart and verify**

```bash
docker compose restart archie_platform
```

Navigate to Media Studio → Social Video tab. Step 0 section should appear above Step 1 (Text/Quote), showing an empty grid and a hidden selection bar.

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/media_studio/templates/tools/media_studio/_tab_social_video.html
git commit -m "feat(social-presence): Social Video — Step 0 theme picker HTML shell"
```

---

### Task 5: ms-social-video.js — Theme Loading + Selection

**Files:**
- Modify: `platform_v2/tools/media_studio/static/js/ms-social-video.js`

- [ ] **Step 1: Add `_selectedTheme` variable**

After `var _imageSource = 'gallery';` at the top of the IIFE, add:

```javascript
var _selectedTheme = null;
```

- [ ] **Step 2: Add theme methods to `window.msSocialVideo`**

Add these methods before the closing `};` of `window.msSocialVideo`:

```javascript
    loadThemes: function () {
      _get('/api/themes').then(function (data) {
        var grid = _el('msSvThemeGrid');
        if (!grid) return;
        grid.textContent = '';
        (data.themes || []).forEach(function (theme) {
          var card = document.createElement('div');
          card.dataset.themeId = theme.id;
          card.style.cssText = 'background:#0d1117;border:1px solid ' +
            (theme.accent_color || '#333') + '44;border-radius:4px;padding:6px 5px;' +
            'cursor:pointer;text-align:center;';
          var nameEl = document.createElement('div');
          nameEl.style.cssText = 'font-size:0.52rem;color:' + (theme.accent_color || '#888') +
            ';font-family:\'Orbitron\',sans-serif;letter-spacing:0.3px;line-height:1.3;';
          nameEl.textContent = theme.name;
          var curEl = document.createElement('div');
          curEl.style.cssText = 'font-size:0.48rem;color:#444;margin-top:2px;';
          curEl.textContent = theme.curator_name || '';
          card.appendChild(nameEl);
          card.appendChild(curEl);
          card.onclick = (function (t) { return function () { msSocialVideo.selectTheme(t); }; })(theme);
          grid.appendChild(card);
        });
      }).catch(function (err) { console.warn('[msSV] loadThemes failed:', err); });
    },

    selectTheme: function (theme) {
      _selectedTheme = theme;
      var grid = _el('msSvThemeGrid');
      if (grid) {
        grid.querySelectorAll('[data-theme-id]').forEach(function (c) {
          var active = String(c.dataset.themeId) === String(theme.id);
          c.style.borderColor = active ? (theme.accent_color || '#8b5cf6') : (theme.accent_color || '#333') + '44';
          c.style.background = active ? (theme.accent_color || '#8b5cf6') + '18' : '#0d1117';
        });
      }
      var sel = _el('msSvThemeSelected');
      var selName = _el('msSvThemeSelectedName');
      if (sel) sel.style.display = 'flex';
      if (selName) selName.textContent = theme.name;
    },

    selectThemeById: function (themeId) {
      _get('/api/themes/' + themeId + '/scenes').then(function (data) {
        if (data.theme) msSocialVideo.selectTheme(data.theme);
      }).catch(function (err) { console.warn('[msSV] selectThemeById failed:', err); });
    },

    clearTheme: function () {
      _selectedTheme = null;
      var grid = _el('msSvThemeGrid');
      if (grid) {
        grid.querySelectorAll('[data-theme-id]').forEach(function (c) {
          c.style.borderColor = '#33333344';
          c.style.background = '#0d1117';
        });
      }
      var sel = _el('msSvThemeSelected');
      if (sel) sel.style.display = 'none';
    },
```

- [ ] **Step 3: Call `loadThemes()` in `init()`**

Change:

```javascript
    init: function () {
      msSocialVideo.loadQueue();
      msSocialVideo.loadImageSource();
    },
```

To:

```javascript
    init: function () {
      msSocialVideo.loadThemes();
      msSocialVideo.loadQueue();
      msSocialVideo.loadImageSource();
    },
```

- [ ] **Step 4: Add `theme_id` to both queue POST payloads**

In `queueAndRender()`, add `theme_id: _selectedTheme ? _selectedTheme.id : null` to the POST body.
In `queueForPosting()`, add the same field.

- [ ] **Step 5: Restart and test**

```bash
docker compose restart archie_platform
```

Navigate to Social Video tab. 9 theme cards should appear in Step 0. Click "Live the Dream" — it highlights pink/magenta and the selection bar shows "Live the Dream". Click X — clears.

- [ ] **Step 6: Commit**

```bash
git add platform_v2/tools/media_studio/static/js/ms-social-video.js
git commit -m "feat(social-presence): Social Video theme picker — 9 cards, select/clear, theme_id in queue payload"
```

---

### Task 6: Gallery Brand — Theme Library

**Files:**
- Modify: `platform_v2/tools/media_studio/templates/tools/media_studio/_tab_gallery.html`
- Modify: `platform_v2/tools/media_studio/static/js/ms-gallery.js`

- [ ] **Step 1: Add Brand theme panel to `_tab_gallery.html`**

In `_tab_gallery.html`, find `<div id="msGallerySubjectGrid"` and add a sibling div immediately after it:

```html
<!-- Brand theme library — shown when Brand subject selected -->
<div id="msGalleryBrandThemes" style="display:none;padding-top:4px;">
  <div style="color:#22c55e;font-size:0.58rem;letter-spacing:2px;text-transform:uppercase;margin-bottom:10px;">
    CONTENT THEMES
  </div>
  <div id="msGalleryThemeCards"
    style="display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:10px;">
  </div>
</div>
```

- [ ] **Step 2: Add `loadBrandThemes()` to `ms-gallery.js`**

Add to `window.msGallery` before the closing `};`:

```javascript
    loadBrandThemes: function () {
      var themeEl = _el('msGalleryBrandThemes');
      var gridEl = _el('msGallerySubjectGrid');
      var headerEl = _el('msGallerySubjectHeader');
      if (!themeEl) return;
      themeEl.style.display = 'block';
      if (gridEl) gridEl.style.display = 'none';
      if (headerEl) {
        headerEl.style.cssText = 'display:flex;align-items:center;gap:12px;margin-bottom:14px;';
        while (headerEl.firstChild) headerEl.removeChild(headerEl.firstChild);
        var nameEl = document.createElement('div');
        nameEl.style.cssText = 'font-size:0.85rem;font-family:\'Orbitron\',sans-serif;color:#22c55e;';
        nameEl.textContent = 'Kytran Empowerment';
        var deptEl = document.createElement('div');
        deptEl.style.cssText = 'color:#555;font-size:0.65rem;';
        deptEl.textContent = 'Brand · Content Themes';
        headerEl.appendChild(nameEl);
        headerEl.appendChild(deptEl);
      }
      fetch('/tools/media-studio/api/themes', {credentials: 'same-origin'})
        .then(function (r) { return r.json(); })
        .then(function (data) {
          var cards = _el('msGalleryThemeCards');
          if (!cards) return;
          cards.textContent = '';
          (data.themes || []).forEach(function (theme) {
            var card = document.createElement('div');
            card.style.cssText = 'background:#0d1117;border:1px solid ' +
              (theme.accent_color || '#333') + '44;border-radius:6px;padding:12px;cursor:pointer;';
            var dot = document.createElement('div');
            dot.style.cssText = 'width:28px;height:4px;background:' +
              (theme.accent_color || '#8b5cf6') + ';border-radius:2px;margin-bottom:8px;';
            var nameEl = document.createElement('div');
            nameEl.style.cssText = 'font-family:\'Orbitron\',sans-serif;font-size:0.6rem;color:#ccc;margin-bottom:3px;';
            nameEl.textContent = theme.name;
            var curEl = document.createElement('div');
            curEl.style.cssText = 'font-size:0.55rem;color:#555;margin-bottom:3px;';
            curEl.textContent = theme.curator_name || '';
            var cntEl = document.createElement('div');
            cntEl.style.cssText = 'font-size:0.52rem;color:#444;';
            cntEl.textContent = (theme.scene_count || 0) + ' scenes';
            card.appendChild(dot);
            card.appendChild(nameEl);
            card.appendChild(curEl);
            card.appendChild(cntEl);
            card.onclick = (function (t) {
              return function () {
                if (window.switchMsTab) switchMsTab('social-video');
                setTimeout(function () {
                  if (window.msSocialVideo) msSocialVideo.selectThemeById(t.id);
                }, 350);
              };
            })(theme);
            cards.appendChild(card);
          });
        })
        .catch(function (err) { console.warn('[msGallery] loadBrandThemes failed:', err); });
    },
```

- [ ] **Step 3: Wire Brand click → `loadBrandThemes()` in `loadAssets()`**

In `ms-gallery.js`, at the very top of `loadAssets: function ()`, add the early-return for Brand:

```javascript
    loadAssets: function () {
      if (!_subject) return;
      // Brand: show theme library instead of image grid
      if (_subject.type === 'brand') {
        msGallery.loadBrandThemes();
        return;
      }
      // Restore grid + hide brand panel when switching to an agent
      var gridEl = _el('msGallerySubjectGrid');
      var themeEl = _el('msGalleryBrandThemes');
      if (gridEl) gridEl.style.display = '';
      if (themeEl) themeEl.style.display = 'none';
      // ... rest of existing loadAssets code unchanged below ...
```

- [ ] **Step 4: Restart and test**

```bash
docker compose restart archie_platform
```

Navigate to Gallery → click Brand in sidebar → "CONTENT THEMES" grid with 9 cards appears. Click "Faith & Strength" → switches to Social Video tab → "Faith & Strength" theme highlighted in Step 0.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/media_studio/templates/tools/media_studio/_tab_gallery.html \
        platform_v2/tools/media_studio/static/js/ms-gallery.js
git commit -m "feat(social-presence): Gallery Brand → 9 theme cards, click routes to Social Video pre-filled"
```

---

### Task 7: DHQ S.I.G.N.A.L. — Themes Sub-tab API

**Files:**
- Create: `platform_v2/tools/department_hq/theme_routes.py`
- Modify: `platform_v2/tools/department_hq/__init__.py`

- [ ] **Step 1: Create `theme_routes.py`**

```python
# platform_v2/tools/department_hq/theme_routes.py
"""DHQ S.I.G.N.A.L. — Content Theme management API routes."""
import logging

from flask import jsonify, request

logger = logging.getLogger(__name__)


def register_theme_routes(bp, admin_required):

    @bp.route("/api/signal/themes")
    @admin_required
    def api_signal_themes():
        from platform_v2.tools.media_studio.services.theme_service import get_all_themes
        return jsonify({"themes": get_all_themes(active_only=False)})

    @bp.route("/api/signal/themes/<int:theme_id>/scenes")
    @admin_required
    def api_signal_theme_scenes(theme_id):
        from platform_v2.tools.media_studio.services.theme_service import (
            get_theme,
            get_scenes_for_theme,
        )
        theme = get_theme(theme_id)
        if not theme:
            return jsonify({"error": "not found"}), 404
        return jsonify({"theme": theme, "scenes": get_scenes_for_theme(theme_id)})

    @bp.route("/api/signal/themes/<int:theme_id>", methods=["PATCH"])
    @admin_required
    def api_signal_update_theme(theme_id):
        from platform_v2.tools.media_studio.services.theme_service import update_theme
        data = request.get_json() or {}
        updated = update_theme(theme_id, **data)
        if not updated:
            return jsonify({"error": "not found or no valid fields"}), 400
        return jsonify(updated)

    @bp.route("/api/signal/themes/<int:theme_id>/scenes", methods=["POST"])
    @admin_required
    def api_signal_add_scene(theme_id):
        from platform_v2.tools.media_studio.services.theme_service import upsert_scene
        data = request.get_json() or {}
        scene = upsert_scene(theme_id, scene_id=None, **data)
        return jsonify(scene), 201

    @bp.route("/api/signal/themes/<int:theme_id>/scenes/<int:scene_id>", methods=["PATCH"])
    @admin_required
    def api_signal_update_scene(theme_id, scene_id):
        from platform_v2.tools.media_studio.services.theme_service import upsert_scene
        data = request.get_json() or {}
        scene = upsert_scene(theme_id, scene_id=scene_id, **data)
        return jsonify(scene)
```

- [ ] **Step 2: Register in `__init__.py`**

Find the import block (around line 35 where `from .social_routes import register_social_routes` is) and add:

```python
from .theme_routes import register_theme_routes  # noqa: E402
```

Find the registration block (around line 65) and add:

```python
register_theme_routes(department_hq_bp, admin_required)
```

- [ ] **Step 3: Restart and test**

```bash
docker compose restart archie_platform && docker logs archie_platform --tail 10 2>&1 | grep -iE "error|theme"
```

Expected: no errors. Then verify:

Navigate to `http://192.168.1.200:3000/tools/department-hq/api/signal/themes` (logged in as admin) — returns JSON with 9 themes including curator names and scene counts.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/department_hq/theme_routes.py platform_v2/tools/department_hq/__init__.py
git commit -m "feat(social-presence): DHQ theme_routes.py — 5 S.I.G.N.A.L. Themes API routes registered"
```

---

### Task 8: DHQ S.I.G.N.A.L. — Themes Sub-tab UI

**Files:**
- Modify: the DHQ template containing the S.I.G.N.A.L. tab

- [ ] **Step 1: Find the S.I.G.N.A.L. tab template**

```bash
grep -rn "signal\|S\.I\.G\.N\.A\.L\|subtab" /mnt/archie_brain/platform_v2/templates/ --include="*.html" -l 2>/dev/null | head -5
grep -rn "Compose\|Post Log\|Pending\|Hashtags" /mnt/archie_brain/platform_v2/templates/ --include="*.html" | head -5
```

Use the file returned to locate the sub-tab button row for `Compose`, `Post Log`, `Pending`, `Hashtags`.

- [ ] **Step 2: Add Themes sub-tab button**

Next to the existing sub-tab buttons (`Compose`, `Post Log`, `Pending`, `Hashtags`), add:

```html
<button class="signal-subtab-btn" data-subtab="themes"
  onclick="switchSignalSubtab('themes', this)"
  style="background:transparent;border:1px solid #333;color:#555;padding:4px 10px;
         border-radius:3px;font-size:0.6rem;cursor:pointer;letter-spacing:1px;">
  THEMES
</button>
```

- [ ] **Step 3: Add Themes sub-tab panel**

Alongside the other sub-tab panels, add:

```html
<div id="signal-subtab-themes" class="signal-subtab-pane" style="display:none;">
  <div style="color:#555;font-size:0.58rem;letter-spacing:1px;margin-bottom:12px;text-transform:uppercase;">
    Department Content Themes — 9 lanes
  </div>
  <div id="signalThemesList"
    style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px;">
  </div>
</div>
```

- [ ] **Step 4: Add JS to load themes in the Themes sub-tab**

Find where `switchSignalSubtab` is defined and add a case for `'themes'` that calls `loadSignalThemes()`. Then define:

```javascript
function loadSignalThemes() {
  var el = document.getElementById('signalThemesList');
  if (!el || el.childElementCount > 0) return; // already loaded
  fetch('/tools/department-hq/api/signal/themes', {credentials: 'same-origin'})
    .then(function (r) { return r.json(); })
    .then(function (data) {
      el.textContent = '';
      (data.themes || []).forEach(function (theme) {
        var card = document.createElement('div');
        card.style.cssText = 'background:#0d1117;border:1px solid ' +
          (theme.accent_color || '#333') + '44;border-radius:6px;padding:12px;';
        var dot = document.createElement('div');
        dot.style.cssText = 'width:10px;height:10px;border-radius:50%;background:' +
          (theme.accent_color || '#8b5cf6') + ';margin-bottom:6px;';
        var nameEl = document.createElement('div');
        nameEl.style.cssText = 'font-family:\'Orbitron\',sans-serif;font-size:0.62rem;color:#ccc;margin-bottom:3px;';
        nameEl.textContent = theme.name;
        var curEl = document.createElement('div');
        curEl.style.cssText = 'font-size:0.58rem;color:#555;margin-bottom:3px;';
        curEl.textContent = 'Curator: ' + (theme.curator_name || '—');
        var cntEl = document.createElement('div');
        cntEl.style.cssText = 'font-size:0.55rem;color:#444;';
        cntEl.textContent = (theme.scene_count || 0) + ' scenes · ' + (theme.music_mood || '—') + ' music';
        card.appendChild(dot);
        card.appendChild(nameEl);
        card.appendChild(curEl);
        card.appendChild(cntEl);
        el.appendChild(card);
      });
    })
    .catch(function (err) { console.warn('[signal] loadThemes failed:', err); });
}
```

- [ ] **Step 5: Restart and test**

```bash
docker compose restart archie_platform
```

Navigate to DHQ → S.I.G.N.A.L. tab → click THEMES sub-tab → 9 department theme cards render with accent colors, curator names, and scene counts.

- [ ] **Step 6: Commit**

```bash
git add platform_v2/templates/  # whichever file was modified
git commit -m "feat(social-presence): DHQ S.I.G.N.A.L. Themes sub-tab — 9 department theme cards with curator + scene info"
```

---

### Task 9: Push + End-to-End Verification

- [ ] **Step 1: Push all commits**

```bash
git push origin main
```

- [ ] **Step 2: Full end-to-end checklist**

```bash
# Verify DB has all 9 themes + 27 scenes
docker exec archie_database psql -U archie -d archie -c "
SELECT t.name, COUNT(s.id) scenes
FROM social_content_themes t
LEFT JOIN social_content_scenes s ON s.theme_id=t.id
GROUP BY t.name ORDER BY t.name;"
```

Expected: 9 rows, each `scenes = 3`

Manual browser checks (logged in at http://192.168.1.200:3000):
- [ ] Media Studio → Social Video → Step 0 shows 9 theme cards
- [ ] Click "Wellness & Healing" → green highlight + "Wellness & Healing" in selection bar
- [ ] Click X → clears selection
- [ ] Gallery → Brand → "CONTENT THEMES" grid with 9 colored cards
- [ ] Click "Live the Dream" → switches to Social Video, pink/magenta theme pre-selected
- [ ] Queue with theme selected → `social_video_queue` has `theme_id` set:

```bash
docker exec archie_database psql -U archie -d archie -c "
SELECT id, title, theme_id, status FROM social_video_queue ORDER BY id DESC LIMIT 3;"
```

- [ ] DHQ → S.I.G.N.A.L. → THEMES sub-tab → 9 cards visible

---

## What Phase 2 Adds (separate plan)

- `social_content_calendar` + `agent_social_voice` DB tables
- DHQ S.I.G.N.A.L. → Content Calendar week grid UI
- APScheduler auto-suggest worker (daily 8am + gap detection → Telegram)
- S.I.G.N.A.L. caption writing via DHQ dispatch using agent system_prompt + theme tone

## What Phase 3 Adds (separate plan)

- Lifestyle / Selfie / Announcement generation modes in Media Studio Generate tab
- IP-Adapter ComfyUI workflow for face consistency
- M.U.S.E. prompt refinement per scene
- Per-agent social accounts (Task #2511) as a zero-architecture-change layer
