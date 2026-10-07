#!/usr/bin/env bash
# opencode_gf_docker_parity.sh — give the guard-free OpenCode lane the SAME docker
# reach the canonical lane has, so it can ship like Claude-CLI instead of being told
# it cannot.
#
#   scripts/opencode_gf_docker_parity.sh            # dry run: print the plan, change nothing
#   scripts/opencode_gf_docker_parity.sh --apply    # do it (stops the old container, keeps it)
#   scripts/opencode_gf_docker_parity.sh --rollback # put the pre-988 container back
#
# WHY THIS EXISTS — the parity gap, measured, not guessed
# -------------------------------------------------------
# `docker-compose.yml` gives the canonical lane this, with a comment that names the
# exact failure this script fixes:
#
#     # uid 1000 cannot open a gid-988 0660 socket without being in that group.
#     group_add:
#       - "988"
#
# `archie_opencode_terminal_gf` is NOT in docker-compose.yml. It was created by hand
# on 2026-09-27 (see docs/superpowers/specs/2026-09-27-opencode-guard-free-terminal*)
# and the hand-typed `docker run` mounted /var/run/docker.sock but omitted --group-add.
# The mount is therefore present and USELESS:
#
#     uid=1000(node) gid=1000(node) groups=1000
#     srw-rw---- 1 root docker /var/run/docker.sock      <- gid 988, not a member
#     $ docker ps -> permission denied ... docker.sock
#
# Both documented workarounds then fail, and each failure reads like a different bug:
#   * /opencode-home/bin/mk-pr.sh needs `docker exec archie_platform` -> blocked
#   * opencode-pr needs Pull requests: write on the lane PAT      -> the PAT has
#     Contents only (measured: GET /pulls 403, POST /pulls 403, GET /git/ref 200)
# So the lane cannot open a PR even though opencode-pr is installed and both skills
# say it can. THAT is the parity gap this closes: one missing flag on one container.
#
# SAFETY — this recreates a container, which is not reversible by Ctrl-C. Therefore:
#   * the container to replace is NEVER deleted, only stopped and renamed
#     (<name>-pre988), so --rollback is a rename away;
#   * the run command is derived from the LIVE container via `docker inspect`, not
#     from a remembered invocation, because nothing in the repo records how _gf was
#     created (that absence is the whole reason this defect is possible);
#   * the docker gid is read from the socket at run time, never hardcoded;
#   * dry run is the DEFAULT. Nothing is created or destroyed without --apply.
#
# ⚠️ SCOPE OF THE GRANT. Docker socket access is ROOT-EQUIVALENT ON THE HOST, and
# scripts/set_lane_github_token.sh says so in terms: "since option B these lanes mount
# the docker socket and are root-equivalent on the host ... Do not mistake it for a
# sandbox." This script does not create a new privilege; it restores the one the
# canonical lane already has and this instance was always meant to have. It is still
# the largest thing this lane can hold, so it is opt-in and verbose about it.
set -euo pipefail

CONTAINER="${OPENCODE_GF_CONTAINER:-archie_opencode_terminal_gf}"
BACKUP="${CONTAINER}-pre988"
PLATFORM="${PLATFORM_CONTAINER:-archie_platform}"
MODE="${1:---dry-run}"
SHOW_ENV=0
[ "${2:-}" = "--show-env" ] && SHOW_ENV=1

