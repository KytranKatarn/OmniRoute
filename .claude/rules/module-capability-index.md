---
globs: ["platform_v2/tools/**", "platform_v2/module_registry.py"]
---

# Master Module Capability Index

From `module_registry.py` (36 modules). Full detail: `search_knowledge(category="module_capability")`.

## Legend
- **Status**: ✅ enabled · 🅱 beta · ⏳ coming_soon · ⛔ disabled
- **Maturity**: 🟢 Mature · 🟡 Partial · 🔴 Stub

---

## admin_operations (4)

**W.A.R.D.E.N. agent #363** (Operations & Infrastructure, qwen2.5:7b, Lv4) — autonomous guardian. Dispatch: `user_audit`, `backup_verify`, `compliance_check`, `account_management`, `access_review`. KB #263995. Decision #575.

### Backup Manager — `backup_manager` · `/tools/backup-manager` · ✅ · 🟢
- **Capability**: 10 tabs — Backups (Brain/Full/Archive), Cloud (GDrive AES-256-GCM), External (USB), Deployment, Modules (36), Standalones (9), Hooks, Retention (GFS), Packages. W.A.R.D.E.N. (#363) chat overlay.
- **Tables**: `backups`, `backup_locks`, `webhook_subscriptions`, `backup_log`, `deployment_package_jobs`. All `@admin_required`.
- **Retention**: GFS 7 daily / 4 weekly / 3 monthly. Job #60 auto-cleanup 07:00 AM. Path normalization: `/backups/` and `/mnt/data2/backups/` variants.
- **Standalone schema map** (corrected PR #1407, KB #270283/#270284): `backup_standalone()` has a `db_kind` dispatcher that backs up each watch product's LIVE DB over the Headscale mesh — wtf→`hub_schema` (hub `wtf` DB pg_dump); legal_watch→`sqlite` boston-2 (`kytran_legal_api:/app/data/legal.db`); civic_watch→`sqlite` outpost-us (`kytran_watch_api:/app/data/watch.db`); market_watch→`sqlite` outpost-us (`kytran_market_api:/app/data/market.db`); gov_watch→`pg_container` outpost-us (`gov_watch_db`). kbs/media_hub/creed/kso → still code-only. (Old hub `gov_watch`/`civic_transparency` schemas were stale — no longer dumped.)
- **DR cold-copy (2026-06-02)**: nightly `scripts/backup_triage.sh` (cron 02:00) ships each Daily_Triage to `boston-2:/opt/archie-dr/backups` over mesh (keep-7, `backup_log` tier='dr') + dumps the `wtf` DB + refreshes the boston-2 warm-standby source. Restore needs `pgvector/pgvector:pg16` image (KB #256851). Docs KB #270238/#270239. Project #368.
- **KB Docs**: #264022 · #264472 (audit 2026-05-09) · **Rules**: `admin-ops.md`

### Security & Network — `security_network` · `/tools/security-network` · ✅ · 🟢
- **Capability**: SSL/TLS cert watch, Hostinger DNS CRUD, NPM proxy host lifecycle, 5 compliance rule packs (Ubuntu STIG/Docker STIG/HIPAA/Network STIG/CIS Ubuntu), device discovery (AdGuard+ARP 5min), Home Assistant cameras, supervision schedules.
- **Chat overlay**: **V.I.G.I.L.** #3 → `security-network-chat.js`, red `#ef4444`. 5 action types. Briefing: `tools/archie_chat/security_network_briefing.py`.
- **LCARS gotcha**: Template uses BOTH `--frame-color` CSS vars AND direct `background: #HEX !important` — two-pass replacement required for color changes (64+ sites).
- **KB Docs**: #263992 · #264473 (audit 2026-05-09) · **Rules**: `admin-ops.md`, `compliance-standards.md`

### Account Center — `account_center` · `/tools/account-center` · ✅ · 🟢
- **Capability**: 10 tabs — Overview, Users, Permissions, Subscriptions, Security, Sessions, API Keys, Bulk Ops, Activity, Orgs. Role hierarchy (GUEST 5→SUPER_ADMIN 100). Invite system (`user_invites`, Stalwart SMTP). API key scopes: chat/read/admin.
- **Critical**: `cat_accent` must be `'#ef4444'` (literal hex) NOT `'var(--archie-palette-red-500)'` in Jinja2 inline styles.
- **Chat overlay**: **R.E.S.O.L.V.E.** id=142 → `account-center-chat.js`, red `#ef4444`.
- **KB Docs**: #263991 · #264474 (audit 2026-05-09) · **Rules**: `admin-ops.md`, `app-core.md`

### System Operations — `system_operations` · `/tools/system-operations` · ⛔
- **Status**: Disabled — replaced by KSO standalone at port 8085, server.kytranempowerment.com

---

## ai_command (7)

### Department HQ — `department_hq` · `/tools/department-hq` · ✅ · 🟡
- **Capability**: 12 tabs — Overview, Org Chart, Roster, Work Tracking, Performance, C.R.E.E.D., S.I.G.N.A.L. (Social), Devices, Dispatch, Fleet, Contractors, COMs. Owns `department_dispatcher.py` (Decision #441), orchestration engine (8-step pipeline), smart_router (11-tier GPU-aware), 118 jobs across 13 depts.
- **S.I.G.N.A.L. tab**: LinkedIn management. Account switcher (Kytran / KE Inc. / Creed-AI). EN + FR posts → Telegram approval → LinkedIn. Personal: `linkedin_post` skill. Company: `linkedin_company_post`, `LINKEDIN_COMPANY_SLUG=106863155`. Gap: approval queue DB times out after 120s (task #2526).
- **Fleet/K.I.N.**: A.R.M.A.D.A. merged. K.I.N. auto-rest at >80% capacity (task_queue_limit=500, trigger at 400). Telegram alert on rest trigger. cooldown_recovery restores after 30min. Fleet resource routing: `fleet_resource_router.py` + `model_sizes.py`. `FLEET_RESOURCE_ROUTING_ENABLED` env gates enforcement.
- **Welfare engine (token-based, KB #270628, PRs #1478/#1479)**: ONE shared formula `services/welfare_load.stress_energy_from_load(load, failures, total, hours_on_duty=, is_resting=)` — all 3 writers (`agent_service.update_welfare_after_task`, `agent_jobs.track_agent_hr` 2c, `dept_hq/jobs.kin_workload_monitor` decay-refresh) feed it the same inputs (no staleness gate). "Hours worked today" = wall-clock interval-UNION via `services/agent_load_service.real_compute_hours_today(cur=, agent_id=)` (Postgres `range_agg`, NOT SUM(duration_ms) — concurrency double-count fix), window resets after last completed rest. Weekly job `agent_budget_recalibration` (Mon 05:00 ET, `agent_jobs.recalibrate_token_budgets`) re-tunes `agent_budgets.token_limit_per_day = max(50k, p90(30d daily tokens)×1.3)`. Public methodology: creed-ai.org WP-002 §8.
- **Hardware-aware node provisioning wizard (#3731, PR #1416, 2026-06-03, LIVE)**: `services/node_provisioning.py` `recommend(cpu/ram/gpu/vram)` → tier + can/cannot-run Ollama + warm-set + ComfyUI checkpoint (VRAM tiers KB#240991; footprints `services.model_sizes`). Endpoints: `GET /api/nodes/<node_id>/model-recommendation`, `POST /api/nodes/model-recommendation` (pre-enroll preview), `POST /api/nodes/<int:id>/provision-warm-set` (fans out to `mesh_sync_log` model_pull/checkpoint_pull — same OTA queue as per-model pulls). UI: 'AI Models' panel in the Fleet node-detail modal (`showNodeDetail()` in `tools/department_hq/static/js/department-hq.js`). Docs KB#270459. Open: #3732 auto-provision at enrollment.
- **Dispatch**: Claude Requests panel — `GET /api/dispatch/claude-feed`. ContextVar attribution flows `request_origin='claude'` through dispatcher to `task_execution_log`. DISPATCH QUEUE + LOADED MODELS panel: `GET /api/fleet/queue-status`.
- **Delegation**: `mcp__archie__delegate_task(capability, reason)` → `unified_tasks` → `delegate_task_worker` (30s, max 3/cycle) → known-tool shortcut or dispatcher.
- **Agentic KB tools (#3534, 2026-05-31, LIVE)**: tool-capable agents (D.A.R.W.I.N./S.P.E.C.T.R.A./W.A.T.C.H., 7B+) run a native Ollama `/api/chat` tool-loop to READ (`search_knowledge`/`search_mistakes`/`recall_context`) and WRITE (`store_memory`) the KB mid-task. `ai_bridge/agentic_search.py` (loop) + `services/agent_kb_service.py` (writes). Writes quarantined (`source_type='agent_proposed'`/`review_status='pending'`, embedding NULL) → hourly `agent_kb_review` job → C.O.D.E.X. promote/reject. Quarantine filter in semantic_search/rag_service/MCP search. Flags `agentic_tool_search` + `agentic_tool_write` (platform_settings, both ON). ADRs #663/#664; migration 409.
- **Scheduler sidecar** (`archie_scheduler`): APScheduler runs separately. New sidecars MUST mirror platform volumes block exactly — drift = silent job degradation (KB #263303).
- **Autonomy tab = Backlog & Jobs Control Center** (decision #676, 2026-06-01): see+toggle every job/loop/backlog on/off. `services/work_control_service.py` is the unified toggle (is_enabled/set_enabled/list_controls; backends platform_settings `work:<key>:enabled` / consciousness loops / WTF env). Backlogs API `GET/POST /api/dispatch/backlogs[/<key>/toggle]` (dispatch_routes.py) + UI in `panel-autonomy`. **Fleet Backlog Runner** (`fleet_backlog_runner` job, agent_loop.py, DEFAULT OFF) promotes ≤3 pending unified_tasks/cycle → fleet. Standard: `.claude/rules/module-work-pattern.md`. Delegation reliability gaps tracked in mistake #269999 (360s timeout; output persistence FIXED PR #1364).
- **Gaps**: agent_skills/budgets/creation_events not agent_service-owned (#2057); 18 legacy ai_bridge.* imports (#2058); CAPABILITY_TAXONOMY hardcoded in smart_router.
- **Audits**: KB 256837/256843/256844 · **Rules**: `department-hq-dispatch.md`, `starbase.md`

### Consciousness — `consciousness` · `/tools/consciousness` · ✅ · 🟢
- **Capability**: 5 tabs + Dev HQ subtabs + Code Health + **Token Economy** tab. Owns `knowledge_base` (31k+ entries, 99%+ embedded). Embedding/Analysis/Translate/GitHub-ingest loops. 129 routes, 62+ async jobs.
- **Token Economy tab** (PR #1394, panel-tokens): local-vs-external token split, per-agent+per-model token counts (cloud=orange, agent-name color=local/cloud blend), tokens-over-time (1H/24H/7/30/90/ALL — sub-day = epoch-floor buckets w/ server-rendered Toronto-local labels), Cloud Impact + capacity/authorship timeline. Endpoint `GET /api/code-health/token-usage?range=1h|24h|7|30|90|365` (`?days=` back-compat) (`code_health_routes.py`, source=task_execution_log, 600s TTL cache). Claude CLI tokens via host cron `scripts/ingest_claude_cli_tokens.py`; historical estimate `scripts/estimate_historical_claude_tokens.py` (capacity-ceiling, ADR-685). Docs KB #270263/#270264/#270265.
- **Code Health self-healing loop** (PRs #1401/1402/1403, KB #270273): scans async via `bridge_jobs` (`POST scan|backfill-git|audit` [no module=audit-all, scans tree once] → poll `GET /api/code-health/job-status/<id>`; advisory-lock dedup). `reverify_deployed_findings()` (`audit_pipeline.py`) re-audits deployed proposals → flips metadata.reverified fixed/still_open (auto after audit-all; manual `POST /api/code-health/reverify`). `GET /api/code-health/orchestration` = per-department ownership (issue→capability→dept; vulnerability_scan→V.I.G.I.L.) + open/deployed/fixed/still_open. UI: Department Orchestration panel (`#chOrchestration`).
- **Integrations**: MCP `store_memory`/`search_knowledge`/`recall_context`/`create_task`/`log_decision`. Repair Bay Code Health: findings → proposals → deploy → re-verify (loop closed, PR #1402).
- **Audit**: KB 256840 · **Rules**: `consciousness.md`, `project-knowledge.md`

### A.R.C.H.I.E. Chat — `archie_chat` · `/tools/archie-chat` · ✅ · 🟡
- **Capability**: Text messaging (Claude-routed or Telegram-bridged), conversation CRUD, agent roster, bridge stations, API key mgmt, Home Assistant voice synth.
- **Tables**: `conversations`, `messages` (source=ha_voice/telegram/web), `api_keys`, `agent_assignments`
- **API key scopes**: `chat` / `read` / `admin` — enforced by `require_scope()` in `auth_middleware.py`. Session users bypass.
- **Gaps**: Telegram via external `archie_comms` (:3002); STT missing; team convo scoping partial.
- **Audit**: KB 256846 · **Rules**: `autonomy.md`

### Repair Bay — `repair_bay` · `/tools/repair-bay` · ✅ · 🟡
- **Capability**: Scan→Proposal→Sandbox→Deploy pipeline. 8 tabs: Reviews, PR Review, Repairs, Diagnose, Test Bay, Ship, QA, Pushes + ENGINEERING station. 10 route files.
- **Ship tab**: `GET /api/deploy/website-status`, `POST /api/deploy/website-trigger`. Results in `system_config` keys `website_deploy_last_run_<domain>` / `website_deploy_last_status_<domain>`.
- **CRITICAL**: Hostinger `POST /api/hosting/v1/websites/{username}/deploy` → **404**. Only working path: `/deploy-website` skill via `mcp__hostinger-api__hosting_deployStaticWebsite`. KB #261679.
- **P.R.O.B.E. perf baselines**: `qa_baseline_service.py`. Tables: `qa_perf_baselines`, `qa_perf_regressions`, `qa_perf_acceptances`. Post-deploy gate: rollback>pause>flag>none. Job #59 nightly 03:45 EDT.
- **Scheduler volumes**: `archie_scheduler` MUST mirror `archie_platform` volumes — missing `/mnt/standalone:ro` silently dropped Code Health by 35% (KB #263303).
- **Gaps**: `_has_open_proposal()` dedup not visible; one-way Consciousness flow.
- **Audit**: KB 256838 · **Rules**: `repair-bay.md`

### Agent Academy — `agent_academy` · `/tools/agent-academy` · ✅ · 🟡
- **Capability**: 5 tabs — Benchmarks, Training, A/B Testing, Skills, Reports. Lv1–5 proficiency (Lv4 unlocks cloud).
- **Tables**: `agent_benchmark_results`, `agent_competency_scores`, `agent_learning_records`, `v_department_readiness`
- **Gaps**: Reports endpoints missing; training automation disabled; Lv4 cloud-unlock not C.R.E.E.D. gated.
- **Audit**: KB 256839

### Automations — `automations` · `/tools/automations` · ⛔
- **Status**: Disabled. Scope unclear.

### C.R.E.E.D. Command — `creed_command` · `/tools/creed-command` · ✅ · 🟢
- **Capability**: E.T.H.O.S. (agent #336) governance work dashboard. 7 tabs — Dashboard (live CREED governance KPIs + weekly ethics brief), **Inbox** (5 Hostinger creed-ai.org boxes over IMAP → E.T.H.O.S. triage → draft → **send-as** via SMTP), **Grants** (pipeline + E.T.H.O.S. drafting), **Marketing** (channel-specific promo gen, grounded, no auto-publish; **'Send to S.I.G.N.A.L. →'** on LinkedIn assets → linkedin_post approval queue post_type=creed, PR #1563), **Tenants** (#3945, PR #1565 — multi-tenant ops: org applications approve+mint-key/reject, active-tenant directory w/ grade/freshness/tier, per-tenant key mgmt; thin hub-local proxies in `tenants_routes.py` → standalone `/api/internal/tenants|applications` + approve/reject/keys, authed w/ shared `CREED_INTERNAL_KEY`), **Files** (in-DB bytea document library + grant linking), Governance (live CREED surface links).
- **Multi-tenant (kytran_creed standalone)**: `internal_or_admin` decorator (X-Internal-Key OR admin session) gates tenant-admin; 10 tenants provisioned (per-product self-transparency #3958, spec KB #272125): creed-institute(public)/kytran-empowerment/what-the-fact/gov-watch/civic-watch/legal-watch/market-watch/media-hub/kso/kbs. **Routing LIVE (#3958 DONE, PR #1569, 2026-06-10)**: every governance event routes to the EMITTING agent's product tenant — `agents.creed_tenant` (migration 428; NULL→kytran-empowerment default; 15 seeded incl. dept-traps M.A.V.E.N.→media-hub, G.A.V.E.L.→platform) + `services/creed_emit.py` shared emitter (`emit_event()`/`auth_header_for_agent()`, TTL-cached resolve, per-product `CREED_INGEST_KEY_<X>` in BOTH .env files, fallback product→default→legacy, `module` tag for core-platform drill-down, `routed_tenant` audit field, DB password via Docker secret file). All 4 hub push sites migrated: agent_loop governance reporter, bias_sampling, carbon_footprint (module=Infrastructure), incident_service (first affected agent). Flip each tenant preview→public when it passes the provisional gate. NEW agent→product assignment = data update on `agents.creed_tenant`, no code.
- **Scoring pillar gate (kytran-creed PR #21, 2026-06-10)**: pillars with <`CREED_PILLAR_MIN_EVENTS` (default 100) events are `provisional` (raw score still shown + note) and EXCLUDED from overall; if NO pillar qualifies → legacy averaging flagged `overall_provisional` (low-volume tenants get no fake confident grade). `/api/v1/scores` adds `overall_provisional`/`pillar_min_events`/`overall_categories`. Fixed live institute 89.6/B+ (2-event env pillar artifact) → 99.6/A+. Real env fix = carbon estimator #3254 (now feeds kytran-empowerment tenant). KB #272128.
- **Mail (self-contained, NOT Email Manager — Stalwart-only, ADR-003/#675)**: `mail_routes.py` → imap.hostinger.com:993 + smtp.hostinger.com:465, per-box `CREED_MAIL_*_PASSWORD` in root `.env`. Read-only IMAP (BODY.PEEK); send gated on explicit human click. Routes: `/api/mail/{status,inbox,message,triage,draft,ai,send}`.
- **Routes**: `grants_routes.py`, `mail_routes.py`, `marketing_routes.py`, `files_routes.py` — all `register_*_routes(bp, admin_required)`. Admin-only.
- **E.T.H.O.S. dispatch**: `capability='policy_assessment'`, `prefer_agent='E.T.H.O.S.'`, **`preferred_node=['Starship-246','Starship-245']`** (GPU cluster, ~1-3s). Async+poll+DB for all AI ops.
- **Tables**: `creed_grants`, `creed_mail_ai`, `creed_marketing_assets`, `creed_files` (migrations 412–416).
- **KB Docs**: #269978–269992 (coder+user per PR) · **PRs**: #1354–1358 (+#1353 GPU routing). Project #367 (feature-complete 2026-06-01).

---

## saas_services (9)

### Email Manager — `email_manager` · `/tools/email-manager` · ✅ · 🟢
- **Capability**: Three-panel command center (Sidebar/Message List/Read Pane). 49 mailboxes (38 AI + 10 business + 1 owner). IMAP sync 5min, AI triage, rules engine, threading, R.E.S.O.L.V.E. auto-reply drafts, chat overlay.
- **Tables**: `email_mailboxes`, `email_messages` (use `imap_uid` NOT `uid`; has `attachment_count`, `ai_priority`, `thread_id`, `in_reply_to`), `email_threads`, `email_rules`, `email_activity_log`.
- **CRITICAL — Stalwart**: Use `http://stalwart_mail:8080` (plain HTTP, Docker internal). NEVER `https://192.168.1.200:8443` — hairpin NAT blocks TLS from containers.
- **Chat overlay**: **R.E.S.O.L.V.E.** → `email-manager-chat.js`, `email_hq_briefing.py`.
- **KB Docs**: #265260 (user) · #265261 (coder) · Migrations 375–378

### Scheduler — `scheduler` · `/tools/scheduler` · ⛔

### Social Media — `social_media` · `/tools/social-media` · ⛔
- **Status**: Disabled. Tables: `social_accounts`, `social_posts`. **Rules**: `saas-services.md`

### Task Planner — `task_planner` · `/tools/task-planner` · ⛔
- **Status**: Disabled. #1984 proposes integration into Dev HQ.

### My Profile — `user_profile` · `/tools/my-profile` · ✅
- **Capability**: User self-service settings, profile, preferences. Audit: pending.

### Google Work Suite — `google_work_suite` · `/tools/google-work-suite` · ✅ · 🟡
- **Capability**: Google OAuth PKCE, Gmail (inbox/fetch/send/sync/LLM-analyze/KB-index), email intelligence (sentiment/intent/urgency/threading).
- **Tables**: `google_accounts` (encrypted tokens), `oauth_tokens`, `email_labels`, `calendar_events`, `drive_files`
- **Gaps**: Calendar + Drive wired in services but NOT exposed in routes.py. No quota/rate-limit awareness.
- **Audit**: KB 256846 · **Rules**: `saas-services.md`

### SaaS Manager — `saas_manager` · `/tools/saas-manager` · ✅ · 🟡
- **Capability**: Org CRUD, per-org module enable/disable, custom domain verify (DNS TXT), node assignment. `show_on_dashboard=False` — folded into Account Center ORGS tab.
- **Tables**: `organizations`, `org_users`, `org_modules`, `org_domains`, `org_nodes`
- **Gaps**: No subscription_level binding on org_modules — blocks #2018 KBS plugin tier gating.
- **Audit**: KB 256846 · **Rules**: `saas-services.md`

### Employee Directory — `directory` · ⛔
- **Status**: DECOMMISSIONED 2026-04-20. Canonical replacement: `/api/public/directory` in `public_api.py` backed by `public_roster_service.py` + `public_agent_directory` view. Redirects: `/tools/directory` → `/tools/department-hq#roster` (308).

### Kytran Business Suite — `kytran_business_suite` · `/external/kbs` · ✅
- **Type**: Standalone — port 8091, business.kytranempowerment.com. 24 plugins. Paywall gates access.
- **Rules**: `saas-services.md`, `standalone-extraction.md`. Active: Project #269 KBS Overhaul.

---

## project_knowledge (1)

### Project Manager — `project_manager` · `/tools/project-manager` · ⛔
- **Status**: Disabled. Dev HQ (Consciousness subtab) is source of truth for unified_projects/tasks/decisions.

---

## applications_concepts (5)

### Media Hub — `media_hub` · `/tools/media-hub` · ✅ · 🟢
- **Capability**: Plex + Jellyfin, Overseerr requests, SABnzbd, Prowlarr, Sonarr/Radarr, TMDB enrichment w/ LRU cache.
- **Tables**: `media_hub_services`, `media_hub_requests`
- **Standalone** (media.kytranempowerment.com port 8105): own DB. M.A.V.E.N. probes: grab_notify (5m), download_pipeline (30m), download_client_health (30m), library_coverage (2h), arr_database (30m), stale_queue (30m). Chat: "request X" / "delete X" (with red confirm). Phase 2: qwen2.5:7b, federated search, watchlist, i18n EN/FR/ES.
- **Gotchas**: SABnzbd `set_config` unreliable — edit sabnzbd.ini directly (KB 261306). Stale Sonarr queue loop requires purging SABnzbd history too (KB 261307).
- **Audit**: KB 256846 · KB 261305 · **Rules**: `media-home.md`

### Family Tree — `family_tree` · `/tools/family-tree` · ✅ · 🟢
- **Capability**: 4,971 LOC · 44 routes. Person/relationship CRUD, GEDCOM import/export, face detection/clustering/colorization, OCR, DNA matching, AI research hints (Bridge dispatch), dedup/merge, timeline narrative.
- **Tables**: `persons`, `relationships`, `photos`, `documents`, `dna_profiles`, `research_hints`, `sources`, `dedup_candidates`
- **Audit**: KB 256846

### Fitness — `fitness` · `/tools/fitness` · ✅ · 🟢
- **Capability**: 803 LOC · 13 routes · FLEX agent (Wellness Coach). Workout gen, form guidance, logging, goal tracking, macro calc (Mifflin-St Jeor BMR/TDEE).
- **Audit**: KB 256846

### Therapy — `therapy` · `/tools/therapy` · ✅ · 🟢
- **Capability**: 691 LOC · 12 routes · River agent (Wellness Therapist). Crisis detection → 988/Crisis Text Line, mood companion SERENE, grounding exercises (4-7-8, body scan, 5-4-3-2-1).
- **Audit**: KB 256846

### DOC — `doc` · `/tools/doc` · ✅ · 🟢
- **Capability**: 597 LOC · 10 routes · Dr. Amara (Medical Advisor). Symptom logging, medication tracking, appointment scheduling, evidence-based guidance w/ disclaimers.
- **Audit**: KB 256846

---

## creative_studios (2)

### Media Studio — `media_studio` · `/tools/media-studio` · ✅ · 🟢
- **Capability**: 9,385 LOC · 98+ routes · 19 service modules. GPU-aware ComfyUI fleet + 6 cloud contractors (OpenAI DALL-E 3, Gemini Imagen 3, HuggingFace, Cloudflare AI, Together, Pollinations). Gallery, portrait gen, batch gen, multi-provider TTS/video. Blueprint: `template_folder="templates"`.
- **Image routing** (ADR-005): ALL image gen → worker queue → `media_generation_worker` (30s) → `generate_via_comfyui` → branches to `_generate_via_contractor` if `params.provider` set. NEVER sync dispatch for image gen — blocks web thread.
- **Provider selector**: `GET /tools/media-studio/api/image-providers` → `{auto, local[], cloud_free[], cloud_paid[]}`. Value format: bare filename for local, `provider:<key>` for cloud. `needs_key=true` options disabled. Free: Pollinations/Cloudflare/Together always selectable.
- **Portrait pipeline**: `describe_portrait()` via moondream (~7s). Upload: JPEG/PNG/WebP ≤10MB → 1024px longest edge → PNG. `agent_portraits.agent_id` UNIQUE (migration 331). Primary upload UI: Agent Profile modal in DHQ Roster.
- **Variant badges**: bottom-left = GPU label from `fleet_node`, bottom-right = model/provider name.
- **Fleet gotchas**: `COMFYUI_HOST=http://172.27.0.11:8188` (direct IP — hostname DNS unreliable). Cold-load timeout 600s for sd_xl_base on RTX 3070. Fail-loud on timeout — NO silent hub fallback.
- **Tables**: `media_generation_queue` (`params->>provider`, `params->>fleet_node`), `media_library`, `agent_portraits` (UNIQUE agent_id), `contractor_providers`, `cloud_model_usage`.
- **Open tasks**: #2940 Replicate/Fal.ai/Stability adapters (needs API keys).
- **Audit**: KB 256846 · #266418–#266420 · **Rules**: `creative-studios.md`

### Game Studio — `game_studio` · `/tools/game-studio` · ✅ · 🟡
- **Capability**: 2,989 LOC · 30 routes · 6 service files. Game project creation (2D/3D), scene mgmt, asset library, world state, market/trading.
- **Gaps**: WebSocket multiplayer skeletal, market_service partial — not production-ready for live MMO.
- **Audit**: KB 256846

---

## crypto (2)

### Archie Pool — `archie_pool` · `/tools/archie-pool` · ✅ · 🔴
- **Capability**: 398 LOC · 11 routes. Pool stats display (Ravencoin hardcoded). **No auth, no persistence, sample data fallback. Demo only.**
- **Audit**: KB 256846

### Pool Management — `pool_management` · `/tools/pool-management` · ✅ · 🟡
- **Capability**: 777 LOC · 18 routes. Pool admin dashboard — proxies external pool API, no DB owned, sample-data fallback.
- **Audit**: KB 256846

---

## media_outreach (6 external standalones)

All VPS (76.13.107.109) except KSO/KBS/CREED on hub.

### Kytran System Operations — `kytran_system_ops` · `/external/kso` · ✅
- **Deployment**: Hub port 8085, server.kytranempowerment.com. Container: `kytran-system-operations`.
- **Source**: `/mnt/archie_brain/kytran-server-manager/` (gitignored, no separate git repo).
- **Capability**: Compliance engine (STIG/HIPAA/CIS), host_monitor.py bridge, 1-click remediation. 9 tabs.
- **Chat overlay**: **B.A.S.E.** #139 → `kso-chat.js`, red `#ef4444`. Proxy: `chat_proxy_routes.py` → hub (http://192.168.1.200:3000). Env: `KSO_CHAT_API_KEY`, `KSO_ARCHIE_HUB_URL`.
- **Pip-install gotcha**: Source loads from site-packages NOT /app/ — hot-patches need BOTH paths. Rebuild: `docker compose build + up -d --no-deps`.
- **KB Docs**: #264475 (audit 2026-05-09)

### Kytran Gov Watch — `kytran_gov_watch` · `/external/gov` · ✅
- **Deployment**: VPS port 8102, gov.kytranempowerment.com.
- **Source**: `/mnt/standalone/kytran-gov-watch/` (**NOT** `/mnt/archie_brain/kytran-gov-watch/` — that path is empty).
- **Capability**: CanadaBuys + PSPC/CRA tender intelligence. P.R.O.C.U.R.E. agent (#349, qwen2.5:7b). 21 endpoints, Kytran SSO. Hub dispatch: `POST /api/procure/dispatch` (JWT bearer).
- **_sync_user_tier gotcha**: CASE clause only protects `('agency','team','solo')` — `'kytran'` tier gets reset to free on every login. Fix: numeric hierarchy lookup, never downgrade higher→lower.

### Kytran Market Watch — `kytran_market_watch` · `/external/market` · ✅
- **Deployment**: VPS port 8101, market.kytranempowerment.com. StockBot migrated here.

### What The Fact — `what_the_fact` · `/external/wtf` · ✅
- **Deployment**: VPS — wtf-consumer port 8103 (what-the-fact.com), wtf-tech port 8104 (what-the-fact.tech), wtf-ingest (internal).
- **Capability**: 10 Canadian sources, RSS 30min, story clustering (Jaccard), extractive summarization, bias scoring, fact-checking. OAuth SSO paywall (bias free, rationale/Deep Dive gated).
- **Schema**: `wtf.sources`, `wtf.articles`, `wtf.story_clusters`, `wtf.summaries`, `wtf.bias_scores`, `wtf.outlet_bias_scores`, `wtf.fact_checks`.
- **CRITICAL**: NEVER pass `WTF_TECH_URL` to browser JS — always add server-side proxy route first (KB #267314).
- **Hub**: `tools/wtf_hub/wtf_hub.html` extends base.html, teal `#00ffff`. Hub dispatch: `bias_analysis`→B.I.A.S., `fact_check`→V.E.R.I.F.Y., `geo_extraction`→L.O.C.A.L.
- **Redeploy**: `docker compose up -d --build wtf-consumer` (image-baked, not volume-mounted).

### Kytran Legal Watch — `kytran_legal_watch` · `/external/legal` · ✅
- **Deployment**: VPS port 8100, legal.kytranempowerment.com

### Kytran Civic Watch — `kytran_civic_watch` · `/external/civic` · ✅
- **Deployment**: VPS port 8099, civic.kytranempowerment.com

### C.R.E.E.D. Institute — `creed_institute` · `/external/creed` · ✅
- **Deployment**: Hub port 8086, creed.kytranempowerment.com (standalone per Decision #438).
- **Capability**: Governance/ethics enforcement, public transparency, grant-target nonprofit.
- **Public APIs (all no-auth, CORS-open `*`, 60s cache)**: `GET /api/public/score` → `{score, grade, events_today, active_categories, last_checked}` (#3362, `routes/public_routes.py`); `GET /api/v1/scores` → `{overall, grade, event_count, by_category{accountability|fairness|privacy|safety|transparency}}` (`api_routes.py`, CORS added kytran-creed PR #3 — powers creed-ai.org governance widget); `GET /api/v1/badge/overall` → SVG badge (`badge_routes.py`). Consumed by creed-ai.org + WTF. Live (99.5/A+). **Verify cross-origin from EXTERNAL vantage** — hub-LAN browser hits Chrome PNA (split-horizon DNS → private IP), KB #269948/#269951.
- **Rules**: `standalone-extraction.md`

---

## Audit Status

All 36 modules audited. Core KB refs: 256837–256847. Open consolidation tasks: #1984, #1985, #1986, #1989.

**Add an audit**: `mcp store_memory(type='vault_note', category='module_capability', tags=[module_id,'audit'])` then update the relevant section above with the KB ID.

---

*Full detail in KB. This file = operational index only — keep it lean.*
