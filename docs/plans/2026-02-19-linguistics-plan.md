# Linguistics Module Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add multilingual support (English + Québécois French) to the A.R.C.H.I.E. platform with AI-generated translations, human review, and chat/voice integration.

**Architecture:** AI batch-translates UI strings via qwen3-coder-cpu, caches in PostgreSQL `translations` table. Frontend JS swaps text via `data-i18n` attributes. Chat responses translated server-side in the orchestration pipeline. Admin manages translations in a new Languages tab inside the Consciousness module.

**Tech Stack:** Flask/Jinja2, PostgreSQL, Ollama (qwen3-coder-cpu, dolphin3-8k, qwen25-classify), vanilla JS

**Design Doc:** `docs/plans/2026-02-19-linguistics-design.md`

---

### Task 1: Database Migration

Create the 3 linguistics tables.

**Files:**
- Create: `database/migrations/114_linguistics_tables.sql`

**Step 1: Write migration SQL**

The migration creates `translations`, `translation_memory`, and `user_language_preferences` tables with appropriate indexes and constraints.

Key schema points:
- `translations`: UNIQUE(key, language), status workflow (pending_review → approved/rejected)
- `translation_memory`: glossary entries with category (ui, chat, technical, glossary)
- `user_language_preferences`: per-user language + auto_detect boolean, PK on user_id

**Step 2: Run migration**

```bash
docker cp database/migrations/114_linguistics_tables.sql archie_database:/tmp/
docker exec archie_database psql -U archie -d archie -f /tmp/114_linguistics_tables.sql
```

**Step 3: Commit**

```bash
git add database/migrations/114_linguistics_tables.sql
git commit -m "feat(linguistics): add translations, translation_memory, user_language_preferences tables"
```

---

### Task 2: Translation Service

Core AI translation engine — batch translate, single translate, language detect.

**Files:**
- Create: `ai_bridge/translation_service.py`
- Modify: `ai_bridge/smart_router.py:160-171` — add translate/detect_language capabilities

**Step 1: Add capabilities to smart router**

Add two entries to `CAPABILITY_ROUTING` dict in `ai_bridge/smart_router.py` (line ~170):

```python
    "translate": "local_analysis",   # Translation via qwen3-coder-cpu
    "detect_language": "classify",   # Language detection via qwen25-classify
```

**Step 2: Create translation service**

Create `ai_bridge/translation_service.py` with these functions:

- `detect_language(text)` — uses qwen25-classify, returns ISO code
- `get_glossary(language)` — fetches translation_memory entries
- `batch_translate(strings, language, model)` — translates list of (key, text, context) tuples in batches of 40, uses JSON array output format, glossary-aware prompts
- `translate_text(text, target_language, source_language, model)` — single string translation for chat, uses dolphin3-8k
- `store_translations(results, language, model)` — upserts batch results to translations table
- `get_translations(language)` — returns dict of all approved translations
- `get_translation_stats(language)` — coverage stats (total, approved, pending, rejected, human_edited)
- `SUPPORTED_LANGUAGES = {"en": "English", "fr": "Québécois French"}`
- DB connection via `psycopg2` to `archie_database`
- Ollama calls via `requests.post` to `http://host.docker.internal:11434/api/generate`

**Step 3: Verify import works**

```bash
docker exec archie_platform python3 -c "from ai_bridge.translation_service import detect_language, SUPPORTED_LANGUAGES; print('OK:', SUPPORTED_LANGUAGES)"
```

**Step 4: Commit**

```bash
git add ai_bridge/translation_service.py ai_bridge/smart_router.py
git commit -m "feat(linguistics): translation service with batch/single translate, language detection, glossary"
```

---

### Task 3: Public API Endpoints

User-facing translation endpoints in app.py.

**Files:**
- Modify: `platform_v2/app.py` — add 4 endpoints after existing dashboard API routes (~line 1115)

**Step 1: Add routes**

Add these endpoints:

