#!/usr/bin/env bash
# Apply option B — give the codex and opencode lanes host-equivalent access.
# Owner decision 2026-09-13, taken knowingly after option A was put in writing.
#
# ─────────────────────────────────────────────────────────────────────────────
# 🔴 READ THIS BEFORE RUNNING. /var/run/docker.sock IS ROOT ON THIS HOST.
#
# A process holding that socket can start a privileged container mounting / and
# do anything the daemon can do. After this runs, `cap_drop: ALL`, `read_only:`
# and the dedicated per-lane networks all still LOOK like a boundary and are
# not one. Anyone who can type into codex.kytranempowerment.com or
# opencode.kytranempowerment.com can take the host.
#
# This script exists because the assistant is deliberately blocked from making
# this change (Claude Code auto-mode classifier, "Security Weaken", twice). That
# block is a control on the assistant, not a bug. Running this yourself is the
# intended path — the decision stays with a human who can see what it costs.
# Same pattern as scripts/provision_coder_lane_keys.sh.
# ─────────────────────────────────────────────────────────────────────────────
#
#   ./scripts/apply_option_b_coder_lane_host_access.sh            # dry run, shows the diff
#   ./scripts/apply_option_b_coder_lane_host_access.sh --apply    # asks you to type the phrase
#
# Idempotent: re-running after a successful apply reports "already wired" and exits 0.
# Reversible: restore the timestamped backup it writes, then recreate the two lanes.
set -euo pipefail

cd "$(dirname "$0")/.."
COMPOSE=docker-compose.yml
APPLY=0
[ "${1:-}" = "--apply" ] && APPLY=1

# The socket's group is read from the HOST, never hardcoded — opencode runs as
# uid 1000 and cannot open a 0660 socket it is not in the group for. A wrong gid
# fails CLOSED (every docker command says "permission denied"), which is why the
# verification below runs `docker ps` inside the lane rather than trusting this.
SOCK=/var/run/docker.sock
[ -S "$SOCK" ] || { echo "FATAL: $SOCK is not a socket — is docker running?" >&2; exit 1; }
SOCK_GID="$(stat -c %g "$SOCK")"
echo "docker socket: $SOCK (gid $SOCK_GID, mode $(stat -c %a "$SOCK"))"

# A socket is useless without a CLIENT. The first version of this script mounted the
# socket and never checked for one — both lane images had no `docker` binary, so a
# perfectly-applied mount still failed with "docker: not found". Added 2026-09-13.
# Checked BEFORE writing anything, so the run aborts instead of half-succeeding.
missing=""
for c in archie_codex_terminal archie_opencode_terminal; do
  docker exec "$c" sh -c 'command -v docker >/dev/null' 2>/dev/null || missing="$missing $c"
done
if [ -n "$missing" ]; then
  echo "FATAL: no docker client in:$missing" >&2
  echo "       Rebuild the lane images first — the Dockerfiles install a pinned" >&2
  echo "       CLIENT-only docker + compose plugin:" >&2
  echo "         docker compose build archie_codex_terminal archie_opencode_terminal" >&2
  exit 1
fi
echo "docker client: present in both lanes (inert until the socket is mounted)"

# ⚠️ `|| rc=$?` is load-bearing: the python below signals with exit codes (2 = dry run,
# 3 = already wired) and `set -e` would abort the script on them, so the dry-run diff
# never printed. Do not "simplify" this back to a bare call.
rc=0
python3 - "$COMPOSE" "$SOCK_GID" "$APPLY" <<'PY' || rc=$?
import io, re, sys, shutil, datetime
compose, sock_gid, apply = sys.argv[1], sys.argv[2], sys.argv[3] == "1"
s = io.open(compose, encoding="utf-8").read()
orig = s

BANNER = """      # ───────────────────────────────────────────────────────────────────────
      # 🔴 HOST-EQUIVALENT. Owner decision 2026-09-13 (option B), applied by
      # scripts/apply_option_b_coder_lane_host_access.sh.
      #
      # /var/run/docker.sock IS ROOT ON THIS HOST. A process holding it can start
      # a privileged container mounting / . cap_drop, read_only and the dedicated
      # network below still look like a boundary and are not one. That is why this
      # lane is labelled HOST in the UI (terminal_lanes.py `contained: False`) —
      # do NOT "tidy" that back to True.
      #
      # /mnt/archie_brain is the LIVE tree archie_platform serves, not a clone. An
      # edit here is served on the next request. Same path as the host so
      # CLAUDE.md, .claude/rules and scripts/ resolve exactly as claude sees them.
      # ───────────────────────────────────────────────────────────────────────
"""
MOUNTS = """      - /mnt/archie_brain:/mnt/archie_brain
      - /var/run/docker.sock:/var/run/docker.sock
"""

LANES = {
    "archie_codex_terminal":    "      - ./codex/skills:/opt/archie-codex-skills:ro\n",
    "archie_opencode_terminal": "      - opencode_terminal_work:/work\n",
}

