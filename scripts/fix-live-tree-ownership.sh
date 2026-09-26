#!/usr/bin/env bash
# fix-live-tree-ownership.sh — durable fix for the root-owned-file trap in the
# shared live tree at /mnt/archie_brain.
#
# WHY THIS EXISTS
#   The `archie_platform` container runs as uid 0 (no `user:` key in
#   docker-compose.yml) and bind-mounts tree subdirs :rw, including
#   ./.git -> /mnt/archie_brain/.git. Every file it creates is root:root.
#   The operator (uid 1000: `kytran` on the host, `node` in the opencode lane
#   container) therefore cannot write them. Symptoms seen in practice:
#     - `git checkout -- <path>` -> "unable to unlink old ...: Permission denied"
#     - `git update-index` blocked, skip-worktree needed as a workaround
#     - pre-commit's stash step reverting the working copy and losing staged work
#
# WHY ACLs AND NOT chown
#   `chown -R 1000:1000` fixes today's 41k files and tomorrow's are root again:
#   the platform container recreates the condition on its next write. A
#   *default* ACL is inherited by every file created in that directory, so it
#   holds for new files too. ACLs also do not remove root's access, which
#   matters because platform_v2/Dockerfile notes TTS triggers a runtime pip
#   install — the platform genuinely needs root, so `user: "1000:1000"` on
#   archie_platform is NOT a safe blanket change. ACLs fix the operator's
#   access without touching the container's privileges.
#
#   Both host and lane are uid 1000, so one ACL entry covers both.
#
# SECRETS ARE EXCLUDED
#   The lane is granted no secrets by policy. secrets/ is bind-mounted :ro into
#   the platform container, so it gains nothing from this, and adding an
#   explicit `u:1000` entry there would hand the lane container read access to
#   secret files. It is pruned from every operation below.
#
# USAGE
#   sudo ./fix-live-tree-ownership.sh                  # report only (default)
#   sudo ./fix-live-tree-ownership.sh --apply-acl      # durable fix
#   sudo ./fix-live-tree-ownership.sh --apply-acl --apply-chown
#   sudo ./fix-live-tree-ownership.sh --uid 1000       # target a specific uid
#   sudo ./fix-live-tree-ownership.sh --apply-acl --path host_commands/completed
#   sudo ./fix-live-tree-ownership.sh --apply-acl --path <dir> --quiet
#
# --path scopes every operation to one subdirectory (relative to the tree, or
#   absolute). Use it for scheduled runs: a full-tree re-walk is 227k entries
#   and would include live Postgres internals, which is not something a timer
#   should be doing to a running database. The cron job uses
#   --path host_commands/completed, which is the only directory whose files the
#   platform rewrites to 644 on a steady cadence.
#
# --quiet prints only problems, for cron. Idempotent. Safe to re-run.

set -uo pipefail

REPO=/mnt/archie_brain
# Never granted: policy says the lane gets no secrets.
PRUNE=( -path "$REPO/secrets" -o -path "$REPO/.git/secrets" )

APPLY_ACL=0
APPLY_CHOWN=0
FORCE=0
QUIET=0
TARGET_UID=""
TARGET="$REPO"

while [ $# -gt 0 ]; do
  case "$1" in
    --apply-acl)     APPLY_ACL=1 ;;
    --apply-chown)   APPLY_CHOWN=1 ;;
    --force)         FORCE=1 ;;
    --quiet)         QUIET=1 ;;
    --uid)           TARGET_UID="${2:-}"; shift ;;
    --path)          TARGET="${2:-}"; shift ;;
    -h|--help)       sed -n '2,46p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1 (try --help)" >&2; exit 2 ;;
  esac
  shift
done

# --path is relative to the tree unless it is already absolute.
case "$TARGET" in
  /*) : ;;
  *)  TARGET="$REPO/${TARGET#/}" ;;
esac
# Refuse to operate inside a secrets directory under any spelling.
case "$TARGET/" in
  */secrets/*|*/secrets/) bad_ref="secrets path" ;;
  *) bad_ref="" ;;
esac

HAVE_PY=0; command -v python3 >/dev/null 2>&1 && HAVE_PY=1

say()  { [ "$QUIET" -eq 1 ] || printf '%s\n' "$*"; }
hdr()  { [ "$QUIET" -eq 1 ] || printf '\n== %s ==\n' "$*"; }
warn() { printf 'WARN: %s\n' "$*"; }
bad()  { printf 'BLOCKED: %s\n' "$*"; }

