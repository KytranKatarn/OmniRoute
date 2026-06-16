# A.R.C.H.I.E. Comms → Orchestration Cockpit — Plan (2026-06-16)

**Surface:** `archie.kytranempowerment.com` (container `archie_comms`, :3002, on the hub)
**Owner decisions (locked this session):**
1. **Front-end home = `archie_comms` (archie.*)** — build the cockpit into the Comms standalone (survives a platform crash, ADR-003; already dual-serves archie/claude + mints terminal tokens).
2. **In-page coding surface = embed the live ttyd Claude terminal** (`terminal.kytranempowerment.com` → tmux `claude-code` → `claude` CLI). Already running.
3. **Next "building machine" = `archie-tui` + her skills + the agent team, with Claude as an agent inside it.**

---

## Ground truth (from the 7-agent investigation, all evidence-cited)

- `archie_comms` is **healthy and live** (up, gunicorn, Beacon edge correct over mesh `100.64.0.4:3002`). Chat works (`dolphin3-8k`). The owner's "doesn't work" = the 3 Phase-0 defects, now fixed.
- **The vision is ~80% built** (Projects **#265** Unified Comms 4-phase + **#288** "ARCHIE Command Center" sub-projects A–E). Specs: `docs/superpowers/specs/2026-04-15-unified-archie-communications-design.md` + KB #256741 / #261453.
- **ttyd terminals are REAL + LIVE** (host systemd, not containers — why a container scan missed them): `terminal.*`→`:7681`→tmux `claude-code`→`claude`; `codex.*`→`:7683`→container `archie_codex_terminal`→`codex`. Auth = admin Basic-Auth OR one-time `?token=` minted by `POST /api/terminal/token`.
- **`archie-tui` is REAL but orphaned**: Go Bubble Tea TUI (`/mnt/archie_brain/archie-tui`) ↔ Python `archie_engine` (`/mnt/archie_brain/archie_engine`, ws:9090, running pid since Jun-04 but `ARCHIE_HUB_URL` unset → "Hub offline", idle since Jun-07, not in docker-compose, zero KB docs). It has full coding-agent machinery: file/git/shell tools, skill-sync from DHQ, an MCP server, a `claude/` escalation bridge, and a `hub/` connector.
- **Trace substrate already exists**: `task_execution_log` (tags Claude (CLI)/Codex (CLI)), `GET /api/dispatch/claude-feed`, `delegate_task` → `delegate_task_worker`.

---

## Phase 0 — Unblock + repair (DONE — PR #1739, live-verified)

- ✅ `INTERNAL_API_KEY` added to `archie_comms` env → delegation + repair-count auth (was 401).
- ✅ `save_message` double-def shadow removed → conversation history persists with correct columns.
- ✅ `.comms-panel` CSS added → header pinned, tab switching works, placeholders styled (no more stacked/unstyled spill).

---

## Phase 1 — Make the cockpit panels real (the "review it back in front end")

Goal: every panel on `/chat` shows live data; no 404s; the page is a true command center.

| Item | Problem | Fix |
|---|---|---|
| Ops summary panel | `GET /tools/department-hq/api/dispatch/ops-summary` → **404** (platform endpoint, not on comms) | Add a server-side proxy route in `app_comms.py` (`/api/ops-summary` → mesh `http://100.64.0.4:3000/...` with `INTERNAL_API_KEY`), OR point the JS at an existing comms endpoint. **Never call the public hostname.** |
| Alerts panel | `GET /api/alerts/unified` → **404** | Same: proxy to the platform alerts endpoint over mesh, or wire to `director_reports`. |
| Agent Activity | Works (lists agents) | Add live shift-state dots + last-activity from `agents` / `task_execution_log`. |
| `OLLAMA_HOST` | uses hub LAN IP `192.168.1.200:11434` (works co-located; latent mesh-smell) | Switch to mesh `100.64.0.4:11434` for correctness (low priority). |

**Deliverable:** a clean `/chat` with no console 404s, live ops/alerts/agent panels.

## Phase 2 — Delegation-in-chat + live team trace (Project #288 Sub-C)

Now that `INTERNAL_API_KEY` works, wire the "delegate to her team + watch it happen" loop:
- In chat, `/delegate`, `/review`, `/test`, `/plan` (the quick-action buttons already exist: Review Code / Run Tests / Plan Feature) → `POST /api/internal/delegation/submit` → `unified_tasks` → `delegate_task_worker` → DHQ → fleet agent.
- Surface **delegation cards** (status: queued → running → done, with `work_notes`) in the chat stream.
- Add a **live dispatch/trace feed** panel sourced from `task_execution_log` + `claude-feed` so the owner can *watch* the A.R.C.H.I.E. team (and Claude/Codex) working — module_source, agent, model, tokens, duration.

**Deliverable:** ask A.R.C.H.I.E. in-page to delegate work; see the team execute it, traced.

## Phase 3 — `archie-tui` as the "building machine" (with Claude as an agent inside)

The owner's core next vision. Revive the orphaned `archie_engine` and make it the orchestrating build engine, reachable from the cockpit.

1. **Connect it to the hub**: set `ARCHIE_HUB_URL=http://100.64.0.4:3000` (mesh) → its `hub/connector` + `hub/sync` + skill-sync activate; inference routes through DHQ (not direct Ollama); `claude/escalation` can pull Claude in.
2. **Containerize it**: add `archie_engine` to `docker-compose.yml` (restart policy, healthcheck, joins `archie_internal`), so it survives reboot and is managed like every other service.
3. **Embed the coding surface in the cockpit**: the **Claude TTY** tab already embeds the live ttyd Claude terminal (decision #2) — wire it fully (token-mint SSO + iframe). This is "Claude coding on her page."
4. **Claude as an agent inside the build machine**: `archie_engine`'s `claude/` bridge + the `task_execution_log` `request_origin='claude'/'codex'` tagging let A.R.C.H.I.E. orchestrate her agent team *and* Claude/Codex on a coding task, all traced on the cockpit.
5. **Document it** (currently zero KB coverage): ADR + coder/user vault_notes via C.O.D.E.X.

**Open question for the owner (Phase 3 kickoff):** revive `archie_engine` as a hub-connected service now, or keep the ttyd Claude terminal as the only in-page coding surface for the near term and revive the engine later? (Decision #2 says ttyd-first; this is about *when* to wire the engine.)

## Phase 4 — History + Collaboration tabs (currently "COMING SOON")

- **History**: real conversation archive (now that saves are fixed) — search/filter/revisit `unified_conversations`/`unified_messages`.
- **Collaboration**: trio sessions (Kytran + A.R.C.H.I.E. + Claude) via the existing `collaboration_engine` + `claude_bridge` SSE.

---

## Cross-cutting rules (do not violate)

- **Mesh-only** for any comms→platform/Ollama call: `http://100.64.0.4:3000` / `:11434`. Never the public hostname (CDN 60s cap).
- **Read-only rootfs** on `archie_comms` → code/static changes need `docker compose up -d --build archie_comms` (not `docker cp`).
- **Chat voice stays direct-Ollama** (ADR-013 waiver) so A.R.C.H.I.E.'s voice survives a platform outage; only *delegated work* + traces touch the platform API.
- Branch → PR → F.O.R.G.E. review → merge. Document every merge via C.O.D.E.X.

---

## Status / next

- Phase 0: **shipped** (PR #1739, live-verified).
- Recommend Phase 1 next (kill the 404s, make panels live) — small, high-visibility.
- Phase 3 is the big one (the "building machine") — needs the owner's "when" decision above.
