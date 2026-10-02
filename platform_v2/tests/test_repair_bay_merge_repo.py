"""The Merge button must send the PR's repo, or it can merge a DIFFERENT PR.

`/forge/prs/<n>/merge` and `/forge/pr-reviews/<n>/merge` resolve the review row by
`(pr_number, repo)`. When `repo` is absent from the POST body both fall back to
archie-platform. PR numbers are NOT unique across the repos F.O.R.G.E. reviews:

    repos_for_pr_number(61) == ['KytranKatarn/archie-code',
                                'KytranKatarn/archie-platform',
                                'KytranKatarn/kytran-business-suite']

Measured 2026-10-02: merging KBS PR #61 (healthchecks for kbs-postgres /
kbs-redis) from Repair Bay answered

    Merge failed: HTTP 404 - {"message":"Not Found", ... "pulls#merge-a-pull-request"}

because the request named no repo, so the lookup resolved archie-platform #61 —
"fix(forge_stats): agent_loop_cycles -> autonomy_loop_log schema rename", MERGED
2026-04-11. GitHub 404s on an already-merged PR, so the click was harmless BY
LUCK. Both merge routes already document the worse case in their own comments:

    "had a same-numbered archie-platform PR carried an approval, the override
     would have merged THAT one."

That is a wrong-PR merge, not a failed one. This test pins the client half.
"""

from __future__ import annotations

import re
from pathlib import Path

JS = Path(__file__).resolve().parents[1] / "static" / "js" / "repair-bay-main.js"


class TestMergeRequestCarriesRepo:
    def test_merge_request_body_includes_repo(self):
        """Scope to the MERGE call. A bare search over every JSON.stringify would
        match the send-back request at line ~775, which already carries repo, and
        pass even while the merge body is repo-less — which is exactly what the
        canary showed."""
        src = JS.read_text()
        block = re.search(r"function _doMergePr\([^)]*\)\s*\{(.*?)\n\}", src, re.S)
        assert block, "_doMergePr body not found"
        body = re.search(r"body:\s*JSON\.stringify\((\{[^}]*\})\)", block.group(1))
        assert body, "could not find the merge request body"
        assert "repo" in body.group(1), f"merge body omits repo: {body.group(1)}"

    def test_do_merge_pr_accepts_a_repo_parameter(self):
        src = JS.read_text()
        sig = re.search(r"function _doMergePr\(([^)]*)\)", src)
        assert sig, "_doMergePr not found"
        assert "repo" in sig.group(1), f"_doMergePr takes no repo: {sig.group(1)}"

    def test_merge_pr_accepts_a_repo_parameter(self):
        src = JS.read_text()
        sig = re.search(r"function _mergePr\(([^)]*)\)", src)
        assert sig, "_mergePr not found"
        assert "repo" in sig.group(1), f"_mergePr takes no repo: {sig.group(1)}"

    def test_button_passes_its_own_row_repo(self):
        """Not just threaded — threaded from the ROW, or it is still the wrong repo."""
        src = JS.read_text()
        call = re.search(r"onclick:\s*function\(\)\s*\{\s*_mergePr\(([^)]*)\)", src)
        assert call, "merge button click not found"
        assert "pr.repo" in call.group(1), f"button does not pass pr.repo: {call.group(1)}"

    def test_coverage_retry_preserves_repo(self):
        """The 422 -> coverage-ack retry is a SECOND request; it must not drop repo."""
        src = JS.read_text()
        retry = re.search(r"_doMergePr\(([^)]*true[^)]*)\)", src)
        assert retry, "coverage retry call not found"
        assert "repo" in retry.group(1), f"retry drops repo: {retry.group(1)}"


class TestConfirmDialogNamesTheRepo:
    def test_dialog_shows_which_repo_is_being_merged(self):
        """A bare '#61' is ambiguous across three repos — the operator must see it."""
        src = JS.read_text()
        block = re.search(r"function _mergePr\([^)]*\)\s*\{(.*?)\n\}", src, re.S)
        assert block, "_mergePr body not found"
        body = block.group(1)
        assert "where" in body and "message:" in body, "confirm does not name the repo"
