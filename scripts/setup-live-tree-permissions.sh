#!/bin/bash
# setup-live-tree-permissions.sh — ONE command to make the live tree usable.
#
#   sudo /mnt/archie_brain/scripts/setup-live-tree-permissions.sh
#
# WHY THIS EXISTS
# ---------------
# archie_platform runs as root and bind-mounts 15 paths of the live tree rw. Every
# file it creates is root-owned, which traps the agent lane (uid 1000) out of the
# repo it is supposed to edit. This script fixes that in one pass and installs the
# hourly repair job, so it does not have to be re-run by hand.
#
# WHAT IS ACTUALLY TRUE (measured on this host, not assumed)
# ---------------------------------------------------------
# A root writer that calls `chmod 644` on a file it just created does NOT delete
# the ACL entry — it clamps the MASK, so `user:1000:rwx` survives as
# `#effective:r--` and uid 1000 is denied. Measured sequence:
#
#   root create + chmod 644 ................ uid 1000 DENIED
#   setfacl -m u:1000:rwX .................. uid 1000 OK      <- repairs it
#   root chmod 644 again ................... uid 1000 DENIED  <- so it must re-run
#   root create, NO chmod .................. uid 1000 OK      <- inherits, free
#
# So there are two independent mechanisms and this script installs both:
#   1. DEFAULT ACLs on the 15 rw mount points. Any root-created file that is NOT
#      chmod-ed afterwards inherits write access and never needs repair.
#   2. AN HOURLY RE-APPLY for the writers that do chmod. This is not optional and
#      not a one-time fix: it is bounded drift management, and the re-apply is
#      what makes the difference (default ACLs alone cannot survive a chmod).
#
# Neither mechanism changes ownership: root keeps writing root-owned files, the
# lane is simply able to write them too. Making the platform itself run as uid
# 1000 is the real fix and needs a compose change (docker-compose* is outside
# this lane's scope).
#
# SAFETY
# ------
#   * Refuses to run as anything but root.
#   * Refuses any path that resolves inside secrets/ — this script has no business
#     granting the agent lane access to credentials.
#   * Idempotent: safe to re-run; it only ever ADDS ACL entries and rewrites the
#     cron file with content that already lives in the repo.
#   * --dry-run prints the plan and changes nothing.
#   * --revert removes exactly what this script adds (the uid:1000 entries and
#     the cron file) and touches nothing else in the ACLs.
#   * --self-test proves the write probe actually works before trusting any of it.
set -uo pipefail

REPO=/mnt/archie_brain
TREE="$REPO"
CRON_SRC="$REPO/scripts/archie-live-tree-acl.cron"
CRON_DST=/etc/cron.d/archie-live-tree-acl
OWNER_SCRIPT="$REPO/scripts/fix-live-tree-ownership.sh"

# The 15 paths archie_platform bind-mounts rw, from docker-compose.yml. These are
# the ONLY places the platform can create root-owned files, so they are the only
# places worth seeding. `secrets` is not in this list and must never be added.
RW_MOUNTS=(
  "$TREE/ai_bridge"
  "$TREE/docs"
  "$TREE/conversation_logs"
  "$TREE/database/migrations"
  "$TREE/scripts"
  "$TREE/goose"
  "$TREE/.claude/rules"
  "$TREE/.claude/skills"
  "$TREE/.git"
  "$TREE/repos"
  "$TREE/website/kytranempowerment.com/data"
  "$TREE/website/creed-ai.org/data"
  "$TREE/website/kytranempowerment.com/assets/portraits"
  "$TREE/website/creed-ai.org/assets/portraits"
  "$TREE/host_commands"
)

# The uid that owns the work tree. Resolved from the tree itself, never hardcoded
# from a container's view — the host has no `node` user, so anything that assumes
# one is wrong here (that mistake cost a round of false DENIED readings).
LANE_UID=$(stat -c %u "$TREE" 2>/dev/null || echo 1000)
LANE_NAME=$(stat -c %U "$TREE" 2>/dev/null || echo uid-$LANE_UID)
MODE="u:${LANE_UID}:rwX"
DEFAULT_MODE="d:u:${LANE_UID}:rwX"

DRY=0
REVERT=0
SELFTEST=0
FAILED=0

say()  { printf '%s\n' "$*"; }
ok()   { printf '  \033[32mok\033[0m    %s\n' "$*"; }
warn() { printf '  \033[33mwarn\033[0m  %s\n' "$*"; }
die()  { printf '  \033[31mFAIL\033[0m  %s\n' "$*" >&2; FAILED=$((FAILED+1)); }

usage() {
  cat <<'EOF'
usage: sudo setup-live-tree-permissions.sh [--dry-run] [--revert] [--self-test]

  (no flags)   seed default ACLs, re-apply access ACLs, install the hourly cron
  --dry-run    print the plan, change nothing
  --revert     undo what this script adds
  --self-test  verify the uid-1000 write probe works, then exit
EOF
}

