#!/usr/bin/env bash
# identity-assertion-gate.sh — PreToolUse hook (Update 2)
# Advisory: warns when identity assertion has not been made this session.
# Does NOT read stdin (avoids false positives from conversation context).
# Hard-block path: future improvement once stdin format is confirmed.

MARKER="/tmp/archie_identity_asserted"

if [ ! -f "$MARKER" ]; then
    cat <<'HOOK_JSON'
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "additionalContext": "⚠️ IDENTITY GATE WARNING: Session identity assertion not yet made this session. If this operation touches users/user_profiles/oauth tables or owner emails (kytranempowerment@gmail.com / admin@KytranEmpowerment.com), run /archie-boot and complete Step 1.5 first. Then run: touch /tmp/archie_identity_asserted"
  }
}
HOOK_JSON
fi

exit 0
