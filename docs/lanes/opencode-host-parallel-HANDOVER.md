# Host-parallel OpenCode — handover for the NEXT agent

**Written 2026-09-30** by the guard-free container instance (`archie_opencode_terminal_gf`,
port 17687) after the owner asked for "parallel on host" access and the container kept
failing to provide it.

**Read this before running anything.** Everything below was measured, not assumed. Where
something is unproven it says so.

---

## 0. Read this first: the goal, and why it exists

The owner asked, repeatedly: *"i had asked to have it parallel on host"*, *"you are
supposed to work in parallel and have access to everything it had as well"*.

Claude-CLI runs **on the host**, as user `kytran`. The OpenCode lanes run **inside
containers**. That single difference is the whole problem:

| | Claude-CLI (host) | OpenCode lane (container) |
|---|---|---|
| docker | host socket, `kytran` in group 988 | socket mounted, **gid 988 not in groups** |
| ssh | host binary | **none**, and rootfs read-only so one cannot be installed |
| host filesystem | everything | 3 bind mounts |
| any host change | directly | **container RECREATE** |

`--group-add 988` fixes **one row** of that table and never yields ssh. The ceiling is
the container. Host-parallel means the same binary as the same user, with nothing between.

---

## 1. What is DONE and working — do not redo any of it

Native host OpenCode is **installed and running** as `kytran`.

- `opencode-ai@1.18.30` installed into the nvm global prefix (user-owned, no sudo).
- `~/.config/opencode/opencode.json` seeded from the guard-free container's config, with
  every container-only endpoint rewritten for the host (see §3).
- `openssh-client` already present on the host — ssh to starbase/citadel/outpost works.
- The `opencode` name was freed; the lane wrapper renamed `opencode-docker`.

### The three entry points

| command | what it is |
|---|---|
| `opencode` | **native host** — real docker, real ssh, whole filesystem |
| `opencode-docker` | `~/.local/bin/opencode`, renamed from `opencode`. tmux-attach to the SHARED session on the **17685** canonical lane. `--solo` / `--shell` still work. |
| `./scripts/opencode-Primary` | repo launcher, `docker exec` into `archie_opencode_terminal_gf` (**17687**, guard-free). Has `--check` and `--live-tree`. **Not on PATH** — must be invoked with `./scripts/`. |

> ⚠️ `opencode` (host) and `opencode-docker` (17685) edit the **same checkout** with no
> boundary between them. `/mnt/archie_brain` is mounted rw into the lanes. Two agents
> writing one tree will fight. **Pick one for write work.** `opencode-Primary` carries the
> same warning about `--solo`.

---

## 2. What is NOT verified — start here

Nothing below has been confirmed end-to-end. Treat it as unproven, not as broken, and not
as working.

1. **MCP servers.** The installer was fixed to write the *real* `archie-kb` bearer and to
   point `hostinger-api` at a host path. The repaired config has been written, but the
   verification method was itself wrong twice (see §5). **Confirm it yourself.**

2. **`TMPDIR` / the noexec TUI fix.** The export was appended to `~/.bashrc` at line 136.
   Whether an interactive shell actually reaches it is unproven. Opencode extracts a
   native `OpenTUI .so` into `$TMPDIR` and `dlopen`s it; `/tmp` is `tmpfs ... noexec` on
   this host, so it fails with *"failed to map segment from shared object"*.

3. **npm global-prefix churn.** Installing `hostinger-api-mcp` globally reported
   `added 7 packages, removed 30 packages, and changed 124 packages` — it writes into the
   **same prefix as `opencode-ai`**. Confirm `opencode --version` still works. The durable
   fix is a separate prefix (`npm i -g --prefix ~/.opencode-mcp`), not a shared one.

4. **No PR exists.** See §6.

### The commands that verify (run 1 and 2 at minimum)

```bash
cd /mnt/archie_brain
git fetch -q origin && git checkout opencode/feat-repair-bay-close-pr 2>/dev/null || git fetch -q origin

git show origin/opencode/feat-repair-bay-close-pr:scripts/fix_opencode_mcp.sh | bash
git show origin/opencode/feat-repair-bay-close-pr:scripts/check_tmpdir_fix.sh | bash
cat /mnt/archie_brain/.tmpdir-check.txt

opencode --version          # did npm remove it?
```

Then restart OpenCode (**MCP servers are read at startup** — a running session keeps
showing `⊙ 0 MCP`). Success looks like **2 MCP servers** in the status bar, and a prompt
reading `Ask anything…` rather than an OpenTUI error.

