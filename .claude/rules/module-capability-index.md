---
globs: ["platform_v2/tools/**", "platform_v2/module_registry.py"]
---

# Master Module Capability Index

Auto-built 2026-04-17 from `module_registry.py` (36 modules) + detailed audits in KB.

This is an **index** — for deep capability detail, see the linked KB vault_note per module.
KB search: `search_knowledge(category="module_capability")` returns all audits.

## Legend
- **Status**: ✅ enabled · 🅱 beta · ⏳ coming_soon · ⛔ disabled
- **Maturity** (where audited): 🟢 Mature · 🟡 Partial · 🔴 Stub
- **Audit**: detailed audit KB id (if done) or "pending"

---

## admin_operations (5)

### Backup Manager — `backup_manager` · `/tools/backup-manager` · ✅ · 🟢
- **Capability**: DB dumps + file snapshots + config exports, restore w/ component granularity, checksum verify, retention policies, external USB sync, pre/post hooks, webhook triggers. 4,845 LOC + gdrive crypto module.
- **Tables**: `backups`, `backup_locks`, `webhook_subscriptions`. All 19 routes `@admin_required`.
- **Gaps**: GDrive upload/sync UI unexposed; 2h lock hardcoded; no incremental backups.
- **Audit**: KB 256846 (#1946, 2026-04-17) · **Rules**: `admin-ops.md`
- **Active**: Project #270 (Backup Redesign — 4-tier defense, 6/8 tasks)

### Security & Network — `security_network` · `/tools/security-network` · ✅ · 🟢
- **Capability**: SSL/TLS cert watch, Hostinger DNS CRUD, NPM proxy host lifecycle, 5 compliance rule packs (Ubuntu STIG/Docker STIG/HIPAA/Network STIG/CIS Ubuntu), device discovery (AdGuard+ARP 5min), Home Assistant cameras, recon scans, 23 agent loop jobs.
- **Distinguishing**: JSON rule pack abstraction, host_command queue bridge, full DNS audit trail.
- **Gaps**: no SSL auto-renewal, camera scheduling suggest-only, single-tenant.
- **Audit**: KB 256841 (2026-04-17) · **Rules**: `admin-ops.md`, `compliance-standards.md`

### Account Center — `account_center` · `/tools/account-center` · ✅ · 🟡
- **Capability**: user CRUD, subscription tiers, login lockout (5 attempts→15min), IP rate limit (10/5min), password complexity, TOTP 2FA, auth event log. **Access control API** (Phase 0, PR #397): `POST /api/access/grant|revoke`, `GET /api/access/check|list` — timing-safe, HMAC token. **Internal notify endpoint** (Phase 4, PR #400): `POST /api/internal/notify` — validates `X-Internal-Key` header, forwards message to Telegram via `send_info` in daemon thread. Used by KBS and standalone products to fire Telegram alerts without direct bot access.
- **Key security**: `auth_service.py` — **23 functions** (not 12 — rules drift); `auth_events` table
- **Rules**: `admin-ops.md`, `app-core.md`
- **Audits**: Cross-cutting OAuth/SSO audit → KB 256845 (#1948, 2026-04-17)
- **Critical security gaps** (new tasks #2060–2065):
  - #2060 No PKCE in authorization_code flow
  - #2061 HS256 with static SECRET_KEY + hardcoded "fallback-secret" fallback
  - #2062 CSRF protection unverified on login/signup/authorize forms
  - #2063 No 2FA backup codes + no password reset flow
  - #2064 kytran_auth.py SDK duplicated across 6 products — consolidate
  - #2065 civic-watch + legal-watch missing from migration 305 client seeds

### System Operations — `system_operations` · `/tools/system-operations` · ⛔
- **Status**: Disabled in registry — replaced by Kytran System Operations (`kytran_system_ops` at `/external/kso`)
- **Note**: Standalone product at port 8085, server.kytranempowerment.com

### SaaS Manager — `saas_manager` · `/tools/saas-manager` · ✅ · 🟡
- **Capability**: Organization (tenant) CRUD, per-org module enable/disable, custom domain verify (DNS TXT), port accessibility check, public IP detection, node assignment. 761 LOC routes + domain_service + ip_monitor.
- **Tables**: `organizations`, `org_users`, `org_modules`, `org_domains`, `org_nodes`
- **Gaps**: **No subscription_level binding on org_modules — blocks #2018 KBS plugin tier gating**. DNS update not exposed. Node assignment UI minimal.
- **Audit**: KB 256846 · **Rules**: `admin-ops.md`
- **Active**: #2018 subscription gating (P10 large)

---

## ai_command (7)

### Department HQ — `department_hq` · `/tools/department-hq` · ✅ · 🟡
- **Capability**: 12 tabs — Overview, Org Chart, Roster, Work Tracking, Performance, C.R.E.E.D., **S.I.G.N.A.L. Command** (Social), Devices (Identity/Portraits), Dispatch, **Fleet**, Contractors, COMs. Owns dispatcher (`services/department_dispatcher.py` — renamed from bridge_dispatcher per Decision #441), orchestration engine (8-step pipeline), smart_router (11-tier GPU-aware escalation), job_registry (118 jobs across 13 depts). Fleet tab merged Starbase Command + Starship + A.R.M.A.D.A. on 2026-04-08.
- **S.I.G.N.A.L. Command tab** (2026-04-29, updated 2026-05-01): Full LinkedIn management hub for Kytran's brands. Account switcher (👤 Kytran Katarn / 🏢 KE Inc. / 🔒 Creed-AI). **Per-account Run Now** (5-min cooldown per account, independent). All sub-tabs filter by selected account. 7 sub-tabs: Overview (agent status + Run Now + content calendar), Compose, Post Log, Pending (filters by account), Hashtags, Calendar, Themes. **FULLY LIVE 2026-05-01**: EN + ⚜️ FR posts auto-draft → Telegram approval with 4 buttons → LinkedIn post. Personal: `linkedin_post` skill. Company: `linkedin_company_post` skill, `LINKEDIN_COMPANY_SLUG=106863155`. `social_routes.py` endpoints: GET /api/signal/overview, /api/signal/post-log?account=, /api/signal/hashtag-stats, /api/signal/pending-approvals?account=, /api/signal/calendar, /api/signal/themes; POST /api/signal/compose, /api/signal/run-now {account: personal|company|all}. Model-affinity dispatch queue (`dispatch_pending_queue`) handles cold-model deferral with `callback_type=signal_pipeline`. `_free_comfyui_vram_if_idle()` in `model_dispatch_service.py` releases GPU when Pixel idle. KB: 261583–261586, 261688–261690, 261693. **Known gap**: approval queue DB connection times out after 120s browser skill → status stays 'approved' (task #2526).
- **Distinctive**: Welfare-gating + replacement hunt (unique vs commodity LLM dispatch). **Delegation surface (2026-04-21, Project #276):** external callers hand work via `mcp__archie__delegate_task(capability, reason, ...)` → persists to `unified_tasks` with `delegation_source` → `delegate_task_worker` (30s, max_instances=1) claims ≤3/cycle → routes to known-tool shortcut or dispatcher. **Skill-first routing (2026-04-21, ADR-002, #2217):** coordinator now calls `find_cross_department_agent()` when the home dept has no agent with the capability in their skills. New MCP tools: `propose_hire` (#2124), `delegate_task` (#2207).
- **Rules**: `department-hq-dispatch.md`, `starbase.md`
- **Audits**: 3 separate notes
  - Security angle → KB 256837 (#1025, 2026-04-17) — ✅ migration debt, no blockers
  - Core tabs (10 non-fleet/dispatch) → KB 256843 (#1942 part 1, 2026-04-17) — 🟢 Mature
  - Dispatch/Fleet/Jobs → KB 256844 (#1942 part 2, 2026-04-17) — 🟡 Partial (legacy imports, stub installers)
  - Delegation + skill-first routing → KB 258687/258688/258693 (2026-04-21) — 🟢 Live, verified end-to-end
- **Gaps**: 3 sibling tables not yet agent_service-owned (agent_skills/budgets/creation_events — #2057); 18 legacy ai_bridge.* imports remain (#2058); 5 dispatch_routes stubs (Project #243); MissionManager coupling; CAPABILITY_TAXONOMY hardcoded in smart_router; `bridge_jobs` may not persist LLM responses for dispatcher path (unverified — noted in #276 handoff).

### Consciousness — `consciousness` · `/tools/consciousness` · ✅ · 🟢
- **Capability**: 5 tabs + Dev HQ subtabs + Code Health. Owns `knowledge_base` (25,874 entries, 99.1% embedded). Embedding/Analysis/Translate/GitHub-ingest loops. 129 routes, 314+ endpoints, 62+ async jobs.
- **Integrations**: MCP `store_memory`/`search_knowledge`/`recall_context`/`create_task`/`log_decision`; Repair Bay Code Health (one-way).
- **Audit**: KB 256840 (2026-04-17) · **Rules**: `consciousness.md`, `project-knowledge.md`

### A.R.C.H.I.E. Chat — `archie_chat` · `/tools/archie-chat` · ✅ · 🟡
- **Capability**: Text messaging (Claude-routed or Telegram-bridged), conversation CRUD, agent roster, bridge stations, API key mgmt, Home Assistant voice synth w/ ARCHIE emotional tone. ~1,640 LOC across routes + chat_service + ha_bridge + auth_middleware.
- **Tables**: conversations, messages (source=ha_voice/telegram/web), api_keys, agent_assignments
- **Gaps**: Telegram via external `archie_comms` container (:3002); **STT (voice input) missing**; team convo scoping partial; API key scopes not enforced per endpoint.
- **Audit**: KB 256846 · **Rules**: `autonomy.md`

### Repair Bay — `repair_bay` · `/tools/repair-bay` · ✅ · 🟡
- **Capability**: Scan→Proposal→Sandbox→Deploy (manual) self-healing pipeline. 8 tabs: Reviews, PR Review, Repairs, Diagnose, Test Bay, **Ship**, QA, Pushes + ENGINEERING station. 10 route files, ~2,849 LOC. Critical/high=immediate proposal; medium=Sunday 02:00 batch. SandboxManager (Docker or schema-separation).
- **Ship tab** (2026-04-30): Website sub-tab added alongside Ready/History/F.O.R.G.E. sub-tabs. `GET /api/deploy/website-status` returns last deploy time, status, pending portrait count per domain. `POST /api/deploy/website-trigger` triggers immediate full-site Hostinger deploy in background thread. Results stored in `system_config` keys `website_deploy_last_run_<domain>` + `website_deploy_last_status_<domain>`.
- **Audit**: KB 256838 (2026-04-17) · **Rules**: `repair-bay.md`
- **Gaps**: `_has_open_proposal()` dedup not visible; 6h scheduler wiring unclear; one-way Consciousness flow.
- **Hostinger deploy — CRITICAL (fixed 2026-05-01, PR #447–448)**: `POST /api/hosting/v1/websites/{username}/deploy` → 404 (endpoint does not exist). `deploy_service.py` now marks `deploy_pending` in system_config instead. **Only working deploy path: `/deploy-website` skill** using `mcp__hostinger-api__hosting_deployStaticWebsite`. Never try raw HTTP to Hostinger deploy API. KB #261679 #261681.
- **Portrait :rw mounts (PR #448)**: `docker-compose.yml` now has `:rw` for `kytranempowerment.com/assets/portraits` and `creed-ai.org/assets/portraits`. Required `docker compose up -d` (not restart) to apply.

### Agent Academy — `agent_academy` · `/tools/agent-academy` · ✅ · 🟡 (3/5)
- **Capability**: 5 tabs — Benchmarks, Training, A/B Testing, Skills, Reports. Lv1–5 proficiency (Lv4 unlocks cloud). 16 routes. `agent_benchmark_results`, `agent_competency_scores`, `agent_learning_records`, `v_department_readiness`.
- **Audit**: KB 256839 (2026-04-17)
- **Gaps**: A/B variant tracking implicit only; Reports endpoints missing; training automation disabled; Lv4 cloud-unlock not C.R.E.E.D. gated; CAPABILITY_TAXONOMY hardcoded in smart_router

### Automations — `automations` · `/tools/automations` · ⛔
- **Status**: Disabled. Scope unclear.

---

## saas_services (8)

### Email Manager — `email_manager` · `/tools/email-manager` · ✅ · 🟢
- **Capability**: 5-tab oversight dashboard — Overview (unread stats + 30s live feed), Inbox (per-mailbox IMAP browser + **✉ Compose button**), Sent, Agents (Stalwart provisioning), Settings (connection test). 48 mailboxes live: 38 AI agents + 10 business. IMAP sync job every 5 min.
- **Backend**: `stalwart_service.py` (provision/delete/rotate), `sync_jobs.py` (IMAP sync 5 min), `mailbox_routes.py`, `overview_routes.py`, `inbox_routes.py`, `sent_routes.py`, **`compose_routes.py`** (Phase 3 send).
- **Tables**: `email_mailboxes` (address, mailbox_type, owner_agent_id, provisioned, imap_password), `email_activity_log` (direction, from/to/subject/message_id, read_at).
- **Compose/Send**: `POST /api/email/compose/send` `{from_address, to_address, subject, body}` — sends via Stalwart :587 STARTTLS → outpost Postfix relay → internet. `GET /api/email/compose/mailboxes` — provisioned From addresses.
- **Key endpoints**: `POST /api/email/mailboxes/<id>/provision`, `POST /api/email/mailboxes/provision-all-agents`, `POST /api/email/mailboxes/rotate-all-passwords`.
- **Stalwart PATCH gotcha**: body must be bare array `[{"action":"set","field":"secrets","value":[pw]}]` — NOT `{"changes":[...]}`.
- **PRs**: #297 (Phase 1), #299 (Phase 2 IMAP), #321 (Phase 3 Compose/Send). KB: 260092–260095, 260190. 2026-04-25.

### Scheduler — `scheduler` · `/tools/scheduler` · ⛔
- **Status**: Disabled.

### Social Media — `social_media` · `/tools/social-media` · ⛔
- **Status**: Disabled. When enabled: 30+ routes, OAuth token refresh, multi-platform. `social_accounts`, `social_posts` tables.
- **Rules**: `saas-services.md`

### Task Planner — `task_planner` · `/tools/task-planner` · ⛔
- **Status**: Disabled. Project #263 #1984 proposes integration into Dev HQ instead.

### My Profile — `user_profile` · `/tools/my-profile` · ✅
- **Capability**: User self-service settings, profile, preferences.
- **Audit**: pending

### Google Work Suite — `google_work_suite` · `/tools/google-work-suite` · ✅ · 🟡
- **Capability**: Google OAuth PKCE, Gmail full surface (inbox/fetch/send/sync/batch-LLM-analyze/KB-index), email intelligence (sentiment/intent/urgency/threading), account disconnect. 677 LOC routes + 2,579 LOC services (gmail, calendar, drive, email_intelligence).
- **Tables**: google_accounts (encrypted tokens), oauth_tokens, email_labels, calendar_events, drive_files
- **Gaps**: **Calendar + Drive wired in services but NOT exposed in routes.py** — big UI gap. Token refresh invisible. No quota/rate-limit awareness.
- **Audit**: KB 256846 · **Rules**: `saas-services.md`

### Employee Directory — `directory` · ~~`/tools/directory`~~ · ⛔
- **Status**: DECOMMISSIONED 2026-04-20 (PR #214, Project #262 tasks #2180-2182 + #2184).
- **Canonical replacement**: `/api/public/directory` (+ `/live`) in `platform_v2/public_api.py`, backed by `services/public_roster_service.py` + `public_agent_directory` view (migration 332). Single source of truth for the public directory.
- **Redirects**: `/tools/directory` → `/tools/department-hq#roster` (308); legacy `/tools/department-hq/api/agents/public-roster[/live]` → `/api/public/directory[/live]` (308).
- **Consumers**: `website/kytranempowerment.com/js/directory.js`, `js/ai-directors.js`, creed-ai.org.

### Kytran Business Suite — `kytran_business_suite` · `/external/kbs` · ✅
- **Type**: External/standalone — port 8091, business.kytranempowerment.com
- **Capability**: Unified billing authority (Project #264 P10). 24 plugins. Paywall gates subscription access.
- **Rules**: `saas-services.md`, `standalone-extraction.md`
- **Audit**: pending
- **Known active work**: Project #269 KBS Overhaul (schema, UI review, Printful, Stripe E2E)

---

## project_knowledge (1)

### Project Manager — `project_manager` · `/tools/project-manager` · ⛔
- **Status**: Disabled. #1989 proposes consolidation into Dev HQ. Dev HQ (Consciousness subtab) is the source of truth for unified_projects/tasks/decisions.

---

## applications_concepts (5)

### Media Hub — `media_hub` · `/tools/media-hub` · ✅ · 🟢
- **Capability**: Unified federation: Plex + Jellyfin libraries, Overseerr requests, SABnzbd downloads, Prowlarr search, Sonarr/Radarr media mgmt, TMDB enrichment w/ LRU cache, encrypted API key storage, auto-discovery.
- **Tables**: `media_hub_services`, `media_hub_requests`
- **Audit**: KB 256846 · **Rules**: `media-home.md`
- **Standalone** (media.kytranempowerment.com port 8105): fully extracted. Own DB (`media_hub_services`, `media_hub_users`, `user_watchlist`, `user_preferences`). See KB 261305 for full session detail (PR #335, 2026-04-27).

### Media Hub Standalone — M.A.V.E.N. Agent + Probes (2026-04-27, PR #335)
**M.A.V.E.N. probes** (health_observer.py, all run at startup):
- `grab_notify_probe` (5m) — Overseerr status 3/5 → Telegram via hub /api/notifications
- `download_pipeline_probe` (30m) — SABnzbd stalls + ETA 00:00:00 stuck items
- `download_client_health_probe` (30m) — auto-resyncs stale SABnzbd API keys in Radarr/Sonarr
- `library_coverage_probe` (2h) — finds 0%-coverage shows, triggers scan
- `arr_database_probe` (30m) — detects DB vacuum errors, auto-restarts container
- `stale_queue_probe` (30m) — clears completed/warning Sonarr queue + purges SABnzbd history

**M.A.V.E.N. chat actions** (`POST /maven/api/action`):
- "request X" / "add X" → searches Overseerr + auto-submits request (TV fetches seasons)
- "delete X" → shows red confirm card → deletes from Radarr/Sonarr with files
- Media type detected from keywords (movie/film → movie, show/series → tv, else auto)
- Download stats injected into system prompt (Sonarr per-show progress + SABnzbd status)

**Phase-2 features shipped**:
- qwen2.5:7b as chat model
- Federated search (all Plex+Jellyfin, dedup by tmdb_id+(title,year))
- Watchlist: `user_watchlist` table, GET/POST/DELETE `/api/watchlist`, profile grid
- User preferences: `user_preferences` table, `/api/preferences`
- i18n: EN/FR/ES in `/static/js/i18n.js`, language selector in header + profile page
- Mistake: SABnzbd `set_config` unreliable — edit sabnzbd.ini directly (KB 261306)
- Mistake: Stale Sonarr queue loop requires purging SABnzbd history too (KB 261307)

### Family Tree — `family_tree` · `/tools/family-tree` · ✅ · 🟢
- **Capability**: 4,971 LOC · 44 routes across 7 sub-modules. Person/relationship CRUD (recursive), GEDCOM import/export, face detection + clustering + colorization, OCR, DNA matching, **AI research hints (Bridge dispatch)**, dedup/merge with conflict resolution, timeline narrative generation.
- **Tables**: persons, relationships, photos, documents, dna_profiles, research_hints, sources, dedup_candidates
- **Audit**: KB 256846 — correction: rules file called this "early-stage" but it's actually mature

### Fitness — `fitness` · `/tools/fitness` · ✅ · 🟢
- **Capability**: 803 LOC · 13 routes · FLEX agent (Wellness Coach) via archie_bridge. AI workout generation/form guidance, logging, goal tracking, macro calc (Mifflin-St Jeor BMR/TDEE), safety disclaimers.
- **Audit**: KB 256846 · **Rules**: `applications.md` (stale — says placeholder)

### Therapy — `therapy` · `/tools/therapy` · ✅ · 🟢
- **Capability**: 691 LOC · 12 routes · River agent (Wellness Therapist). **Crisis detection → 988/Crisis Text Line routing**, mood companion SERENE, grounding/breathing/meditation exercises (4-7-8, body scan, 5-4-3-2-1), mood timeline.
- **Audit**: KB 256846 · **Rules**: `applications.md` (stale)

### DOC — `doc` · `/tools/doc` · ✅ · 🟢
- **Capability**: 597 LOC · 10 routes · Dr. Amara agent (Medical Advisor). Symptom logging + non-diagnostic analysis, medication tracking, appointment scheduling, evidence-based guidance w/ disclaimers.
- **Audit**: KB 256846 · **Rules**: `applications.md` (stale)

---

## creative_studios (2)

### Media Studio — `media_studio` · `/tools/media-studio` · ✅ · 🟢
- **Capability**: 9,385 LOC · 98+ routes · 19 service modules. GPU-aware image/video/audio via ComfyUI fleet dispatcher (tier: base/mid/high/CPU), gallery w/ per-user ownership + tagging + smart collections, portrait generation w/ canonical/variant + approval flows, social video queue, batch generation, multi-provider TTS + video, RunPod integration. Bridge dispatch at generation_service.py:128.
- **Portrait pipeline** (2026-04-20, PRs #205-#210): `describe_portrait()` via moondream for auto-prompts (~7s); `upload_canonical()` accepts JPEG/PNG/WebP ≤10MB, resizes to 1024 longest edge, saves as `static/media/portraits/<stem>.png`. Endpoints: `POST /api/portraits/describe`, `POST /api/portraits/<id>/upload`, bulk-generate with serialized progress UX. `agent_portraits.agent_id` now `UNIQUE` (migration 331). Primary upload UI: Agent Profile modal in DHQ Roster. Public roster also now serves `avatar_thumb_url` (relative `/assets/portraits/<stem>.jpg`) so website pages render same-origin thumbs (43× smaller than full PNG).
- **Generation now async** (2026-04-30): `submit_generation()` returns `{queue_id, pending}` instantly for comfyui provider. `media_generation_worker` agent_loop job (30s, Creative & Design / M.U.S.E.) consumes queue — handles VRAM, cold boot, platform restarts. `COMFYUI_HOST=http://172.27.0.11:8188` (direct IP — hostname DNS unreliable).
- **M.U.S.E. Prompt Refinement** (2026-04-30): `POST /api/portraits/<id>/refine-prompt` `{feedback}` → dispatches to M.U.S.E. via DHQ `capability='creative'` → returns `{refined_prompt, original_prompt}`. UI panel in portrait detail: "Refine with M.U.S.E." textarea + ASK M.U.S.E. button + Generate/Save/Dismiss. `saveRefinedPrompt()` uses `PUT /api/portraits/<id>/identity-prompt`.
- **Portrait approve no longer deploys** (2026-04-30): `approve_canonical()` writes thumbnail to website repo only. Deploy handled by `website_deploy_worker` daily job or Repair Bay manual trigger.
- **Tables**: media_generation_queue, media_gallery, media_tags, media_collections, media_smart_collections, media_analytics, agent_portraits (UNIQUE(agent_id))
- **Audit**: KB 256846 · **Rules**: `creative-studios.md`

### Game Studio — `game_studio` · `/tools/game-studio` · ✅ · 🟡
- **Capability**: 2,989 LOC · 30 routes · 6 service files. Game project creation (2D/3D templates), scene mgmt with hierarchy, asset library, world state persistence, session tracking, market/trading, launch w/ event broadcasting.
- **Gaps**: WebSocket multiplayer skeletal, market_service partial, event broadcasting incomplete. Usable for single-player/turn-based; not production-ready for live MMO.
- **Audit**: KB 256846 · **Rules**: `creative-studios.md`

---

## crypto (2)

### Archie Pool — `archie_pool` · `/tools/archie-pool` · ✅ · 🔴
- **Capability**: 398 LOC · 11 routes. Pool stats display, miner lookup, blocks + payment history, worker mgmt per wallet, network stats. Ravencoin hardcoded (COIN="RVN"). **No auth, no persistence, falls back to hardcoded sample data**.
- **Verdict**: Demo/prototype only — NOT production-safe.
- **Audit**: KB 256846 · **Rules**: `crypto.md`

### Pool Management — `pool_management` · `/tools/pool-management` · ✅ · 🟡
- **Capability**: 777 LOC · 18 routes. Pool admin dashboard (stats/miners/blocks/payouts), miner ban actions, payout processing + retry, analytics, settings (fee/min-payout), conversion rate tracking. **Proxies external pool API — no DB tables owned, no auth visible, sample-data fallback.**
- **Audit**: KB 256846 · **Rules**: `crypto.md`

---

## media_outreach (6 external products)

These are standalone products surfaced as modules with `/external/` routes. All run on VPS (76.13.107.109) except KSO/Business Suite on hub.

### Kytran System Operations — `kytran_system_ops` · `/external/kso` · ✅
- **Deployment**: Hub, port 8085, server.kytranempowerment.com
- **Capability**: Compliance engine (STIG/HIPAA/CIS), host_monitor.py bridge, 1-click remediation. 100% Network STIG (per KB 255611).
- **Rules**: `standalone-extraction.md`

### Kytran Gov Watch — `kytran_gov_watch` · `/external/gov` · ✅
- **Deployment**: VPS, port 8102, gov.kytranempowerment.com
- **Capability**: Canadian federal tender intelligence. CanadaBuys + PSPC/CRA feed ingest (`CanadaBuysFeed` in `feeds.py`), filtered browse by department/trade/province/value/deadline, saved supplier profiles (email + trades[] + provinces[] + value range), AI tender analysis + bid drafting, deadline alerts, KBS CRM opportunity push. 21 endpoints, Kytran SSO (dual-auth), shared Postgres in `gov_watch` schema.
- **Distinguishing**: **P.R.O.C.U.R.E. agent** (agent #349, Analytics & Intelligence, `qwen2.5:7b`) — beats the federal government's own Procura chatbot by personalizing to the supplier profile, extracting RFP criteria as checklists, and refusing to deflect users to phone lines. Hub-side dispatch surface: `POST /api/procure/dispatch` (JWT bearer → Bridge). Persona auto-loaded from `agents.system_prompt` so every response opens with "Procure here." See KB #258941 (Procura competitive intel), Project #203.
- **Skills**: tender_match Lv5, tender_summarize Lv5, bid_draft Lv4, naics_mapping Lv4, deadline_alert Lv3, award_history_analysis Lv3, sosa_navigation Lv3, supplier_profile Lv3. All 8 mapped to Analytics &amp; Intelligence in `CAPABILITY_DEPARTMENT_MAP`.
- **Source**: `/mnt/standalone/kytran-gov-watch/` (the `/mnt/archie_brain/kytran-gov-watch/` path is empty — do not edit there).
- **Gaps / Phase 2**: `/procure` conversational surface on Gov Watch, RFP PDF → criteria extractor, extended profile schema (NAICS, certs, Indigenous/women/minority-owned flags), procure_bids pipeline table, existing AI routes migrated to hub dispatch.

### Kytran Market Watch — `kytran_market_watch` · `/external/market` · ✅
- **Deployment**: VPS, port 8101, market.kytranempowerment.com
- **Note**: StockBot was migrated here (project_stockbot-migrated.md)

### What The Fact — `what_the_fact` · `/external/wtf` · ✅
- **Deployment**: VPS, 3 containers — wtf-consumer (port 8103, what-the-fact.com), wtf-tech (port 8104, what-the-fact.tech), wtf-ingest (internal). Supersedes TheNews (retired 2026-04-18).
- **SP2 Capability** (2026-04-25, PRs #329-#332): **10 Canadian sources** with bias profiles (left→right), RSS ingestion every 30 min, **story clustering** (Jaccard title similarity, 24h window), **extractive summarization** (headline/brief/full per cluster), **bias scoring** per article + rolling outlet averages, **fact-checking** (claim extraction + heuristic verdicts).
- **Pipeline**: RSS fetch → canonicalize → bias_score → upsert → cluster → summarize → factcheck → outlet_bias recompute
- **API (wtf-tech)**: `GET /api/v1/articles`, `/articles/<id>`, `/articles/<id>/fact-checks`, `/clusters`, `/clusters/<id>`, `/sources`
- **Schema**: `wtf.sources` (rss_feed, bias_lean), `wtf.articles` (cluster_id), `wtf.story_clusters`, `wtf.summaries`, `wtf.bias_scores`, `wtf.outlet_bias_scores`, `wtf.fact_checks`
- **Pending migrations on VPS**: 002–005 (run `psql $WTF_DATABASE_URL < migrations/00N_*.sql` in order)
- **LLM upgrade paths**: replace extractive summarizer + heuristic fact-checker with Bridge dispatch for accuracy
- **Source**: `/mnt/archie_brain/what-the-fact/` · schema `wtf` on hub Postgres · KB: 260192
- **WTF Hub dispatch** (fixed 2026-05-01, PR #444): `platform_v2/tools/wtf_hub/routes.py` dispatches bias/factcheck/geo tasks to News & Media agents. Capabilities: `bias_analysis`→B.I.A.S., `fact_check`→V.E.R.I.F.Y., `geo_extraction`→L.O.C.A.L. All three added to `CAPABILITY_DEPARTMENT_MAP` in `services/department_coordinator.py`. Dead `prefer_agent` param removed.
- **WTF consumer portraits** (fixed 2026-05-01, PR #449): `routes.py` now fetches live portrait URLs from `/api/public/directory` with 1h cache (no more hardcoded file paths). Redeploy wtf-consumer with `docker compose up -d --build` after code changes (image-baked, not volume-mounted).

### Kytran Legal Watch — `kytran_legal_watch` · `/external/legal` · ✅
- **Deployment**: VPS, port 8100, legal.kytranempowerment.com

### Kytran Civic Watch — `kytran_civic_watch` · `/external/civic` · ✅
- **Deployment**: VPS, port 8099, civic.kytranempowerment.com

### C.R.E.E.D. Institute — `creed_institute` · `/external/creed` · ✅
- **Deployment**: Hub, port 8086, creed.kytranempowerment.com (standalone per Decision #438)
- **Capability**: Governance/ethics enforcement directive, public transparency page. Grant-target nonprofit.
- **Rules**: `standalone-extraction.md`

---

## Audit Progress

**Completed detailed audits** (all 36 modules covered):
- security_network (KB 256841) 🟢 · consciousness (KB 256840) 🟢 · repair_bay (KB 256838) 🟡 · agent_academy (KB 256839) 🟡
- department_hq: security (KB 256837) + core tabs (KB 256843) + dispatch/fleet/jobs (KB 256844) — 🟡 overall
- OAuth/SSO cross-cutting: KB 256845 — 🟡 (6 security tasks #2060–2067)
- Remaining 14 modules consolidated: KB 256846 (task #1946) — 10🟢 / 3🟡 / 1🔴
- Subagent audit failure mode: mistake_learned KB 256847

**All audited**. Remaining open work in Project #263:
- 4 P8 consolidation research tasks (#1984 Task Planner→Dev HQ, #1985 API docs→Consciousness, #1986 GitHub Integration→Consciousness, #1989 Project Manager→Dev HQ)
- VPS-only standalones (civic-watch, legal-watch, market-watch, gov-watch, news) have NO local source — would need extraction for future filesystem audits

**How to contribute an audit**:
1. Use the audit-brief template in prior subagent prompts (under 500 words, operational capabilities + data flow + tables + gaps + verdict)
2. Store via `mcp store_memory(memory_type='vault_note', category='module_capability', tags=[module_id,'audit','capability-index'])`
3. Update the corresponding section of this index with the KB memory_id

---

*Index source of truth: this file.
KB mirror: `search_knowledge(category='module_capability')` returns every detailed audit.*