# Empirical writability test, run as the target user.
#
# `test -w` is NOT trustworthy once ACLs are in play: on a root:root 755 dir
# carrying an access ACL, `test -w` reported "not writable" while an actual
# write succeeded — a false negative from the ACL mask. That would make this
# script report a problem that does not exist (or hide one that does).
# Opening a file in append mode requires write permission but writes nothing,
# so it is both authoritative and non-destructive.
  can_write() {
    local f="$1" uid_arg=""
    if [ "$(id -u)" -eq 0 ] && [ "$LANE_UID" != "0" ]; then uid_arg="$LANE_UID"; fi
    if [ "$HAVE_PY" = "1" ]; then
      # The program is fed on STDIN via a quoted heredoc, not via `-c '...'`.
      # It used to be a `-c` string whose continuation lines were indented, and
      # Python rejects that with IndentationError — so the probe failed for EVERY
      # file, `2>/dev/null` hid the traceback, and the job reported "40/40 not
      # writable" on a tree that was actually fine. A stdin heredoc cannot be
      # broken by indentation, which is why it is written this way.
      #   (Found by the --self-test in setup-live-tree-permissions.sh, which
      #    probes a known-writable control first. Do not "simplify" this back to -c.)
      python3 - "$f" "$uid_arg" <<'PYEOF' 2>/dev/null && return 0 || return 1
import os
import sys

path = sys.argv[1]
uid = sys.argv[2]
if uid and os.getuid() == 0:
    try:
        os.setgroups([])
        os.setuid(int(uid))
    except Exception:
        pass
try:
    open(path, "a").close()
except Exception:
    sys.exit(1)
PYEOF
    fi
    # No python3: we cannot drop privileges, and as root `test -w` is useless
    # (root can write anything, so it would under-report as "writable" for
    # every file). Returning 1 here would report every file as broken and mail
    # a false alarm on every cron run. Report "unknown" (2) instead and let
    # the caller skip the probe.
    [ "$(id -u)" -eq 0 ] && [ "$LANE_UID" != "0" ] && return 2
    test -w "$f"
  }

# ── who are we fixing? ───────────────────────────────────────────────────────
if [ -n "$TARGET_UID" ]; then
  LANE_UID="$TARGET_UID"
  LANE_USER=$(getent passwd "$LANE_UID" 2>/dev/null | cut -d: -f1)
  [ -n "$LANE_USER" ] || LANE_USER="uid:$LANE_UID"
elif [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ]; then
  LANE_USER="$SUDO_USER"
  LANE_UID=$(id -u "$LANE_USER" 2>/dev/null)
  [ -n "$LANE_UID" ] || LANE_UID=$(id -u)
else
  # sudo with no SUDO_USER, or not sudo at all: fall back to the owner of the
  # repo, which is the account that actually needs write access.
  LANE_UID=$(stat -c %u "$REPO" 2>/dev/null)
  LANE_USER=$(getent passwd "$LANE_UID" 2>/dev/null | cut -d: -f1)
  [ -n "$LANE_USER" ] || LANE_USER="uid:$LANE_UID"
fi

hdr "Preflight"
[ -d "$TARGET" ] || { bad "no such path: $TARGET"; exit 1; }
if [ "$TARGET" = "$REPO" ]; then
  [ -d "$REPO/.git" ] || { say "not a git repo: $REPO"; exit 1; }
fi
if [ -n "$bad_ref" ]; then bad "refusing to operate on $TARGET ($bad_ref)"; exit 1; fi
if [ "$LANE_UID" = "0" ]; then
  bad "resolved target uid is 0 (root) — refusing; this would grant or chown to root"
  exit 1
fi
say "invoking user : $(id -un) (uid $(id -u))"
say "target user   : $LANE_USER (uid $LANE_UID)"
say "scope         : $TARGET"
if [ "$(id -u)" -ne 0 ]; then
  warn "not root — --apply-* will fail on root-owned files (use sudo)"
fi
if ! command -v setfacl >/dev/null 2>&1; then
  warn "setfacl not found — the ACL fix needs the 'acl' package."
  warn "  Debian/Ubuntu: sudo apt-get install -y acl"
  warn "  Without it, only --apply-chown is available, and that decays:"
  warn "  the next root-created file is root-owned again."
fi

# ── current state ────────────────────────────────────────────────────────────
not_owned=$(find "$TARGET" -xdev \( "${PRUNE[@]}" \) -prune -o ! -uid "$LANE_UID" -print 2>/dev/null | wc -l)
say ""
say "entries not owned by uid $LANE_UID : $not_owned"

hdr "Where they are"
[ "$QUIET" -eq 1 ] || find "$TARGET" -xdev \( "${PRUNE[@]}" \) -prune -o ! -uid "$LANE_UID" -printf '%P\n' 2>/dev/null \
  | cut -d/ -f1 | grep -v '^$' | sort | uniq -c | sort -rn | head -12 | sed 's/^/   /'

# The number that actually matters: of the files the operator does NOT own, how
# many can it write? Before the fix this equals the not_owned count.
hdr "Write probe (the real test)"
probe_files=$(find "$TARGET" -xdev \( "${PRUNE[@]}" \) -prune -o ! -uid "$LANE_UID" -type f -print 2>/dev/null | head -40)
if [ -z "$probe_files" ]; then
  say "no foreign-owned files to probe"
