# DS9 gateway and Codex terminal deployment — 2026-10-21

Owner explicitly authorized deployment and the scoped container/credential changes.
No AppArmor or global user-namespace policy was changed.

## Running gateway

- Source fix: `2eeef0b602000753e691417e342964f46d596412`.
- Activated build: `FBLx77TZcg9tbvL6P1SHe`, built against the previously deployed
  revision plus the three-file adapter patch and existing branding.
- Restarted only `deep-space-9.service`; upstream service/login unchanged.
- Both services active; HTTP `/api/health` 200.
- 44 focused tests, production build and scratch health/auth checks passed.
- Live structured function-call/result replay recovered the unpredictable marker
  without issuing another tool call. Usage: input 228, output 27, total 255.
- No upstream branch upgrade; existing branding hashes and migration files preserved.
- Task **7379 completed** with deployed evidence.

Rollback build:
`/mnt/standalone/deep-space-9/.build/next.rollback-20261021-090751`.
Stop only the gateway, retain the current build under a new name, rename that
rollback directory back to `.build/next`, then start and check gateway health.
Deployment manifest and live evidence are in `codex/patches/ds9-7379-*.json`.

## Running Codex terminal

- Image: `sha256:ebc9cc43a477ebdab95ab76a7e890cb5a131fc82713eba5bf8942b290fb45dcc`.
- CLI pinned to the previously deployed **0.154.0**, avoiding an older shared base.
- DS9 profile: `cxa/gpt-6.1-sol`, Responses protocol,
  `http://host.docker.internal:20129/v1`, verified host-gateway alias.
- Dedicated credential created through `/api/keys`; stored model/connection
  restrictions and `self:usage` scope verified. A forbidden model was rejected.
  Only the key identifier is retained in private metadata; no credential in TOML,
  command arguments, Compose environment or this report.
- Docker secret source is root-owned, mode 0600: capability-dropped container root
  cannot read a host uid-1000-owned mode-0600 file. No broad read permission added.
- Launcher uses `on-request` and `workspace-write`; sandbox bypass removed.
- Existing workspace branch, clean status and SHA
  `1eda2e3cfa5c28aee5f854a4f1b7f89288e06394` preserved. Startup no longer resets it.
- Five focused configuration/workspace tests pass. The workspace regression also
  detects the original reset behavior. Shell syntax and diff checks pass.
- Final deployed CLI fresh session and separate resume passed the remembered marker.
  Session: `01a15ecf-4255-7dc3-892b-d520d7062fd9`.
- Terminal and gateway HTTP 200; final container running with zero restarts.

Ordinary direct-provider configuration remains available. The DS9 overlay disables
**design_systems MCP only**: enabling that tool set caused repeated bridge failures;
disabling only it made the same deployed client pass. This is a compatibility
limitation, not full MCP acceptance.

Rollback image: `archie_brain-archie_codex_terminal:rollback-ds9-20261021`.
Original scoped source/config files: `codex/patches/ds9-container-before/`.
Before restoring an old launcher, preserve the workspace: the old init script
resets its clone and the old launcher bypasses its sandbox. Revoke only the
dedicated container key if retiring DS9; leave the platform key and upstream login.

## Remaining acceptance — task 7405

- The actual host CLI sandbox runner passes read-only read/write-denial and
  workspace-write controls. A fresh DS9-backed host CLI fixture test still produced
  no outer command event or edited file and reported a namespace failure. Tool
  provenance/client relay needs investigation; do not change host policy blindly.
- The container's actual sandbox probe fails namespace creation under its existing
  Docker policy. No privilege or sandbox relaxation was added. Full coding
  acceptance remains blocked; text and resume success do not establish tool execution.
- Fix design-system MCP compatibility before re-enabling it in the DS9 overlay.
- Existing Archie KB bearer mount logs permission denied (host uid1000/gid1000,
  mode0640; container root has capabilities dropped). Its value and ownership were
  not changed here. Verify authorized MCP access separately.

Deployment diagnostics caught and corrected a malformed generated TOML section and
new-secret ownership before final acceptance. The final profile generation is tested;
the old failed client probes were stopped. No stale disposable smoke container remains.
