"""#6653 Phase 4 — the cockpit page: both layouts from one template; the JS never
renders server text with innerHTML."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "templates" / "cockpit.html").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "css" / "cockpit.css").read_text(encoding="utf-8")

IDS = ["pane-crew", "pane-builder", "pane-approvals", "ck-tabs", "ck-search", "ck-chips", "ck-roster", "ck-more",
       "ck-agent", "ck-agent-close", "ck-hire-open", "ck-hire", "ck-provider", "ck-model", "ck-prompt", "ck-system",
       "ck-run", "ck-jobs", "ck-approvals", "ck-strip", "ck-toast"]


def test_template_has_every_id_the_js_binds():
    missing = [i for i in IDS if f'id="{i}"' not in HTML]
    assert not missing, missing


def test_template_loads_cockpit_assets_and_not_the_chat_stylesheet():
    # the chat body rule is overflow:hidden and pins the cockpit at scrollY 0 — must NOT be linked
    assert '/static/css/archie-chat.css' not in HTML
    assert '/static/css/cockpit.css' in HTML and '/static/js/cockpit.js' in HTML
    assert 'name="viewport"' in HTML


def test_css_has_the_three_breakpoints_and_the_desktop_grid():
    assert "grid-template-columns: 320px 1fr 400px" in CSS
    for bp in ("480px", "768px", "1024px"):
        assert f"(max-width: {bp})" in CSS or f"(min-width: {bp})" in CSS, bp


def test_no_phantom_state_classes():
    assert "sc-live" not in HTML + CSS and "sc-static" not in HTML + CSS


JS = (ROOT / "static" / "js" / "cockpit.js").read_text(encoding="utf-8")


def test_js_never_renders_server_text_with_innerhtml():
    assert ".innerHTML" not in JS and "insertAdjacentHTML" not in JS and "outerHTML" not in JS


def test_js_binds_the_cockpit_routes_and_polls_every_5s():
    for route in ("/api/cockpit/agents", "/api/cockpit/agents/create", "/api/cockpit/build/providers", "/api/cockpit/build/run", "/api/cockpit/build/runs", "/api/approvals/pending"):
        assert route in JS, route
    assert "POLL_MS = 5000" in JS


def test_js_requires_the_typed_name_before_decommission():
    assert "decommissioned" in JS
    assert "type the agent's name" in JS.lower()  # the confirm prompt (double-quoted in the JS so the apostrophe is literal)


def test_chat_header_links_to_the_cockpit():
    chat = (ROOT / "templates" / "chat.html").read_text(encoding="utf-8")
    assert "/cockpit" in chat


def test_js_reset_reload_rewinds_the_roster_offset():
    # a reload after an action/decision must start from page 1 — "Load more" left offset at 50
    assert "if (reset) roster.offset = 0;" in JS


def test_js_keeps_polling_after_a_failed_jobs_poll():
    # spec §7: a poll error shows once and polling continues
    assert "jobsErrToasted" in JS and "const ACTIVE = new Set(['pending', 'pending_approval', 'running', 'queued'])" in JS


def test_js_polls_the_roster_while_a_hire_is_pending():
    assert "hirePending" in JS and "if (hirePending) loadRoster(true)" in JS


def test_css_hides_tabs_and_shows_the_strip_from_tablet_up():
    tablet = CSS.split("@media (min-width: 768px)")[1].split("@media (min-width: 1024px)")[0]
    assert ".ck-tabs { display: none; }" in tablet and "#pane-approvals { display: none !important; }" in tablet
