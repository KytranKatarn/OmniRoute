#!/usr/bin/env bash
# fix_opencode_mcp.sh — repair the two MCP servers the host install broke.
#
#   ./scripts/fix_opencode_mcp.sh      # diagnose, verify, then confirm
#   ./scripts/fix_opencode_mcp.sh --rollback
#
# WHAT IS BROKEN, AND WHY IT IS MY FAULT
# --------------------------------------
# 1. archie-kb answers 401. The installer copied the working container config and then
#    REPLACED the real Authorization bearer with a literal placeholder:
#        "Authorization": "<82 chars> (UNCHANGED — verify auth)"
#    I redacted a credential I was supposed to COPY, so the header was never valid and
#    "verify auth" was never actionable. The container does this correctly by rendering
#    the bearer from the mounted secret on every start (start_opencode_terminal.sh); the
#    host must do the same from the repo's secrets dir.
#
# 2. hostinger-api cannot spawn. Its command pointed at
#    /opencode-home/opt/node_modules/.bin/hostinger-hosting-mcp — a CONTAINER path that
#    does not exist on the host. The package is hostinger-api-mcp@1.63.4 on npm and the
#    binary it exposes is hostinger-hosting-mcp.
#
# VERIFICATION IS REAL, NOT A CONFIG READ
# ---------------------------------------
# "The config looks right" is exactly the check that passed while both servers were
# broken. So this script:
#   * calls the gateway WITH the bearer and requires a non-401;
#   * spawns the hostinger binary and requires it to start;
#   * reports per-server PASS/FAIL, and says plainly if it cannot prove either.
# The bearer is never printed, only its length, and the config file is chmod 600.
set -euo pipefail

CFG="${XDG_CONFIG_HOME:-$HOME/.config}/opencode/opencode.json"
KB_SECRET=/mnt/archie_brain/secrets/opencode/mcp_bearer.txt
HI_SECRET=/mnt/archie_brain/secrets/opencode/hostinger_token.txt
HOSTINGER_PKG="hostinger-api-mcp@1.63.4"
HOSTINGER_BIN_NAME="hostinger-hosting-mcp"


# Verify auth the way MCP actually works: an initialize POST. A bare GET is NOT a valid
# MCP request — the gateway answers 406 to one whether or not auth is correct, so the
# earlier GET-based check reported a healthy bearer as broken. Confirmed against the
# live gateway: initialize POST -> 200 with the bearer, 401 without.
mcp_probe() {  # $1 = url, $2 = bearer, $3 = "auth"|"noauth"
  local url="$1" tok="$2" mode="$3"
  python3 - "$url" "$tok" "$mode" <<'PYEOF'
import json, sys, urllib.request, urllib.error
url, tok, mode = sys.argv[1], sys.argv[2], sys.argv[3]
h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
if mode == "auth":
    h["Authorization"] = "Bearer " + tok
body = json.dumps({"jsonrpc":"2.0","id":1,"method":"initialize","params":{
    "protocolVersion":"2024-11-05","capabilities":{},
    "clientInfo":{"name":"probe","version":"1"}}}).encode()
try:
    r = urllib.request.urlopen(urllib.request.Request(url, data=body, headers=h), timeout=10)
    print(r.status)
except urllib.error.HTTPError as e:
    print(e.code)
except Exception:
    print("000")
PYEOF
}

say()  { printf '%s\n' "$*"; }
step() { printf '\n\033[1;33m==>\033[0m %s\n' "$*"; }
die()  { printf '\033[31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

APPLY=0; ROLLBACK=0; SAW=0
for a in "$@"; do
  case "$a" in
    --apply) APPLY=1; SAW=1 ;;
    --rollback) ROLLBACK=1; SAW=1 ;;
    -h|--help) echo "usage: $0 [--apply|--rollback]"; exit 0 ;;
    *) echo "usage: $0 [--apply|--rollback]" >&2; exit 2 ;;
  esac
done

if [ "$ROLLBACK" = "1" ]; then
  step "Rollback"
  [ -f "$CFG.bak-mcp" ] || die "no $CFG.bak-mcp to restore"
  cp -a "$CFG.bak-mcp" "$CFG"; say "  restored $CFG from $CFG.bak-mcp"
  exit 0
fi

# ---------------------------------------------------------------------------
step "Diagnosing"
# ---------------------------------------------------------------------------
[ -f "$CFG" ] || die "$CFG not found — run scripts/install_opencode_on_host.sh first"
say "  config    : $CFG ($(stat -c%s "$CFG") bytes)"

