# Dev HQ coordination, contract surface, traps

**Reference for `archie-lane-ship`.** Split out so the skill file itself fits a review pass window. The SKILL.md carries the decision rules; this carries the detail.

---

## 6. Dev HQ / KB coordination (verified for THIS lane, 2026-09-23)
**Denied MCP reads (encoded fallbacks — do not retry blindly):**
`get_current_work`/`get_work_history`/`get_my_tasks`/`get_projects_brief`/
`get_activity_feed` → permission denied (work_sessions, unified_tasks,
unified_projects, project_activity). Continuity comes from
`/opencode-home/data/archie-handover.md` (refresh at EVERY session end) + task
prompts that arrive inside delegated work.
**Works:** `search_knowledge`/`search_mistakes`/`recall_context`/
`get_recent_activity`/`get_knowledge_stats`/`session_briefing` (KB-first, always —
290+ recorded mistakes); `add_task_note` route reachable (verify param quirk
"note text required" against a real task); `set_task_status` on unknown id →
denied ⇒ unified_tasks writes likely blocked too.
**When a real task id is known (delegated work):** search KB first → do work →
`add_task_note(id, note=what/what-found/what-left)` → `set_task_status` → record
decisions via KB flows; if writes deny, put the same content in the handover
§ Next-actions and TELL the owner which Dev HQ updates are pending (owner/host
must GRANT the lane's MCP identity on unified_* to match Claude-CLI — open ask).
Fleet doc queue after merges: `delegate_task_to_fleet(capability='documentation',
reason=...)`.

## 7. Contract surface (site ↔ KBS ↔ Account Center)
Per `GAP-MATRIX.md` §E (`/home/node/design/`): store cart, `/billing/checkout`,
login/signup redirects, `return_url`s = KBS/CRM + Account Center contract — never
client-ize (ke-cart mock rejected), never strip params; Account Center
`access_grants`/dispatcher themselves are OUT of lane scope (record only).

## 8. Traps (paid lessons)
- `_lane_ship` files vanish between runs ⇒ regenerate from a script, keep patches
  gitignored; `translations.json` newline dirt and `ds-bundle/` (gitignored) must
  never enter a site patch; `blocked.html` has no nav by design; `index.html` nav
  is at line ~670 outside the swept region (don't duplicate `backToTop`).
- `var(--accent-primary, …)` is never defined ⇒ its fallback literal renders live.
- Host `gh` is unauthed (by design); `gh pr create` in the runner never fires.
- archie_platform rootfs read-only ⇒ stdin scripts only; token never leaves it.
- Scope: deny-by-default (`config/agents/opencode.yaml`; `website/` allowed
  2026-09-23). Out-of-lane stale docs (report, don't edit): `AGENTS.md`,
  `opencode/Dockerfile.terminal`, `scripts/agents/opencode-lane-sync.sh`.
