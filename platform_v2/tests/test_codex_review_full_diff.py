"""Drive the real shell reviewer with offline substitutes; never invoke Codex/GitHub."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/codex_pr_review.sh"


class FullDiffTests(unittest.TestCase):
    def run_reviewer(
        self,
        *,
        cap=None,
        model_rc=0,
        fail_diff=False,
        fail_worktree=False,
        moved_head=False,
        post=False,
        fail_post=False
    ):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            diff = root / "diff.txt"
            # Exceeds both the old 60K cap and the per-argument OS limit.
            text = "diff --git a/one b/one\n" + "+changed line\n" * 17000 + "END_FULL_DIFF\n"
            diff.write_text(text)
            capture = root / "stdin.txt"
            gh = root / "gh"
            gh.write_text(
                """#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
if '--method' in sys.argv and 'POST' in sys.argv:
    Path(os.environ['TEST_POST_CAPTURE']).write_text(sys.stdin.read())
    sys.exit(int(os.environ['TEST_FAIL_POST']))
elif 'application/vnd.github.diff' in ' '.join(sys.argv):
    if os.environ.get('TEST_FAIL_DIFF') == '1': sys.exit(1)
    print(Path(os.environ['TEST_DIFF']).read_text(),end='')
elif '.head.sha' in sys.argv:
    print('b'*40 if os.environ.get('TEST_MOVED_HEAD') == '1' else 'a'*40)
elif '--jq' in sys.argv:
    print(json.dumps(dict(title='test',author='test',state='open',head='feature',sha='a'*40,base='main',files=2,additions=17000,deletions=0)))
else: sys.exit(1)
"""
            )
            codex = root / "codex"
            codex.write_text(
                """#!/usr/bin/env python3
import os,sys
from pathlib import Path
assert sys.argv[-1] == '-'
Path(os.environ['TEST_CAPTURE']).write_text(sys.stdin.read())
print('VERDICT: COMMENT')
print('offline stub; no external model was used')
sys.exit(int(os.environ['TEST_MODEL_RC']))
"""
            )
            (root / "docker").write_text("#!/bin/sh\nexit 1\n")
            (root / "git").write_text(
                """#!/usr/bin/env python3
import os,sys
from pathlib import Path
args=sys.argv[1:]
if 'fetch' in args and os.environ.get('TEST_FAIL_WORKTREE') == '1': sys.exit(1)
if 'rev-parse' in args:
    print(args[1] if '--show-toplevel' in args else 'a'*40)
elif 'worktree' in args and 'add' in args:
    Path(args[-2], '.git').write_text('offline worktree fixture')
"""
            )
            for name in ["gh", "codex", "git", "docker"]:
                (root / name).chmod(0o755)
            env = os.environ.copy()
            env.update(
                PATH=str(root) + os.pathsep + env["PATH"],
                CODEX_REVIEW_TOKEN="offline-read",
                CODEX_REVIEW_WRITE_TOKEN="offline-write",
                TEST_DIFF=str(diff),
                TEST_CAPTURE=str(capture),
                TEST_POST_CAPTURE=str(root / "posted.json"),
                TEST_FAIL_POST=str(int(fail_post)),
                CODEX_REVIEW_REPO_DIR=str(root),
                CODEX_REVIEW_WORKTREE_ROOT=str(root),
                TEST_FAIL_WORKTREE=str(int(fail_worktree)),
                TEST_MOVED_HEAD=str(int(moved_head)),
                TEST_MODEL_RC=str(model_rc),
                TEST_FAIL_DIFF=str(int(fail_diff)),
            )
            env.pop("MAX_DIFF_CHARS", None)
            if cap is not None:
                env["MAX_DIFF_CHARS"] = str(cap)
            result = subprocess.run(
                ["bash", str(SCRIPT), "3986"] + (["--post"] if post else []),
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
            )
            prompt = capture.read_text() if capture.exists() else None
            posted = root / "posted.json"
            self.posted = json.loads(posted.read_text()) if posted.exists() else None
            return result, prompt, text

    def test_post_is_comment_pinned_to_reviewed_commit(self):
        result, _, _ = self.run_reviewer(post=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.posted["event"], "COMMENT")
        self.assertEqual(self.posted["commit_id"], "a" * 40)
        self.assertTrue(self.posted["body"].startswith("VERDICT: COMMENT"))

    def test_failed_post_does_not_report_success(self):
        result, _, _ = self.run_reviewer(post=True, fail_post=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("posted: https://", result.stdout)

    def test_full_large_diff_reaches_reviewer_over_stdin(self):
        result, prompt, diff = self.run_reviewer()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(diff, prompt)
        self.assertIn("END_FULL_DIFF", prompt)
        self.assertNotIn("TRUNCATED", result.stdout)

    def test_explicit_limit_refuses_instead_of_reviewing_prefix(self):
        result, prompt, _ = self.run_reviewer(cap=60000)
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(prompt)
        self.assertIn("Nothing reviewed or posted", result.stderr)

    def test_missing_diff_is_not_a_completed_review(self):
        result, prompt, _ = self.run_reviewer(fail_diff=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(prompt)

    def test_head_change_during_diff_fetch_is_not_reviewed(self):
        result, prompt, _ = self.run_reviewer(moved_head=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(prompt)
        self.assertIn("PR head changed", result.stderr)

    def test_failed_worktree_is_not_reviewed(self):
        result, prompt, _ = self.run_reviewer(fail_worktree=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(prompt)
        self.assertIn("could not create disposable worktree", result.stderr)

    def test_failed_model_with_verdict_text_is_not_reported_as_completed(self):
        result, prompt, _ = self.run_reviewer(model_rc=124)
        self.assertEqual(result.returncode, 124)
        self.assertIsNotNone(prompt)
        self.assertNotIn("CODEX REVIEW =", result.stdout)
        self.assertIn("No completed review", result.stderr)


if __name__ == "__main__":
    unittest.main()
