"""The ACL repair scripts must be able to tell writable from unwritable.

WHY THIS FILE EXISTS
--------------------
`scripts/fix-live-tree-ownership.sh` had a probe (`can_write`) that fed a
multi-line program to `python3 -c` with the continuation lines INDENTED. Python
rejects that with `IndentationError`, so the probe failed for EVERY file, the
`2>/dev/null` on the call hid the traceback, and the job cheerfully reported
"40/40 files not writable" on a tree that was completely fine. It shipped in
PR #3497 and was only caught because `setup-live-tree-permissions.sh --self-test`
probes a known-writable control before trusting any reading.

The lesson encoded below: a probe that can only ever answer "no" is
indistinguishable from a probe that is working. These tests make the probe
answer "yes" at least once, and make the embedded program parse.
"""

import os
import pathlib
import re
import subprocess

import pytest

HERE = pathlib.Path(__file__).resolve()
# The scripts live at the repo root, outside platform_v2/ where the tests run.
CANDIDATES = [
    HERE.parents[2] / "scripts" / "fix-live-tree-ownership.sh",
    pathlib.Path("/mnt/archie_brain/scripts/fix-live-tree-ownership.sh"),
]
FIXER = next((p for p in CANDIDATES if p.exists()), None)
SETUP = next(
    (
        p
        for p in [
            HERE.parents[2] / "scripts" / "setup-live-tree-permissions.sh",
            pathlib.Path("/mnt/archie_brain/scripts/setup-live-tree-permissions.sh"),
        ]
        if p.exists()
    ),
    None,
)

pytestmark = pytest.mark.skipif(FIXER is None, reason="ACL scripts not visible from this run")


def _extract_probe_python(src: str) -> str:
    """Pull the embedded probe program out of can_write().

    Accepts either form: a quoted heredoc (`python3 - <<'PY'`) or a `-c '...'`
    string. Returns "" if neither is found, so a future refactor fails loudly
    here rather than silently skipping the check.
    """
    fn = re.search(r"can_write\(\)\s*\{(.*?)\n\s*\}", src, re.S)
    assert fn, "can_write() not found — rename it and this test will tell you"
    body = fn.group(1)
    heredoc = re.search(r"<<'(\w+)'.*?\n(.*?)\n\1", body, re.S)
    if heredoc:
        return heredoc.group(2)
    dash_c = re.search(r"python3 -c '(.*?)'\s+\"\$f\"", body, re.S)
    return dash_c.group(1) if dash_c else ""


def test_embedded_probe_python_compiles():
    """The regression test for the IndentationError.

    `python3 -c` with indented continuation lines is a SyntaxError, and the
    resulting non-zero exit was indistinguishable from "file not writable".
    Compiling the program catches it without needing root or a real file.
    """
    src = FIXER.read_text()
    program = _extract_probe_python(src)
    assert program, "could not locate the embedded probe program in can_write()"
    compile(program, "<probe>", "exec")  # raises SyntaxError/IndentationError


def test_probe_python_has_no_indented_continuation_lines():
    # Belt and braces: the first line of a `-c` program must be unindented, and
    # this is the exact shape that broke. Heredocs are immune, so if someone
    # converts back to `-c` this catches the regression.
    src = FIXER.read_text()
    fn = re.search(r"can_write\(\)\s*\{(.*?)\n\s*\}", src, re.S)
    body = fn.group(1)
    if "<<'" in body:
        return  # heredoc form is safe
    dash_c = re.search(r"python3 -c '(.*?)'\s+\"\$f\"", body, re.S)
    if not dash_c:
        return
    for line in dash_c.group(1).splitlines()[1:]:
        assert not line.startswith(" "), (
            "indented continuation line in a `python3 -c` string -> IndentationError; "
            "the probe would fail for every file (see this module's docstring)"
        )


@pytest.mark.skipif(os.geteuid() != 0, reason="the probe drops privileges; needs root")
def test_probe_demonstrates_a_writable_file():
    """A probe that can only say "no" is indistinguishable from a broken one.

    This is the positive control that would have caught the shipped
    IndentationError on its own: the setup script probes a known-writable file
    BEFORE reporting on anything else, and must be able to say OK.
    """
    if SETUP is None:
        pytest.skip("setup-live-tree-permissions.sh not found")
    r = subprocess.run(
        ["/bin/bash", str(SETUP), "--self-test"],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert "Self-test passed" in r.stdout, (
        "the ACL probe cannot demonstrate a writable file — it is reporting "
        "noise, not permission state:\n" + r.stdout + r.stderr
    )


def test_setup_script_refuses_secrets_paths():
    if SETUP is None:
        pytest.skip("setup script not found")
    src = SETUP.read_text()
    # The secrets guard must exist, and secrets must never be in the seed list.
    assert "secrets" in src
    seed = re.search(r"RW_MOUNTS=\((.*?)\)", src, re.S)
    assert seed, "RW_MOUNTS list not found"
    assert "secrets" not in seed.group(1), "secrets must never be an ACL seed target"


def test_setup_script_lists_no_duplicates():
    if SETUP is None:
        pytest.skip("setup script not found")
    seed = re.search(r"RW_MOUNTS=\((.*?)\)", pathlib.Path(SETUP).read_text(), re.S)
    paths = re.findall(r'"\$TREE/([^"]+)"', seed.group(1))
    assert len(paths) == len(set(paths)), "duplicate entries in RW_MOUNTS"


@pytest.mark.skipif(SETUP is None, reason="setup script not found")
def test_setup_script_is_syntactically_valid():
    r = subprocess.run(["bash", "-n", str(SETUP)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_fixer_is_syntactically_valid():
    r = subprocess.run(["bash", "-n", str(FIXER)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
