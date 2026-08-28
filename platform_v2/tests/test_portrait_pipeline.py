"""Tests for portrait deploy pipeline wiring (Project #292 — portrait integration).

Run: docker exec archie_platform python -m pytest tests/test_portrait_pipeline.py -v
"""

from __future__ import annotations

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


class TestDeployPortraitToSites:
    def test_calls_run_deploy_pipeline_for_kytranempowerment(self, tmp_path):
        """_deploy_portrait_to_sites calls run_deploy_pipeline for kytranempowerment.com."""
        from tools.media_studio.services.portrait_service import _deploy_portrait_to_sites

        kytran_portraits = tmp_path / "kytranempowerment" / "assets" / "portraits"
        kytran_portraits.mkdir(parents=True)
        (kytran_portraits / "portrait.jpg").write_bytes(b"fake jpeg")

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.error = None

        with patch(
            "tools.media_studio.services.portrait_service.run_deploy_pipeline",
            return_value=mock_result,
        ) as mock_deploy, patch(
            "tools.media_studio.services.portrait_service._PORTRAIT_DEPLOY_SITES",
            [
                {"domain": "kytranempowerment.com", "source_path": str(tmp_path / "kytranempowerment")},
                {"domain": "creed-ai.org", "source_path": str(tmp_path / "creed")},
            ],
        ):
            _deploy_portrait_to_sites("portrait", "TEST_AGENT")

        calls = mock_deploy.call_args_list
        domains = [c.args[1]["domain"] for c in calls if len(c.args) > 1 and "domain" in c.args[1]]
        assert "kytranempowerment.com" in domains

    def test_calls_run_deploy_pipeline_for_creed(self, tmp_path):
        """_deploy_portrait_to_sites calls run_deploy_pipeline for creed-ai.org."""
        from tools.media_studio.services.portrait_service import _deploy_portrait_to_sites

        creed_portraits = tmp_path / "creed" / "assets" / "portraits"
        creed_portraits.mkdir(parents=True)
        (creed_portraits / "portrait.jpg").write_bytes(b"fake jpeg")

        mock_result = MagicMock()
        mock_result.success = True

        with patch(
            "tools.media_studio.services.portrait_service.run_deploy_pipeline",
            return_value=mock_result,
        ) as mock_deploy, patch(
            "tools.media_studio.services.portrait_service._PORTRAIT_DEPLOY_SITES",
            [
                {"domain": "kytranempowerment.com", "source_path": str(tmp_path / "kytranempowerment")},
                {"domain": "creed-ai.org", "source_path": str(tmp_path / "creed")},
            ],
        ):
            _deploy_portrait_to_sites("portrait", "TEST_AGENT")

        calls = mock_deploy.call_args_list
        domains = [c.args[1]["domain"] for c in calls if len(c.args) > 1 and "domain" in c.args[1]]
        assert "creed-ai.org" in domains

    def test_skips_domain_when_portrait_file_missing(self, tmp_path):
        """_deploy_portrait_to_sites skips a domain if the portrait JPEG is not in that site dir."""
        from tools.media_studio.services.portrait_service import _deploy_portrait_to_sites

        mock_result = MagicMock()
        mock_result.success = True

        with patch(
            "tools.media_studio.services.portrait_service.run_deploy_pipeline",
            return_value=mock_result,
        ) as mock_deploy, patch(
            "tools.media_studio.services.portrait_service._PORTRAIT_DEPLOY_SITES",
            [
                {
                    "domain": "kytranempowerment.com",
                    "source_path": str(tmp_path / "kytranempowerment"),
                },  # portraits dir does not exist
                {"domain": "creed-ai.org", "source_path": str(tmp_path / "creed")},  # portraits dir does not exist
            ],
        ):
            _deploy_portrait_to_sites("portrait", "TEST_AGENT")

        assert mock_deploy.call_count == 0

    def test_continues_second_site_if_first_fails(self, tmp_path):
        """_deploy_portrait_to_sites continues to creed even if kytranempowerment deploy fails."""
        from tools.media_studio.services.portrait_service import _deploy_portrait_to_sites

        for domain_dir in ("kytranempowerment", "creed"):
            d = tmp_path / domain_dir / "assets" / "portraits"
            d.mkdir(parents=True)
            (d / "portrait.jpg").write_bytes(b"fake jpeg")

        failed = MagicMock()
        failed.success = False
        failed.error = "Hostinger 500"
        ok = MagicMock()
        ok.success = True

        with patch(
            "tools.media_studio.services.portrait_service.run_deploy_pipeline",
            side_effect=[failed, ok],
        ) as mock_deploy, patch(
            "tools.media_studio.services.portrait_service._PORTRAIT_DEPLOY_SITES",
            [
                {"domain": "kytranempowerment.com", "source_path": str(tmp_path / "kytranempowerment")},
                {"domain": "creed-ai.org", "source_path": str(tmp_path / "creed")},
            ],
        ):
            _deploy_portrait_to_sites("portrait", "TEST_AGENT")

        assert mock_deploy.call_count == 2


