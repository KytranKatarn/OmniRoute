#!/usr/bin/env bash
#
# provision_bwrap_userns_apparmor.sh — let bubblewrap (bwrap) create unprivileged user
# namespaces on this host, so the Codex command runner's Linux sandbox can run again.
#
# ── THE FAILURE THIS FIXES ──────────────────────────────────────────────────────────
# On the host (Ubuntu 24.04) every Codex tool call failed with:
#     bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted
# and, on a plain bind:
#     bwrap: setting up uid map: Permission denied
# `unshare -n` failed identically. Because the COMMAND RUNNER could not sandbox a single
# command, `command -v codex-pr`, `git status`, everything looked broken — codex-pr was
# never missing. Measured live 2026-10-18 in a host `codex` session.
#
# ── ROOT CAUSE ──────────────────────────────────────────────────────────────────────
# There are TWO independent causes, and fixing only the first leaves the sandbox
# broken in a way that LOOKS like the first is still unfixed.
#
# (a) Ubuntu 24.04 ships kernel.apparmor_restrict_unprivileged_userns=1. It denies
#     user-namespace creation to UNCONFINED binaries, so bwrap — which needs
#     CLONE_NEWUSER before it can build its sandbox — exits before running
#     anything. Verified on the host:
#         $ sysctl kernel.apparmor_restrict_unprivileged_userns
#         kernel.apparmor_restrict_unprivileged_userns = 1
#         $ cat /proc/sys/user/max_user_namespaces           # 514616  (not the limit)
#         $ cat /proc/sys/kernel/unprivileged_userns_clone   # 1       (not the limit)
#     So the only thing standing in the way was the AppArmor userns restriction.
#
# (b) bwrap must also WRITE A UID_MAP. A multi-id map can only be written by an
#     unprivileged user through the setuid newuidmap/newgidmap helpers, which
#     ship in the `uidmap` package. Without them bwrap fails with:
#         bwrap: setting up uid map: Permission denied
#     — the SAME text as an AppArmor denial, which is why (b) hides behind (a).
#     /etc/subuid and /etc/login.defs may ALREADY grant the range while the
#     helper that can use it is simply not installed. Measured on this host
#     2026-10-20: the profile below was already installed and loaded, the
#     sandbox was still broken, and the missing piece was the 26 KB uidmap
#     package.
#
# ALSO: the Codex CLI ships its own bwrap under codex-resources/. That is a
# DIFFERENT path from /usr/bin/bwrap, so the profile below does NOT cover it.
# The CLI prefers the PATH copy ("Codex could not find bubblewrap on PATH...
# Codex will use the bundled bubblewrap in the meantime"), so keeping
# bubblewrap installed and on PATH is what makes the Codex sandbox work.
#
# ── ⚠️ THE "FIX" THAT GETS REVERTED — DO NOT USE IT ON THE HOST ─────────────────────
#     codex --dangerously-bypass-approvals-and-sandbox
# KB records that as HIGH severity (Agent/Subprocess Permission Bypass); it was applied
# for this exact bwrap error in scripts/agents/run-codex-task.sh and REVERTED before
# merge. It runs codex at full host privilege — on the HOST that is read access to
# ~/.codex/auth.json, ~/.ssh and .env files plus unrestricted outbound network. The
# CONTAINER lane (archie_codex_terminal, cap_drop: ALL, no host fs, no host secrets) may
# bypass because the CONTAINER is the boundary; the host has no such boundary. Restore
# the sandbox — do not remove it.
#
# ── WHAT THIS DOES (and does NOT) ───────────────────────────────────────────────────
# Writes /etc/apparmor.d/bwrap granting `userns` to /usr/bin/bwrap ONLY, then loads it.
# It does NOT change kernel.apparmor_restrict_unprivileged_userns — the host-wide
# restriction stays ON and exactly one binary is exempted. This is the documented Ubuntu
# remedy for bubblewrap.
#
# ── USAGE ───────────────────────────────────────────────────────────────────────────
#   scripts/provision_bwrap_userns_apparmor.sh            # report status (default, read-only)
#   sudo scripts/provision_bwrap_userns_apparmor.sh --apply
#
# Idempotent: safe to re-run; reports "already current" when nothing would change.
# Reversible:  sudo rm /etc/apparmor.d/bwrap && sudo apparmor_parser -R /usr/bin/bwrap
# Persistent:  apparmor.service is enabled and loads /etc/apparmor.d/ at boot, so this
#              survives a reboot without re-running the script.
#
set -euo pipefail