---

## 3. Environment facts — measured, so you don't have to rediscover them

| fact | value |
|---|---|
| host user | `kytran`, uid 1000, groups `1000 4 24 27 30 46 101 987 988` (988 = docker ✅) |
| node | v24.13.0 via **nvm** at `~/.nvm/versions/node/v24.13.0` |
| npm global prefix | inside `$HOME` → **writable, no sudo needed** |
| `/tmp` | `tmpfs ... rw,nosuid,nodev,noexec` |
| `$HOME` | **NOT mounted** into the container agent — only `/mnt/archie_brain` is |
| lane secrets | `/mnt/archie_brain/secrets/opencode/{mcp_bearer,hostinger_token,github_token}.txt` |
| MCP gateway | `127.0.0.1:17800/mcp` (compose publishes loopback-only) |
| OmniRoute | `127.0.0.1:20128/v1` |

Container names/ports: `archie_opencode_terminal` **17685** (canonical, guarded),
`archie_opencode_terminal_host` **17686**, `archie_opencode_terminal_gf` **17687**
(this one; **not in any compose file** — created by hand, invisible to V.I.G.I.L.,
orphaned by `docker compose down`).

---

## 4. Scripts that exist (all on `opencode/feat-repair-bay-close-pr`)

Read the header comment of each before running; they explain their own failure modes.

| script | purpose |
|---|---|
| `install_opencode_on_host.sh` | installs opencode-ai + seeds config (idempotent) |
| `free_opencode_name.sh` | renames the `opencode` wrapper; auto-detects alias vs PATH file |
| `link_lane_commands.sh` | symlinks `opencode-Primary` into `~/.local/bin` |
| `fix_opencode_noexec_tmp.sh` | TMPDIR fix; **verifies by starting the TUI on a pty** |
| `fix_opencode_mcp.sh` | repairs both MCP servers; verifies with a real `initialize` POST |
| `check_tmpdir_fix.sh` | reports whether the TMPDIR export is reachable |
| `dump_bashrc_region.sh` | shows `~/.bashrc` up to the export, secrets masked |
| `opencode_gf_docker_parity.sh` | recreates the 17687 container with `--group-add 988` |
| `set_lane_github_token.sh` | **modified**: now verifies `pull_requests` scope, which it previously did not |

All are `--probe`/auto-detect and confirm interactively (`type APPLY`) rather than
requiring a flag — **because this terminal silently dropped flags from pasted commands,
twice**, causing wrong-but-successful-looking runs.

---

## 5. Read this before writing any more shell

**The failure pattern of the previous session, so you do not repeat it.** Of 17 bugs,
these were the avoidable classes:

1. **`set -e` + command substitution = silent abort.** `X="$(grep ... | head -1)"` exits
   non-zero when `grep` matches nothing, and `set -e` kills the script. Five separate
   instances shipped: `grep`-no-match ×2, a `first_ok` probe, `git config --get` on an
   *unset* key, and **`diff`** — which exits 1 *when files differ*, i.e. the success case.
   Always `|| true`, and audit every `$(...)` before shipping.

2. **Verifying something weaker than the claim.** This was the worst class, because it
   produced *green* results that meant nothing:
   - `opencode --version` passed → but it never starts the TUI.
   - "the config has an Authorization header" passed → but the value was a placeholder.
   - a `GET` to the MCP endpoint reported auth failure → but a GET is not a valid MCP
     request; the gateway answers `406` either way. A proper `initialize` POST returns
     **200** with the bearer and **401** without.
   - grepping for the word `OpenTUI` reported a failure on a TUI that had started.
   - reading `$TMPDIR` inside a `bash -c` subprocess → which never sources `.bashrc`, so
     it was always unset and proved nothing about the owner's shell.

   **Check the thing you are about to claim.** Prefer a real call over a config read.

3. **`chmod +x` without checking the index.** The write tool creates `0644`; only
   `git ls-files -s` records what the next checkout gets. Three scripts shipped `100644`.

4. **Printing secrets.** An early version of `opencode_gf_docker_parity.sh` echoed env
   values and printed `OMNIROUTE_API_KEY` in cleartext. It is redacted now.

### ⚠️ `git show origin/<branch>:<path>` silently serves a STALE ref

Fetching a script straight out of a remote ref is the most convenient way to run
something without checking out a branch — and it fails in a way that misleads:

```bash
# MISSING git fetch  ->  runs whatever your LAST fetch left behind, or:
fatal: path 'scripts/foo.sh' does not exist in 'origin/<branch>'
```

