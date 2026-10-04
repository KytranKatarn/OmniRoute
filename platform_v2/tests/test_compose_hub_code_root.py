"""docker-compose HUB_CODE_ROOT — the compose change must stay INERT until the cutover sets it.

Text-level on purpose (no docker in CI): the contract is that every parametrized mount
defaults to `.` (today's checkout) and that the runtime-state overlays exist in BOTH services,
because a container that mounts the clean clone but lacks them silently loses ~860 MB of
generated media. KB #367081/#367082, task #7067.
"""

import re

from tests.repo_root import repo_path

# Was `Path(__file__).resolve().parent.parent.parent / "docker-compose.yml"`, which is
# correct on the host and resolves to `/docker-compose.yml` inside the test container,
# where `platform_v2` is bind-mounted AS `/app`. The module-level `.read_text()` then
# raised FileNotFoundError during COLLECTION, which took the whole file down with it —
# the one collection error in a 6,281-test run. This is the bug tests/repo_root.py
# exists to stop; its docstring names this file as one of the stragglers that carried a
# comment about the bug instead of the fix.
COMPOSE_PATH = repo_path("docker-compose.yml")
assert COMPOSE_PATH.exists(), (
    "docker-compose.yml not reachable via tests.repo_root "
    f"(looked at {COMPOSE_PATH}); the compose contract cannot be verified."
)
COMPOSE = COMPOSE_PATH.read_text()


def _service(name):
    m = re.search(rf"^  {name}:\n(.*?)(?=^  [A-Za-z_]+:\s*$)", COMPOSE, re.S | re.M)
    assert m, name
    return m.group(1)


def test_every_code_root_default_is_the_current_checkout():
    uses = re.findall(r"\$\{HUB_CODE_ROOT(:-[^}]*)?\}", COMPOSE)
    assert uses, "no HUB_CODE_ROOT mounts found"
    assert set(uses) == {":-."}, "a HUB_CODE_ROOT default other than '.' would change today's mounts"


def test_both_services_parametrize_the_same_code_mounts():
    a = sorted(re.findall(r"\$\{HUB_CODE_ROOT:-\.\}/([^:\s]+):", _service("archie_platform")))
    b = sorted(re.findall(r"\$\{HUB_CODE_ROOT:-\.\}/([^:\s]+):", _service("archie_scheduler")))
    assert a == b and len(a) == 17, (a, b)  # drift between the two is the KB #263303 failure
    assert "platform_v2" in a and "ai_bridge" in a and ".git" in a


def test_state_overlays_exist_in_both_services_and_stay_on_the_brain():
    for svc in ("archie_platform", "archie_scheduler"):
        body = _service(svc)
        for path in ("static/media", "static/downloads", "static/baselines", "static/qa_reports"):
            assert f"- ./platform_v2/{path}:/app/{path}:rw" in body, (svc, path)
        assert "- ./platform_v2/secrets:/app/secrets:rw" in body, svc
        assert "- ./platform_v2/static/screenshots:/app/static/screenshots:rw" in body


def test_writers_and_local_config_are_not_moved_to_the_clone():
    for svc in ("archie_platform", "archie_scheduler"):
        body = _service(svc)
        for keep in (
            "./scripts:",
            "./.claude/rules:",
            "./.claude/skills:",
            "./docs:",
            "./.mcp.json:",
            "./conversation_logs:",
            "./backups:",
            "./secrets:",
            "./host_commands:",
        ):
            assert f"- {keep}" in body, (svc, keep)
