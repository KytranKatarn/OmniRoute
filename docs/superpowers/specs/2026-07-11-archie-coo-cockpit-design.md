# A.R.C.H.I.E. COO Cockpit — Design Spec

**Date:** 2026-07-11
**Status:** Approved design — ready for implementation plan(s)
**Owner:** Kytran (A.R.C.H.I.E. platform)
**Surface:** `archie.kytranempowerment.com` (the `archie_comms` cockpit)
**Decomposition:** 4 independently-shippable slices (see §7). This spec covers the whole cockpit vision; each slice gets its own implementation plan, built in order.

---

## 1. Motivation

`archie.kytranempowerment.com` should be the one place where Kytran and A.R.C.H.I.E. (his AI COO) actually *work together* — talk (by voice or text), hand her files, delegate work, run skills, and approve findings, in one conversation. Today the cockpit does chat + delegation but nothing else: you can't approve the 77 Code-Health findings there, can't hand her a document, and she has no voice or presence.

This spec turns the existing `archie_comms` cockpit into a full COO collaboration surface **without moving heavy logic into the standalone** — the cockpit stays a thin, sovereign presentation layer and reaches the platform for every real operation.

## 2. Goal & Non-Goals

**Goal:** four capabilities added to the cockpit, each riding existing platform infrastructure:
1. **Approvals** — approve/deny Tier-2 findings (incl. the red Code-Health cards) both chat-natively ("approve the family_tree one") and via a visual panel.
2. **Attachments** — drop a file in chat; A.R.C.H.I.E. reads its text.
3. **Voice** — she speaks (TTS), you speak (STT), both **on-cluster / sovereign**.
4. **The "Face"** — her avatar + presence states + per-message attribution, fusing the above into one COO presence.

