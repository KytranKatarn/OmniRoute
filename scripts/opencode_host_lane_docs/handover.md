# Host opencode — handover

**This is the host instance's own handover** — native `opencode` (user `kytran`),
home `~/.config/opencode/`. Seeded by `scripts/install_opencode_on_host.sh` so
`/archie-boot` has a continuity file: the boot procedure reads one, and the host
had none (the container lanes keep theirs in their own volumes). Read it at boot;
rewrite it in place at session end. Keep it under ~150 lines.

## Instance identity
- **Host-native, not a container.** Real Docker socket, real `ssh`, whole
  filesystem, running as `kytran`. No `/opencode-home`, no `/work/archie-platform`
  clone, no scope guard.
- Siblings (do not confuse): `archie_opencode_terminal` 17685 (guarded),
  `archie_opencode_terminal_host` 17686, `archie_opencode_terminal_gf` 17687
  (guard-free, entrypoint `lane-docs-boot`).
- Home: `~/.config/opencode/` — `opencode.json` (config, host-rewritten) and
  `GUARDRAILS.md` (this instance's rules).

## Ship flow — host
`opencode-pr` and `ship-branch.sh` are **absent** on the host. Ship with `git` +
the real `gh` from a **separate worktree/clone** off `origin/main` (never from
`/mnt/archie_brain`):
```bash
git -C /mnt/archie_brain worktree add -b opencode/<short> <scratch> origin/main
# edit, add explicit files, commit in <scratch>
git -C <scratch> push -u origin opencode/<short>
gh pr create --base main --head opencode/<short> --title "..."
```
**Never merge or approve your own PR.** F.O.R.G.E. reviews; a human merges.

## Truth sources (read, don't trust this file for platform state)
- Platform-wide active fire:
  `~/.claude/projects/-mnt-archie-brain/memory/project_session-handoff.md`
- Owner identity:
  `~/.claude/projects/-mnt-archie-brain/memory/feedback_owner-context.md`
- Host-parallel baseline: `docs/lanes/opencode-host-parallel-HANDOVER.md`

## Next actions
1. (seed) Nothing recorded yet — this is the generic seed. Rewrite this file with
   the real state at the end of the first host session.
