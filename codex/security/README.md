# Codex terminal namespace sandbox candidate (task 7405)

Review candidate; not activated on the running terminal. This configuration must
land together with the non-root image and persistent-storage preparation below.
The live repository and Docker socket mounts still confer host-equivalent
access outside Codex's sandbox. These policies do not turn that terminal into a
safe boundary for untrusted repositories.

## Provenance and policy changes

The base seccomp profile is vendored verbatim from Docker Engine commit
`83bca51` (the running 29.3.0 daemon),
`vendor/github.com/moby/profiles/seccomp/default.json`, dependency v0.1.0.
Source: https://github.com/moby/moby/blob/83bca51/vendor/github.com/moby/profiles/seccomp/default.json
The AppArmor candidate derives from the same commit's
`vendor/github.com/moby/profiles/apparmor/template.go`:
https://github.com/moby/moby/blob/83bca51/vendor/github.com/moby/profiles/apparmor/template.go
See LICENSE.moby for its Apache-2.0 license.

`codex-seccomp.json` retains the complete default profile and adds three constrained rules:

- `unshare` only for `CLONE_NEWUSER` by itself;
- `clone` only when the exact NEWUSER|NEWNS|NEWIPC|NEWPID|NEWNET set used by Codex is present (ordinary clones retain Docker's existing rules);
- `mount`, `umount2`, `pivot_root`, still constrained by kernel capabilities and
  AppArmor. No SYS_ADMIN or other initial-namespace capabilities are added.

The AppArmor profile retains Docker's proc/sysfs, signal and ptrace restrictions.
It permits user namespaces and the tmpfs/proc/devpts, bind/remount and propagation
operations needed by bubblewrap. It does not allow arbitrary filesystem types.
Namespace creation is newly available to the container user; this is an explicit
increase in kernel attack surface requiring security review. AppArmor remains in
**enforce** mode; seccomp remains an errno-default allowlist.

A per-binary AppArmor transition was investigated and rejected: Codex sets
no-new-privileges before executing bubblewrap, so the kernel denies a transition
that adds mount/userns permissions. Do not disable no-new-privileges to revive
that approach. The candidate uses one confined profile with bounded setup rules.

## Rehearsal evidence

The actual deployed image and pinned CLI 0.154.0 passed `probe_sandbox.py` in a
throwaway container as UID/GID 1000, with all capabilities dropped and
no-new-privileges. The container had no host mounts, secrets or Docker socket.
Network mode was none; inner AF_INET socket creation independently failed with
EPERM/EACCES rather than merely timing out. Workspace writes succeeded;
read-only writes, writes to a writable sibling outside the workspace and writes
to `.git` were denied. Independent checks confirmed denied files were absent.
The harness verifies UID, effective capability mask, no-new-privileges, AppArmor
attachment and seccomp filter status before testing.

Example after loading the named profile in a controlled rehearsal environment:

```sh
docker run --rm -i --network none --user 1000:1000 --cap-drop ALL \
  --security-opt no-new-privileges \
  --security-opt seccomp=codex/security/codex-seccomp.json \
  --security-opt apparmor=archie-codex-sandbox \
  --tmpfs /tmp:mode=1777 --tmpfs /work:mode=1777 \
  -e HOME=/work/home -e CODEX_HOME=/work/home/codex \
  --entrypoint /bin/sh "$REHEARSAL_IMAGE" \
  -c 'mkdir -p /work/home/codex; exec python3 -' \
  < codex/security/probe_sandbox.py
```

Use `apparmor_parser --skip-kernel-load` for syntax validation. Loading a new
named profile for the rehearsal does not replace Docker's default profile.
Unload the rehearsal profile after its containers exit. Do not restart Docker.

## Coordinated activation prerequisites (not performed)

1. Review this policy delta and the DS9 adapter patch. Apply/retest/build the
   separate DS9 candidate before activating the client path.
2. Inventory/backup only this terminal's persistent `/codex-home` and `/work`
   volumes. Preserve its existing repository, auth, skills, sessions and Git head.
   Change ownership of those dedicated volume contents to UID/GID 1000 while the
   terminal is stopped; do not traverse or chown the live host repository mount.
3. Update only the dedicated DS9 key file metadata from root:root 0600 to UID/GID
   1000 mode 0400 so the non-root launcher can read it. Preserve its bytes and
   verify the digest before and after without displaying the key. Existing KB and
   GitHub mounts already allow UID 1000 to read; no KB secret ownership change is
   needed with this design. The existing Codex auth mount is readable by UID 1000.
   Do not widen access to world-readable or change credential values.
4. Rebuild the non-root terminal image. Its launch configuration must keep
   cap_drop ALL and add no-new-privileges plus these two named policies.
   Set HOME=/home/node; preserve CODEX_HOME and the existing DS9 origin/model.
   Preserve Docker socket access with the existing socket group (currently GID
   988) as a supplemental group only; this retains the already-authorized
   host-equivalent socket authority. Measure that group on this host at activation;
   do not copy 988 to another machine. No new socket or repository mount is introduced.
5. Load the approved AppArmor profile and reference the reviewed seccomp file by
   absolute host path. Do not use privileged mode, SYS_ADMIN, unconfined policies,
   sandbox bypass, setuid bubblewrap or a host sysctl relaxation.
6. Before recreation, verify UID 1000 can read the required secret mounts and
   write the dedicated volumes without changing their contents. Capture rollback
   image/config and the current workspace HEAD. Recreate only this terminal.
7. Verify through the running terminal: launcher environment, gateway health,
   workspace HEAD preservation, real DS9-mediated file edit, read-only denial,
   resume and actual model-driven MCP calls. Passing this isolated kernel test
   alone is not application acceptance and does not close task 7405.

Rollback must restore the prior image, service security settings and volume
metadata from the captured inventory. Do not restore an old sandbox-bypass
launcher or reset the repository to main as part of rollback.

The AppArmor profile `archie-codex-sandbox` is currently loaded on the host only
for this disposable rehearsal. The production terminal is still attached to
Docker's default profile and unchanged. Unload the named rehearsal profile after
all probe containers have exited; re-load it for an operator-approved activation.

The terminal remains root until a separately reviewed service launch configuration
runs this image as the baked `node` user. Compose and live service configuration
are intentionally outside this PR. The activation operator must pass the measured
supplemental socket group for this host to preserve the currently approved Docker
socket access; socket authority remains host-equivalent.
