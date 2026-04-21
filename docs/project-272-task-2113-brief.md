# Project #272, Task #2113 — Session-Level Learning via C.O.D.E.X.

**Status:** Scoping brief · 2026-04-21 · not yet implemented
**Source of truth on pieces already shipped:** this doc, audited against code on 2026-04-21
**Intended implementor:** next session (fresh context) or a subagent following this brief

## TL;DR

C.O.D.E.X. already auto-documents **decisions** (`project_decisions` → `vault_note` via `_run_codex_event_docs` at `ai_bridge/agent_loop.py:3720`, every 30 min). This task extends the same pattern to **session-level artifacts**: for each Claude session, synthesize a compact learning summary and store it in KB so the next `session_briefing` call retrieves it automatically.

**Gap:** there is no structured record that captures what a session shipped, what it learned, and what to avoid next time. The `project_session-handoff.md` file that the session protocol references is **manual** — written by Claude only when it remembers to. When Claude forgets (common), the next session starts cold.

## What's already built

### Hook infrastructure — `platform_v2/scripts/hooks/`

| Hook | Role |
|------|------|
| `session_start_hook.sh` | Runs at session boot; handles briefing/memory load |
| `session_end_hook.sh` | Runs at session close; currently ingests raw transcript (see `post_session_ingest.sh`) |
| `post_session_ingest.sh` | Pulls a session transcript into KB as raw `conversation_memory` |
| `task_sync_hook.sh` | Syncs tasks between Claude TaskWrite and DHQ |
| `memory_context_hook.sh` | Pre-compact context loader |
| `pre_compact_hook.sh` | Context summarizer before the model auto-compacts |
| `error_learning_hook.sh` | Captures errors into `mistake_learned` KB rows |

**Important:** hooks already HAVE DB access (each uses the standard `DB_PASSWORD_FILE` secret-file pattern mirrored from `services/dispatch_service.py`). A new hook or extension to `session_end_hook.sh` can directly insert a structured summary.

### Existing C.O.D.E.X. pipeline — `platform_v2/services/codex_event_docs_service.py`

Reads rows from `project_decisions` where no matching `vault_note` exists; templates a doc-style note per decision; writes via `store_memory(knowledge_type='vault_note')`. Template-based — no LLM call. Runs every 30 min.

This is the reusable pattern: **event source → template → vault_note**. Session learning just uses a richer event source (session transcript + task log + git activity + decision log).

### What `session_briefing` already surfaces

`mcp__archie__session_briefing(topic)` already pulls `conversation_memory` rows in its knowledge_context. If session summaries are stored as `vault_note` + conversation_memory with the right tags, they surface automatically at the start of the next session — no code changes to the briefing path.

### Raw ingestion (already shipped)

`post_session_ingest.sh` already writes the raw transcript as `conversation_memory`. **That's the haystack, not the needle.** Today a fresh session can technically search it but the signal is buried in thousands of lines of tool output and intermediate back-and-forth.

## The gap

What's missing is a **synthesis step** between "raw transcript ingested" and "future session briefed":

1. **Per-session extraction** — turn a session's artifacts into a 10-line digest: what shipped (PRs/commits), what broke (errors), what decisions were made, what the user re-iterated as preference.
2. **Structured storage** — one `vault_note` per session with consistent tags (`session-summary`, `project-<id>`, ISO date) so retrieval is predictable.
3. **Ranking** — importance_score biased high (0.9) for session summaries so they surface above raw transcript chunks in semantic search.

## Phase 1 MVP scope

### New file: `platform_v2/services/session_learning_service.py` (~120 LOC)

Reads session artifacts from 4 sources, produces one structured digest, writes one vault_note. Follows the `codex_event_docs_service.py` pattern — template-based, no LLM call for MVP.