else
  unwritable=0; probed=0
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    [ -e "$f" ] || continue          # broken link, not a permissions problem
    can_write "$f"; rc=$?
    [ "$rc" -eq 2 ] && continue          # probe unavailable, not a failure
    probed=$((probed+1))
    [ "$rc" -eq 0 ] || unwritable=$((unwritable+1))
  done <<< "$probe_files"
  if [ "$probed" -eq 0 ] && [ "$HAVE_PY" != "1" ]; then
    say "  probe SKIPPED: needs python3 to drop privileges and test honestly"
  fi
  say "probed $probed foreign-owned files as $LANE_USER"
  say "NOT writable by $LANE_USER : $unwritable"
  if [ "$unwritable" -gt 0 ] && [ "$QUIET" -eq 0 ]; then
    say "  the ones that fail (a chmod(644) by a root writer rewrites the ACL"
    say "  mask, so these revert on every run; re-applying helps only until"
    say "  the next write):"
    printf '%s\n' "$probe_files" | while IFS= read -r f; do
      [ -n "$f" ] && [ -e "$f" ] && { can_write "$f" || echo "    $f"; }
    done | head -8
  fi
  if [ "$unwritable" -eq 0 ] && [ "$probed" -gt 0 ]; then
    say "VERDICT: access is in place for the sampled files"
  elif [ "$probed" -eq 0 ]; then
    say "VERDICT: NOT DETERMINED — nothing was sampled (see note above)"
  else
    say "VERDICT: $unwritable sampled file(s) not writable — see list above"
  fi
fi

# ── the fix ──────────────────────────────────────────────────────────────────
if [ "$APPLY_ACL" -eq 0 ] && [ "$APPLY_CHOWN" -eq 0 ]; then
  hdr "Result"
  say "CHECK ONLY — nothing modified. Re-run with --apply-acl to fix."
  exit 0
fi

if [ "$(id -u)" -ne 0 ]; then
  bad "must run as root (sudo) to change ownership/ACLs"; exit 1
fi

if [ "$APPLY_CHOWN" -eq 1 ]; then
  hdr "Applying ownership"
  if [ "$FORCE" -eq 0 ] && [ "$not_owned" -gt 500 ]; then
    say "would chown $not_owned entries to $LANE_UID (large). Re-run with --force to confirm."
    exit 0
  fi
  find "$TARGET" -xdev \( "${PRUNE[@]}" \) -prune -o ! -uid "$LANE_UID" -print0 2>/dev/null \
    | xargs -0 -r chown -h "$LANE_UID" 2>/dev/null
  say "chowned foreign-owned entries to uid $LANE_UID"
fi

if [ "$APPLY_ACL" -eq 1 ]; then
  hdr "Applying ACLs"
  if ! command -v setfacl >/dev/null 2>&1; then
    bad "setfacl unavailable — install 'acl' first; chown alone will decay"
    exit 1
  fi
  # Access ACL: grant the operator rw now.
  # Default ACL: every file/dir created here later inherits that grant, which is
  # what makes this durable against the root-running platform container.
  say "granting u:$LANE_UID:rwX and default u:$LANE_UID:rwX under $TARGET (secrets pruned)"
  find "$TARGET" -xdev \( "${PRUNE[@]}" \) -prune -o -print0 2>/dev/null \
    | xargs -0 -r setfacl -m "u:$LANE_UID:rwX" -m "d:u:$LANE_UID:rwX" 2>/dev/null
  say "ACLs applied. New files created by root in this tree are now writable by $LANE_USER."

  hdr "Verifying"
  unwritable=0; probed=0
  probe2=$(find "$TARGET" -xdev \( "${PRUNE[@]}" \) -prune -o ! -uid "$LANE_UID" -type f -print 2>/dev/null | head -40)
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    [ -e "$f" ] || continue
    can_write "$f"; rc=$?
    [ "$rc" -eq 2 ] && continue          # probe unavailable, not a failure
    probed=$((probed+1))
    [ "$rc" -eq 0 ] || unwritable=$((unwritable+1))
  done <<< "$probe2"
  if [ "$probed" -eq 0 ] && [ "$HAVE_PY" != "1" ]; then
    say "probe SKIPPED: needs python3 (not a failure)"
  else
    say "probed $probed; NOT writable: $unwritable"
  fi
  if [ "$unwritable" -eq 0 ] && [ "$probed" -gt 0 ]; then
    say "PASS: operator can write root-created files"
  elif [ "$unwritable" -gt 0 ]; then
    warn "some files still unwritable — check for other mounts"
  fi
fi

hdr "Result"
say "scope         : $TARGET"
say "target user   : $LANE_USER (uid $LANE_UID)"
say "ACL applied   : $APPLY_ACL   (durable — inherited by new files)"
say "chown applied : $APPLY_CHOWN (one-time normalisation)"
