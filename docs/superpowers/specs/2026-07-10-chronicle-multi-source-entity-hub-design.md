# Chronicle — Central Multi-Source Entity Hub

**Date:** 2026-07-10
**Status:** Approved design → implementation planning
**Extends:** Mailbox Story Extractor (`mailbox_story`, ADR-768) · Email Memory Vault (`google_work_suite`, ADR-001)

---

## 1. Goal

Build **Chronicle**: a central, **person-centric** knowledge hub that ingests and **retains** a person's full communications from multiple sources (starting with **Gmail** + **LinkedIn**), fuses them into per-entity **timelines, stories, and a voice model**, and uses that to **draft emails in that person's voice with their full background** — beginning with Terry. Designed so more sources (SMS, WhatsApp, documents) slot in later.

The name reflects the purpose: a timestamped **chronicle** of each person, built from everything we know about them.

## 2. Context / why this shape

- The **Email Memory Vault** (`google_work_suite`) ingests Gmail but keeps only metadata + AI-extracted *facts*; it reads bodies transiently (6k-char cap) and ignores attachments (verified live 2026-07-10). It is a *facts extractor*, not a full archive.
- The **Mailbox Story Extractor** (`mailbox_story`) already reconstructs **entities → timeline → narrative** from ingested content, all local-AI, welfare-gated — but it is **per-import** (per uploaded file), stores **truncated** bodies, and has **no attachment download/OCR**.
- We already hold Terry's **authored LinkedIn voice corpus** (posts / comments / engagement, all timestamped) but **not** his profile / connections / inbox.

Rather than build a parallel story engine, Chronicle **reuses `mailbox_story`'s working engine** and adds a **cross-source entity/story/voice layer** plus **complete-content ingestion** (full bodies + attachment files + OCR).

## 3. Scope

