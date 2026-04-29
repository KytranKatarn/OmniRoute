"""Tests for portrait deploy pipeline wiring (Project #292 — portrait integration).

Run: docker exec archie_platform python -m pytest tests/test_portrait_pipeline.py -v
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch


class TestSyncAllSiteThumbs:
    def test_returns_primary_path_and_kytranempowerment_site(self, tmp_path):
        """_sync_all_site_thumbs returns kytranempowerment.com in sites list when _sync_website_thumb succeeds."""
        from tools.media_studio.services.portrait_service import _sync_all_site_thumbs

        primary = tmp_path / "portrait.jpg"
        primary.write_bytes(b"fake jpeg")
        creed_dir = tmp_path / "creed" / "assets" / "portraits"

        with patch(
            "tools.media_studio.services.portrait_service._sync_website_thumb",
            return_value=str(primary),
        ), patch(
            "tools.media_studio.services.portrait_service.CREED_PORTRAIT_DIR",
            str(creed_dir),
        ):
            result, sites = _sync_all_site_thumbs("/static/media/images/portrait.png")

        assert result == str(primary)
        assert "kytranempowerment.com" in sites

    def test_copies_to_creed_dir(self, tmp_path):
        """_sync_all_site_thumbs copies portrait JPEG to creed-ai.org directory."""
        from tools.media_studio.services.portrait_service import _sync_all_site_thumbs

        primary = tmp_path / "portrait.jpg"
        primary.write_bytes(b"fake jpeg")
        creed_dir = tmp_path / "creed" / "assets" / "portraits"

        with patch(
            "tools.media_studio.services.portrait_service._sync_website_thumb",
            return_value=str(primary),
        ), patch(
            "tools.media_studio.services.portrait_service.CREED_PORTRAIT_DIR",
            str(creed_dir),
        ):
            _sync_all_site_thumbs("/static/media/images/portrait.png")

        assert (creed_dir / "portrait.jpg").is_file()

    def test_returns_creed_in_sites_list(self, tmp_path):
        """_sync_all_site_thumbs includes creed-ai.org in returned sites."""
        from tools.media_studio.services.portrait_service import _sync_all_site_thumbs

        primary = tmp_path / "portrait.jpg"
        primary.write_bytes(b"fake jpeg")
        creed_dir = tmp_path / "creed" / "assets" / "portraits"

        with patch(
            "tools.media_studio.services.portrait_service._sync_website_thumb",
            return_value=str(primary),
        ), patch(
            "tools.media_studio.services.portrait_service.CREED_PORTRAIT_DIR",
            str(creed_dir),
        ):
            _result, sites = _sync_all_site_thumbs("/static/media/images/portrait.png")

        assert "creed-ai.org" in sites

    def test_returns_none_when_primary_sync_fails(self):
        """_sync_all_site_thumbs returns (None, []) when _sync_website_thumb returns None."""
        from tools.media_studio.services.portrait_service import _sync_all_site_thumbs

        with patch(
            "tools.media_studio.services.portrait_service._sync_website_thumb",
            return_value=None,
        ):
            result, sites = _sync_all_site_thumbs("/static/media/images/portrait.png")

        assert result is None
        assert sites == []

    def test_still_returns_kytranempowerment_if_creed_copy_fails(self, tmp_path):
        """_sync_all_site_thumbs still returns primary if creed copy raises PermissionError."""
        from tools.media_studio.services.portrait_service import _sync_all_site_thumbs

        primary = tmp_path / "portrait.jpg"
        primary.write_bytes(b"fake jpeg")
        creed_dir = tmp_path / "creed" / "assets" / "portraits"

        with patch(
            "tools.media_studio.services.portrait_service._sync_website_thumb",
            return_value=str(primary),
        ), patch(
            "tools.media_studio.services.portrait_service.CREED_PORTRAIT_DIR",
            str(creed_dir),
        ), patch(
            "tools.media_studio.services.portrait_service.shutil.copy2",
            side_effect=PermissionError("read-only"),
        ):
            result, sites = _sync_all_site_thumbs("/static/media/images/portrait.png")

        assert result == str(primary)
        assert "kytranempowerment.com" in sites
        assert "creed-ai.org" not in sites
