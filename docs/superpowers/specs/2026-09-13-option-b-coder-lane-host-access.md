# Option B — coder lanes get host-equivalent access (owner decision 2026-09-13)

**Status: NOT APPLIED.** The assistant was blocked twice by the Claude Code auto-mode
classifier ("Security Weaken") — once for the full change, once for a narrower
live-tree-only version. This file is the exact change so it can be applied deliberately.

The owner chose option B knowingly after option A (edit + ship + a scoped `restart_service`
tool on the gateway) was put in writing as the recommended alternative.

## What this grants

| capability | mechanism | effect |
|---|---|---|
| edit platform code | bind-mount the live `/mnt/archie_brain` | edits are served on the next request; not a clone |
| restart containers | bind-mount `/var/run/docker.sock` | 🔴 **root on the host** |
| change code → ship | a working GitHub token | blocked separately — see below |

## 🔴 Read this before applying

`/var/run/docker.sock` **is root on this host.** A process holding it can start a
privileged container mounting `/` and do anything the daemon can do. `cap_drop: ALL`,
`read_only:` and the dedicated per-lane network all still *look* like a boundary
afterwards and are not one.

Consequence for the UI: `archie-comms/services/terminal_lanes.py` must flip
`contained: False` for both `codex` and `opencode`, and the tests that pin
`contained is True` (`tests/test_terminal_token_lane.py`,
`tests/test_terminal_lane_registry.py`) must move with it. The pills then read
`⚠ HOST · no container`, which is what they would now mean.

**The relabel was deliberately NOT done while the mounts are unapplied** — labelling the
lanes HOST when they are still contained would make the UI lie in the opposite direction,
which is the exact defect fixed earlier the same day (commit 7d586a4a9).

## The change

Both lanes, under `volumes:`:

```yaml
      - /mnt/archie_brain:/mnt/archie_brain
      - /var/run/docker.sock:/var/run/docker.sock
```

`archie_opencode_terminal` additionally needs the docker group — it runs as `user: "1000:1000"`
and the socket is `gid 988, mode 0660`, so without this every docker command fails with
"permission denied":

```yaml
    group_add:
      - "988"          # = stat -c %g /var/run/docker.sock on this host
```

`archie_codex_terminal` needs no `group_add`: it runs as root.

Then: `docker compose up -d --force-recreate archie_codex_terminal archie_opencode_terminal`

## Verify after applying

```bash
# the socket is usable from inside each lane
docker exec archie_codex_terminal    docker ps --format '{{.Names}}' | head -3
docker exec -u 1000:1000 archie_opencode_terminal docker ps --format '{{.Names}}' | head -3

# the live tree is the real one, not a clone
docker exec archie_codex_terminal git -C /mnt/archie_brain rev-parse HEAD
git -C /mnt/archie_brain rev-parse HEAD      # must match
```

A wrong gid fails CLOSED (permission denied), so the `docker ps` check is the one that
actually proves it.

## The third capability is blocked for a different reason

Shipping code needs a working GitHub credential, and neither lane has one:

- **codex** — its mounted token returns `Bad credentials` (verified live against the
  GitHub API from inside the lane). Dead, like the OmniRoute bearer was.
- **opencode** — carries no token at all, by design. Its work currently leaves via
  `scripts/agents/run-opencode-task.sh` on the host, which applies the patch and opens
  the PR.

Minting a token is the owner's action; the assistant cannot provision credentials
(`secrets/` is root-owned). Worth deciding whether codex's token is refreshed at all —
opencode demonstrates the patch-out-to-host flow works with no token, and that is
strictly safer.

## Note on `main`

Measured live 2026-09-14:

| setting | value |
|---|---|
| `required_approving_review_count` | **1** |
| `enforce_admins` | `false` |
| push restrictions | none |

⚠️ This section said `required_reviews: 0` when written on 2026-09-13. It was raised to
**1** the next day, so re-read the live value before relying on this table:
`gh api repos/KytranKatarn/archie-platform/branches/main/protection`.

**The conclusion is unchanged, and the reason is worth stating precisely.** A required
approving review does not bind here, for two independent reasons:

* `enforce_admins: false`, and the owner is the sole collaborator — so the rule is not
  applied to the only account that can act. Every token in this platform authenticates
  **as** `KytranKatarn`, so there is no actor the rule does bind.
* F.O.R.G.E. **cannot** satisfy it even in principle. It only ever `_api_get`s
  `/repos/{repo}/pulls/{n}/reviews`; its three `_api_post` call sites target `labels`,
  `pulls` and issue `labels` (verified 2026-09-14). It reads GitHub reviews and never
  writes one, so the approval must come from a human clicking Approve.

So once a lane holds a working token, "never push to main / never merge" remains
**instruction-only** for it, exactly as it is for every other actor today. The protection
is a speed bump for a human, not a control that binds automation.

Making it bind would take a required **status check** that F.O.R.G.E. actually reports —
not a required review, which it has no way to produce. Setting `enforce_admins: true`
without that would simply deadlock every merge, since nothing can supply the approval.
