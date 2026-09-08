#!/bin/bash
# ============================================================================
# Regression tests for beacon_flip.sh — task #5264, found by the 2026-07-27
# live DR drill.
#
#   bash scripts/dr/test_beacon_flip.sh
#
# Self-contained: builds its own Caddyfile fixture, stubs the ssh seam to run
# locally, and stubs caddy/systemctl as exported shell FUNCTIONS (not files on
# disk — /tmp is noexec on the hub, which makes stub binaries fail rc=126 and
# every `caddy validate` look like a validation failure).
#
# WHAT THIS PINS
#   The drill found beacon_flip_ports reporting "validated + reloaded" while
#   substituting NOTHING: PR #2497 moved mesh.'s upstream to the reverse tunnel
#   (127.0.0.1:8095), so the hardcoded 100.64.0.4:8095 pattern stopped matching.
#   sed changed zero lines, caddy validated an unchanged file, and the flip
#   claimed success. In a real outage the tunnel dies WITH the hub, so the one
#   hostname that must keep answering would have been silently abandoned.
# ============================================================================
set -uo pipefail
# Resolve beacon_flip.sh RELATIVE TO THIS FILE, because this test runs from two
# different layouts: the repo (scripts/dr/) and the flat deployed DR directory
# on boston-2 (/opt/archie-dr/). It is a sibling in BOTH, whereas the old
# "$(dirname $0)/../.." resolved to /opt on boston-2, so `source` silently
# failed, every helper was undefined, and 6 assertions "passed" vacuously.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLIP="$HERE/beacon_flip.sh"
[ -f "$FLIP" ] || { echo "FATAL: beacon_flip.sh not found beside $0"; exit 2; }
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT

# Minimal fixture mirroring the REAL Beacon Caddyfile's shape.
cat > "$T/base" <<'CADDY'
# Beacon front door.
# The platform upstream is flipped during DR with:
#   sed 's#reverse_proxy http://100.64.0.4:3000#reverse_proxy http://100.64.0.10:3000#'
# ^ that COMMENT must never be rewritten by the flip.
(platform_backend) {
	reverse_proxy http://100.64.0.4:3000
}
platform.kytranempowerment.com {
	import platform_backend
}
creed.kytranempowerment.com {
	reverse_proxy http://100.64.0.4:8086
}
mesh.kytranempowerment.com {
	# Upstream is a PERSISTENT REVERSE TUNNEL from the hub (ssh -R), NOT the
	# hub mesh IP — pointing it at 100.64.0.4 deadlocks a hub reboot.
	reverse_proxy http://127.0.0.1:8095
}
server.kytranempowerment.com {
	reverse_proxy http://100.64.0.4:8085
}
plex.kytranempowerment.com {
	reverse_proxy http://100.64.0.4:32400
}
CADDY

log(){ echo "$*"; }
caddy(){ return 0; }
systemctl(){ return 0; }
export -f caddy systemctl

export HUB_MESH=100.64.0.4
# shellcheck disable=SC1091
source "$FLIP"
# Fail LOUD if the source did not actually define the helpers. Without this the
# suite reports "6 pass" against undefined functions — a false partial success.
for fn in beacon_flip_ports beacon_hub_host_for_port; do
    type "$fn" >/dev/null 2>&1 || { echo "FATAL: $fn undefined after sourcing $FLIP"; exit 2; }
done

# Capture the REAL _beacon_ssh BEFORE the stub below replaces it. T7 needs it: the entire
# point of BEACON_LOCAL=1 is that _beacon_ssh runs the command string LOCALLY instead of
# over ssh, and a stub that always runs locally cannot tell the two branches apart.
_REAL_BEACON_SSH_DEF="$(declare -f _beacon_ssh)"

touch "$T/fakekey"
FLEET_KEY="$T/fakekey"
BEACON_BAK_SUFFIX=".bak-test"
_beacon_ssh(){ bash -c "$1"; }

