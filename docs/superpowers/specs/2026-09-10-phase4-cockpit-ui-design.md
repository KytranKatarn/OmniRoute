# Phase 4 — Cockpit UI (Crew + Code Builder) — design spec

**Date:** 2026-09-10 · **Program:** master-command (build order 0–6), step **4** · **Owner decisions:** #1094 (one master command interface), #1099 (build order) · **Predecessors live on `main`:** Phase 2 `agents:manage` API (#3270), Phase 3a coding lane + served-model attribution (#3271–#3274, ADR-040) · **Mockups reviewed by the owner:** https://claude.ai/code/artifact/6b727716-96f8-4a44-a6fd-bbee1a5bcecb

## 1. What this builds

A new page in **archie-comms** — `GET /cockpit` at archie.kytranempowerment.com — with two panes, **Crew** and **Code Builder**, and the existing approvals rail. From a phone or a desktop the owner can list the crew, open an agent, add/remove skills, set a daily token budget, reassign a department, change shift state, propose a hire (Tier-2), run a cloud coding job through the ask-first lane, approve it, and read the result.

**First slice only.** Tasks & projects (needs new hub APIs) → Phase 4b. "Apply via engine" / automatic PRs for builder output → Phase 4b. TTY lanes → Phase 5.

### Owner decisions taken during brainstorming (2026-09-10)
| # | Question | Decision |
|---|---|---|
| Q1 | First slice scope | **Crew + Contractors** (the two with backend ready) |
| Q2 | Form factor | **Both equally** — two deliberate layouts, same components |
| Q3 | Builder result | **Show the result; the owner applies it** — nothing touches a repo in this slice |
| Q4 | Where it lives | **B: separate `/cockpit` page in archie-comms** (own template/JS/CSS; chat page untouched except a nav link) |
| S4 | Layouts | Phone: bottom tabs Crew · Builder · Approvals, agent card as a full-screen sheet. Desktop: three panes 320 · flexible · 400 with approvals as a **strip** under the header. Builder shows the answer with Copy. Decommission = typed-name confirm. Hire always Tier-2. |

## 2. Architecture

```
browser ──(comms session)──▶ archie-comms  ──(Bearer INTERNAL_API_KEY / per-caller key)──▶ hub /api/internal/*
                             /cockpit page          services/cockpit_proxy.py                 agent_service · bridge_jobs · approvals
```

