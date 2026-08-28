"""Tests for inspect_element.py helpers.

Run: docker exec archie_platform python -m pytest tests/test_inspect_element.py -v
"""

from __future__ import annotations

import json
import os
import sys

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


class TestGetElementDetails:
    def test_extracts_tag_and_id_from_page(self):
        """get_element_details returns tag, id, classes for a found element."""
        from inspect_element import get_element_details
        from unittest.mock import MagicMock

        mock_page = MagicMock()
        mock_page.evaluate.side_effect = [
            {
                "tag": "DIV",
                "id": "roster-header",
                "classes": ["lcars-header", "sc-live"],
                "text": "AI Roster",
                "rect": {"x": 10.0, "y": 20.0, "width": 800.0, "height": 48.0},
                "styles": {
                    "width": "800px",
                    "height": "48px",
                    "padding": "8px 16px",
                    "margin": "0px",
                    "font-size": "18px",
                    "font-family": "Orbitron, sans-serif",
                    "color": "rgb(0, 229, 255)",
                    "background-color": "rgba(0, 0, 0, 0)",
                    "border": "none",
                    "border-radius": "0px",
                    "display": "flex",
                    "position": "relative",
                    "top": "auto",
                    "left": "auto",
                    "flex": "0 0 auto",
                    "gap": "0px",
                    "z-index": "auto",
                    "opacity": "1",
                    "overflow": "visible",
                    "box-shadow": "none",
                },
                "found": True,
            }
        ]

        result = get_element_details(mock_page, selector="#roster-header")

        assert result["tag"] == "DIV"
        assert result["id"] == "roster-header"
        assert "lcars-header" in result["classes"]
        assert result["bounding_box"]["width"] == 800.0
        assert result["computed_css"]["font-size"] == "18px"
        assert result["found"] is True

    def test_returns_not_found_for_missing_selector(self):
        """get_element_details returns found=False when selector matches nothing."""
        from inspect_element import get_element_details
        from unittest.mock import MagicMock

        mock_page = MagicMock()
        mock_page.evaluate.return_value = {"found": False}

        result = get_element_details(mock_page, selector=".nonexistent-class")

        assert result["found"] is False

    def test_supports_xy_coordinates(self):
        """get_element_details accepts x,y coordinates and uses elementFromPoint."""
        from inspect_element import get_element_details
        from unittest.mock import MagicMock

        mock_page = MagicMock()
        mock_page.evaluate.return_value = {
            "tag": "IMG",
            "id": "",
            "classes": ["agent-avatar"],
            "text": "",
            "rect": {"x": 50.0, "y": 100.0, "width": 64.0, "height": 64.0},
            "styles": {"border-radius": "50%", "width": "64px"},
            "found": True,
        }

        result = get_element_details(mock_page, xy=(200, 350))

        assert result["tag"] == "IMG"
        assert result["found"] is True
        # Verify js_args were built correctly for the XY path
        call_js_args = mock_page.evaluate.call_args[0][1]
        assert call_js_args["selector"] is None
        assert call_js_args["x"] == 200
        assert call_js_args["y"] == 350

    def test_raises_value_error_when_no_args(self):
        """get_element_details raises ValueError when neither selector nor xy is given."""
        from inspect_element import get_element_details
        from unittest.mock import MagicMock
        import pytest

        mock_page = MagicMock()
        with pytest.raises(ValueError, match="Pass either selector= or xy="):
            get_element_details(mock_page)


class TestDrawHighlight:
    def test_creates_highlighted_image_file(self, tmp_path):
        """draw_highlight writes a new PNG with a red rectangle overlay."""
        from inspect_element import draw_highlight
        from PIL import Image

        # Create a 400x300 white test image
        src = tmp_path / "screenshot.png"
        img = Image.new("RGB", (400, 300), "white")
        img.save(str(src))

        out = tmp_path / "highlighted.png"
        draw_highlight(
            src_path=str(src),
            out_path=str(out),
            bbox={"x": 50.0, "y": 80.0, "width": 200.0, "height": 60.0},
        )

        assert out.is_file()
        result = Image.open(str(out))
        assert result.size == (400, 300)

    def test_highlight_box_is_red(self, tmp_path):
        """draw_highlight draws a red (#ef4444) rectangle border."""
        from inspect_element import draw_highlight
        from PIL import Image

        src = tmp_path / "screenshot.png"
        Image.new("RGB", (400, 300), "white").save(str(src))

        out = tmp_path / "highlighted.png"
        draw_highlight(
            src_path=str(src),
            out_path=str(out),
            bbox={"x": 50.0, "y": 80.0, "width": 200.0, "height": 60.0},
        )

        result = Image.open(str(out))
        # Sample a pixel on the top edge of the highlight box
        pixel = result.getpixel((51, 80))
        # Should be red-ish (PIL uses RGB tuples)
        assert pixel[0] > 200 and pixel[1] < 100 and pixel[2] < 100
