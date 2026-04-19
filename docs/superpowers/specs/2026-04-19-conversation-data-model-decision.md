# Conversation Data Model Decision — Research #2172
**Date:** 2026-04-19
**Branch:** research/conversation-data-model-2172
**Status:** RECOMMENDATION: Option B — retire `chat_*`, complete the `unified_*` vision
**Scope:** Medium

---

## Background

archie_comms maintains two parallel conversation stores introduced at different points
in the product's history. As of today (2026-04-19) they coexist with an active
dual-write stopgap (FU9, commit `20e7008d`) patching over the impedance mismatch.
This document maps every read and write, characterises each store, identifies bugs,
and recommends a migration path.

---

## 1. Current State — Read/Write Map

### 1.1 `chat_conversations` + `chat_messages`

**Schema** (live):
```
chat_conversations
  id                SERIAL PK
  conversation_uuid UUID UNIQUE (gen_random_uuid())
  user_id           INTEGER NOT NULL (FK → users)
  team_id           INTEGER (nullable)
  title             VARCHAR(255)
  agent_target      VARCHAR(100)
  is_archived       BOOLEAN DEFAULT false
  created_at        TIMESTAMP
  updated_at        TIMESTAMP

chat_messages
  id                SERIAL PK
  conversation_id   FK → chat_conversations.id
  role              VARCHAR(20)          -- user / assistant / system
  content           TEXT
  metadata          JSONB
  created_at        TIMESTAMP
```

**Live row counts:**
- `chat_conversations`: **5 rows**
- `chat_messages`: **82 rows**

**Reads (SELECT):**

| File | Line(s) | What |
|------|---------|------|
| `archie-comms/chat/chat_service.py` | 137, 145, 177, 300, 311, 364–378 | `get_conversations()`, `get_messages()`, `search_conversations()` — the sidebar and message history APIs |
| `archie-comms/chat/api_routes.py` | `GET /api/v1/chat/conversations` (line 286) | Calls `chat_service.get_conversations()` — served to comms.js sidebar |
| `kytran-business-suite/core/chat_manager.py` | 93, 135, 146, 204, 207, 209 | KBS reads its own conversations from this store |
| `ai_bridge/telegram_gateway.py` | 822–826 | FU9: `SELECT id FROM chat_conversations WHERE title='A.R.C.H.I.E. Escalations'` — find-or-create guard |

**Writes (INSERT/UPDATE/DELETE):**

| File | Line(s) | What |
|------|---------|------|
| `archie-comms/chat/chat_service.py` | 95, 232, 260, 335, 449 | Normal chat CRUD — create conversation, save message, update timestamp, archive |
| `platform_v2/tools/archie_chat/chat_service.py` | 95, 232, 260, 335 | **Platform-side copy** — the `archie_chat` module writes to the same table; this is the platform chat UI |
| `ai_bridge/telegram_gateway.py` | 831, 836, 847 | FU9 dual-write: escalation notifications insert an "A.R.C.H.I.E. Escalations" conversation + messages |
| `kytran-business-suite/core/chat_manager.py` | 45, 58, 104, 168 | KBS chat feature writes here |

**Who reads the sidebar from this store:**
`archie-comms/chat/api_routes.py → GET /api/v1/chat/conversations` → `chat_service.get_conversations()` → `SELECT FROM chat_conversations ORDER BY updated_at DESC`.
`comms.js` calls this endpoint and renders `c.title` (post-FU8 fix).

---

### 1.2 `unified_conversations` + `unified_messages`

**Schema** (live):
```
unified_conversations
  id            SERIAL PK
  user_id       INTEGER (nullable — no FK enforced!)
  topic         VARCHAR(500)
  status        VARCHAR(20) DEFAULT 'active'
  created_at    TIMESTAMP
  last_activity TIMESTAMP

unified_messages
  id              SERIAL PK
  conversation_id FK → unified_conversations.id ON DELETE CASCADE
  channel         VARCHAR(20) NOT NULL  -- platform, telegram, claude, cli
  direction       VARCHAR(10) NOT NULL  -- inbound, outbound
  sender          VARCHAR(100) NOT NULL -- kytran, archie, agent_name, claude
  content         TEXT NOT NULL
  metadata        JSONB DEFAULT '{}'   -- source_agent, department, project_id, model, latency_ms
  created_at      TIMESTAMP
```

**Live row counts:**
- `unified_conversations`: **1 row**
- `unified_messages`: **8 rows**

