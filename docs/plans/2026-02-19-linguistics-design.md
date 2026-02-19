# Linguistics Module Design — DB Translation Cache with AI Generation

**Project**: #94 — Platform UI Overhaul
**Date**: 2026-02-19
**Approach**: DB Translation Cache (Approach A) — AI batch-generates, human reviews
**Languages**: English (default) + Québécois French
**UI Home**: New "Languages" tab inside Consciousness module

---

## Overview

Add multilingual support to the A.R.C.H.I.E. platform covering static UI, chat responses, and voice output. AI generates translations in batch, stores them in a DB cache, and an admin reviews/approves them. Chat responses are translated server-side in the orchestration pipeline. The language selector in the dashboard command bar drives the experience.

**Three layers:**
1. **DB layer** — `translations`, `translation_memory`, `user_language_preferences` tables
2. **Backend layer** — `ai_bridge/translation_service.py` + Consciousness API routes + orchestration pipeline hooks
3. **Frontend layer** — `archie-i18n.js` in `base.html`, `data-i18n` attributes on elements

---

## Architecture

### Translation Flow (Static UI)

```
Admin clicks "Generate Translations"
  → Scan templates for [data-i18n] keys
  → Batch translate via qwen3-coder-cpu (50 strings/batch)
  → Store in translations table (status: pending_review)
  → Admin reviews in Consciousness Languages tab
  → Approve/edit/reject
  → Corrections saved to translation_memory (glossary)
```

### Runtime Flow (Page Load)

```
Page loads → archie-i18n.js checks user language preference
  → If not English: fetch /api/translations/fr (cached client-side 5min)
  → Walk all [data-i18n] elements, swap text content
  → No page reload needed on language switch
```

### Chat Flow

```
User types message
  → Detect language (qwen25-classify)
  → If not English: translate input to English for processing
  → Orchestration pipeline processes in English
  → ARCHIE generates English response
  → Translate response to user's language (dolphin3-8k or qwen3-coder-cpu)
  → Send to client
  → Optionally synthesize via XTTS v2 in French
```

### Language Detection Strategy

- User preference stored in DB (`user_language_preferences`)
- Auto-detect enabled by default: if user types in French, ARCHIE responds in French
- If user types in English but preference is French, ARCHIE responds in French (preference as default, auto-detect as override)
- Detection cached per conversation session

---

## Database Schema

### `translations` — cached AI translations

| Column | Type | Purpose |
|--------|------|---------|
| id | SERIAL PK | |
| key | VARCHAR(255) | i18n key, e.g. `dashboard.search_placeholder` |
| language | VARCHAR(10) | `fr`, `en` |
| text | TEXT | Translated string |
| source | VARCHAR(20) | `ai_generated`, `human_edited`, `imported` |
| status | VARCHAR(20) | `pending_review`, `approved`, `rejected` |
| context | TEXT | Where string appears (helps AI accuracy) |
| generated_by | VARCHAR(50) | Model that translated |
| reviewed_by | INTEGER FK → users | User who approved/edited |
| created_at | TIMESTAMP | Default NOW() |
| updated_at | TIMESTAMP | Default NOW() |
| UNIQUE(key, language) | | One translation per key per language |

### `translation_memory` — corrections and glossary

| Column | Type | Purpose |
|--------|------|---------|
| id | SERIAL PK | |
| source_text | TEXT | Original English |
| translated_text | TEXT | Corrected/preferred translation |
| language | VARCHAR(10) | |
| category | VARCHAR(50) | `ui`, `chat`, `technical`, `glossary` |
| created_by | INTEGER FK → users | |
| created_at | TIMESTAMP | Default NOW() |

### `user_language_preferences` — per-user setting

| Column | Type | Purpose |
|--------|------|---------|
| user_id | INTEGER FK → users PK | |
| language | VARCHAR(10) | Default `en` |
| auto_detect | BOOLEAN | Default TRUE |
| updated_at | TIMESTAMP | Default NOW() |

---

## API Endpoints

### Public (authenticated)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/translations/<lang>` | GET | All approved translations for a language (JSON dict) |
| `/api/user/language` | GET/PUT | Get/set user's language preference + auto_detect |
| `/api/translate/text` | POST | On-demand translate a single string |
| `/api/language/detect` | POST | Detect language of input text |

### Admin (Consciousness routes)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/tools/consciousness/api/translations/generate` | POST | Batch-generate translations for a language |
| `/tools/consciousness/api/translations/review` | GET | List pending translations |
| `/tools/consciousness/api/translations/approve` | PUT | Approve/reject/edit a translation |
| `/tools/consciousness/api/translations/stats` | GET | Coverage stats per language |
| `/tools/consciousness/api/translations/scan` | POST | Scan templates for data-i18n keys |
| `/tools/consciousness/api/translation-memory` | GET/POST | View/add glossary entries |

