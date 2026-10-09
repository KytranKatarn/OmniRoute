# Planned Code Health repairs

Status: handoff, reviewed PR/artifact reconciliation, and multi-file completion
verification implemented; dispatch OFF. Safe unclaimed-task cancellation/retry is implemented. Failed-worker and closed-PR
recovery plus the live pilot remain pending. This is a repository design
artifact requested by the owner, not a claim of Dev HQ or KB persistence.

## Problem and outcome

The mechanical drain and engine deliberately refuse LARGE_FILE and
SQL_INJECTION_RISK. Approved findings have no executable planned-work handoff.
Adding those classes to the mechanical allowlist would reintroduce unsafe fixes.

The target workflow is finding → planned task → isolated coding → tests → PR →
F.O.R.G.E. review of the current head → human merge → deployment evidence → module
QA → original-finding verification. A coding task completing is never proof that
a repair is live. Protected oversight targets remain human-led work.

## Phase 1: explicit handoff (this PR)

- Classify findings with current canonical source resolution, Codex scope and the
  existing target-based governance exclusions. No scope widening.
- Expose an admin-only planned-refactor action for approved LARGE_FILE findings.
- Keep `code_health_planned_repairs` disabled by default, visible in Work Control.
  Do not enable it before phases 2–3 and the pilot below pass.
- Lock the proposal and create the `codex_task` plus `planned_repair.task_id` link
  in one transaction. The task is deferred to the existing host worker. Repeated
  requests return the same task, including failed/cancelled tasks; never silently
  start another attempt. Insert/link failures roll back together.
- Preserve proposal status and existing scan counts. GET progress reads the
  linked task and its PR number without mutation or inference.
- A missing task is blocked. Task completion means awaiting verification.
- SQL assessment dispatch stays refused: the worker currently expects a PR, so a
  no-change assessment would otherwise be falsely reported as blocked.

## Phase 2: coder results and PR linkage

The initial implementation polls the trusted host worker's task writeback rather
than accepting callbacks. It verifies task/proposal association, repository and
branch, complete bounded file inventory, every changed/renamed path against current
scope and governance, and an approved current-head review. Reviewed blobs are
verified against Git object hashes before SHA-256 manifests are recorded. A final
head check and locked task/proposal/review comparison reject stale snapshots.
The proposal enters `pr_open` with `apply_mode=planned_codex_pr`; it is never marked
deployed by this step. Reconciliation runs before the existing drain admission
switch, bounded to three proposals per cycle. No worker harness changes are used.

Post-merge P.R.O.B.E. found the hub does not mount the root config tree. Read the
real local scope file where present, otherwise the exact tracked
`HEAD:config/agents/codex.yaml` through the existing .git mount. Unavailable or
invalid policy fails closed; no copied allowlist or mount change is introduced.

Manifest refresh after later pushes and completion retries are implemented below.
Safe unclaimed-task recovery is implemented below. Failed-worker and closed-PR
replacement remain pending. Keep dispatch disabled.

Use a platform-owned reconciler in a scheduled background job; no GitHub reads,
inference or sandbox operations in request handlers. A task result must carry
proposal/task IDs, attempt ID, outcome, branch, repository, PR and head SHA.
Authenticate callbacks and verify association server-side; never trust a browser
supplied fingerprint or PR number as proof. Worker changes under scripts/agents
need the authorized maintainer lane; Codex must not edit its own harness.

For a PR outcome, verify the repository, branch/task association, canonical
changed paths, lane scope and governance. Persist a complete artifact manifest
from the exact reviewed commit: additions/modifications/deletions/renames and
hashes for every final file. Treat incomplete/paginated GitHub results as unknown.
Do not relabel Codex PRs as engine-authored to reuse `record_engine_pr`.
Reuse the repair merge sweep after legitimate registration, preserving its
closed-unmerged recovery. Claims need durable leases and attempt history;
callbacks from an older attempt cannot overwrite a newer attempt.

