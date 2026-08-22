"""#5945 — a fixer needs an openable path; the fingerprint is not one.

`_audit_file_path` deliberately keeps a "["-prefixed module token so a re-audit
matches the original proposals. 124 of the 327 still_open static proposals carried
one, so no find/replace fixer could ever move them.
"""

import sys

sys.path.insert(0, "/app")

from services.audit_pipeline import _audit_file_path, resolve_fix_path  # noqa: E402


def test_resolves_the_two_tokens_that_cover_the_backlog():
    """Roots were DERIVED by testing each token's files against candidate roots on
    disk, not assumed: [AI_BRIDGE] 43/43, [APP_CORE] 262/274. These two account for
    all 124 still_open pseudo-path proposals (50 + 74)."""
    assert resolve_fix_path("[AI_BRIDGE]/semantic_search.py") == "ai_bridge/semantic_search.py"
    assert resolve_fix_path("[APP_CORE]/app.py") == "platform_v2/app.py"
    assert resolve_fix_path("[MIGRATIONS]/001.sql") == "database/migrations/001.sql"


def test_unknown_token_returns_None_rather_than_guessing():
    """⚠️ [dispatch_routing] is deliberately ABSENT from the map: only 1 of its 69
    files resolves anywhere, so it is a LOGICAL grouping, not a directory. Inventing a
    root would write a path that silently points at nothing — worse than no path."""
    assert resolve_fix_path("[dispatch_routing]/foo.py") is None
    assert resolve_fix_path("[NOPE]/foo.py") is None
    assert resolve_fix_path("[AI_BRIDGE]") is None  # token with no file part


def test_a_real_path_passes_through_unchanged():
    assert resolve_fix_path("platform_v2/tools/x/y.py") == "platform_v2/tools/x/y.py"


def test_junk_in_returns_None_not_an_exception():
    for bad in (None, "", 123, []):
        assert resolve_fix_path(bad) is None


def test_it_is_the_inverse_of_the_fingerprint_builder():
    """Round-trip: whatever _audit_file_path emits for a token module must be something
    resolve_fix_path can turn back into a real path. If someone changes the fingerprint
    format, this fails rather than silently producing unopenable fix_paths."""
    fp = _audit_file_path("[AI_BRIDGE]", "semantic_search.py")
    assert fp == "[AI_BRIDGE]/semantic_search.py"
    assert resolve_fix_path(fp) == "ai_bridge/semantic_search.py"


def test_it_never_mutates_the_fingerprint():
    """⚠️ THE DANGEROUS SHORTCUT. Rewriting file_path itself would break fingerprint
    matching, drop every affected proposal out of the reverify's `current` set, and flip
    all 124 to 'fixed' — a real backlog rendered as a clean bill of health."""
    fp = "[APP_CORE]/app.py"
    resolve_fix_path(fp)
    assert fp == "[APP_CORE]/app.py"