---

## Frontend Integration

### data-i18n attributes

```html
<!-- English stays as default fallback -->
<span class="hud-pod-label" data-i18n="hud.system">SYSTEM</span>
<input placeholder="Search modules..." data-i18n-placeholder="dashboard.search_placeholder" />
```

- `data-i18n` — replaces `textContent`
- `data-i18n-placeholder` — replaces `placeholder` attribute
- `data-i18n-title` — replaces `title` attribute

### archie-i18n.js (injected in base.html)

- On page load: fetch user language from `/api/user/language`
- If not English: fetch `/api/translations/{lang}`, cache client-side 5 min
- Walk all `[data-i18n]` elements and swap
- Expose `window.archieI18n.t('key')` for JS-generated content
- Language button click triggers swap without reload

### Rollout strategy

1. Dashboard first — command bar, HUD pods, section headers, boot sequence
2. Then base.html — nav, footer, common elements
3. Then module pages incrementally

---

## Consciousness Languages Tab

New 9th tab: `🌐 Languages`

### Sub-tab 1: Dashboard
- Coverage stats with progress bar: "French: 142/156 keys (91%), 128 approved, 14 pending"
- "Generate Translations" button — batch AI translation
- "Scan Templates" button — find new/missing keys
- Last generation timestamp, model used

### Sub-tab 2: Review
- Table: key, English source, AI translation, status
- Inline edit to correct translations
- Approve/reject per row, bulk approve
- Corrections auto-saved to translation_memory

### Sub-tab 3: Glossary
- Translation memory entries: source → target
- Add/edit/delete with category filter (ui, chat, technical)
- Fed to AI as context during batch generation

---

## AI Routing

### Smart Router additions

```python
CAPABILITY_ROUTING["translate"] = "local_analysis"   # qwen3-coder-cpu (32K, free)
CAPABILITY_ROUTING["detect_language"] = "classify"    # qwen25-classify (fast, CPU)
```

### Model usage

| Task | Model | Why |
|------|-------|-----|
| Batch translation | qwen3-coder-cpu | Free, 32K context, batches of 50 |
| Chat response translation | dolphin3-8k | Fast GPU, short strings |
| Language detection | qwen25-classify | Fast CPU classifier |
| Fallback | minimax-m2.5 (cloud) | If local fails |

### Translation service prompt pattern

```
Translate these UI strings to Québécois French.
Use these glossary terms: {glossary entries}
Rules:
- Keep technical terms (ARCHIE, API, CPU, etc.) as-is
- Use Québécois expressions, not France French
- Keep translations concise for UI labels
- Maintain any {variables} or {{template syntax}} unchanged
```

### Orchestration pipeline modification

```
Before: intent → IAAE → welfare → route → agent → GPU → execute → log
After:  intent → IAAE → welfare → DETECT_LANG → route → agent → GPU → execute → TRANSLATE_RESPONSE → log
```

Two new steps — both no-ops when language is English.

---

## What We're NOT Building (v1 scope)

- No knowledge base content translation
- No per-module translation files — single flat namespace
- No Aya 35B model — qwen3-coder-cpu handles French fine
- No automatic re-translation on source change
- No translation API for external consumers
- No multi-dialect support — one French variant (Québécois)
- No RTL layout support
- No user-generated content translation

---

## Files to Create/Modify

### New files
- `database/migrations/082_linguistics_tables.sql`
- `ai_bridge/translation_service.py`
- `platform_v2/static/js/archie-i18n.js`

### Modified files
- `platform_v2/templates/base.html` — inject archie-i18n.js
- `platform_v2/templates/dashboard_dynamic.html` — add data-i18n attributes
- `platform_v2/tools/consciousness/routes.py` — add translation API endpoints
- `platform_v2/tools/consciousness/templates/consciousness_dashboard.html` — Languages tab
- `ai_bridge/smart_router.py` — add translate/detect_language capabilities
- `ai_bridge/orchestration_engine.py` — add detect_lang and translate_response steps
- `platform_v2/app.py` — add public translation API routes

---

## Testing Plan

- Migration: verify 3 tables created with correct constraints
- Translation service: batch translate 10 test strings, verify output
- API: test all endpoints with curl/Playwright
- Frontend: verify data-i18n swap works on dashboard
- Chat: send French message, verify French response
- Language tab: generate, review, approve flow
- Edge cases: missing translations fall back to English, empty glossary works
