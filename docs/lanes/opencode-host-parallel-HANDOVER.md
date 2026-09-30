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