## Phase 3: verification and recovery

Implemented completion slice: the bounded scheduler refreshes manifests against
current-head approval, records GitHub merge SHA/time, and calls the scoped internal
web verification endpoint. It runs independently of new-work admission and preserves
operator-visible errors. No new worker attempt is launched. The serving process
checks merge ancestry, exact bytes for every present artifact, absent removed/old
renamed files, runtime after merge and file modification, Python syntax and the
600-line limit across extracted files, original finding, and fresh active QA for
each affected module. Platform core files use the existing `app` QA mapping.
Artifacts outside the serving product have no runtime mapping and fail closed.
A second local verification after QA rejects deployment changes during collection.
`PLATFORM_INTERNAL_URL` (or `BRIDGE_URL`) and `INTERNAL_API_KEY` must be configured;
only mesh endpoints are accepted and redirects are refused. Missing configuration
blocks completion visibly; no credentials or infrastructure are changed by this PR.

Implemented recovery slice: admin cancellation locks the proposal and task against
the host worker's atomic `deferred` claim. It only cancels an associated task with
no PR/branch or patch workflow. A server-owned marker proves this cancellation;
explicit retry accepts only that cancelled attempt, rechecks current governance,
scope and dispatch admission, preserves history, and links the new task in one
transaction. Expected task IDs reject stale clicks; failures roll back together.
Cancellation remains available while admission is paused. These controls do not
change finding counts or close proposals.

Remaining: failed-worker stop evidence and closed-PR replacement. The current host
worker can be marked blocked by stale-task cleanup without proof it exited; this
UI must not launch a replacement from that status. A maintainer change under
`scripts/agents/` must supply durable attempt/worker-stop evidence before such
retry can be safe. Codex must not edit its own harness. The live pilot remains
gated; dispatch stays disabled.

Extend the existing completion authority for manifest-backed planned repairs;
retain existing single-file receipts. Check the deployed commit and all manifest
artifacts, including absence of deleted files, in the serving environment. Prove
fresh runtime where imports require it, then passing active module suites after
deployment and the original finding's disappearance. For a refactor, also scan
new files so merely moving the oversized body does not count as a repair.

Schedule bounded verification retries independently from dispatch admission.
Pausing new work must not stop tracking active PRs or verifying deployments.
Do not restart while a native F.O.R.G.E. review is running.

Explicit recovery actions must preserve history: retry failed task, withdraw
unclaimed work, replace closed-unmerged PR, and reverify failed deployment/QA.
Never infer success from a timeout, absent callback or unavailable GitHub/QA.
Human merges performed outside the promotion consumer still need reconciliation.

Approval-queue tiers and PR merge tiers are separate. Promotion messages must
describe the evidence actually available. Do not claim sandbox preview/testing
from the presence of a default URL. Never bypass a refused review or merge gate.

## Phase 4: security assessment

Add typed results: confirmed vulnerability, evidence-backed false positive,
needs more context, or blocked. Assess bound values, identifier allowlists and
input data flow. A confirmed vulnerability takes the tested PR path. A safe-query
assessment needs human approval tied to a source fingerprint and detector version,
with reevaluation on relevant code change. Preserve the original issue/history;
do not disable the detector or rewrite safe SQL to reduce the count.

## Acceptance and rollout

Before enabling dispatch, prove transactional duplicate protection with concurrent
requests, rollback after each write, protected/scope refusal, login/admin gates,
and no inference in the HTTP handler. Mutation checks must make the regression
tests fail in a copy. Test DOM behavior for disabled, queued and blocked states.

Then prove one approved, unprotected Department HQ refactor through the real UI,
host worker, tests, native F.O.R.G.E., human merge, authorized deployment, fresh
P.R.O.B.E. module QA and re-audit. Capture task/PR/commit/manifest/runtime/QA
receipts. Test duplicate callbacks, worker timeout, stale review, closed PR,
changed deployment artifacts and failed QA. None may close a finding falsely.

