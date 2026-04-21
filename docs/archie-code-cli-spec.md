# ArchieCode — OpenClaude Fork + Delegation Surface

**Project:** #276 · 2026-04-21
**Priority:** P10 · target: working Phase 1+2 by **2026-04-26**
**Authoritative spec.** Any deviation during implementation should come back and update this doc.

## TL;DR

Fork [Gitlawb/openclaude](https://github.com/Gitlawb/openclaude) → `KytranKatarn/archie-code-cli`, rebrand the binary as `archie-code`, and wire its defaults to the local A.R.C.H.I.E. platform (Ollama fleet on 192.168.1.200, MCP server with 103 tools, Department HQ dispatcher for escalation). The result is a second CLI — parallel to Claude Code — that Kytran can use to delegate work to A.R.C.H.I.E. directly, run locally against Ollama (zero cost), and invoke any platform capability (search_knowledge, create_task, propose_hire, run_misroute_audit, etc.) without ever leaving the terminal.

Two CLIs, two budgets, one platform:
- **Claude Code** — complex reasoning, architectural refactor, long-context multi-file work (Anthropic subscription)
- **ArchieCode** — routine edits, local Ollama-backed work, platform-integrated tasks (free — runs on hub)

## Why OpenClaude is the right base

| Feature | Why it matters for us |
|---|---|
| npm-installable TypeScript CLI | Fork + rebrand takes hours, not weeks |
| Native Ollama support via `OPENAI_BASE_URL=.../v1` | Zero adapter code for our Quadro M4000 fleet |
| **MCP client built-in** | A.R.C.H.I.E.'s 103 MCP tools plug in without us writing a bridge |
| gRPC headless mode (`localhost:50051`) | `archie_comms` (Telegram) can drive the same engine |
| Agent routing via settings.json | Explore → qwen2.5-coder, Plan → gpt-oss:20b, cloud via dispatcher |
| Bash / file / grep / glob / tasks / slash commands | Same surface Claude Code users expect |
| Apache-2.0 license | Fork is legally clean; must preserve attribution |

## Integration surface — what we plug where

```
┌────────────────────────────────────────────────────────────┐
│  Kytran's terminal                                         │
│  ┌──────────────┐        ┌──────────────┐                  │
│  │ Claude Code  │        │ archie-code  │  ← new           │
│  └──────┬───────┘        └──────┬───────┘                  │
│         │                       │                          │
│         │ MCP (stdio)           │ MCP (stdio)              │
└─────────┼───────────────────────┼──────────────────────────┘
          │                       │
          ▼                       ▼
    ┌────────────────────────────────────┐
    │ A.R.C.H.I.E. MCP server (103 tools)│
    │  search_knowledge, create_task,    │
    │  propose_hire, run_misroute_audit, │
    │  log_decision, store_memory, …     │
    └───────────┬────────────────────────┘
                │
                ▼
    ┌────────────────────────────────────┐
    │ Department HQ dispatcher           │
    │  • Welfare check                   │
    │  • Capability match                │
    │  • Agent selection (13 depts)      │
    │  • GPU-aware model routing         │
    │  • Tier escalation → cloud         │
    │  • C.R.E.E.D. ethics gate          │
    └───────────┬────────────────────────┘
                │
                ▼
    ┌────────────────────────────────────┐
    │ Ollama fleet on 192.168.1.200      │
    │  qwen2.5-coder:7b, gpt-oss:20b,    │
    │  mistral:7b, nomic-embed, etc.     │
    └────────────────────────────────────┘
```

Key principle: **archie-code never calls cloud APIs directly.** All cloud escalation goes through the platform's Bridge dispatcher so C.R.E.E.D. ethics + approval gating still apply. This also keeps cost tracking in one place (`bridge_jobs.cost_usd`).

## Phase plan

### Phase 1 — Fork + brand + local Ollama (this week, 2026-04-22 → 04-24)

| # | Task | Effort |
|---|------|--------|
| 2189 | Write this spec (doc) | small |
| 2190 | `gh repo fork Gitlawb/openclaude KytranKatarn/archie-code-cli` | tiny |
| 2191 | Rename binary `openclaude` → `archie-code`; keep `openclaude` alias | small |
| 2192 | Default config: `OPENAI_BASE_URL=http://192.168.1.200:11434/v1`, model=qwen2.5-coder:7b, optional `ARCHIE_MCP_URL` env | small |
| 2193 | `CLAUDE.md` → `ARCHIE.md` with Kytran platform rules + never-direct-cloud rule | small |
| 2194 | Install globally + smoke test (`archie-code "hello"` round-trips Ollama) | small |

**Exit criteria (Phase 1):** Kytran can run `archie-code` on his laptop, point it at hub, and chat with Ollama. No MCP integration yet.

### Phase 2 — Delegate to A.R.C.H.I.E. (2026-04-25 → 04-26)

| # | Task | Effort |
|---|------|--------|
| 2195 | Wire A.R.C.H.I.E. MCP server into archie-code settings | medium |
| 2196 | `/archie` slash command → invokes Department HQ dispatcher via MCP | medium |
| 2197 | Agent routing: Explore→qwen2.5-coder, Plan→gpt-oss:20b, cloud-via-dispatcher | small |
| 2198 | Telegram bridge hook (start/finish pings via platform's telegram_service) | small |

**Exit criteria (Phase 2):** `archie-code "use FORGE to review this diff"` dispatches the work through DHQ → FORGE → Bridge → Ollama/cloud → result streamed back to CLI. That's the full loop we want for the week.

### Phase 3 — Shared skill library (next week)

| # | Task | Effort |
|---|------|--------|
| 2199 | Consciousness ingest pipeline pushes skills to `~/.archie-code/skills/` in addition to `~/.claude/skills/` | medium |
| 2200 | skill-pipeline-test extended: pass/fail recorded per CLI | medium |
| 2201 | Adapt the 27 ARCHIE-flagged skills (likely mostly no-op) | medium |

Current state (from `.claude/rules/learned-skills.md`): 389 installed in Claude Code, 52 tested pass, 31 tested fail, 27 adapted for ARCHIE. Extending to archie-code should be mostly mechanical since both CLIs speak the same SKILL.md schema.

### Phase 4 — gRPC headless + A.R.C.H.I.E. Comms unification

| # | Task | Effort |
|---|------|--------|
| 2202 | archie-code gRPC server on hub (port 50051, systemd or docker-compose) | medium |
| 2203 | `archie_comms` Telegram bridge forwards to gRPC → unified engine for CLI + Telegram | medium |
| 2204 | Session summaries feed C.O.D.E.X. event-docs pipeline (reuses #2108) | small |

### Phase 5 — Division of labor

| # | Task | Effort |
|---|------|--------|
| 2205 | Decision doc: Claude Code vs ArchieCode use cases | small |
| 2206 | Handoff pattern: Claude plans → ArchieCode executes (one end-to-end example) | medium |

## Risks & gotchas

- **Name collision with completed #185** (`ARCHIE Code CLI — Branded Development Tool`). That project was a Claude-Code rebrand and shipped a package called `archie-code`. The new openclaude fork also wants that binary name. **Decision:** supersede the old one — it was never used in production per the current memory index. Archive the old npm package; publish the new archie-code under the same name. If old artifacts exist on npm, bump major version.
- **Ollama concurrency:** one more CLI hitting Ollama means more contention. `MAX_LOADED_MODELS=3` + `KEEP_ALIVE=5m` is already tight. If Phase 2 MCP round-trips spike load average, add ArchieCode traffic tracking in `ollama_lifecycle_telemetry`.
- **MCP auth:** the platform's MCP server currently assumes local trust. archie-code running on Kytran's laptop needs either a token handshake or a mesh-only endpoint. Mesh-only (via Tailscale 100.64.0.0/10) is simpler for week 1.
- **Upstream drift:** openclaude moves fast (465 commits). Plan a quarterly rebase cadence. Keep brand changes in a thin diff so rebases stay easy.
- **Skill path divergence:** openclaude reads from `~/.claude/skills/` **by default** too (per their README). If we point both CLIs at the same directory, we may get conflicts on skills that assume Anthropic API behavior. Use `~/.archie-code/skills/` separately and copy-on-write from the shared library.
- **SaaS model:** if Kytran wants to resell ArchieCode later, the fork's Apache-2.0 lets us relicense derivative work under any terms. But we must preserve openclaude's NOTICE file.

## Open questions (for decision this week)

1. **Repo location:** new top-level sibling to `archie_platform`, or nested under `/mnt/archie_brain/archie-code-cli/`? Recommend nested — simpler local dev.
2. **Telegram integration depth:** just start/finish pings (small), or full bidirectional (Telegram → archie-code gRPC)? Phase 2 picks start/finish; Phase 4 does full bridge.
3. **Cloud fallback authority:** can archie-code force cloud escalation without DHQ gate for routine queries? Recommend: NO. Always through dispatcher so cost and C.R.E.E.D. gate stay consistent.
4. **VSCode extension:** openclaude ships one in-tree. Rebrand now, or skip for MVP? Skip for MVP; revisit when Phase 4 is stable.

## This week's committed scope

Phase 0 + Phase 1 + Phase 2 = 10 tasks, all small/medium. Realistic 2–3 focused sessions. Exit criteria above per phase.

Phases 3–5 deferred to week of 2026-04-27 with the same project.

---

**This spec lives at `docs/archie-code-cli-spec.md`. Update it as we make design decisions rather than creating new notes.**
