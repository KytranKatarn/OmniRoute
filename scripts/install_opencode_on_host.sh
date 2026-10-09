#!/usr/bin/env bash
# install_opencode_on_host.sh — run OpenCode ON THE HOST, in parallel with Claude-CLI.
#
#   ./scripts/install_opencode_on_host.sh            # dry run: show the plan
#   ./scripts/install_opencode_on_host.sh --apply    # install
#
# WHY THIS EXISTS
# ---------------
# The lanes run OpenCode inside a CONTAINER. Claude-CLI runs on the HOST. That single
# difference is the whole problem the owner kept hitting: a container can never be
# host-parallel, because the container is what stands between the agent and the host.
#
#   capability        Claude-CLI (host)     OpenCode lane (container)
#   docker            host socket, kytran   socket mounted, gid 988 NOT in groups
#   ssh               host binary           NONE, and rootfs is read-only so one
#                                           cannot be installed from inside
#   host filesystem   everything            3 bind mounts
#   any host change   directly              container RECREATE
#
# `--group-add 988` (scripts/opencode_gf_docker_parity.sh) fixes exactly ONE row of
# that table. It never yields ssh, and it never will — the ceiling is the container.
# Host-parallel means the same binary running as the same user, with nothing between.
#
# WHAT IT DOES
# ------------
#   1. installs opencode-ai globally (idempotent, version-pinned)
#   2. installs openssh-client if absent — the other half of parity
#   3. seeds ~/.config/opencode/opencode.json FROM THE RUNNING CONTAINER, so the host
#      copy is the config that demonstrably works rather than a hand-typed guess
#   4. RE-RESOLVES every container-only endpoint for the host (see below) — this is the
#      part that matters and the part a naive `cp` gets wrong
#   5. seeds the credential helper so `git push` works from the host
#   6. verifies, and tells you the one command to start
#
# THE ENDPOINT PROBLEM — a blind copy is broken
# ---------------------------------------------
# The lane config is full of names that only resolve inside the compose network:
#
#   archie-kb   url  http://archie_mcp_gateway:7800/mcp   <- docker service name
#   omniroute   baseURL http://omniroute:20128/v1         <- docker service name
#   hostinger   cmd   cat /run/secrets/hostinger_token    <- container mount path
#   instructions     /opencode-home/config/opencode/GUARDRAILS.md
#
# Copied verbatim to the host, EVERY ONE of those fails: docker service names do not
# resolve outside the network, and /run/secrets does not exist there. So the script
# probes real candidates and substitutes the first that answers.
#
# SAFETY
# ------
# Writes only under $HOME/.config/opencode and $HOME/.local. Never touches the live
# tree, never writes a secret to stdout, backs up any config it replaces, and refuses
# to run inside a container. No secret is ever echoed: values are rendered as <N chars>.
set -euo pipefail

APPLY=0
[ "${1:-}" = "--apply" ] && APPLY=1

SRC_CONTAINER="${SRC_CONTAINER:-archie_opencode_terminal_gf}"
OPENCODE_VERSION="${OPENCODE_VERSION:-1.18.30}"
CFG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/opencode"
CFG="$CFG_DIR/opencode.json"
SECRETS_REPO=/mnt/archie_brain/secrets/opencode

# The HOST instruction set (GUARDRAILS.md + a handover seed), tracked in the repo
# under scripts/opencode_host_lane_docs/. It exists because the container's
# copy — which this script used to copy verbatim — names /opencode-home/... paths
# that do not exist on the host, so /archie-boot failed to read its handover.
# Installing a tracked HOST copy is what stops a re-seed from reintroducing that.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
HOST_DOCS="$REPO_DIR/scripts/opencode_host_lane_docs"
[ -d "$HOST_DOCS" ] || HOST_DOCS=/mnt/archie_brain/scripts/opencode_host_lane_docs

