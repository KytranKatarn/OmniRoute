"""DR steps that report success while doing nothing (#5439, #5440).

Both bugs shipped a log line asserting an outcome that never happened:

  #5439  poll_action() returns its value on STDOUT, and log() also writes STDOUT,
         so `action="$(poll_action ...)"` captured the LOG LINE + the value. It
         matched no case, fell through to "awaiting decision", and because the
         decision file is removed before the case runs, the request was consumed
         and destroyed. That broke precisely the no-Telegram escape hatch.

  #5440  auto_failback stopped 'archie_platform' (the HUB's container name, absent
         on boston-2) instead of 'archie_platform_standby', swallowed the error with
         `>/dev/null 2>&1 || true`, then logged "DR platform stopped" unconditionally.

These tests exercise the REAL shipped shell, extracted from the scripts at run time,
so they cannot drift from a copy. Each bug also has a companion test that reproduces
the OLD behaviour and asserts it FAILS — without that, a passing test proves nothing.
"""

import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest
from tests.repo_root import repo_root as _shared_repo_root

_MARKER = Path("scripts") / "dr" / "watchdog" / "dr_watchdog.sh"


def _find_repo() -> Path:
    """Locate the repo root by SEARCHING for a known file, not by counting parents (#5994).

    `parents[2]` is correct on the HOST, where this file sits at
    /mnt/archie_brain/platform_v2/tests/. Inside the test container `platform_v2` is mounted
    AS /app, so the same expression resolves one level too shallow — to the FILESYSTEM ROOT.
    Every path built from it became /scripts/dr/..., and 13 assertions failed on files that
    exist perfectly well one directory over.

    /mnt/archie_brain is appended because the container mounts the repo there read-only
    while `__file__` lives under /app, so no ancestor of this file is the repo root.

    Same approach already used by test_dr_watchdog_snooze_early_close.py — this file just
    never adopted it.
    """
    for base in list(Path(__file__).resolve().parents) + [Path("/mnt/archie_brain")]:
        if (base / _MARKER).exists():
            return base
    # Fall back to the historical guess rather than raising at import: the tests below
    # already skip on a missing script, and a hard failure here would abort collection.
    return _shared_repo_root()  # one resolver for the whole suite (#5994)


_REPO = _find_repo()
_WATCHDOG = _REPO / _MARKER
_FAILBACK = _REPO / "scripts" / "dr" / "auto_failback.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")


def _require(path: Path) -> str:
    assert path.is_file(), f"missing {path} — test cannot prove anything"
    return path.read_text()


def _extract_poll_action(src: str) -> str:
    """Pull log() + poll_action() out of the real watchdog script."""
    log_line = next(l for l in src.splitlines() if l.startswith("log()"))
    m = re.search(r"^poll_action\(\)\{.*?^\}", src, re.S | re.M)
    assert m, "poll_action() not found — did the script get restructured?"
    return log_line + "\n" + m.group(0)


def _run_bash(script: str, cwd: Path, env=None) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, cwd=str(cwd), env=env)


# ---------------------------------------------------------------------------
# #5439 — the file-based decision must reach the caller intact
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("decision", ["rebuild", "skip_rebuild", "verify", "proceed", "abort"])
def test_file_decision_is_returned_verbatim(tmp_path, decision):
    body = _extract_poll_action(_require(_WATCHDOG))
    (tmp_path / ".dr_decision").write_text(decision + "\n")
    script = f'DR={tmp_path}\n{body}\naction="$(poll_action 0)"\nprintf "[%s]" "$action"\n'
    r = _run_bash(script, tmp_path)
    assert r.stdout == f"[{decision}]", f"caller saw {r.stdout!r} (stderr: {r.stderr!r})"


def test_decision_file_is_consumed_single_use(tmp_path):
    body = _extract_poll_action(_require(_WATCHDOG))
    (tmp_path / ".dr_decision").write_text("rebuild\n")
    script = f'DR={tmp_path}\n{body}\naction="$(poll_action 0)"\nprintf "[%s]" "$action"\n'
    _run_bash(script, tmp_path)
    assert not (tmp_path / ".dr_decision").exists(), "a decision left on disk re-fires every cycle"


def test_the_explanatory_log_still_appears_on_stderr(tmp_path):
    """Moving the log off stdout must not make it VANISH — that was half the bug."""
    body = _extract_poll_action(_require(_WATCHDOG))
    (tmp_path / ".dr_decision").write_text("rebuild\n")
    script = f'DR={tmp_path}\n{body}\naction="$(poll_action 0)"\nprintf "[%s]" "$action"\n'
    r = _run_bash(script, tmp_path)
    assert "decision 'rebuild' read from" in r.stderr


