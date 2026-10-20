#!/usr/bin/env bash
# Install the isolated DS9 Codex app-server (systemd unit + pinned runtime).
#
# Idempotent. Prints NO secret material: the capability token is generated,
# written with 0600 to a root-owned path, and never echoed.
#
#   sudo scripts/systemd/install-ds9-codex-appserver.sh
#
# What it does:
#   1. creates the dedicated `ds9-codex` system user
#   2. installs the PINNED codex 0.163.0 runtime to /usr/local/lib/ds9-codex
#   3. creates the isolated CODEX_HOME (/var/lib/ds9-codex) and scratch cwd
#   4. generates the WS capability token at /etc/ds9-codex/ws.token (0600)
#   5. installs + enables the systemd unit
#
# It does NOT touch the owner's ~/.codex, DS9's own service, or any existing
# Codex login. It does not enable the host `ds9` client profile.
set -euo pipefail

CODEX_VERSION="0.163.0"
CODEX_PKG="@openai/codex@${CODEX_VERSION}"
CODEX_PLATFORM_PKG="@openai/codex@${CODEX_VERSION}-linux-x64"

CODEX_HOME_DIR="/var/lib/ds9-codex"
WORK_DIR="/srv/ds9-codex/work"
TOKEN_DIR="/etc/ds9-codex"
TOKEN_FILE="${TOKEN_DIR}/ws.token"
UNIT_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/ds9-codex-appserver.service"
UNIT_DST="/etc/systemd/system/ds9-codex-appserver.service"
SERVICE_USER="ds9-codex"

log() { printf '[install-ds9-codex] %s\n' "$*"; }
die() { printf '[install-ds9-codex] ERROR: %s\n' "$*" >&2; exit 1; }

# The runtime lives in $RUNTIME_DIR/bin/codex (see the install step below).
RUNTIME_DIR="/usr/local/lib/ds9-codex"
CODEX_BIN="$RUNTIME_DIR/bin/codex"

# npm lives in the owner's nvm tree, which is NOT on root's PATH. Resolve it
# explicitly rather than assuming `npm` is reachable as root.
NPM_BIN=""
for candidate in \
  "$(command -v npm 2>/dev/null || true)" \
  /usr/local/bin/npm \
  /usr/bin/npm \
  /home/kytran/.nvm/versions/node/*/bin/npm \
  /root/.nvm/versions/node/*/bin/npm
do
  if [[ -n "$candidate" && -x "$candidate" ]]; then NPM_BIN="$candidate"; break; fi
done
[[ -n "$NPM_BIN" ]] || die "npm not found (looked on PATH and in nvm trees)"
[[ $EUID -eq 0 ]] || die "must run as root (sudo)"
[[ -f "$UNIT_SRC" ]] || die "unit file not found: $UNIT_SRC"

# ── 1. dedicated system user ───────────────────────────────────────────────
if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
  log "creating system user '$SERVICE_USER' (no login shell, no home)"
  useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
else
  log "system user '$SERVICE_USER' already exists"
fi

# ── 2. pinned codex runtime ────────────────────────────────────────────────
install -d -m 0755 "$RUNTIME_DIR"
if [[ -x "$CODEX_BIN" && -x "$RUNTIME_DIR/bin/codex-code-mode-host" ]] \
   && "$CODEX_BIN" --version 2>/dev/null | grep -q "codex-cli ${CODEX_VERSION}$"; then
  log "codex ${CODEX_VERSION} already installed at $RUNTIME_DIR"