Only after that pilot add bounded automatic planned-work admission. Use explicit
capacity limits and welfare/cost controls, with operator-visible blocker reasons.
Keep protected targets and security dispositions out of unattended coding.

## Failed-worker and closed-PR recovery findings

The general delegation retry API could bypass Repair Bay's stop-evidence refusal
by putting a blocked planned `codex_task` back in `deferred`. The generic stale
reclaimer also considered host-owned Codex tasks absent from its own live-id set,
then wrote `pending`; the hub pending selector accepted that wrong queue state.
The ownership fix refuses generic retry for tasks carrying `repair_proposal_id`,
excludes Codex tasks from generic stale reclamation, and excludes them from the
hub pending selector. Ordinary hub work and legacy manual Codex retry behavior
remain supported. No existing task is rewritten by deployment of these filters.

Read-only PostgreSQL verification used the actual candidate SELECT statements
against synthetic CTE rows: ordinary hub and missing-capability rows stayed
selectable; planned/legacy Codex rows were excluded, with and without PR metadata
and with a live-id exclusion. Removing the predicate admitted host-owned tasks.
No production rows were selected for mutation or changed by this verification.

### Maintainer-owned worker contract (required before failed-worker retry)

The change belongs in `scripts/agents/codex-delegation-worker.py` and the runner's
process lifecycle; Codex scope explicitly blocks this directory. Do not replace
that change with guessed timestamps or an operator checkbox in the web app.

1. Atomically claim with a unique attempt ID, host/process identity and generation;
   publish a durable claim/lease before starting execution. Missing or expired
   heartbeat means unknown, never proof of exit.
2. On timeout, stop and reap the entire execution process group, including child
   runners. Confirm no surviving descendants or outstanding PR fallback operation
   before emitting a server-owned terminal receipt. Merely catching TimeoutExpired
   or writing `blocked` is insufficient.
3. Bind every status/PR writeback and stop receipt to task ID plus attempt ID using
   compare-and-set. An older process cannot overwrite a newer attempt or register
   its PR on a replacement. Preserve PR/branch evidence even on partial failure.
4. Only accept a retry after validated terminal evidence and an operator request,
   rechecking Repair Bay governance, current scope, admission and proposal identity.
   Allocate the replacement and preserve prior evidence in one transaction.
5. Test a live process after the nominal timeout, a surviving child process, lease
   expiry without exit, stale callback, partial PR creation, repeated requests,
   rollback, and concurrent cancellation/retry. Every unknown state must refuse
   replacement and remain visible.

### Closed-unmerged PR contract (implementation still pending)

The existing merge sweep preserves PR metadata and changes the proposal to
`fix_requested`; planned completion polling currently selects only `pr_open`.
That is a recovery gap, not evidence that the original finding is fixed. Never
clear the old PR fields and feed the proposal into ordinary mechanical retry.

Implement an explicit admin replacement request carrying expected task/PR IDs;
let a bounded background consumer perform the GitHub reads. Verify repository,
branch, task/proposal association, current head, `closed` and not merged, and
recheck immediately before accepting replacement. Unavailable, reopened, merged,
foreign or changed PRs must refuse that replacement. Reopened/merged PRs should
resume their original reviewed-manifest and completion path instead.

Retain the old task, PR, head, manifest, review and closure evidence in immutable
attempt history. Require worker completion/stop evidence, renewed finding approval,
current scope/governance, and enabled admission. Allocate/link the new attempt
atomically, with stale-request protection and no original-finding closure.
Preserve an operator-visible blocker when dispatch is paused or proof is missing.
Test close/reopen races, merged-after-close, changed head/task, stale requests,
missing GitHub data, duplicate requests and failed insertion/link writes. Keep
planned dispatch OFF until these contracts and the live pilot are proved.