- **archie-comms** (image-baked, container `archie_comms`, separate hardened surface per #1094): new route `GET /cockpit` gated exactly like `/` (`app_comms.py:641 index()` — same session check), template `templates/cockpit.html`, `static/js/cockpit.js`, `static/css/cockpit.css`. Reuses: the comms header (`static/js/lcars-header.js`), the approvals proxy (`services/approvals_proxy.py`: `list_pending()`, `approve(approval_id, user_id)`, `deny(approval_id, user_id, reason)`), comms' chat stylesheet (`static/css/archie-chat.css` — `--ac-*` tokens such as `--ac-accent-cyan: #00ffff`, IBM Plex Mono) for the shared header only; `cockpit.css` sets its own palette as literals (`#00d4ff` accent on `#0a0a1a`) and does not read those tokens. New `services/cockpit_proxy.py` wraps the hub calls below; local routes under `/api/cockpit/*` are session-gated.
- **Hub (platform_v2, bind-mounted):** one new scope, four new read endpoints (§3.1), five new single-reader helpers in `agent_service` (`list_roster`, `roster_facets`, `get_agent_skills`, `get_agent_budget`, `get_agent_recent_work`). No new write paths — the six Phase 2 writes and the Phase 3a run/poll are consumed as they are.
- **Deleted:** comms' direct-SQL roster peek `_fetch_agent_status()` (`app_comms.py`, feeds `/api/status`) — replaced by the new hub read. Comms keeps no DB access for agent data.

## 3. API contract

### 3.1 Hub additions (platform_v2/app.py + services/internal_auth.py + services/agent_service.py)

**Scope.** Add `"agents:read"` to `SCOPES` (`internal_auth.py:72`) and to the `archie_comms` entry of `CALLER_SCOPES` (`:93`, beside `agents:manage` at `:104`). No other caller gets it. The scope-completeness test (`tests/test_internal_auth_scopes.py`) auto-covers the new routes.

**Endpoints** (all `@require_internal_scope("agents:read")` unless noted; JSON; errors `{"error": "<text>"}`):

1. `GET /api/internal/agents?q=&department=&state=&worker_type=&limit=50&offset=0`
   → `{"agents":[{id, name, display_name, department, shift_state, worker_type, model, title, is_department_ai, performance_score, success_rate, last_used}], "total": N, "facets": {"departments": {"<name>": count}, "states": {"<state>": count}}}`.
   Backed by two new single-reader helpers `agent_service.list_roster(...)` (rows + total, shaped after `list_agents_public`) and `agent_service.roster_facets(...)` (department/state counts); `list_agents` itself is untouched. Default excludes `decommissioned` unless `state=decommissioned`. `limit` max 200.
2. `GET /api/internal/agents/<int:agent_id>`
   → `{"agent": {…as above + bio, first_name, last_name, email, created_at}, "skills": [{skill_name, skill_category, proficiency_level, can_escalate_to}], "budget": {token_limit_per_day, tokens_used_today, task_queue_limit, current_task_count, token_reset_at} | null, "recent_work": [{id, capability, model_used, provider, success, duration_ms, created_at}] (last 5 from task_execution_log)}`.
   Backed by `agent_service.get_agent(agent_id)` (`:121`) plus **three new single-reader helpers** `agent_service.get_agent_skills(agent_id)`, `agent_service.get_agent_budget(agent_id)` and `agent_service.get_agent_recent_work(agent_id, limit=5)` (reads only — five new readers in total with the two roster helpers above; the writes stay `add_skill`/`remove_skill`/`set_token_budget`). 404 when the agent does not exist.
3. `GET /api/internal/cloud-code/runs?limit=20` (`cloud:code`)
   → `{"runs": [{job_id, status, model, provider, created_at, completed_at, result: {model_used, served_model_resolved, prompt_tokens, completion_tokens, error} | null}]}` — the caller's `bridge_jobs` rows with `job_type='cloud_code'`, newest first, `limit` max 100. Prompt text is NOT included in the list (the detail route has it).
4. `GET /api/internal/cloud-code/providers` (`cloud:code`)
   → `{"providers": [{provider_key, display_name, default_model, models: [<model name string>, …], is_active}]}` read directly from the `contractor_providers` table (`capabilities ? 'text_chat'`, active, not a cloud proxy — the same rows `external_providers.get_providers_with_capability` returns; the hub route mirrors the cloud-code status route's direct read, the one raw-SQL exception the plan allows in `app.py`); the cockpit never calls OmniRoute directly.

**Consumed unchanged** (Phase 2, `agents:manage`): `POST /api/internal/agents/create` (Tier-2 via `propose_hire`), `POST /api/internal/agents/<id>/assign` (`department` only), `POST …/shift-state` (`state` ∈ `VALID_SHIFT_STATES` (`agent_service.py:43`) + `reason`; `decommissioned` terminal), `POST …/skills/add`, `POST …/skills/remove`, `POST …/budget` (floor 50k enforced server-side). (Phase 3a, `cloud:code`): `POST /api/internal/cloud-code/run` (202 `{job_id, approval_id, status:'pending_approval'}`; 409 allowlist refusal or `approval_unavailable`; 404 provider; 400 missing prompt) and `GET /api/internal/cloud-code/run/<int:job_id>`. (Line numbers deliberately omitted — they shift with every insertion; locate each route by its path.) Approvals: `GET /api/internal/approvals/pending`, `POST /api/internal/approvals/autonomy:<id>/approve|deny` — the id is **source-prefixed** (a bare id 500s today, #6666).

### 3.2 Comms proxies (`archie-comms/services/cockpit_proxy.py`) and local routes (`app_comms.py`)

Every proxy: `Authorization: Bearer <INTERNAL_API_KEY or the per-caller key comms already uses>`, timeouts **15 s reads / 30 s writes**, fail-closed (a missing key → 503 `{"error":"comms is not configured to reach the hub"}`), and the hub's status code + `error` text passed through verbatim.

| Local route (session-gated) | Hub call |
|---|---|
| `GET /api/cockpit/agents?…` | `GET /api/internal/agents?…` |
| `GET /api/cockpit/agents/<id>` | `GET /api/internal/agents/<id>` |
| `POST /api/cockpit/agents/create` | `POST /api/internal/agents/create` |
| `POST /api/cockpit/agents/<id>/{assign,shift-state,skills/add,skills/remove,budget}` | the matching Phase 2 write |
| `GET /api/cockpit/build/providers` | `GET /api/internal/cloud-code/providers` |
| `POST /api/cockpit/build/run` | `POST /api/internal/cloud-code/run` |
| `GET /api/cockpit/build/<id>` | `GET /api/internal/cloud-code/run/<id>` |
| `GET /api/cockpit/build/runs` | `GET /api/internal/cloud-code/runs?limit=20` |
| approvals | existing `/api/approvals/pending`, `/api/approvals/<id>/<verb>` (unchanged) |

Comms never calls Ollama, the engine, or the DB for any of this. The builder's capability is fixed to `code` by the hub (`cloud_code_lane.CAPABILITY`); comms sends no capability field.

## 4. Components

### 4.1 Crew pane
- **Roster list.** Search box (matches `name`/`display_name`, debounced 300 ms), filter chips from `facets` (departments, states; `decommissioned` off by default), worker-type chip. Cards: display name, department, **one** state pill (real class per state — never the phantom `sc-live`/`sc-static`), model, success %. Paged 50; "Load more".
- **Agent card** (phone: full-screen sheet with back; desktop: centre pane). Header: name, title, department, state pill, model. Performance: success %, score, tasks, last used. **Skills:** chips `skill_name · Lv N` with ×; "+ add" opens name / category / level (1–5). **Budget:** used-today / limit with a bar; queue current / limit; "Set limit" (number field; the hub enforces the 50k floor and the message is shown verbatim). **Actions:** Department select (options = `facets.departments`) → `assign`; Shift-state select (options = `VALID_SHIFT_STATES` minus `decommissioned`) + reason → `shift-state`; **Decommission** button → a dialog that requires typing the agent's display name exactly → `shift-state {state:'decommissioned', reason}`. **Recent work:** last 5 rows (capability · model · node/provider · ✓/✗ · age).
- **Propose a hire.** Form: name, display_name, department (select), model (text with the local model names as suggestions), capability, reason, suggested_skills (comma list). Success state: "Hire proposed — approval #N is waiting in Approvals and Telegram". The roster re-fetches when the approval executes (poll the roster every 30 s while a hire is pending).
- After any write: re-fetch the agent card; show the server's message in a toast; no optimistic updates.

### 4.2 Code Builder pane
- **Compose:** provider select (from `/build/providers`; default `omniroute`), model select (that provider's `models[]`; default its `default_model` — today `oc/big-pickle`), prompt textarea, optional system prompt (collapsed), **Run — needs your approval**. On 202: a job row appears as `pending approval` with the hint "approve it in Approvals or Telegram".
- **Jobs list:** last 20 from `/build/runs` + any created this session; states `pending approval`, `running`, `completed`, `failed`, `cancelled`. Polling: `GET /build/<id>` every **5 s** while any job is non-terminal; stops at terminal; manual Refresh.
- **Job card:** requested model → served `model_used`, `served_model_resolved` badge, prompt/completion tokens, cost, latency (from `routing_decision` when present), the answer in a `<pre>` code block (rendered with `textContent`), **Copy**. `failed` shows the worker's `error_message`. Nothing writes to any repo.
- Collision: a 409 `approval_unavailable` reads "approve or deny the pending coding job first".

### 4.3 Approvals
The existing rail component from the chat page (`ac-approvals-list`, proxied `list_pending`/`approve`/`deny`) rendered as the **Approvals tab** on phone (badge = count) and as the **strip under the header** on desktop. Rows: `cloud_code_dispatch` (job id, provider, model, prompt excerpt) and hire proposals (`create_agent`/`propose_hire` action types), each with Approve / Deny. Approving here or in Telegram is the same row; whichever comes first wins (the executor acknowledges both worker-drained types since #3273).

### 4.4 Navigation
Comms header gains **Cockpit** beside Chat / Terminal / Collaboration. Inside the cockpit: phone = bottom tab bar; desktop = the three panes always visible. `/cockpit#builder` and `/cockpit#crew` select a pane on load (the Code Builder tile links to `#builder`).

## 5. Layouts (mockups approved 2026-09-10)

- **Phone (390 px, one hand):** header (brand · back/"Chat ›"), content, bottom tab bar Crew · Builder · Approvals. Crew list → agent sheet; Builder compose above the jobs list; Approvals as full-width cards with two equal Approve/Deny buttons.
- **Desktop (≥1024 px):** header with nav; approvals strip; CSS grid `320px 1fr 400px` — roster · agent card · builder. Between 768 and 1024 px the builder pane drops below the agent card (two columns); below 768 px the phone layout applies. Breakpoints per `.claude/rules/frontend.md` (480 / 768 / 1024).
- Both layouts render the **same components** from `cockpit.js`; only `cockpit.css` differs by media query. No `innerHTML` with server data anywhere (source-scan test).

## 6. Data flow (sequences)

- **Open cockpit:** `GET /cockpit` → template → `GET /api/cockpit/agents` + `GET /api/approvals/pending` + `GET /api/cockpit/build/runs` + `GET /api/cockpit/build/providers` in parallel → render.
- **Edit skill:** tap × → `POST …/skills/remove {skill_name}` → hub `remove_skill` → 200 → re-fetch card → toast "Removed code_review".
- **Set budget:** "Set limit" → `POST …/budget {token_limit_per_day}` → hub enforces floor → 200/400 → card/toast.
- **Propose hire:** form → `POST …/agents/create` → hub `propose_hire` → 200 `{tier2:true, approval_id}` → the strip/tab shows the row → Approve (cockpit or Telegram) → executor runs the hire → roster poll shows the agent.
- **Coding job:** compose → `POST /build/run` → 202 → approval row → Approve → `cloud_code_worker` (30 s) claims, dispatches `capability='code', model_override=<model>` → job `completed` → poll shows the card with the served model.

## 7. Error handling

- Hub non-2xx → its `error` verbatim (toast + inline on the card); network/timeouts → "hub unreachable — retry"; 401/403 → "comms is not authorised for <route>" (a scope/config fault, surfaced not hidden).
- Builder: 409 allowlist → the hub's text; 409 `approval_unavailable` → "approve or deny the pending coding job first"; 404 provider → the hub's text; `failed` → `error_message`; a job past the worker's 24 h expiry shows `cancelled`.
- Crew: invalid state → the hub's valid-state list; hire dedup → the hub's text; decommission without the typed name → the dialog refuses locally (no request).
- Polling never retries a terminal job; a poll error shows once and keeps polling at the same interval.

## 8. Security and sovereignty invariants (pinned by tests)

1. Comms reaches the hub only through its scoped key; the **only new grant is `agents:read`** to `archie_comms`. No caller other than comms holds it.
2. The cockpit exposes **no setting toggle**: `escalation_mode`, the cloud capability allowlist and the Cloud master switch are unreachable from it.
3. The builder's capability is `code` server-side; every run needs a Tier-2 approval; company/civic/legal/fact-check data never rides the lane by construction (allowlist, #3256).
4. Roster reads go through `agent_service`; comms' direct-SQL peek is removed; no raw SQL in the new hub routes.
5. All server text is rendered with `textContent`; the source-scan test fails on `innerHTML` in `cockpit.js`.
6. Secrets never appear in responses or logs; the proxies pass through hub errors but never the key.

## 9. Testing and proof

- **Hub unit:** `tests/test_internal_auth_scopes.py` — `agents:read` in `SCOPES`, granted to `archie_comms` only, the four new routes covered by the completeness test; `tests/test_agents_read_api.py` — roster/detail/runs/providers shapes against `archie_test` with seeded rows (assert `total > 0` — the empty test DB passes vacuous assertions, KB mistake `pytest-live-data-is-vacuous`); 404 on unknown agent; `decommissioned` excluded by default.
- **Comms unit:** `tests/test_cockpit_proxy.py` — key passed, timeouts, fail-closed on missing key, hub error text verbatim; `tests/test_cockpit_page.py` — `/cockpit` session-gated, both panes in the template, hash routing, and the `innerHTML` source scan (pattern of `tests/test_no_direct_ollama.py`).
- **Live acceptance (hub Playwright / P.R.O.B.E.), same script at 390 px and 1280 px:** list crew → open F.O.R.G.E. → add then remove a skill (DB round-trip via `agent_skills`) → set a budget and read it back → assign a department and back → propose a hire → approve in the strip → the agent appears; run a builder job → approve → `completed` with a concrete served `model_used` and `served_model_resolved=true`; screenshots at both widths. `escalation_mode` still `local_only` afterwards.
- **F.O.R.G.E. review** on every PR; coverage demotions discharged by an independent full read (Ruling 15 pattern).

## 10. Deployment

1. Hub PR (scope + 4 reads + 2 helpers + tests) → merge → `git checkout main && git pull --ff-only` on the hub → `docker compose restart archie_platform`.
2. Comms PR (page + proxies + tests) → merge → `docker compose up -d --build archie_comms` (image-baked; a merge deploys nothing by itself).
3. Verify from inside `archie_comms`: `GET /api/internal/agents?limit=1` → 200; from the browser: `/cockpit` renders both layouts; run the acceptance script.

## 11. Follow-ups (not this slice)
- **4b:** tasks & projects panes (needs `tasks:read/write` internal APIs); "Apply via engine" on a builder result (engine `apply_edit` + approval → branch/PR); job history search.
- **Phase 5:** TTY lanes reachable from the cockpit.
- Related open items: #6672 (A/B capability select), #6666 (bare approval id 500), #6675 (OmniRoute 3b conditions before paid keys), #6664 (gateway hardening).

## 12. Global constraints for the implementation plan
- Branch + PR, never `main`; F.O.R.G.E. APPROVE before merge; never `docker compose up` while a feature branch is checked out in `/mnt/archie_brain` (bind mount); comms rebuilds with `up -d --build archie_comms`.
- No new secrets; the existing comms key is reused; `INTERNAL_KEY_LEGACY_ACCEPT` untouched.
- All inference stays behind the DHQ dispatcher (ADR-013); the cockpit never calls a model.
- Agent mutations only via `agent_service` single-writer methods; reads via new single-reader helpers.
- `textContent` only for API data; real state classes (no `sc-live`/`sc-static`); breakpoints 480/768/1024.
- Tests must be non-vacuous (seeded rows, `total > 0`); acceptance runs at 390 px and 1280 px.
