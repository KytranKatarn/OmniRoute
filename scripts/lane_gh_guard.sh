#!/bin/sh
# gh guard for the coder lanes — installed at /usr/local/bin/gh, AHEAD of the real
# binary (/usr/bin/gh) on PATH. Passes everything through EXCEPT the operations that
# would land code on main without the review that is supposed to gate it.
#
# WHY THIS EXISTS
# ---------------
# The owner asked for `gh` in the lanes so they can open PRs. `gh` also ships
# `gh pr merge`, and .claude/skills merge-pr says of exactly that command:
# "Do NOT fall back to `gh pr merge`. That bypasses the gate entirely and leaves no
# record — it is how #2547/#2549/#2550 reached main with no tier state recorded."
#
# That is not a hypothetical here. Measured 2026-09-14 on KytranKatarn/archie-platform:
#
#     branches/main/protection -> required_approving_review_count: 0
#     rulesets                 -> []
#
# main is PR-ONLY but requires ZERO approvals, and there are no rulesets. So GitHub
# will happily merge a PR that F.O.R.G.E. has never seen, or has REQUESTED CHANGES on.
# Today the review gate is enforced only by callers choosing the gated path
# (github_service.merge_pr -> _automerge_governance_ok). Handing a lane raw `gh`
# hands it the bypass.
#
# ⚠️ HONEST ABOUT WHAT THIS IS: a GUARDRAIL, NOT A SECURITY BOUNDARY.
# Since option B these lanes mount /var/run/docker.sock and are root-equivalent on the
# host; the real gh remains at /usr/bin/gh and `git push` needs no gh at all. Anyone
# deliberately routing around this can. It stops the ACCIDENT and the casual reach for
# the convenient command — which is what actually happened in #2547/#2549/#2550 — and
# it makes the intended path discoverable at the moment of the mistake.
#
# THE REAL FIX IS SERVER-SIDE and is an owner decision on the repo settings:
# set required_approving_review_count >= 1 on main. Then no token, in a lane or
# anywhere else, can merge unreviewed work. Until that lands, this wrapper and the
# procedural gate are all there is. Tracked with the lane work; see the PR that
# added this file.
set -eu

REAL_GH="${LANE_REAL_GH:-/usr/bin/gh}"

_refuse() {
    # stderr, so a script capturing stdout still surfaces it
    printf '\n\033[31m[lane gh-guard] REFUSED: %s\033[0m\n' "$1" >&2
    printf '%s\n\n' "$2" >&2
    exit 1
}

# PARSE the arg list; do not glob it.
#
# ⚠️ Globbing a command line looks fine and is wrong, twice over — both forms were
# measured failing on 2026-09-14 before this was rewritten:
#
#   *" api "*            never matches `gh api …`, because "api" sits at position 0
#                        with no space before it. `gh api -X PUT …/merge` sailed
#                        straight through to the real gh.
#   *" pr "*" merge "*   never matches `gh pr merge 123` — the single space between
#                        "pr" and "merge" is CONSUMED by the `" pr "` half, so the
#                        `" merge "` half then needs a second space that is not
#                        there. It matches `gh pr --repo x merge 9` and misses the
#                        obvious form, which is the worst possible split.
#
# So: walk the args, collect the non-flag tokens, and compare them for EQUALITY.
# Equality is what keeps `gh pr comment 5 --body "...merge..."` from being refused;
# the 3-token window keeps a bare `--body merge` out of it too.
_verb=""; _sub=""; _n=0; _endpoint=""
for _a in "$@"; do
    _l=$(printf '%s' "$_a" | tr '[:upper:]' '[:lower:]')
    case "$_l" in -*) continue ;; esac      # flags and their single-dash forms
    _n=$((_n + 1))
    [ "$_n" -eq 1 ] && _verb="$_l"
    # look for the action verb in the first 3 positional tokens only
    if [ "$_n" -le 3 ]; then
        case "$_l" in merge|review|edit) _sub="$_l" ;; esac
    fi
    case "$_l" in */*) _endpoint="$_endpoint $_l" ;; esac   # api paths
done

case "$_verb/$_sub" in
    # --- merging -------------------------------------------------------------
    pr/merge)
        _refuse "gh pr merge" \
"Merging is gated and does not happen from a lane.

Open the PR (this lane's <lane>-pr helper, or 'gh pr create') and let F.O.R.G.E.
review it. A human then merges through the gated path, which checks the stored
verdict, the allowlist and the tier ceiling:

    /merge-pr <number>

That path records the tier state. 'gh pr merge' records nothing and skips the
verdict check entirely."
        ;;

    # --- approving your own work ---------------------------------------------
    pr/review)
        _refuse "gh pr review" \
"A lane does not approve PRs — including its own. Review is F.O.R.G.E.'s job and
the final say is the owner's. Post findings as a normal PR comment instead:

    gh pr comment <number> --body '...'"
        ;;

    # --- weakening the protection that is already too weak -------------------
    repo/edit)
        _refuse "changing branch protection or repo settings" \
"Repo protection settings are the owner's, not a lane's. main already requires
zero approving reviews; it must not get weaker from in here."
        ;;

    # --- the API back door to the same operations ----------------------------
    api/*)
        case "$_endpoint" in
            */merge|*/merge\ *|*/reviews|*/reviews\ *|*protection*|*rulesets*)
                _refuse "gh api against a merge / review / protection endpoint" \
"Same rule as 'gh pr merge' — merging, approving and protection settings are gated.
Use /merge-pr to merge; leave protection to the owner."
                ;;
        esac
        ;;
esac

# Protection endpoints also reachable without the api verb (e.g. `gh repo edit`).
case "$_endpoint" in
    *protection*|*rulesets*)
        _refuse "changing branch protection or repo rulesets" \
"Repo protection settings are the owner's, not a lane's. main already requires zero
approving reviews; it must not get weaker from in here."
        ;;
esac

[ -x "$REAL_GH" ] || {
    printf '[lane gh-guard] real gh not found at %s\n' "$REAL_GH" >&2
    exit 127
}
exec "$REAL_GH" "$@"
