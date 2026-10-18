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
# Ubuntu 24.04 ships kernel.apparmor_restrict_unprivileged_userns=1. It denies user-
# namespace creation to UNCONFINED binaries, so bwrap — which needs CLONE_NEWUSER before
# it can build its sandbox — exits before running anything. Verified on the host:
#     $ sysctl kernel.apparmor_restrict_unprivileged_userns
#     kernel.apparmor_restrict_unprivileged_userns = 1
#     $ cat /proc/sys/user/max_user_namespaces           # 514616  (not the limit)
#     $ cat /proc/sys/kernel/unprivileged_userns_clone   # 1       (not the limit)
# So the only thing standing in the way was the AppArmor userns restriction.
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
  if command -v "$BWRAP" >/dev/null 2>&1; then
    if bwrap_works; then
      echo "bwrap sandbox:  WORKS"
    else
      echo "bwrap sandbox:  BROKEN — userns denied by AppArmor"
    fi
  else
    echo "bwrap sandbox:  bwrap not installed at ${BWRAP}"
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
    echo "      Check 'sudo aa-status' and 'journalctl -k | tail'." >&2
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
