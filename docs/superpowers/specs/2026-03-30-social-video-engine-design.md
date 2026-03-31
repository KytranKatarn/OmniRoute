# A.R.C.H.I.E. Social Video Engine — Design Spec

**Date:** 2026-03-30
**Project:** LTX-2 Video Generation (#205)
**Tasks:** #1505 (Cloud GPU Research), #1506 (Cloud Dispatch), #1507 (Media Studio UI)
**Status:** Approved

---

## Purpose

Generate and publish video content to Instagram, Facebook, and Indeed using AI video generation (LTX-Video). Content ranges from agent selfie moments to motivational videos to employer branding. Combines manual creation with an automated pipeline that drafts content for review.

## Content Types

| Type | Style | Cadence | Approval | Platforms |
|------|-------|---------|----------|-----------|
| Agent Moments | AI-generated scenes — selfies, events, behind-the-scenes | 3-4x/week | Auto after first few approved per agent | Instagram, Facebook |
| Motivational | Cinematic, inspirational quotes + visuals | Daily | Auto-post | Instagram, Facebook |
| Employer Branding | Project showcases, "life at Kytran", team highlights | Weekly | Manual review | Instagram, Facebook, Indeed |
| Recruitment | Role spotlights, what we're building next | As needed | Manual review | Indeed, Facebook |

Agent personality influences content: F.O.R.G.E. posts about code, M.U.S.E. posts about design, D.A.R.W.I.N. posts about research breakthroughs, etc.

## Architecture

### Layer 1: Content Generator (Bridge + LTX-Video)

Prompt templates per content type. Each template has placeholders for agent name, personality traits, current project context, and style directives.

**Prompt template examples:**
- Agent Selfie: `"{agent_name} taking a selfie at their {department} workstation, {personality_trait}, LCARS sci-fi environment, {style}"`
- Motivational: `"Cinematic wide shot, {scene_description}, overlaid text: '{quote}', inspirational tone, warm lighting"`
- Employer Branding: `"Team of AI agents collaborating on {project_name}, modern tech office aesthetic, {style}"`

**Generation flow:**
1. Select content type + agent (scheduled or manual)
2. Build prompt from template + agent personality + optional user override
3. Submit to Bridge dispatcher
4. Bridge routes to best GPU: local ComfyUI (drafts/previews) or cloud (final quality)
5. Poll for completion, download result
6. Auto-generate caption + hashtags via LLM (Bridge dispatch)
7. Insert into content queue

**Video parameters by quality tier:**
- Draft/Preview: 256x256, 9 frames, 8fps (~1s) — local Quadro M4000
- Standard: 512x512, 24 frames, 8fps (~3s) — cloud GPU
- High Quality: 768x512, 48 frames, 24fps (~2s) — cloud GPU

### Layer 2: Content Queue

**New table: `social_content_queue`**

| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL PK | |
| content_type | VARCHAR(50) | agent_moment, motivational, employer_branding, recruitment |
| agent_id | INTEGER FK | NULL for non-agent content |
| prompt | TEXT | Full generation prompt used |
| video_path | VARCHAR(500) | Path to generated video file |
| thumbnail_path | VARCHAR(500) | Auto-extracted frame |
| caption | TEXT | Auto-generated, editable |
| hashtags | TEXT[] | Auto-generated, editable |
| target_platforms | TEXT[] | instagram, facebook, indeed |
| status | VARCHAR(20) | draft, approved, scheduled, posted, rejected |
| approval_tier | VARCHAR(20) | auto, manual |
| scheduled_at | TIMESTAMPTZ | When to publish |
| posted_at | TIMESTAMPTZ | When actually published |
| post_urls | JSONB | Platform URLs after posting |
| created_at | TIMESTAMPTZ | |
| created_by | VARCHAR(50) | agent_loop, manual, agent_name |

**New table: `social_content_templates`**

| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL PK | |
| content_type | VARCHAR(50) | |
| name | VARCHAR(200) | Human-readable template name |
| prompt_template | TEXT | With {placeholders} |
| caption_template | TEXT | Optional caption structure |
| default_hashtags | TEXT[] | Base hashtags for this type |
| style_directive | VARCHAR(200) | pixel_art, cinematic, motion_graphics |
| video_params | JSONB | width, height, frames, fps, steps |
| platforms | TEXT[] | Default target platforms |
| approval_tier | VARCHAR(20) | auto or manual |
| is_active | BOOLEAN | |
| created_at | TIMESTAMPTZ | |

**Status flow:**
```
draft → approved → scheduled → posted
  ↓
rejected (with reason)
```

**Auto-approval logic:**
- Motivational content: auto-approve after template is approved once
- Agent moments: auto-approve after 3 manual approvals for that agent
- Employer branding / recruitment: always manual

### Layer 3: Publishing Pipeline

Leverages existing Social Media module infrastructure:
- `publishing_service.py` — handles the actual API calls
- `platform_clients.py` — Instagram, Facebook adapters
- `oauth_handler.py` — token management

**New additions:**
- Indeed Employer API client (video upload + employer branding posts)
- Video format adapter per platform:
  - Instagram Reels: 9:16 vertical, max 90s, MP4
  - Facebook Video: 16:9 or 1:1, max 240min, MP4
  - Indeed: 16:9, employer page video post
- Caption length enforcement (Instagram 2200 chars, Facebook 63206 chars, Indeed varies)

**Publishing flow:**
1. Agent loop job checks queue for `scheduled` items where `scheduled_at <= now()`
2. For each item, iterate target platforms
3. Adapt video format (ffmpeg resize/crop if needed)
4. Post via platform client
5. Store post URLs in `post_urls` JSONB
6. Update status to `posted`
7. Send Telegram notification with preview link

### Cloud GPU Strategy (Task #1505)

**Primary: RunPod Serverless**
- Pay-per-second GPU rental
- LTX-Video compatible (CUDA, Python runtime)
- API-driven: submit job → poll → download result
- Estimated cost: ~$0.01-0.05 per video (depending on resolution/length)
- GPU tiers: RTX 3090 ($0.22/hr), RTX 4090 ($0.44/hr), A100 ($1.00/hr)

**Fallback: Local ComfyUI (Quadro M4000)**
- Used for: draft previews, low-res thumbnails, testing prompts
- Limitation: 8GB VRAM, only 256x256 @ 9 frames practical
- VRAM swap: auto-unloads Ollama GPU models before generation

**Routing logic in Bridge dispatcher:**
```
if quality == "draft" or quality == "preview":
    route to local ComfyUI
elif cloud_budget_remaining > estimated_cost:
    route to RunPod Serverless
else:
    queue for local (slow but free)
```

**Budget controls:**
- Daily cloud spend limit (configurable, default $5/day)
- Monthly cap (default $50/month)
- Track in `cloud_gpu_usage` table or existing billing infrastructure

### Agent Loop Jobs

| Job | Schedule | What |
|-----|----------|------|
| Social Content Generator | Configurable per content type | Picks agent + type, generates prompt, submits to Bridge |
| Content Queue Publisher | Every 5 minutes | Checks for scheduled items ready to post |
| Content Auto-Approver | Every 15 minutes | Applies auto-approval rules to draft items |

### Media Studio UI (Task #1507)

New "Social Video" tab in Media Studio with:

**Manual Creation:**
- Content type selector (agent moment, motivational, employer branding, recruitment)
- Agent picker (for agent moments)
- Prompt editor with template suggestions
- Quality tier selector (draft preview vs final)
- Generate button → shows preview when ready
- Caption + hashtag editor
- Platform selector (Instagram, Facebook, Indeed)
- Schedule or publish now

**Queue Management:**
- List view of all queued content with status filters
- Video preview player
- Approve/reject buttons with one click
- Edit caption/hashtags inline
- Reschedule drag or date picker
- Bulk approve for trusted content types

**Analytics (stretch):**
- Post performance per platform (views, likes, shares)
- Best performing content types
- Agent engagement rankings

## What This Touches

| Component | Change |
|-----------|--------|
| Media Studio (`tools/media_studio/`) | New "Social Video" tab, routes for queue management |
| Social Media (`tools/social_media/`) | Indeed client, video publishing support |
| Bridge Dispatcher (`ai_bridge/bridge_dispatcher.py`) | RunPod Serverless provider, cloud budget tracking |
| Agent Loop (`ai_bridge/agent_loop.py`) | 3 new scheduled jobs |
| Database | 2 new tables (`social_content_queue`, `social_content_templates`) |
| ComfyUI workflows | Existing `ltx-video-basic.json` used as-is |
| Telegram | Notifications for content awaiting approval + post confirmations |

## Out of Scope (for now)

- TikTok / YouTube / LinkedIn publishing (can add later via platform clients)
- Video editing/trimming in browser
- A/B testing different captions
- Music/audio overlay on videos
- Multi-clip video composition (montages)

## Dependencies

- RunPod account + API key
- Indeed Employer API access
- Instagram Graph API video upload permissions (may need app review)
- Facebook Page video upload permissions
- ffmpeg available in Docker container for format adaptation