say()  { printf '%s\n' "$*"; }
step() { printf '\n\033[1;33m==>\033[0m %s\n' "$*"; }
die()  { printf '\033[31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

# ---------------------------------------------------------------------------
step "Preflight"
# ---------------------------------------------------------------------------
if [ -f /.dockerenv ] || grep -qa 'docker' /proc/1/cgroup 2>/dev/null; then
  die "this looks like a CONTAINER. Run it on the HOST — installing into the container is the thing being fixed."
fi
have node || die "node is missing on the host. Claude-CLI implies it exists; check PATH."
have npm  || die "npm is missing on the host; opencode-ai is an npm package."
say "node $(node --version)   npm $(npm --version)"
have docker || die "docker is not on PATH for this user — host-parallel includes docker access."
docker info >/dev/null 2>&1 || die "docker is installed but unusable by $(id -un). Is $(id -un) in the docker group?"
say "docker $(docker --version | head -1)"

docker inspect "$SRC_CONTAINER" >/dev/null 2>&1 \
  || die "source container $SRC_CONTAINER not found. Set SRC_CONTAINER=<name>."
say "seeding from container: $SRC_CONTAINER"

# ---------------------------------------------------------------------------
step "Resolving host-reachable endpoints"
# ---------------------------------------------------------------------------
# Each probe tries candidates in order and keeps the first that answers. A wrong guess
# here is what makes a hand-copied config fail at runtime with an opaque MCP error.
# "Reachable" must mean THE SERVER ANSWERED, not "returned 2xx".
# Measured 2026-09-30: the gateway's /mcp answers a plain GET with 401 and its /health
# with 200 "ok". A strict `curl -f` therefore reports a perfectly healthy gateway as
# unreachable, and the script would then advertise a compose service name that cannot
# resolve on the host — the exact failure this script exists to prevent. So: probe the
# documented /health path first, and fall back to accepting ANY HTTP status.
probe_http() {  # url
    local url="$1"
    if have curl; then
        curl -fsS -m 4 -o /dev/null "$url" 2>/dev/null && return 0
        curl -sS -m 4 -o /dev/null -w '%{http_code}' "$url" 2>/dev/null | grep -qE '^[1-5][0-9][0-9]$' && return 0
        return 1
    fi
    timeout 5 python3 - "$url" <<'PY' 2>/dev/null
import sys, urllib.request, urllib.error
try:
    urllib.request.urlopen(sys.argv[1], timeout=4)
except urllib.error.HTTPError:
    sys.exit(0)          # a status code IS an answer: the server is there
except Exception:
    sys.exit(1)
PY
}
first_ok() {  # label candidates...
    local label="$1"; shift
    for c in "$@"; do
        if probe_http "$c"; then printf '%s\t%s\n' "$label" "$c"; return 0; fi
    done
    printf '%s\t%s\n' "$label" "$1"   # nothing answered: keep the first, and flag it
    return 1
}
# Probes use the /health path (documented in the gateway healthcheck); the value that
# goes into the config is the same host:port with the real /mcp path.
kb_ok() { probe_http "${1%/mcp}/health"; }
KB_URL=""; OR_URL=""; DEGRADED=0
# Candidate order matters: the PUBLISHED host ports come first, because those are the
# ones a host process can actually use. compose publishes:
#   archie_mcp_gateway  127.0.0.1:17800 -> 7800   "It is NOT network-reachable."
#   omniroute           127.0.0.1:20128 -> 20128  published so the HOST CLI can reach it
# The docker service names (archie_mcp_gateway:7800 / omniroute:20128) are what the
# lane config carries and they do NOT resolve on the host — a verbatim copy of the lane
# config is broken, which is the whole reason this script exists rather than a `cp`.
KB_CANDIDATES="http://127.0.0.1:17800 http://localhost:17800 http://127.0.0.1:7800 http://archie_mcp_gateway:7800"
KB_PICK=""
for c in $KB_CANDIDATES; do
    if kb_ok "$c/mcp"; then KB_PICK="$c"; break; fi
done
if [ -z "$KB_PICK" ]; then
    KB_PICK="http://archie_mcp_gateway:7800"
    say "  ! no archie-kb gateway answered — falling back to the compose service name, which only resolves ON the compose network"
    DEGRADED=1
fi
KB_URL="$KB_PICK/mcp"
say "  archie-kb gateway : $KB_URL"
# ⚠️ `|| true` is REQUIRED on both assignments. When every candidate fails to answer,
# first_ok exits non-zero by design (that is how DEGRADED gets set), and `set -e` +
# `pipefail` would kill the script mid-install with no message. This is the third time
# this exact trap has shipped in this session; both `|| true`s are load-bearing.
OR_URL="$( { first_ok omniroute http://127.0.0.1:20128/v1/models http://localhost:20128/v1/models http://omniroute:20128/v1/models || true; } | cut -f2)"
[ -n "$OR_URL" ] || OR_URL="http://127.0.0.1:20128/v1/models"
OR_BASE="${OR_URL%/models}"
say "  omniroute baseURL : $OR_BASE"

# Secrets: on the host these live in the repo, not /run/secrets.
HOSTINGER_SECRET="$SECRETS_REPO/hostinger_token.txt"
[ -r "$HOSTINGER_SECRET" ] || { say "  ! $HOSTINGER_SECRET unreadable — the hostinger MCP will start but fail to auth"; DEGRADED=1; }
GH_SECRET="$SECRETS_REPO/github_token.txt"
[ -r "$GH_SECRET" ] || { say "  ! $GH_SECRET unreadable — git push from the host will not authenticate"; DEGRADED=1; }

# ---------------------------------------------------------------------------
step "Plan"
# ---------------------------------------------------------------------------
say "  1. npm i -g opencode-ai@$OPENCODE_VERSION"
if ! have ssh; then say "  2. apt-get install -y openssh-client   (ssh is the half of parity group_add can never give)"; else say "  2. openssh-client already present"; fi
say "  3. seed $CFG from $SRC_CONTAINER, rewriting container-only endpoints"
say "     archie-kb -> $KB_URL"
say "     omniroute -> $OR_BASE"
say "     hostinger -> $HOSTINGER_SECRET"
if [ -f "$HOST_DOCS/GUARDRAILS.md" ]; then
  say "  3b. install HOST GUARDRAILS.md + data/archie-handover.md from $HOST_DOCS"
else
  say "  3b. ! $HOST_DOCS/GUARDRAILS.md missing — will fall back to the container's"
  say "      copy, which is NOT host-correct (only the handover path is rewritten)"
  DEGRADED=1
fi
say "  4. git credential helper -> $GH_SECRET"
[ "$DEGRADED" = "1" ] && say "  ! one or more endpoints could NOT be verified from this host — see above"

if [ "$APPLY" = "0" ] && [ -t 0 ]; then
  # Interactive confirmation instead of a required --apply. 2026-09-30: this terminal
  # dropped trailing tokens from three separate pastes, and a flag-driven installer is
  # exactly the shape that fails quietly — it printed the plan and exited 0 as though
  # nothing had been installed. The dangerous failure mode is silence, so there is no
  # silent path: either you type APPLY, or it installs nothing.
  cat <<'EOF'

Nothing has been installed. This WILL install opencode-ai system-wide, install
openssh-client if absent, and write ~/.config/opencode/opencode.json.
EOF
  printf "  type APPLY to install: "
  read -r _confirm
  if [ "$_confirm" != "APPLY" ]; then
    say ""
    say "  cancelled — nothing was installed."
    exit 0
  fi
  APPLY=1
fi

if [ "$APPLY" = "0" ]; then
  cat <<'EOF'

DRY RUN — nothing changed. Re-run with --apply.

This installs OpenCode as a HOST binary. It is not a sandbox and not a lane: it
runs as your user, with your docker group and your ssh. That is the point, and it
is also the reason it is opt-in.
EOF
  exit 0
fi

# ---------------------------------------------------------------------------
step "Installing"
# ---------------------------------------------------------------------------
if have opencode && opencode --version 2>/dev/null | grep -q "$OPENCODE_VERSION"; then
  say "  opencode $OPENCODE_VERSION already installed — skipping"
else
  say "  installing opencode-ai@$OPENCODE_VERSION (this takes a minute)…"
  # sudo was the WRONG instinct here and it failed: `sudo npm` -> "sudo: npm: command
  # not found", because sudo resets PATH and npm lives in an nvm directory
  # (~/.nvm/versions/node/vX/bin) that is not in secure_path. Fixing it by chasing sudo
  # would have been the wrong fix anyway: under nvm the GLOBAL PREFIX is inside the
  # user's own home, so the user can write it and sudo is not needed at all. Escalate
  # only if the prefix genuinely is not writable, and pass the absolute npm path plus
  # PATH through so the same failure cannot recur.
  NPM_BIN="$(command -v npm 2>/dev/null || echo npm)"
  NPM_PREFIX="$(npm prefix -g 2>/dev/null || echo "")"
  if [ -n "$NPM_PREFIX" ] && [ -w "$NPM_PREFIX" ]; then
    say "  global prefix $NPM_PREFIX is yours — no sudo needed"
    "$NPM_BIN" i -g "opencode-ai@$OPENCODE_VERSION"
  elif have sudo && [ "$(id -u)" != "0" ]; then
    say "  global prefix $NPM_PREFIX is not writable — using sudo with an explicit PATH"
    sudo env "PATH=$PATH" "$NPM_BIN" i -g "opencode-ai@$OPENCODE_VERSION"
  else
    "$NPM_BIN" i -g "opencode-ai@$OPENCODE_VERSION"
  fi
fi

if ! have ssh; then
  say "  installing openssh-client…"
  if have sudo && [ "$(id -u)" != "0" ]; then
    sudo apt-get update -qq && sudo apt-get install -y -qq openssh-client
  else
    apt-get update -qq && apt-get install -y -qq openssh-client
  fi
  have ssh && say "  ssh installed: $(command -v ssh)" || say "  WARNING: ssh still absent"
fi

# ---------------------------------------------------------------------------
step "Seeding config"
# ---------------------------------------------------------------------------
mkdir -p "$CFG_DIR"
[ -f "$CFG" ] && { cp -a "$CFG" "$CFG.bak-$(date +%Y%m%d-%H%M%S)"; say "  backed up existing config"; }

# Pull the WORKING config out of the running container, then rewrite it for the host.
RAW="$(docker exec "$SRC_CONTAINER" cat /opencode-home/config/opencode/opencode.json)"
say "  read config from container ($(printf '%s' "$RAW" | wc -c) bytes)"

CFG="$CFG" KB_URL="$KB_URL" OR_BASE="$OR_BASE" HOSTINGER_SECRET="$HOSTINGER_SECRET" \
SRC_CONTAINER="$SRC_CONTAINER" HOST_DOCS="$HOST_DOCS" python3 - <<'PY'
import json, os, subprocess, sys

cfg_path = os.environ["CFG"]
raw = subprocess.run(["docker", "exec", os.environ["SRC_CONTAINER"],
                      "cat", "/opencode-home/config/opencode/opencode.json"],
                     capture_output=True, text=True, check=True).stdout
c = json.loads(raw)

def n(v):  # report a length, never a value
    return f"<{len(str(v))} chars>"

# --- archie-kb: rewrite the compose service name to something the host can reach ---
mcp = c.setdefault("mcp", {})
kb = mcp.get("archie-kb", {})
if "headers" in kb and "Authorization" in kb["headers"]:
    kb["headers"]["Authorization"] = n(kb["headers"]["Authorization"]) + " (UNCHANGED — verify auth)"
kb["url"] = os.environ["KB_URL"]
mcp["archie-kb"] = kb

# --- omniroute: /run/secrets path -> the repo path on the host ---
hid = mcp.get("hostinger-api", {})
if "command" in hid:
    hid["command"] = ["/bin/sh", "-c",
        'export HOSTINGER_API_TOKEN=$(cat %s 2>/dev/null); exec hostinger-hosting-mcp'
        % os.environ["HOSTINGER_SECRET"]]
mcp["hostinger-api"] = hid

# --- providers: any baseURL pointing at a docker service name ---
for name, p in (c.get("provider") or {}).items():
    opts = p.get("options") or {}
    if opts.get("baseURL", "").startswith("http://omniroute:"):
        opts["baseURL"] = os.environ["OR_BASE"]
        p["options"] = opts

# --- instructions: the container path does not exist here ---
c["instructions"] = [os.path.join(os.path.dirname(cfg_path), "GUARDRAILS.md")]

# --- permissions: on the host the agent is the user, so ask less ---
c["permission"] = {"external_directory": {"*": "ask",
                   "/mnt/archie_brain/**": "allow"}}

with open(cfg_path, "w") as f:
    json.dump(c, f, indent=2)
    f.write("\n")
print("  wrote %s" % cfg_path)

# --- host instruction set ---------------------------------------------------
# GUARDRAILS.md: install the HOST copy from the tracked template, never by
# verbatim-copying the container's file. The container copy names
# /opencode-home/... paths that do not exist here, which is exactly the bug
# this template exists to prevent. `instructions` above already points here.
# Fallback (older checkout, no template): copy the container's file but REWRITE
# the one path that breaks /archie-boot, and say plainly that the rest is wrong.
g = os.path.join(os.path.dirname(cfg_path), "GUARDRAILS.md")
host_docs = os.environ.get("HOST_DOCS", "")
tmpl = os.path.join(host_docs, "GUARDRAILS.md") if host_docs else ""
handover_host = os.path.join(os.path.dirname(cfg_path), "data", "archie-handover.md")

def _write(path, data):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w") as f:
        f.write(data)

if tmpl and os.path.isfile(tmpl):
    with open(tmpl) as f:
        body = f.read()
    _write(g, body)
    print("  wrote %s from host template (%d bytes)" % (g, len(body)))
else:
    print("  ! %s not found — falling back to the container's GUARDRAILS.md"
          % (tmpl or "$HOST_DOCS/GUARDRAILS.md"))
    try:
        body = subprocess.run(["docker", "exec", os.environ["SRC_CONTAINER"],
                               "cat", "/opencode-home/config/opencode/GUARDRAILS.md"],
                              capture_output=True, text=True, check=True).stdout
        if body.strip():
            body = body.replace("/opencode-home/data/archie-handover.md", handover_host)
            _write(g, body)
            print("  wrote %s from container copy, handover path rewritten (%d bytes)"
                  % (g, len(body)))
            print("  ! NOTE: that copy still describes the CONTAINER — only the handover path was fixed.")
    except Exception as e:
        print("  note: could not write GUARDRAILS.md (%s) — `instructions` will point at a missing file"
              % type(e).__name__)

# handover: CREATE ONLY. Continuity must never be clobbered by a re-install.
hd_tmpl = os.path.join(host_docs, "handover.md") if host_docs else ""
if os.path.exists(handover_host):
    print("  handover already present — left untouched: %s" % handover_host)
elif hd_tmpl and os.path.isfile(hd_tmpl):
    with open(hd_tmpl) as f:
        _write(handover_host, f.read())
    print("  created %s (host handover seed)" % handover_host)
else:
    print("  note: no handover seed template — %s not created" % handover_host)
PY

# ---------------------------------------------------------------------------
step "Git credential helper (host)"
# ---------------------------------------------------------------------------
git config --global user.name  "OpenCode (host)" 2>/dev/null || true
git config --global user.email "opencode@kytranempowerment.com" 2>/dev/null || true
git config --global --add safe.directory /mnt/archie_brain 2>/dev/null || true

# ⚠️ credential.helper is GLOBAL — it is the SAME one Claude-CLI pushes through. An
# earlier draft overwrote it unconditionally, which would silently break the host's
# existing git auth (e.g. `gh auth git-credential`) for EVERY repo on the box, not just
# this one. Never clobber silently: if one is already set, leave it and offer the
# per-repo alternative instead.
EXISTING_HELPER="$( { git config --global --get-all credential.helper 2>/dev/null || true; } | tr '\n' ' ')"
if [ -n "$EXISTING_HELPER" ]; then
  say "  credential.helper already set — NOT touching it: $EXISTING_HELPER"
  say "    (that is what Claude-CLI pushes through; overwriting it would break host git auth)"
  say "    If opencode cannot push, set it per-repo instead:"
  say "      git -C /mnt/archie_brain config --local credential.helper '!f() { echo username=x-access-token; echo \"password=\$(cat '"$GH_SECRET"')\"; }; f'"
else
  git config --global credential.helper \
    "!f() { echo username=x-access-token; echo \"password=\$(cat $GH_SECRET)\"; }; f" 2>/dev/null || true
  say "  credential.helper set -> $GH_SECRET"
fi
say "  NOTE: that token is Contents-only (measured 2026-09-30: GET/POST /pulls -> 403)."
say "        The host can PUSH. To open a PR, use your own gh login instead."

# ---------------------------------------------------------------------------
step "Verifying"
# ---------------------------------------------------------------------------
fail=0
have opencode && say "  ✓ opencode $(opencode --version 2>/dev/null | head -1)" || { say "  ✗ opencode not on PATH"; fail=1; }

# ⚠️ TWO SHADOWS, not one. `type -a` catches an ALIAS or SHELL FUNCTION in ~/.bashrc,
# which `command -v` alone will not show correctly — and that is almost certainly what
# the owner hit: typing `opencode` produced
#   "No 'opencode' tmux session in archie_opencode_terminal — the lane's entrypoint
#    creates it. Try: docker compose restart archie_opencode_terminal"
# That text is not in /mnt/archie_brain/scripts/opencode (verified: an ELF opencode
# build with no tmux/docker-exec strings), so it comes from a wrapper in the owner's
# shell. A correct native install is INVISIBLE while that alias exists — which is the
# whole reason the last attempt looked like it had done nothing.
SHADOW=""
if type -a opencode >/dev/null 2>&1; then
    TYPE_OUT="$(type -a opencode 2>&1)"
    case "$TYPE_OUT" in
      *"is aliased"*|*"is a function"*)
        SHADOW="alias-or-function"
        say "  ✗ 'opencode' is an $(echo "$TYPE_OUT" | head -1 | sed 's/.*opencode is/opencode is/')"
        say "    That wrapper is why the install looked like it did nothing. It is in your"
        say "    shell rc, which this script cannot edit. Find it:"
        say "      grep -rn 'opencode' ~/.bashrc ~/.bash_aliases ~/.profile 2>/dev/null"
        say "    Then either remove it, or keep it and give the native build its own name:"
        say "      alias opencode-host=/usr/local/bin/opencode"
        fail=1 ;;
      *node_modules/opencode-ai*)
        say "  ✓ resolves to the npm install" ;;
      *"/bin/opencode"|*"/bin/opencode.exe")
        # nvm installs a plain symlink at <prefix>/bin/opencode -> ../lib/node_modules/
        # opencode-ai/bin/opencode.exe, so `type -a` shows the PREFIX, never the package
        # path. Matching on the literal package name therefore missed it and printed a
        # false "unexpected location" alarm on a perfectly good install. Resolve the
        # symlink and look at the target, and confirm it is a real npm package.
        _tgt="$(readlink -f "${TYPE_OUT#opencode is }" 2>/dev/null || true)"
        case "$_tgt" in
          *node_modules/opencode-ai*) say "  ✓ resolves to the npm install ($_tgt)" ;;
          *) say "  ! resolves to ${TYPE_OUT#opencode is } (target ${_tgt:-unknown}) — confirm it is the npm one" ;;
        esac ;;
      *scripts/opencode*)
        say "  ✗ resolves to the repo's old binary (/mnt/archie_brain/scripts/opencode)"
        say "      rm /mnt/archie_brain/scripts/opencode"
        fail=1 ;;
      *) say "  ! type -a says: $(echo "$TYPE_OUT" | head -3 | tr '\n' ' ')" ;;
    esac
