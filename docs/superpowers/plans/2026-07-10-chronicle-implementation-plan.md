# Chronicle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reframe `mailbox_story` into **Chronicle** — a central, person-centric, multi-source knowledge hub (email + LinkedIn now; Drive/Calendar next) that builds per-entity timelines, stories, and a voice model to draft emails in a person's voice with full background.

**Architecture:** Model A from the spec — per-source imports (reusing the existing `mailbox_story` engine) feeding a new cross-source entity/story/voice layer. Built as 9 independently-shippable slices; **this document details Slice 01 (Rename/Reframe)** in full and **indexes Slices 02–09** as a roadmap (each gets its own detailed plan when reached, because their exact interfaces only firm up once the earlier slices' tables/services exist — writing them now would require placeholders, which this skill forbids).

**Tech Stack:** Python 3.11 · Flask blueprints (`platform_v2/tools/`) · services (`platform_v2/services/` + `tools/*/services/`) · Postgres + pgvector (migrations `database/migrations/NNN_*.sql`, latest **452**) · local-only LLM via `tools.department_hq.services.department_dispatcher.dispatch(..., local_only=True)` · pytest (`platform_v2/tests/`) · tesseract OCR (in-container).

**Spec:** `docs/superpowers/specs/2026-07-10-chronicle-multi-source-entity-hub-design.md`

## Global Constraints

- **All LLM inference is local-only:** every dispatch uses `dispatch(..., local_only=True)` (ADR-013 + the vault's sovereign design). Never call Ollama directly; never a cloud model.
- **Every heavy worker is welfare-gated + resumable** via a status column (`profile_ingest_ledger`, `mailbox_emails.enrich_status`, `mailbox_attachments.extract_status`, an entity-resolution watermark). Idempotent inserts (`ON CONFLICT DO NOTHING`, keyed on `message_id`/`sha256`).
- **Keep the `mailbox_*` table names** as the per-import substrate — the rename is cosmetic (module/UI/routes only). New cross-source data uses `chronicle_*` tables.
- **Deploy is volume-mounted:** `docker compose restart archie_platform archie_scheduler` (no rebuild). Migrations applied via `docker exec -i archie_database psql -U archie -d archie < database/migrations/NNN_*.sql`.
- **Each slice = its own branch + PR** through F.O.R.G.E. review, and is **live-verified on Terry's data** (Gmail `account_id=7`, agent `377`) before closing.
- **Draft-assist NEVER auto-sends** — human approves/edits every draft.
- Migrations are **idempotent** (`CREATE TABLE IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`).

---

# Slice 01 — Rename / Reframe `mailbox_story` → Chronicle

**Goal:** Rebrand the module to "Chronicle" at `/tools/chronicle`, with the old `/tools/mailbox-story` path 307-redirecting (preserves POST bodies), and no behavior change. Table names, blueprint variable, and the module directory stay `mailbox_story` (cosmetic rename only; a later cleanup may rename the dir).

**Files:**
- Modify: `platform_v2/tools/mailbox_story/__init__.py:18` (blueprint `url_prefix`)
- Modify: `platform_v2/module_registry.py:637-649` (id stays, `name`/`route`/`health_check` path)
- Modify: `platform_v2/templates/tools/mailbox_story.html:105` (`const BASE`), `:3` + `:49` (title/heading)
- Modify: `platform_v2/app.py` (add `mailbox_story_compat_redirect`, mirroring `starship_compat_redirect` at :420)
- Modify: `platform_v2/services/mailbox_scout_capture.py` (internal POST URL to capture-share — verify + update)
- Modify: `.claude/rules/module-capability-index.md:192-193` (entry) + `:62` (the `chat_capture` `/tools/mailbox-story/api/capture-share` reference)
- Test: `platform_v2/tests/test_chronicle_rename.py`

**Interfaces:**
- Produces: blueprint `mailbox_story_bp` now served at `url_prefix="/tools/chronicle"`; a compat route so `GET|POST /tools/mailbox-story/<path>` → 307 → `/tools/chronicle/<path>`; registry `id="mailbox_story"` unchanged (so `blueprint_import` + health tracking keep working), `route="/tools/chronicle"`, `name="Chronicle"`.

- [ ] **Step 1: Write the failing test**

```python
# platform_v2/tests/test_chronicle_rename.py
from app import app

def test_new_chronicle_route_serves():
    c = app.test_client()
    # status endpoint is @admin_required; unauthenticated should NOT 404 (route exists → 302 login or 200)
    r = c.get("/tools/chronicle/api/status")
    assert r.status_code != 404, "new /tools/chronicle prefix must be registered"

def test_old_mailbox_story_path_redirects():
    c = app.test_client()
    r = c.get("/tools/mailbox-story/api/status", follow_redirects=False)
    assert r.status_code in (307, 308), f"old path must 307-redirect, got {r.status_code}"
    assert "/tools/chronicle/api/status" in r.headers.get("Location", "")

def test_registry_rebranded():
    from module_registry import MODULES  # adjust import to the actual registry symbol
    m = next(x for x in MODULES if getattr(x, "id", None) == "mailbox_story")
    assert m.name == "Chronicle"
    assert m.route == "/tools/chronicle"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_chronicle_rename.py -v`
Expected: FAIL — old path returns 200/302 (no redirect yet); registry `name` still "Mailbox Story Extractor". (If `MODULES` import symbol differs, fix the import first by reading `module_registry.py` — it's a list/registry of module descriptors.)

- [ ] **Step 3: Change the blueprint prefix + registry branding**

`platform_v2/tools/mailbox_story/__init__.py:18` — change `url_prefix="/tools/mailbox-story"` → `url_prefix="/tools/chronicle"`.
`platform_v2/module_registry.py:637-649` — set `name="Chronicle"`, `route="/tools/chronicle"`, and the `health_check` lambda path `"/tools/chronicle/api/status"`. Leave `id="mailbox_story"` and `blueprint_import` unchanged.

- [ ] **Step 4: Add the 307 compat redirect in app.py**

Mirror `starship_compat_redirect` (`app.py:420`). Add:

```python
@app.route("/tools/mailbox-story", defaults={"subpath": ""})
@app.route("/tools/mailbox-story/<path:subpath>",
           methods=["GET", "POST", "PUT", "DELETE"])
def mailbox_story_compat_redirect(subpath):
    """Chronicle rename (2026-07-10): old Mailbox Story path → /tools/chronicle.
    307 preserves method + body so the internal capture-share POST keeps working."""
    q = ("?" + request.query_string.decode()) if request.query_string else ""
    return redirect(f"/tools/chronicle/{subpath}".rstrip("/") + q, code=307)
```

(Confirm `request` is imported in app.py — it is, used throughout.)

- [ ] **Step 5: Update the template BASE constant + title**

`platform_v2/templates/tools/mailbox_story.html:105` — `const BASE = "/tools/mailbox-story";` → `const BASE = "/tools/chronicle";`.
`:3` — `{% block title %}Mailbox Story Extractor{% endblock %}` → `{% block title %}Chronicle{% endblock %}`.
`:49` — `<h1>Mailbox Story Extractor</h1>` → `<h1>Chronicle</h1>`.

- [ ] **Step 6: Update the internal capture-share caller**

Read `platform_v2/services/mailbox_scout_capture.py`; find the `/tools/mailbox-story/api/capture-share` POST and change it to `/tools/chronicle/api/capture-share` (the 307 redirect would also carry it, but update the source so it's a direct call).

- [ ] **Step 7: Run tests to verify they pass**

Run: `docker compose -f /mnt/archie_brain/docker-compose.yml restart archie_platform && sleep 15 && docker exec archie_platform python3 -m pytest /app/tests/test_chronicle_rename.py -v`
Expected: PASS (3 tests). Then manual: `curl -si http://192.168.1.200:3000/tools/mailbox-story/api/status | head -1` shows `307`.

- [ ] **Step 8: Update the capability index + rules**

`.claude/rules/module-capability-index.md:192` — `### Chronicle — `mailbox_story` · `/tools/chronicle` · ...` and note "(formerly Mailbox Story Extractor; renamed 2026-07-10 → central multi-source entity hub)". Update the `:62` `chat_capture` reference `/tools/mailbox-story/api/capture-share` → `/tools/chronicle/...` (note old path 307-redirects).

- [ ] **Step 9: Commit**

```bash
git add platform_v2/tools/mailbox_story/__init__.py platform_v2/module_registry.py \
  platform_v2/templates/tools/mailbox_story.html platform_v2/app.py \
  platform_v2/services/mailbox_scout_capture.py \
  platform_v2/tests/test_chronicle_rename.py .claude/rules/module-capability-index.md
git commit -m "feat(chronicle): rename mailbox_story module → Chronicle (/tools/chronicle + 307 compat redirect) [slice 01/09]"
```

- [ ] **Step 10: Live-verify + PR**

Browser-verify `/tools/chronicle` renders (login as a temp admin per KB #279406) and the old path redirects. Push branch, open PR, F.O.R.G.E. review, merge, `restart archie_platform archie_scheduler`.

---

# Roadmap — Slices 02–09 (each gets its own detailed plan when reached)

Each slice = its own branch/PR, live-verified on Terry's data. Interfaces below are the contracts the next slice consumes; the detailed TDD plan for a slice is written when its predecessor has landed (so tables/signatures are real, not guessed).

**Slice 02 — Data model (migrations).** Files: `database/migrations/453_chronicle_schema.sql`. Adds: `mailbox_imports.source_kind/source_account_id/is_live_source`; `mailbox_emails.body_html` + drop the body truncation for live sources; `mailbox_attachments`; `chronicle_entity`/`_entity_link`/`_entity_story`/`_voice_profile`; pgvector embedding columns on `mailbox_emails` + `mailbox_attachments`. *Produces:* the schema every later slice writes to. Test: apply migration to a scratch DB, assert columns/tables exist.

**Slice 03 — Attachment pipeline.** Files: `services/chronicle_attachment_service.py` (download → save `/mnt/data2/mailbox_story/<import>/att/…` → extract text: pdf(pdfminer)/docx(python-docx)/plain/OCR(tesseract) → `mailbox_attachments`), a DHQ-registered worker (`tools/mailbox_story/jobs.py` or agent_loop), resumable via `extract_status`, welfare-gated. *Consumes:* Slice-02 `mailbox_attachments`. *Produces:* `extract_attachments_for_email(email_id) -> int`. Test: pdf/docx/image fixtures → asserted extracted_text; OCR path with a scanned-image fixture.

**Slice 04 — Gmail full-content ingestion.** Files: `services/chronicle_gmail_source.py` (fetch `format="full"` per `profile_ingest_ledger` row → full body + attachment parts → `ingest_source(source_kind="gmail", …)`), worker + ledger flags `body_done`/`attach_done`. *Consumes:* Slice-03 attachment service + Slice-06 seam (`ingest_source`). *Produces:* full bodies + attachments in `mailbox_emails`/`mailbox_attachments` tagged `source_kind='gmail'`. Test: mocked Gmail client → asserts body + attachment rows; live: Terry account_id=7 catches up. **Note:** the generalized `ingest_source` seam (below) is a prerequisite — build it first or as part of this slice.

**Slice 05 — `ingest_source` seam + LinkedIn adapter.** Files: generalize `services/mailbox_chat_service.ingest_chat` → `ingest_source(source_kind, source_account, items[], owner_id)`; `services/chronicle_linkedin_source.py` (read `agent_content_posts`/`linkedin_post_log`/`autonomy_approval_queue`(linkedin drafts)/`linkedin_comments`/`linkedin_engagement_ledger` for the target agent → timestamped items, flag Terry-authored for the voice corpus, capture engaged links → `ingest_source(source_kind="linkedin", …)`). *Produces:* Terry's LinkedIn corpus as `mailbox_emails` rows tagged `source_kind='linkedin'`. Test: fixture rows → asserted item mapping + authored-flagging; live: agent 377 counts.

**Slice 06 — Cross-source entity resolution.** Files: `services/chronicle_entity_service.py` (unify per-import `mailbox_entities` person rows → `chronicle_entity` via email/alias-anchored match + confidence threshold + manual-override table), worker + watermark. *Consumes:* Slices 04/05 (multi-source `mailbox_entities`). *Produces:* `resolve_entities(owner_id) -> int`; one "Terry" `chronicle_entity` spanning gmail+linkedin. Test: alias/dedup/false-merge cases.

**Slice 07 — Per-entity story/timeline.** Files: extend `services/mailbox_story_service.py` (clustering keyed on `chronicle_entity` across imports, `dispatch(..., local_only=True, capability="summarize")`) → `chronicle_entity_story`; timeline query over `mailbox_emails` for an entity. *Consumes:* Slice-06 `chronicle_entity`. *Produces:* `build_entity_story(chronicle_entity_id)`. Test: mocked dispatch → asserted story row + timeline ordering.

**Slice 08 — Voice model.** Files: `services/chronicle_voice_service.py` (gather the entity's authored timestamped corpus → local-AI style-guide synthesis → `chronicle_voice_profile`; aligns with S.I.G.N.A.L. `voice_key terry`). *Consumes:* Slice-05 authored-flag + Slice-06 entity. *Produces:* `build_voice_profile(chronicle_entity_id)`. Test: fixture corpus → asserted style_guide JSON shape; mocked dispatch.

**Slice 09 — Draft-assist.** Files: `services/chronicle_draft_service.draft_email(entity, intent, extra_context=None)` (RAG over embeddings + `chronicle_entity_story` + facts + recent thread + `chronicle_voice_profile` → `dispatch(..., local_only=True)` → draft + sources); admin endpoint in `tools/mailbox_story/routes.py` (`POST /tools/chronicle/api/draft`) + a "draft to <entity> with full background" compose action; **human-approved, never auto-send**. *Consumes:* Slices 02/06/07/08 + embeddings. Test: mocked retrieval+dispatch → asserted draft assembly + no-auto-send guard; live: draft a Terry email, human review.

**Deferred source roadmap (post-09, own specs):** Google **Drive** + **Calendar** adapters (reuse `google_work_suite` Google OAuth — already wired) via the same `ingest_source` seam; then LinkedIn profile/connections/inbox capture; then SMS/WhatsApp/on-disk docs.

---

## Self-Review

- **Spec coverage:** rename (Slice 01) · full body + attachments + `chronicle_*` schema (02) · attachment files+OCR (03) · Gmail complete ingestion (04) · ingest seam + LinkedIn (05) · entity resolution (06) · story/timeline (07) · voice model (08) · draft-assist (09) · Drive/Calendar + other sources (deferred roadmap). All spec sections map to a slice.
- **Placeholder scan:** Slice 01 has concrete file:line targets, real code, exact commands. Slices 02–09 are intentionally roadmap-level (interfaces defined, detailed steps deferred until predecessors land — the skill's guidance against guessing unbuilt interfaces).
- **Type consistency:** `ingest_source(source_kind, source_account, items[], owner_id)` used consistently in 04/05; `chronicle_entity` / `build_entity_story` / `build_voice_profile` / `draft_email` names consistent across 06–09.
