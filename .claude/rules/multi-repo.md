# Multi-Repo Workspace — FOUR git repos live under /mnt/archie_brain, plus a 5th on GitHub only

**Established 2026-07-29 (task #5401).** `/mnt/archie_brain` is not one repository. Several
products are their **own independent git repos nested inside it**, and almost every tool that
says "the repo" silently means *the caller's* repo. That distinction has now caused two
separate defects in one day, so it is written down.

## The repos

| Path | Repo | Notes |
|---|---|---|
| `/mnt/archie_brain` | `KytranKatarn/archie-platform` | The platform. `platform_v2/`, `ai_bridge/`, `scripts/`, `standalone/`, `.claude/` |
| `/mnt/archie_brain/kytran-business-suite` | `KytranKatarn/kytran-business-suite` | **Own repo.** KBS, :8091 |
| `/mnt/archie_brain/kytran-creed` | own repo | C.R.E.E.D., :8086 |
| `/mnt/archie_brain/kytran-server-manager` | `KytranKatarn/kytran-system-operations` | KSO, :8085 |
| *(not cloned locally)* | `KytranKatarn/kytran-what-the-fact` | 🟡 **History mirror only, created 2026-09-05.** NOT yet the deployed source — `archie-platform`'s `what-the-fact/` still is, until a separate gated cutover (new DB + F.O.R.G.E. token grant + deploy retarget) happens. Full history preserved via `git subtree split` (600 app commits + the old static-landing-page history merged under `static-site/`). Exists so design tooling has a real repo to connect to. See `what-the-fact/.design-sync/conventions.md` for the live-vs-mirror status. |

⚠️ `standalone/media_hub` is **NOT** in this list — it is a *subdirectory* of archie-platform.
That is exactly why tooling written against media_hub breaks on the other three: media_hub is
the only image-baked product that lives inside the platform repo. `kytran-what-the-fact` is the
same shape in reverse: don't assume editing it affects the live site until cutover is done.

## Retired repos in this family — do not connect to any of these

`what-the-fact-site`, `kytran-news`, `kytran-news-site` are all archived dead ends from the
April 2026 pre-launch attempt (static "Coming Soon" page, pre-consolidation app skeleton, and a
landing page for a domain that no longer resolves, respectively). All three carry corrective
READMEs as of 2026-09-05. See `.claude/rules/wtf.md` for the full history.

## Trap 1 — a "repo root" derived from cwd is the WRONG repo (#5401)

`scripts/deploy_with_sha.sh` did `REPO_ROOT="$(git rev-parse --show-toplevel)"` against `$PWD`
and treated the product dir as a subdirectory of it. Deploying KBS from `/mnt/archie_brain`
stamped **archie-platform's** commit `f63ef4e04` into the KBS image — a SHA that is not a valid
object in the KBS repo at all.

**A wrong stamp is worse than a missing one.** `deploy-provenance.md` treats `unknown` as an
honest unknown and fails open; a foreign SHA is *confidently false*, and
`deploy_drift_check.py` compares the baked SHA against the product repo's head.

**Rule: derive the repo from the TARGET path, never the caller's cwd.**
`git -C "$TARGET" rev-parse --show-toplevel`. Fixed in `deploy_with_sha.sh`; apply the same
rule to any new script that resolves a repo for a product.

## Trap 2 — background jobs are worktree-pinned, interactive sessions are not

A **background job** must isolate into a worktree before editing, so its `Edit`/`Write` are
pinned to `/mnt/archie_brain/.claude/worktrees/<name>/`. From there **KBS/creed/KSO files are
unreachable** — including a legitimate git worktree of those repos, because the guard matches
on the path prefix, not on whether the target is isolated. `EnterWorktree` will not switch to
them either: it only manages worktrees under *this* repository's `.claude/worktrees/`.

A **normal interactive session at `/mnt/archie_brain`** is not worktree-pinned and can edit all
four repos directly.

⚠️ **Do NOT "solve" this by launching a session inside a product repo.** Memory and config are
keyed by launch path: `~/.claude/projects/-mnt-archie-brain/` holds **126 memory files**, and
`/mnt/archie_brain/.claude/` holds **41 rules files** plus hooks, commands and plans. KBS has
**no `CLAUDE.md`** and its `.claude/` holds only `worktrees/`. Launching there yields an
amnesiac session with no guardrails on the most commercially sensitive repo. Work the product
repos from a normal `/mnt/archie_brain` session instead.

## Deploying a nested-repo product (KBS shown; creed/KSO are the same shape)

Image-baked (`COPY .`), so **a merge does not deploy**. Export the stamp from **inside** the
product repo, and rebuild **every** service built from that context:

```bash
cd /mnt/archie_brain/kytran-business-suite
export GIT_SHA="$(git rev-parse HEAD)"
export BUILD_TIME="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
docker compose up -d --build kytran-business-suite kbs-worker   # BOTH, not just the app
```
Or `scripts/deploy_with_sha.sh kytran-business-suite kytran-business-suite kbs-worker` (post-#5401
it resolves the right repo and accepts multiple services).

⚠️ **KBS has no `.dockerignore`**, so `COPY . .` bakes **untracked** files into the image — the
artifact can contain code that is in no commit while the stamp claims a clean tree. The fixed
script warns about this; `git diff --quiet` alone never detects it.

Verify: `/version` `git_sha` must equal the **product repo's** HEAD, then
`FORGE_REVIEW_TOKEN=<token> python3 scripts/deploy_drift_check.py`.
⚠️ `deploy_drift_check.py` needs `FORGE_REVIEW_TOKEN`/`GITHUB_TOKEN`. Run from a shell without
one and **all 9 products report `?` fail-open** — which looks like a broken monitor but is a
missing credential. The tokens live in the `archie_platform` container.

## Review + merge across repos

- **Only `archie-platform` and the 4 watch repos are in `GITHUB_REPOS`.** KBS, creed and KSO are
  **not polled**, so their PRs never reach Repair Bay on their own and `_automerge_governance_ok`
  fails closed — correctly, but it means nothing can ever auto-merge there.
- Review one explicitly: `review_pr(<pr>, repo="KytranKatarn/kytran-business-suite")` —
  `FORGE_REVIEW_TOKEN` is read-scoped across all repos.
- ⚠️ **The write token is NOT archie-platform-scoped** — corrected 2026-08-23 (#5981) after
  probing `GET /repos/{repo}` → `.permissions` with the container's own `GITHUB_TOKEN`:

  | repo | write token |
  |---|---|
  | `archie-platform`, `archie-code`, `kytran-system-operations`, `kytran-creed` | **push + admin** |
  | the 4 watch repos, `kytran-business-suite` | 404 — no access |

  So "human-merge-only" holds for the **watch products and KBS** — but NOT for archie-code, KSO or
  creed, where the token can merge and administer. **Never reason about merge safety from assumed
  token absence**; the governance gate (`_automerge_governance_ok`, and the `coo_window` manifest
  naming an explicit `(repo, PR)` pair) is the control that actually binds. Re-probe before trusting
  this table — a token's grants can change without any code change.

## Databases — KBS is NOT self-contained (corrected 2026-08-30, task #6129)

| Product | Connect |
|---|---|
| platform | `docker exec archie_database psql -U archie -d archie` |
| **KBS** | **the SAME platform DB** — `docker exec archie_database psql -U archie -d archie` |

The KBS app reads the **platform `archie` database**, not its own: `kbs_app` env is
`KBS_DB_NAME=archie`, `KBS_DB_HOST=archie_database` (verified live from the running
container 2026-08-30). This file previously said `kbs_postgres` was KBS's database — wrong.

⚠️ **`kbs_postgres` is a RUNNING container holding a STALE, DIVERGENT copy.** It answers
queries plausibly — it has its own `tenant_*` schemas (`tenant_1/95758/91408/90333/92898`,
a DIFFERENT id set than live) — but the app never reads it; querying it misread live state
as "0 tenants" (#6129). If you must inspect it anyway: `docker exec kbs_postgres psql -U kbs
-d kbs` (user `kbs`, not `postgres`).

The LIVE KBS tenant schemas are in the **archie** DB: `tenant_1` (= Kytran Empowerment),
`tenant_9908/9914/9915`; `public` holds the shared `module_catalog`. This is THE
KBS-independence constraint: KBS is not self-contained, so a real DB split (archie → its
own postgres) comes BEFORE any move off-hub (owner decision: split-DB-before-move).

⚠️ `pg_stat_user_tables.n_live_tup` is a **stale estimate** — it reported
`public.billing_subscriptions` as 0 when `COUNT(*)` returns 5. Use `COUNT(*)` for anything
you will act on.