else
    say "  ✗ no 'opencode' on PATH at all after install"
    fail=1
fi

have ssh      && say "  ✓ ssh present" || { say "  ✗ ssh missing"; fail=1; }
python3 -c "import json;json.load(open('$CFG'))" 2>/dev/null && say "  ✓ config parses" || { say "  ✗ config does not parse"; fail=1; }
# Host instruction set: the whole point of this fix — assert it landed and that
# it does NOT still send boot to the container's /opencode-home handover.
if [ -f "$CFG_DIR/GUARDRAILS.md" ]; then
  say "  ✓ host GUARDRAILS.md present"
else
  say "  ✗ host GUARDRAILS.md missing — \`instructions\` points at nothing"; fail=1
fi
if [ -f "$CFG_DIR/GUARDRAILS.md" ] && grep -q '/opencode-home/data/archie-handover.md' "$CFG_DIR/GUARDRAILS.md" 2>/dev/null; then
  say "  ✗ host GUARDRAILS.md still names the container's /opencode-home handover"; fail=1
elif [ -f "$CFG_DIR/GUARDRAILS.md" ]; then
  say "  ✓ host GUARDRAILS.md names no /opencode-home handover path"
fi
if [ -f "$CFG_DIR/data/archie-handover.md" ]; then
  say "  ✓ handover present ($CFG_DIR/data/archie-handover.md)"
