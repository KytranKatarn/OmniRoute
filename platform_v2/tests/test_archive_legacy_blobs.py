import services.audit_pipeline as ap


def test_legacy_basename_header_is_legacy():
    # pre-format: basename-only header (2647-style), or full-file blob
    assert ap._is_legacy_blob("--- a/__init__.py\n+++ b/__init__.py\n@@ -7,4 +7,4 @@\n-x\n+y\n") is True
    assert (
        ap._is_legacy_blob("--- a/department_dispatcher.py\n+++ b/department_dispatcher.py\n@@ -1,10815 +1,6 @@\n")
        is True
    )
    assert ap._is_legacy_blob('[{"file_path": "x.py", "content": "y"}]') is True


def test_modern_repo_relative_diff_is_not_legacy():
    modern = "--- a/platform_v2/tools/brainstorm/__init__.py\n+++ b/platform_v2/tools/brainstorm/__init__.py\n@@ -1 +1 @@\n-x\n+y\n"
    assert ap._is_legacy_blob(modern) is False
    modern_bridge = "--- a/ai_bridge/x.py\n+++ b/ai_bridge/x.py\n@@ -1 +1 @@\n-a\n+b\n"
    assert ap._is_legacy_blob(modern_bridge) is False


def test_empty_or_nonstring_code_changes_is_legacy():
    # NULL code_changes column or an empty/whitespace-only legacy row must be
    # treated as legacy (archive+regenerate), never as a modern diff.
    assert ap._is_legacy_blob(None) is True
    assert ap._is_legacy_blob("") is True
    assert ap._is_legacy_blob("   \n\t ") is True
