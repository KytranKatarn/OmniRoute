"""changed_files_since must classify what SHIPS — git bookkeeping is not a change.

Approval #13856 (2026-08-29): the website_content_autocommit job committed generated
site content, which touched .git/ mtimes; the nightly deploy worker swept those into
changed_files, classify_risk saw suffix-less .git object files, and the owner was
paged with an approval whose reason was a raw dump of .git paths — for a site whose
deployable content was byte-identical (the deploy zip has always excluded .git/*).
"""

import os
import time

from services.deploy_service import changed_files_since

_SINCE = "2020-01-01T00:00:00+00:00"  # everything below is newer than this


def _touch(root, rel):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x")
    now = time.time()
    os.utime(p, (now, now))
    return p


class TestGitNoiseFilter:
    def test_git_internals_and_gitignore_are_never_changes(self, tmp_path):
        _touch(tmp_path, ".git/COMMIT_EDITMSG")
        _touch(tmp_path, ".git/objects/05/abc123")
        _touch(tmp_path, ".gitignore")
        assert changed_files_since(str(tmp_path), _SINCE) == []

    def test_real_content_still_detected_beside_git_noise(self, tmp_path):
        _touch(tmp_path, ".git/index")
        _touch(tmp_path, "index.html")
        _touch(tmp_path, "assets/style.css")
        got = changed_files_since(str(tmp_path), _SINCE)
        assert sorted(got) == ["assets/style.css", "index.html"]

    def test_dotgit_named_content_file_is_not_swallowed(self, tmp_path):
        """The filter matches the .git DIRECTORY component, not a substring —
        a legitimate file that merely contains '.git' in its name must survive."""
        _touch(tmp_path, "docs/why-we-use-git.html")
        got = changed_files_since(str(tmp_path), _SINCE)
        assert got == ["docs/why-we-use-git.html"]
