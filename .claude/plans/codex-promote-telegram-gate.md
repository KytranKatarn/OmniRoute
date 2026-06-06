# Codex → Telegram-approve → Production (implementation plan)

**Goal:** After you like a Codex change on sandbox, a **Telegram message to Kytran** with
Approve/Deny → on Approve: **merge the PR + deploy to production** (`platform.kytranempowerment.com`).

## What already exists (reuse — don't reinvent)
- **Approval + Telegram buttons:** `ai_bridge.agent_loop.request_approval(action_type, action_data,
  reason, requested_by, tier=2, priority)` → inserts `autonomy_approval_queue` row + sends Telegram
  with Approve/Deny (reaches all admins). `_process_approval_queue` (job) runs the consumer on approve.
- **Consumer dispatch:** big `if/elif action_type` in `agent_loop._execute_approved_action`
  (send_email, deploy_approve, restart_container, …). Add ONE `elif` branch for `codex_promote`.
- **Safe prod restart:** `scripts/safe_restart.sh` (health-check + AUTO-ROLLBACK via
  `backups/last_deployment.json`) + `deployment_watchdog.sh`.
- **PR merge:** `tools.repair_bay.services.github_service.merge_pr(pr, 'squash')` (in-container, API).

## What must be NEW
- **Trigger** `promote_codex_pr(pr_number)`: gather module + F.O.R.G.E. verdict + sandbox URL →
  `request_approval(action_type='codex_promote', action_data={pr_number, module, sandbox_url},
  reason=..., tier=2)`. (Callable by Claude on your word, or wired to the sandbox-preview step.)
- **Consumer branch** in `agent_loop._execute_approved_action` (additive `elif`):
  on approve → `merge_pr(pr_number,'squash')` → write a host deploy-request marker
  (e.g. `/mnt/archie_brain/.codex_deploy_request` with the module) → return merged result.
  ⚠️ The consumer runs IN-CONTAINER — it can merge (API) but CANNOT git-pull host / restart prod.
- **Host deploy poller** `scripts/agents/codex-prod-deploy.sh` + cron (every ~2 min):
  sees the marker → `git fetch && git checkout main && git reset --hard origin/main` →
  `bash scripts/safe_restart.sh` (auto-rollback on health fail) → verify
  `https://platform.kytranempowerment.com/tools/<module>` 200 → `telegram_service` "LIVE" → clear marker.

## Why deploy_approve can't be reused
`deploy_approve` deploys **Repair-Bay `improvement_proposals`** (file-diffs) via
`deploy_to_production(proposal_id)` + P.R.O.B.E. sandbox gate. Codex changes are **git PRs to main**,
not proposals — different mechanism. Hence the merge + git-pull + safe_restart path above.

## Risk (why this is the highest-stakes item)
1. **Edits the autonomy core** (`agent_loop.py`, ~5.5k lines, runs the whole scheduler). A syntax
   error breaks ALL autonomy. Verify parse + container health after the edit.
2. **Auto-deploys PRODUCTION** from a Telegram tap. Mitigations: 3 gates (F.O.R.G.E. + sandbox preview
   + Kytran tap) + `safe_restart.sh` auto-rollback. Still: must dry-run the deploy poller first.
3. **Host-execution split** (same as Phase B): consumer in-container, deploy on host.

## Safe build order
- **P1 (low risk):** trigger + `codex_promote` consumer branch = **merge on Telegram approve**.
  Verify: parse agent_loop, container healthy, simulate consumer (merge a test PR), confirm Telegram
  send. Deploy still done by Claude in-loop (`safe_restart` + verify) — NO new prod automation.
- **P2 (staged, tested):** host deploy poller + cron — DRY-RUN mode first (log only), then enable.

## Zero-build interim (works TODAY)
You tap a Telegram approve OR just say "ship #X" → Claude merges + runs `safe_restart` + verifies +
reports live. Human-in-loop, no new infra, no autonomy-core edit. The loop is already complete; this
plan only AUTOMATES the final hop.

## Status: PLAN. Prereqs (terminal, scope, F.O.R.G.E. auto-review, sandbox preview) all LIVE.