say()  { printf '%s\n' "$*"; }
step() { printf '\n\033[1;33m==>\033[0m %s\n' "$*"; }
die()  { printf '\033[31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

[ "$MODE" = "--apply" ] || [ "$MODE" = "--dry-run" ] || [ "$MODE" = "--rollback" ] \
  || die "usage: $0 [--dry-run|--apply|--rollback]"

# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------
if [ "$MODE" = "--rollback" ]; then
    step "Rolling $CONTAINER back to the pre-parity container"
    docker inspect "$BACKUP" >/dev/null 2>&1 || die "no backup container named $BACKUP — nothing to roll back to"
    docker inspect "$CONTAINER" >/dev/null 2>&1 && die "$CONTAINER still exists; stop and rename it first (this script will not discard it)"
    say "restoring $BACKUP -> $CONTAINER"
    docker rename "$BACKUP" "$CONTAINER"
    docker start "$CONTAINER"
    say "rolled back. Note: the rolled-back container is the one WITHOUT docker group access."
    exit 0
fi

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------
step "Preflight"
command -v docker >/dev/null || die "docker is not on PATH — run this on the HOST, not inside the lane"
docker info >/dev/null 2>&1 || die "docker is present but not usable here (socket denied?); run it on the host"
docker inspect "$CONTAINER" >/dev/null 2>&1 || die "container $CONTAINER not found — set OPENCODE_GF_CONTAINER if it was renamed"
[ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER")" = "true" ] || say "note: $CONTAINER is currently stopped"

[ -S /var/run/docker.sock ] || die "/var/run/docker.sock is missing on this host — nothing to grant"
DOCKER_GID="$(stat -c '%g' /var/run/docker.sock)"
DOCKER_GNAME="$(stat -c '%G' /var/run/docker.sock)"
say "docker socket gid : $DOCKER_GID ($DOCKER_GNAME)  [read at run time, never hardcoded]"

HAS_GROUP="$(docker exec "$CONTAINER" sh -c 'id -G' 2>/dev/null | tr ' ' '\n' | grep -cx "$DOCKER_GID" || true)"
if [ "${HAS_GROUP:-0}" -gt 0 ]; then
    say "already in group $DOCKER_GID — nothing to do. (this script is idempotent)"
    exit 0
fi
say "current groups in $CONTAINER: $(docker exec "$CONTAINER" sh -c 'id -G' 2>/dev/null || echo '?')"

docker inspect "$BACKUP" >/dev/null 2>&1 \
  && die "$BACKUP already exists — resolve it first (it means a previous run was interrupted)"

# ---------------------------------------------------------------------------
# Reconstruct the run command FROM THE LIVE CONTAINER
# ---------------------------------------------------------------------------
step "Reconstructing the run command from $CONTAINER via docker inspect"
IMG="$(docker inspect -f '{{.Config.Image}}' "$CONTAINER")"
USER="$(docker inspect -f '{{.Config.User}}' "$CONTAINER")"
WORKDIR="$(docker inspect -f '{{.Config.WorkingDir}}' "$CONTAINER")"
HOSTNAME_C="$(docker inspect -f '{{.Config.Hostname}}' "$CONTAINER")"
RESTART="$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' "$CONTAINER")"
NETMODE="$(docker inspect -f '{{.HostConfig.NetworkMode}}' "$CONTAINER")"
PRIV="$(docker inspect -f '{{.HostConfig.Privileged}}' "$CONTAINER")"
ROROOT="$(docker inspect -f '{{.HostConfig.ReadonlyRootfs}}' "$CONTAINER")"
say "image=$IMG user=${USER:-<image default>} restart=$RESTART network=$NETMODE"

RUN=(docker run -d --name "$CONTAINER")
# ⚠️ EVERY conditional below is an `if`, never `[ cond ] && action`.
# A `&&` list whose TEST is false evaluates to status 1, and under `set -e` that
# terminates the script. 2026-09-30: the first draft used `[ -n "$WORKDIR" ] && RUN+=(...)`
# and died silently the moment WorkingDir was empty — the dry run stopped between the
# "Reconstructing" banner and the planned command, which looked like a docker failure but
# was this line. Optional settings are the NORMAL case, so they must never be able to abort.
if [ -n "$USER" ];      then RUN+=(--user "$USER"); fi
if [ -n "$WORKDIR" ];   then RUN+=(-w "$WORKDIR"); fi
if [ -n "$HOSTNAME_C" ]; then RUN+=(--hostname "$HOSTNAME_C"); fi
if [ "$PRIV" = "true" ];   then RUN+=(--privileged); fi
if [ "$ROROOT" = "true" ]; then RUN+=(--read-only); fi
if [ -n "$RESTART" ] && [ "$RESTART" != "no" ]; then RUN+=(--restart "$RESTART"); fi

# Resource limits: carry them over from the live container. They were applied with
# `docker update` (2026-10-06: 8g / 4 cpus / 512 pids) and a bare reconstruction would
# silently drop them, handing the guard-free lane an unbounded hub again.
MEM="$(docker inspect -f '{{.HostConfig.Memory}}' "$CONTAINER")"
MEMSWAP="$(docker inspect -f '{{.HostConfig.MemorySwap}}' "$CONTAINER")"
NANOCPU="$(docker inspect -f '{{.HostConfig.NanoCpus}}' "$CONTAINER")"
PIDS="$(docker inspect -f '{{.HostConfig.PidsLimit}}' "$CONTAINER")"
if [ "${MEM:-0}" -gt 0 ];     then RUN+=(--memory "$MEM"); fi
if [ "${MEMSWAP:-0}" -gt 0 ]; then RUN+=(--memory-swap "$MEMSWAP"); fi
if [ "${NANOCPU:-0}" -gt 0 ]; then RUN+=(--cpus "$(awk "BEGIN{print $NANOCPU/1000000000}")"); fi
if [ "${PIDS:-0}" -gt 0 ];    then RUN+=(--pids-limit "$PIDS"); fi

# THE FIX — and the whole point of this script.
RUN+=(--group-add "$DOCKER_GID")

# Ports (published). The template emits "<containerPort> <HostIp> <HostPort>" — three
# fields, and the two that matter are the LAST two. An earlier draft read only two
# fields and bound the HostIp as the host port, producing `-p 127.0.0.1:7681/tcp`
# instead of `-p 127.0.0.1:17687:7681/tcp` — which would have moved the lane off the
# port the owner reaches it on. Read all three, in order.
docker inspect -f '{{range $p, $conf := .HostConfig.PortBindings}}{{range $conf}}{{$p}} {{.HostIp}} {{.HostPort}}
{{end}}{{end}}' "$CONTAINER" > /tmp/.gf_ports.$$
while read -r cport hip hport; do
    [ -n "${cport:-}" ] || continue
    [ -n "${hport:-}" ] || continue
    if [ -n "${hip:-}" ] && [ "$hip" != "0.0.0.0" ] && [ "$hip" != "::" ]; then
        RUN+=(-p "$hip:$hport:$cport")
    else
        RUN+=(-p "$hport:$cport")
    fi
done < /tmp/.gf_ports.$$
rm -f /tmp/.gf_ports.$$

# Mounts — ALL types. An earlier draft emitted only .Type == "bind", which silently
# DROPPED named volumes: the canonical service mounts opencode_terminal_home and
# opencode_terminal_work as volumes, so recreating from that command would have started
# the lane with no /opencode-home and no /work at all — no handover file, no skills, no
# repo clone. A missing mount is silent and destructive, so a volume type must be as
# loud as a bind. `volume` mounts print as "<name>:<dest>:<mode>", which is exactly
# what `docker run -v` wants.
docker inspect -f '{{range .Mounts}}{{if .Type}}{{if eq .Type "bind"}}{{.Source}}:{{.Destination}}:{{if .Mode}}{{.Mode}}{{else}}rw{{end}}{{else if eq .Type "volume"}}{{.Name}}:{{.Destination}}:{{if .Mode}}{{.Mode}}{{else}}rw{{end}}{{end}}
{{end}}{{end}}' "$CONTAINER" > /tmp/.gf_binds.$$
while read -r b; do if [ -n "$b" ]; then RUN+=(-v "$b"); fi; done < /tmp/.gf_binds.$$
rm -f /tmp/.gf_binds.$$

# Cap drops/adds — the lane's isolation posture, preserved exactly.
docker inspect -f '{{range .HostConfig.CapDrop}}{{.}}
{{end}}' "$CONTAINER" | { grep -v '^$' || true; } | while read -r c; do printf '%s\t%s\n' '--cap-drop' "$c"; done > /tmp/.gf_caps.$$
while IFS=$'\t' read -r flag val; do if [ -n "$val" ]; then RUN+=("$flag" "$val"); fi; done < /tmp/.gf_caps.$$
rm -f /tmp/.gf_caps.$$
docker inspect -f '{{range .HostConfig.CapAdd}}{{.}}
{{end}}' "$CONTAINER" | { grep -v '^$' || true; } | while read -r c; do printf '%s\t%s\n' '--cap-add' "$c"; done > /tmp/.gf_capa.$$
while IFS=$'\t' read -r flag val; do if [ -n "$val" ]; then RUN+=("$flag" "$val"); fi; done < /tmp/.gf_capa.$$
rm -f /tmp/.gf_capa.$$
docker inspect -f '{{range .HostConfig.SecurityOpt}}{{.}}
{{end}}' "$CONTAINER" | { grep -v '^$' || true; } | while read -r s; do if [ -n "$s" ]; then RUN+=(--security-opt "$s"); fi; done

# Env (names AND values — this is a lane, and hiding them would make the command lie).
docker inspect -f '{{range .Config.Env}}{{.}}
{{end}}' "$CONTAINER" | { grep -v '^$' || true; } | while read -r e; do
    name="${e%%=*}"
    if [ "$SHOW_ENV" = "1" ]; then
        printf '%s\t%s\n' '-e' "$e"
    else
        printf '%s\t%s\n' '-e' "$name=<redacted, ${#e} chars; pass --show-env to print>"
    fi
done > /tmp/.gf_env.$$
while IFS=$'\t' read -r flag val; do if [ -n "$val" ]; then RUN+=("$flag" "$val"); fi; done < /tmp/.gf_env.$$
rm -f /tmp/.gf_env.$$

# Entrypoint / Cmd. These are DIFFERENT things and docker takes them differently:
# --entrypoint replaces the image entrypoint, while Cmd is the argv appended AFTER the
# image name. Passing Cmd to --entrypoint (an easy slip — both are JSON arrays) starts
# the wrong process and the lane comes up looking dead. Split into arrays first so an
# argument containing a space survives.
json_array() {  # -> one argv element per line
    docker inspect -f "{{json .Config.$1}}" "$CONTAINER" \
      | sed 's/^\[//; s/\]$//' \
      | python3 -c 'import json,sys
raw = sys.stdin.read().strip()
try: print("\n".join(json.loads("[" + raw + "]")))
except Exception: sys.exit(1)' 2>/dev/null || true
}
EP_ARR=(); while IFS= read -r x; do if [ -n "$x" ]; then EP_ARR+=("$x"); fi; done < <(json_array Entrypoint)
CMD_ARR=(); while IFS= read -r x; do if [ -n "$x" ]; then CMD_ARR+=("$x"); fi; done < <(json_array Cmd)
if [ "${#EP_ARR[@]}" -gt 0 ]; then RUN+=(--entrypoint "${EP_ARR[0]}"); fi
# Remaining entrypoint elements are argv[1:] and must follow the image.
EP_TAIL=("${EP_ARR[@]:1}")

RUN+=("$IMG")
RUN+=("${EP_TAIL[@]}" "${CMD_ARR[@]}")

# Networks beyond the default.
docker inspect -f '{{range $n, $c := .NetworkSettings.Networks}}{{$n}}
{{end}}' "$CONTAINER" | { grep -v '^$' || true; } | while read -r n; do
    if [ "$n" != "$NETMODE" ]; then printf -- '--network %s\n' "$n"; fi
done > /tmp/.gf_nets.$$
while read -r l; do if [ -n "$l" ]; then RUN+=("$l"); fi; done < /tmp/.gf_nets.$$
rm -f /tmp/.gf_nets.$$

# The mounts below are not decoration: /opencode-home holds the handover file, the
# skills and opencode's own config; /work holds the repo clone. Losing either starts a
# lane that LOOKS healthy and has no memory. The command can be byte-perfect and still
# be wrong here, so the dry run calls this out by name rather than trusting you to
# eyeball a wall of -v flags.
MISSING_MOUNTS=""
printf '%s\n' "${RUN[@]}" > /tmp/.gf_argv.$$
for want in opencode-home work; do
    if ! grep -q -- ":/$want:" /tmp/.gf_argv.$$; then
        MISSING_MOUNTS="$MISSING_MOUNTS /$want"
    fi
done
rm -f /tmp/.gf_argv.$$
if [ -n "$MISSING_MOUNTS" ]; then
    say ""
    say "  !! NO MOUNT for:$MISSING_MOUNTS"
    say "     The source container had no such mount, so this is faithful — but it means"
    say "     the lane would start with an empty home and/or no repo clone. Confirm that"
    say "     is intended before applying."
fi

step "Planned command"
printf '  %s\n' "${RUN[*]}"

if [ "$MODE" = "--dry-run" ]; then
    cat <<'EOF'

DRY RUN — nothing was changed. Re-run with --apply to execute the plan above.

Before you do, sanity-check two things in that command, because a wrong flag here
takes the lane down:
  * every -v mount is present, especially the opencode-home and work VOLUMES (your
    session, handover file and git history live in them);
  * the published port is the one you reach the lane on (17687).

To roll back after applying:  scripts/opencode_gf_docker_parity.sh --rollback
EOF
    exit 0
fi

# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------
step "Applying"
say "stopping $CONTAINER (it is NOT removed)"
docker stop "$CONTAINER" >/dev/null
say "renaming it to $BACKUP so rollback is a rename away"
docker rename "$CONTAINER" "$BACKUP"
say "creating the replacement with --group-add $DOCKER_GID"
docker "${RUN[@]}"

step "Verifying — these must all be true"
fail=0
G="$(docker exec "$CONTAINER" sh -c 'id -G' | tr ' ' '\n' | grep -cx "$DOCKER_GID" || true)"
[ "${G:-0}" -gt 0 ] && say "  ✓ in docker group $DOCKER_GID" || { say "  ✗ NOT in docker group $DOCKER_GID"; fail=1; }

if docker exec "$CONTAINER" docker ps >/dev/null 2>&1; then say "  ✓ docker socket works"
else say "  ✗ docker socket still denied"; fail=1; fi

if docker exec "$CONTAINER" docker exec -i "$PLATFORM" true 2>/dev/null; then
  say "  ✓ can docker exec into $PLATFORM  <- mk-pr.sh's route now works"
else
  say "  ✗ cannot docker exec into $PLATFORM (is $PLATFORM running?)"
  fail=1
fi

if docker exec "$CONTAINER" sh -c 'test -d /opencode-home/data && test -f /opencode-home/data/archie-handover.md' 2>/dev/null; then
  say "  ✓ /opencode-home volume carried over (handover present)"
else
  say "  ✗ /opencode-home looks empty — the volume did NOT carry over. Roll back:"
  say "      scripts/opencode_gf_docker_parity.sh --rollback"
  exit 1
fi

echo
if [ "$fail" -eq 0 ]; then
  say "Parity restored. In the lane, re-check whether a PR can be opened:"
  say "    1. PAT route:  bash /opencode-home/bin/mk-pr.sh <branch>   (needs docker, now present)"
  say "    2. or the platform token route the skills describe — never copy that token out."
  say "    3. Separately: opencode-pr still needs 'Pull requests: write' on the lane PAT."
    say "       scripts/set_lane_github_token.sh opencode wires a token, but VERIFY it"
    say "       actually has PR scope before trusting it — that script's check only"
    say "       tests Contents:push, so a contents-only token passes it silently."
else
  say "Something did not verify. The old container is intact as $BACKUP."
  say "Roll back with:  scripts/opencode_gf_docker_parity.sh --rollback"
fi
exit "$fail"
