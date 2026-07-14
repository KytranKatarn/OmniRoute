# A.R.C.H.I.E. CLI Collaboration (comms + engine + archie-tui) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete `archie.kytranempowerment.com` (the `archie_comms` service) + `archie-tui` + the Claude-collaboration hooks so A.R.C.H.I.E. is operable as a full command line — like a Claude Code session, but driven by the real agent fleet (DHQ dispatch) and node/mesh system.

**Architecture:** The machine already exists and runs. `archie_comms` (Flask, :3002) is the "cockpit"; `archie_engine` (Python, ws:9090) is the executor that dispatches to the fleet over REST (`dhq_complete`) and runs file/git/shell/build tools; `archie-tui` (Go/Bubble Tea) is the terminal client. This plan **completes and wires** three gaps: (1) a first-class **API-key streaming chat surface** on comms (today a `NotImplementedError` stub), (2) a **persistent, progress-streaming engine session** (today one-shot request/reply), and (3) an **interactive agentic TUI** (streamed agent output, a tool/slash palette, driveable build loop, file-edit approval) sharing session/task state with comms and the Claude MCP bridge.

**Tech Stack:** Python 3.11 / Flask / gunicorn / SSE / websockets (comms + engine); Go / Bubble Tea / gorilla-websocket (archie-tui); DHQ dispatch over REST (`/api/internal/dhq/chat`, `/api/v1/tools/generate_code`); Postgres (`conversations`, `messages`, `unified_tasks`).

## Global Constraints

