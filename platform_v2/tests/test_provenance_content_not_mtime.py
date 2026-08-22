"""#5918 — mtime is not evidence that the CODE changed.

`check_hub_deploy` reported restart_required whenever the newest .py mtime was
later than process start. `git checkout` between branches, `touch`, an editor
re-save, or Black reformatting-then-reverting all bump mtime with byte-identical
content — so the observer alarmed on code that was already live. An alarm that
fires on a no-op gets muted, which is the failure family this module exists to
prevent.
"""

import os
import sys
import tempfile
import time

sys.path.insert(0, "/app")

import services.hub_deploy_provenance as hp  # noqa: E402


def _tree():
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "a.py"), "w") as fh:
        fh.write("x = 1\n")
    os.makedirs(os.path.join(d, "sub"), exist_ok=True)
    with open(os.path.join(d, "sub", "b.py"), "w") as fh:
        fh.write("y = 2\n")
    return d


def test_touch_does_not_change_the_hash():
    """THE FALSE POSITIVE. Same bytes, newer mtime -> identical fingerprint."""
    d = _tree()
    before = hp.source_tree_sha(d)
    time.sleep(1.1)
    os.utime(os.path.join(d, "a.py"), None)
    assert hp.source_tree_sha(d) == before


def test_a_real_edit_does_change_the_hash():
    """The half that must NOT be lost: a genuine change still alarms."""
    d = _tree()
    before = hp.source_tree_sha(d)
    with open(os.path.join(d, "a.py"), "w") as fh:
        fh.write("x = 2\n")
    assert hp.source_tree_sha(d) != before


def test_a_new_file_changes_the_hash():
    d = _tree()
    before = hp.source_tree_sha(d)
    with open(os.path.join(d, "sub", "c.py"), "w") as fh:
        fh.write("z = 3\n")
    assert hp.source_tree_sha(d) != before


def test_hash_is_path_sensitive_not_just_content():
    """Two files swapping names is a real change even though the bytes are the same
    set; folding the path in makes that visible."""
    d = _tree()
    before = hp.source_tree_sha(d)
    os.rename(os.path.join(d, "a.py"), os.path.join(d, "renamed.py"))
    assert hp.source_tree_sha(d) != before


def test_a_missing_root_never_raises():
    """FAIL-OPEN, per the module contract: an UNKNOWN is never a fault, and a monitor
    that throws on its own environment is how the original bug stayed invisible.

    (An earlier version of this test ended in `or True` and could therefore never
    fail — the exact anti-pattern this file's sibling tests exist to prevent.)
    """
    got = hp.source_tree_sha("/definitely/not/a/real/path")
    assert isinstance(got, str) and len(got) == 64  # empty walk -> stable sha of nothing
    assert got == hp.source_tree_sha("/another/missing/path")  # deterministic
    assert got != hp.source_tree_sha(_tree())  # and distinguishable from real content


def test_a_LATE_import_is_not_trusted():
    """⚠️ THE FALSE-NEGATIVE GUARD, and the reason this isn't a one-liner. If the
    module were imported lazily on first request, an edit made between startup and
    that import would ALREADY be inside _LOADED_TREE_SHA — so a content match would
    wrongly read as in_sync, silently suppressing the exact alarm this module exists
    to raise. Only a near-startup import is trusted; otherwise the conservative mtime
    verdict stands."""
    assert hp._loaded_sha_is_trustworthy(hp._IMPORT_TIME - 5) is True
    assert hp._loaded_sha_is_trustworthy(hp._IMPORT_TIME - 3600) is False
    assert hp._loaded_sha_is_trustworthy("nonsense") is False
    assert hp._loaded_sha_is_trustworthy(None) is False
