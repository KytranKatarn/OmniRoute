#!/usr/bin/env bash
# link_lane_commands.sh — make the three opencode entry points work as BARE words.
#
#   ./scripts/link_lane_commands.sh      # inspect, then confirm
#   ./scripts/link_lane_commands.sh --rollback
#
# WHY
# ---
# Typing `opencode-Primary` does nothing today: the script lives at
# /mnt/archie_brain/scripts/opencode-Primary, and /mnt/archie_brain/scripts is NOT on
# PATH (probe 2026-09-30 confirms zero archie_brain entries in it). You would have to
# write ./scripts/opencode-Primary every time. ~/.local/bin IS on PATH and is the first
# entry, so a symlink there makes the name work from anywhere.
#
# The three entry points, and why they are three and not one:
#
#   opencode            NATIVE HOST install. Real docker, real ssh, whole filesystem.
#                       This is the "parallel on host" one.
#   opencode-docker     /home/kytran/.local/bin/opencode — tmux-attach to the SHARED
#                       session on the 17685 canonical lane. Scrollback is tmux's.
#   opencode-Primary    this repo's launcher — docker exec into
#                       archie_opencode_terminal_gf (17687), the GUARD-FREE lane.
#                       Has its own --check and --live-tree modes.
#
# ⚠️ opencode and opencode-docker edit the SAME checkout with nothing between them.
# /mnt/archie_brain is mounted rw into the lanes, and the host agent has the whole
# filesystem. Two agents writing one tree will fight — the same warning opencode-Primary
# already carries about --solo. Pick one for write work.
#
# Symlinks, not copies: a copy would silently rot the moment the script changes.
# `--rollback` removes only the links this script created (identified by target).
set -euo pipefail

LINK_DIR="${LINK_DIR:-$HOME/.local/bin}"
REPO_SCRIPTS="${REPO_SCRIPTS:-/mnt/archie_brain/scripts}"
LINK_NAME="opencode-Primary"
TARGET="$REPO_SCRIPTS/$LINK_NAME"

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
  step "Removing the link"
  L="$LINK_DIR/$LINK_NAME"
  if [ -L "$L" ]; then
    rm "$L"; say "  removed $L"
  else
    say "  nothing to remove at $L"
  fi
  exit 0
fi

step "Checking"
[ -x "$TARGET" ] || die "$TARGET is missing or not executable"
say "  source : $TARGET ($(stat -c%s "$TARGET") bytes)"

# Is the link dir actually on PATH? Creating a link somewhere unreachable would look
# successful and change nothing, which is the failure mode this script exists to avoid.
case ":$PATH:" in
  *":$LINK_DIR:"*) on_path=yes ;;
  *) on_path=no ;;
esac
say "  link   : $LINK_DIR/$LINK_NAME"
say "  $LINK_DIR on PATH: $on_path"
[ "$on_path" = "no" ] && die "$LINK_DIR is not on PATH — a link there would do nothing"

EXISTING="$LINK_DIR/$LINK_NAME"
if [ -e "$EXISTING" ] || [ -L "$EXISTING" ]; then
  if [ -L "$EXISTING" ] && [ "$(readlink -f "$EXISTING" 2>/dev/null || true)" = "$(readlink -f "$TARGET")" ]; then
    say "  link already correct — nothing to do."
    exit 0
  fi
  say "  WARNING: $EXISTING exists and is not our link."
  say "    current: $(ls -la "$EXISTING")"
  die "refusing to replace it — resolve that first"
fi

step "The three entry points"
for c in opencode opencode-docker "$LINK_NAME"; do
  r="$(command -v "$c" 2>/dev/null || echo '— not on PATH —')"
  say "  $c -> $r"
done

if [ "$APPLY" = "0" ]; then
  say ""
  if [ ! -t 0 ]; then
    say "DRY RUN (not a terminal) — nothing changed. Re-run interactively."
    exit 0
  fi
  say "About to symlink $LINK_NAME into $LINK_DIR so it works as a bare word."
  printf "  type APPLY to continue: "
  read -r c
  [ "$c" = "APPLY" ] || { say "cancelled — nothing changed."; exit 0; }
fi

step "Linking"
mkdir -p "$LINK_DIR"
ln -s "$TARGET" "$LINK_DIR/$LINK_NAME"
say "  $LINK_DIR/$LINK_NAME -> $TARGET"

step "Verifying"
for c in opencode opencode-docker "$LINK_NAME"; do
  r="$(command -v "$c" 2>/dev/null || echo 'MISSING')"
  say "  $c -> $r"
done

cat <<EOF

Three entry points, all bare words now:

    opencode            native host   — real docker, real ssh, whole filesystem
    opencode-docker     17685 lane    — tmux-attach shared session; Ctrl-b [ scrolls
    $LINK_NAME    17687 guard-free — --check and --live-tree available

⚠️  opencode and opencode-docker edit the same checkout with no boundary between them.
    Choose one for write work; use the other to read.
EOF
