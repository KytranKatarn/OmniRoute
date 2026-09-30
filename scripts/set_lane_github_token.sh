#!/usr/bin/env bash
# Wire a GitHub token into a coder lane (codex | opencode) and PROVE it works.
#
# WHY A SCRIPT: the token has to land in a docker secret file, the lane has to be
# recreated to pick it up (a `restart` re-reads nothing), and the only honest test
# is an authenticated call to GitHub — not "the file is there". Doing that by hand
# is where the 2026-08-10 token quietly expired unnoticed for five weeks.
#
#   scripts/set_lane_github_token.sh codex
#   scripts/set_lane_github_token.sh opencode
#
# The token is READ FROM A PROMPT, never passed as an argument — an argv token
# lands in shell history and in `ps` output for every user on the box.
#
# WHAT TOKEN TO CREATE (GitHub → Settings → Developer settings →
#   Personal access tokens → Fine-grained tokens → Generate new token):
#   • Resource owner:  KytranKatarn
#   • Repository access: ONLY select repositories → KytranKatarn/archie-platform
#   • Permissions:  Contents: Read and write      (push a branch)
#                   Pull requests: Read and write (open a PR)
#     Nothing else. Do NOT grant Administration.
#   • Expiration: your call. The last one lapsed at ~5 weeks with no warning and
#     nothing noticed until a push failed, so put a reminder wherever you keep them.
#
# ⚠️ "Pull requests: write" also permits MERGING — GitHub does not split those.
# The lane is stopped from merging by /usr/local/bin/gh (the guard) and by the
# pre-push scope guard, but both are GUARDRAILS, not boundaries: since option B
# these lanes mount the docker socket and are root-equivalent on the host, so a
# determined process inside one can reach any credential on the box anyway. The
# real reason to give each lane its OWN token is ATTRIBUTION and INDEPENDENT
# REVOCATION, not isolation. Do not mistake it for a sandbox.
set -euo pipefail

LANE="${1:-}"
case "$LANE" in
  codex)    SECRET_FILE="secrets/codex/github_token.txt";    CONTAINER="archie_codex_terminal";    COMPOSE_SVC="archie_codex_terminal" ;;
  opencode) SECRET_FILE="secrets/opencode/github_token.txt"; CONTAINER="archie_opencode_terminal"; COMPOSE_SVC="archie_opencode_terminal" ;;
  *) echo "usage: $0 <codex|opencode>" >&2; exit 2 ;;
esac

cd "$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"

echo "Lane:   $LANE"
echo "Secret: $SECRET_FILE"
echo
printf 'Paste the fine-grained PAT (input hidden), then Enter: '
read -rs TOKEN
echo
[ -n "$TOKEN" ] || { echo "empty token — aborted, nothing written" >&2; exit 1; }

case "$TOKEN" in
  github_pat_*|ghp_*) : ;;
  *) echo "that does not look like a GitHub PAT (expected github_pat_… or ghp_…) — aborted" >&2; exit 1 ;;
esac

