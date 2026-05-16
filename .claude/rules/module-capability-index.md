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

## admin_operations (4)

**W.A.R.D.E.N. agent #363** (Operations & Infrastructure, qwen2.5:7b, Lv4) is the autonomous guardian for this category. Dispatch: `user_audit`, `backup_verify`, `compliance_check`, `account_management`, `access_review`. Skills file: `.claude/skills/warden-agent.md`. KB #263995. Decision #575.

### Backup Manager — `backup_manager` · `/tools/backup-manager` · ✅ · 🟢
- **Capability**: 10 tabs — Backups (Brain/Full/Archive), Cloud (GDrive AES-256-GCM), External (USB), Deployment (pre-deploy snapshots), Modules (36 modules, search, age colors, restore), Standalones (9 products, partial/full status), Hooks (upload scripts + webhooks LCARS), Retention (GFS configurable 10d/5w/6m), Packages. 9,527 LOC. W.A.R.D.E.N. (#363) chat button with portrait. Zero browser confirm()/prompt().
- **Tables**: `backups`, `backup_locks`, `webhook_subscriptions`, `backup_log` (+ `standalone_name`), `deployment_package_jobs`. All routes `@admin_required`.
- **Standalone schema map**: gov_watch→`gov_watch`, civic_watch→`civic_transparency`, wtf→`wtf` (hub archie DB); kbs/media_hub/creed/kso/legal_watch/market_watch → own DBs (partial = code-only).
- **Chat overlay**: `backup-manager-chat.js` → **W.A.R.D.E.N.** #363, red `#ef4444`. Reference implementation for module-agent pattern. Server-side `_inject_warden_action()` for cleanup/backup/standalones. All 3 actions verified 2026-05-08. KB #264461.
- **Retention**: GFS 7 daily / 4 weekly / 3 monthly (max 14). **Job #60** auto-cleanup at 07:00 AM in `department_hq/jobs.py`. Path normalization: cleanup matches both `/backups/` and `/mnt/data2/backups/` variants + sub-component LIKE. W.A.R.D.E.N. briefing flags path anomalies proactively.
- **Badges**: daily (blue), weekly (purple), monthly (amber) — added 2026-05-08. Standalones excluded from main backup list (own tab). Cron script: `platform_version` dynamic from DB, `backup_type` = mode (daily/weekly/monthly).
- **Code health**: ✅ CLEAN, 14 files, 9,527 LOC. **QA**: Suite #19 23/23 passed (run_id 2113, 2026-05-09).
- **Gaps**: ~~Preview modal fails DB-only backups~~ → **Fixed (PR #581)** — DB-ONLY badge shown instead of "0 files". USB sync already wired. pg_dump is custom Python by design (architectural choice, not a bug). Zero open gaps.
- **KB Docs**: #264022 (audit 2026-05-07) · #264057 (user ref) · #264058 (chat overlay coder ref) · #264461 (W.A.R.D.E.N. chat 2026-05-08) · **#264472** (full audit 2026-05-09) · **Rules**: `admin-ops.md`

### Security & Network — `security_network` · `/tools/security-network` · ✅ · 🟢
- **Capability**: SSL/TLS cert watch, Hostinger DNS CRUD, NPM proxy host lifecycle, 5 compliance rule packs (Ubuntu STIG/Docker STIG/HIPAA/Network STIG/CIS Ubuntu), device discovery (AdGuard+ARP 5min), Home Assistant cameras, recon scans, supervision schedules (AdGuard per-device blocking), 23 agent loop jobs.
- **Distinguishing**: JSON rule pack abstraction, host_command queue bridge, full DNS audit trail. Supervision blocks social/gaming/streaming/adult categories per device per time window.
- **Chat overlay**: `security-network-chat.js` → **V.I.G.I.L.** #3 (Security & Compliance director), red `#ef4444`. Live briefing from DB (scan results, device count, compliance score). 5 action types: run_compliance_scan, check_ssl_certs, check_security_alerts, run_network_scan, check_firewall_rules. Briefing: `tools/archie_chat/security_network_briefing.py`. Action injection: `_inject_vigil_action()` in `archie_chat/api_routes.py`. KB #264473.
- **LCARS note**: Template uses BOTH `--frame-color` CSS vars AND direct `background: #HEX !important` inline — two-pass replacement required for future color changes (64+ replacements total, done 2026-05-09).
- **Code health**: ✅ CLEAN, 71 files, 38,964 LOC. **QA**: Suites #5/#6/#8 21/21 passed (run_ids 2088/2093/2097, 2026-05-09). All f-string SQL removed (PR #551).
- **KB Docs**: #263992 (full user + developer guide, 2026-05-06) · **#264473** (full audit 2026-05-09) · **Rules**: `admin-ops.md`, `compliance-standards.md`

### Account Center — `account_center` · `/tools/account-center` · ✅ · 🟢
- **Capability**: 10 tabs — Overview, Users, Permissions, Subscriptions, Security, Sessions, API Keys, Bulk Ops, Activity, Orgs. User CRUD, role hierarchy (GUEST 5→SUPER_ADMIN 100), invite system (user_invites table, Stalwart SMTP), API key scopes (chat/read/admin), login lockout (5→15min), IP rate limit (20/15min), HMAC access control API, internal notify endpoint.
- **Key security**: `auth_service.py` 23 functions; `SESSION_COOKIE_SECURE` env-driven; IP rate limit exempts 172.x for internal QA.
- **Code health**: ✅ CLEAN, 8 files, 11,238 LOC. **QA**: Suite #16 35/35 passed (run_id 2114, 2026-05-09).
- **Chat overlay**: `account-center-chat.js` → **R.E.S.O.L.V.E.** (id 142, Customer Success & Support), red `#ef4444`. Persistent shared team channel. Verified 2026-05-09. KB #264465.
- **LCARS fix (2026-05-09)**: `cat_accent` must be `'#ef4444'` (literal hex) NOT `'var(--archie-palette-red-500)'` — CSS var refs don't resolve as Jinja2 inline style values.
- **KB Docs**: #263991 (full user + developer guide, 2026-05-06) · #264465 (chat overlay, 2026-05-08) · **#264474** (full audit 2026-05-09) · **Rules**: `admin-ops.md`, `app-core.md`
- **Security status (audited 2026-05-09)**: ✅ PKCE fully implemented (S256, all SDKs). ✅ Password reset fully implemented (`initiate_password_reset()`, `complete_password_reset()`, `forgot_password.html`, login link). SECRET_KEY in `.env` (correct practice — no rotation UI yet, deferred). SDK duplication: 7×`kytran_auth.py` copies across products — deferred (2-3 day extraction effort, task #2065).

### System Operations — `system_operations` · `/tools/system-operations` · ⛔
- **Status**: Disabled in registry — replaced by Kytran System Operations (`kytran_system_ops` at `/external/kso`)
- **Note**: Standalone product at port 8085, server.kytranempowerment.com

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
- **Fleet tab — Queue panel (PR #464, 2026-05-01)**: New DISPATCH QUEUE + LOADED MODELS panel. `GET /api/fleet/queue-status` → `{queued, running, items[], loaded[]}`. Queries `dispatch_pending_queue`; live Ollama `/api/ps`. 30s auto-refresh. KB #261708.
- **Dispatch tab — Claude Requests panel (PRs #493 + #494, 2026-05-03)**: ContextVar attribution in `mcp_server/dispatch_context.py` flows `request_origin='claude'` + `mcp_tool=<name>` from MCP `call_tool` through dispatcher's `_log_execution` to `task_execution_log`. New `GET /api/dispatch/claude-feed?hours=&limit=` returns `{feed[], by_tool[], success_rate, total}`. New CLAUDE REQUESTS section in DHQ Dispatch tab (top-tools chips + table). New `_notify_claude_dispatch` hook fires platform alerts on every Claude dispatch (severity by outcome) + Telegram on failures/cost-bearing when `CLAUDE_DISPATCH_TELEGRAM=1`. Activates on Claude Code session restart. KB #262281, #262282, ADR-001.
- **Fleet resource-aware routing (PRs #504 + #505, 2026-05-03, ADR-555 / Project #303 #2516)**: New `services/model_sizes.py` (model_name → {vram_gb, ram_gb, prefer_gpu}) + `services/fleet_resource_router.py` (`score_node_for_model`, `should_dispatch_to_node`, `utilization_pct`, `is_stale`). New `GET /tools/fleet/api/node-utilization` returns per-node `{load_pct, fail_rate, stale, gpu/cpu/ram, extra_capabilities}` + aggregate `{online_count, total_count}`. New `fleet_capacity_report` agent_loop job (24h, 03:45 UTC) writes daily vault_note (category `fleet_capacity`) and Telegram-pings A.R.C.H.I.E. when any node sustains ≥80% load. **PR #505 wires capacity precheck into `BridgeDispatcher._dispatch_to_node`** — fail-open, gated by `FLEET_RESOURCE_ROUTING_ENABLED` env (default `false` = log warnings only; `true` = refuse mismatched dispatch, caller's existing escalation handles fallback). 31 unit tests. KB #262300–#262304. Phase 3 (real-time VRAM tracking via heartbeat extension) deferred for 48h soak.
- **APScheduler sidecar + workers=4 (PRs #510/#511/#512/#513, 2026-05-03, decision_id 558)**: Three-arc fix for the qa_scheduled flake (27 → 1 errored). (1) `qa_spec_runner.execute_spec()` accepts `skip_auth` flag and `qa_service.run_suite()` accepts `session` + `skip_auth` so `_run_qa_scheduled` can authenticate ONCE per `(base_url, user)` and reuse across all suites in the loop. Inter-suite sleep dropped 8s → 2s. (2) APScheduler + AgentLoop + JobService extracted into a new Docker container `archie_scheduler` running `platform_v2/scheduler_daemon.py`. Same image as platform; imports `app:app` and gates side effects with `ARCHIE_RUN_SCHEDULER` (default `"1"`) + `ARCHIE_RUN_TELEGRAM` (default `"1"`) — sidecar sets the latter to `"0"` so Telegram bot stays in platform. Singleton enforced via `pg_advisory_lock(0x4152434843484544)` in `scheduler_daemon.py`. Migration 367 added `scheduler_heartbeat` table; new agent_loop job `_write_scheduler_heartbeat` writes `{hostname, ts, running, jobs_total, next_run_ts, details(jobs JSON)}` every 30s, prunes >24h. New `services/scheduler_health.py` (`read_status()`, `get_jobs()`, `is_running()`) — HTTP routes that previously read `app.config["AGENT_LOOP"]` / `["CONSCIOUSNESS_SCHEDULER"]` fall back here when in-process objects are `None` (4 sites in `dispatch_routes.py`, 1 in `consciousness/routes.py`). Stale threshold 90s. (3) Platform gunicorn bumped `--workers 1 → 4`, `mem_limit 4g → 8g` — safe because only the sidecar holds the singleton lock; workers cannot fire jobs. Telegram fcntl lock is already worker-safe (LOCK_NB; first worker wins). (4) `qa_spec_runner` `_run_api_test` and `_run_page_load_test` now read `test.get("timeout_ms", 30000)` and divide by 1000 — opt-in per-test timeout override for LLM-backed routes (faith devotional bumped to 120000ms in migration 368, idempotent). Activation steps in `~/.claude/projects/-mnt-archie-brain/memory/project_session-handoff.md`. KB #262314–#262321.
- **K.I.N. × C.R.E.E.D. welfare pipeline (PR #462, 2026-05-01)**: `_run_kin_welfare_digest` in agent_loop.py now 4-phase LLM pipeline: collect → K.I.N. assess (capability='welfare') → autonomous actions (rest/cooldown/barracks/workload_cap logged to governance_audit_log) → C.R.E.E.D. file (event_category='welfare_ethics') + A.R.C.H.I.E. Telegram report. 16 tests. KB #261709.
- **CAPABILITY_DEPARTMENT_MAP (PR #460, 2026-05-01)**: 55 new entries; S.H.I.E.L.D. skill fixed (hyphen bug → "security"/"security_review"/"vulnerability_scan"). Migration 366 applied.
- **Duplicate endpoint fix (2026-05-01 hotfix)**: `social_routes.py` had duplicate `api_signal_themes` + `api_signal_calendar`. Fixed + idempotency guard added to `register_theme_routes` (`_theme_routes_registered` flag).
- **Gaps**: 3 sibling tables not yet agent_service-owned (agent_skills/budgets/creation_events — #2057); 18 legacy ai_bridge.* imports remain (#2058); 5 dispatch_routes stubs (Project #243); MissionManager coupling; CAPABILITY_TAXONOMY hardcoded in smart_router; `bridge_jobs` may not persist LLM responses for dispatcher path (unverified — noted in #276 handoff).

### Consciousness — `consciousness` · `/tools/consciousness` · ✅ · 🟢
- **Capability**: 5 tabs + Dev HQ subtabs + Code Health. Owns `knowledge_base` (25,874 entries, 99.1% embedded). Embedding/Analysis/Translate/GitHub-ingest loops. 129 routes, 314+ endpoints, 62+ async jobs.
- **Integrations**: MCP `store_memory`/`search_knowledge`/`recall_context`/`create_task`/`log_decision`; Repair Bay Code Health (one-way).
- **Audit**: KB 256840 (2026-04-17) · **Rules**: `consciousness.md`, `project-knowledge.md`

### A.R.C.H.I.E. Chat — `archie_chat` · `/tools/archie-chat` · ✅ · 🟡
- **Capability**: Text messaging (Claude-routed or Telegram-bridged), conversation CRUD, agent roster, bridge stations, API key mgmt, Home Assistant voice synth w/ ARCHIE emotional tone. ~1,640 LOC across routes + chat_service + ha_bridge + auth_middleware.
- **Tables**: conversations, messages (source=ha_voice/telegram/web), api_keys, agent_assignments
- **API key scopes (2026-05-02, #2259)**: `require_scope()` decorator in auth_middleware.py enforces per-endpoint scopes for bearer-token callers: `chat` (POST /message, POST/DELETE /conversations), `read` (GET lists/search/agents), `admin` (key CRUD). Session users bypass scope checks.
- **Gaps**: Telegram via external `archie_comms` container (:3002); **STT (voice input) missing**; team convo scoping partial.
- **Audit**: KB 256846 · **Rules**: `autonomy.md`

### Repair Bay — `repair_bay` · `/tools/repair-bay` · ✅ · 🟡
- **Capability**: Scan→Proposal→Sandbox→Deploy (manual) self-healing pipeline. 8 tabs: Reviews, PR Review, Repairs, Diagnose, Test Bay, **Ship**, QA, Pushes + ENGINEERING station. 10 route files, ~2,849 LOC. Critical/high=immediate proposal; medium=Sunday 02:00 batch. SandboxManager (Docker or schema-separation).
- **Ship tab** (2026-04-30): Website sub-tab added alongside Ready/History/F.O.R.G.E. sub-tabs. `GET /api/deploy/website-status` returns last deploy time, status, pending portrait count per domain. `POST /api/deploy/website-trigger` triggers immediate full-site Hostinger deploy in background thread. Results stored in `system_config` keys `website_deploy_last_run_<domain>` + `website_deploy_last_status_<domain>`.
- **Audit**: KB 256838 (2026-04-17) · **Rules**: `repair-bay.md`
- **Gaps**: `_has_open_proposal()` dedup not visible; 6h scheduler wiring unclear; one-way Consciousness flow.
- **Hostinger deploy — CRITICAL (fixed 2026-05-01, PR #447–448)**: `POST /api/hosting/v1/websites/{username}/deploy` → 404 (endpoint does not exist). `deploy_service.py` now marks `deploy_pending` in system_config instead. **Only working deploy path: `/deploy-website` skill** using `mcp__hostinger-api__hosting_deployStaticWebsite`. Never try raw HTTP to Hostinger deploy API. KB #261679 #261681.
- **Portrait :rw mounts (PR #448)**: `docker-compose.yml` now has `:rw` for `kytranempowerment.com/assets/portraits` and `creed-ai.org/assets/portraits`. Required `docker compose up -d` (not restart) to apply.
- **P.R.O.B.E. perf baselines + post-deploy gate (2026-05-04, PRs #519/#521, ADR-001 / Decision #560)**: Historical p95 perf baselines for every YAML test (api/page_load/e2e); post-deploy regression gate auto-rolls back critical regressions and pauses the sandbox queue on non-critical 2-of-3. Service: `services/qa_baseline_service.py` (compute_baseline, check_regression, decide_action, evaluate_post_deploy, recompute_all_baselines). Tables: `qa_perf_baselines`, `qa_perf_regressions`, `qa_perf_acceptances` (migration 369 + 370). Hook A: `qa_spec_runner.execute_spec` propagates `result["perf_flags"]` from `extract_perf_flags(test)`. Hook B: `qa_service.run_suite` writes `qa_perf_regressions` after the per-test INSERT on trip. Hook C: `proposal_service._evaluate_perf_gate` daemon — strongest action wins (rollback>pause>flag>none) using AutoRollbackManager + Telegram. Hook D: `sandbox_queue` honours `system_config.deploy_paused_perf` flag via new `_is_deploy_paused_for_perf()` helper. Job #59: nightly `daily_recompute_perf_baselines` at 03:45 EDT in `tools/department_hq/jobs.py`. **Endpoints (all under `/tools/repair-bay/`)**: `GET /api/qa/baselines` · `GET /api/qa/regressions[?status=pending|cleared|accepted]` · `POST /api/qa/regressions/<id>/clear` (auto-lifts pause when last pending row clears) · `POST /api/qa/regressions/<id>/accept` (records `qa_perf_acceptances` + immediate baseline recompute). YAML: opt-in `critical: bool` and `baseline_ms_override: int` per test. Constants: MIN_SAMPLES=10, WINDOW_SIZE=30, TRIP_THRESHOLD_PCT=200, PAUSE_THRESHOLD=2, CLEAR_COOLDOWN_HOURS=24. **30-day soak built in** — gate dormant during ramp. Tests: 26 (`test_qa_baseline_service.py` 18 unit, `test_qa_baseline_routes.py` 4 endpoint, `test_perf_gate_integration.py` 4 integration).
- **Scheduler sidecar mount parity (2026-05-04, PRs #520/#522/#525)**: PR #511's Path C extracted APScheduler into `archie_scheduler` with a hand-curated volumes list — silently dropped Code Health by ~35% files / ~18% lines because `/mnt/standalone:ro` was missing. Fixed in 3 PRs: #520 added `/mnt/standalone`; #522 added `/mnt/Plex/config:ro`, `/mnt/llm_drive/ollama/models:ro`, `./credentials:rw`, `./platform_v2/static/screenshots:rw`; #525 added `./archie-comms`, `./what-the-fact`, `./standalone/media_hub` (3 hub-resident standalones outside `/mnt/standalone/`). Both `archie_platform` and `archie_scheduler` now see 11/11 standalones (2,467 files / 707,579 lines). KB mistake_learned #263303. **Rule for future Path-style extractions: any new sidecar that runs the same image MUST mirror the platform volumes block exactly. Drift = silent degradation of scheduled jobs.**

### Agent Academy — `agent_academy` · `/tools/agent-academy` · ✅ · 🟡 (3/5)
- **Capability**: 5 tabs — Benchmarks, Training, A/B Testing, Skills, Reports. Lv1–5 proficiency (Lv4 unlocks cloud). 16 routes. `agent_benchmark_results`, `agent_competency_scores`, `agent_learning_records`, `v_department_readiness`.
- **Audit**: KB 256839 (2026-04-17)
- **Gaps**: A/B variant tracking implicit only; Reports endpoints missing; training automation disabled; Lv4 cloud-unlock not C.R.E.E.D. gated; CAPABILITY_TAXONOMY hardcoded in smart_router

### Automations — `automations` · `/tools/automations` · ⛔
- **Status**: Disabled. Scope unclear.

---

## saas_services (9)

### Email Manager — `email_manager` · `/tools/email-manager` · ✅ · 🟢
- **Capability** (PR #597, 2026-05-11): **Three-panel command center** — Sidebar (220px, folder nav + unread badges), Message List (280px, paginated + search), Read Pane (flex, DOMPurify HTML render, thread toggle, Draft Reply). 49 mailboxes (38 AI + 10 business + 1 owner). IMAP sync 5 min, AI triage on ingest, rules engine first-match-wins.
- **Features**: Phase 5 agent auto-reply drafts (R.E.S.O.L.V.E., capability=support), Phase 6 rules engine (5 ops: set_priority/archive/star/skip_triage/mark_read), Phase 7 threading (In-Reply-To+References), Phase 8 R.E.S.O.L.V.E. chat overlay (red #ef4444, live briefing).
- **Tables**: `email_mailboxes`, `email_messages` (use `imap_uid` NOT `uid`, has `attachment_count`, `ai_priority`, `thread_id`, `in_reply_to`, `references_header`), `email_threads`, `email_rules` (mailbox_id, condition_op, action_type), `email_activity_log`.
- **Service files**: `email_parser.py`, `sync_jobs.py`, `triage_service.py`, `rules_service.py`, `thread_service.py`, `email_hq_briefing.py`, `messages_routes.py` (14 endpoints), `rules_routes.py`.
- **CRITICAL — Stalwart**: Use `http://stalwart_mail:8080` (plain HTTP, Docker internal). `stalwart_mail` must be in `archie_network`. Never `https://192.168.1.200:8443` — hairpin NAT blocks TLS from containers.
- **Owner mailbox**: `POST /api/email/mailboxes/provision-owner` → `kytran@kytranempowerment.com` 10GB (409 = update password fallback).
- **Chat overlay**: `static/js/email-manager-chat.js`, module_key=`email_manager` routes to `email_hq_briefing.py` in `api_routes.py`.
- **KB Docs**: #265260 (user-doc) · #265261 (coder-doc) · Migrations 375–378 · PRs: #297/#299/#321 (phases 1–3) + **#597** (phases 4–8, full redesign).

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

### SaaS Manager — `saas_manager` · `/tools/saas-manager` · ✅ · 🟡
- **Capability**: Organization (tenant) CRUD, per-org module enable/disable, custom domain verify (DNS TXT), port accessibility check, public IP detection, node assignment. 761 LOC routes + domain_service + ip_monitor.
- **Tables**: `organizations`, `org_users`, `org_modules`, `org_domains`, `org_nodes`
- **Note**: `show_on_dashboard=False` — functionality folded into Account Center ORGS tab. Admin-only (`minimum_role="ADMIN"`). No chat overlay (hidden module).
- **Gaps**: **No subscription_level binding on org_modules — blocks #2018 KBS plugin tier gating**. DNS update not exposed. Node assignment UI minimal.
- **Audit**: KB 256846 · **Rules**: `saas-services.md`
- **Active**: #2018 subscription gating (P10 large)

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
- **Variant provenance badges** (2026-05-16, PR #765 commit `0fd4fb7a`): variant tiles show GPU label (bottom-left, e.g., "RTX 3070" / "Quadro M4000") + model name (bottom-right, e.g., "RealVisXL" / "SDXL Turbo"). `portrait_service.get_agent_portrait` LEFT JOINs `media_generation_queue` to surface `params.model` + `params.fleet_node`. `generate_via_comfyui` persists `fleet_node` into queue.params on dispatch.
- **Fleet ComfyUI reliability** (2026-05-16, PR #765): pre-dispatch `/system_stats` ping dropped (was timing out under SDXL inference load, causing false hub fallbacks); trusts `remote_nodes.last_heartbeat` instead. Cold-load poll timeout 360s → 600s for sd_xl_base on RTX 3070. On fleet timeout: fail-loud (reaper retries every 10min) instead of silent hub fallback.
- **Unified image provider selector** (2026-05-16, PR #766, ADR-005): both `#ms-canonical-model` and `#ms-variant-model` dropdowns dynamically populated from `GET /tools/media-studio/api/image-providers`. Returns `{auto, local[], cloud_free[], cloud_paid[]}` — 6 local checkpoints from disk + active contractors from `contractor_providers WHERE capabilities ? 'image_gen'`. UI uses `<optgroup>`s for Local / Cloud Free / Cloud Paid. Selector value format: bare filename for local (backward compat), `provider:<key>` for contractor (e.g., `provider:openai`, `provider:pollinations`).
- **Cloud contractor dispatch** (2026-05-16, PR #766 commit `e1298506`): `submit_generation` returns pending for ALL image media_type. `media_generation_worker` claims all pending image jobs (no provider filter). `generate_via_comfyui` branches early to `_generate_via_contractor(queue_id, queue_row, params, provider_key)` when `params.provider` is set — calls `ai_bridge.external_providers.generate_media(provider_key, request)`. 6 adapters live today: openai (DALL-E 3), gemini (Imagen 3), huggingface, cloudflare_ai, together, pollinations. 3 providers registered but no adapter yet: replicate, fal_ai, stability_ai (task #2940). Pollinations end-to-end verified (free, no auth, ~30s).
- **Cost ledger** (2026-05-16, PR #773): `_log_image_contractor_usage()` in `generation_service.py` writes to `cloud_model_usage` from BOTH success + failure paths of `_generate_via_contractor`. Attribution via `queue_row.owner_type/owner_id` → `user_id`/`agent_id`. `task_type='image_generation'`. Free providers still get rows (cost=0) for provider-mix analytics. Verified live: Pollinations queue #243 → ledger row #7523.
- **Dropdown needs_key UX** (2026-05-16, PR #774): `get_image_providers()` JOINs `external_api_keys` to compute `needs_key` per cloud entry — true when paid AND no active key. Frontend `_msBuildOptgroup` marks `needs_key=true` options as `disabled` with tooltip "Add an API key in Department HQ → Contractors". Free providers (Pollinations/Cloudflare/Together) always selectable. Gemini selectable (has key). OpenAI/HuggingFace/Replicate/Fal.ai/Stability disabled until key added.
- **Per-provider model picker** (2026-05-16, PR #775): new `PROVIDER_MODELS` catalog (9 providers × 1-4 models) in `generation_service.py`. `get_image_providers()` returns `models[]` + `default_model` per cloud entry. Frontend `updateProviderModelPicker(providerSelId, modelPickerId)` shows secondary `<select>` when a `provider:*` option is chosen, default-selects entry.default_model. `portrait_service._parse_provider_or_model(value, model_override=None)` — override wins over PROVIDER_DEFAULT_MODEL for provider selections. `generate_variant`/`generate_fanout` accept `model_override` kwarg. Routes plumb `data.get('model_override')` from request body. **Adapter fixes shipped same PR**: OpenAI + Gemini image adapters now honor `params.model` (were hardcoded). All 6 image adapters now respect picker selection.
- **Tables**: media_generation_queue (now `params->>provider`, `params->>fleet_node`), media_gallery, media_tags, media_collections, media_smart_collections, media_analytics, agent_portraits (UNIQUE(agent_id)), contractor_providers (image_gen capability), **cloud_model_usage (now populated for image gen, PR #773)**.
- **Active v2 tasks**: #2940 (Replicate/Fal.ai/Stability adapters — still pending, needs API keys). #2941 ✅ COMPLETE (PR #773). #2942 ✅ COMPLETE (PR #775).
- **Audit**: KB 256846 · KB #266418 (cost ledger coder ref) · KB #266419 (provider UX user ref) · KB #266420 (provider UX coder ref) · **Rules**: `creative-studios.md`

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
- **Deployment**: Hub, port 8085, server.kytranempowerment.com | Container: kytran-system-operations
- **Source**: `/mnt/archie_brain/kytran-server-manager/` (gitignored from archie_brain, no separate git repo)
- **Capability**: Compliance engine (STIG/HIPAA/CIS), host_monitor.py bridge, 1-click remediation. 9 tabs: Dashboard | Storage | Hardware | Memory | Processes | Docker | Network | Firewall | Compliance
- **LCARS**: Red (#ef4444) — full treatment applied 2026-05-09. Dark-only (Kytran theme, no separate light mode).
- **Chat overlay**: `kso-chat.js` → **B.A.S.E.** #139 (Operations & Infrastructure director), red `#ef4444`. Live briefing from `/data/host_monitor_data.json` (CPU/RAM/disk/services/uptime + compliance score). 5 action types: run_compliance_scan, check_services, check_docker, refresh_system_data, check_health_alerts.
- **Chat proxy**: `routes/chat_proxy_routes.py` — proxies `/tools/archie-chat/api/` → hub (http://192.168.1.200:3000). Portrait via `/api/public/directory`. Env: `KSO_CHAT_API_KEY`, `KSO_ARCHIE_HUB_URL`.
- **Code Health**: IN REPAIR (13 repairs) | 100 files | 45,483 LOC | scanned 2026-05-09
- **Pip-install architecture**: Source loads from site-packages NOT /app/ — hot-patches need BOTH `/app/kytran_system_operations/` AND `/usr/local/lib/python3.12/site-packages/kytran_system_operations/`. Rebuild with `docker compose build + up -d --no-deps`.
- **Back arrow**: → https://platform.kytranempowerment.com
- **KB Docs**: #264475 (full audit 2026-05-09) · **Rules**: `standalone-extraction.md`

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
- **WTF freemium paywall (PR #466, 2026-05-01)**: Kytran OAuth SSO added to consumer (`consumer/auth.py`). Bias band free; rationale+trigger phrases+V.E.R.I.F.Y. panel+Deep Dive gated behind Starter+. `/login` → platform OAuth → `/auth/callback` → Flask session `{wtf_username, wtf_tier, wtf_authenticated}`. OAuth client `wtf-consumer` registered in platform DB. **VPS deploy required**: `docker compose build wtf-consumer && docker compose up -d wtf-consumer` + add `WTF_CLIENT_SECRET=wtf_cs_k7mxp2r9q4n8v1j6` + `FLASK_SECRET_KEY=<random>` to VPS .env. KB #261707.
- **OAuth token now includes subscription_tier (PR #466)**: `platform_v2/oauth_provider.py` — all OAuth clients receive `user.subscription_tier` in token response + `tier` claim in JWT. Fetches from `users.subscription_tier` in platform DB.
- **WTF Hub LCARS template (PR #652, 2026-05-12)**: `tools/wtf_hub/routes.py` was using `render_template_string()` — no nav bar, no category color. Created `templates/tools/wtf_hub.html` extending base.html with teal `#00ffff` accent, full 7-module ai_command header_shortcuts nav, LCARS frame structure. Routes.py updated: `render_template_string → render_template('tools/wtf_hub.html', interval=...)`. KB #265603.

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