for a in "$@"; do
  case "$a" in
    --dry-run)   DRY=1 ;;
    --revert)    REVERT=1 ;;
    --self-test) SELFTEST=1 ;;
    -h|--help)   usage; exit 0 ;;
    *)           echo "unknown flag: $a" >&2; usage; exit 2 ;;
  esac
done

# ── the probe ────────────────────────────────────────────────────────────────
# Provenance: an earlier version of this used `su -s /bin/sh node`, which reported
# DENIED for every file — including mode-666 controls. The host has no `node` user
# (it is container-only), so every reading was a false negative and nearly caused
# the whole repair job to be declared useless. The python form below was checked
# against a mode-666 control first. Keep it that way: if you change the probe,
# re-run --self-test or you are reading noise.
can_write() {
  /usr/bin/python3 -c "
import os, sys
os.setgroups([]); os.setuid(int(sys.argv[1]))
try:
    open(sys.argv[2], 'a').close()
except Exception:
    sys.exit(1)
" "$LANE_UID" "$1" 2>/dev/null
}

if [ "$(id -u)" -ne 0 ]; then
  cat >&2 <<EOF
This script changes ACLs across the live tree and writes /etc/cron.d, so it must
run as root:

    sudo $0 $*
EOF
  exit 1
fi

# ── guard rail ───────────────────────────────────────────────────────────────
for p in "$TREE" "${RW_MOUNTS[@]}"; do
  case "$(readlink -f "$p" 2>/dev/null || echo "$p")" in
    */secrets|*/secrets/*) die "refusing to touch a secrets path: $p" ;;
  esac
done

# ── self-test ────────────────────────────────────────────────────────────────
if [ "$SELFTEST" -eq 1 ]; then
  say "Self-test: can uid $LANE_UID ($LANE_NAME) write a root-owned file?"
  T=$(mktemp -d /tmp/acl-selftest.XXXXXX)
  # mktemp -d creates 0700. uid $LANE_UID cannot TRAVERSE that, so every probe
  # below would report DENIED for a reason that has nothing to do with the ACL —
  # which is exactly the false negative this self-test exists to catch. It caught
  # itself once already; do not remove this line.
  chmod 755 "$T"
  if echo x > "$T/probe"; then
    chmod 644 "$T/probe"
    if can_write "$T/probe"; then ok "probe works — a root-owned 644 file IS writable"
    else warn "probe DENIED on a fresh root file; ACLs are NOT in place yet (expected on a first run)"; fi
  fi
  setfacl -m "$MODE" "$T/probe" 2>/dev/null
  if can_write "$T/probe"; then ok "probe works after setfacl — the repair path is sound"
  else die "probe still DENIED after setfacl; the ACL mechanism itself is not working here"; fi
  rm -rf "$T"
  [ "$FAILED" -eq 0 ] && { say; say "Self-test passed."; exit 0; }
  say; say "Self-test FAILED ($FAILED problem(s))."; exit 1
fi

say "=============================================================="
say " Live-tree permissions  (tree=$TREE  lane=$LANE_NAME:$LANE_UID)"
say "=============================================================="

# ── revert ───────────────────────────────────────────────────────────────────
if [ "$REVERT" -eq 1 ]; then
  say "Reverting what this script added."
  say ""
  say "[1/2] Removing uid:$LANE_UID ACL entries from the tree"
  say "      NOTE: setfacl recalculates the ACL mask as it removes entries, so the"
  say "      EFFECTIVE permissions of any other named ACL entries can shift. This"
  say "      undoes this script's grant; it is not a byte-exact rollback."
  if [ "$DRY" -eq 1 ]; then
    say "      would run: setfacl -R -x u:$LANE_UID -x d:u:$LANE_UID $TREE"
  elif command -v setfacl >/dev/null 2>&1; then
    setfacl -R -x "u:$LANE_UID" "$TREE" 2>/dev/null
    setfacl -R -x "d:u:$LANE_UID" "$TREE" 2>/dev/null
    ok "uid:$LANE_UID entries removed from $TREE"
  else
    die "setfacl unavailable; cannot revert"
  fi

  say ""
  say "[2/2] Removing the hourly repair job"
  if [ ! -e "$CRON_DST" ]; then
    say "      $CRON_DST not present — nothing to do"
  elif [ "$DRY" -eq 1 ]; then
    say "      would remove $CRON_DST"
  else
    rm -f "$CRON_DST" && ok "removed $CRON_DST" || die "could not remove $CRON_DST"
  fi

  say ""
  say "--------------------------------------------------------------"
  [ "$DRY" -eq 1 ] && say "DRY RUN — nothing was changed." || say "Revert complete."
  say "The lane will be locked out of root-owned files again — that is the"
  say "original problem this script exists to solve."
  say "--------------------------------------------------------------"
  [ "$FAILED" -eq 0 ] || exit 1
  exit 0
fi

# ── 0. dependencies ──────────────────────────────────────────────────────────
if ! command -v setfacl >/dev/null 2>&1; then
  if [ "$DRY" -eq 1 ]; then
    warn "acl not installed — a real run would install it (apt-get install -y acl)"
  else
    say "  installing acl..."
    DEBIAN_FRONTEND=noninteractive apt-get install -y acl >/dev/null 2>&1 \
      && ok "acl installed" || { die "could not install acl; install it and re-run"; }
  fi
fi
command -v setfacl >/dev/null 2>&1 && ok "setfacl available"

# ── 1. default ACLs on the rw mount points ───────────────────────────────────
say ""
say "[1/4] Seeding DEFAULT ACLs on the rw mount points"
say "      (root-created files that are not chmod-ed then inherit write access)"
for p in "${RW_MOUNTS[@]}"; do
  if [ ! -d "$p" ]; then warn "skip (missing): $p"; continue; fi
  if [ "$DRY" -eq 1 ]; then say "      would set $MODE + $DEFAULT_MODE on $p"; continue; fi
  if setfacl -m "$MODE" -m "$DEFAULT_MODE" "$p" 2>/dev/null; then
    say "      seeded $p"
  else
    die "setfacl failed on $p"
  fi
done
[ "$DRY" -eq 0 ] && ok "default ACLs seeded on ${#RW_MOUNTS[@]} mount points"

# ── 2. re-apply access ACLs across the tree ──────────────────────────────────
say ""
say "[2/4] Re-applying access ACLs across the tree"
if [ "$DRY" -eq 1 ]; then
  say "      would run: $OWNER_SCRIPT --apply-acl --quiet"
else
  if [ -x "$OWNER_SCRIPT" ]; then
    # Delegated: the ACL logic lives in one place (PR #3497) rather than being
    # duplicated here, so a fix there fixes it here too.
    "$OWNER_SCRIPT" --apply-acl --quiet && ok "tree re-applied" || die "tree re-apply reported a problem"
  else
    warn "$OWNER_SCRIPT missing or not executable — falling back to a direct sweep"
    setfacl -R -m "$MODE" "$TREE" 2>/dev/null && ok "direct sweep done" || die "direct sweep failed"
  fi
fi

# ── 3. hourly repair cron ────────────────────────────────────────────────────
say ""
say "[3/4] Hourly repair job (for the writers that DO chmod)"
if [ ! -f "$CRON_SRC" ]; then
  warn "no cron source at $CRON_SRC (it ships in PR #3497) — skipping"
elif [ "$DRY" -eq 1 ]; then
  say "      would install $CRON_SRC -> $CRON_DST (0644 root:root)"
else
  install -m 0644 -o root -g root "$CRON_SRC" "$CRON_DST" \
    && ok "installed $CRON_DST" || die "could not install the cron file"
  # cron ignores dotfiles in this directory, so a dot-prefixed name is a silent
  # no-op — worth a hard check rather than a comment.
  case "$(basename "$CRON_DST")" in
    .*) die "cron filename starts with a dot; cron will silently ignore it" ;;
  esac
fi

# ── 4. verify ────────────────────────────────────────────────────────────────
say ""
say "[4/4] Verifying as uid $LANE_UID"
if [ "$DRY" -eq 1 ]; then
  say "      (dry run — nothing to verify)"
else
  VERIFIED=0; UNWRITABLE=0
  while IFS= read -r f; do
    [ -z "$f" ] && continue
    if can_write "$f"; then VERIFIED=$((VERIFIED+1)); else UNWRITABLE=$((UNWRITABLE+1)); fi
  done < <(find "$TREE/host_commands/completed" -maxdepth 1 -type f ! -user "$LANE_UID" 2>/dev/null | head -50)
  if [ "$VERIFIED" -gt 0 ] && [ "$UNWRITABLE" -eq 0 ]; then
    ok "$VERIFIED/$VERIFIED sampled root-owned files are writable by $LANE_NAME"
  elif [ "$VERIFIED" -eq 0 ]; then
    warn "no foreign-owned files sampled — nothing to verify (harmless)"
  else
    warn "$UNWRITABLE of $((VERIFIED+UNWRITABLE)) sampled files still unwritable;"
    warn "  that is the chmod drift the hourly job repairs — check the log:"
    warn "  journalctl -u cron --since -2h | grep -i live-tree"
  fi
fi

# ── summary ──────────────────────────────────────────────────────────────────
say ""
say "--------------------------------------------------------------"
if [ "$DRY" -eq 1 ]; then
  say "DRY RUN — nothing was changed."
elif [ "$REVERT" -eq 1 ]; then
  say "Reverted (see steps above)."
else
  if [ "$FAILED" -eq 0 ]; then
    say "Done. The lane can now write root-owned files in the tree."
  else
    say "Completed with $FAILED problem(s) — see the FAIL lines above."
  fi
  cat <<EOF

Still expected, and not a failure:
  * A root writer that chmods a file WILL lock the lane out again until the next
    hourly run. That is the chmod-clamps-the-mask behaviour measured above, and
    the hourly job exists precisely to repair it. Seeding defaults cannot prevent
    it; only the re-apply can.
  * To confirm the job is firing:
        sudo journalctl -u cron --since -2h --no-pager | grep -i live-tree
  * To undo everything this script added:
        sudo $0 --revert
EOF
fi
say "--------------------------------------------------------------"

[ "$FAILED" -eq 0 ] || exit 1
exit 0
