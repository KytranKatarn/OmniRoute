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
2. **Lane clone `/work/archie-platform` — THIS lane's work site, and the only tree
   you ship from.** In the guard-free instance it is a full clone with `origin` =
   GitHub, so `opencode-pr` can commit, push and open the PR. (The scope-gated
   runner — `run-opencode-task.sh` + `_lane_ship/mk-pr.sh` — is the GUARDED lane's
   Path B. It does not apply here: this instance has no scope gate, and the runner
   would re-introduce one.)
3. **Divergence:** same branch/HEAD? If not, say plainly which tree holds what.
   Shipping is `opencode-pr "<title>"` from the clone. Never `git push` from the
   live tree — `opencode-pr` refuses it by design.
4. `_lane_ship/` notes below apply to the guarded lane, which has a `bin/` with
   `ship-branch.sh`. This instance has no `/opencode-home/bin/`.

Do not modify anything. Output a short state table plus any warning.