- `GET /api/translations/<lang>` — returns all approved translations for a language as JSON dict. Validates language against SUPPORTED_LANGUAGES.
- `GET/PUT /api/user/language` — get/set user's language preference and auto_detect flag. Uses `user_language_preferences` table with upsert.
- `POST /api/translate/text` — on-demand single string translation. Accepts `text`, `target_language`, `source_language`.
- `POST /api/language/detect` — detect language of input text. Returns ISO code.

All endpoints require `@login_required`.

**Step 2: Restart and test**

```bash
docker restart archie_platform && sleep 10
curl -s -b cookies.txt http://192.168.1.200:3000/api/translations/fr | python3 -m json.tool
curl -s -b cookies.txt http://192.168.1.200:3000/api/user/language | python3 -m json.tool
```

**Step 3: Commit**

```bash
git add platform_v2/app.py
git commit -m "feat(linguistics): public API endpoints for translations, user language, detect, translate"
```

---

### Task 4: Admin Translation Endpoints in Consciousness

Backend routes for generating, reviewing, and managing translations.

**Files:**
- Modify: `platform_v2/tools/consciousness/routes.py` — add admin translation API routes

**Step 1: Add admin endpoints**

Add these routes to the consciousness blueprint (requires `@require_permission(Permission.ADMIN_ACCESS)`):

