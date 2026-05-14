import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["SCOUT_POOL_SIZE"] = "2"
os.environ["SCOUT_VPS_SOCKS"] = ""
os.environ["SCOUT_PROXY_URL"] = ""

from unittest.mock import MagicMock, patch


def _patched_pool():
    """Return a BrowserPool with Playwright mocked out.

    Reload the module first so POOL_SIZE picks up the env var, then patch
    sync_playwright on the freshly-reloaded module before constructing the pool.
    The patch stays active (patch.start form) so the BrowserPool object continues
    to hold a mock _pw after this function returns.
    """
    import importlib
    import browser_pool

    # Reload first so the module namespace is fresh (picks up SCOUT_POOL_SIZE=2)
    importlib.reload(browser_pool)

    # Now patch the reloaded module's sync_playwright reference
    patcher = patch("browser_pool.sync_playwright")
    mock_pw_cls = patcher.start()

    mock_pw = MagicMock()
    mock_pw_cls.return_value.start.return_value = mock_pw
    mock_browser = MagicMock()
    mock_pw.chromium.launch.return_value = mock_browser
    mock_ctx = MagicMock()
    mock_browser.new_context.return_value = mock_ctx
    mock_page = MagicMock()
    mock_ctx.new_page.return_value = mock_page

    pool = browser_pool.BrowserPool()
    return pool, mock_ctx, mock_page


def test_pool_initializes_with_correct_size():
    pool, _, _ = _patched_pool()
    assert pool.size == 2
    assert pool.available_count() == 2


def test_claim_and_release_cycle():
    pool, _, mock_page = _patched_pool()
    assert pool.available_count() == 2
    slot_id, page = pool.claim(egress_tier=1)
    assert pool.available_count() == 1
    pool.release(slot_id, page)
    assert pool.available_count() == 2