class TestApproveCanonicalWiring:
    def test_approve_canonical_calls_sync_all_site_thumbs(self):
        """approve_canonical calls _sync_all_site_thumbs instead of _sync_website_thumb directly."""
        import tools.media_studio.services.portrait_service as ps

        fake_media = {
            "file_path": "/static/media/images/2026-04-29/test.png",
            "thumbnail_path": None,
            "seed": "42",
            "metadata": {},
        }

        with patch.object(ps, "get_db_cursor") as mock_db, patch.object(ps, "agent_service") as _mock_svc, patch.object(
            ps, "_sync_all_site_thumbs", return_value=(None, [])
        ) as mock_sync, patch.object(ps, "_deploy_portrait_to_sites") as _mock_deploy:

            mock_cur = MagicMock()
            mock_cur.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur))
            mock_cur.__exit__ = MagicMock(return_value=False)
            mock_cur.fetchone.return_value = fake_media
            mock_db.return_value = mock_cur

            ps.approve_canonical(agent_id=1, media_id=99)

        mock_sync.assert_called_once_with(fake_media["file_path"])

    def test_thread_not_started_when_sync_returns_empty(self):
        """No background thread starts when _sync_all_site_thumbs returns (None, [])."""
        import tools.media_studio.services.portrait_service as ps

        fake_media = {
            "file_path": "/static/media/images/2026-04-29/test.png",
            "thumbnail_path": None,
            "seed": None,
            "metadata": {},
        }

        with patch.object(ps, "get_db_cursor") as mock_db, patch.object(ps, "agent_service"), patch.object(
            ps, "_sync_all_site_thumbs", return_value=(None, [])
        ), patch("threading.Thread") as mock_thread:

            mock_cur = MagicMock()
            mock_cur.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur))
            mock_cur.__exit__ = MagicMock(return_value=False)
            mock_cur.fetchone.return_value = fake_media
            mock_db.return_value = mock_cur

            ps.approve_canonical(agent_id=1, media_id=99)

        mock_thread.assert_not_called()

    def test_approve_canonical_returns_sites_queued(self):
        """approve_canonical return dict includes sites_queued from _sync_all_site_thumbs."""
        import tools.media_studio.services.portrait_service as ps

        fake_media = {
            "file_path": "/static/media/images/2026-04-29/test.png",
            "thumbnail_path": None,
            "seed": None,
            "metadata": {},
        }
        fake_agent = {"name": "TEST_AGENT"}

        with patch.object(ps, "get_db_cursor") as mock_db, patch.object(ps, "agent_service"), patch.object(
            ps, "_sync_all_site_thumbs", return_value=("/tmp/test.jpg", ["kytranempowerment.com", "creed-ai.org"])
        ), patch.object(ps, "_deploy_portrait_to_sites"), patch("threading.Thread") as mock_thread:

            # Two separate DB calls: first returns media, second returns agent name
            mock_cur_media = MagicMock()
            mock_cur_media.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur_media))
            mock_cur_media.__exit__ = MagicMock(return_value=False)
            mock_cur_media.fetchone.return_value = fake_media

            mock_cur_agent = MagicMock()
            mock_cur_agent.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur_agent))
            mock_cur_agent.__exit__ = MagicMock(return_value=False)
            mock_cur_agent.fetchone.return_value = fake_agent

            mock_db.side_effect = [mock_cur_media, mock_cur_agent]
            mock_thread.return_value.start = MagicMock()

            result = ps.approve_canonical(agent_id=1, media_id=99)

        assert result.get("sites_queued") == ["kytranempowerment.com", "creed-ai.org"]