cd "$(dirname "$0")/.."

PROFILE=/etc/apparmor.d/bwrap
BWRAP=/usr/bin/bwrap
SYSCTL=/proc/sys/kernel/apparmor_restrict_unprivileged_userns

APPLY=0
case "${1:-}" in
  --apply) APPLY=1 ;;
  ""|--check|--status) APPLY=0 ;;
  *) echo "usage: $0 [--apply]" >&2; exit 2 ;;
esac

# The single source of truth for the profile. Written verbatim to $PROFILE on --apply,
# and diffed against it to decide whether anything needs to change.
desired_profile() {
  cat <<'PROFILE_EOF'
# Managed by scripts/provision_bwrap_userns_apparmor.sh — do not hand-edit.
#
# Grants ONLY /usr/bin/bwrap the ability to create user namespaces. Ubuntu 24.04's
# kernel.apparmor_restrict_unprivileged_userns=1 otherwise denies it, and bwrap is the
# Linux sandbox the Codex command runner depends on. The host-wide restriction is NOT
# disabled — this exempts exactly one binary. See the script header for the full story.
abi <abi/4.0>,
include <tunables/global>

profile bwrap /usr/bin/bwrap flags=(unconfined) {
  userns,

  include if exists <local/bwrap>
}
PROFILE_EOF
}

bwrap_works() {
  "$BWRAP" --die-with-parent --unshare-user --unshare-pid --unshare-net \
           --ro-bind / / --dev /dev true >/dev/null 2>&1
}

# The SECOND half of the requirement, and the one that is easy to miss.
#
# The AppArmor profile above is NECESSARY but NOT SUFFICIENT. bwrap must also
# write a uid_map, and a multi-id map can only be written by an unprivileged
# user through the setuid newuidmap/newgidmap helpers. Without them:
#
#     $ bwrap --ro-bind / / true
#     bwrap: setting up uid map: Permission denied
#
# …which looks EXACTLY like an AppArmor denial, so it is very easy to
# "fix" the profile, reload it, and still have a broken sandbox. Measured on
# this host 2026-10-20: the profile was already installed and loaded, the
# sandbox was still broken, and the actual missing piece was the `uidmap`
# package (26 KB, providing /usr/bin/newuidmap + newgidmap).
#
# /etc/subuid and /etc/login.defs may ALREADY grant the range (here they did:
# kytran:100000:65536, SUB_UID_MIN=100000, SUB_UID_COUNT=65536) while the
# helper that can use it is simply not installed. So check the HELPER, not
# just the config.
uidmap_helpers_present() {
  [ -x /usr/bin/newuidmap ] && [ -x /usr/bin/newgidmap ]
}

profile_current() {
  [ -f "$PROFILE" ] && diff -q <(desired_profile) "$PROFILE" >/dev/null 2>&1
}

report() {
  local userns
  userns=$(cat "$SYSCTL" 2>/dev/null || echo "(absent)")
  echo "kernel.apparmor_restrict_unprivileged_userns = ${userns}"
  echo "profile file ${PROFILE}: $( [ -f "$PROFILE" ] && echo present || echo absent )"
  if profile_current; then
    echo "profile content: matches desired"
  elif [ -f "$PROFILE" ]; then
    echo "profile content: DIFFERS from desired (a previous hand-written version?)"
  else
    echo "profile content: absent"
  fi
  if uidmap_helpers_present; then
    echo "uidmap helpers:  present (/usr/bin/newuidmap, /usr/bin/newgidmap)"
  else
    echo "uidmap helpers:  MISSING — bwrap cannot write a MULTI-id uid_map."
    echo "                 Install them:  sudo apt-get install -y uidmap"
    echo "                 (the AppArmor profile alone is NOT sufficient)"
    echo "                 NOTE: bwrap's SINGLE-uid mode still works without them, which"
    echo "                 is why a basic bwrap probe can pass while other userns"
    echo "                 users (docker userns-remap, podman, --map-root-user) fail."
  fi
  if command -v "$BWRAP" >/dev/null 2>&1; then
    if bwrap_works; then
      echo "bwrap sandbox:  WORKS"
    else
      echo "bwrap sandbox:  BROKEN"
      if uidmap_helpers_present; then
        echo "                 uidmap helpers are present, so the AppArmor profile is the"
        echo "                 likely cause — check 'sudo aa-status' and the audit log."
      else
        echo "                 the uidmap helpers are missing, so bwrap cannot write the"
        echo "                 uid_map. Install them:  sudo apt-get install -y uidmap"
      fi
    fi
  else
    echo "bwrap sandbox:  bwrap not installed at ${BWRAP}"
  fi
  # The Codex CLI ships its OWN bwrap under codex-resources/. It is a DIFFERENT
  # path from /usr/bin/bwrap, so the profile above does NOT cover it, and the
  # CLI falls back to it when bwrap is not on PATH. The CLI prefers the PATH
  # copy ("Codex could not find bubblewrap on PATH... Codex will use the
  # bundled bubblewrap in the meantime"), so keeping bubblewrap installed and
  # on PATH is what makes the Codex sandbox work. Check that here, because a
  # missing PATH bwrap is a THIRD way to end up with a broken sandbox.
  if command -v bwrap >/dev/null 2>&1; then
    echo "bwrap on PATH:   $(command -v bwrap)  (the Codex CLI prefers this copy)"
  else
    echo "bwrap on PATH:   MISSING — the Codex CLI would fall back to its BUNDLED copy,"
    echo "                 which the profile above does not cover. Install: sudo apt-get install -y bubblewrap"
  fi
}