**In scope (this program):**
- Rename/reframe `mailbox_story` → **Chronicle**: a per-**entity** hub fed by per-**source** imports (model A).
- Complete ingestion: **full email bodies** + **attachment files (on disk) + OCR/extracted text**.
- **Gmail** source adapter (complete content) + **LinkedIn** source adapter (Terry's stored authored corpus + engaged links, timestamped).
- Cross-source **entity resolution** (one "Terry" across email + LinkedIn).
- Per-entity **story/timeline** (reuse engine) + **voice model** (style guide from the authored corpus).
- **Draft-assist**: RAG-hybrid drafting in the entity's voice, with background. Human-approved before send.

**Deferred (later slices/specs), in likely order:**
- **Google Drive** (documents) + **Google Calendar** (events: attendees, dates, subjects) — high value and low cost because they **reuse the existing `google_work_suite` Google OAuth** (Drive/Calendar are already wired in services, just unexposed); each is a small source adapter on the same `ingest_source` seam.
- LinkedIn **profile / connections / following / DM-inbox** persistent capture (ephemeral browser skills today).
- Additional sources (SMS, WhatsApp, on-disk documents).
- Standalone extraction of Chronicle.

**Out of scope:** the S.I.G.N.A.L. posting flow; the general Email Manager.

## 4. Architecture (model A)

```
SOURCES  ──ingest seam──►  CHRONICLE HUB  ─────►  KNOWLEDGE  ────►  APPLICATION
 Gmail (full)             per-source import        per-entity        draft-assist
 LinkedIn (authored)      + full body              timeline/story    (in-voice,
 [future: SMS, docs]      + attachments (file+OCR)  + voice model      w/ background,
                          + cross-source entity                        human-approved)
                            resolution
```

- Each **source** lands as a per-source **import** (reusing `mailbox_imports`), tagged with `source_kind`.
- The existing **enrich** worker (local-AI) tags per-email facts + entities per import.
- A **new cross-source layer** resolves per-import entities into global **`chronicle_entity`** records and builds per-entity **story / timeline / voice**.
- **Draft-assist** retrieves an entity's story + facts + relevant bodies/documents + voice profile → local drafting model → draft.

Model A keeps imports as the per-source landing zone (reusing the whole working engine) and adds the person-centric hub above it. (Rejected: a full refactor to a source+global-entity schema — cleaner long-term but rewrites the working engine; not worth the blast radius now.)

## 5. Data model (extends the `mailbox_*` schema; new migrations)

**Changed:**
- `mailbox_imports`: add `source_kind` (gmail|linkedin|pst|onenote|chat), `source_account_id` (nullable), `is_live_source` (bool). Gmail/LinkedIn are *live* sources, not one-shot uploads (re-ingested incrementally).
- `mailbox_emails`: store **full** `body_text` (drop the `_BODY_CAP` truncation for live sources) + `body_html` (nullable); make `has_attachments` accurate.

**New:**
- `mailbox_attachments` (id, email_id FK, filename, mime_type, size_bytes, sha256, stored_path, extracted_text, ocr_used bool, extract_status). File on `/mnt/data2`, text in DB; `sha256` dedups.
- `chronicle_entity` (id, owner_id, canonical_name, entity_type, aliases[], created_at) — the cross-source person/org.
- `chronicle_entity_link` (chronicle_entity_id, mailbox_entity_id) — maps per-import entities → the global entity.
- `chronicle_entity_story` (chronicle_entity_id, narrative, span_start/end, source_kinds[], model_used, updated_at) — fused per-entity story across sources.
- `chronicle_voice_profile` (chronicle_entity_id, style_guide [JSON: tone, phrasings, greetings/sign-offs, vocabulary, topics/links], sample_count, span_start/end, model_used, updated_at).
- **Embeddings** (pgvector) over `mailbox_emails.body_text` + `mailbox_attachments.extracted_text` — the retrieval index.

**Voice corpus** = a view over the entity's *authored*, timestamped content: owner-sent Gmail messages + LinkedIn posts/comments/engagement text.

## 6. Sources + the ingest seam

**Common seam:** generalize `mailbox_chat_service.ingest_chat` into `ingest_source(source_kind, source_account, items=[{role, text, sent_at, from, to, subject, message_id, attachments?}], owner_id)` → creates/updates a per-source import + `mailbox_emails` rows → sets `status='extracted'` → DHQ enrich/story workers auto-run. Attachments handed to the attachment pipeline. Idempotent via `message_id` / `sha256` (`ON CONFLICT DO NOTHING`).

**Gmail adapter** (`chronicle_gmail_source`): the complete-content ingestion — a new worker fetches `format=full` for every enumerated message (reusing `profile_ingest_ledger`, which already lists all ids), stores the full body, downloads attachments, then calls `ingest_source(source_kind='gmail', …)`. Resumable, welfare-gated, Gmail-quota-aware.

**LinkedIn adapter** (`chronicle_linkedin_source`): reads the already-stored tables for the target agent — `agent_content_posts` (37), `linkedin_post_log` (21), `autonomy_approval_queue` linkedin drafts (31), `linkedin_comments` (17 inbound), `linkedin_engagement_ledger` (67 actions w/ comment text + engaged links) — maps each to a timestamped item, flags Terry-authored items for the voice corpus, captures shared links → `ingest_source(source_kind='linkedin', …)`. Profile/connections/inbox capture is deferred (needs new persistence).

## 7. Attachment pipeline (files + OCR)

New worker (welfare-gated, resumable via `mailbox_attachments.extract_status`): for each email with attachment parts → download via the source API (Gmail attachments API for the gmail source) → save to `/mnt/data2/mailbox_story/<import>/att/<email>/<filename>` → text-extract by type: PDF (pdftotext/pdfminer), docx (python-docx), plain (direct), images/scans (**tesseract OCR**, already in-container) → store `extracted_text` + `sha256`. Non-extractable types kept file-only.

## 8. Cross-source entity resolution

New worker: unify per-import `mailbox_entities` (person type) into `chronicle_entity` by normalized name / email / alias → `chronicle_entity_link`, with a confidence threshold + manual-override to avoid false merges. Then, keyed on `chronicle_entity` across imports: **story synthesis** (reuse `mailbox_story_service` clustering, local-AI `summarize`) → `chronicle_entity_story`; **voice synthesis** → `chronicle_voice_profile`.

## 9. Voice model

`chronicle_voice_service`: gather the entity's authored, timestamped text (owner-sent Gmail + LinkedIn posts/comments/engagement) → local-AI synthesis of a **style guide** (tone, sentence length, greetings/sign-offs, characteristic phrasings, vocabulary, the topics + links he engages with) → `chronicle_voice_profile`. Aligns with / can feed the existing S.I.G.N.A.L. `voice_key terry` persona-pack. Recomputed as new authored content lands.

## 10. Draft-assist

`chronicle_draft_service.draft_email(entity, intent, extra_context?)`:
1. **Retrieve**: `chronicle_entity_story` + top facts + semantically-retrieved relevant bodies/attachments (RAG over embeddings) + recent thread(s) + `chronicle_voice_profile`.
2. **Assemble** a grounded prompt (background + voice style guide + intent).
3. **Dispatch** to a **local** drafting model via DHQ (`local_only=True`, sovereign) → return a draft + the sources it drew on.
4. **Surface**: an admin endpoint + a "draft to &lt;entity&gt; with full background" action wired into the compose flow / archie_chat. **Human approves/edits before send — never auto-send.**

## 11. Rename plan (mailbox_story → Chronicle)

Bounded, mostly cosmetic:
- Module UI title "Mailbox Story" → "Chronicle"; route prefix `/tools/mailbox-story` → `/tools/chronicle` (+ 308 redirect from the old path).
- `module_registry.py` + `rbac.py` entries; `.claude/rules/` + capability index + KB refs.
- **Keep the `mailbox_*` table names** as the per-import substrate (a table rename is risky and adds nothing functional); new cross-source data uses `chronicle_*`. A later cleanup can rename tables if desired.

## 12. Cross-cutting

- **Privacy / sovereignty:** all inference local-only (`dispatch(local_only=True)`), the owner's own data, self-hosted — consistent with both source modules.
- **Welfare + quota:** every heavy worker (full-content fetch, OCR, synthesis) routes through DHQ, welfare-gated; Gmail-quota-aware (429 backoff); a token/compute budget for the ~11.5k full fetches + OCR + synthesis backfill.
- **Resumability:** each stage keyed on a status column (`profile_ingest_ledger` for enumeration, `mailbox_emails.enrich_status`, `mailbox_attachments.extract_status`, an entity-resolution watermark).

## 13. Build order (one spec, verifiable slices → sequenced PRs)

1. **Rename/reframe** mailbox_story → Chronicle (module, route+redirect, registry, UI, rules) — no behavior change.
2. **Data model**: full body + `mailbox_attachments` + `chronicle_*` tables + embeddings (migrations).
3. **Attachment pipeline** (download + OCR) — verify on an existing import.
4. **Gmail full-content ingestion** (format=full + attachments) → feeds the hub via the seam.
5. **LinkedIn adapter** (stored authored corpus → hub).
6. **Cross-source entity resolution** → `chronicle_entity`.
7. **Per-entity story/timeline** (reuse engine, keyed on `chronicle_entity`).
8. **Voice model** (`chronicle_voice_profile`).
9. **Draft-assist** (RAG hybrid) + compose surface.

Each slice ships + is verified independently (live-verified on Terry's data, as with today's ingestion check).

## 14. Testing

Per slice: unit tests for the source adapters (deterministic item mapping), the attachment extractor (PDF/docx/OCR fixtures), entity resolution (alias/dedup cases), voice/story synthesis (mocked dispatch), draft-assist (mocked retrieval + dispatch). Plus live verification on Terry's real data per slice.

## 15. Risks / open questions

- **Table-rename risk** — mitigated by keeping `mailbox_*` + layering `chronicle_*` (cosmetic module rename only).
- **Gmail quota/cost** for ~11.5k full fetches + attachment downloads + OCR — bounded by welfare/quota gating + resumability; a multi-day background backfill is acceptable.
- **Voice-model quality** depends on authored-corpus volume (Terry: ~1,199 sent emails + ~140 LinkedIn authored items — sufficient).
- **Entity resolution false-merges** — mitigated by email/alias-anchored matching + a confidence threshold + manual override.
- **OAuth token longevity** — the vault froze for a month on a dead refresh token; a Gmail token-health alert (separate follow-up) should land so a live source can't silently stall.