That second message reads like "the script was never committed". It usually means your
origin ref is simply old. **Always `git fetch -q origin` first**, in the same command:

```bash
cd /mnt/archie_brain && git fetch -q origin \
  && bash -c "$(git show origin/<branch>:scripts/foo.sh)"
```

This cost a real round trip twice on 2026-09-30 — once where a stale ref silently served
a script that had already been fixed, and once where a stale ref produced a `fatal` that
looked like a missing file. The failure is quiet in one direction and alarming in the
other, which is the worst combination.

### Shell traps on this host
- **`/tmp` is `noexec`.** `bash /tmp/x.sh` works (`bash` reads it); `./x.sh` and any
  `execve` of a file there does not.
- **`sudo` resets `PATH`.** npm lives under nvm, so `sudo npm` → *command not found*.
- **The terminal drops tokens from long pastes** — a leading `type` and a trailing
  `--probe`. `bind 'set enable-bracketed-paste off'` is worth setting.

---

## 6. Open work

1. **Open the PR.** Branch `opencode/feat-repair-bay-close-pr` @ `788e5e414`, pushed,
   **no PR**. `opencode-pr` cannot: the lane PAT is **Contents-only** (`GET /pulls` 403,
   `POST /pulls` 403, `GET /git/ref` 200). From the host, `gh` has the owner's login:

   ```bash
   cd /mnt/archie_brain
   gh pr create --base main --head opencode/feat-repair-bay-close-pr \
     --title "feat(repair-bay): close-PR control, shared merge affordance, opencode scope"
   ```

   **Consider splitting first.** The branch carries two unrelated bodies of work:
   `2e5189546` is the close-PR feature (mutation-proven: 33 Python tests + 14 mutations
   confirmed red, plus a node harness that executes the real shipped helpers). The 17
   commits after `09fffc298` are lane provisioning. `config/agents/opencode.yaml` is
   security-sensitive. Different risks, arguably different reviewers.

2. **Rotate `OMNIROUTE_API_KEY`** — printed in cleartext by an earlier script version.

3. **`.bashrc` errors on every login:** `-bash: …/secrets/codex/mcp_bearer.txt: Permission
   denied`. A line reads a *codex* secret `kytran` cannot access. Harmless but noisy, and
   it may `return` early and make the TMPDIR export unreachable. `dump_bashrc_region.sh`
   shows the structure without leaking values.

4. **Recreate 17685 / 17686** — still blocked on docker group access for those lanes
   (same gid-988 wall). `opencode_gf_docker_parity.sh` handles 17687 only, and it is
   still **unapplied**.

---

## 7. Rules that hold here

- **Never merge or approve your own PR.** F.O.R.G.E. reviews; a human merges.
- **Never ship from `/mnt/archie_brain`.** It is the owner's shared live tree. Never
  `git add -A` there. Look, do not stage.
- **Never write a secret to stdout**, into a commit, or into the repo.
- Two agents must not write `/mnt/archie_brain` concurrently — there is no boundary.
---

## 8. Session 2026-09-30 — MCP gateway repaired, 5 PRs, procedures exposed

Previous agent. Sections 0–7 are the inherited baseline and still hold unless noted.

### 8.1 Section 2's "NOT verified" list is now RESOLVED — do not redo it

| Item | Verdict |
|---|---|
| Both MCP servers | **WORK.** Real `initialize` POST → 200 with bearer, 401 without. |
| TMPDIR / noexec-`/tmp` fix | **WORKS.** `opencode --version` → 1.18.33; shared npm prefix intact (`opencode-ai`, `@openai`, `@anthropic-ai`, `playwright`, `hostinger-api-mcp`, `token-optimizer-mcp` all present). The reported 30-package removal did **not** happen. |
| Entry points | Work — **after an exec-bit fix**, see 8.2. |

### 8.2 Shipped

`#3554` repair-bay close-PR · `#3555` host-lane provisioning · `#3556` opencode lane
scope widened (owner decision; inert until the opencode terminal image is rebuilt) ·
`#3558` fix(mcp) · `#3559` OmniRoute DS9/LCARS spec — **all merged**. `#3563`
`.opencode/command/` wrappers — **open**.

