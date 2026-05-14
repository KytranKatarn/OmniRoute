import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from unittest.mock import MagicMock


def _make_page(texts: list) -> MagicMock:
    page = MagicMock()
    page.goto.return_value = None
    page.wait_for_selector.return_value = None
    els = [MagicMock(inner_text=MagicMock(return_value=t)) for t in texts]
    page.query_selector_all.return_value = els
    return page


def test_web_scrape_extracts_text():
    from skills.web_scrape import run
    page = _make_page(["Tender A", "Tender B", "Tender C"])
    result = run(
        page=page,
        url="https://example.com",
        params={"selectors": {"tenders": "tr.tender"}},
        job_id=1,
    )
    assert result["data"]["tenders"] == ["Tender A", "Tender B", "Tender C"]
    assert result["auto_approve"] is True
    assert "findings" in result


def test_web_scrape_respects_max_items():
    from skills.web_scrape import run
    page = _make_page([f"Item {i}" for i in range(10)])
    result = run(
        page=page,
        url="https://example.com",
        params={"selectors": {"items": "li"}, "max_items": 3},
        job_id=2,
    )
    assert len(result["data"]["items"]) == 3


def test_ux_audit_returns_screenshots_and_not_auto_approved():
    from unittest.mock import patch
    from skills.ux_audit import run

    page = MagicMock()
    page.title.return_value = "Test Site"
    page.query_selector_all.return_value = [
        MagicMock(inner_text=MagicMock(return_value="Welcome"))
    ]

    with patch("skills.ux_audit.save_screenshot", return_value="1/desktop_homepage.png"), \
         patch("skills.ux_audit.screenshot_entry",
               return_value={"step": "desktop_homepage",
                              "path": "1/desktop_homepage.png", "caption": "Desktop homepage"}):
        result = run(page=page, url="https://example.com", params={}, job_id=1)

    assert result["auto_approve"] is False
    assert len(result["screenshots"]) >= 1
    assert "Test Site" in result["findings"]
    assert result["data"]["title"] == "Test Site"


def test_procurement_sync_returns_tenders_auto_approved():
    from unittest.mock import patch
    from skills.procurement_sync import run

    page = MagicMock()
    row1 = MagicMock()
    row1.inner_text.return_value = "AI Services | PSPC | Deadline: 2026-06-01"
    link1 = MagicMock()
    link1.get_attribute.return_value = "/en/tender/12345"
    row1.query_selector_all.return_value = [link1]
    page.query_selector_all.return_value = [row1]
    page.query_selector.return_value = None  # no next-page button

    with patch("skills.procurement_sync.save_screenshot", return_value="1/tenders_page_1.png"), \
         patch("skills.procurement_sync.screenshot_entry",
               return_value={"step": "tenders_page_1", "path": "1/tenders_page_1.png", "caption": ""}):
        result = run(page=page, url="https://canadabuys.canada.ca", params={"max_pages": 1}, job_id=1)

    assert result["auto_approve"] is True
    assert len(result["data"]["tenders"]) >= 1
    assert result["data"]["tenders"][0]["text"] == "AI Services | PSPC | Deadline: 2026-06-01"
