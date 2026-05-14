import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from unittest.mock import MagicMock, patch


def _page(texts=None, title="Test"):
    page = MagicMock()
    page.title.return_value = title
    page.goto.return_value = None
    page.reload.return_value = None
    page.wait_for_load_state.return_value = None
    page.wait_for_selector.return_value = None
    if texts is not None:
        els = [MagicMock(inner_text=MagicMock(return_value=t)) for t in texts]
        page.query_selector_all.return_value = els
    else:
        page.query_selector_all.return_value = []
    page.query_selector.return_value = None
    return page


def _assert_valid_result(result):
    assert isinstance(result, dict)
    assert "data" in result
    assert "screenshots" in result
    assert "network_log" in result
    assert "findings" in result
    assert "auto_approve" in result
    assert isinstance(result["auto_approve"], bool)


# TASK 1

def test_multi_page_scrape_returns_items_auto_approved():
    from skills.multi_page_scrape import run
    page = _page(["Row 1", "Row 2"])
    result = run(page=page, url="https://example.com", params={"selectors": {"rows": "tr"}, "max_pages": 1}, job_id=1)
    _assert_valid_result(result)
    assert result["auto_approve"] is True
    assert "rows" in result["data"]


def test_authenticated_fetch_returns_content_auto_approved():
    from skills.authenticated_fetch import run
    page = _page(["Article content here"])
    page.query_selector.return_value = MagicMock()
    result = run(
        page=page,
        url="https://example.com/article",
        params={
            "login_url": "https://example.com/login",
            "username": "user@example.com",
            "password": "secret",
            "username_selector": "#email",
            "password_selector": "#password",
            "submit_selector": "button[type=submit]",
            "content_selector": "article",
        },
        job_id=2,
    )
    _assert_valid_result(result)
    assert result["auto_approve"] is True


def test_search_scrape_returns_results_auto_approved():
    from skills.search_scrape import run
    page = _page(["Result One", "Result Two"])
    result = run(
        page=page,
        url="https://www.google.com/search?q=test",
        params={"result_selector": "h3", "max_results": 10},
        job_id=3,
    )
    _assert_valid_result(result)
    assert result["auto_approve"] is True
    assert "results" in result["data"]


# TASK 2

def test_site_change_monitor_detects_change():
    from skills.site_change_monitor import run
    page = MagicMock()
    page.goto.return_value = None
    el = MagicMock()
    el.inner_text.return_value = "New content here"
    page.query_selector_all.return_value = [el]
    result = run(page=page, url="https://example.com", params={"content_selector": "main", "stored_hash": "old_hash_abc"}, job_id=4)
    _assert_valid_result(result)
    assert result["auto_approve"] is True
    assert "changed" in result["data"]
    assert "current_hash" in result["data"]


def test_pdf_extract_returns_text_auto_approved():
    from skills.pdf_extract import run
    page = MagicMock()
    page.goto.return_value = None
    link = MagicMock()
    link.get_attribute.return_value = "https://example.com/doc.pdf"
    page.query_selector_all.return_value = [link]
    with patch("skills.pdf_extract._download_and_extract", return_value="PDF text content"):
        result = run(page=page, url="https://example.com", params={"pdf_link_selector": "a[href$='.pdf']"}, job_id=5)
    _assert_valid_result(result)
    assert result["auto_approve"] is True


def test_document_download_returns_metadata():
    from skills.document_download import run
    page = MagicMock()
    page.goto.return_value = None
    page.query_selector.return_value = MagicMock()
    with patch("skills.document_download._trigger_download", return_value={"filename": "report.xlsx", "size_bytes": 12345}):
        result = run(page=page, url="https://example.com", params={"download_selector": "a.download-btn"}, job_id=6)
    _assert_valid_result(result)
    assert result["auto_approve"] is True


# TASK 3