```python
"""Synthesize a session-level learning digest from structured artifacts."""

def build_session_digest(session_id: str, cutoff_ts: datetime) -> dict:
    """Aggregate what happened in a session since cutoff_ts.

    Sources (DB-driven, no transcript parsing):
    - git activity:     git log --since=cutoff_ts --pretty=...
    - DHQ tasks:        unified_tasks.completed_at > cutoff_ts
    - decisions:        project_decisions.created_at > cutoff_ts
    - mistakes:         knowledge_base WHERE knowledge_type='mistake_learned'
                        AND created_at > cutoff_ts
    - autonomy jobs:    autonomy_loop_log WHERE created_at > cutoff_ts
                        (surfaces anomalies that fired during session)
    """

def save_session_digest(digest: dict) -> int:
    """Store as vault_note with tags=[session-summary, project-N, YYYY-MM-DD].

    Use importance_score=0.9, quality_score=0.85 (high recall priority).
    Title: 'Session {session_id} — {top-level accomplishment}'.
    """
```

### Edited file: `platform_v2/scripts/hooks/session_end_hook.sh`

At the very end (after `post_session_ingest.sh`), call:

```bash
python3 -c "
import sys
sys.path.insert(0, '/mnt/archie_brain/platform_v2')
from services.session_learning_service import build_session_digest, save_session_digest
from datetime import datetime, timedelta

digest = build_session_digest(
    session_id='$SESSION_ID',
    cutoff_ts=datetime.utcnow() - timedelta(hours=6),  # session window
)
if digest['items_count'] > 0:
    note_id = save_session_digest(digest)
    print(f'Session digest saved as vault_note #{note_id}')
"
```

### Verification path (no new code — reuses existing pieces)

1. First session ends → hook fires → digest inserted as vault_note
2. Next session starts → `session_briefing` semantic-searches KB → digest surfaces in `knowledge_context`
3. Fresh session reads the digest and picks up with the right context
4. Repeat — each session leaves a breadcrumb for the next

## Phase 2 extensions (separate follow-up tasks, not in MVP)

| Extension | Source | Lift |
|-----------|--------|-----:|
| LLM-written narrative | Bridge dispatch to C.O.D.E.X. with the raw digest | medium |
| Cross-session threading | Link digest to previous session digest by topic tag | small |
| Handoff file rewrite | Replace manual `project_session-handoff.md` with auto-generated view | small |
| Learning rollup | Weekly aggregate of all session digests → `weekly-review` vault_note | small |

## Risks & gotchas

- **Hook re-entry:** `session_end_hook.sh` can fire on `/clear` or abnormal termination. Digest builder must tolerate a missing/empty cutoff window (return early with 0 items).
- **Importance bias:** session summaries weighted at 0.9 could crowd out other high-signal vault_notes in semantic search. Test with 5+ session summaries present; tune down if `session_briefing` gets noisy.
- **Transcript vs digest collision:** `post_session_ingest.sh` writes raw `conversation_memory`; this task writes synthesized `vault_note`. The two must have distinct tags or retrieval will return duplicates. Recommend prefixing digest tag with `session-summary-` vs raw transcript's existing tag (verify on first run).
- **Session boundary detection:** `SESSION_ID` must be stable for the hook to read. Check how current hooks resolve it — `session_start_hook.sh` should already set `$ARCHIE_SESSION_ID` in an env file.
- **Rehydrate risk:** if the digest is template-only, it may be too generic to help. The `reasons` + `decisions` fields must carry specific PR numbers, file paths, and named errors — otherwise it's no better than `git log`.

## Proposed subtasks under #272 (or a spun-out #275)

| # | Title | Est |
|---|------|----:|
| a | Verify session hook env contract (`SESSION_ID`, cutoff resolution) | 30 min |
| b | Author `session_learning_service.py` (4-source aggregator + template) | 2–3 hr |
| c | Wire into `session_end_hook.sh`; manual test with current session | 1 hr |
| d | Ingest 3+ session runs; verify `session_briefing` retrieval quality | 1 hr |
| e | (Phase 2) LLM narrative via Bridge dispatch; Phase 2 handoff rewrite | separate |

## Why this belongs to C.O.D.E.X.

C.O.D.E.X. owns the documentation pipeline (#2108 already ships). Putting session learning under C.O.D.E.X. keeps the ownership chain clean: decisions, auto-docs, and session digests all flow through one director; one rules file; one vault_note tag family. Consistent with the pillar-complete observer pattern (feedback_pillar-complete-observers) — one agent owns the observe→synthesize→publish loop.