# 🔴 T1-T6 are pinned to the REMOTE shape on purpose, and this is a SAFETY property.
# On the actual front door (Citadel, which runs the `beacon` container) the auto-detect
# resolves BEACON_LOCAL=1, and the validate/reload commands then become
# `docker exec beacon caddy validate|reload --config /etc/caddy/Caddyfile` — the REAL
# production Caddyfile, not this suite's temp fixture. Running the suite bare on that
# host would issue a live `caddy reload` against the public front door on every case.
# These cases exercise the sed/substitution logic, which is transport-agnostic, so the
# remote shape (with the `caddy`/`systemctl` shell stubs above) is both safe and correct.
# Setting this HERE rather than requiring the caller to export BEACON_LOCAL is what keeps
# T8 honest — see the isolation note there.
BEACON_LOCAL=0

pass=0; fail=0
check(){ if [ "$2" = "$3" ]; then echo "  PASS  $1"; pass=$((pass+1));
         else echo "  FAIL  $1 (expected '$2', got '$3')"; fail=$((fail+1)); fi; }
# ANCHORED like the sed is — an unanchored match reads the documenting comment
# above instead of the live directive and reports a good flip as failed.
upstream_for(){ grep -oE "^[[:space:]]*reverse_proxy http://[0-9.]+:$1" "$BEACON_CADDYFILE" \
                | head -1 | sed 's|.*http://||'; }

echo "=== T1: platform :3000 hub -> DR ==="
BEACON_CADDYFILE="$T/c1"; cp "$T/base" "$BEACON_CADDYFILE"
beacon_flip_ports 100.64.0.4 100.64.0.10 platform 3000 >/dev/null; rc=$?
check "returns 0" 0 "$rc"
check ":3000 now on boston-2" "100.64.0.10:3000" "$(upstream_for 3000)"
check "exactly 1 line changed" "1" "$(diff "$T/base" "$BEACON_CADDYFILE" | grep -c '^>')"
check "documenting COMMENT untouched" "1" "$(grep -c '^#.*100\.64\.0\.4:3000' "$BEACON_CADDYFILE")"
check "hub-only :8085 untouched" "100.64.0.4:8085" "$(upstream_for 8085)"
check "hub-only :32400 untouched" "100.64.0.4:32400" "$(upstream_for 32400)"

echo "=== T2: mesh :8095 hub -> DR  (THE #5264 REGRESSION) ==="
BEACON_CADDYFILE="$T/c2"; cp "$T/base" "$BEACON_CADDYFILE"
beacon_flip_ports 100.64.0.4 100.64.0.10 headscale 8095 >/dev/null; rc=$?
check "returns 0" 0 "$rc"
check "mesh. actually moved to boston-2 (was a silent no-op)" "100.64.0.10:8095" "$(upstream_for 8095)"

echo "=== T3: mesh :8095 DR -> hub — failback must restore the TUNNEL ==="
beacon_flip_ports 100.64.0.10 100.64.0.4 headscale 8095 >/dev/null; rc=$?
check "returns 0" 0 "$rc"
check "back on the reverse tunnel, NOT the hub mesh IP" "127.0.0.1:8095" "$(upstream_for 8095)"
check "round-trip is byte-identical to baseline" "" "$(diff "$T/base" "$BEACON_CADDYFILE")"

echo "=== T4: no matching upstream must FAIL LOUD, never report success ==="
BEACON_CADDYFILE="$T/c4"; cp "$T/base" "$BEACON_CADDYFILE"
out="$(beacon_flip_ports 100.64.0.4 100.64.0.10 bogus 9999 2>&1)"; rc=$?
check "returns 1" 1 "$rc"
check "says NOTHING WAS FLIPPED" "yes" "$(echo "$out" | grep -q 'NOTHING WAS FLIPPED' && echo yes || echo no)"
check "Caddyfile untouched" "" "$(diff "$T/base" "$BEACON_CADDYFILE")"

echo "=== T5: creed :8086 unaffected by the :8095 special case ==="
BEACON_CADDYFILE="$T/c5"; cp "$T/base" "$BEACON_CADDYFILE"
beacon_flip_ports 100.64.0.4 100.64.0.10 creed 8086 >/dev/null; rc=$?
check "returns 0" 0 "$rc"
check ":8086 moved to boston-2" "100.64.0.10:8086" "$(upstream_for 8086)"

echo "=== T6: hub-side host map resolves per port ==="
check ":3000 -> hub mesh IP" "100.64.0.4" "$(beacon_hub_host_for_port 3000)"
check ":8086 -> hub mesh IP" "100.64.0.4" "$(beacon_hub_host_for_port 8086)"
check ":8095 -> reverse tunnel" "127.0.0.1" "$(beacon_hub_host_for_port 8095)"