def test_login_test_captures_flow_needs_review():
    from skills.login_test import run
    page = _page()
    with patch("skills.login_test.save_screenshot", return_value="7/login_form.png"), \
         patch("skills.login_test.screenshot_entry", return_value={"step": "login_form", "path": "7/login_form.png", "caption": "Login form"}):
        result = run(page=page, url="https://example.com/login",
                     params={"username": "test@example.com", "password": "testpass",
                             "username_selector": "#email", "password_selector": "#password",
                             "submit_selector": "button[type=submit]"}, job_id=7)
    _assert_valid_result(result)
    assert result["auto_approve"] is False
    assert len(result["screenshots"]) >= 1


def test_signup_flow_captures_registration_needs_review():
    from skills.signup_flow import run
    page = _page()
    with patch("skills.signup_flow.save_screenshot", return_value="8/signup_form.png"), \
         patch("skills.signup_flow.screenshot_entry", return_value={"step": "signup_form", "path": "8/signup_form.png", "caption": "Signup"}):
        result = run(page=page, url="https://example.com/signup",
                     params={"fields": {"#name": "Test User", "#email": "test@example.com"},
                             "submit_selector": "button[type=submit]"}, job_id=8)
    _assert_valid_result(result)
    assert result["auto_approve"] is False


def test_network_inspect_captures_requests_needs_review():
    from skills.network_inspect import run
    page = _page()
    page.on = MagicMock()
    result = run(page=page, url="https://example.com", params={}, job_id=9)
    _assert_valid_result(result)
    assert result["auto_approve"] is False
    assert "requests_captured" in result["data"]


# TASK 4

def test_accessibility_check_returns_report_needs_review():
    from skills.accessibility_check import run
    page = _page()
    page.evaluate.return_value = {"images_missing_alt": 2, "inputs_missing_label": 1, "headings": ["h1", "h2"], "has_h1": True, "h1_count": 1, "links_no_text": 0, "html_lang": "en"}
    result = run(page=page, url="https://example.com", params={}, job_id=10)
    _assert_valid_result(result)
    assert result["auto_approve"] is False
    assert "issues" in result["data"]


def test_seo_snapshot_returns_metadata_needs_review():
    from skills.seo_snapshot import run
    page = _page(title="My Site")
    page.evaluate.return_value = {"title": "My Site", "meta_description": "A site", "h1": ["Welcome"], "canonical": "/", "robots": "index,follow", "og_title": "My Site", "og_description": None, "og_image": None, "h2": [], "images_count": 5, "images_with_alt": 3, "links_internal": 10, "links_external": 2, "schema_types": []}
    result = run(page=page, url="https://example.com", params={}, job_id=11)
    _assert_valid_result(result)
    assert result["auto_approve"] is False
    assert "title" in result["data"] or "seo" in result["data"]


def test_broken_link_check_returns_link_report():
    from skills.broken_link_check import run
    page = _page()
    link1 = MagicMock()
    link1.get_attribute.return_value = "https://example.com/good"
    link2 = MagicMock()
    link2.get_attribute.return_value = "https://example.com/bad"
    page.query_selector_all.return_value = [link1, link2]
    with patch("skills.broken_link_check._check_url", return_value=200):
        result = run(page=page, url="https://example.com", params={"max_links": 5}, job_id=12)
    _assert_valid_result(result)
    assert result["auto_approve"] is False
    assert "links_checked" in result["data"]


# TASK 5

def test_screenshot_diff_returns_comparison_needs_review():
    from skills.screenshot_diff import run
    page = _page()
    with patch("skills.screenshot_diff.save_screenshot", return_value="13/current.png"), \
         patch("skills.screenshot_diff.screenshot_entry", return_value={"step": "current", "path": "13/current.png", "caption": "Current"}), \
         patch("skills.screenshot_diff._compare_images", return_value=0.95):
        result = run(page=page, url="https://example.com", params={"baseline_path": "/tmp/baseline.png", "threshold": 0.9}, job_id=13)
    _assert_valid_result(result)
    assert result["auto_approve"] is False
    assert "similarity" in result["data"]


