---
description: Report live-tree state and any divergence from the lane clone — HEAD, branch, dirty count on /mnt/archie_brain vs /work/archie-platform, and which tree to use for what. Use when the user says "sync", "is my tree current", "lane drift", "tree status".
---

opencode works from TWO trees with distinct jobs (post option-B, 2026-09-13).
Read-only exercise; change nothing.

Report:

1. **Live tree `/mnt/archie_brain` (the served platform — default work site):**
   - branch: `git -C /mnt/archie_brain rev-parse --abbrev-ref HEAD`
   - HEAD: `git -C /mnt/archie_brain rev-parse --short HEAD`
   - dirty: `git -C /mnt/archie_brain status --porcelain | wc -l`
   - A dirty live tree usually includes the OWNER's/Claude's in-progress work —
     never blanket-stage it. Known churn: `website/.../data/translations.json`
     (autocommit worker newline strip) and `ds-bundle/` (gitignored).
2. **Lane clone `/work/archie-platform` (scope-gated runner base — Path B):**
   - same three fields. It is NOT abandoned: `run-opencode-task.sh` bundles from
     the host here, applies patches, runs the real test gate, pushes the ship
     branch. Edits made ONLY here do not reach the served platform.
3. **Divergence:** same branch/HEAD? If not, say plainly which tree holds what.
   `git push`/`git fetch` from the lane is never the ship step — shipping is
   the host runner (`scripts/agents/run-opencode-task.sh`) — this lane has no
   shipping helper of its own, so there is no Path A to choose from,
   both via the platform token (skill `archie-lane-ship`).
4. `_lane_ship/` patches/scripts are gitignored on the host and NOT shared with
   the lane clone — `docker cp` the patch across before a Path B run; files may
   vanish between runs (regenerate deterministically).

Do not modify anything. Output a short state table plus any warning.