echo "=== T7: BEACON_LOCAL=1 drives the CONTAINER, never host systemd ==="
# The Beacon VPS was removed 2026-08-28 and Citadel inherited the front door as a container
# literally named `beacon`: no host caddy, no systemd caddy unit, and no ssh-to-self. Every
# test above exercises the REMOTE shape, because THIS host runs no such container — so
# without T7/T8 the local branch would ship completely unexercised, which is how the whole
# ingress layer sat inert through the 2026-09-07 failover ("Beacon platform flip failed").
eval "$_REAL_BEACON_SSH_DEF"            # restore the real transport seam
BEACON_LOCAL=1
BEACON_CADDYFILE="$T/c7"; cp "$T/base" "$BEACON_CADDYFILE"
: > "$T/docker_calls"
# Record rather than assert-by-absence: proving WHICH command ran is the point.
docker(){ echo "docker $*" >> "$T/docker_calls"; return 0; }
systemctl(){ echo "systemctl $*" >> "$T/docker_calls"; return 0; }
export -f docker systemctl
export T                                 # the stubs resolve $T inside `bash -c`
beacon_flip_ports 100.64.0.4 100.64.0.10 platform 3000 >/dev/null; rc=$?
check "returns 0" 0 "$rc"
check ":3000 moved in the host bind-mount" "100.64.0.10:3000" "$(upstream_for 3000)"
check "validated INSIDE the beacon container" "yes" \
      "$(grep -q 'docker exec beacon caddy validate' "$T/docker_calls" && echo yes || echo no)"
check "reloaded INSIDE the beacon container" "yes" \
      "$(grep -q 'docker exec beacon caddy reload' "$T/docker_calls" && echo yes || echo no)"
check "never fell back to host systemd" "no" \
      "$(grep -q 'systemctl reload caddy' "$T/docker_calls" && echo yes || echo no)"
# The host file is /opt/archie-ingress/Caddyfile; caddy sees it at /etc/caddy/Caddyfile.
# Passing the HOST path to `docker exec` would validate a file that does not exist in the
# container — caddy would fail and the flip would roll back a change that was actually fine.
check "validated the CONTAINER path, not the host path" "yes" \
      "$(grep -q 'config /etc/caddy/Caddyfile' "$T/docker_calls" && echo yes || echo no)"

echo "=== T8: the front door is AUTO-DETECTED, never hardcoded ==="
# A hardcoded topology is what broke this twice: first the Beacon IP, then Beacon's very
# existence. Re-source the script in a clean sub-shell with only `docker ps` faked.
# ⚠️ `env -u` is LOAD-BEARING. T7 assigns BEACON_LOCAL=1, and if BEACON_LOCAL was already
# exported (e.g. a caller ran `BEACON_LOCAL=0 bash test_beacon_flip.sh` to stay off a real
# front door) that assignment updates the EXPORTED variable. The sub-shell would then
# inherit 1, skip the auto-detect entirely, and report the local paths for BOTH cases —
# a green-looking test that never exercised the detection it claims to cover. Measured on
# Citadel 2026-09-08: T8's negative case returned '1 /opt/archie-ingress/Caddyfile'.
_detect(){   # $1 = what `docker ps` should print ('' = no beacon container here)
  env -u BEACON_LOCAL -u BEACON_CADDYFILE \
      FLIP="$FLIP" PS_OUT="$1" HUB_MESH=100.64.0.4 bash -c '
      docker(){ if [ "$1" = "ps" ] && [ -n "$PS_OUT" ]; then echo "$PS_OUT"; fi; return 0; }
      export -f docker
      . "$FLIP" >/dev/null 2>&1
      echo "$BEACON_LOCAL $BEACON_CADDYFILE"'
}
check "beacon container present -> local + host bind-mount path" \
      "1 /opt/archie-ingress/Caddyfile" "$(_detect beacon)"
check "no beacon container -> remote + historical caddy path" \
      "0 /etc/caddy/Caddyfile" "$(_detect '')"

echo
echo "=== RESULT: $pass pass · $fail fail ==="
[ "$fail" -eq 0 ]