*(Every task's requirements implicitly include this section.)*

- **Two repos.** `archie-comms` lives in **this** platform repo (`/mnt/archie_brain/archie-comms/`, built by the root `docker-compose.yml`). `archie_engine` + `archie-tui` live in the **separate public repo** at `/mnt/standalone/archie-code/` (`KytranKatarn/archie-code`). Each repo gets its own branch + PR. Never mix commits across repos.
- **All inference through DHQ.** Comms' primary path is `POST /api/internal/dhq/chat`; the engine dispatches via `connector.dhq_complete(...)`/`generate_code`. The comms local-model crash-survival fallback is an ADR-013-waivered exception only — do not add new paths that bypass the DHQ dispatcher.
- **Never merge, never push to main; the engine build loop already refuses protected branches** — keep it that way. PR creation needs `ARCHIE_GITHUB_TOKEN`; it fails closed without it.
- **Comms container is `read_only` + `cap_drop: ALL`.** It cannot write files; all file/git/shell mutation must route through `archie_engine` tools. Do not try to give comms write access.
- **Mesh/internal hostnames only** for inter-service calls (`archie_platform:3000`, `archie_engine:9090/9091`, `100.64.0.4`) — never public hostnames.
- **XSS-safe UI**: any external/agent text rendered in a web view uses `textContent`, never `innerHTML`.
- **Deploy is rebuild, not restart** (image-baked): `docker compose up -d --build archie_comms` / the engine's compose; the Go TUI is a rebuilt binary.
- **Tests:** comms/engine Python via `pytest` in their containers; TUI via `go test ./...` in `/mnt/standalone/archie-code/archie-tui`.

---

## File Structure

**Repo A — platform (`/mnt/archie_brain/archie-comms/`):**

| File | Responsibility |
|---|---|
| `chat/api_routes.py` | **modify** — implement the stubbed `POST /api/v1/chat/message` (→ DHQ, SSE) |
| `chat/auth_middleware.py` | **modify** — allow API-key auth on the streaming write path |
| `services/conversation_service.py` | **modify** — expose a reusable streaming generator for both session + API-key callers |
| `tests/test_v1_chat_api.py` | new — v1 API tests |

**Repo B — archie-code (`/mnt/standalone/archie-code/`):**

| File | Responsibility |
|---|---|
| `archie_engine/engine.py`, `server.py` | **modify** — persistent session handler + progress-frame streaming |
| `archie_engine/session.py` | new — per-session state (id, history, active job, cancel) |
| `archie_engine/tests/test_session_stream.py` | new — engine session/streaming tests |
| `archie-tui/client.go` | **modify** — consume streamed frames + session channel |
| `archie-tui/model.go`, `messages.go` | **modify** — REPL state, streamed rendering, tool palette |
| `archie-tui/views/palette.go` | new — slash-command / tool palette |
| `archie-tui/build_view.go` | new — launch + stream the build loop, file-edit approval |
| `archie-tui/*_test.go` | new — Go tests |

---

## Task 1: Complete the comms `POST /api/v1/chat/message` (DHQ, non-streaming first)

Unstub the Bearer-authed v1 chat endpoint and route it to the same DHQ path the SSE UI already uses. Non-streaming first (smallest correct increment); streaming in Task 3.

**Repo:** platform (`archie-comms`).

**Files:**
- Modify: `chat/api_routes.py` (~L191, the `NotImplementedError`)
- Test: `tests/test_v1_chat_api.py`

**Interfaces:**
- Consumes: `services/conversation_service` DHQ helper (`_dhq_chat_reply` at L36, or a public wrapper).
- Produces: `POST /api/v1/chat/message {message, conversation_id?} -> {reply, conversation_id, agent, dispatched_via}` (200), Bearer-authed.

- [ ] **Step 1: Write the failing test**

```python
# archie-comms/tests/test_v1_chat_api.py
import json
import app_comms  # Flask app factory / module-level `app`


def _client():
    app_comms.app.config["TESTING"] = True
    return app_comms.app.test_client()


def test_v1_message_returns_reply(monkeypatch):
    # stub the DHQ round-trip so the test is hermetic
    import chat.api_routes as ar
    monkeypatch.setattr(ar, "dhq_reply",
                        lambda text, conv_id=None, **kw: {"reply": "pong", "agent": "A.R.C.H.I.E.",
                                                          "conversation_id": conv_id or "c1",
                                                          "dispatched_via": "dhq"})
    monkeypatch.setattr(ar, "require_api_key", lambda f: f)  # bypass auth in unit test
    c = _client()
    r = c.post("/api/v1/chat/message", json={"message": "ping"},
               headers={"Authorization": "Bearer archie_test"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["reply"] == "pong" and body["dispatched_via"] == "dhq"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec archie_comms python3 -m pytest tests/test_v1_chat_api.py -v`
Expected: FAIL — `NotImplementedError` (or 501) from the current stub.

- [ ] **Step 3: Read the stub + the DHQ helper, then implement**

Confirm the current stub + helper:
Run: `docker exec archie_comms sh -c "sed -n '30,60p' services/conversation_service.py; sed -n '180,210p' chat/api_routes.py"`

Add a small module-level `dhq_reply(...)` seam in `chat/api_routes.py` that wraps `conversation_service`'s existing `_dhq_chat_reply` (non-streaming), then implement the route:

```python
# chat/api_routes.py  (replace the NotImplementedError body)
from services.conversation_service import dhq_chat_reply as _dhq_chat_reply  # public wrapper (Task 2)

def dhq_reply(text, conv_id=None, **kw):
    return _dhq_chat_reply(text, conversation_id=conv_id, **kw)

@bp.route("/api/v1/chat/message", methods=["POST"])
@require_api_key
def v1_chat_message():
    from flask import request, jsonify
    data = request.get_json(silent=True) or {}
    text = (data.get("message") or "").strip()
    if not text:
        return jsonify({"error": "message required"}), 400
    out = dhq_reply(text, conv_id=data.get("conversation_id"))
    return jsonify(out), 200
```

If `conversation_service` only has the private `_dhq_chat_reply(text, ...)`, add a thin public `dhq_chat_reply(text, conversation_id=None, **kw)` wrapper there (Task 2 Step 3 formalizes it; for this task a minimal wrapper is fine).

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec archie_comms python3 -m pytest tests/test_v1_chat_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit** (platform repo)

```bash
git add archie-comms/chat/api_routes.py archie-comms/services/conversation_service.py archie-comms/tests/test_v1_chat_api.py
git commit -m "feat(comms): implement v1 chat API -> DHQ (was NotImplementedError stub)"
```

---

## Task 2: API-key auth on the streaming write path

Today `/api/chat/send_message` (SSE) is session-cookie only; a CLI has no token entry. Make the SSE write path accept the same Bearer API key the v1 route uses.

**Repo:** platform (`archie-comms`).

**Files:**
- Modify: `chat/auth_middleware.py` (the `@chat_auth_required` decorator — already tries Bearer then session)
- Modify: `services/conversation_service.py` (add the public `dhq_chat_reply` + a `stream_reply` generator seam)
- Test: `tests/test_streaming_auth.py`

**Interfaces:**
- Consumes: `chat_api_keys` SHA-256 lookup (existing in `auth_middleware`).
- Produces: `stream_reply(text, conversation_id=None, user_ctx=None) -> Iterator[str]` yielding SSE `data:` chunks; used by both session SSE and the API-key SSE route (Task 3).

- [ ] **Step 1: Write the failing test**

```python
# archie-comms/tests/test_streaming_auth.py
import app_comms


def test_send_message_accepts_bearer_key(monkeypatch):
    import chat.auth_middleware as am
    # a valid key resolves to a service principal
    monkeypatch.setattr(am, "resolve_api_key", lambda raw: {"principal": "cli", "scopes": ["chat"]})
    import services.conversation_service as cs
    monkeypatch.setattr(cs, "stream_reply",
                        lambda text, **kw: iter(["data: hi\n\n", "data: [DONE]\n\n"]))
    app_comms.app.config["TESTING"] = True
    c = app_comms.app.test_client()
    r = c.post("/api/chat/send_message", json={"message": "hi"},
               headers={"Authorization": "Bearer archie_valid"})
    assert r.status_code == 200
    assert b"data:" in r.data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec archie_comms python3 -m pytest tests/test_streaming_auth.py -v`
Expected: FAIL — 401/redirect (route is session-only today).

- [ ] **Step 3: Read the SSE route + decorator, then wire Bearer**

Run: `docker exec archie_comms sh -c "sed -n '540,620p' app_comms.py; sed -n '1,80p' chat/auth_middleware.py"`

Change the SSE route (`/api/chat/send_message`) to use `@chat_auth_required` (Bearer-or-session) instead of the raw session check, and set the streaming principal from either source. Add to `conversation_service.py`:

```python
# services/conversation_service.py
def dhq_chat_reply(text, conversation_id=None, **kw):
    """Public non-streaming DHQ reply (wraps _dhq_chat_reply)."""
    return _dhq_chat_reply(text, conversation_id=conversation_id, **kw)

def stream_reply(text, conversation_id=None, user_ctx=None):
    """SSE generator shared by session + API-key callers. Streams the DHQ reply
    (single chunk today; token-streaming lands when the engine session streams —
    Track B Task 4). Yields 'data: ...\\n\\n' frames ending with '[DONE]'."""
    out = _dhq_chat_reply(text, conversation_id=conversation_id)
    yield f"data: {out['reply']}\n\n"
    yield "data: [DONE]\n\n"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec archie_comms python3 -m pytest tests/test_streaming_auth.py -v`
Expected: PASS

- [ ] **Step 5: Deploy + live smoke** (image-baked)

```bash
docker compose -f /mnt/archie_brain/docker-compose.yml up -d --build archie_comms
```
Then from a shell with a valid key: `POST http://archie_comms:3002/api/chat/send_message` with `Authorization: Bearer <key>` returns an SSE stream. (Use an internal mesh caller; the container is not publicly reachable for this.)

- [ ] **Step 6: Commit** (platform repo)

```bash
git add archie-comms/app_comms.py archie-comms/chat/auth_middleware.py archie-comms/services/conversation_service.py archie-comms/tests/test_streaming_auth.py
git commit -m "feat(comms): API-key auth on SSE write path + shared stream_reply generator"
```

---

## Task 3: Persistent engine session + progress-frame streaming

The engine ws:9090 is one-shot request/reply. Add a **session** concept so a CLI can hold a live channel, and stream **progress frames** (dispatch queued/running, build step, tool result) instead of a single terminal frame. This is what makes the TUI feel like a live agent loop.

**Repo:** archie-code (`archie_engine`).

**Files:**
- Create: `archie_engine/session.py`
- Modify: `archie_engine/engine.py` (`handle_message`), `archie_engine/server.py`
- Test: `archie_engine/tests/test_session_stream.py`

**Interfaces:**
- Consumes: existing `intent`/`dispatch_strategy`/`router`/`connector.dhq_complete`.
- Produces: new ws frames on an open session socket:
  - inbound `{type:"session_start", session_id?}` → `{type:"session_ready", session_id}`
  - inbound `{type:"message", session_id, content}` → a **stream** of `{type:"progress", session_id, stage, detail}` frames, then `{type:"response", session_id, content, intent, dispatch_target, tool_calls}`.
  - inbound `{type:"cancel", session_id}` → `{type:"cancelled", session_id}`.
- Produces: `class Session` with `id`, `history: list`, `active: bool`, `cancel()`.

- [ ] **Step 1: Read the engine message loop + dispatch path**

Run: `docker exec archie_engine sh -c "grep -n 'handle_message\|async def\|def dispatch\|dhq_complete\|websocket' /app/archie_engine/engine.py /app/archie_engine/server.py | head -60"`
Record the exact async signature of `handle_message` and how frames are currently sent (so the new streaming frames use the same send path).

- [ ] **Step 2: Write the failing test**

```python
# archie_engine/tests/test_session_stream.py
import asyncio
import archie_engine.engine as engine
from archie_engine.session import Session, SESSIONS


def test_session_lifecycle():
    s = Session.create()
    assert s.id in SESSIONS and s.active is False
    s.mark_active(); assert s.active is True
    s.cancel(); assert s.active is False


def test_message_emits_progress_then_response(monkeypatch):
    sent = []
    async def fake_send(frame): sent.append(frame)

    # stub the actual dispatch so we only assert framing
    async def fake_route(content, session, emit):
        await emit({"type": "progress", "stage": "dispatch", "detail": "queued"})
        return {"content": "done", "intent": "chat", "dispatch_target": "F.O.R.G.E.", "tool_calls": []}
    monkeypatch.setattr(engine, "route_with_progress", fake_route)

    s = Session.create()
    asyncio.get_event_loop().run_until_complete(
        engine.handle_session_message({"type": "message", "session_id": s.id, "content": "hi"}, fake_send))
    stages = [f.get("stage") for f in sent if f["type"] == "progress"]
    assert "dispatch" in stages
    assert any(f["type"] == "response" and f["content"] == "done" for f in sent)
```

- [ ] **Step 3: Implement `session.py` + the session message handler**

```python
# archie_engine/session.py
import uuid

SESSIONS: dict[str, "Session"] = {}

class Session:
    def __init__(self, sid):
        self.id = sid
        self.history: list = []
        self.active = False
        self._cancelled = False
    @classmethod
    def create(cls):
        s = cls(uuid.uuid4().hex[:12]); SESSIONS[s.id] = s; return s
    def mark_active(self): self.active = True; self._cancelled = False
    def cancel(self): self.active = False; self._cancelled = True
    @property
    def cancelled(self): return self._cancelled
```

Add to `engine.py`:

```python
from archie_engine.session import Session, SESSIONS

async def route_with_progress(content, session, emit):
    """Runs intent->dispatch, emitting progress frames via `emit`. Wraps the
    EXISTING dispatch path (connector.dhq_complete / tool ops); on each stage
    boundary it awaits emit({...progress...}). Returns the final response dict."""
    await emit({"type": "progress", "stage": "intent", "detail": "classifying"})
    # ... call the existing intent + dispatch_strategy + router here, emitting
    #     {"stage":"dispatch"/"build"/"test"/"tool"} as those steps run ...
    result = await _existing_route(content, session)   # the current one-shot path
    return result

async def handle_session_message(msg, send):
    s = SESSIONS.get(msg.get("session_id")) or Session.create()
    s.mark_active()
    async def emit(frame):
        frame.setdefault("session_id", s.id)
        await send(frame)
    if msg.get("type") == "cancel":
        s.cancel(); await send({"type": "cancelled", "session_id": s.id}); return
    resp = await route_with_progress(msg.get("content", ""), s, emit)
    s.history.append({"role": "assistant", "content": resp.get("content", "")})
    s.active = False
    await send({"type": "response", "session_id": s.id, **resp})
```

Wire `handle_message` in `engine.py`/`server.py` to dispatch `session_start`/`message`(with `session_id`)/`cancel` to `handle_session_message`; keep the legacy one-shot path for back-compat (existing TUI file ops must not break).

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec archie_engine python3 -m pytest archie_engine/tests/test_session_stream.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Deploy the engine + live ws smoke**

Rebuild per the engine's compose (image-baked). Then a quick ws client (python `websockets`) sends `session_start` → `message` and prints frames; confirm ≥1 `progress` then a `response`.

- [ ] **Step 6: Commit** (archie-code repo)

```bash
cd /mnt/standalone/archie-code
git checkout -b feat/engine-session-streaming
git add archie_engine/session.py archie_engine/engine.py archie_engine/server.py archie_engine/tests/test_session_stream.py
git commit -m "feat(engine): persistent session channel + progress-frame streaming"
```

---

## Task 4: archie-tui streamed agent output + REPL loop

Make the TUI render streamed frames live (progress + final) instead of blocking on one reply, over a held session channel.

**Repo:** archie-code (`archie-tui`, Go/Bubble Tea).

**Files:**
- Modify: `archie-tui/client.go` (consume streamed frames, hold session)
- Modify: `archie-tui/messages.go` (frame → Bubble Tea `Msg`), `archie-tui/model.go` (render loop)
- Test: `archie-tui/client_test.go`

**Interfaces:**
- Consumes: the Task 3 frames (`session_ready`/`progress`/`response`/`cancelled`).
- Produces: Go types `ProgressMsg{Stage, Detail}`, `ResponseMsg{Content, Agent, ToolCalls}`, and a `SessionClient` with `Start()`, `Send(text)`, `Frames() <-chan tea.Msg`, `Cancel()`.

- [ ] **Step 1: Read the current client + model to confirm patterns**

Run: `sed -n '1,80p' /mnt/standalone/archie-code/archie-tui/client.go; sed -n '1,60p' /mnt/standalone/archie-code/archie-tui/messages.go`
Confirm the gorilla/websocket usage + how existing `Msg`s reach `Update`.

- [ ] **Step 2: Write the failing Go test**

```go
// archie-tui/client_test.go
package main

import "testing"

func TestParseFrameProgress(t *testing.T) {
    raw := []byte(`{"type":"progress","session_id":"s1","stage":"dispatch","detail":"queued"}`)
    msg, err := parseFrame(raw)
    if err != nil { t.Fatalf("parse: %v", err) }
    p, ok := msg.(ProgressMsg)
    if !ok { t.Fatalf("want ProgressMsg, got %T", msg) }
    if p.Stage != "dispatch" { t.Fatalf("stage=%q", p.Stage) }
}

func TestParseFrameResponse(t *testing.T) {
    raw := []byte(`{"type":"response","session_id":"s1","content":"done","dispatch_target":"F.O.R.G.E."}`)
    msg, err := parseFrame(raw)
    if err != nil { t.Fatalf("parse: %v", err) }
    r, ok := msg.(ResponseMsg)
    if !ok { t.Fatalf("want ResponseMsg, got %T", msg) }
    if r.Content != "done" || r.Agent != "F.O.R.G.E." { t.Fatalf("bad: %+v", r) }
}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd /mnt/standalone/archie-code/archie-tui && go test ./... -run TestParseFrame -v`
Expected: FAIL — `undefined: parseFrame` / `ProgressMsg`.

- [ ] **Step 4: Implement `parseFrame` + message types + streamed render**

```go
// archie-tui/messages.go  (add)
type ProgressMsg struct{ Stage, Detail string }
type ResponseMsg struct{ Content, Agent string; ToolCalls []any }
type CancelledMsg struct{}

func parseFrame(raw []byte) (tea.Msg, error) {
    var m map[string]any
    if err := json.Unmarshal(raw, &m); err != nil { return nil, err }
    switch m["type"] {
    case "progress":
        return ProgressMsg{Stage: str(m["stage"]), Detail: str(m["detail"])}, nil
    case "response":
        return ResponseMsg{Content: str(m["content"]), Agent: str(m["dispatch_target"])}, nil
    case "cancelled":
        return CancelledMsg{}, nil
    }
    return nil, nil // unknown frame ignored
}
func str(v any) string { if s, ok := v.(string); ok { return s }; return "" }
```

In `client.go`, hold the session socket open, read frames in a goroutine, `parseFrame` each, and push onto the Bubble Tea program (`p.Send(msg)`). In `model.go` `Update`, append `ProgressMsg` as a dim status line and `ResponseMsg` as the agent turn; add a key (e.g. `esc`) that sends `Cancel()`.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /mnt/standalone/archie-code/archie-tui && go test ./... -run TestParseFrame -v`
Expected: PASS

- [ ] **Step 6: Build + manual smoke**

Run: `cd /mnt/standalone/archie-code/archie-tui && go build ./... && ./archie-tui` — send a message, confirm progress lines stream then the agent reply lands, and `esc` cancels.

- [ ] **Step 7: Commit** (archie-code repo)

```bash
cd /mnt/standalone/archie-code
git add archie-tui/client.go archie-tui/messages.go archie-tui/model.go archie-tui/client_test.go
git commit -m "feat(tui): streamed agent output over a held session channel + cancel"
```

---

## Task 5: TUI tool/slash palette + driveable build loop + file-edit approval

The three interactions that make it "a command line like Claude Code": a slash/tool palette (backed by the engine's `list_skills`), the ability to launch + stream the autonomous `build_loop`, and an interactive approve/reject for agent file edits (`apply_edit`).

**Repo:** archie-code (`archie-tui` + minor `archie_engine`).

**Files:**
- Create: `archie-tui/views/palette.go`, `archie-tui/build_view.go`
- Modify: `archie-tui/model.go` (key routing), `archie_engine/engine.py` (stream `pull_repair_work`/`run_build` progress + surface `apply_edit` as an approval-gated frame)
- Test: `archie-tui/palette_test.go`, `archie_engine/tests/test_build_stream.py`

**Interfaces:**
- Consumes: engine `list_skills` (existing), `pull_repair_work`/`run_build` (existing, made streaming), `apply_edit` (existing).
- Produces: TUI `PaletteModel` (filterable command list), a build view that renders streamed build stages, and an `apply_edit` **approval frame** `{type:"approval_request", session_id, kind:"apply_edit", path, diff}` → user Y/N → `{type:"approval", approved:bool, ...}`.

- [ ] **Step 1: Write failing tests**

```go
// archie-tui/palette_test.go
package main

import "testing"

func TestPaletteFiltersSkills(t *testing.T) {
    p := NewPalette([]string{"code", "code_review", "documentation", "security"})
    p.SetFilter("code")
    got := p.Visible()
    if len(got) != 2 { t.Fatalf("want 2, got %d (%v)", len(got), got) }
}
```

```python
# archie_engine/tests/test_build_stream.py
import asyncio
import archie_engine.engine as engine


def test_build_emits_stage_frames(monkeypatch):
    sent = []
    async def send(f): sent.append(f)
    async def fake_build(emit):
        for stage in ("coordinate", "build", "test", "pr"):
            await emit({"type": "progress", "stage": stage, "detail": ""})
        return {"pr_url": "https://github.com/x/y/pull/1", "merged": False}
    monkeypatch.setattr(engine, "run_build_streaming", fake_build)
    asyncio.get_event_loop().run_until_complete(
        engine.handle_build_command({"type": "run_build", "session_id": "s1"}, send))
    stages = [f["stage"] for f in sent if f["type"] == "progress"]
    assert stages == ["coordinate", "build", "test", "pr"]
    assert any(f.get("pr_url") for f in sent)  # final frame carries PR, never a merge
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /mnt/standalone/archie-code/archie-tui && go test ./... -run TestPalette -v` → FAIL (`undefined: NewPalette`).
Run: `docker exec archie_engine python3 -m pytest archie_engine/tests/test_build_stream.py -v` → FAIL (`handle_build_command` missing).

- [ ] **Step 3: Implement the palette**

```go
// archie-tui/views/palette.go
package views

import "strings"

type PaletteModel struct {
    all    []string
    filter string
}
func NewPalette(cmds []string) *PaletteModel { return &PaletteModel{all: cmds} }
func (p *PaletteModel) SetFilter(f string)   { p.filter = f }
func (p *PaletteModel) Visible() []string {
    if p.filter == "" { return p.all }
    out := []string{}
    for _, c := range p.all {
        if strings.Contains(c, p.filter) { out = append(out, c) }
    }
    return out
}
```

Wire a key (e.g. `/`) in `model.go` to open the palette, fetch `list_skills` from the engine to populate it, and on select send the chosen command/capability.

- [ ] **Step 4: Implement `run_build_streaming` + `handle_build_command` + `apply_edit` approval in the engine**

In `engine.py`, wrap `build_loop`'s existing coordinate→build→test→pr steps so each awaits `emit({"type":"progress","stage":...})`; the final frame carries `pr_url` and `merged: False` (the loop already never merges). For `apply_edit`, when an agent proposes an edit, emit `{type:"approval_request", kind:"apply_edit", path, diff}` and wait for an `{type:"approval", approved}` frame before calling the existing `apply_edit`/`file_ops` write.

- [ ] **Step 5: Implement `build_view.go` (TUI)** — render streamed build stages as a checklist; on `approval_request`, prompt Y/N and send the `approval` frame. Read `model.go` first to match the existing view-switch pattern.

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd /mnt/standalone/archie-code/archie-tui && go test ./... -run TestPalette -v` → PASS
Run: `docker exec archie_engine python3 -m pytest archie_engine/tests/test_build_stream.py -v` → PASS

- [ ] **Step 7: Build + manual smoke** — `/` opens palette; launching a build streams stages and ends on a PR link; an agent edit prompts for approval before applying.

- [ ] **Step 8: Commit** (archie-code repo)

```bash
cd /mnt/standalone/archie-code
git add archie-tui/views/palette.go archie-tui/build_view.go archie-tui/model.go archie-tui/palette_test.go \
        archie_engine/engine.py archie_engine/tests/test_build_stream.py
git commit -m "feat(tui+engine): tool palette, streamed build loop, apply_edit approval gate"
```

---

## Task 6: Shared session/task state + Claude MCP co-drive

Make comms, the engine, and the TUI operate on **one** conversation/task record, and confirm Claude (this CLI) can co-drive the same session via the existing `archie_engine/claude/mcp_server.py`.

**Repo:** both (platform `archie-comms` + archie-code `archie_engine`).

**Files:**
- Modify: `archie_engine/session.py` (persist to `unified_tasks`/`conversations` via the hub API), `archie_engine/claude/mcp_server.py` (expose the active session id + a `session_send` tool)
- Modify: `archie-comms/services/conversation_service.py` (attach engine `session_id` to the comms `conversation`)
- Test: `archie_engine/tests/test_session_persist.py`

**Interfaces:**
- Consumes: hub `/api/internal/dhq/chat` + `unified_tasks` (via the platform API, mesh).
- Produces: a `session_id` shared across all three surfaces; MCP tool `session_send(session_id, text)` so Claude can post into a live A.R.C.H.I.E. session; `context_bridge`/`state_sync` carry the shared history.

- [ ] **Step 1: Read the MCP server + state_sync to confirm the tool-registration pattern**

Run: `docker exec archie_engine sh -c "grep -n 'def \|tool\|register\|state_sync' /app/archie_engine/claude/mcp_server.py /app/archie_engine/claude/state_sync.py | head -40"`

- [ ] **Step 2: Write the failing test**

```python
# archie_engine/tests/test_session_persist.py
import archie_engine.session as sess


def test_session_links_conversation(monkeypatch):
    saved = {}
    monkeypatch.setattr(sess, "_persist_link",
                        lambda session_id, conversation_id: saved.update(
                            {"s": session_id, "c": conversation_id}))
    s = sess.Session.create()
    s.link_conversation("conv-42")
    assert saved == {"s": s.id, "c": "conv-42"}
```

- [ ] **Step 3: Implement the link + persistence + MCP tool**

Add to `session.py`:

```python
def _persist_link(session_id, conversation_id):
    """Record the engine-session <-> comms-conversation link in the hub so all
    surfaces resolve the same thread. Mesh call; non-fatal on failure."""
    import logging, requests, os
    try:
        requests.post(f"{os.getenv('PLATFORM_URL','http://archie_platform:3000')}/api/internal/session-link",
                      json={"session_id": session_id, "conversation_id": conversation_id},
                      headers={"Authorization": f"Bearer {os.getenv('INTERNAL_API_KEY','')}"}, timeout=4)
    except Exception as exc:
        logging.getLogger(__name__).warning("session link persist failed: %s", exc)

# on Session:
def link_conversation(self, conversation_id):
    self.conversation_id = conversation_id
    _persist_link(self.id, conversation_id)
```

Add an MCP tool `session_send(session_id, text)` in `mcp_server.py` (following the existing tool-registration pattern) that pushes `text` into the live session's `handle_session_message` — so Claude and the TUI share the loop. (The hub `/api/internal/session-link` endpoint is a small platform-side addition; if out of scope for this repo pass, stub it to 200 and note the platform follow-up.)

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec archie_engine python3 -m pytest archie_engine/tests/test_session_persist.py -v`
Expected: PASS

- [ ] **Step 5: Commit** (archie-code repo)

```bash
cd /mnt/standalone/archie-code
git add archie_engine/session.py archie_engine/claude/mcp_server.py archie_engine/tests/test_session_persist.py
git commit -m "feat(engine): shared session<->conversation link + MCP session_send for Claude co-drive"
```

---

## Task 7: Node/mesh visibility in the TUI

Surface which fleet agent + node handled each turn (from `DispatchResult`), so the CLI shows the real platform working — not a black box.

**Repo:** archie-code (`archie-tui` + engine passthrough).

**Files:**
- Modify: `archie_engine/engine.py` (include `agent`/`node`/`model` from the DHQ response in the `response` frame), `archie-tui/model.go` (render an agent/node badge)
- Test: `archie-tui/badge_test.go`

**Interfaces:**
- Consumes: DHQ `DispatchResult` fields (`agent_name`, `station_code`/node, `model_used`) already returned by `dhq_complete`/`generate_code`.
- Produces: `response` frame gains `agent`, `node`, `model`; TUI renders `⟨F.O.R.G.E. · Starship-246 · qwen2.5:7b⟩`.

- [ ] **Step 1: Write the failing Go test**

```go
// archie-tui/badge_test.go
package main

import "testing"

func TestAgentBadge(t *testing.T) {
    got := agentBadge("F.O.R.G.E.", "Starship-246", "qwen2.5:7b")
    want := "⟨F.O.R.G.E. · Starship-246 · qwen2.5:7b⟩"
    if got != want { t.Fatalf("got %q want %q", got, want) }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/standalone/archie-code/archie-tui && go test ./... -run TestAgentBadge -v`
Expected: FAIL — `undefined: agentBadge`.

- [ ] **Step 3: Implement the badge + carry the fields**

```go
// archie-tui/model.go  (add)
func agentBadge(agent, node, model string) string {
    parts := []string{}
    for _, p := range []string{agent, node, model} {
        if p != "" { parts = append(parts, p) }
    }
    return "⟨" + strings.Join(parts, " · ") + "⟩"
}
```

Extend `ResponseMsg` (Task 4) with `Node, Model string`, populate them in `parseFrame` from the `response` frame, and render `agentBadge(...)` under the agent turn. In `engine.py`, copy `agent`/`node`/`model` from the DHQ response into the `response` frame.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/standalone/archie-code/archie-tui && go test ./... -run TestAgentBadge -v`
Expected: PASS

- [ ] **Step 5: Commit** (archie-code repo)

```bash
cd /mnt/standalone/archie-code
git add archie-tui/model.go archie-tui/messages.go archie-tui/badge_test.go archie_engine/engine.py
git commit -m "feat(tui): agent/node/model badge from DispatchResult (real fleet visibility)"
```

---

## Task 8: End-to-end integration + deploy + token check

Prove the full path — CLI (API key) → comms SSE → DHQ → engine session → fleet agent → streamed reply — and confirm the PR-creating build path is live.

**Repo:** both.

**Files:**
- Test: `archie-comms/tests/test_e2e_cli.py` (marked slow/live), a short manual TUI script

- [ ] **Step 1: Verify `ARCHIE_GITHUB_TOKEN` present in the live engine**

```bash
docker inspect archie_engine -f '{{range .Config.Env}}{{println .}}{{end}}' | grep -i ARCHIE_GITHUB_TOKEN
```
If absent → PR creation fails closed; flag to the owner (secret provisioning is manual).

- [ ] **Step 2: Deploy both surfaces** (image-baked)

```bash
docker compose -f /mnt/archie_brain/docker-compose.yml up -d --build archie_comms
# engine per the archie-code compose:
cd /mnt/standalone/archie-code && docker compose up -d --build archie_engine
```

- [ ] **Step 3: Live E2E via API key**

```python
# archie-comms/tests/test_e2e_cli.py
import os, pytest, requests

@pytest.mark.slow
def test_api_key_chat_streams_from_dhq():
    key = os.environ["ARCHIE_CLI_KEY"]  # a real chat-scope key
    r = requests.post("http://archie_comms:3002/api/chat/send_message",
                      json={"message": "say hello"},
                      headers={"Authorization": f"Bearer {key}"}, stream=True, timeout=60)
    assert r.status_code == 200
    body = b"".join(r.iter_content()).decode()
    assert "data:" in body and "[DONE]" in body
```

Run: `docker exec archie_comms python3 -m pytest tests/test_e2e_cli.py -v -m slow`
Expected: PASS (a real DHQ-backed reply streams to an API-key caller — the CLI entry point works).

- [ ] **Step 4: Manual TUI E2E** — launch `archie-tui`, hold a session, send a task, watch progress stream, open the palette, launch a build, approve an edit, see the agent/node badge. Capture a short gif (optional) for the owner.

- [ ] **Step 5: Commit** (platform repo)

```bash
git add archie-comms/tests/test_e2e_cli.py
git commit -m "test(comms): live E2E — API-key CLI chat streams from DHQ"
```

---

## Self-Review

**Scope coverage (against the owner's Track B ask + the Explore map):**
- "Complete `archie.kytranempowerment.com`" → Tasks 1–2 (unstub v1 API + API-key streaming — the two concrete comms gaps the map found).
- "integrated with the Claude collaboration" → Task 6 (MCP `session_send` co-drive + shared session link; builds on the existing `claude/mcp_server.py`).
- "archie-tui able to write/update/interact … as a complete command line" → Tasks 3–5 (persistent streaming session, streamed REPL, tool palette, driveable build loop, file-edit approval).
- "using the full agent platform and node system" → Tasks 4/7 (DHQ dispatch already the execution path; Task 7 surfaces agent/node/model). Build loop already routes fixes via `dhq_complete(prefer_agent="F.O.R.G.E.")`.
- **Convergence with Track A:** Task 5's driveable build loop + Track A Task 9's `pull_repair_work` handoff are the same engine path — Code Health findings become tested PRs surfaced in the TUI, human-merged.

**Placeholder scan:** Go-internal and engine-internal tasks carry an explicit "read file X to confirm the pattern" first step (Tasks 3/4/5/6) because those internals were mapped but not read line-by-line; the representative code is anchored to the identified files and the tests pin the contracts. Two platform-side touchpoints are flagged as small follow-ups (`/api/internal/session-link`, and `/api/internal/dhq/chat` which already exists) rather than silently assumed.

**Type consistency:** frame types (`ProgressMsg`/`ResponseMsg`) defined in Task 4 are extended (not renamed) in Task 7; the engine `response` frame keys (`content`, `dispatch_target`→`agent`, `node`, `model`) match between engine (Tasks 3/7) and TUI `parseFrame`. `session_id` is the single correlation key across comms, engine, and MCP.

**Known cross-repo risk called out:** engine/TUI changes ship in `KytranKatarn/archie-code` (separate PRs), comms in the platform repo — the plan never mixes them in one commit, and every commit block names its repo.