def test_unrecognised_decision_yields_empty_not_a_log_line(tmp_path):
    body = _extract_poll_action(_require(_WATCHDOG))
    (tmp_path / ".dr_decision").write_text("banana\n")
    script = f'DR={tmp_path}\n{body}\naction="$(poll_action 0)"\nprintf "[%s]" "$action"\n'
    r = _run_bash(script, tmp_path)
    assert r.stdout == "[]", f"garbage leaked into the caller: {r.stdout!r}"
    assert "unrecognised decision" in r.stderr


def test_5439_is_load_bearing_unredirected_log_breaks_the_caller(tmp_path):
    """Reproduce the ORIGINAL bug: strip the '>&2' and the caller must NOT get 'rebuild'."""
    body = _extract_poll_action(_require(_WATCHDOG)).replace('" >&2', '"')
    assert ">&2" not in body.split("case")[1].split("esac")[0], "defect not reintroduced"
    (tmp_path / ".dr_decision").write_text("rebuild\n")
    script = f'DR={tmp_path}\n{body}\naction="$(poll_action 0)"\nprintf "[%s]" "$action"\n'
    r = _run_bash(script, tmp_path)
    assert r.stdout != "[rebuild]", "old code should have polluted stdout — proof is void"
    assert "decision 'rebuild' read from" in r.stdout, "the log line should be INSIDE the value"


# ---------------------------------------------------------------------------
# #5440 — never claim the DR platform stopped without proof
# ---------------------------------------------------------------------------


def _extract_step4(src: str) -> str:
    m = re.search(r"^# ---- 4\. .*?(?=^# ---- 5\.)", src, re.S | re.M)
    assert m, "step 4 block not found in auto_failback.sh"
    return m.group(0)


def _fake_docker(all_names, running_names):
    """Stub `docker` as a bash FUNCTION, not a PATH shim.

    A function beats PATH lookup unconditionally, so this cannot silently fall
    through to the real docker — which is exactly what happened with a bin/ stub:
    `command -v docker` still resolved to /usr/bin/docker, the real hub daemon
    answered, and because the hub genuinely has no 'archie_platform_standby' the
    test read "not present" and passed for the wrong reason.
    """
    return textwrap.dedent(
        f"""\
        docker(){{
          if [ "$1" = "ps" ] && [ "$2" = "-a" ]; then printf '%s\\n' {all_names or "''"}; return 0; fi
          if [ "$1" = "ps" ]; then printf '%s\\n' {running_names or "''"}; return 0; fi
          return 0
        }}
        """
    )


def _run_step4(tmp_path, all_names, running_names):
    body = _extract_step4(_require(_FAILBACK))
    script = 'log(){ echo "$*"; }\n' + _fake_docker(all_names, running_names) + body
    return _run_bash(script, tmp_path)


def test_the_docker_stub_actually_intercepts(tmp_path):
    """Guard the guard: if the stub is bypassed, every step-4 test is meaningless."""
    script = _fake_docker("'sentinel_container'", "") + "docker ps -a --format '{{.Names}}'\n"
    r = _run_bash(script, tmp_path)
    assert r.stdout.strip() == "sentinel_container", f"stub bypassed — got {r.stdout!r}"


def test_step4_targets_the_standby_container_not_the_hub_name():
    """'archie_platform' is the HUB's name and does not exist on boston-2."""
    body = _extract_step4(_require(_FAILBACK))
    assert "archie_platform_standby" in body
    assert not re.search(r"\barchie_platform\b(?!_standby)", body.replace("#", "\n#").split("\n#")[0])


def test_step4_reports_success_when_containers_really_stop(tmp_path):
    r = _run_step4(tmp_path, "'archie_platform_standby' 'archie_scheduler_standby'", "")
    assert "DR platform stopped" in r.stdout
    assert "STILL RUNNING" not in r.stdout


def test_step4_refuses_to_claim_success_when_a_container_survives(tmp_path):
    """The #5440 failure: it logged 'DR platform stopped' while the standby ran on."""
    r = _run_step4(
        tmp_path,
        "'archie_platform_standby' 'archie_scheduler_standby'",
        "'archie_platform_standby'",
    )
    assert "STILL RUNNING" in r.stdout
    assert "NOT fully stopped" in r.stdout
    # the bare success line must NOT be emitted
    assert not any(l.strip() == "DR platform stopped" for l in r.stdout.splitlines())


def test_step4_is_quiet_and_honest_when_nothing_is_deployed(tmp_path):
    r = _run_step4(tmp_path, "", "")
    assert "not present" in r.stdout
    assert "DR platform stopped" in r.stdout  # nothing to stop IS success
