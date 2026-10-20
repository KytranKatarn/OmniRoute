# Host Codex session — launch & approval path

**Audience:** anyone launching the *native host* Codex install on `archie`
(user `kytran`, working dir `/mnt/archie_brain`). This is NOT the contained
web-terminal lane at `codex.kytranempowerment.com`
(`scripts/start_codex_terminal.sh`), which runs
`--dangerously-bypass-approvals-and-sandbox` inside its container on purpose —
the container is that lane's boundary.

## How to launch

```sh
codex            # interactive TUI — the approval path below is active
codex resume     # resume a previous session, same policy
```

That's it. Do **not** add these on the host:

| Flag | Why not |
|---|---|
| `--ask-for-approval never` | Overrides the config and makes escalation impossible — this is what broke `docker ps` and GitHub branch creation (see below). |
| `--yolo` / `--dangerously-bypass-approvals-and-sandbox` | Removes all confirmation and sandboxing. Reserved for externally-sandboxed contexts only (container lanes, `codex_pr_review.sh`). |

The effective policy comes from `~/.codex/config.toml`:

```toml
approval_policy = "on-request"   # root key — must sit above the first [table]
```

## What `on-request` means in practice

- Ordinary commands still run inside the **workspace-write sandbox with network
  off** — identical safeguards to before.
- Commands that need more than the sandbox allows (the host Docker socket, MCP
  tools marked as write/approve) raise a **TUI approval dialog**. You decide:
  allow once, allow for session, always allow, or cancel.
- Read-only MCP tools (e.g. the archie KB `search_knowledge`) run without
  prompts, same as before.

## Why this was changed (2026-10-20)

Both failures had one cause: sessions were launched as
`codex --ask-for-approval never`, so there was no path to a prompt at all.

1. **`docker ps` → EPERM.** Not a docker-group problem — `kytran` is in group
   `docker` and unsandboxed `docker ps` works. The workspace-write sandbox's
   syscall filter blocks the `docker.sock` connect() (inside the sandbox the
   socket even shows as `nobody:nogroup`). With approval disabled the model
   could never ask to run it outside the sandbox.
2. **GitHub branch creation → "MCP tool call requires approval, but approval
   policy is never."** `github.create_branch` (ChatGPT GitHub connector) is a
   write tool (`readOnlyHint: false`); with policy `never` the call was
   hard-rejected before any dialog could appear.

**Verified 2026-10-20** in a fresh session: `docker ps` ran after approving the
sandbox-escape dialog (52 containers listed); a `github.create_branch` probe
raised the approval dialog instead of erroring and was cancelled — no branch was
created.

## Rollback

```sh
cp ~/.codex/config.toml.bak-20261020-approvalpath ~/.codex/config.toml
```

(Backup taken before the change; a copy of the reasoning also lives as a
comment block next to the `approval_policy` key.)

## Notes for automation

- Every scripted `codex exec` in this repo (`codex_pr_review.sh`,
  `run-codex-task.sh`, the review-queue cron) already passes
  `--dangerously-bypass-approvals-and-sandbox` explicitly, so the config
  change does not affect them — the CLI flag wins, by design.
- The owner's long-running session started before this change keeps
  `--ask-for-approval never` until it is restarted. Relaunch with plain
  `codex` to pick up the approval path.
