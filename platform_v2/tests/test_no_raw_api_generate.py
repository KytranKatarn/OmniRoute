"""Lint regression — no raw api/generate outside the helper + allowlist.

Ensures new dispatcher-style code routes through build_options(), per
spec §'Single-writer guardrail' of docs/superpowers/specs/
2026-04-19-dispatcher-gpu-awareness-design.md.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


# Inside the container, platform_v2/ is mounted at /app but the full repo
# lives at /mnt/archie_brain. Resolve robustly: walk up from this file until
# we find the scripts/ directory, then fall back to the known host path.
def _find_repo_root() -> Path:
    candidate = Path(__file__).resolve()
    for parent in candidate.parents:
        if (parent / "scripts" / "check_agent_single_writer.py").exists():
            return parent
    # Absolute fallback for the container mount point
    return Path("/mnt/archie_brain")


REPO = _find_repo_root()


def test_single_writer_guardrail_passes_on_current_tree():
    """The canonical post-Task-7 tree should pass the guardrail clean.

    Covers: ollama_options (helper), department_dispatcher + orchestration_engine
    (retrofitted consumers in allowlist), agent_loop (health ping in allowlist),
    archie_bridge + knowledge_analyzer (legacy deferred, in allowlist).
    """
    script = REPO / "scripts" / "check_agent_single_writer.py"
    targets = [
        "platform_v2/tools/department_hq/services/ollama_options.py",
        "platform_v2/tools/department_hq/services/department_dispatcher.py",
        "platform_v2/tools/department_hq/services/orchestration_engine.py",
        "ai_bridge/agent_loop.py",
        "ai_bridge/archie_bridge.py",
        "ai_bridge/knowledge_analyzer.py",
    ]
    existing = [str(REPO / t) for t in targets if (REPO / t).exists()]
    result = subprocess.run(
        [sys.executable, str(script), *existing],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"guardrail should pass on retrofitted + allowlisted tree.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_single_writer_guardrail_flags_new_raw_api_generate(tmp_path):
    """A new file with raw api/generate must trip the guardrail."""
    script = REPO / "scripts" / "check_agent_single_writer.py"
    offender = tmp_path / "fake_dispatcher.py"
    offender.write_text(
        "import requests\n\n" "def run():\n" '    requests.post("http://ollama/api/generate", json={"model": "x"})\n'
    )
    result = subprocess.run(
        [sys.executable, str(script), str(offender)],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, "guardrail should flag raw api/generate in new file"
    output = (result.stdout + result.stderr).lower()
    assert (
        "api/generate" in output or "build_options" in output
    ), f"guardrail output should mention the offending pattern: {result.stdout} {result.stderr}"


def test_single_writer_guardrail_flags_new_raw_api_chat(tmp_path):
    """Same rule applies to /api/chat — both endpoints are guarded."""
    script = REPO / "scripts" / "check_agent_single_writer.py"
    offender = tmp_path / "fake_chat_caller.py"
    offender.write_text(
        "import requests\n\n" "def run():\n" '    requests.post("http://ollama/api/chat", json={"model": "x"})\n'
    )
    result = subprocess.run(
        [sys.executable, str(script), str(offender)],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, "guardrail should flag raw api/chat in new file"


def test_single_writer_guardrail_ignores_tests_and_comments():
    """Test files and comment lines in production code must not trip the guardrail."""
    script = REPO / "scripts" / "check_agent_single_writer.py"
    # Our own test file references "api/generate" in strings that are test fixtures.
    # It must not trip the guardrail.
    self_path = Path(__file__)
    result = subprocess.run(
        [sys.executable, str(script), str(self_path)],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"test file with api/generate in a string fixture must NOT trip guardrail.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_single_writer_guardrail_skips_pure_comment_lines(tmp_path):
    """A production .py file whose only api/generate reference is inside a
    comment line should NOT trip the guardrail.
    """
    script = REPO / "scripts" / "check_agent_single_writer.py"
    benign = tmp_path / "benign_production.py"
    benign.write_text(
        '"""Some module."""\n\n'
        "# NOTE: historically this module called api/generate directly,\n"
        "# migrated to build_options() in 2026-04.\n\n"
        "def run():\n"
        '    return "ok"\n'
    )
    result = subprocess.run(
        [sys.executable, str(script), str(benign)],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"file with api/generate only in comments should NOT trip guardrail.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_single_writer_guardrail_does_not_false_match_on_api_generated(tmp_path):
    """The regex must not match substrings like api/generated_code or api/chat_history."""
    script = REPO / "scripts" / "check_agent_single_writer.py"
    benign = tmp_path / "benign_substrings.py"
    benign.write_text('URL = "http://svc/api/generated_code"\n' 'OTHER = "http://svc/api/chat_history"\n')
    result = subprocess.run(
        [sys.executable, str(script), str(benign)],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"regex should not match api/generated_code or api/chat_history:\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
