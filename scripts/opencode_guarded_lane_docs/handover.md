# Session handover — opencode lane (seeded clone)

**Lane:** `archie_opencode_terminal_host` — a *guarded* opencode lane. Its scope
guard is armed (`core.hooksPath=/opt/lane-guard`) and a GitHub token is mounted
read-only at `/run/secrets/opencode_github_token`.

**Two rules that are easy to get wrong here:**

1. **This lane does not ship.** Commit in `/work/archie-platform` and stop; the
   host runner (`scripts/agents/run-opencode-task.sh`) scope-checks, tests and
   opens the PR. Never `git push` — the token is mounted, so a push would succeed
   and skip the scope check.
2. **Never commit in `/mnt/archie_brain`.** That is the owner's live tree.

**Continuity:** refresh this file at the end of every session — what was done, what
was found, what is left. It is a record, not configuration: the installer that seeds
it will never overwrite it, and never should.

---

## 2026-09-28 — lane brought up and its instructions corrected

The lane had booted with an **empty `/work`**: no repository, no git identity and no
guard armed, because `/start.sh` gates all of its git setup behind a repo being
present. Seeded it from the mounted live tree (origin repointed at GitHub, on
`main`), restarted, and the guard re-armed normally on the next boot.

Then found that its command/skill tree was written for a lane that can ship itself
from `/mnt/archie_brain` using `/opencode-home/bin/ship-branch.sh`. Neither holds
here: `/opencode-home/bin/` is only populated for the canonical lane, and the docs
also claimed "the lane has no credential" — false, the token is mounted. Corrected
the set, and it is now tracked in the repository
(`scripts/opencode_guarded_lane_docs/`) and re-applied on every `--apply`, so
wiping this volume does not bring the wrong instructions back.