def block(src, svc):
    m = re.search(r"\n  %s:(.*?)(?=\n  [a-z_]+:\n)" % svc, src, re.S)
    if not m:
        sys.exit("FATAL: service %s not found in %s" % (svc, compose))
    return m

wired = []
for svc, anchor in LANES.items():
    if "/var/run/docker.sock" in block(s, svc).group(1):
        wired.append(svc); continue
    if s.count(anchor) != 1:
        sys.exit("FATAL: anchor for %s matched %d times, expected 1 — compose has "
                 "changed shape; apply by hand using the spec." % (svc, s.count(anchor)))
    s = s.replace(anchor, anchor + BANNER + MOUNTS)

# opencode runs as uid 1000 and needs the docker GROUP; codex runs as root and does not.
oc = block(s, "archie_opencode_terminal")
if "group_add:" not in oc.group(1):
    add = ('\n    # uid 1000 cannot open a gid-%s 0660 socket without being in that group.\n'
           '    # Read from the host at apply time, never hardcoded. Fails CLOSED if wrong.\n'
           '    group_add:\n      - "%s"' % (sock_gid, sock_gid))
    end = oc.end(1) - len(oc.group(1)) + oc.group(1).index("\n    volumes:")
    s = s[:end] + add + s[end:]

if len(wired) == len(LANES) and s == orig:
    print("already wired — both lanes have the socket and the live tree. Nothing to do.")
    sys.exit(3)
if wired:
    print("note: %s already wired; patching the rest." % ", ".join(wired))

if not apply:
    io.open("/tmp/_optionb_preview.yml", "w", encoding="utf-8").write(s)
    print("\nDRY RUN — nothing written. Preview at /tmp/_optionb_preview.yml")
    print("Re-run with --apply to write it.\n")
    sys.exit(2)

stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
backup = "%s.bak-optionb-%s" % (compose, stamp)
shutil.copy2(compose, backup)
io.open(compose, "w", encoding="utf-8").write(s)
print("wrote %s (backup: %s)" % (compose, backup))
PY
[ $rc -eq 3 ] && exit 0
[ $rc -eq 2 ] && { echo "--- diff that WOULD be applied ---"; diff -u "$COMPOSE" /tmp/_optionb_preview.yml || true; exit 0; }

if [ "$APPLY" != "1" ]; then exit 0; fi

# Typed confirmation AFTER the diff is on screen, so consent follows seeing it.
echo
echo "This makes both coder lanes ROOT-EQUIVALENT on this host."
printf 'Type exactly: I ACCEPT HOST ACCESS  > '
read -r CONFIRM
if [ "$CONFIRM" != "I ACCEPT HOST ACCESS" ]; then
  echo "Not confirmed — reverting." >&2
  cp -p "$(ls -t ${COMPOSE}.bak-optionb-* | head -1)" "$COMPOSE"
  echo "docker-compose.yml restored. Nothing was deployed."
  exit 1
fi

docker compose config -q || {
  echo "FATAL: compose no longer validates — restoring." >&2
  cp -p "$(ls -t ${COMPOSE}.bak-optionb-* | head -1)" "$COMPOSE"; exit 1; }

docker compose up -d --force-recreate archie_codex_terminal archie_opencode_terminal

echo
echo "=== VERIFY (a passing 'docker ps' is the only real proof; a wrong gid fails closed) ==="
for c in archie_codex_terminal archie_opencode_terminal; do
  printf '  %-26s socket: ' "$c"
  if docker exec "$c" docker ps --format '{{.Names}}' >/dev/null 2>&1; then echo "OK"; else echo "DENIED"; fi
done
# ⚠️ Do NOT add 2>/dev/null here. It did, and git's "dubious ownership" refusal (the
# repo is uid 1000, codex is root) came out as a bare "lane-unknown" that read like a
# missing mount. An EMPTY result is not a PASS — show the error.
printf '  live tree mounted:      '
for c in archie_codex_terminal archie_opencode_terminal; do
  docker exec "$c" test -f /mnt/archie_brain/docker-compose.yml \
    && printf '%s=OK ' "$c" || printf '%s=MISSING ' "$c"
done; echo
printf '  git usable in the tree: '
docker exec archie_codex_terminal git -C /mnt/archie_brain rev-parse --abbrev-ref HEAD 2>&1 | head -2

cat <<'NEXT'

STILL TO DO — tell Claude the mounts are live and it will:
  • flip `contained: False` for codex + opencode in archie-comms/services/terminal_lanes.py
  • move the tests pinning `contained is True`
  • rebuild archie_comms so the pills read "⚠ HOST · no container"
Until that lands the UI calls these lanes "contained", which is now FALSE.

NOT covered by this script: shipping code. Neither lane has a working GitHub
credential (codex's returns "Bad credentials", opencode has none by design).
Minting one is yours — secrets/ is root-owned.

TO REVERT: restore docker-compose.yml.bak-optionb-<stamp>, then
  docker compose up -d --force-recreate archie_codex_terminal archie_opencode_terminal
NEXT