# VERIFY BEFORE WRITING. A dead token written to disk is exactly the state this
# script exists to end; better to refuse than to store something that 401s.
echo "→ checking the token against GitHub before writing it anywhere…"
CHECK=$(TOKEN="$TOKEN" python3 - <<'PY'
import os, json, urllib.request, urllib.error
t = os.environ["TOKEN"]
H = {"Authorization": "Bearer " + t, "Accept": "application/vnd.github+json", "User-Agent": "lane-token-setup"}
try:
    u = json.load(urllib.request.urlopen(urllib.request.Request("https://api.github.com/user", headers=H), timeout=20))
except urllib.error.HTTPError as e:
    print("FAIL|token rejected by GitHub: HTTP %s" % e.code); raise SystemExit
try:
    r = json.load(urllib.request.urlopen(urllib.request.Request(
        "https://api.github.com/repos/KytranKatarn/archie-platform", headers=H), timeout=20))
    p = r.get("permissions") or {}
except urllib.error.HTTPError as e:
    print("FAIL|authenticates as %s but CANNOT see archie-platform (HTTP %s) — check the repository-access list"
          % (u.get("login"), e.code)); raise SystemExit
if not p.get("push"):
    print("FAIL|authenticates as %s but has NO push on archie-platform — add Contents: read and write"
          % u.get("login")); raise SystemExit

# Pull-request access is checked SEPARATELY and explicitly, because the header above
# promises it and `permissions.push` does not cover it. 2026-09-30: a token carrying
# Contents-only passed this check, was written, and left the lane unable to open a PR
# (GET /pulls 403, POST /pulls 403) while opencode-pr sat installed and both lane
# skills insisted it worked. The lane looks healthy and cannot ship.
try:
    urllib.request.urlopen(urllib.request.Request(
        "https://api.github.com/repos/KytranKatarn/archie-platform/pulls?state=open&per_page=1",
        headers=H), timeout=20)
    pr = "ok"
except urllib.error.HTTPError as e:
    pr = "no (HTTP %s)" % e.code
except Exception as e:
    pr = "unknown (%s)" % type(e).__name__

if pr != "ok":
    # Warnings go to STDERR so they reach the terminal without polluting $CHECK,
    # which the caller parses as "<STATUS>|<detail>". stdout still ends in OK, so a
    # push-only token is installed (it is still useful) rather than blocking setup.
    eprint = lambda m: print(m, file=sys.stderr)
    eprint("! authenticates as %s and can push, but CANNOT READ pull requests: %s."
           % (u.get("login"), pr))
    eprint("!  The lane will push branches fine but CANNOT open a PR — opencode-pr and")
    eprint("!  mk-pr.sh will both fail with a 403 that reads like a broken script.")
    eprint("!  Add 'Pull requests: Read and write' to the token and re-run for parity.")
else:
    print("OK|%s|push=%s pr=readable admin=%s" % (u.get("login"), p.get("push"), p.get("admin")))
PY
)
if [ "${CHECK%%|*}" != "OK" ]; then
  echo "✗ ${CHECK#*|}" >&2
  echo "  NOTHING was written. Fix the token and re-run." >&2
  exit 1
fi
echo "✓ ${CHECK#*|}"

mkdir -p "$(dirname "$SECRET_FILE")"
if [ -f "$SECRET_FILE" ]; then
  BK="$SECRET_FILE.bak-$(date +%Y%m%d-%H%M%S)"
  cp -a "$SECRET_FILE" "$BK"; echo "→ previous token backed up to $BK"
fi
# printf, not echo: a trailing newline in the file becomes part of the credential
# for anything that does not .strip() it. The codex credential-helper cats it raw.
printf '%s' "$TOKEN" > "$SECRET_FILE"
chmod 600 "$SECRET_FILE"
echo "→ wrote $SECRET_FILE (mode 600, no trailing newline)"

echo "→ recreating $COMPOSE_SVC so it picks the secret up (restart would NOT)…"
docker compose up -d --no-deps --force-recreate "$COMPOSE_SVC" >/dev/null
sleep 4

echo "→ proving it from INSIDE the lane (this is the only test that counts):"
if docker exec "$CONTAINER" git ls-remote https://github.com/KytranKatarn/archie-platform -h refs/heads/main >/dev/null 2>&1; then
  echo "  ✓ $LANE can authenticate to GitHub and read refs"
else
  echo "  ✗ the lane still cannot authenticate — check its credential.helper:"
  docker exec "$CONTAINER" git config --global --get credential.helper || true
  exit 1
fi
echo
echo "Done. $LANE can now push a ${LANE}/* branch and open a PR via '${LANE}-pr \"title\"'."
echo "It still cannot merge: the gh guard refuses 'pr merge', and main is PR-only."