else
  say "  ✗ handover missing at $CFG_DIR/data/archie-handover.md"; fail=1
fi
probe_http "$KB_URL" && say "  ✓ archie-kb gateway reachable" || { say "  ✗ archie-kb gateway NOT reachable from the host ($KB_URL)"; fail=1; }

echo
if [ "$fail" = 0 ]; then
  cat <<EOF

Host-parallel OpenCode is installed. Start it with:

    cd /mnt/archie_brain && opencode

TWO opencode, ON PURPOSE — do not confuse them:
  opencode             this one: NATIVE on the host, as $(id -un). Real docker, real ssh.
  ./scripts/opencode-Primary   the EXISTING launcher: docker exec into
                       $SRC_CONTAINER. Untouched by this script, still the way to reach
                       the web terminal on 127.0.0.1:17687.
  If you ever want a single obvious name, alias one — but pick deliberately, because
  two commands that both start "opencode" and differ by container-vs-host is how the
  next person (or agent) ends up in the wrong one.

What changes, concretely:
  * docker  — works, because you are $(id -un) and $(id -un) is in the docker group.
  * ssh     — available, so starbase / citadel / outpost are reachable. This is the
              thing a container can never give you.
  * files   — the whole host filesystem, no container boundary.
  * ship    — git push works; for a PR use your own gh login, because the lane PAT is
              Contents-only.

NOTE: this is a HOST agent, not a sandbox. It runs as you, with your ssh keys and your
docker group. That is what "parallel on host" means and it is why it is opt-in.
EOF
else
  say "Something did not verify — see the ✗ lines above. Nothing was rolled back; re-run after fixing."
fi
exit "$fail"
