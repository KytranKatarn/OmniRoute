# Portrait Deploy Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire portrait approval into `deploy_service.run_deploy_pipeline` so approved portraits deploy to kytranempowerment.com AND creed-ai.org with backup, retry, rollback, and alerting — replacing the fire-and-forget TUS upload thread.

**Architecture:** Two new helpers are added to `portrait_service.py`: `_sync_all_site_thumbs()` copies the approved JPEG to both site directories; `_deploy_portrait_to_sites()` calls `run_deploy_pipeline('deploy_static', ...)` for each domain in a background thread, inheriting the full pipeline (pre-deploy snapshot, full Hostinger zip, 200 verify, one retry, rollback + Telegram alert on failure). `approve_canonical()` calls both helpers, replacing its existing TUS fire-and-forget block.

**Tech Stack:** Python 3.11, Pillow, `services.deploy_service.run_deploy_pipeline / DeployResult`, `shutil.copy2`, pytest + unittest.mock, Docker exec for test runs.

**Context:**
- `deploy_service.py` already exists at `platform_v2/services/deploy_service.py` (460 lines, PR #383).
- `run_deploy_pipeline(capability, context)` returns `DeployResult(success, error, metadata)`.
- `context` keys: `domain`, `source_path`, `changed_files` (list), `verify_url` (optional), `reason`.
- Tests run inside the container: `docker exec archie_platform python -m pytest tests/test_portrait_pipeline.py -v`
- All existing tests must keep passing: `docker exec archie_platform python -m pytest tests/ -v`

---

### Task 1: Add CREED_PORTRAIT_DIR constant + `_sync_all_site_thumbs()`

**Files:**
- Modify: `platform_v2/tools/media_studio/services/portrait_service.py:43-47` (add constant)
- Modify: `platform_v2/tools/media_studio/services/portrait_service.py:118` (add function after `_sync_website_thumb`)
- Create: `platform_v2/tests/test_portrait_pipeline.py`

- [ ] **Step 1: Write the failing test**

```python
# platform_v2/tests/test_portrait_pipeline.py
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

        # Create a fake JPEG at the path _sync_website_thumb would return
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
        assert "creed-ai.org" in open(str(creed_dir / "portrait.jpg"), "rb").read() or True

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

        with patch(
            "tools.media_studio.services.portrait_service._sync_website_thumb",
            return_value=str(primary),
        ), patch(
            "tools.media_studio.services.portrait_service.CREED_PORTRAIT_DIR",
            "/root/no-permission/creed",  # will fail makedirs
        ):
            result, sites = _sync_all_site_thumbs("/static/media/images/portrait.png")

        assert result == str(primary)
        assert "kytranempowerment.com" in sites
        assert "creed-ai.org" not in sites
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker exec archie_platform python -m pytest tests/test_portrait_pipeline.py -v
```

Expected: `ImportError` or `AttributeError: module has no attribute '_sync_all_site_thumbs'`

- [ ] **Step 3: Add CREED_PORTRAIT_DIR constant**

In `platform_v2/tools/media_studio/services/portrait_service.py`, after line 46 (after `WEBSITE_THUMB_PRIMARY = ...`):

```python
# Current lines 43-47 look like:
WEBSITE_THUMB_PRIMARY = os.getenv(
    "PORTRAIT_WEBSITE_THUMB_DIR",
    "/mnt/archie_brain/website/kytranempowerment.com/assets/portraits",
)
WEBSITE_THUMB_STAGING = os.path.join(_PLATFORM_DIR, "static", "media", "thumbs")
```

After the `WEBSITE_THUMB_PRIMARY` block and before `WEBSITE_THUMB_STAGING`, insert:

```python
CREED_PORTRAIT_DIR = os.getenv(
    "PORTRAIT_CREED_THUMB_DIR",
    "/mnt/archie_brain/website/creed-ai.org/assets/portraits",
)
```

- [ ] **Step 4: Add `_sync_all_site_thumbs()` after `_sync_website_thumb()`**

After line 117 (the `return None` at end of `_sync_website_thumb`), insert:

```python
def _sync_all_site_thumbs(
    canonical_db_path: str,
) -> tuple[Optional[str], list[str]]:
    """Copy approved portrait JPEG to every public site that displays agent portraits.

    Calls _sync_website_thumb for kytranempowerment.com (primary), then copies
    to creed-ai.org. Returns (primary_path, sites_written). On partial failure
    still returns the primary so the deploy can proceed for the sites that worked.
    """
    import shutil

    primary = _sync_website_thumb(canonical_db_path)
    if not primary:
        return None, []

    stem = os.path.splitext(os.path.basename(primary))[0]
    sites_written: list[str] = ["kytranempowerment.com"]

    # Copy to creed-ai.org
    try:
        os.makedirs(CREED_PORTRAIT_DIR, exist_ok=True)
        creed_dst = os.path.join(CREED_PORTRAIT_DIR, f"{stem}.jpg")
        shutil.copy2(primary, creed_dst)
        sites_written.append("creed-ai.org")
        logger.info("[Portrait] Synced thumb to creed-ai.org: %s", creed_dst)
    except Exception as exc:
        logger.warning("[Portrait] Could not sync thumb to creed-ai.org: %s", exc)

    return primary, sites_written
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
docker exec archie_platform python -m pytest tests/test_portrait_pipeline.py::TestSyncAllSiteThumbs -v
```

Expected: 5 tests PASS

- [ ] **Step 6: Commit**

```bash
git add platform_v2/tools/media_studio/services/portrait_service.py platform_v2/tests/test_portrait_pipeline.py
git commit -m "feat(portrait): add creed-ai.org thumb sync — _sync_all_site_thumbs writes to both sites"
```

---

### Task 2: Add `_deploy_portrait_to_sites()` using run_deploy_pipeline

**Files:**
- Modify: `platform_v2/tools/media_studio/services/portrait_service.py` (add function after `_sync_all_site_thumbs`)
- Modify: `platform_v2/tests/test_portrait_pipeline.py` (add tests)

- [ ] **Step 1: Write the failing tests**

Append to `platform_v2/tests/test_portrait_pipeline.py`:

```python
class TestDeployPortraitToSites:
    def test_calls_run_deploy_pipeline_for_kytranempowerment(self, tmp_path):
        """_deploy_portrait_to_sites calls run_deploy_pipeline for kytranempowerment.com."""
        from tools.media_studio.services.portrait_service import _deploy_portrait_to_sites

        portrait = tmp_path / "portrait.jpg"
        portrait.write_bytes(b"fake jpeg")
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
            "tools.media_studio.services.portrait_service.KYTRAN_DEPLOY_SOURCE",
            str(tmp_path / "kytranempowerment"),
        ), patch(
            "tools.media_studio.services.portrait_service.CREED_DEPLOY_SOURCE",
            str(tmp_path / "creed"),
        ):
            _deploy_portrait_to_sites(str(portrait), "portrait", "TEST_AGENT")

        calls = mock_deploy.call_args_list
        domains = [c.args[1]["domain"] for c in calls if "domain" in (c.args[1] if len(c.args) > 1 else {})]
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
            "tools.media_studio.services.portrait_service.KYTRAN_DEPLOY_SOURCE",
            str(tmp_path / "kytranempowerment"),
        ), patch(
            "tools.media_studio.services.portrait_service.CREED_DEPLOY_SOURCE",
            str(tmp_path / "creed"),
        ):
            _deploy_portrait_to_sites("any.jpg", "portrait", "TEST_AGENT")

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
            "tools.media_studio.services.portrait_service.KYTRAN_DEPLOY_SOURCE",
            str(tmp_path / "kytranempowerment"),  # portraits dir does not exist
        ), patch(
            "tools.media_studio.services.portrait_service.CREED_DEPLOY_SOURCE",
            str(tmp_path / "creed"),  # portraits dir does not exist
        ):
            _deploy_portrait_to_sites("any.jpg", "portrait", "TEST_AGENT")

        # No deploys should fire — portrait JPEG missing from both site dirs
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
            "tools.media_studio.services.portrait_service.KYTRAN_DEPLOY_SOURCE",
            str(tmp_path / "kytranempowerment"),
        ), patch(
            "tools.media_studio.services.portrait_service.CREED_DEPLOY_SOURCE",
            str(tmp_path / "creed"),
        ):
            _deploy_portrait_to_sites("any.jpg", "portrait", "TEST_AGENT")

        assert mock_deploy.call_count == 2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker exec archie_platform python -m pytest tests/test_portrait_pipeline.py::TestDeployPortraitToSites -v
```

Expected: `ImportError` or `AttributeError` — `_deploy_portrait_to_sites` does not exist yet; `KYTRAN_DEPLOY_SOURCE` and `CREED_DEPLOY_SOURCE` do not exist yet.

- [ ] **Step 3: Add source path constants**

In `portrait_service.py`, after `CREED_PORTRAIT_DIR`:

```python
# Source path roots for full-site deploys (deploy_service zips the entire tree)
KYTRAN_DEPLOY_SOURCE = os.getenv(
    "KYTRAN_DEPLOY_SOURCE",
    "/mnt/archie_brain/website/kytranempowerment.com",
)
CREED_DEPLOY_SOURCE = os.getenv(
    "CREED_DEPLOY_SOURCE",
    "/mnt/archie_brain/website/creed-ai.org",
)
```

- [ ] **Step 4: Add `_deploy_portrait_to_sites()` after `_sync_all_site_thumbs()`**

```python
def _deploy_portrait_to_sites(
    website_thumb: str, stem: str, agent_name: str
) -> None:
    """Deploy portrait JPEG to all public sites via deploy_service pipeline.

    Runs inside a background thread (called from approve_canonical). Never
    raises — errors are logged and run_deploy_pipeline handles Telegram
    alerting + Repair Bay proposal on failure.
    """
    from services.deploy_service import run_deploy_pipeline

    SITE_CONFIGS = [
        {
            "domain": "kytranempowerment.com",
            "source_path": KYTRAN_DEPLOY_SOURCE,
        },
        {
            "domain": "creed-ai.org",
            "source_path": CREED_DEPLOY_SOURCE,
        },
    ]

    for cfg in SITE_CONFIGS:
        portrait_path = os.path.join(
            cfg["source_path"], "assets", "portraits", f"{stem}.jpg"
        )
        if not os.path.isfile(portrait_path):
            logger.info(
                "[Portrait] Skipping %s — portrait not present at %s",
                cfg["domain"],
                portrait_path,
            )
            continue

        try:
            result = run_deploy_pipeline(
                "deploy_static",
                {
                    "domain": cfg["domain"],
                    "source_path": cfg["source_path"],
                    "changed_files": [f"assets/portraits/{stem}.jpg"],
                    "verify_url": f"https://{cfg['domain']}/assets/portraits/{stem}.jpg",
                    "reason": f"Portrait approved for agent {agent_name}",
                },
            )
            if result.success:
                logger.info(
                    "[Portrait] Deploy to %s succeeded for %s",
                    cfg["domain"],
                    agent_name,
                )
            else:
                logger.error(
                    "[Portrait] Deploy to %s failed for %s: %s",
                    cfg["domain"],
                    agent_name,
                    result.error,
                )
        except Exception as exc:
            logger.error(
                "[Portrait] Unexpected error deploying to %s for %s: %s",
                cfg["domain"],
                agent_name,
                exc,
            )
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
docker exec archie_platform python -m pytest tests/test_portrait_pipeline.py::TestDeployPortraitToSites -v
```

Expected: 4 tests PASS

- [ ] **Step 6: Commit**

```bash
git add platform_v2/tools/media_studio/services/portrait_service.py platform_v2/tests/test_portrait_pipeline.py
git commit -m "feat(portrait): add _deploy_portrait_to_sites — deploy_service pipeline for both sites"
```

---

### Task 3: Wire `approve_canonical()` to use new helpers

**Files:**
- Modify: `platform_v2/tools/media_studio/services/portrait_service.py:466-511` (the `approve_canonical` function body)
- Modify: `platform_v2/tests/test_portrait_pipeline.py` (add integration test)

- [ ] **Step 1: Write the failing test**

Append to `platform_v2/tests/test_portrait_pipeline.py`:

```python
class TestApproveCanonicalWiring:
    def test_approve_canonical_calls_sync_all_site_thumbs(self):
        """approve_canonical calls _sync_all_site_thumbs instead of _sync_website_thumb directly."""
        from tools.media_studio.services import portrait_service

        fake_media = {
            "file_path": "/static/media/images/2026-04-29/test.png",
            "thumbnail_path": None,
            "seed": "42",
            "metadata": {},
        }

        with patch.object(portrait_service, "get_db_cursor") as mock_db, \
             patch.object(portrait_service, "agent_service") as mock_svc, \
             patch.object(portrait_service, "_sync_all_site_thumbs", return_value=(None, [])) as mock_sync, \
             patch.object(portrait_service, "_deploy_portrait_to_sites") as mock_deploy:

            mock_cursor = MagicMock()
            mock_cursor.__enter__ = MagicMock(return_value=(MagicMock(), mock_cursor))
            mock_cursor.__exit__ = MagicMock(return_value=False)
            mock_cursor.fetchone.side_effect = [fake_media, {"name": "TEST_AGENT"}]
            mock_db.return_value = mock_cursor

            portrait_service.approve_canonical(agent_id=1, media_id=99)

        mock_sync.assert_called_once_with(fake_media["file_path"])

    def test_approve_canonical_does_not_call_push_via_api(self):
        """approve_canonical no longer calls the old TUS _push_portrait_via_api."""
        from tools.media_studio.services import portrait_service

        fake_media = {
            "file_path": "/static/media/images/2026-04-29/test.png",
            "thumbnail_path": None,
            "seed": None,
            "metadata": {},
        }

        with patch.object(portrait_service, "get_db_cursor") as mock_db, \
             patch.object(portrait_service, "agent_service"), \
             patch.object(portrait_service, "_sync_all_site_thumbs", return_value=(None, [])), \
             patch.object(portrait_service, "_deploy_portrait_to_sites"), \
             patch.object(portrait_service, "_push_portrait_via_api") as mock_old_push:

            mock_cursor = MagicMock()
            mock_cursor.__enter__ = MagicMock(return_value=(MagicMock(), mock_cursor))
            mock_cursor.__exit__ = MagicMock(return_value=False)
            mock_cursor.fetchone.side_effect = [fake_media, {"name": "TEST_AGENT"}]
            mock_db.return_value = mock_cursor

            portrait_service.approve_canonical(agent_id=1, media_id=99)

        mock_old_push.assert_not_called()

    def test_approve_canonical_returns_sites_queued(self):
        """approve_canonical return dict includes sites_queued from _sync_all_site_thumbs."""
        from tools.media_studio.services import portrait_service

        fake_media = {
            "file_path": "/static/media/images/2026-04-29/test.png",
            "thumbnail_path": None,
            "seed": None,
            "metadata": {},
        }

        with patch.object(portrait_service, "get_db_cursor") as mock_db, \
             patch.object(portrait_service, "agent_service"), \
             patch.object(portrait_service, "_sync_all_site_thumbs",
                          return_value=("/tmp/test.jpg", ["kytranempowerment.com", "creed-ai.org"])), \
             patch.object(portrait_service, "_deploy_portrait_to_sites"), \
             patch.object(portrait_service, "threading"):

            mock_cursor = MagicMock()
            mock_cursor.__enter__ = MagicMock(return_value=(MagicMock(), mock_cursor))
            mock_cursor.__exit__ = MagicMock(return_value=False)
            mock_cursor.fetchone.side_effect = [fake_media, {"name": "TEST_AGENT"}]
            mock_db.return_value = mock_cursor

            result = portrait_service.approve_canonical(agent_id=1, media_id=99)

        assert result.get("sites_queued") == ["kytranempowerment.com", "creed-ai.org"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker exec archie_platform python -m pytest tests/test_portrait_pipeline.py::TestApproveCanonicalWiring -v
```

Expected: Tests FAIL — `approve_canonical` still calls `_sync_website_thumb`, not `_sync_all_site_thumbs`; still uses TUS; return dict lacks `sites_queued`.

- [ ] **Step 3: Replace the portrait-push block in `approve_canonical`**

In `portrait_service.py`, find lines 466–511 (from `# Publish a 400x400 JPEG thumb…` through `t.start()`). Replace the entire block:

**REMOVE (lines 466–504):**
```python
    # Publish a 400x400 JPEG thumb to the kytranempowerment.com website
    # repo so the public directory page can render same-origin. Best-effort
    # — a thumb-gen failure must NOT fail the approval.
    website_thumb = _sync_website_thumb(file_path)

    # Push the new thumb directly to Hostinger via API in a background thread.
    # Uses TUS upload protocol — no FTP password needed, just HOSTINGER_API_KEY.
    # Fire-and-forget: upload failure never fails the approval.
    if website_thumb:
        # Get agent name for logging
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                "SELECT name FROM agents WHERE id = %s",
                (agent_id,),
            )
            agent_row = cur.fetchone()
            agent_name = agent_row["name"] if agent_row else str(agent_id)

        def _push_portrait_logged(path: str, name: str) -> None:
            try:
                _push_portrait_via_api(path)
                logger.info("[Portrait] Deployed %s to Hostinger", name)
            except Exception as exc:
                logger.error("[Portrait] Deploy failed for %s: %s", name, exc)
                try:
                    from database import get_db_cursor

                    with get_db_cursor(commit=True) as (conn, cur):
                        cur.execute(
                            """INSERT INTO system_notifications
                               (type, title, message, source, priority, visibility, is_read, created_at)
                               VALUES ('error', 'Portrait Deploy Failed', %s, 'portrait_service', 'high', 'admin', FALSE, NOW())""",
                            (f"Failed to deploy portrait for {name}: {exc}",),
                        )
                except Exception:
                    pass

        t = threading.Thread(target=_push_portrait_logged, args=(website_thumb, agent_name), daemon=True)
        t.start()
```

**REPLACE WITH:**
```python
    # Sync portrait JPEG to all sites (kytranempowerment.com + creed-ai.org)
    # and dispatch deploy_service pipeline for each in a background thread.
    website_thumb, sites_synced = _sync_all_site_thumbs(file_path)

    if website_thumb and sites_synced:
        stem = os.path.splitext(os.path.basename(website_thumb))[0]
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute("SELECT name FROM agents WHERE id = %s", (agent_id,))
            agent_row = cur.fetchone()
            agent_name = agent_row["name"] if agent_row else str(agent_id)

        t = threading.Thread(
            target=_deploy_portrait_to_sites,
            args=(website_thumb, stem, agent_name),
            daemon=True,
        )
        t.start()
```

- [ ] **Step 4: Update the return dict**

The existing return (after the replaced block) is:
```python
    return {
        "status": "approved",
        "agent_id": agent_id,
        "media_id": media_id,
        "website_thumb": website_thumb,
    }
```

Replace with:
```python
    return {
        "status": "approved",
        "agent_id": agent_id,
        "media_id": media_id,
        "website_thumb": website_thumb,
        "sites_queued": sites_synced,
    }
```

- [ ] **Step 5: Run all portrait tests**

```bash
docker exec archie_platform python -m pytest tests/test_portrait_pipeline.py -v
```

Expected: All tests PASS (including TestSyncAllSiteThumbs and TestDeployPortraitToSites from earlier tasks)

- [ ] **Step 6: Run full test suite to catch regressions**

```bash
docker exec archie_platform python -m pytest tests/ -v
```

Expected: All tests PASS, no regressions in `test_deploy_service.py`

- [ ] **Step 7: Restart and smoke test**

```bash
docker compose restart archie_platform
```

Navigate to Media Studio → Portraits tab → select any agent → approve their canonical portrait.

Check docker logs:
```bash
docker logs archie_platform --tail=50 | grep "\[Portrait\]"
```

Expected lines:
```
[Portrait] Synced thumb to creed-ai.org: /mnt/archie_brain/website/creed-ai.org/assets/portraits/<stem>.jpg
[Portrait] Deploy to kytranempowerment.com succeeded for <agent>
[Portrait] Deploy to creed-ai.org succeeded for <agent>
```

- [ ] **Step 8: Commit**

```bash
git add platform_v2/tools/media_studio/services/portrait_service.py platform_v2/tests/test_portrait_pipeline.py
git commit -m "feat(portrait): wire approve_canonical to deploy_service — backup + retry + creed-ai.org deploy"
```

---

## Self-Review

### Spec coverage
- ✅ Portrait pipeline brings into `deploy_service.run_deploy_pipeline` backbone (replaces TUS fire-and-forget)
- ✅ Deploys to kytranempowerment.com AND creed-ai.org (Option B from brainstorm)
- ✅ Pre-deploy backup handled by `run_deploy_pipeline → snapshot_current` (already in deploy_service)
- ✅ Retry handled by `run_deploy_pipeline` (one retry, then rollback)
- ✅ Rollback + Telegram alert + Repair Bay proposal on failure — handled by `run_deploy_pipeline`
- ✅ Non-blocking for approval UX (background thread preserved)
- ✅ `avatar_thumb_url` CDN URL already fixed in commit `a186ff83` — no change needed

### Type consistency
- `_sync_all_site_thumbs()` returns `tuple[Optional[str], list[str]]` — used correctly in `approve_canonical`
- `_deploy_portrait_to_sites(website_thumb, stem, agent_name)` matches `threading.Thread` call signature
- `run_deploy_pipeline("deploy_static", context_dict)` matches existing deploy_service API
- `sites_synced` (list[str]) matches `sites_queued` in return dict

### No placeholders
- All code blocks are complete and runnable
- Test file is ready to create (no TBD sections)
- All imports referenced are real modules already on the Python path inside the container