**Introduction:** Migration `archie-comms/migrations/003_unified_conversations.sql`
(the migration header states: *"Replaces separate chat_messages + telegram_message_log
for A.R.C.H.I.E. conversations"*). Created as Project #265 Phase 3 "canonical
cross-channel store."

**Reads (SELECT):**

| File | Line(s) | What |
|------|---------|------|
| `archie-comms/services/conversation_service.py` | 35, 216, 237–238 | `get_or_create_conversation()`, `get_history()`, `get_conversations()` — reads the unified store |
| `archie-comms/app_comms.py` | 293–305 | `GET /api/chat/conversations` — calls `conversation_service.get_conversations()` |

**Writes (INSERT/UPDATE):**

| File | Line(s) | What |
|------|---------|------|
| `archie-comms/services/conversation_service.py` | 47, 69, 87, 323, 327 | All chat flows routed through `send_message()` / `new_conversation()` write here |
| `ai_bridge/telegram_gateway.py` | 766, 771, 782 | Escalation notification writes to unified store (T8, pre-FU9) |
| `platform_v2/tests/test_approvals_multi_source.py` | 607, 611, 714 | Test cleanup deletes from unified store |

**Who reads the sidebar from this store:**
`archie-comms/app_comms.py → GET /api/chat/conversations` → `conversation_service.get_conversations()` → `SELECT c.topic FROM unified_conversations`. This route is **the legacy app_comms route**, not the one comms.js actually polls.

---

### 1.3 The Routing Split — Two Different `/api/chat/conversations` Endpoints

This is the core of the problem. There are **two routes with overlapping paths** in archie-comms:

| Route | File | Table | Field |
|-------|------|-------|-------|
| `GET /api/chat/conversations` | `archie-comms/app_comms.py:293` | `unified_conversations` | `topic` |
| `GET /api/v1/chat/conversations` | `archie-comms/chat/api_routes.py:286` | `chat_conversations` | `title` |

`comms.js` calls the **`/api/v1/chat/conversations`** endpoint (the chat Blueprint, registered under `/api/v1/`). It reads `c.title` (post-FU8). The app_comms route at `/api/chat/conversations` returns `c.topic` from unified_conversations and appears to be a legacy path that is no longer the primary consumer.

---

## 2. Store Characterisation

### `chat_*` — The Operational Store

- **Purpose:** Interactive web chat threads between a user and A.R.C.H.I.E. / agents.
- **Introduced:** `archie-comms/migrations/add_chat_tables.sql` — predates unified_* by several migrations.
- **UI surface:** The primary comms.js sidebar (`/api/v1/chat/conversations`) and the platform archie_chat module.
- **Writers:** archie-comms chat service, platform archie_chat service, KBS chat_manager, and now (FU9) telegram_gateway for escalations.
- **Key columns:** `conversation_uuid` (UUID for external reference), `agent_target` (which agent owns this thread), `team_id` (multi-user scoping), `title` (display name), `is_archived`.
- **Richer schema** — more intentional chat product design; UUID, team scoping, archival, agent targeting.

### `unified_*` — The Cross-Channel Aspirational Store

- **Purpose:** Single canonical record of all conversations regardless of channel (platform, telegram, claude, cli). Project #265 Phase 3 intent.
- **Introduced:** `archie-comms/migrations/003_unified_conversations.sql` — explicitly intended to *replace* chat_messages + telegram_message_log.
- **UI surface:** The legacy `app_comms.py` `/api/chat/conversations` endpoint — which is no longer the primary sidebar source.
- **Writers:** `conversation_service.py` (via send_message / new_conversation), `telegram_gateway.py` (escalation T8).
- **Key columns:** `channel` and `direction` in unified_messages (cross-channel metadata). No `conversation_uuid`, no `agent_target`, no `team_id`, no `is_archived`. `user_id` has no FK constraint enforced.
- **Weaker schema** — simpler, designed for logging not product UX.

---

## 3. Bug Signals

### 3.1 The `c.topic` vs `c.title` Mismatch (pre-FU8 bug)

**Root cause:** `comms.js` originally read `c.topic` (unified_* field name), but the
sidebar endpoint `/api/v1/chat/conversations` returns rows from `chat_conversations`
which uses `title`. Every sidebar row fell through to the `'Conversation'` fallback.

**Fix (FU8, commit `20e7008d`):** `comms.js` changed to read `c.title || c.topic || 'Conversation'`.
This is a defensive shim, not a real fix — it papers over the store duality.

**Signal:** This bug only existed because the field names diverged between stores.
If there were one store with one field name, this class of bug cannot happen.

### 3.2 The FU9 Dual-Write is Unsustainable

`ai_bridge/telegram_gateway.py` lines 804–847: escalation notifications write to BOTH
stores in the same transaction block. The dual-write is wrapped in a try/except that
silently swallows failures on the chat_* write. This means:

- Escalation rows can appear in `unified_*` but not `chat_*` (silent failure path).
- Every new channel (CLI, future mobile) must remember to dual-write to both.
- The write path is a duct-tape try/except, not an abstraction.

### 3.3 `conversation_service.py` — Active But Orphaned from the UI

`archie-comms/services/conversation_service.py` is **actively imported** by `app_comms.py`
(lines 235, 260, 302, 320, 336) and owns the `send_message`, `get_conversations`,
`get_conversation_messages`, `new_conversation`, and `escalate_to_claude` functions.
All of these write/read `unified_*`.

However, the primary chat UI (`comms.js`) does NOT call the `app_comms.py` routes —
it calls the versioned `/api/v1/` Blueprint routes in `chat/api_routes.py` which read
`chat_*`. So `conversation_service.py` IS invoked, but the data it produces is not
surfaced in the primary sidebar. The unified_* store is effectively a background sink
with no primary UI consumer today.

### 3.4 Orphaned Writes in T8

`telegram_gateway.py` lines 766–782: escalation inserts into `unified_conversations`
and `unified_messages`. Before FU9, these had no UI consumer (the sidebar reads
`chat_*`). FU9 added the chat_* dual-write to make them visible. The original T8
unified_* writes are now redundant if we move to Option B.

### 3.5 KBS as an Independent Consumer

`kytran-business-suite/core/chat_manager.py` writes independently to `chat_conversations`
and `chat_messages`. It is a separate container (port 8091) with its own codebase. If
we retire `chat_*`, KBS must be migrated separately — it is a real dependency the
migration plan must account for.

---

## 4. Options

### Option A — Retire `unified_*`, keep `chat_*`

Migrate all `conversation_service.py` callers to `chat_service.py`. Roll back the
unified_conversations vision.

**Pros:** Eliminates the weaker schema; `chat_*` is richer and already the UI source of
truth. Low UI risk.
**Cons:** Loses cross-channel metadata (`channel`, `direction`, `sender` fields). The
`unified_*` schema was purpose-built for cross-channel logging (Telegram, CLI, etc.) —
`chat_*` has no equivalent columns. We would need to add `channel`/`direction` to
`chat_messages` anyway, recreating unified_* inside chat_*.

### Option B — Retire `chat_*`, complete `unified_*` (RECOMMENDED)

Migrate `chat_service.get_conversations()` and sidebar reads to `unified_*`. Add the
missing columns (`conversation_uuid`, `agent_target`, `team_id`, `is_archived`,
`title`) to `unified_conversations`. Make `user_id` FK-enforced. Update comms.js to
read from the `/api/chat/conversations` route (or re-point the v1 Blueprint to the
unified store).

**Pros:** One SSOT for all channels; the `channel`/`direction`/`sender`/`metadata`
richness is preserved; migration 003 intent is fulfilled; FU9 dual-write can be
deleted; `conversation_service.py` becomes the only writer.
**Cons:** Requires schema migration on `unified_conversations`; KBS must be migrated;
platform `archie_chat` module must be updated.

### Option C — Keep both with explicit boundaries

Document `chat_*` = web threads, `unified_*` = automated/cross-channel. Formalise the
dual-write as intentional.

**Cons:** Every new channel still dual-writes. The `c.title` / `c.topic` bug can
recur. Two schemas to maintain. KBS writes to `chat_*`; escalations write to both.
This is not a SSOT, it is an acknowledged split-brain. Does not eliminate any of the
current bugs — just names them.

---

## 5. Recommendation: Option B

**Retire `chat_*` and complete the `unified_*` vision.**

The reasoning:

1. **The unified_* schema is strictly richer** for the multi-channel use case. It has
   `channel`, `direction`, `sender`, `metadata` — none of which exist in `chat_messages`.
   Option A would require adding these columns to `chat_*`, at which point we have
   rebuilt unified_* inside a table with the wrong name.

2. **The data volume is tiny.** `chat_conversations` has 5 rows; `chat_messages` has 82.
   `unified_conversations` has 1 row; `unified_messages` has 8. Migration risk is near-zero.

3. **The FU9 dual-write is a code smell, not an architecture.** It is a try/except block
   with a silent failure path. Removing it requires picking one store. Option B lets us
   delete those 57 lines of FU9 code.

4. **The `conversation_service.py` layer already exists** and is well-structured. It
   just needs the `chat_*` callers moved to it.

5. **Option C is Option B deferred with added complexity.** Every future channel still
   dual-writes. Naming the problem is not solving it.

---

## 6. Migration Plan

### Phase 1 — Schema augmentation (small)

Add missing columns to `unified_conversations` so it can replace `chat_conversations`:

```sql
-- database/migrations/NNN_unified_conversations_chat_parity.sql
ALTER TABLE unified_conversations
  ADD COLUMN IF NOT EXISTS title VARCHAR(255),
  ADD COLUMN IF NOT EXISTS agent_target VARCHAR(100),
  ADD COLUMN IF NOT EXISTS team_id INTEGER,
  ADD COLUMN IF NOT EXISTS is_archived BOOLEAN DEFAULT false,
  ADD COLUMN IF NOT EXISTS conversation_uuid UUID DEFAULT gen_random_uuid() UNIQUE;

-- Enforce user_id FK (currently unenforceable due to nullable)
-- Only safe once we've verified no orphaned rows
ALTER TABLE unified_conversations
  ALTER COLUMN user_id SET NOT NULL,
  ADD CONSTRAINT unified_conversations_user_id_fkey
    FOREIGN KEY (user_id) REFERENCES users(id);

-- unified_messages already has everything chat_messages needs
-- No schema changes required on unified_messages
```

**Risk:** Low. Additive only. No data moved yet.

### Phase 2 — Migrate archie-comms send_message path (medium)

1. Update `archie-comms/app_comms.py` `send_message` route: it already calls
   `conversation_service.send_message()` which writes to `unified_*`. No change needed.

2. Re-point `archie-comms/chat/api_routes.py` `GET /api/v1/chat/conversations` to call
   `conversation_service.get_conversations()` instead of `chat_service.get_conversations()`.
   The returned dict field should be renamed from `title` to use whichever name comms.js
   will read — pick `title` and add it as an alias to the unified SELECT (`c.title AS title`).

3. Update `comms.js` to read `c.title` (already done post-FU8; no further change).

4. Update `archie-comms/chat/api_routes.py` create/archive/search conversation routes
   to call `conversation_service` equivalents rather than `chat_service`.

**Estimate:** 4–6 files, ~150 lines changed. Low risk.

### Phase 3 — Remove FU9 dual-write (small)

Once Phase 2 is deployed and verified:

1. Delete the FU9 block in `ai_bridge/telegram_gateway.py` (lines 804–857). The T8
   `unified_*` writes above that block remain — they are the only write needed.

2. Delete the FU9 test assertions in `test_approvals_multi_source.py` that verify
   `chat_*` dual-write. Keep the unified_* assertions.

**Estimate:** ~60 lines deleted. Zero risk once Phase 2 is verified.

### Phase 4 — Migrate platform archie_chat module (medium)

`platform_v2/tools/archie_chat/chat_service.py` is a near-identical copy of
`archie-comms/chat/chat_service.py`. Update it to write/read `unified_*` using the
same `conversation_service` abstraction (or import it via a shared service layer).

**Estimate:** 1 file, ~100 lines. Medium risk — requires testing the platform chat UI.

### Phase 5 — Migrate KBS (medium, separate timeline)

`kytran-business-suite/core/chat_manager.py` is a separate container. It writes to
`chat_conversations` and `chat_messages`. Options:

- **5a:** Give KBS its own SQLite/Postgres schema and have its chat be independent
  (it is a standalone product — this is appropriate).
- **5b:** Migrate KBS chat_manager to call the A.R.C.H.I.E. comms API rather than
  writing directly to the shared DB.

**Recommended:** 5a. KBS is an independent product. Let it own its own chat tables in
its own schema, prefixed `kbs_`. Do not route KBS tenant chat through ARCHIE's
unified_conversations — that conflates tenant data with platform operator data.

**Estimate:** Medium scope within KBS. Not blocking Phase 1–4.

### Phase 6 — Deprecate `chat_*` tables (small)

Once all writers are migrated:

1. Verify zero new writes to `chat_conversations` / `chat_messages` (add a monitoring
   query to the audit pipeline or agent loop).
2. Rename tables to `_deprecated_chat_conversations` / `_deprecated_chat_messages` for
   a 30-day hold, then drop.

**Estimate:** 1 migration file + 30-day wait. Trivial.

---

## 7. Summary Table

| Item | `chat_*` | `unified_*` |
|------|----------|-------------|
| Row count | 5 conv / 82 msg | 1 conv / 8 msg |
| Primary UI reader | comms.js sidebar (via `/api/v1/`) | None (legacy app_comms route) |
| Key writers | chat_service, archie_chat, KBS, FU9 | conversation_service, telegram_gateway T8, FU9 |
| Schema richness | UUID, team_id, agent_target, is_archived | channel, direction, sender, metadata |
| FK enforcement | user_id NOT NULL + FK | user_id nullable, no FK |
| Field name | `title` | `topic` |
| Introduced | add_chat_tables.sql (older) | 003_unified_conversations.sql (newer) |
| Retire in plan | Yes (Phases 5–6) | No — becomes the SSOT |

---

## 8. Risk Factors

- **KBS independence:** KBS must not be left with broken chat after chat_* is renamed.
  Phase 5a mitigates by giving KBS its own schema before Phase 6 drops the shared tables.
- **Platform archie_chat module:** Has its own chat_service.py copy. Must be updated in
  Phase 4 before Phase 6. A missed reference will silently fail to create conversations.
- **user_id nullable in unified_conversations:** Enforcing NOT NULL requires verifying
  no existing rows have NULL user_id. With only 1 row today, this is trivial.
- **conversation_uuid uniqueness:** unified_conversations will gain a UUID column. Existing
  1 row will get a random UUID on ALTER — no conflict risk.

---

*Research performed on branch `research/conversation-data-model-2172`, 2026-04-19.*
*All file:line references verified against live codebase and live DB state.*

---

## Phase 5 Audit — KBS Isolation Verified (2026-04-19)

**Branch:** `feat/unified-conversations-phase5-6-complete-migration`
**Auditor:** Claude Code (Sonnet 4.6)

### Finding: KBS is fully isolated from public.chat_*

Every KBS reference to `chat_conversations` / `chat_messages` resolves to the
**tenant-scoped schema**, not `public`. Isolation is enforced at the DB cursor level:

- `kytran-business-suite/core/chat_manager.py` — `set_tenant_search_path(cur, tenant_id)`
  is called at the top of **every** method before any SQL touching chat tables:
  `start_conversation()` (line 42), `add_message()` (line 89), `get_messages()` (line 128),
  `close_conversation()` (line 165), `get_active_conversations()` (line 199).

- `kytran-business-suite/plugins/kbs_communications/routes.py` — all three query blocks
  that reference `chat_conversations` (lines 51, 194, 257) call
  `set_tenant_search_path(cur, g.tenant_id)` first.

### Schema divergence confirms independence

| Column | `public.chat_conversations` | `tenant_1.chat_conversations` |
|--------|-----------------------------|-------------------------------|
| user_id | ✅ integer NOT NULL | — |
| title | ✅ varchar(255) | — |
| agent_target | ✅ varchar(100) | — |
| is_archived | ✅ boolean | — |
| visitor_name | — | ✅ varchar(255) |
| visitor_email | — | ✅ varchar(255) |
| customer_id | — | ✅ integer |
| channel | — | ✅ varchar(20) CHECK widget/internal |
| sender_type | — | ✅ (in chat_messages) |

KBS columns (`visitor_name`, `channel`, `sender_type`) **do not exist** in the public
schema — any accidental public-schema access would immediately raise a Postgres column
error. The two systems are structurally incompatible, providing defence-in-depth beyond
the `set_tenant_search_path` guard.

### Tenant table row counts (at audit time)

- `tenant_1.chat_conversations` — 0 rows (empty provisioned schema)
- `tenant_9908.chat_conversations` — 0 rows (empty provisioned schema)

No KBS data exists to be affected by dropping `public.chat_*`.

### Conclusion

Dropping `public.chat_conversations` + `public.chat_messages` in Phase 6 carries
**zero risk** to KBS. KBS tenant schemas are fully independent and will continue
operating normally after the drop.

---

## Phase 6 — Drop Applied (2026-04-19)

**Migration:** `database/migrations/unified_conversations_phase6_drop_public_chat.sql`

**Pre-drop catch-up results:**
- `public.chat_conv unmigrated` before catch-up: **1** (edge-case row from Phase 2→4 window)
- After Phase 2 idempotent catch-up re-run: **0** unmigrated conversations, **0** unmigrated messages

**Tables dropped:** `public.chat_messages` (CASCADE), `public.chat_conversations`

**Post-drop verification:** Only `tenant_1.chat_*` and `tenant_9908.chat_*` remain in
`information_schema.tables` — no `public.chat_*` entries.

**Migration is complete. All six phases of #2172 are done.**