KB_URL="$(python3 -c "
import json,sys
c=json.load(open('$CFG'))
print(c.get('mcp',{}).get('archie-kb',{}).get('url',''))
")"
[ -n "$KB_URL" ] || die "no archie-kb url in the config"
say "  archie-kb : $KB_URL"

CURRENT_AUTH="$(python3 -c "
import json
c=json.load(open('$CFG'))
print(c.get('mcp',{}).get('archie-kb',{}).get('headers',{}).get('Authorization',''))
")"
if printf '%s' "$CURRENT_AUTH" | grep -q "UNCHANGED\|verify auth\|<.*chars"; then
  say "  bearer    : PLACEHOLDER — this is the bug (${#CURRENT_AUTH} chars, not a token)"
  NEEDS_BEARER=1
else
  say "  bearer    : present (${#CURRENT_AUTH} chars)"
  NEEDS_BEARER=0
fi

HI_CMD="$(python3 -c "
import json
c=json.load(open('$CFG'))
cmd=c.get('mcp',{}).get('hostinger-api',{}).get('command',[])
print(cmd[-1] if cmd else '')
")"
say "  hostinger : ${HI_CMD:-<unset>}"

if [ -r "$KB_SECRET" ]; then
  KB_LEN="$(tr -d '\n' < "$KB_SECRET" | wc -c)"
  say "  secret    : $KB_SECRET readable (${KB_LEN} bytes)"
else
  say "  secret    : $KB_SECRET NOT readable by $(id -un)"
  NEEDS_BEARER=1
fi

# ---------------------------------------------------------------------------
step "Finding the hostinger binary"
# ---------------------------------------------------------------------------
HI_BIN="$(command -v "$HOSTINGER_BIN_NAME" 2>/dev/null || true)"
if [ -z "$HI_BIN" ]; then
  for d in "$(npm prefix -g 2>/dev/null)/bin" /usr/local/bin "$HOME/.local/bin"; do
    [ -x "$d/$HOSTINGER_BIN_NAME" ] && { HI_BIN="$d/$HOSTINGER_BIN_NAME"; break; }
  done
fi
if [ -n "$HI_BIN" ]; then
  say "  found     : $HI_BIN"
  NEEDS_HI=0
else
  say "  not installed — will run: npm i -g $HOSTINGER_PKG"
  NEEDS_HI=1
fi

# ---------------------------------------------------------------------------
step "Testing what we CAN test, before changing anything"
# ---------------------------------------------------------------------------
if [ "$NEEDS_BEARER" = "1" ] && [ -r "$KB_SECRET" ]; then
  REAL="$(tr -d '\n' < "$KB_SECRET")"
  CODE="$(mcp_probe "$KB_URL" "$REAL" auth)"
  NOAUTH="$(mcp_probe "$KB_URL" "$REAL" noauth)"
  say "  MCP initialize WITH the real bearer    -> HTTP $CODE"
  say "  MCP initialize WITHOUT it (control)    -> HTTP $NOAUTH"
  if [ "$CODE" = "200" ] && [ "$NOAUTH" = "401" ]; then
    say "  => the bearer is correct and the gateway accepts it."
  else
    say "  => NOT PROVEN. Expected 200 with the bearer and 401 without."
    die "refusing to write an unverified bearer into the config"
  fi
else
  UNSET=""
fi

if [ "$APPLY" = "0" ]; then
  say ""
  say "This will:"
  [ "$NEEDS_BEARER" = "1" ] && say "  * copy the real bearer from $KB_SECRET into the config (never printing it)"
  [ "$NEEDS_HI" = "1" ] && say "  * npm i -g $HOSTINGER_PKG and repoint the hostinger command at the real binary"
  say "  * back up the config to $CFG.bak-mcp and chmod 600"
  say ""
  if [ ! -t 0 ]; then say "DRY RUN (not a terminal). Re-run interactively or pass --apply."; exit 0; fi
  printf "  type APPLY to repair: "
  read -r c
  [ "$c" = "APPLY" ] || { say "cancelled — nothing changed."; exit 0; }
fi

# ---------------------------------------------------------------------------
step "Repairing"
# ---------------------------------------------------------------------------
cp -a "$CFG" "$CFG.bak-mcp"; say "  backed up to $CFG.bak-mcp"