- `GET /api/translations/stats` — coverage stats per language (total, approved, pending, rejected, human_edited)
- `POST /api/translations/scan` — scan templates directory for `data-i18n` attributes using regex, returns keys with file locations
- `POST /api/translations/generate` — batch-generate translations for a language. Finds missing keys (English source exists, target doesn't), calls `batch_translate()`, stores results. Accepts optional `strings` list for manual input.
- `GET /api/translations/review` — list translations with status filter (pending_review, approved, rejected, all)
- `PUT /api/translations/approve` — approve/reject/edit individual translation. On edit: saves correction to `translation_memory` automatically.
- `PUT /api/translations/bulk-approve` — bulk approve by list of IDs
- `GET/POST /api/translation-memory` — view/add glossary entries
- `DELETE /api/translation-memory/<id>` — delete glossary entry

**Step 2: Restart and test**

```bash
docker restart archie_platform && sleep 10
curl -s -b cookies.txt http://192.168.1.200:3000/tools/consciousness/api/translations/stats | python3 -m json.tool
```

**Step 3: Commit**

```bash
git add platform_v2/tools/consciousness/routes.py
git commit -m "feat(linguistics): admin translation API in Consciousness — generate, review, approve, glossary"
```

---

### Task 5: Frontend i18n Script

Client-side translation engine that swaps text on language change.

**Files:**
- Create: `platform_v2/static/js/archie-i18n.js`
- Modify: `platform_v2/templates/base.html` — inject script before `</body>`
- Modify: `platform_v2/templates/dashboard_dynamic.html` — update language button to use `archieI18n.switchLanguage()`, reduce dropdown to just English + Français (QC)

**Step 1: Create archie-i18n.js**

Self-contained IIFE exposing `window.archieI18n`:
- `init()` — on page load, fetches user language pref from `/api/user/language`, applies if not English
- `fetchTranslations(lang)` — fetches `/api/translations/{lang}`, caches client-side for 5 min
- `applyTranslations(translations)` — walks `[data-i18n]`, `[data-i18n-placeholder]`, `[data-i18n-title]` elements, swaps content
- `storeOriginals()` / `revertToEnglish()` — saves original English text before first swap, restores on switch back
- `switchLanguage(lang)` — saves to server + localStorage, fetches translations, applies. No page reload.
- `t(key, fallback)` — returns translated string for key (for JS-generated content like featured cards)
- `getCurrentLanguage()` — returns current language code
- `refresh()` — re-applies current language (useful after dynamic content added)

**Step 2: Inject in base.html**

Add before `</body>`:
```html
<script src="{{ url_for('static', filename='js/archie-i18n.js') }}"></script>
```

**Step 3: Update dashboard language button**

Wire `.cb-lang-option` click to `archieI18n.switchLanguage(lang)`. Reduce language options to:
```html
<button class="cb-lang-option active" data-lang="en">English</button>
<button class="cb-lang-option" data-lang="fr">Français (QC)</button>
```

**Step 4: Commit**

```bash
git add platform_v2/static/js/archie-i18n.js platform_v2/templates/base.html platform_v2/templates/dashboard_dynamic.html
git commit -m "feat(linguistics): archie-i18n.js frontend engine + language button wiring"
```

---

### Task 6: Tag Dashboard with data-i18n Attributes

Add i18n tags to dashboard and seed English source strings in DB.

**Files:**
- Modify: `platform_v2/templates/dashboard_dynamic.html` — add `data-i18n` to ~20 key strings

**Step 1: Tag static text elements**

Target elements with `data-i18n` attributes:
- Boot sequence: `boot.initializing`, `boot.system_online`, `boot.threat_nominal`, `boot.skip`
- HUD pods: `hud.system`, `hud.cpu`, `hud.memory`, `hud.ai_status`, `hud.archie`, `hud.agents`, `hud.uptime`
- Command bar: `cmd.search_placeholder` (use `data-i18n-placeholder`)
- Section headers: `section.priority_stations`, `section.recent_activity`, `section.system_alerts`, `section.ai_insights`
- Status labels: `status.online`, `status.offline`, `status.checking`
- Footer: `footer.last_refreshed`

**Step 2: Seed English source strings in DB**

Run a Python script inside Docker that inserts ~20 English rows into `translations` table with `language='en'`, `status='approved'`, `source='imported'`, and context descriptions. These serve as the source for AI batch generation.

**Step 3: Commit**

```bash
git add platform_v2/templates/dashboard_dynamic.html
git commit -m "feat(linguistics): tag dashboard with data-i18n attributes + seed English strings"
```

---

### Task 7: Consciousness Languages Tab

Add the Languages tab UI to the Consciousness dashboard.

**Files:**
- Modify: `platform_v2/tools/consciousness/templates/consciousness_dashboard.html`

**Step 1: Add tab button**

After the Voice tab button (line ~862):
```html
<button class="tab-btn" data-tab="languages">🌐 Languages</button>
```

**Step 2: Add tab content HTML**

After the voice tab content, add `<div id="tab-languages" class="tab-content">` with 3 sub-tabs (reusing the `voice-subtabs` CSS pattern):

**Sub-tab 1: lang-dashboard**
- Stats grid: Total Keys, Approved, Pending Review, Human Edited (stat-card pattern)
- Coverage progress bar with percentage
- Action buttons: Scan Templates, Generate French Translations, Bulk Approve All Pending
- Status text area for feedback

**Sub-tab 2: lang-review**
- Filter dropdown (pending_review, approved, rejected, all)
- Table with: key (monospace), editable translation input, status badge (color-coded), action buttons (approve/save/reject)
- Table built via DOM methods or trusted admin-only data

**Sub-tab 3: lang-glossary**
- Add entry form: English input, French input, category select, Add button
- Table listing: source, translation, category, delete button

**Step 3: Add JavaScript**

Functions to add in the script block:
- `switchLangTab(tabId)` — sub-tab switcher
- `loadLangStats()` — fetch from `/api/translations/stats`, update stat cards + progress bar
- `scanTemplates()` — POST to `/api/translations/scan`, show count
- `generateTranslations()` — POST to `/api/translations/generate`, show results
- `bulkApproveAll()` — fetch pending IDs, PUT to `/api/translations/bulk-approve`
- `loadReviewTable()` — fetch with status filter, render table with inline edit + action buttons
- `reviewAction(id, action)` — PUT to `/api/translations/approve`
- `loadGlossary()` — fetch from `/api/translation-memory`
- `addGlossaryEntry()` — POST to `/api/translation-memory`
- `deleteGlossary(id)` — DELETE to `/api/translation-memory/{id}`
- Hook into tab switching so Languages tab loads stats on open

Note: Table rendering uses admin-only data from the translations DB. All inputs are from the admin's own review actions, not untrusted user content.

**Step 4: Commit**

```bash
git add platform_v2/tools/consciousness/templates/consciousness_dashboard.html
git commit -m "feat(linguistics): Languages tab in Consciousness with dashboard, review, glossary sub-tabs"
```

---

### Task 8: Orchestration Pipeline Integration

Add language detection and response translation steps to the chat pipeline.

**Files:**
- Modify: `ai_bridge/orchestration_engine.py:252-427` — add 2 new pipeline steps

**Step 1: Add language detection after intent parsing**

After Step 1 (parse intent, ~line 254), before Step 2 (IAAE check), add Step 1b:
- Query `user_language_preferences` for user's language and auto_detect setting
- If auto_detect: call `detect_language(message)` from translation_service
- Otherwise: use stored preference
- Add ThinkingStep with `step_type="language_detect"` if non-English detected
- Store `detected_lang` and `user_lang_pref` as local variables

**Step 2: Add response translation after execution**

After Step 7 (execute, ~line 426), before Step 8 (log), add Step 7b:
- Determine `response_lang`: use detected_lang if non-English, otherwise user_lang_pref
- If response_lang != "en" and response_text exists: call `translate_text(response_text, response_lang, "en")`
- Add ThinkingStep with `step_type="translate_response"` if translation applied
- Replace `response_text` with translated version
- Both steps are wrapped in try/except — failures are logged but don't break the pipeline

**Step 3: Restart and test**

```bash
docker restart archie_platform
```

**Step 4: Commit**

```bash
git add ai_bridge/orchestration_engine.py
git commit -m "feat(linguistics): language detection + response translation in orchestration pipeline"
```

---

### Task 9: Deploy and Verify End-to-End

Full integration test and Dev HQ updates.

**Step 1: Run migration if not already done**

```bash
docker cp database/migrations/114_linguistics_tables.sql archie_database:/tmp/
docker exec archie_database psql -U archie -d archie -f /tmp/114_linguistics_tables.sql
```

**Step 2: Restart platform**

```bash
docker restart archie_platform && sleep 15
```

**Step 3: Seed English strings and generate French translations**

Run the seed script from Task 6, then call the generate endpoint.

**Step 4: Approve translations**

Visit Consciousness → Languages tab → Bulk Approve All Pending

**Step 5: Test language switch**

1. Open dashboard, click language button → Français (QC)
2. Verify HUD labels and section headers switch to French
3. Send a chat message in French — verify response comes back in French

**Step 6: Update Dev HQ**

- `mcp log_decision` — "ADR: Chose DB translation cache over real-time AI translation. Rationale: fast page loads, correction persistence, works offline for UI."
- `mcp update_project_understanding` — Project #94

**Step 7: Push**

```bash
git push origin main
```

---

## Summary

| Task | What | Files |
|------|------|-------|
| 1 | DB migration (3 tables) | `database/migrations/114_linguistics_tables.sql` |
| 2 | Translation service | `ai_bridge/translation_service.py`, `ai_bridge/smart_router.py` |
| 3 | Public API endpoints | `platform_v2/app.py` |
| 4 | Admin API endpoints | `platform_v2/tools/consciousness/routes.py` |
| 5 | Frontend i18n script | `platform_v2/static/js/archie-i18n.js`, `base.html`, `dashboard_dynamic.html` |
| 6 | Dashboard data-i18n tags + seed | `platform_v2/templates/dashboard_dynamic.html` |
| 7 | Consciousness Languages tab | `consciousness_dashboard.html` |
| 8 | Orchestration pipeline hooks | `ai_bridge/orchestration_engine.py` |
| 9 | Deploy + verify + Dev HQ | — |