**Non-Goals (explicitly out of scope):**
- Multi-user cockpit / non-owner access. It stays admin-gated (owner + staff), Kytran = `user_id=2`.
- Moving inference, TTS, extraction, or approval *execution* into `archie_comms`. All of it stays on the platform behind `@_require_internal_key`.
- Replacing the DHQ-first chat path (the ADR-013-waivered local-voice fallback stays).
- Telegram/Home-Assistant voice changes (the platform's `ha_bridge` keeps working unchanged).
- A public product surface. This is the owner's private cockpit.

## 3. Current State (grounded 2026-07-11 by reading the code)

**Cockpit (`/mnt/archie_brain/archie-comms/`):**
- LCARS 3-column UI: `templates/chat.html` (cyan `#00ffff`, Antonio/Orbitron/IBM Plex Mono), `static/css/archie-chat.css`, `static/js/archie-chat.js` (classes `SessionManager`, `MessageStream`, `StatusPanel`, `DelegationCard`, `TerminalDrawer`). Left session sidebar, center message list + `ac-input-bar` + `ac-quick-actions`, right rail (agents / dispatch-feed / platform / repair-bay / engine status), a terminal drawer.
- **Chat flow:** `MessageStream.send()` → `POST /api/chat/send_message` (SSE); event types `token`/`delegation_queued`/`delegation_failed`/`done`. `DelegationCard` polls `/api/delegation/<id>/status`.
- **Marker mechanism** (`services/conversation_service.py`): `_DELEGATE_RE` (~L914) matches `{{DELEGATE capability="X" reason="Y"}}`; `_DELEGATION_SYSTEM_PROMPT` (~L930) tells A.R.C.H.I.E. when to emit it; `stream_send_message` harvests via `_collect_delegate` (~L1115), strips markers from the visible text, yields `delegation_detected`. `app_comms.py::api_chat_send_message` fires `_call_platform_delegation_submit(capability, reason)` and emits `delegation_queued`.
- **DHQ reply path:** `_dhq_chat_reply` / `dhq_chat_raw` POST `{prompt, system_prompt, user_id}` to `{PLATFORM_URL}/api/internal/dhq/chat` with `Authorization: Bearer {INTERNAL_API_KEY}`. Both env vars present in comms.
- **Auth:** kytran_auth OIDC, admin-gated (`on_sso_login` discards non-admins). Session `user_id`. Bearer chat-key path for CLI.
- **Persona:** `services/archie_voice_service.py::_get_system_prompt()` is DB-driven (`archie_personality` + `archie_relationships` for user 2 + traits), TTL-cached.
- **Container constraint:** `read_only: true`, `cap_drop: ALL`, bind-mounted `:ro`. Only tmpfs is writable → the cockpit persists nothing.
- **Gaps:** no approvals endpoints at all; no attachment/multipart handling; voice bridge stubbed (`chat/ha_bridge.py` `VOICE_SYNTHESIS_AVAILABLE=False`, `/ha/tts` → 503); no avatar/presence; no per-message agent/model badge.

**Platform approvals (`platform_v2/tools/department_hq/approvals_routes.py`):**
- `GET /api/approvals/pending` → `approvals_pending()` (unifies `autonomy_approval_queue` + `contractor_approval_requests` + `bridge_jobs`), all `@admin_required` (session).
- `POST /api/approvals/<approval_id>/approve` → `approvals_approve()` → `_approve_autonomy(source_id, user_id)` (flips the queue row to `approved`, records `approved_by`). `POST …/deny` → `_deny_autonomy(source_id, user_id, reason)`. `approval_id` is source-prefixed (`autonomy:123`).
- Downstream of a queue-approve: the `ai_bridge/agent_loop` consumer flips `improvement_proposals.status='approved'` → `audit_pipeline.dispatch_audit_proposals()` (red requires `status IN ('approved','fix_requested')`) → `dispatch_proposal_fix(proposal_id)` generates the fix. **A cockpit "approve" ultimately triggers this by flipping the queue row.**

**Platform voice (`ai_bridge/voice_synthesis.py`):**
- `get_voice_synthesizer()` singleton; `synth.synthesize_for_agent(text, agent_id=2, emotion, user_id)` → `{success, audio_base64, cached, generation_time_ms, engine}`. Kokoro default (fast, multi-tier cached, phrase pre-warm via `voice_pregen.py`); XTTS heavy/GPU. A.R.C.H.I.E. = agent_id 2; voice via `agent_voice_profiles` + `static/voices/{id}.wav`.
- Browser TTS already solved in platform: `POST /tools/archie-chat/api/voice/synthesize` → `{audio_base64}`; `POST /api/voice/preview`.
- **STT:** none server-side anywhere. Browser Web Speech API is proven in `archie_chat` (rejected here for sovereignty). Whisper is net-new.

**Platform attachments:** no general chat upload (chat takes base64 images for vision only). One reusable extractor: `services/chronicle_attachment_service.py::extract_text_from_file(path, mime) -> (text, ocr_used)` (PDF via PyPDF2, docx via python-docx, image via `tools/family_tree/services/ocr_service.ocr_document`). **Platform-only** (imports `tools.family_tree`). No prompt size cap on `/api/internal/dhq/chat`.

**Internal-key pattern (`platform_v2/app.py`):** `_require_internal_key(f)` (~L4413) compares `Authorization` to `Bearer {INTERNAL_API_KEY}`. Existing: `/api/internal/dhq/chat`, `/api/internal/session-link`, `/api/internal/sessions/<a>/<p>/state`, `/api/internal/engine/telemetry`. **No internal approval / attachment / voice endpoints exist yet.** Internal calls have no `current_user` → an explicit owner `user_id` must be passed.

## 4. Design

### 4.1 Architecture principle — thin sovereign cockpit

```
Browser (Kytran, admin OIDC)
   │  chat SSE · approvals · attachment · voice · presence
   ▼
archie_comms  (read-only, admin-gated, holds only INTERNAL_API_KEY)
   │  Bearer INTERNAL_API_KEY  (the /api/internal/dhq/chat pattern)
   ▼
platform_v2  (@_require_internal_key endpoints wrapping EXISTING logic)
   ├─ dhq/chat            (exists)      → DHQ dispatch → A.R.C.H.I.E./fleet
   ├─ approvals/*         (NEW, §4.2)   → _approve_autonomy/_deny_autonomy
   ├─ attachments/extract (NEW, §4.3)   → extract_text_from_file
   └─ voice/synthesize|transcribe (NEW, §4.4) → synthesize_for_agent / whisper
```

The cockpit adds UI + thin proxy routes only. Every real operation is a platform internal endpoint that wraps logic that already exists (or, for Whisper, a new local service). No business logic, no secrets beyond `INTERNAL_API_KEY`, no persistence in comms.

### 4.2 Slice 1 — Approvals (chat-native + panel)

**Platform (new `@_require_internal_key` endpoints in `app.py`, thin wrappers over `approvals_routes`):**
- `GET  /api/internal/approvals/pending` → returns `approvals_pending()`'s list (refactor the query body out of the `@admin_required` route into a callable `list_pending_approvals()` both share).
- `POST /api/internal/approvals/<approval_id>/approve {user_id}` → `_approve_autonomy(source_id, user_id)` (owner id from body, default 2).
- `POST /api/internal/approvals/<approval_id>/deny {user_id, reason}` → `_deny_autonomy(...)`.

**Cockpit backend (`archie_comms`):**
- Proxy routes (session-auth for Kytran) `GET /api/approvals/pending`, `POST /api/approvals/<id>/approve|deny` → forward to the platform internal endpoints with Bearer `INTERNAL_API_KEY`, injecting the logged-in `user_id`. (Same shape as `_dhq_chat_reply`.)

**Chat-native (`conversation_service.py` + `app_comms.py`):**
- Add `_APPROVE_RE` = `{{APPROVE id="autonomy:N"}}` and `_APPROVALS_RE` = `{{APPROVALS}}` beside `_DELEGATE_RE`; harvest them in the same `_collect_delegate`-style pass; yield `approval_action` / `approvals_list_request` events.
- Extend A.R.C.H.I.E.'s system prompt (a new `_APPROVALS_SYSTEM_PROMPT` block, appended like the delegation one) telling her: when the owner asks to see pending approvals emit `{{APPROVALS}}`; when he approves/denies a specific one emit `{{APPROVE id="autonomy:N"}}` / `{{DENY id="autonomy:N" reason="..."}}`. She resolves "the family_tree one" → the right `autonomy:N` from the list already shown in-conversation.
- `app_comms.py` handles the events: `{{APPROVALS}}` → calls the pending proxy, streams an `approvals_list` SSE event (rendered as cards); `{{APPROVE …}}` → calls the approve proxy, streams `approval_done`.

**Panel (frontend `archie-chat.js` + `chat.html`):**
- A right-rail **Approvals** panel: polls `GET /api/approvals/pending`, renders each as an `ApprovalCard` (extend the existing `DelegationCard` component/CSS) showing the friendly label already produced by `_code_fix_label` (PR #2205) + Approve/Deny buttons → `POST /api/approvals/<id>/approve|deny`. Chat-native and panel share the same proxy backend, so an approval from either updates both.

### 4.3 Slice 2 — Attachments

**Platform (new internal endpoint):**
- `POST /api/internal/attachments/extract {filename, content_b64, mime}` → decode to a tmpfs/`:rw` temp path → `extract_text_from_file(path, mime)` → `{text, ocr_used, chars}` → delete temp. Guard: reject > a max upload size; truncate returned text to a cap.

**Cockpit:**
- `POST /api/chat/send_message` accepts multipart (`file` + `message`) OR a small JSON pre-step `POST /api/chat/attach` that returns extracted text; comms holds bytes **in memory only**, forwards base64 to the platform extract endpoint, then prepends `\n\n[Attachment: <name> (<chars> chars, ocr=<bool>)]\n<text>\n` to the DHQ `prompt` (hard cap ~20k chars, explicit, logged when truncated).
- Frontend: 📎 button in `ac-input-bar` → file chip shown on the pending message; the attachment summary rides that message.

### 4.4 Slice 3 — Voice (sovereign both directions)

**TTS — she speaks (platform already does the work):**
- New internal `POST /api/internal/voice/synthesize {text, emotion?, user_id?}` → `synthesize_for_agent(text, agent_id=2, emotion, user_id)` → `{audio_base64, cached, engine}`. (Or reuse `/tools/archie-chat/api/voice/synthesize` behind an internal-key alias.)
- Cockpit: a `voice` toggle. When on, after a reply finishes streaming, comms proxy `POST /api/voice/synthesize` → cockpit decodes `audio_base64` → `new Audio().play()`. Kokoro engine (fast, cached) keeps it interactive. Presence flips to **speaking** while audio plays.

**STT — you speak (new sovereign Whisper service):**
- New `whisper` service on the **hub** (faster-whisper, GPU; CPU fallback on an outpost) exposed to the platform as `POST /api/internal/voice/transcribe {audio_b64, mime}` → `{text}`. Audio never leaves the cluster.
- Cockpit: mic button in `ac-input-bar` records (MediaRecorder) → base64 → comms proxy → transcript fills the input textarea (owner edits then sends, or auto-send on a setting). Presence flips to **listening** while recording.

### 4.5 Slice 4 — The "Face" / presence

- **Avatar:** render agent-2's portrait (the platform agent-portrait system already holds it; comms fetches it via an internal/static path) in a header/presence element.
- **Presence states:** `idle · thinking · speaking · listening` driven by chat/voice state (streaming → thinking; TTS playing → speaking; mic recording → listening).
- **Per-message attribution:** a small badge on each assistant turn — which fleet agent + model answered (the DHQ reply already returns `agent_name`/`model_used`; thread it into the SSE `done` event and render `⟨A.R.C.H.I.E. · qwen2.5:7b⟩`).
- **Persona header:** her DB traits (`greeting_style`, trust/preferred_name for Kytran) surface as "A.R.C.H.I.E. · COO · <presence>", pulled from the existing persona service.

## 5. Reuse vs Build

**Reuse (unchanged):** `_approve_autonomy`/`_deny_autonomy`/`approvals_pending`, `_code_fix_label` (PR #2205), `extract_text_from_file`, `synthesize_for_agent` + Kokoro cache/pregen, the `_dhq_chat_reply` proxy pattern, the `{{DELEGATE}}` marker machinery, `DelegationCard`, the agent-portrait store, `_require_internal_key`, the DB-driven persona.

**Build:** platform internal endpoints (approvals ×3, attachments/extract, voice/synthesize, voice/transcribe) + a shared `list_pending_approvals()` extraction; a new **Whisper** service; comms proxy routes + `{{APPROVE}}`/`{{APPROVALS}}` markers + attachment forwarding + voice proxy; frontend Approvals panel, 📎 button, mic + TTS controls, avatar/presence + attribution badge.

## 6. Interfaces (exact)

**Platform internal (all `@_require_internal_key`, in `app.py`):**
- `GET  /api/internal/approvals/pending` → `{approvals: [...]}` (the `approvals_pending()` payload).
- `POST /api/internal/approvals/<path:approval_id>/approve` `{user_id?}` → `{ok, action_type}`.
- `POST /api/internal/approvals/<path:approval_id>/deny` `{user_id?, reason?}` → `{ok}`.
- `POST /api/internal/attachments/extract` `{filename, content_b64, mime?}` → `{text, ocr_used, chars, truncated}`.
- `POST /api/internal/voice/synthesize` `{text, emotion?, user_id?}` → `{success, audio_base64, cached, engine}`.
- `POST /api/internal/voice/transcribe` `{audio_b64, mime?}` → `{text}`.

**Cockpit (session-auth) →** proxy to the above with Bearer `INTERNAL_API_KEY`, injecting the logged-in `user_id`:
- `GET /api/approvals/pending` · `POST /api/approvals/<id>/approve|deny`
- `POST /api/chat/attach` (multipart) → returns extracted text; or multipart on `send_message`
- `POST /api/voice/synthesize` · `POST /api/voice/transcribe`

**Chat markers (A.R.C.H.I.E. emits, comms strips + acts):** `{{APPROVALS}}` · `{{APPROVE id="autonomy:N"}}` · `{{DENY id="autonomy:N" reason="..."}}`.

## 7. Slice decomposition & build order

| # | Slice | Ships | Depends on |
|---|-------|-------|------------|
| 1 | **Approvals** (chat-native + panel) | approve/deny the 77 reds + all Tier-2 from the cockpit | nothing new |
| 2 | **Attachments** | drop a file, she reads it | nothing new |
| 3 | **Voice** | she speaks (TTS) + you speak (Whisper STT) | new Whisper service |
| 4 | **Face / presence** | avatar + presence states + attribution badge | Slices 1–3 for the states to reflect |

Each slice is a separate implementation plan, independently deployable (comms rebuild + platform restart). Order = value × (inverse) risk: approvals first (your explicit ask, smallest), face last (frontend polish over the working guts).

## 8. Error handling

- Every comms→platform proxy is **fail-soft**: a platform outage returns a clean cockpit error ("A.R.C.H.I.E. can't reach the platform right now"), never a hang — mirrors `_dhq_chat_reply`'s fail-to-None. The DHQ-first chat keeps its local-voice fallback (ADR-013 waiver).
- **Approvals are fail-closed:** a proxy/exec error surfaces the failure and leaves the approval **pending** — never optimistically shows "approved".
- **Attachments:** oversize/unsupported → rejected with a message; extraction failure → the message still sends without the attachment text (+ a note). Extracted text is hard-capped; truncation is surfaced.
- **Voice:** TTS failure → silently fall back to text (no audio, no error spam). STT failure → the mic just yields no transcript; the owner types.
- **Chat markers:** a malformed/unknown `{{APPROVE …}}` id → comms reports "couldn't find that approval" in-chat, never blindly approves.

## 9. Testing

- **Platform internal endpoints:** unit tests with the auth boundary + underlying function stubbed (approve routes to `_approve_autonomy`; extract routes to `extract_text_from_file`; voice routes to `synthesize_for_agent`/whisper). A 401-without-key test each.
- **Comms proxy + markers:** unit tests for the `{{APPROVE}}`/`{{APPROVALS}}` parse+strip (mirror the existing delegation-marker tests) and the proxy fail-soft/fail-closed behavior with a stubbed platform.
- **Whisper service:** a smoke test transcribing a known short clip.
- **Frontend (face/voice/panel):** browser verification via P.R.O.B.E./Playwright — login, approve from the panel, approve via chat, attach a file, hear TTS, mic→transcript, presence transitions. This is the one part unit tests can't cover.
- **End-to-end per slice** in the freshly-built comms + platform.

## 10. Decisions Made (during brainstorming)

- **Thin sovereign cockpit** — comms is presentation-only; all heavy ops are platform `@_require_internal_key` endpoints wrapping existing logic. ✔
- **Both approval surfaces** — chat-native (`{{APPROVE}}` markers, reusing the delegation rail) AND a visual panel (reusing `DelegationCard`). ✔
- **Sovereign STT = self-hosted Whisper** (not browser Web Speech API, which streams audio to Google — contradicts the platform's local-sovereign identity). TTS already local (Kokoro). ✔
- **4-slice decomposition**, built in order approvals → attachments → voice → face; each independently shippable. ✔
- **Owner-only** — stays admin-gated, `user_id=2`; no multi-user scope. ✔

## 11. Open Questions (for the implementation plans)

- Whisper deployment shape: a dedicated `archie_whisper` container (faster-whisper GPU) vs an in-platform endpoint loading faster-whisper lazily. Lean container (keeps the platform image lean; mirrors `archie_comfyui`), decide in the Slice-3 plan.
- Attachment cap value (20k chars is a starting point) + whether images attach as vision (base64 image path already exists) vs text-only — Slice-2 plan.
- Avatar treatment: static agent-2 portrait vs a lightweight reactive/animated presence — Slice-4 plan (a visual decision; may use the design companion).
- Voice auto-send vs edit-before-send after STT — Slice-3 plan (default: fill input, owner sends).
