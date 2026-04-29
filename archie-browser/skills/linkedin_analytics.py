"""LinkedIn analytics — reads profile and post performance metrics."""
import os
from datetime import datetime

SKILL_NAME = "linkedin_analytics"
PLATFORMS = ["linkedin"]

_SCREENSHOTS_DIR = os.getenv("SCREENSHOTS_DIR", "/tmp/browser_screenshots")
os.makedirs(_SCREENSHOTS_DIR, exist_ok=True)


def _screenshot(page, name):
    path = f"{_SCREENSHOTS_DIR}/{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    page.screenshot(path=path)
    return path


def execute(page, params: dict) -> dict:
    mode = params.get("mode", "profile")  # profile or posts

    if mode == "posts":
        page.goto("https://www.linkedin.com/analytics/creator/content/?metricType=IMPRESSIONS&timeRange=past_28_days", wait_until="domcontentloaded")
    else:
        page.goto("https://www.linkedin.com/in/me/", wait_until="domcontentloaded")
    page.wait_for_timeout(4000)
    _screenshot(page, "analytics_loaded")

    if mode == "profile":
        # Extract profile analytics from the "Analytics" section on own profile
        analytics = page.evaluate("""() => {
            const data = {};

            // Profile views
            const viewsEl = document.querySelector(
                'a[href*="profileViewers"], .analytics-module .artdeco-stat'
            );
            if (viewsEl) data.profile_views = viewsEl.textContent.trim();

            // Post impressions
            const impEl = document.querySelector(
                'a[href*="postImpressions"], .analytics-module'
            );
            if (impEl) data.post_impressions = impEl.textContent.trim();

            // Search appearances
            const searchEl = document.querySelector(
                'a[href*="searchAppearances"]'
            );
            if (searchEl) data.search_appearances = searchEl.textContent.trim();

            // Followers count
            const follEl = document.querySelector(
                '.pv-top-card--list .t-black--light, .follower-count'
            );
            if (follEl) data.followers = follEl.textContent.trim();

            // Try analytics section directly
            const analyticsSection = document.querySelector('.pv-profile-section__analytics-results');
            if (analyticsSection) {
                data.analytics_raw = analyticsSection.textContent.trim().substring(0, 500);
            }

            return data;
        }""")
    else:
        # Post analytics page
        analytics = page.evaluate(f"""() => {{
            const posts = [];
            const rows = document.querySelectorAll(
                '.analytics-table__row, tr[data-test-analytics-table-row]'
            );
            let count = 0;
            for (const row of rows) {{
                if (count >= 10) break;
                const cells = row.querySelectorAll('td');
                if (cells.length >= 3) {{
                    posts.push({{
                        post: cells[0] ? cells[0].textContent.trim().substring(0, 100) : '',
                        impressions: cells[1] ? cells[1].textContent.trim() : '',
                        engagements: cells[2] ? cells[2].textContent.trim() : '',
                    }});
                    count++;
                }}
            }}
            return {{ posts }};
        }}""")

    return {
        "success": True,
        "mode": mode,
        "analytics": analytics,
        "screenshot_path": _screenshot(page, "analytics_result"),
    }
