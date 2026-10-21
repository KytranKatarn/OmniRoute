# DS9 final gates: deployment and client sandbox acceptance

Status: deployed with explicit owner authorization on 2026-10-21. See
[the deployment record](../audits/2026-10-21-ds9-deployment.md) for the final
running artifacts, live verification, rollback and remaining task 7405. The
sections below retain the preparation context; their pending wording is historical.

## 7379: adapter deployment candidate

The three-file patch from commit `44470824c` applies to the existing deployed
revision `3834805e`. Do not deploy the newer upstream release branch: the existing
checkout is thousands of commits behind it.

Candidate: `/mnt/standalone/deep-space-9/.claude/worktrees/ds9-7379-deploy-candidate`,
branch `fix/ds9-7379-deployed-revision`. It includes copies of the seven existing
branding changes. Their original SHA-256 hashes are recorded privately in
`codex/patches/ds9-7379-branding-baseline.json`. The shared checkout is untouched.

Both focused suites pass on this exact revision: 44 tests, zero failures. The
production build passed with a candidate-local DATA_DIR and the project's
build-time database stubs. A standalone smoke test on loopback port 20139 with
scratch data returned 200 for /api/health and /login, and 401 for unauthenticated
/v1/models. No production credential was supplied. All seven shared-tree branding
hashes remain unchanged. Deployed acceptance remains outstanding.

Activation requires preserving the old standalone build, checking native module
resolution and migration compatibility, then restarting only deep-space-9.service.
Keep ds9-codex-appserver.service, its isolated login and its read-only policy intact.
Check a real response's output-token count and structured result replay through
the running gateway. Roll back to the old build if startup or acceptance fails.
Never print the gateway unit's environment: it contains an inline encryption key.

## 7381: resolved by OpenCode; independently verified

A fresh Dev HQ read revealed OpenCode already completed this task by installing
uidmap helpers and using the existing system-bwrap profile. No additional
AppArmor attachment is needed. A direct bundled-bwrap probe still fails, but that
is not the path selected by the working CLI.

Codex independently ran the actual pinned 0.163.0 binary's sandbox subcommand:

- read-only: read an unpredictable local fixture successfully;
- read-only: touch was denied and no file was created;
- workspace-write: copied the fixture into a new file, verified independently.

No inference, sandbox bypass or host policy modification was used. The original
proposal for a bundled-bwrap profile is withdrawn. This verifies the actual CLI's
sandbox runner; fresh DS9-mediated client file acceptance remains separate.

## 7380: host gate completed; container follow-up remains

Dev HQ now records host gate 7 as completed by OpenCode. Preserve that completed
record; the container follow-up below remains outstanding.

Observed container runtime: Codex 0.154.0; old base URL points to port 20128; model is
auto/coding:free; no host.docker.internal mapping. The launcher ignores those
provider settings and uses the built-in provider. Updating environment alone
cannot activate DS9. The container's clone is currently clean on main.

Required scoped changes:

- Add a dedicated DS9 profile using the Responses protocol, cxa/gpt-6.1-sol and
  http://host.docker.internal:20129/v1. Preserve the ordinary direct profile.
- Mint a separate container key via POST /api/keys with restricted model and
  connection lists and self:usage scope. Verify stored camelCase restrictions
  and a denied model. Mount as a Docker secret; never use the shared platform key.
- Add and verify the host alias, and remove stale inherited inference settings.
- Make startup preserve an existing workspace branch and uncommitted changes;
  the current init script resets the clone to origin/main on every restart.
- Replace the current sandbox-bypass launch with on-request/workspace-write and
  independently establish whether the container supports that sandbox. It has
  docker-default AppArmor, cap_drop ALL and no PATH bwrap. A host profile does not
  automatically solve container sandboxing. Do not add broad privilege or disable
  sandboxing to make the test pass.
- Correct claims that this container has no host filesystem access: its host
  repository and Docker socket mounts already confer host-equivalent authority.

After preserving active sessions and workspace state, recreate only the Codex
terminal. Verify the selected profile, credential restrictions, fresh session,
resume and an actual outer-client file read/edit. Keep incomplete gates open in
Dev HQ and record exact blockers rather than marking transport-only checks as
coding acceptance.
