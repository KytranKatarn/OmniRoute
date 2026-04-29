"""Tests for inspect_element.py helpers.

Run: docker exec archie_platform python -m pytest tests/test_inspect_element.py -v
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from unittest.mock import patch

# The script is in scripts/, not on the Python path — import it directly
# Inside Docker, platform_v2/ is mounted at /app/ and scripts/ at /mnt/archie_brain/scripts/
_scripts_dir = os.path.join(os.path.dirname(__file__), "..", "..", "scripts")
_scripts_dir_abs = os.path.abspath(_scripts_dir)
# Fallback to known Docker mount path if relative resolution escapes /app
if not os.path.isdir(_scripts_dir_abs):
    _scripts_dir_abs = "/mnt/archie_brain/scripts"
sys.path.insert(0, _scripts_dir_abs)


class TestFindSessionDir:
    def test_returns_screen_dir_from_last_server_started_line(self, tmp_path):
        """find_session_dir reads screen_dir from last server-started entry in launcher log."""
        from inspect_element import find_session_dir

        log = tmp_path / "brainstorm-launcher.log"
        log.write_text(
            json.dumps(
                {"type": "server-started", "screen_dir": "/old/session/content", "state_dir": "/old/session/state"}
            )
            + "\n"
            + json.dumps(
                {"type": "server-started", "screen_dir": "/new/session/content", "state_dir": "/new/session/state"}
            )
            + "\n"
        )

        result = find_session_dir(log_path=str(log))
        assert result == ("/new/session/content", "/new/session/state")

    def test_returns_none_when_log_missing(self, tmp_path):
        """find_session_dir returns (None, None) when launcher log doesn't exist."""
        from inspect_element import find_session_dir

        result = find_session_dir(log_path=str(tmp_path / "nonexistent.log"))
        assert result == (None, None)

    def test_returns_none_when_no_server_started_entries(self, tmp_path):
        """find_session_dir returns (None, None) when log has no server-started lines."""
        from inspect_element import find_session_dir

        log = tmp_path / "brainstorm-launcher.log"
        log.write_text('{"error": "Server failed to start within 5 seconds"}\n')

        result = find_session_dir(log_path=str(log))
        assert result == (None, None)

    def test_does_not_overwrite_good_pair_with_partial_entry(self, tmp_path):
        """find_session_dir skips server-started entries missing screen_dir or state_dir."""
        from inspect_element import find_session_dir

        log = tmp_path / "brainstorm-launcher.log"
        log.write_text(
            json.dumps({"type": "server-started", "screen_dir": "/good/content", "state_dir": "/good/state"})
            + "\n"
            + json.dumps({"type": "server-started"})  # missing both keys
            + "\n"
        )

        result = find_session_dir(log_path=str(log))
        assert result == ("/good/content", "/good/state")
