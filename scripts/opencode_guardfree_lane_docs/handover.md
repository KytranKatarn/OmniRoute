# Lane handover — opencode GUARD-FREE instance

`archie_opencode_terminal_gf` · `127.0.0.1:17687` · image
`archie_opencode_terminal_guardfree:latest` (derived from the base; base untouched).
Seeded 2026-09-28. **This file is this instance's own** — the guarded lane
(`archie_opencode_terminal`, 17685) keeps its long handover in its own volume.

## 1. Lane identity
- **Guard-free on purpose.** Owner request 2026-09-27: "access and modify
  everything like claude-cli does". The scope guard is absent; the review
  boundary is not: F.O.R.G.E. reviews, a human merges, never self-approve.
- Siblings (do not touch): `archie_opencode_terminal` 17685 (guarded, the lane you
  are probably reading about elsewhere), `archie_opencode_terminal_host` 17686.
- Mounts: `/mnt/archie_brain` rw (owner's live tree, shared), `docker.sock` rw,
  `github_token.txt` + `mcp_bearer.txt` ro, `/home/kytran/.claude/settings.json`
  as ONE ro file (deliberately not the dir — it holds a DR replicator password,
  a secrets archive, an Xauthority cookie, bash history).

## 2. Ship flow — ONE path
Work in `/work/archie-platform` (full clone, `origin` = GitHub, `main` in sync,
git identity set, `core.hooksPath=/opt/no-guard`):
```bash
git switch -c <type>/<short>   # opencode-pr requires an opencode/* branch
git add <explicit files> && git commit -m "..."
opencode-pr "fix(<module>): <what and why>"     # commits, pushes, opens the PR
```
**Never ship from `/mnt/archie_brain`** — `opencode-pr` refuses it (it runs
`git add -A`, and an untracked `platform_v2` copy was once swept into a lane
commit that way). Read `/ship` for the detail; it was rewritten for this
instance 2026-09-28, as were `archie-save`, `archie-end`, `sync-lane`, and the
`archie-lane-ship` / `archie-repair-bay` skills. Originals: `*.guard-bak`.

**Do not repeat this as fact:** the PR body `opencode-pr` writes claims
"scope-guarded to allowed Applications/Concepts paths". There is no scope gate
here. Correct it when you report.

## 3. Tree state
- Lane clone `/work/archie-platform`: `main` @ `e318e3db1` = `origin/main`, clean.
  Populated by the image build's `seed_clone` (this was empty on first boot —
  the base image bakes no `/work`, so the lane had no repo at all).
- Live tree `/mnt/archie_brain`: the owner's. As of 2026-09-28 it sits on
  `fix/retired-cloud-models-and-blocked-delegations` @ `94b1e2ef6` with the
  owner's in-progress `website/` work uncommitted. **Re-read it; do not trust
  this line.** Never blanket-stage it.

## 4. Blockers / open owner decisions
- **#7026** — branch protection on `main` is UNVERIFIABLE from this host (403 with
  both the lane PAT and the platform token; neither has `Administration: read`),
  and the mounted PAT's "PR: write" also permits merging. Guard-free +
  merge-capable credential + unknown protection is the one combination where an
  agent could plausibly merge its own work. Owner decision, deliberately not
  pre-empted.
- **#7027** — this instance's `GUARDRAILS.md` lives only in the volume; nothing in
  the repo or `opencode/Dockerfile.terminal` writes it, so the file rewritten
  today is lost on the next image rebuild. Same for the command/skill edits
  above. `opencode/` is outside this lane's `allowed_paths`.
- This container is **not in any compose file** (created by `docker run`), so it is
  invisible to platform inventory / V.I.G.I.L. and orphaned by `docker compose
  down`. `docker-compose*` is outside this lane's scope.
- `gh` here is unauthenticated; read GitHub through
  `docker exec -i archie_platform python3 -`. `gh pr merge` is refused by the guard.

## 5. Next actions
1. Owner: decide #7026, and do #7027 (or accept the per-image caveat).
2. Owner: merge PR #3504 (guard-free clone seeding + this doc), then the two
   untracked copies of those files in `/mnt/archie_brain` can be deleted.
3. After ANY image rebuild of this instance, re-check `GUARDRAILS.md` and
   `/opencode-home/config/opencode/command/ship.md` — they revert to the guarded
   lane's copies.