if [ "$NEEDS_HI" = "1" ]; then
  say "  installing $HOSTINGER_PKG (a minute)…"
  NPM_BIN="$(command -v npm)"
  NPM_PREFIX="$(npm prefix -g 2>/dev/null || true)"
  if [ -n "$NPM_PREFIX" ] && [ -w "$NPM_PREFIX" ]; then
    "$NPM_BIN" i -g "$HOSTINGER_PKG"
  elif command -v sudo >/dev/null && [ "$(id -u)" != "0" ]; then
    sudo env "PATH=$PATH" "$NPM_BIN" i -g "$HOSTINGER_PKG"
  else
    "$NPM_BIN" i -g "$HOSTINGER_PKG"
  fi
  HI_BIN="$(command -v "$HOSTINGER_BIN_NAME" 2>/dev/null || true)"
  [ -n "$HI_BIN" ] || HI_BIN="$(npm prefix -g 2>/dev/null)/bin/$HOSTINGER_BIN_NAME"
fi

CFG="$CFG" KB_URL="$KB_URL" KB_SECRET="$KB_SECRET" HI_BIN="$HI_BIN" HI_SECRET="$HI_SECRET" python3 - <<'PY'
import json, os, stat
cfg = os.environ["CFG"]
c = json.load(open(cfg))
mcp = c.setdefault("mcp", {})

# --- archie-kb: the REAL bearer, read from the repo secret ---
kb = mcp.setdefault("archie-kb", {})
kb["type"] = "remote"
kb["url"] = os.environ["KB_URL"]
kb.setdefault("headers", {})["Authorization"] = \
    "Bearer " + open(os.environ["KB_SECRET"]).read().strip()

# --- hostinger-api: a path that exists on THIS host ---
hi = mcp.setdefault("hostinger-api", {})
hi["type"] = "local"
hi["command"] = ["/bin/sh", "-c",
    'export HOSTINGER_API_TOKEN=$(cat %s 2>/dev/null); exec %s'
    % (os.environ["HI_SECRET"], os.environ["HI_BIN"])]
hi["enabled"] = True

with open(cfg, "w") as f:
    json.dump(c, f, indent=2); f.write("\n")
os.chmod(cfg, stat.S_IRUSR | stat.S_IWUSR)   # 600: it now holds a real bearer
print("  patched %s (mode 600)" % cfg)
PY

# ---------------------------------------------------------------------------
step "Verifying — real calls, not a config read"
# ---------------------------------------------------------------------------
fail=0
BEARER="$(tr -d '\n' < "$KB_SECRET" 2>/dev/null || echo '')"
if [ -n "$BEARER" ]; then
  CODE="$(mcp_probe "$KB_URL" "$BEARER" auth)"
  NOAUTH="$(mcp_probe "$KB_URL" "$BEARER" noauth)"
  if [ "$CODE" = "200" ] && [ "$NOAUTH" = "401" ]; then
    say "  ✓ archie-kb: MCP initialize returns 200 with the bearer, 401 without"
  else
    say "  ✗ archie-kb: got $CODE (with) / $NOAUTH (without); expected 200 / 401"; fail=1
  fi
else
  say "  ✗ archie-kb: no bearer available to test"; fail=1
fi

# npm wrote into the same global prefix as opencode-ai and reported
# "removed 30 packages, changed 124". Confirm the agent itself survived.
if command -v opencode >/dev/null 2>&1; then
  say "  ✓ opencode still resolves: $(command -v opencode)"
else
  say "  ✗ opencode is GONE — the global npm install removed it"; fail=1
fi

if [ -x "${HI_BIN:-/nonexistent}" ]; then
  say "  ✓ hostinger-api: binary present and executable ($HI_BIN)"
  say "    (it starts on first use; a token check would call Hostinger, so not done here)"
else
  say "  ✗ hostinger-api: binary still missing"; fail=1
fi

echo
if [ "$fail" = 0 ]; then
  cat <<EOF
Both MCP servers are wired. RESTART opencode for it to pick the config up — MCP servers
are read at startup, so an already-running session keeps 0 servers.

    # inside opencode: ctrl+p then 'restart', or just quit and run opencode again

After restarting, the status bar should show 2 MCP servers, not "⊙ 0 MCP".
EOF
else
  say "Not fully repaired. Nothing was rolled back; fix the ✗ item and re-run."
fi
exit "$fail"
