# Email-History Ingestion → Personal Profile ("Memory Vault")

**Status:** Design / proposed
**Owner module:** `platform_v2/tools/google_work_suite/` (new `memory_vault/` service package)
**Author:** Synthesis of three design lenses (pragmatic reuse / resumable-pipeline / profile-first), grounded in real code.
**Goal:** Ingest Kytran's entire ~10-year Gmail history across 2 accounts and turn it into a structured, owner-scoped, queryable PERSONAL PROFILE so the mail agent (R.E.S.O.L.V.E. / A.R.C.H.I.E.) genuinely knows who he is, his relationships, his history, and his communication style — and drafts in his voice.

---

## 1. Overview & Goal

The mail agent today (`gmail_service._dispatch_to_bridge`) reasons about each email in isolation: it sees `From / Subject / body[:2000]` and produces a one-shot priority/category/draft. It has **no memory** of who the correspondent is, what Kytran's history with them is, or how Kytran normally writes to them.

This design builds a **persistent personal-memory layer** populated by a resumable, idempotent, tier-routed FLEET pipeline:

- **Ingest** the full mailbox of both accounts (not just `INBOX`, not just 50 messages).
- **Triage** every message cheaply (Gmail's own labels + heuristics + a 1.5B pre-filter) so a 7B model NEVER runs on ~40k promo/newsletter emails.
- **Extract** structured facts (people, orgs, relationships, commitments, life events, tone signals) from the surviving important mail on Starship GPUs.
- **Resolve** people/orgs against the existing **#373 Shared Entity Graph** (`shared.entities`) instead of inventing a second identity engine.
- **Synthesize** facts into per-contact profiles + a global "who is Kytran" profile on the Hub.
- **Embed** profile rows (`nomic-embed-text`, 768-dim) so the mail agent can semantically recall context.
- **Retrieve** that context via `get_contact_context()` BEFORE drafting, injected into the existing `_dispatch_to_bridge` system prompt → profile-aware, voice-matched replies.

Two accounts (verify ids against `google_accounts` at build time):
- `kytranempowerment@gmail.com` — `owner_id=2` (Kytran, business/empowerment voice)
- `terry.p.caetano@gmail.com` — `owner_id=4` (same human, personal voice / different context)

---

## 2. Privacy / Local-Sovereign Constraints (HARD)

These are non-negotiable and shaped the architecture more than anything else.

1. **Email content NEVER leaves the cluster.** All analysis runs on LOCAL fleet agents. No cloud escalation of email body/subject/sender. The global `platform_settings.escalation_mode='local_only'` already blocks cloud, but every Memory Vault dispatch **also asserts local-only** (`allow_cloud=False`) so a future flip of the global flag can't leak personal mail.
2. **Profile facts do NOT go through the agent-proposed KB quarantine.** `agent_kb_service.propose_agent_memory()` **hard-rejects** any content containing an email/phone (`_PII_PATTERNS` at `agent_kb_service.py:29`) and forces `knowledge_type='conversation_memory'`. Personal email facts are, by definition, full of emails/phones/names. They live in **dedicated owner-scoped tables in the `archie` DB** — never `knowledge_base`, never `source_type='agent_proposed'`, never visible to other agents.
3. **Strict owner-scoping.** Every fact/contact/profile row carries `owner_id` + `account_id`. Retrieval filters by owner. The two accounts are attributable separately even if they roll up to one human (see open question on merge policy).
4. **No bulk body storage.** We do NOT dump 10 years of raw bodies into Postgres (privacy + size liability). `google_email_cache` stays metadata-only; bodies are fetched on-demand via `gmail_service.get_email()` during extraction and discarded after the facts are extracted. The durable artifacts are *extractions + summaries*, not raw mail.
5. **Tokens already Fernet-encrypted** (`google_accounts`, via `google_api_service`). Accounts are `permission_level='draft_only'` → the agent can only **draft**, never auto-send. We keep that invariant.
6. **Right-to-forget path** (Phase 3): purging a contact deletes its `profile_facts` + `profile_contacts` rows and any embeddings. Since nothing was promoted to the shared KB, there is no cross-system fan-out to chase.

---

## 3. End-to-End Pipeline

```
                      ┌─────────────────────────────────────────────────────────┐
                      │  Gmail API (both accounts, full history)                 │
                      └───────────────┬─────────────────────────────────────────┘
                                      │ (IO only, no LLM)
  (1) INGEST CRAWLER  ───────────────▼────────────────────────────────────────────
      gmail_full_ingest_crawler:  messages().list(q='', pageToken loop) — ALL mail
        • upsert metadata → google_email_cache (reuse sync_inbox ON CONFLICT shape)
        • enqueue gmail_id → profile_ingest_ledger (state='fetched')
        • advance profile_account_cursor (page_token / historyId / internalDate HWM)
                                      │
  (2) TRIAGE          ───────────────▼────────────────────────────────────────────
      gmail_profile_triage_worker:
        GATE 1 (FREE):  Gmail labels in google_email_cache.labels jsonb →
                        CATEGORY_PROMOTIONS/SOCIAL/UPDATES/FORUMS/SPAM/TRASH = 'bulk'
        GATE 2 (heuristic): noreply@/List-Unsubscribe/Precedence:bulk = 'bulk';
                        known/replied senders + Kytran's SENT = 'important'
        GATE 3 (1.5B):  only the ambiguous middle → dispatch(capability='classify')
                        → Analytics (S.P.E.C.T.R.A./W.A.T.C.H.) on OUTPOST CPU
        → ledger.triage_verdict = important|bulk|skip
                                      │ (only 'important')
  (3) EXTRACT         ───────────────▼────────────────────────────────────────────
      gmail_profile_extract_worker:
        • thread+content_hash dedup (one extraction per thread, not per quoted copy)
        • get_email() body on-demand, truncate ~3000 chars
        • dispatch_json(capability='analyze') → Analytics (W.A.T.C.H.) on STARSHIP 7B
        • write structured facts → profile_facts  (state='extracted')
                                      │
  (4) RESOLVE ENTITIES ──────────────▼────────────────────────────────────────────
      entity resolver (personal overlay on #373):
        • normalize email (lower, strip +tags) → profile_contact_addresses
        • link to shared.entities (slug dedup) or create person entity there
        • backfill profile_facts.entity_id / profile_contacts.entity_id
                                      │
  (5) SYNTHESIZE      ───────────────▼────────────────────────────────────────────
      gmail_profile_synthesis_worker (daily, hub):
        • roll facts per contact → profile_contacts (relationship + comm-style fingerprint)
        • roll global → profile_owner ("who is Kytran", default voice)
        • dispatch(capability='research_synthesis') → R&D (D.A.R.W.I.N.) on HUB gemma3:12b
                                      │
  (6) EMBED           ───────────────▼────────────────────────────────────────────
      profile_embed_worker (reuse Consciousness embedding-loop pattern):
        • embedding_service.generate_embedding (nomic-embed-text, 768-dim)
        • embed profile_facts + profile_contacts + profile_owner summaries
                                      │
  (7) RETRIEVE        ───────────────▼────────────────────────────────────────────
      get_contact_context(owner_id, account_id, sender):  (read-only, no inference)
        • resolve sender → entity_id → profile_contacts row
        • top-k semantic profile_facts for that entity (vector recall)
        • profile_owner.default_voice
        → injected into _dispatch_to_bridge system_prompt before drafting
```

Every inference hop in (2),(3),(5) goes through `tools.department_hq.services.department_dispatcher.dispatch()/dispatch_json()` — inheriting K.I.N. welfare gating, Token Economy cost tracking, capability→department routing, and the local-only escalation lock. **Zero new dispatch code.** Steps (1),(4),(6),(7) are IO/DB only (no LLM), as is the embedding loop reuse.

---

## 4. DB Schema

### 4.1 Reused as-is (no schema change)
- **`google_email_cache`** — metadata cache. Reuse the existing `sync_inbox` `ON CONFLICT (account_id, gmail_id)` upsert. Already has `labels` jsonb (the free triage signal), `ai_*` columns, `filed_to_kb`, `received_at`. *Note: `received_at` is `TIMESTAMP` (no tz) — a known drift trap; the authoritative time key is Gmail `internalDate` (epoch-ms) stored in the ledger/cursor, per `timezone.md`.*
- **`google_accounts`** — `owner_id`, `permission_level`, encrypted tokens. Read-only here.
- **`shared.entities` / `shared.entity_mentions` / `shared.entity_relationships`** (#373, WTF db `030_shared_entity_graph.sql`) — canonical identity. `slug` = normalized-name dedup key. We REUSE this; `profile_*` tables carry a nullable `entity_id` FK. *Caveat: `shared.*` currently lives in the WTF/parliament DB, not the main `archie` DB — see Risks/Open Questions for the cross-DB reference decision.*

### 4.2 New owner-scoped tables (main `archie` DB)

```sql
-- (A) Resumable per-account cursor — high-water mark so restarts never re-list 50k ids
CREATE TABLE IF NOT EXISTS profile_account_cursor (
    account_id              INTEGER PRIMARY KEY REFERENCES google_accounts(id) ON DELETE CASCADE,
    phase                   VARCHAR(20) DEFAULT 'full_backfill',  -- full_backfill | incremental
    backfill_page_token     TEXT,                                 -- resume mid-page
    oldest_internaldate_done BIGINT,                              -- epoch-ms backfill HWM
    newest_internaldate_seen BIGINT,
    last_history_id         TEXT,                                 -- Gmail historyId for incremental
    total_enqueued          INTEGER DEFAULT 0,
    total_done              INTEGER DEFAULT 0,
    full_backfill_complete  BOOLEAN DEFAULT FALSE,
    last_full_scan_at       TIMESTAMPTZ,
    last_incremental_at     TIMESTAMPTZ,
    updated_at              TIMESTAMPTZ DEFAULT NOW()
);

-- (B) Idempotent processed-ledger + dedup — ONE row per message; the state machine
CREATE TABLE IF NOT EXISTS profile_ingest_ledger (
    id              BIGSERIAL PRIMARY KEY,
    account_id      INTEGER NOT NULL REFERENCES google_accounts(id) ON DELETE CASCADE,
    gmail_id        VARCHAR(100) NOT NULL,
    thread_id       VARCHAR(100),
    internal_date   BIGINT,                          -- epoch-ms (authoritative time)
    content_hash    VARCHAR(64),                     -- sha256(normalized subject+from+body-prefix, quoted text stripped)
    gmail_labels    JSONB DEFAULT '[]',
    triage_verdict  VARCHAR(20),                     -- important | bulk | skip
    triage_source   VARCHAR(20),                     -- gmail_label | heuristic | model
    triage_score    REAL,
    state           VARCHAR(20) DEFAULT 'fetched',   -- fetched|triaged_skip|triaged_keep|extracting|extracted|failed
    attempts        INTEGER DEFAULT 0,
    last_error      TEXT,
    claimed_at      TIMESTAMPTZ,
    triaged_at      TIMESTAMPTZ,
    extracted_at    TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (account_id, gmail_id)
);
CREATE INDEX IF NOT EXISTS idx_pil_claim ON profile_ingest_ledger(account_id, state)
    WHERE state IN ('fetched','triaged_keep','extracting');
CREATE INDEX IF NOT EXISTS idx_pil_chash ON profile_ingest_ledger(account_id, content_hash);

-- (C) Atomic extracted facts — append-only, evidence-linked, embedded, regenerable
CREATE TABLE IF NOT EXISTS profile_facts (
    id              BIGSERIAL PRIMARY KEY,
    owner_id        INTEGER NOT NULL,
    account_id      INTEGER NOT NULL REFERENCES google_accounts(id) ON DELETE CASCADE,
    source_gmail_id VARCHAR(100),
    source_thread_id VARCHAR(100),
    entity_id       INTEGER,                         -- nullable FK → shared.entities (filled at resolve)
    fact_type       VARCHAR(24) NOT NULL,            -- relationship|org|commitment|life_event|preference|project|style_cue|biographical|situation
    fact_text       TEXT NOT NULL,
    structured      JSONB,
    confidence      REAL,
    importance_score REAL DEFAULT 0.5,
    occurred_at     TIMESTAMPTZ,
    embedding       VECTOR(768),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pf_owner_type ON profile_facts(owner_id, fact_type);
CREATE INDEX IF NOT EXISTS idx_pf_entity ON profile_facts(entity_id);

-- (D) Address-book bridge — many email aliases → one entity (where identity resolution attaches)
CREATE TABLE IF NOT EXISTS profile_contact_addresses (
    id            BIGSERIAL PRIMARY KEY,
    owner_id      INTEGER NOT NULL,
    entity_id     INTEGER,                           -- nullable FK → shared.entities
    email_address VARCHAR(255) NOT NULL,             -- normalized lower, +tags stripped
    display_name  VARCHAR(255),
    first_seen    TIMESTAMPTZ,
    last_seen     TIMESTAMPTZ,
    msg_count     INTEGER DEFAULT 0,
    UNIQUE (owner_id, email_address)
);

-- (E) Per-person rollup — the answer to "who is this + how does Kytran talk to them"
CREATE TABLE IF NOT EXISTS profile_contacts (
    id                   BIGSERIAL PRIMARY KEY,
    owner_id             INTEGER NOT NULL,
    entity_id            INTEGER,                     -- nullable FK → shared.entities
    canonical_email      VARCHAR(255),
    canonical_name       VARCHAR(255),
    relationship_label   VARCHAR(80),                 -- e.g. business_partner | family | vendor | recruiter
    relationship_summary TEXT,
    communication_style  JSONB,                        -- {formality, greeting, signoff, avg_length, emoji_use, response_latency_norm}
    open_commitments     JSONB,
    recurring_topics     JSONB,
    first_seen           TIMESTAMPTZ,
    last_interaction_at  TIMESTAMPTZ,
    message_count        INTEGER DEFAULT 0,
    importance_rank      INTEGER,
    summary_embedding    VECTOR(768),
    refreshed_at         TIMESTAMPTZ,
    UNIQUE (owner_id, canonical_email)
);

-- (F) Global synthesis — "who is Kytran" for holistic drafting context
CREATE TABLE IF NOT EXISTS profile_owner (
    id                BIGSERIAL PRIMARY KEY,
    owner_id          INTEGER NOT NULL,
    section           VARCHAR(40) NOT NULL,           -- bio|relationships|situations_timeline|recurring_orgs|comm_style_overall|default_voice
    content_md        TEXT,
    structured        JSONB,                          -- e.g. default_voice {tone, common_phrasings, signoffs}
    source_fact_count INTEGER,
    content_embedding VECTOR(768),
    generated_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (owner_id, section)
);
```

Migration is idempotent (`CREATE TABLE IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS`), follows `database.py` conventions, all timestamps `TIMESTAMPTZ` per `timezone.md`.

---

## 5. Scheduled Jobs & Fleet Workers

All are **module-specific scheduled jobs** (the domain-specific backlog drain mandated by `module-work-pattern.md` — same pattern as Consciousness loops), registered in `ai_bridge/agent_loop.py` with `max_instances=1, coalesce=True` (the `delegate_task_worker` guardrails) and `CronTrigger(..., timezone='America/Toronto')`. A one-shot operator kickoff/re-run is filed via `mcp delegate_task(capability='analyze', reason='re-run gmail profile backfill for account N')` (satisfies the cross-module entry-point clause). Inference dispatch is `dispatch()/dispatch_json()` — never sync on the web thread; long calls use the dispatcher's async+poll path.

| Job | Cadence | Tier / dispatch | Capability → Dept/Agent | Does |
|-----|---------|------|------|------|
| `gmail_full_ingest_crawler` | every 6h, off-peak, while backfilling then idle | **no LLM** (Gmail API/IO only) | — | Paginate ALL mail (`messages().list` `q=''`, `nextPageToken`, ~500/page, page-budgeted). Upsert metadata → `google_email_cache`. `INSERT … ON CONFLICT DO NOTHING` ledger rows `state='fetched'`. Advance cursor. After drain → `phase='incremental'` using `users().history().list(startHistoryId=last_history_id)`. |
| `gmail_profile_triage_worker` | every 5 min during run | GATE 1/2 **no LLM**; GATE 3 **OUTPOST CPU** | `classify` → Analytics (**S.P.E.C.T.R.A./W.A.T.C.H.**), `preferred_node=['outpost-*']`, model `qwen2.5:1.5b`/`llama3.2:3b` | Claim N `state='fetched'` rows (`FOR UPDATE SKIP LOCKED`). Free label gate, then heuristic gate, then 1.5B for ambiguous only. Set `triage_verdict`. Per-cycle cap; K.I.N. welfare-gated. **Never calls 7B.** |
| `gmail_profile_extract_worker` | every 5 min during run, batch ≤10 | **STARSHIP GPU** | `analyze` → Analytics (**W.A.T.C.H.**), `preferred_node=['Starship-246','Starship-245']`, `qwen2.5:7b`, `allow_cloud=False` | Claim `triage_verdict='important' AND state='triaged_keep'`. content_hash dedup (one per thread). `get_email()` body on-demand, `dispatch_json('analyze', body[:3000])` with extraction schema → `profile_facts`. Retry w/ capped `attempts` → `failed`. Backpressure: skip cycle if fleet busy / K.I.N. flags stress. Night-window preferred (8PM–6AM ET hardware rest). |
| `gmail_profile_synthesis_worker` | daily 02:30 ET | **HUB** | `research_synthesis` → R&D (**D.A.R.W.I.N.**), `gemma3:12b` on hub | For contacts with new facts since `refreshed_at`: roll `profile_facts` → `profile_contacts` (relationship summary + comm-style fingerprint). Periodically rebuild `profile_owner`. Heavy context → hub only. Resolve entity ids. |
| `profile_embed_worker` | every 30 min | **OUTPOST CPU** (reuse embedding loop) | `embedding_service.generate_embedding` (`nomic-embed-text`, 768-dim) | Embed new `profile_facts` / `profile_contacts` / `profile_owner` summaries so retrieval stays warm. |
| `gmail_profile_progress_observer` | every 30 min | **no LLM** | — | Snapshot ledger state counts per account, est. completion, cost-to-date from `task_execution_log`, failure rate → status row + Token Economy + a Memory Vault panel in Google Work Suite / DHQ. Alert via `telegram_service` on failure spike or quota exhaustion. |

**Connection-leak discipline (DR lesson, `fleet.md`):** every raw cursor in a worker uses `with get_db_cursor()` or `try/finally: rollback+close` — a bare `except: log` leaks the conn → pool exhaustion.

---

## 6. Triage Strategy (the cost firewall)

The whole design hinges on never running a 7B model on bulk mail. Three escalating gates; the expensive one only sees the ambiguous remainder.

- **GATE 1 — FREE (zero inference).** The Gmail labels are already in `google_email_cache.labels` jsonb after the crawler. If labels intersect `{CATEGORY_PROMOTIONS, CATEGORY_SOCIAL, CATEGORY_UPDATES, CATEGORY_FORUMS, SPAM, TRASH}` → `triage_verdict='bulk'`, no model. This removes the bulk of a decade's mailbox at $0. Up-weight `IMPORTANT`, `STARRED`, and **`SENT`** (Kytran's own outbound = the gold source for voice).
- **GATE 2 — heuristic (zero inference).** Header signals: `List-Unsubscribe` / `Precedence: bulk` / `noreply@|no-reply@|notifications@` senders → `bulk`. Senders Kytran has replied to ≥1×, threads he sent into, or domains already in `profile_contact_addresses` → `important`.
- **GATE 3 — cheap model (only the middle).** One `dispatch(capability='classify')` to an **outpost CPU** (`qwen2.5:1.5b`) returning `{important: bool, reason}`. Reuses the `analyze_email` prompt shape.

Only `important` graduates to Starship 7B extraction. **Thread + content_hash dedup runs before any gate** so a 200-message thread is extracted once and quoted/forwarded copies collapse. Net effect: tens of thousands of messages → a few thousand 7B passes, cost ≈ linear in number of real human relationships, not raw message count. GATE-1 defaults conservative; the GATE-3 threshold and per-night extraction cap are tunable from a settings row.

---

## 7. Personal-Profile Model & Retrieval Surface

### 7.1 Layered model
1. **`profile_facts`** — atomic, evidence-linked observations (`source_gmail_id` traces every claim back to a real message, so synthesis is auditable and re-derivable). Embedded for semantic recall.
2. **`profile_contacts`** — per-person rollup: relationship label + summary, and crucially a **communication-style fingerprint** (`{formality, greeting, signoff, avg_length, emoji_use, response_latency_norm}`) describing how Kytran modulates tone *for this specific person*; plus open commitments and recurring topics.
3. **`profile_owner`** — global synthesis: bio, relationship map, life-situation timeline, recurring orgs, and `default_voice` (tone / common phrasings / sign-offs).

### 7.2 Identity resolution — reuse #373, don't reinvent
People/orgs resolve against `shared.entities` (the #373 slug/dedup convention) via `profile_contact_addresses` (email-alias → `entity_id`). A correspondent already in the civic graph (e.g. an MP) links to the SAME entity so personal and civic knowledge converge on one identity. Contacts not in the graph get a new `person` entity created in the same store. Until/unless the cross-DB reference (Risk R8) is settled, `entity_id` columns stay **nullable** and the resolver falls back to normalized-email + display-name clustering within owner scope; a one-shot backfill links `entity_id` once the reference path is chosen. **No competing resolver is built.**

### 7.3 Retrieval surface (the payoff)
`get_contact_context(owner_id, account_id, sender)` — **read-only, no inference**, called by the mail agent BEFORE drafting (extends the existing `gmail_service._dispatch_to_bridge` / `_execute_email_action` path). Returns:
- the `profile_contacts` row (relationship_summary, communication_style, open_commitments, recurring_topics, importance_rank, entity_id),
- top-k semantically relevant `profile_facts` for that entity scoped to the current subject/thread (vector recall via `summary_embedding`/`embedding`),
- `profile_owner.default_voice`.

This bundle is injected into the drafting `dispatch_json` **system prompt** (same call `_dispatch_to_bridge` already makes — no new dispatch path), so the local model writes AS Kytran: matched greeting/sign-off/tone, aware of shared history and any unmet commitments, grounded in real prior facts. Drafts still honor `permission_level='draft_only'` (`create_draft`, never auto-send). All local + owner-scoped; the personal context never leaves the cluster.

---

## 8. Phased Delivery Plan

- **Phase 1 — Ingest + Triage + Cache (the resumable backfill).** Schema migration (cursor + ledger + the cache stays as-is). Add `gmail_service.list_all_message_ids()` (full-mailbox paginator — the one real gap; `sync_inbox` is hardcoded `labelIds=['INBOX'], maxResults=50`). Wire `gmail_full_ingest_crawler` + `gmail_profile_triage_worker` (3 gates) + the progress observer. Run against account 2 first, then account 4. **Exit:** both mailboxes fully enumerated with accurate counts; ledger split important/bulk/skip; cost report proving bulk never hit a 7B model.
- **Phase 2 — Extract + Entity + Profile.** `gmail_profile_extract_worker` (Starship 7B, `profile_facts`, content_hash dedup, retries). Entity resolver + `profile_contact_addresses` bridge aligned to #373. `gmail_profile_synthesis_worker` (hub gemma3:12b) building `profile_contacts` + `profile_owner`. `profile_embed_worker` online. **Exit:** queryable per-contact + owner profiles with evidence-linked facts; survives multi-night drain + restart.
- **Phase 3 — Retrieval + Profile-Aware Drafting.** `get_contact_context()` API; wire it into the R.E.S.O.L.V.E./A.R.C.H.I.E. pre-draft enrichment in `_dispatch_to_bridge`. Incremental steady-state (`historyId`). Right-to-forget purge path. Memory Vault progress panel + Telegram alerts. **Exit:** mail agent drafts in Kytran's voice for a given relationship, verified against held-out SENT mail.

---

## 9. Risks & Mitigations

- **R1 — Gmail API quota.** ~250 quota-units/user/sec; `messages.get` ~5 units each; tens of thousands of gets can 429 or hit daily caps. → page-budgeted crawler, exponential backoff on `rateLimitExceeded`, `format='metadata'` for triage and `format='full'` only for `important`, multi-night draining.
- **R2 — OAuth token expiry/revoke mid-multi-day run.** → cursor persists and resumes after re-auth; observer alerts on auth failure.
- **R3 — Triage too permissive** (e.g. letting `CATEGORY_UPDATES` through to 7B) blows up cost. → conservative GATE-1 defaults, tunable GATE-3 threshold + hard per-night token budget that pauses extraction.
- **R4 — PII/quarantine collision.** Accidentally calling `agent_kb_service.propose_agent_memory()` silently drops the content (PII reject) or worse leaks it into shared KB. → profile facts ONLY go to `profile_*` tables; never `store_memory`/`source_type='agent_proposed'`.
- **R5 — Cloud leak of email body.** → assert `allow_cloud=False` on every Memory Vault dispatch; rely on `escalation_mode='local_only'`; never include raw body in any external call.
- **R6 — Naive timestamps** (`google_email_cache.received_at` is `TIMESTAMP` not `TIMESTAMPTZ`). → authoritative time key is `internalDate` epoch-ms in cursor/ledger; new tables `TIMESTAMPTZ`.
- **R7 — Synthesis hallucination / style flattening** on decade-old context-poor mail. → confidence scores, evidence-linked `source_gmail_id` on every fact, weight recent mail higher (style drifts over 10 years), low-confidence facts excluded from drafting.
- **R8 — `shared.*` lives in the WTF/parliament DB, #373 still in planning.** Building entity FKs against a moving / cross-DB target. → `entity_id` nullable + email/name fallback now; defer the cross-DB reference decision (FK vs replicated lookup vs deferred backfill) to an explicit owner decision; no blocking dependency.
- **R9 — Identity false merges** (role addresses `info@`, shared family domains). → reuse #373 dedup confidence guardrails; low-confidence → 'unresolved' bucket, never forced merge.
- **R10 — Fleet starvation** from a multi-day backlog. → K.I.N. welfare gate + small batch caps + night-window + `coalesce=True` so the run yields to interactive/daytime load.

---

## 10. Open Scoping Decisions (owner only)

1. **Account merge policy:** do `owner_id=2` (kytranempowerment) and `owner_id=4` (terry.p.caetano) roll up to ONE unified profile (with account context tags) or stay two separate personas? Same human, likely distinct voices/relationship sets. Also confirm terry.p.caetano is Kytran's own account, not someone else's mailbox he manages.
2. **History scope:** full 10 years of both accounts, or a cap (last 5 years / since a date)? Sets cost + run duration. (Recommended default: enqueue all, label-gate-skip bulk, extract important.)
3. **Sent-mail priority:** SENT/Drafts are the richest source of Kytran's actual voice — confirm we ingest them (read scope must cover all mail, not just INBOX) and extract them at a higher-priority tier than received mail.
4. **Privacy floor:** any categories excluded from extraction entirely (medical, legal, financial, intimate/family threads) even when "important"? Only Kytran can set the no-extract boundary.
5. **#373 entity store write policy:** may personal contacts CREATE new `person` rows in the shared `shared.entities` store (mixing private acquaintances into civic tooling), or stay in a private partition that references #373 read-only? Plus the cross-DB reference path (R8).
6. **Triage aggressiveness:** high recall (richer profile, more 7B cost) vs high precision (cheaper, may miss quiet-but-important contacts)? The main cost dial.
7. **Attachment depth:** extract from PDFs/docs too (OCR + cost), or body-only for Phase 1/2?
8. **Run budget & retention:** hard per-night/overall token ceiling at which the pipeline pauses for review? Keep full ledger+facts indefinitely or age out facts older than N years from active retrieval?
9. **Draft-only invariant:** confirm the enriched agent always `create_draft` and never auto-sends for owner accounts (current `permission_level='draft_only'`).

---

*Grounding verified against: `gmail_service.py` (primitives + `_dispatch_to_bridge` using `dispatch_json`), `database/migrations/160_google_work_suite.sql` (cache/accounts schema, `received_at TIMESTAMP`), `175_gmail_ai_analysis.sql` (`ai_analyzed_at`/`filed_to_kb`), `agent_kb_service.py` (PII hard-reject + forced quarantine), `what-the-fact/migrations/030_shared_entity_graph.sql` (`shared.entities` slug dedup), `department_dispatcher.py` (`dispatch`/`dispatch_json` signatures).*

---

## 11. Owner Decisions — LOCKED 2026-06-09 (scoping round 1)

1. **Accounts → ONE unified "Kytran" profile, account-context-tagged.** Both are him:
   - `terry.p.caetano@gmail.com` = **personal** → primary source of relationships, family, life events, authentic voice.
   - `kytranempowerment@gmail.com` = **business + Google-SSO hub** (LinkedIn, Facebook, social-media logins) → expect heavy machine noise (SSO/login confirmations, social notifications). Facts tagged with account-context (`personal` | `business`).
   - **Triage refinement (feeds [P1] triage task #3850):** GATE 2 header heuristics MUST add SSO/social sender filters for the business account — `noreply@` / `notifications@` / `no-reply@` + `linkedin.com` / `facebook.com` / `accounts.google.com` / `twitter.com` / `instagram.com` domains → route to `skip`/`bulk`, never extract. This account is where the bulk-skip ratio pays off most.
2. **History scope: full 10 years, both accounts.** Enqueue-all, label-gate-skip bulk.
3. **SENT = gold voice source.** Extract SENT/Drafts at higher priority than received (read scope must cover all mail, not just INBOX). The per-contact communication-style fingerprint is built primarily from SENT.
4. **Privacy floor: STILL OPEN — must be set before Phase 2.** Not needed for Phase 1 (metadata + triage only, no content extraction). Before the [P2] extract worker runs, Kytran sets which categories (medical / legal / financial / intimate-family), if any, are excluded from deep extraction even when triaged important. Right-to-forget purge ([P3]) exists regardless.
5. **#373 entity store: private partition, read-only reference** (Claude default, owner not yet overridden). Personal contacts do NOT write into the shared civic `shared.entities` graph — they live in a private partition that references #373 read-only. Revisit if unification is wanted.
6. **Triage aggressiveness: HIGH RECALL.** Richer profile, accept higher 7B cost for the one-time backfill; catch quiet-but-important contacts. GATE-3 threshold tunable ([P2] task #3858).
7. Attachment depth (#7), run budget (#8), draft-only invariant (#9): defaults stand (body-only P1/P2; tunable per-night token budget; `draft_only` never auto-sends). Confirm later.

**Dev HQ:** Project #377, tasks #3847–#3864 (P1 #3847–3852 / P2 #3853–3858 / P3 #3859–3864).

---

## 12. Phase 4 — SaaS Billing, Tiers & Cloud Opt-in (design 2026-06-09)

The Memory Vault becomes a multi-tenant, tiered SaaS. Build against the **Watch Series
billing pattern** (`billing.md`, `services/watch_billing_handler.py`, `bundle_checkout_service.py`,
`billing_product_plans`). **Billing touches real money + the canonical KBS Stripe account — build
carefully, in stages, never rushed.**

### Tier model (owner-decided 2026-06-09)
| Tier | Price | What it unlocks |
|------|-------|-----------------|
| **Free** | $0 | Inbox access only — NO AI, NO ingestion |
| **Local** | premium ($$$, "our unique one") | Private on-cluster AI + full Memory Vault ingestion/profile. The differentiator. |
| **Cloud** | cheaper ($$) | Claude / ChatGPT processing — explicit opt-in + per-provider consent ("content sent to <provider>") |

Deliberate inversion: **local sovereignty is the premium**; cloud is the cheaper commodity.

### Privacy posture (owner-decided)
Local is default + the brand. Cloud is allowed **only** with: (a) an active Cloud-tier subscription,
AND (b) a recorded one-time consent that email content will be sent to Anthropic/OpenAI. Never a
silent toggle. The owner's OWN vault stays Local regardless.

### Build (each a task under #377)
1. **Stripe prices + `billing_product_plans` rows** for `email_ai` product (local / cloud tiers).
   ⚠️ PREREQ — prices must be minted in the **KBS Stripe account** (canonical, `KBS_STRIPE_SECRET_KEY`);
   owner action via KBS / Stripe dashboard. No unilateral product creation.
2. **Entitlement resolver** — `get_email_ai_tier(user)` via `subscription_service.get_user_entitlements` /
   `resolve_tier_for_product('email_ai', price_id)`.
3. **Paywall + upsell modal** in Google Work Suite (Watch Series pattern) — free users see email only;
   AI/vault features show an upsell → checkout (`stripe_service.create_checkout` / bundle pattern).
4. **AI provider selector → functional** — persist per-user provider pref; gate Local/Cloud by
   entitlement; record cloud consent (consent table or per-user platform_settings + timestamp).
5. **Per-owner vault gating** — crawler/triage/extract run ONLY for Local/Cloud-entitled owners
   (today they run for all `google_accounts`). Free = no ingestion.
6. **Cloud routing** — extract/analyze read each owner's provider pref + tier; drop `local_only`
   (route to cloud via `external_providers`) only for consented Cloud-tier owners; else stay local.
7. **Webhook handler** — `email_ai` subscription events → entitlement (mirror `watch_billing_handler`;
   idempotent via `billing_events`; register one handler per event prefix).
8. **Account Center** — surface + manage the email-AI subscription in the Subscriptions tab.

### Multi-tenant note
The data model is already owner-scoped (SaaS-ready). The per-tenant compute-budget + fairness work
(extraction is local-GPU-bound) is required before scaling to many paying tenants — small custom
co-fit models (Agent Academy) are the throughput unlock.
