# Agent Social Presence Engine — Design Spec

**Goal:** Give every Kytran Empowerment agent an AI-managed social media presence — lifestyle images, selfies, thought leadership content — orchestrated by Department HQ and produced in Media Studio.

**Architecture:** Two modules, one pipeline. DHQ S.I.G.N.A.L. tab is the agency side (plan, schedule, approve, publish). Media Studio is the studio side (generate, assemble, gallery, video). Telegram approval bridges them. KBS posts to LinkedIn.

**Tech Stack:** Flask + Jinja2 + vanilla JS, PostgreSQL, LCARS aesthetic, ComfyUI via P.I.X.E.L./DHQ (IP-Adapter for face consistency), S.I.G.N.A.L. for caption writing, KBS for LinkedIn posting, APScheduler for auto-suggest worker.

**Build order:** Phase 1 → Phase 2 → Phase 3

---

## Pipeline Overview

```
DHQ S.I.G.N.A.L. Tab (Agency)     ←→     Media Studio (Studio)
  Content Calendar                          Theme Library (Gallery Brand)
  Theme Manager                             Social Video builder (Step 0: Theme)
  Agent Voice settings                      Scene picker + image generation
  Auto-suggest worker                       Slideshow assembler + video
  Approval queue                            Gallery (generated content)
        ↓
  Telegram approval (S.I.G.N.A.L.)
        ↓
  KBS → LinkedIn (Kytran Empowerment page)
        ↓  (future — Task #2511)
  Per-agent LinkedIn accounts
```

---

## Department Themes (9 lanes, 1 per department)

| Theme | Curator Agent | Tone | Example Scenes |
|-------|--------------|------|---------------|
| Faith & Strength | F.A.I.T.H. | Spiritual, hopeful, "believe in..." | Sunrise prayer, candle reflection, community gathering |
| Wellness & Healing | V.I.T.A.L. | Nurturing, grounding, health-forward | Morning yoga, nature walk, mindful meal |
| Legal Empowerment | G.A.V.E.L. | Bold, empowering, "know your rights" | Confident at desk, advocacy rally, victory moment |
| Build & Innovate | F.O.R.G.E. | Forward-thinking, ambitious | Late night building, tech conference, maker energy |
| Financial Freedom | L.E.D.G.E.R. | Smart, strategic, "build legacy" | Growth mindset, vision board, professional confidence |
| Protect & Serve | V.I.G.I.L. | Protective, trustworthy, serious | Vigilant professional, safety awareness |
| Culture & People | K.I.N. | Warm, inclusive, community-first | Team celebration, onboarding, "our people" |
| Create Without Limits | M.U.S.E. | Expressive, vibrant, artistic | Art studio, creative process, inspiration board |
| Live the Dream | S.I.G.N.A.L. | Aspirational, personal, relatable | Beach sunrise, city rooftop, selfie moments |

---

## Phase 1 — Theme & Scene Engine

### New DB Tables