`#3555` needed one fix on top of the replayed history: the six entry-point scripts
ship mode `0644` but are invoked as `./scripts/*.sh`, so they failed with `Permission
denied` before running a line — including `install_opencode_on_host.sh`, the documented
one-command install. Two commits had already tried to fix this and neither left the
tree matching its own message: `788e5e414` is titled *"restore exec bit (100644 ->
100755)"* but actually diffs `mode change 100755 => 100644` — it **removed** the bit;
`98d8d1d32` did set `100644 => 100755` and `0161d124b` silently put it back. Set with
`git update-index --chmod=+x`, deliberately not `chmod + add`, which is the sequence
that silently failed. **This is the recurring pattern: assert what you expect rather
than what you need to know.**

### 8.3 The MCP gateway defects (`#3558`)

Three causes, none matching its symptom:

1. **`check_platform_health` probed `/api/health`, which does not exist.** Every
   `/api/*` sits behind Flask-Login, so it 302'd, `requests` followed the redirect, and
   `response.json()` hit the HTML login page → `Expecting value: line 1 column 1
   (char 0)`. That is a `ValueError`, which `requests.RequestException` does **not**
   catch, so it escaped and a healthy hub read as `offline`. Now probes `/health` with
   `allow_redirects=False` and catches `ValueError`.
2. **`list_agents` / `get_system_status` read the DB.** The lane's role is `codex_ro`
   (SELECT-only, 40 tables) with no grant on `agents` or `bridge_stations`. Both failed
   with `permission denied for table agents`. **The credential was already there** —
   `/api/internal/agents` returns 200 from inside the gateway with the key it already
   carries, and `coder_lanes` already holds `agents:read`. `docker-compose.yml` says it
   outright: task/agent tools *"call the hub's INTERNAL HTTP API (never the DB), so the
   Postgres role above stays read-only."* The tools were not using it. No new
   credential, no widened scope.
3. **`get_system_status` shared one transaction**, so the first permission error
   poisoned it and `InFailedSqlTransaction` killed sections whose tables *were*
   readable. Now each section rolls back independently.

Also: the MCP client sends **explicit `null`** for omitted optional args, so
`arguments.get("status", "active")` silently disabled the documented default. Use
`arguments.get("status") or "active"`.

Verified through the running process, not the file: 158 agents; agents 158/153 + 17
stations + knowledge 98,257; platform healthy v2.0.

### 8.4 Deploy: the gateway inherits `platform_v2` only via its base image

`mcp-gateway/Dockerfile` is `FROM archie_platform:latest` and COPYs just `gateway.py`
+ `entrypoint.sh`. So:

- Rebuilding **only** `archie_mcp_gateway` rebuilds on the same stale base and
  **serves old code while looking green.**
- `docker compose build <svc>` does **not** touch running containers. Use it to refresh
  an image with no restart — that is how to avoid a double-bounce when another lane
  just restarted a service.
- `docker compose up -d` will **not** recreate a container whose image ID is unchanged.
  Compare `sha256sum` of the file inside the container against the commit before
  declaring a deploy landed.

Correct sequence:

```bash
docker compose build archie_platform      # base first
docker compose build archie_mcp_gateway   # then the leaf
docker compose up -d --no-deps archie_mcp_gateway
```

The platform container itself never needs restarting — it bind-mounts `platform_v2`.
Record `docker inspect -f '{{.Image}}' <container>` before recreating, for rollback.

### 8.5 GUARDRAILS.md is stale — trust the handover over it

| GUARDRAILS claims | Reality |
|---|---|
| `/opencode-home/data/archie-handover.md` is this instance's handover, read at boot | **Does not exist** and cannot be created — `/` is not writable, no volume mounted. |
| `/work/archie-platform` is a clean `main` clone | Empty root-owned dir, **no `.git`**. This lane works in `/mnt/archie_brain`. |
| `opencode-pr` at `/usr/local/bin` | **Absent.** Push with `git` + `gh`; the credential helper reads `secrets/opencode/github_token.txt`. |
| `/ship` exists, "rewritten for this instance" | **Was absent.** Now written in `#3563`. |
| `/opt/no-guard`, `core.hooksPath = /opt/no-guard` | Absent; hooks are **active** at `/mnt/archie_brain/.git/hooks`. |
| GitHub token at `/run/secrets/opencode_github_token` | Not mounted. |

`gh` here is the **real** CLI 2.63.2, not the refusing shim, and `enforce_admins` is
`false` on `main`. Branch protection **is** on (`required_approving_review_count: 1`) —
that previously-unverified risk is now closed — but it will not stop *this* lane from
merging its own PR. Restraint is the only control.

### 8.6 opencode reads `.claude/skills/` but NOT `.claude/commands/`

