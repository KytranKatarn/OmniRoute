"""Guards for deploy.sh service resolution (task #5796).

Two defects, found by running it: a documented invocation that could not work, and
a command that under-delivered on its own promise.

1. **The usage header lied.** It advertised `consumer | ingest | tech`, but the code
   passed the argument straight to `docker compose`, whose services are all `wtf-`
   prefixed. Every documented single-service deploy died on "no such service" — and
   it died at step 2 of 3, *after* the rsync, leaving the VPS source ahead of its
   running container. A half-applied deploy is worse than a refused one: the next
   person's unrelated rebuild silently picks up someone else's code.

2. **`all` rebuilt three of four services.** The list was hand-written
   (`wtf-consumer wtf-ingest wtf-tech`) while docker-compose.yml defines four —
   `wtf-ingest-api` was silently skipped by the one command whose entire promise is
   "everything". Same family as a retention tier with a policy and no pruner: the
   operation reports success while quietly not covering its stated scope.

Both fixes are structural rather than corrective: the service list is READ FROM
docker-compose.yml so it cannot drift again, and validation runs BEFORE the rsync so
a bad argument cannot leave the VPS half-applied.

Parsed and executed, not grepped for prose — a substring scan over this file matches
its own docstring.
"""
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy.sh"
COMPOSE = ROOT / "docker-compose.yml"

# The awk expression the script uses, run here against the real compose file.
_AWK = (
    r'/^services:/{s=1;next} /^[^[:space:]]/{s=0} '
    r's && /^  [a-z0-9_-]+:/{gsub(/[ :]/,"");print}'
)


def _parsed_services() -> list[str]:
    out = subprocess.run(["awk", _AWK, str(COMPOSE)], capture_output=True, text=True, check=True)
    return out.stdout.split()


def _compose_services_via_yaml() -> set[str]:
    """Independent parse, so the test is not just the implementation restated."""
    txt = COMPOSE.read_text()
    # `services:` is the FIRST line of this file, so a leading-newline split misses it.
    m = re.search(r"^services:\s*$", txt, re.M)
    assert m, "compose file has no services: block"
    body = txt[m.end():]
    body = re.split(r"\n(?=\S)", body)[0]      # stop at the next top-level key
    return set(re.findall(r"^  ([a-z0-9_-]+):\s*$", body, re.M))


def test_script_is_valid_bash():
    subprocess.run(["bash", "-n", str(DEPLOY)], check=True)


def test_parsed_services_match_an_independent_yaml_read():
    assert set(_parsed_services()) == _compose_services_via_yaml()


def test_volumes_and_networks_are_not_mistaken_for_services():
    """THE trap in the parse. `wtf_billing_data`, `hf_cache` and `archie_net` are also
    two-space keys; only the `services:` scoping keeps them out. A naive
    `grep '^  [a-z-]*:'` would try to `docker compose build archie_net`."""
    parsed = set(_parsed_services())
    for not_a_service in ("wtf_billing_data", "hf_cache", "archie_net"):
        assert not_a_service in COMPOSE.read_text(), "fixture assumption: key exists in the file"
        assert not_a_service not in parsed, f"{not_a_service} is a volume/network, not a service"


def test_every_compose_service_is_deployable_by_short_and_long_name():
    services = _parsed_services()
    assert services, "parsed no services at all"
    for svc in services:
        short = svc[len("wtf-"):] if svc.startswith("wtf-") else svc
        for spelling in (svc, short):
            resolved = spelling if spelling.startswith("wtf-") else f"wtf-{spelling}"
            assert resolved in services, f"'{spelling}' does not resolve to a real service"


def test_unknown_service_is_refused_before_the_rsync():
    """The half-applied-deploy guard. Must exit non-zero AND must not have rsynced."""
    r = subprocess.run([str(DEPLOY), "definitely-not-a-service"],
                       capture_output=True, text=True, cwd=str(ROOT))
    assert r.returncode != 0, "an unknown service must fail"
    combined = r.stdout + r.stderr
    assert "Rsync complete" not in combined, "validation must precede the rsync"
    assert "untouched" in combined, "the operator must be told the VPS was not modified"


def test_validation_precedes_rsync_in_source_order():
    """Belt and braces: the runtime test above passes trivially if the script dies for
    some other reason. Pin the ordering itself."""
    src = DEPLOY.read_text()
    guard_at = src.index("Nothing was rsynced")
    rsync_at = src.index("rsync -az")
    assert guard_at < rsync_at, "the unknown-service guard must sit above the rsync call"


def test_all_is_not_a_hardcoded_list():
    """#5796 regression: `all` must be derived, or it silently under-covers again."""
    src = DEPLOY.read_text()
    assert "ALL_SERVICES=" in src and "docker-compose.yml" in src, \
        "the service list must be read from the compose file"
    # the specific stale triple that skipped wtf-ingest-api
    assert "--build wtf-consumer wtf-ingest wtf-tech" not in src, \
        "hardcoded 3-service list is back — wtf-ingest-api would be skipped again"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