def test_form_audit_returns_form_analysis_needs_review():
    from skills.form_audit import run
    page = _page()
    page.evaluate.return_value = [{"action": "/submit", "method": "POST", "field_count": 3, "has_csrf": True, "fields": []}]
    result = run(page=page, url="https://example.com", params={}, job_id=14)
    _assert_valid_result(result)
    assert result["auto_approve"] is False
    assert "forms" in result["data"]


def test_competitor_snapshot_captures_pages_needs_review():
    from skills.competitor_snapshot import run
    page = _page(title="Competitor Site")
    page.evaluate.return_value = {"tech": [], "jobs_links": 0, "meta_generator": None}
    with patch("skills.competitor_snapshot.save_screenshot", return_value="15/homepage.png"), \
         patch("skills.competitor_snapshot.screenshot_entry", return_value={"step": "homepage", "path": "15/homepage.png", "caption": "Homepage"}):
        result = run(page=page, url="https://competitor.com", params={"pages": ["homepage"]}, job_id=15)
    _assert_valid_result(result)
    assert result["auto_approve"] is False


# TASK 6

def test_ancestry_research_returns_records_auto_approved():
    from skills.ancestry_research import run
    page = _page(["John Smith b.1852"])
    with patch("skills.ancestry_research.save_screenshot", return_value="16/results.png"), \
         patch("skills.ancestry_research.screenshot_entry", return_value={"step": "results", "path": "16/results.png", "caption": "Results"}):
        result = run(page=page, url="https://search.ancestry.com/search/", params={"username": "u@e.com", "password": "pass", "search_name": "John Smith"}, job_id=16)
    _assert_valid_result(result)
    assert result["auto_approve"] is True


def test_crm_enrich_returns_profile_auto_approved():
    from skills.crm_enrich import run
    page = _page()
    page.evaluate.return_value = {"name": "Jane Doe", "headline": "CEO", "company": "Acme", "location": "Montreal", "followers": "500+", "about": None}
    result = run(page=page, url="https://www.linkedin.com/in/janedoe/", params={}, job_id=17)
    _assert_valid_result(result)
    assert result["auto_approve"] is True
    assert "profile" in result["data"]


def test_contact_harvest_extracts_contacts_auto_approved():
    from skills.contact_harvest import run
    page = _page()
    page.evaluate.return_value = {"emails": ["info@example.com"], "phones": ["514-555-1234"], "addresses": [], "team": []}
    result = run(page=page, url="https://example.com", params={}, job_id=18)
    _assert_valid_result(result)
    assert result["auto_approve"] is True
    assert "emails" in result["data"]


def test_social_profile_check_returns_snapshot_auto_approved():
    from skills.social_profile_check import run
    page = _page(title="@testuser on Twitter")
    page.evaluate.return_value = {"name": "Test User", "bio": "Bio here", "followers": "1,234", "following": "567"}
    result = run(page=page, url="https://twitter.com/testuser", params={"platform": "twitter"}, job_id=19)
    _assert_valid_result(result)
    assert result["auto_approve"] is True
    assert "profile" in result["data"]


def test_price_monitor_extracts_prices_auto_approved():
    from skills.price_monitor import run
    price_el = MagicMock()
    price_el.inner_text.return_value = "$99.99"
    title_el = MagicMock()
    title_el.inner_text.return_value = "Widget Pro"
    page = _page()
    page.query_selector_all.side_effect = lambda sel: [price_el] if "price" in sel.lower() else ([title_el] if sel else [])
    result = run(page=page, url="https://example.com/product", params={"price_selector": ".price", "title_selector": "h1"}, job_id=20)
    _assert_valid_result(result)
    assert result["auto_approve"] is True
    assert "items" in result["data"]