~60 skills loaded fine this session while **all 20 platform procedures were
invisible** — `/archie-save` was not invocable and its steps were executed by hand
after reading the markdown. opencode scans `~/.config/opencode/command`,
`.opencode/command/`, `.opencode/commands/`. `#3563` adds a **delegating** wrapper per
procedure (so they cannot drift) plus `/ship`.

**Two upstream procedures merge** — `merge-pr.md` (*"HARD GATE, enforced here"*) and
`commit-push-merge.md` (*"auto-merge"*). Their wrappers carry a hard override: stop
after the review check, report `mergeStateStatus`/`reviewDecision`, never merge.

### 8.7 This lane cannot write the KB

No `store_memory` among its 71 exposed tools, and `github_search` returns 0 for
everything. So `/archie-save` step 4 — the **mandatory** Consciousness doc refresh —
cannot be completed here. The KB has **zero** entries for `omniroute`, DS9 or LCARS,
which is exactly why that plan has been reported "lost" twice. **A lane with
`store_memory` must write them.**

### 8.8 OmniRoute — what is actually true

The Phase 3 plan was **executed 2026-09-09** (`docs/superpowers/plans/2026-09-09-
phase3-omniroute-contractor.md`, 1,652 lines) and DS9 governed routing **shipped**
(`#3439`, spec `#3395`). The plan was never lost — it was undiscoverable.

```
container   diegosouzapw/omniroute:3.8.50   Up 11 days (healthy)
publishes   192.168.1.200:20128 -> 20128/tcp  ->  HTTP 200, 534 models
opencode.json baseURL  http://127.0.0.1:20128/v1  ->  HTTP 000, NOTHING BOUND
```

That one-line address mismatch is the likely cause of "had issues to get working".

**Correction to record:** an earlier probe this session reported OmniRoute *down* from
a `127.0.0.1:20128` curl returning HTTP 000. **Wrong** — it is healthy; the probe used
an address it does not bind. Check what a service binds; do not reason about what it
probably binds.

Contractor → Engineer is migration-scale: 809 Python occurrences, 23 files on
`contractor_providers`, 4 tables, 2 views, 3 UI files. **Trap:**
`construction_subcontractors` is a different domain — build the exclusion list before
renaming. Scope is in `#3559`.

**Unanswered:** whether the 5 non-`:free` model ids route to free or paid upstream.
Probes timed out (`000`) or 502'd inside 10 s. The executed plan is free-only until
V.I.G.L. clears and treats every prompt as public.

### 8.9 Still open

- **Rotate `OMNIROUTE_API_KEY`** — plaintext in `opencode.json` (3rd copy; root `.env`
  and `platform_v2/.env` mirror correctly). Deferred to codex_cli testing.
- **Rotate `INTERNAL_API_KEY_CODER_LANES`** — printed into a session transcript by a
  careless `docker compose config | grep`. Hash, never print. Needs
  `--force-recreate` on both platform and gateway.
- **Blocked by design** (no `/api/internal/*` equivalent): `get_station_assignments`,
  `manage_shifts`, `view_analytics`, `get_node_status`, `forge_stats`,
  `check_infra_heartbeat`, `get_skills_matrix`. Needs new scoped routes in `app.py`
  (platform work) or a `codex_ro` grant — an owner decision.
- **`get_welfare_digest`** throws `'>=' not supported between instances of 'int' and
  'NoneType'` — independent NULL bug, unrelated to auth.
- **12 `http_endpoint` tools** untouched deliberately: they need general platform API
  auth this lane lacks, and `send_email` / `run_backup` / `create_invoice` map to
  scopes it is explicitly denied (`mail`, `repair:write`).

### 8.10 More shell traps (extends section 5)

- **`docker cp` cannot write into a `read_only` container's tmpfs.** Stream:
  `tar -C <dir> -cf - <pkg> | docker exec -i <c> sh -c 'tar -xf - -C /tmp/verify'`.
- Running `python3` with cwd=`/app` makes `/app` beat `PYTHONPATH`, so a shadow copy in
  `/tmp` is silently ignored. `cd` to the shadow dir first.
- **Host Black ≠ repo Black.** The hook pins `black 24.4.2 --line-length=120`; host
  Black is 26.x and disagrees on untouched lines. Never pre-format with the host
  version — let the hook decide, re-stage when it reformats, and **do not amend** a
  rejected commit.
- `psycopg2` here returns `RealDictCursor`, so `for (t,) in rows` yields dict KEYS. Use
  `r['table']`. A failed statement poisons the transaction: `InFailedSqlTransaction` on
  the next query means roll back first.
