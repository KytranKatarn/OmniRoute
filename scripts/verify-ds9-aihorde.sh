#!/usr/bin/env bash
# Prove the aihorde path works in the RUNNING gateway (#7424).
#
# This is the acceptance test for "the free tier has a second transport that is
# not the browser". It runs against the LIVE gateway over HTTP — not against
# the source tree — because the thing being tested is the BUILT artifact.
#
# Usage: scripts/verify-ds9-aihorde.sh
#
# What it checks:
#   1. the gateway is healthy and its health endpoint answers
#   2. the aihorde executor is present in the BUILT artifact
#   3. a plain chat through the aihorde provider returns a real completion
#   4. a TOOL-bearing chat through aihorde comes back as a real tool_call —
#      which is the whole point: AI Horde has no native function calling, so
#      this only works if BOTH the prompt contract and the named-block
#      dialect normalizer are live in the built gateway
#
# It prints the evidence and exits non-zero if any check fails. It does NOT
# modify anything.

set -uo pipefail

DS9="${DS9_BASE_URL:-http://127.0.0.1:20129}"
ROOT="/mnt/standalone/deep-space-9"
KEY="${OMNIROUTE_API_KEY:-}"

fail=0
ok()   { echo "    PASS  $1"; }
bad()  { echo "    FAIL  $1"; fail=1; }

echo "==> 1. the gateway is up"
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$DS9/api/health" || echo 000)
if [ "$code" = "200" ]; then ok "GET /api/health -> 200"; else bad "GET /api/health -> $code"; fi

echo "==> 2. the artifact mentions aihorde"
# A WEAK, smoke-level signal only: the aihorde base URL was already in the
# gateway's provider catalogue before the aihorde executor existed, so this
# cannot prove the executor is in the build. The authoritative check is #4 --
# only a built gateway with the executor can answer a tool-bearing request
# through aihorde.
if grep -rq "oai.aihorde.net" "$ROOT/.build/next/standalone" 2>/dev/null; then
  ok "the artifact mentions aihorde (smoke signal; check 4 is the real one)"
else
  bad "the artifact does NOT mention aihorde at all"
fi

if [ -z "$KEY" ]; then
  echo "    SKIP  the chat checks: OMNIROUTE_API_KEY is not set"
  exit $fail
fi

# The prefix is the PROVIDER ID ("aihorde"), not the alias ("horde"). The
# gateway serves aihorde/<model-id>; asking for horde/<model-id> resolves no
# provider and the model string is used as the target URL, which fails with a
# misleading upstream error.
MODEL="aihorde/google/gemma-4-31b"

echo "==> 3. a plain chat through aihorde"
body=$(curl -s --max-time 180 -X POST "$DS9/v1/chat/completions" \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with exactly: ALOVE\"}],\"max_tokens\":40}")
if printf '%s' "$body" | grep -q '"choices"'; then
  ok "the gateway returned a completion"
  printf '%s' "$body" | head -c 220 | sed 's/^/      /'; echo
else
  bad "no completion: $(printf '%s' "$body" | head -c 220)"
fi

echo "==> 4. a TOOL-bearing chat through aihorde comes back as a tool_call"
body=$(curl -s --max-time 240 -X POST "$DS9/v1/chat/completions" \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"What is the weather in Toronto? Use the tool.\"}],\"max_tokens\":400,\"tools\":[{\"type\":\"function\",\"function\":{\"name\":\"get_weather\",\"description\":\"Get the weather for a city\",\"parameters\":{\"type\":\"object\",\"properties\":{\"city\":{\"type\":\"string\"}},\"required\":[\"city\"]}}}]}")
if printf '%s' "$body" | grep -q '"tool_calls"'; then
  ok "the reply carries a tool_call — the prompt contract AND the dialect normalizer are both live"
  printf '%s' "$body" | head -c 320 | sed 's/^/      /'; echo
else
  bad "no tool_call in the reply: $(printf '%s' "$body" | head -c 260)"
fi

echo
[ "$fail" = "0" ] && echo "==> ALL CHECKS PASSED" || echo "==> SOME CHECKS FAILED"
exit $fail