else
  log "downloading ${CODEX_PLATFORM_PKG} (via ${NPM_BIN})"
  # Build in /var/tmp, NOT /tmp: on this host /tmp is a 2 GiB tmpfs that other
  # lanes fill, and this download is ~160 MiB compressed / ~370 MiB extracted.
  TMP="$(mktemp -d -p /var/tmp ds9-codex-build-XXXXXX)"
  trap 'rm -rf "$TMP"' EXIT
  export TMPDIR="$TMP"
  export npm_config_cache="$TMP/npm-cache"
  # npm's shebang is `#!/usr/bin/env node`; node is in the nvm tree, not on
  # root's PATH. Put the node bin dir on PATH for the call.
  NODE_BIN_DIR="$(dirname "$NPM_BIN")"
  ( cd "$TMP" && PATH="${NODE_BIN_DIR}:${PATH}" "$NPM_BIN" pack "$CODEX_PLATFORM_PKG" >/dev/null )
  TARBALL="$(find "$TMP" -name '*.tgz' -print -quit)"
  [[ -n "$TARBALL" ]] || die "npm pack produced no tarball"
  mkdir -p "$TMP/x" && tar xzf "$TARBALL" -C "$TMP/x"
  VENDOR="$TMP/x/package/vendor/x86_64-unknown-linux-musl"
  [[ -d "$VENDOR" ]] || die "unexpected package layout (no musl vendor dir)"
  BIN="$VENDOR/bin/codex"
  [[ -x "$BIN" ]] || die "unexpected package layout (no musl codex binary)"

  # Install the WHOLE bin/ directory, not just the entrypoint. The package ships
  # `codex-code-mode-host` alongside `codex`; the app-server launches it as the
  # tool host for harness tool calls. Copying only `bin/codex` yields an app-server
  # whose tool calls fail with "the tool host executable is missing" — the
  # text path still works, so it looks healthy until a tool is actually called.
  install -d -m 0755 "$RUNTIME_DIR/bin"
  install -m 0755 "$VENDOR"/bin/* "$RUNTIME_DIR/bin/"

  # The CLI resolves helper binaries (rg, bwrap) relative to its own path.
  if [[ -d "$VENDOR/codex-path" ]]; then
    cp -a "$VENDOR/codex-path" "$RUNTIME_DIR/"
  fi
  if [[ -d "$VENDOR/codex-resources" ]]; then
    cp -a "$VENDOR/codex-resources" "$RUNTIME_DIR/"
  fi
  chown -R root:root "$RUNTIME_DIR"
  log "installed codex runtime"
fi
INSTALLED_VERSION="$("$CODEX_BIN" --version 2>/dev/null | awk '{print $2}')"
[[ "$INSTALLED_VERSION" == "$CODEX_VERSION" ]] || die "version mismatch: expected ${CODEX_VERSION}, got '${INSTALLED_VERSION}'"
log "verified: codex --version -> ${INSTALLED_VERSION}"

# The tool-host binary MUST be present. The app-server launches it to execute
# harness tool calls; without it, tool calls fail with "the tool host executable
# is missing" while the text path still works — so this only surfaces when a
# tool is actually called. Assert it here, at install time, instead.
[[ -x "$RUNTIME_DIR/bin/codex-code-mode-host" ]] \
  || die "codex-code-mode-host is missing from $RUNTIME_DIR/bin (tool calls would fail)"
log "verified: codex-code-mode-host present"

# The app-server help must advertise the capability-token flags we depend on.
"$CODEX_BIN" app-server --help 2>&1 | grep -q -- "--ws-auth" \
  || die "pinned codex does not support --ws-auth (capability-token mode missing)"
"$CODEX_BIN" app-server --help 2>&1 | grep -q -- "--ws-token-file" \
  || die "pinned codex does not support --ws-token-file"
log "verified: app-server help advertises --ws-auth / --ws-token-file"

# ── 3. isolated home + scratch cwd ─────────────────────────────────────────
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0750 "$CODEX_HOME_DIR"
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0750 "$WORK_DIR"
log "prepared isolated CODEX_HOME ($CODEX_HOME_DIR) and scratch cwd ($WORK_DIR)"

# ── 4. WS capability token ─────────────────────────────────────────────────
install -d -o root -g "$SERVICE_USER" -m 0750 "$TOKEN_DIR"
if [[ ! -s "$TOKEN_FILE" ]]; then
  umask 077
  head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n' > "$TOKEN_FILE"
  log "generated a new WS capability token (value not shown)"
else
  log "reusing the existing WS capability token (value not shown)"
fi
chown root:"$SERVICE_USER" "$TOKEN_FILE"
chmod 0640 "$TOKEN_FILE"
# 0640 root:ds9-codex -> the service reads it via LoadCredential (as its own
# user); the group is what makes that possible without world-readability.

# ── 5. systemd unit ────────────────────────────────────────────────────────
install -m 0644 "$UNIT_SRC" "$UNIT_DST"
systemctl daemon-reload
systemctl enable ds9-codex-appserver.service >/dev/null
log "installed and enabled $UNIT_DST"

log "done. Next: systemctl start ds9-codex-appserver.service"
log "Then: systemctl status ds9-codex-appserver.service"
