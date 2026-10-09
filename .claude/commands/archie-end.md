# A.R.C.H.I.E. Session End — Full Close-Out Protocol

Complete end-of-session ritual. Saves everything, commits, provides a clean handoff. Pushes follow the rate-respect policy — not a blanket freeze.

## Step 0: GitHub Rate Check

Run `gh api /rate_limit` before any push. `core` remaining > 4,000 = safe. If below 1,000 or you see a 403 secondary-rate-limit today, hold pushes for 60 min.

## Step 1: Commit All Work + Push

```
1. Run `git status` — check for uncommitted changes
2. If changes exist: stage, commit with descriptive message
3. Push to current branch (respect rate-check from Step 0)
4. If the branch is ready for review, open a PR with gh pr create
5. If on a feature branch with a PR: note the PR number and status
6. Prefer batching several branches into a single PR where they share a theme
```

## Step 2: Complete Dev HQ Tasks

```
1. `mcp__archie__complete_task` for any tasks finished this session
2. `mcp__archie__log_decision` for any architectural choices made
3. `mcp__archie__update_project_understanding` for projects worked on
```

## Step 3: Store Memories

```
1. `mcp__archie__store_memory` — any important learnings (use mistake_learned for errors)
2. Update MEMORY.md if new memory files were created
```

## Step 3a: Consciousness Doc Refresh — HARD GATE (session is NOT done until this passes)

> **If you skip this step, the session close-out is INCOMPLETE.** High context is not an excuse. Low time is not an excuse. Two vault_notes per substantive PR is the minimum floor — no exceptions.

The Consciousness module is how both end-users and coders (future Claude, future devs, agent loops) discover what the platform can do. If you ship a PR and don't leave a searchable doc, the work is effectively invisible next session.

**Walk every PR shipped this session.** For each, confirm the KB has at least two `vault_note` entries, and update the capability index when operational surface changed.

Per-PR checklist — ALL four must be checked before proceeding to Step 4:
- [ ] **User-facing vault_note** — *What can the user now do? Where in the UI? How is it triggered?*
      Tags: `["user-doc", "project-<id>", "pr-<n>"]`
- [ ] **Coder-facing vault_note** — *What's the contract?* (endpoint path + method + body + response shape, OR service function signature + side effects + preconditions)
      Tags: `["coder-doc", "project-<id>", "pr-<n>"]`
- [ ] **Capability index** — If the PR added/removed/renamed a route, tab, service, or DB column, edit the module's curated notes via `platform_registry_service.set_notes(module_id, text)` (NOT `docs/generated/module-capability-index.md` by hand — it is regenerated; run `scripts/generate_registry_docs.py` after). The generated index is no longer auto-loaded; it is searchable via `search_knowledge(category="module_capability")`.
- [ ] **Mistake_learned** — Any 2+ step debug loop or "this was harder than it should have been" moment gets its own entry so we don't repeat it.

**Self-check before moving on:** State out loud: "I have written [N] vault_notes for PR #[X]." If N < 2, stop and write them now.

MCP call shape (copy-paste friendly):
```
mcp__archie__store_memory(
    memory_type="vault_note",
    title="<feature> — <user|coder> reference (PR #<n>, <YYYY-MM-DD>)",
    content="<markdown>\n## Summary\n…\n## API contract / UI entry point\n…\n## Examples\n…",
    category="<project-slug>",
    tags=["user-doc" OR "coder-doc", "project-<id>", "pr-<n>", <module tags>],
    importance=0.75  # 0.9 for frequently-referenced surfaces (public API, core service)
)
```

Two vault_notes per substantive PR is the floor. Quantity-over-verbosity — they get embedded and semantically searched, so many small, focused notes beat one giant one. Skipping this step fails the close-out.

## Step 4: Update Session Handoff

Edit `~/.claude/projects/-mnt-archie-brain/memory/project_session-handoff.md` with:
- Complete list of what was done
- Clear "first steps next session" with specific commands/actions
- Any blockers, critical issues, or debugging context
- Key technical notes (paths, IDs, gotchas)

## Step 5: Session Stats

Print a comprehensive session report:

```
## Session Complete

**Duration:** [start time] — [end time]
**Branch:** [branch name]
**Commits:** [count] ([files changed], +[insertions]/-[deletions])
**PR:** #[number] ([status])

### Completed
- [bullet list of what was done]

### Decisions Logged
- [ADR numbers and titles]

### For Next Session
1. [first priority]
2. [second priority]
3. [third priority]

**Plan tier:** Max 20x | **Session usage:** [if known]
```

## Step 6: Final Note

End with: "Session saved. Next session: start with `/archie-boot` or `/archie-resume`."
