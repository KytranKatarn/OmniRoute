"""LinkedIn search — find people by keyword, title, company, or location."""
import os
from datetime import datetime

SKILL_NAME = "linkedin_search"
PLATFORMS = ["linkedin"]

_SCREENSHOTS_DIR = os.getenv("SCREENSHOTS_DIR", "/tmp/browser_screenshots")
os.makedirs(_SCREENSHOTS_DIR, exist_ok=True)


def _screenshot(page, name):
    # Diagnostic only — non-fatal. Bare page.screenshot() times out at 30s on
    # LinkedIn's animated composer and falsely fails posts (#3953). 5s timeout
    # + animations disabled + swallow errors.
    path = f"{_SCREENSHOTS_DIR}/{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    try:
        page.screenshot(path=path, timeout=5000, animations="disabled")
        return path
    except Exception:
        return None


def execute(page, params: dict) -> dict:
    query = params.get("query", "").strip()
    search_type = params.get("type", "people")  # people, posts, companies, jobs
    filters = params.get("filters", {})  # title, company, location, connection_degree
    limit = int(params.get("limit", 10))

    if not query:
        raise ValueError("query is required for linkedin_search")

    # Build search URL
    type_map = {"people": "PEOPLE", "posts": "CONTENT", "companies": "COMPANY", "jobs": "JOBS"}
    origin = type_map.get(search_type, "PEOPLE")
    search_url = f"https://www.linkedin.com/search/results/{search_type.lower()}/?keywords={query.replace(' ', '%20')}"

    # Append filters
    if filters.get("title"):
        search_url += f"&title={filters['title'].replace(' ', '%20')}"
    if filters.get("company"):
        search_url += f"&company={filters['company'].replace(' ', '%20')}"

    page.goto(search_url, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    _screenshot(page, "search_loaded")

    if search_type == "people":
        results = page.evaluate(f"""() => {{
            const items = [];
            const cards = document.querySelectorAll(
                '.reusable-search__result-container, .search-result__info, li.reusable-search__result-container'
            );
            let count = 0;
            for (const card of cards) {{
                if (count >= {limit}) break;
                const nameEl = card.querySelector('.actor-name, .entity-result__title-text a span[aria-hidden="true"]');
                const name = nameEl ? nameEl.textContent.trim() : '';
                const titleEl = card.querySelector('.entity-result__primary-subtitle, .subline-level-1');
                const title = titleEl ? titleEl.textContent.trim() : '';
                const locationEl = card.querySelector('.entity-result__secondary-subtitle, .subline-level-2');
                const location = locationEl ? locationEl.textContent.trim() : '';
                const linkEl = card.querySelector('a.app-aware-link[href*="/in/"]');
                const profile_url = linkEl ? linkEl.href.split('?')[0] : '';
                const connEl = card.querySelector('.entity-result__badge-text, .dist-value');
                const connection = connEl ? connEl.textContent.trim() : '';
                if (name) {{
                    items.push({{ name, title, location, profile_url, connection }});
                    count++;
                }}
            }}
            return items;
        }}""")
    else:
        results = page.evaluate(f"""() => {{
            const items = [];
            const cards = document.querySelectorAll('.reusable-search__result-container');
            let count = 0;
            for (const card of cards) {{
                if (count >= {limit}) break;
                const titleEl = card.querySelector('.entity-result__title-text');
                const title = titleEl ? titleEl.textContent.trim() : '';
                const subtitleEl = card.querySelector('.entity-result__primary-subtitle');
                const subtitle = subtitleEl ? subtitleEl.textContent.trim() : '';
                const linkEl = card.querySelector('a.app-aware-link');
                const url = linkEl ? linkEl.href.split('?')[0] : '';
                if (title) {{ items.push({{ title, subtitle, url }}); count++; }}
            }}
            return items;
        }}""")

    return {
        "success": True,
        "query": query,
        "type": search_type,
        "total": len(results),
        "results": results,
        "screenshot_path": _screenshot(page, "search_result"),
    }
