# services/agents/tests/test_codex_scope.py
from services.agents.codex_scope import is_in_scope

CFG = {
    "allowed_paths": ["platform_v2/tools/fitness/", "platform_v2/tests/"],
    "blocked_globs": ["*.env", "docker-compose*", "scripts/dr/*"],
}


def test_allowed_module_path():
    assert is_in_scope("platform_v2/tools/fitness/routes.py", CFG) is True


def test_outside_scope_denied():
    assert is_in_scope("platform_v2/app.py", CFG) is False


def test_blocked_glob_denied_even_if_under_allowed():
    # an .env dropped inside an allowed dir is still blocked
    assert is_in_scope("platform_v2/tools/fitness/.env", CFG) is False


def test_dr_script_denied():
    assert is_in_scope("scripts/dr/failover.sh", CFG) is False


def test_test_dir_allowed():
    assert is_in_scope("platform_v2/tests/test_fitness.py", CFG) is True


# --- security regression tests (path-traversal / fail-open hardening) ---


def test_path_traversal_escaping_allowed_dir_denied():
    # resolves to platform_v2/app.py — must be denied despite the allowed prefix
    assert is_in_scope("platform_v2/tools/fitness/../../app.py", CFG) is False


def test_deep_traversal_to_secret_denied():
    assert is_in_scope("platform_v2/tools/fitness/../../../../.env", CFG) is False


def test_absolute_path_denied():
    assert is_in_scope("/etc/passwd", CFG) is False


def test_parent_traversal_denied():
    assert is_in_scope("../secrets.txt", CFG) is False


def test_dot_slash_prefix_normalized_and_allowed():
    assert is_in_scope("./platform_v2/tools/fitness/x.py", CFG) is True


def test_sibling_dir_boundary_not_matched():
    # a prefix without trailing slash must NOT match a sibling like fitness_evil/
    cfg = {"allowed_paths": ["platform_v2/tools/fitness"], "blocked_globs": []}
    assert is_in_scope("platform_v2/tools/fitness_evil/x.py", cfg) is False
    assert is_in_scope("platform_v2/tools/fitness/x.py", cfg) is True


def test_malformed_config_fails_closed():
    # empty / root prefixes must be skipped, not allow-all
    cfg = {"allowed_paths": ["", "/", ".."], "blocked_globs": []}
    assert is_in_scope("platform_v2/app.py", cfg) is False
    assert is_in_scope("anything/at/all.py", cfg) is False
