# Sub-C: ARCHIE Delegation in Chat — Design Spec
**Project**: #288 ARCHIE Command Center
**Task**: #2351
**Date**: 2026-04-27
**Status**: Approved by user

---

## Overview

Wire the existing platform delegation surface (Project #276, complete) into the
archie.kytranempowerment.com chat UI. Users can ask ARCHIE in natural language to
delegate tasks to agents, or use an explicit `/delegate` command. Delegation cards
appear in the message thread and poll for results.

**What already exists:**
- `delegate_task_worker` APScheduler job (30s) picks up `unified_tasks` rows where
  `delegation_source IS NOT NULL`, dispatches via `department_dispatcher.dispatch()`,
  writes results to `work_notes`, flips `status` to `completed`/`blocked`
- Known-tool shortcuts bypass LLM: `run_qa_suite`, `check_dep_drift`, `health_check`,
  `check_platform_health`, `run_misroute_audit`, `run_misroute_to_proposal_adapter`
- `unified_tasks` table has: `id, title, description, status, priority,
  delegation_source, delegation_args (JSON), streaming_channel, work_notes`

**What Sub-C adds:**
- Platform HTTP endpoints so archie_comms can submit and poll delegations
- `{{DELEGATE}}` marker detection in `stream_send_message`
- `/delegate` command shortcut in the chat input
- Delegation cards in the message thread with live status polling

---

## Architecture

### New Platform Endpoints (platform_v2)

Two new routes added to `platform_v2/app.py` (or a new `delegation_api.py` blueprint),
protected by `INTERNAL_API_KEY` bearer token:

```
POST /api/internal/delegation/submit
  Headers: Authorization: Bearer <INTERNAL_API_KEY>
  Body: { capability, reason, args={}, priority=5, requested_by="web_chat" }
  Response: { task_id, status: "queued", capability, reason }

GET /api/internal/delegation/<task_id>/status
  Headers: Authorization: Bearer <INTERNAL_API_KEY>
  Response: { task_id, status, capability, work_notes, agent_name, created_at, updated_at }
```

`submit` inserts directly into `unified_tasks` with `delegation_source='web_chat'` —
same path the MCP tool uses. No new service layer needed.

### Auth

New env var `INTERNAL_API_KEY` (shared secret, in both `.env` files). Simple bearer
token check in the two new platform routes. archie_comms reads it from env and includes
it in every call to the platform delegation endpoints.

The platform URL in archie_comms: `PLATFORM_INTERNAL_URL=http://192.168.1.200:3000`
(internal network — never goes through NPM/internet).

### New archie_comms Routes

```
POST /api/delegation/submit
  (auth: session cookie, user_id required)
  Body: { capability, reason, args={} }
  → POSTs to platform /api/internal/delegation/submit
  → Returns: { task_id, status, capability, reason }

GET /api/delegation/<task_id>/status
  (auth: session cookie)
  → GETs platform /api/internal/delegation/<task_id>/status
  → Returns same payload (thin proxy)
```

---

## Natural Language Detection

### System prompt injection

`stream_send_message` prepends a delegation instruction to ARCHIE's system prompt:

```
[DELEGATION] When the user explicitly asks you to delegate a task to an agent or the
platform, include this marker in your response (anywhere in the text):
{{DELEGATE capability="X" reason="Y"}}

Valid capabilities: code_review, health_check, run_qa_suite, documentation,
analyze, check_dep_drift, run_misroute_audit, summarize, research, security.

Example: If the user says "ask F.O.R.G.E. to review the dispatch code", respond
naturally AND include: {{DELEGATE capability="code_review" reason="review dispatch
routing code for gaps"}}

Only include {{DELEGATE}} when the user explicitly asks you to delegate. Never
include it for regular conversation.
```

### Marker stripping + delegation fire

`stream_send_message` accumulates tokens in `full_parts`. After the stream ends,
it scans the complete response for `{{DELEGATE ...}}` with a regex. For each match:

1. Strips the marker from the stored message (user sees clean prose)
2. Calls `POST /api/delegation/submit` on archie_comms (internal call)
3. Yields a new SSE event: `{"type": "delegation_queued", "task_id": N,
   "capability": "X", "reason": "Y"}`

The marker is stripped from `complete_text` before `save_message` — it never
persists to the DB.

---

## `/delegate` Command

Frontend (`archie-chat.js`) intercepts input that starts with `/delegate` before
sending to ARCHIE. Parses the rest as `capability=X reason="Y"` (key=value) or
falls back to keyword heuristic: scan text for known terms and map to capability,
use full text as reason. Keyword map (first match wins):
`health`/`healthy`/`vps` → `health_check` | `qa`/`test`/`suite` → `run_qa_suite` |
`dep`/`drift`/`dependency` → `check_dep_drift` | `review`/`code`/`forge` → `code_review` |
`misroute`/`route` → `run_misroute_audit` | anything else → `general`.

Parse examples:
- `/delegate capability=health_check reason="VPS is showing errors"` → structured key=value parse
- `/delegate check if the QA suite is passing` → keyword `qa` → `run_qa_suite`, full text as reason
- `/delegate ask F.O.R.G.E. to review dispatch` → keyword `forge`+`review` → `code_review`
- `/delegate something unusual` → no keyword match → capability=`general`, full text as reason

The frontend calls `POST /api/delegation/submit` directly (bypasses ARCHIE's LLM).
Then injects a system message into the chat: *"Delegating `capability` to agent..."*
followed immediately by a delegation card.

---

## Delegation Card UI

### Card structure (rendered by `DelegationCard` JS class)

```
┌──────────────────────────────────────────────────────────┐
│  ⟳  code_review  ·  F.O.R.G.E.  ·  pending              │
│  "Review dispatch routing code for gaps"                  │
└──────────────────────────────────────────────────────────┘
```

On completion:
```
┌──────────────────────────────────────────────────────────┐
│  ✓  code_review  ·  F.O.R.G.E.  ·  done  [2m 14s]       │
│  "Found 3 misroute candidates in smart_router.py..."     │
│                                   [Show full result]      │
└──────────────────────────────────────────────────────────┘
```

On failure/blocked:
```
┌──────────────────────────────────────────────────────────┐
│  ✗  code_review  ·  unknown  ·  blocked                  │
│  "No agent available for capability: code_review"        │
└──────────────────────────────────────────────────────────┘
```

### Polling behaviour

`DelegationCard.startPolling()` calls `GET /api/delegation/<task_id>/status`
every 5 seconds. Stops when status is `completed`, `blocked`, or `failed`.
Max 20 polls (100s timeout) — after which shows "Timed out — check Dev HQ".

Cards are inserted into the message list as regular DOM elements. They are NOT
persisted to `unified_messages` (they're ephemeral UI — the task record in
`unified_tasks` is the source of truth). On page reload, pending cards are lost
but completed tasks remain queryable via Dev HQ.

---

## Components Touched

| File | Change |
|------|--------|
| `platform_v2/app.py` (or new `delegation_api.py`) | `POST /api/internal/delegation/submit`, `GET /api/internal/delegation/<id>/status` |
| `platform_v2/.env` | Add `INTERNAL_API_KEY=<generate with: python3 -c "import secrets; print(secrets.token_urlsafe(32))">` |
| `archie-comms/.env` | Add same `INTERNAL_API_KEY` value, `PLATFORM_INTERNAL_URL=http://192.168.1.200:3000` |
| `archie-comms/app_comms.py` | `POST /api/delegation/submit`, `GET /api/delegation/<id>/status` |
| `archie-comms/services/conversation_service.py` | Inject delegation system prompt; strip `{{DELEGATE}}` markers; yield `delegation_queued` events |
| `archie-comms/static/js/archie-chat.js` | `DelegationCard` class; `/delegate` command intercept in `doSend`; handle `delegation_queued` SSE event in `MessageStream` |
| `archie-comms/static/css/archie-chat.css` | `.ac-delegation-card` styles (pending/done/blocked states) |
| `archie-comms/tests/test_chat_overhaul.py` | Tests for marker stripping, delegation proxy route |

---

## What This Does NOT Include

- Persisting delegation cards across page reloads (Sub-E concern — full Dev HQ integration)
- ARCHIE proactively delegating without user asking (future autonomy feature)
- Delegation to specific named agents by name ("ask Nexus to...") — capability-based routing only
- Multi-step delegation chains (one delegation per message)

---

## Success Criteria

1. Type "ARCHIE can you ask F.O.R.G.E. to do a health check" → ARCHIE responds naturally AND a delegation card appears showing `health_check · pending`
2. Card updates to `done` within 30-60s with result from `work_notes`
3. Type `/delegate capability=run_qa_suite reason="check all suites"` → delegation card appears immediately without ARCHIE's LLM being invoked
4. `/delegate check if the platform is healthy` → heuristic maps to `health_check`, card appears
5. `{{DELEGATE}}` marker never visible in ARCHIE's chat response
6. Delegation card shows on page (no persisted to DB — ephemeral)
7. No regression to Sub-A or Sub-B features
