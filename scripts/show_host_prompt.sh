#!/usr/bin/env bash
# show_host_prompt.sh — write the kickoff prompt for a new host-parallel agent.
#
#   ./scripts/show_host_prompt.sh          # WRITES the file (the default)
#   ./scripts/show_host_prompt.sh --print  # print to stdout instead
#
# WHY WRITING IS THE DEFAULT: on this host a trailing flag has been silently dropped
# from a pasted command five times. `--file` as the LAST token of a long one-liner is
# exactly the shape that fails, and it failed loudly-but-uselessly — the prompt printed
# to the terminal instead of the file being written. Nothing on the critical path may
# depend on a trailing token surviving.
#
# WHY THE PROMPT NAMES A `git show` INSTEAD OF A PATH: /mnt/archie_brain is on
# chore/opencode-lane-scope and does NOT contain docs/lanes/. The previous version told
# the next agent to read a path that does not exist on disk. It now tells them the exact
# command that works from any branch.
set -euo pipefail

BRANCH="${BRANCH:-opencode/feat-repair-bay-close-pr}"
DOC_REL="docs/lanes/opencode-host-parallel-HANDOVER.md"
OUT="${OUT:-/mnt/archie_brain/.opencode-host-kickoff.txt}"

MODE=write
case "${1:-}" in --print) MODE=print ;; "") : ;; *) echo "usage: $0 [--print]" >&2; exit 2 ;; esac

PROMPT="You are taking over the \"host-parallel OpenCode\" task on this machine.

READ THIS FIRST, IN FULL, BEFORE RUNNING ANYTHING:

    cd /mnt/archie_brain && git fetch -q origin \\
      && git show origin/${BRANCH}:${DOC_REL} > /tmp/host-handover.md && less /tmp/host-handover.md

NOTE: /mnt/archie_brain is on chore/opencode-lane-scope and does NOT contain that file.
It is on the branch named above. Do not look for it at a path under /mnt/archie_brain.

Short version so you know what you are looking at:
  * The goal was OpenCode running natively ON THE HOST (like Claude-CLI), not inside the
    17687 container. It is installed and 'opencode' works.
  * Three entry points exist: 'opencode' (native host), 'opencode-docker' (the 17685
    tmux wrapper, renamed), './scripts/opencode-Primary' (the 17687 launcher).
  * UNVERIFIED, and where to start: both MCP servers, and the TMPDIR fix for the
    noexec-/tmp OpenTUI error. Section 2 of the handover lists exactly what is unproven.
  * Section 5 is the important one: it lists the shell and verification traps the
    previous agent fell into 17 times. Read it before writing any script.

YOUR FIRST THREE ACTIONS:
  1. Verify MCP actually works. The previous verification was wrong twice; trust only a
     real 'initialize' POST returning 200 with the bearer and 401 without.
  2. Confirm 'opencode --version' still works (a global npm install reported removing 30
     packages from the prefix shared with opencode-ai).
  3. Open the PR for branch ${BRANCH}, and tell the owner first if you think it should
     be split — it carries a feature branch plus 17 commits of lane provisioning.

RULES: never merge or approve your own PR (F.O.R.G.E. reviews, a human merges); never
'git add -A' in /mnt/archie_brain (shared live tree); never print a secret. Do not
re-diagnose anything in section 1 — it is done and verified.

Report what you verified, what you changed, and what you could not prove."

if [ "$MODE" = "print" ]; then
  printf '%s\n' "$PROMPT"
else
  printf '%s\n' "$PROMPT" > "$OUT"
  chmod 600 "$OUT"
  echo "wrote $OUT"
  echo "give the new agent:  read $OUT"
fi