```sql
-- Department content themes
CREATE TABLE social_content_themes (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    slug VARCHAR(50) UNIQUE NOT NULL,
    department VARCHAR(100),
    curator_agent_id INTEGER REFERENCES agents(id),
    tone TEXT,                          -- voice direction for S.I.G.N.A.L.
    hashtags TEXT[] DEFAULT '{}',
    music_mood VARCHAR(50),             -- 'uplifting' | 'calm' | 'professional' | 'ambient'
    accent_color VARCHAR(7),            -- hex for UI theming
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Visual scenes per theme (3-5 per theme)
CREATE TABLE social_content_scenes (
    id SERIAL PRIMARY KEY,
    theme_id INTEGER REFERENCES social_content_themes(id),
    name VARCHAR(100) NOT NULL,
    description TEXT,
    visual_prompt_template TEXT NOT NULL, -- {agent_description}, {scene_details} placeholders
    style_directive TEXT,                 -- passed to M.U.S.E. for refinement
    image_aspect VARCHAR(10) DEFAULT 'square', -- 'square' | 'portrait' | 'landscape'
    generation_type VARCHAR(20) DEFAULT 'lifestyle', -- 'lifestyle' | 'selfie' | 'announcement'
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### Media Studio — Gallery Brand Section

- Theme Library view: 9 cards (one per department theme), accent color per card
- Each card shows: theme name, curator agent avatar, scene count, recent generated content thumbnails
- Click theme → opens scene browser for that theme

### Media Studio — Social Video Builder (Step 0 added)

Current flow: Step 1 (text) → Step 2 (images) → Step 3 (audio) → Step 4 (post)

New flow: **Step 0 (theme)** → Step 1 (text/caption) → Step 2 (images/scenes) → Step 3 (audio) → Step 4 (post)

- Step 0: 9 theme cards + "Custom" option
- Selecting a theme: auto-fills hashtags, music mood, filters agent picker to that department
- "Custom" = existing blank flow unchanged

### DHQ S.I.G.N.A.L. Tab — New Themes Sub-tab

- List all 9 themes with curator agent, scene count, active status
- Edit theme: tone, hashtags, music mood, accent color
- Add/edit/reorder scenes per theme
- Preview: shows sample prompt output

---

## Phase 2 — Content Calendar + Auto-Suggest

### New DB Tables

```sql
-- Weekly content calendar slots
CREATE TABLE social_content_calendar (
    id SERIAL PRIMARY KEY,
    day_of_week SMALLINT NOT NULL,      -- 0=Mon ... 6=Sun
    slot_order SMALLINT DEFAULT 0,      -- multiple posts per day
    theme_id INTEGER REFERENCES social_content_themes(id),
    featured_agent_id INTEGER REFERENCES agents(id),
    auto_generate BOOLEAN DEFAULT false,
    time_of_day TIME DEFAULT '09:00:00',
    platform VARCHAR(50) DEFAULT 'linkedin',
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Per-agent social voice settings
CREATE TABLE agent_social_voice (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER UNIQUE REFERENCES agents(id),
    tone_descriptor TEXT,               -- "warm, aspirational, uses first person"
    sample_phrases TEXT[],              -- example phrases in their voice
    hashtag_preferences TEXT[],
    post_frequency_per_week SMALLINT DEFAULT 2,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

### DHQ S.I.G.N.A.L. Tab — Content Calendar Sub-tab

- Week grid view (Mon–Sun columns)
- Each cell: theme badge + featured agent avatar + status chip (empty / queued / rendering / ready / posted)
- Click empty cell → open Social Video builder pre-filled with theme + agent
- Click queued/ready cell → preview post, approve/edit/delete
- "+ Add Slot" button to schedule custom posts

### Auto-Suggest Worker (APScheduler, daily 8am)

```
For each calendar slot in next 3 days where auto_generate=true:
  1. Pick agent from that theme's department (active, hasn't posted recently)
  2. Pick scene from theme's scene library (rotate, avoid repeating)
  3. Queue to social_video_queue with theme_id + scene_id + agent_id + status='pending_generation'
  4. media_generation_worker picks it up → P.I.X.E.L. generates image
  5. S.I.G.N.A.L. writes caption using agent's system_prompt + theme tone + agent_social_voice
  6. Slideshow assembler builds video
  7. Queues for Telegram approval

Gap detection (runs same time):
  - If tomorrow has no post queued → sends Telegram:
    "Tomorrow is empty — generate a [theme] post featuring [agent]? [✓ Yes] [Skip]"
```

### Caption Writing via S.I.G.N.A.L.

S.I.G.N.A.L. dispatched via DHQ with capability='content_writing':
- Input: agent's `system_prompt` (personality) + `agent_social_voice.tone_descriptor` + theme tone + scene description + optional user hint
- Output: 1-3 sentence caption + hashtags + emoji
- Stored as `social_video_queue.quote_text` (editable before posting)

---

## Phase 3 — Full Content Studio (Lifestyle & Selfie Generation)

### New Generation Modes in Media Studio Generate Tab

Extends existing 3-card type selector (Portrait / Brand Asset / Social Content) with sub-types:

**Portrait** (existing) — professional headshot, identity image

**Lifestyle** (new):
- Agent in a scene from the scene library
- Prompt = `scene.visual_prompt_template` filled with agent's `identity_prompt` description
- IP-Adapter: agent's canonical portrait as face reference image
- Output stored in `media_library` with `metadata.asset_type='lifestyle'` and `metadata.theme_id`

**Selfie** (new):
- Face-forward, close crop, casual/candid style
- Prompt template: "{agent_description}, selfie photo, natural expression, {setting}, candid, authentic, photorealistic"
- IP-Adapter for face consistency
- Output stored with `metadata.asset_type='selfie'`

**Announcement** (new):
- Agent + branded overlay (milestone, celebration, achievement)
- Composite: generated image + text overlay (handled in slideshow_generator)

### Generation Flow

```
1. Pick Theme → Pick Scene → Pick Agent
2. M.U.S.E. refines visual prompt (capability='visual_design' via DHQ)
3. P.I.X.E.L. generates via ComfyUI (IP-Adapter with canonical portrait as reference)
4. Image stored in media_library → appears in Gallery under agent + theme
5. S.I.G.N.A.L. writes caption (capability='content_writing' via DHQ)
6. User previews image + caption → edits if needed
7. "Build Video" → slideshow_generator assembles 3-5 images + caption + music
8. Queue for Telegram approval → KBS → LinkedIn
```

### IP-Adapter Integration

- ComfyUI workflow: load IP-Adapter model → feed canonical portrait as reference → inject into generation
- Fallback: if IP-Adapter unavailable → use enhanced text prompt with agent's `identity_prompt` (current behavior)
- New ComfyUI workflow file: `static/workflows/lifestyle-ipadapter.json`

---

## Cross-Cutting Concerns

### Agent Social Voice (all phases)

- `agent_social_voice` table seeded for all active agents on Phase 2 deploy
- S.I.G.N.A.L. falls back to `agents.system_prompt` if no voice record exists
- Voice can be refined over time — S.I.G.N.A.L. learns from approved posts

### Content Attribution

- All generated social content tagged with: `agent_id`, `theme_id`, `scene_id`, `generation_type`
- Gallery Brand section browsable by theme AND by agent
- `social_video_queue` gains these columns (migration in Phase 2):
  - `theme_id INTEGER REFERENCES social_content_themes(id)`
  - `scene_id INTEGER REFERENCES social_content_scenes(id)`
  - `generation_type VARCHAR(20)` — 'lifestyle' | 'selfie' | 'announcement' | 'slideshow'
  - `caption_draft TEXT` — S.I.G.N.A.L.-written caption before user edits it to `quote_text`

### Per-Agent Social Accounts (Future — Task #2511)

- Zero architecture change required: posting step gains `posted_as` field (`kytran_empowerment` | `agent:<id>`)
- KBS routes to company OAuth or agent Playwright vault based on `posted_as`
- All calendar, theme, and generation infrastructure reused unchanged

### LCARS Visual Language

- Theme Library cards: each theme uses its department's accent color
- Calendar grid: status chips use existing color system (draft=amber, rendering=blue, ready=purple, posted=gray)
- DHQ S.I.G.N.A.L. tab: new sub-tabs (Themes, Calendar, Voice) alongside existing (Overview, Compose, Post Log, Pending, Hashtags)

---

## What Is NOT Changing

- Portraits tab and Queue tab in Media Studio — working well, excluded
- KBS LinkedIn OAuth — existing connection, not rebuilding
- Telegram approval pipeline — existing S.I.G.N.A.L. flow, extending not replacing
- ComfyUI generation pipeline — adding new workflow files, not modifying existing