apply() {
  if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: --apply needs root.  Re-run:  sudo $0 --apply" >&2
    exit 1
  fi

  if ! command -v apparmor_parser >/dev/null 2>&1; then
    echo "ERROR: apparmor_parser not found — is AppArmor installed?" >&2
    exit 1
  fi

  if [ ! -e "$SYSCTL" ]; then
    echo "NOTE: this kernel has no kernel.apparmor_restrict_unprivileged_userns,"
    echo "      so unprivileged user namespaces are not restricted here. Installing the"
    echo "      profile is still harmless and keeps hosts consistent."
  fi

  if profile_current; then
    echo "profile ${PROFILE} already current — no file change."
  else
    if [ -f "$PROFILE" ]; then
      local bak="${PROFILE}.bak-$(date +%Y%m%d-%H%M%S)"
      cp -p "$PROFILE" "$bak"
      echo "backed up existing profile to ${bak}"
    fi
    desired_profile > "$PROFILE"
    chmod 644 "$PROFILE"
    echo "wrote ${PROFILE}"
  fi

  apparmor_parser -r "$PROFILE"
  echo "loaded profile (apparmor_parser -r)"

  # ── the uidmap helpers ────────────────────────────────────────────────────
  # The profile is necessary but NOT sufficient: bwrap must also write a
  # uid_map, and a multi-id map needs the setuid newuidmap/newgidmap helpers.
  # Without them the sandbox fails with the SAME "setting up uid map:
  # Permission denied" text as an AppArmor denial, which is why this was
  # missed for so long. Install them here so one command fixes the whole
  # requirement rather than half of it.
  if ! uidmap_helpers_present; then
    echo
    echo "── installing the uidmap helpers (needed for bwrap's uid map) ──"
    if command -v apt-get >/dev/null 2>&1; then
      apt-get install -y uidmap || true
    fi
    if uidmap_helpers_present; then
      echo "installed /usr/bin/newuidmap + /usr/bin/newgidmap"
    else
      echo "WARNING: uidmap helpers still missing — bwrap will not be able to write"
      echo "         its uid map, and the sandbox will stay broken."
      echo "         Install manually:  sudo apt-get install -y uidmap"
    fi
  else
    echo "uidmap helpers already present"
  fi

  echo
  echo "── verification ──"
  report

  if bwrap_works; then
    echo
    echo "OK: the Codex command runner's sandbox works. A running codex session picks this"
    echo "    up on its next command — no restart needed (AppArmor is consulted per exec)."
  else
    echo
    echo "FAIL: bwrap still cannot create a user namespace here." >&2
    if ! uidmap_helpers_present; then
      echo "      The uidmap helpers are missing — bwrap cannot write the uid_map." >&2
      echo "      Install them:  sudo apt-get install -y uidmap" >&2
    else
      echo "      The helpers are present, so the AppArmor profile is the likely cause." >&2
      echo "      Check 'sudo aa-status' and the audit log." >&2
    fi
    exit 1
  fi
}

if [ "$APPLY" = "1" ]; then
  echo "== applying scoped AppArmor userns profile for bwrap (host-wide restriction untouched) =="
  apply
else
  echo "== provisioning status (read-only; pass --apply to change) =="
  report
  echo
  echo "run 'sudo $0 --apply' to install/refresh the profile."
fi
