---
name: webapp-testing
description: Toolkit for interacting with and testing local web applications using Playwright. Supports verifying frontend functionality, debugging UI behavior, capturing browser screenshots, and viewing browser logs.
---

# Web Application Testing

Test local web applications by writing native Python Playwright scripts.

## Decision Tree

```
User task -> Is it static HTML?
    Yes -> Read HTML file directly to identify selectors
           -> Write Playwright script using selectors
    No (dynamic webapp) -> Is the server already running?
        No -> Use with_server.py helper
        Yes -> Reconnaissance-then-action:
            1. Navigate and wait for networkidle
            2. Take screenshot or inspect DOM
            3. Identify selectors from rendered state
            4. Execute actions with discovered selectors
```

## Reconnaissance-Then-Action Pattern

1. **Inspect rendered DOM**:
   ```python
   page.screenshot(path='/tmp/inspect.png', full_page=True)
   content = page.content()
   page.locator('button').all()
   ```

2. **Identify selectors** from inspection results

3. **Execute actions** using discovered selectors

## Example: Playwright Testing Script

```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto('http://localhost:3000')
    page.wait_for_load_state('networkidle')  # CRITICAL: Wait for JS

    # Responsive testing
    for viewport in [{'width': 374, 'height': 812},   # Fold5 closed
                     {'width': 717, 'height': 812},   # Fold5 open
                     {'width': 1280, 'height': 900}]:  # Desktop
        page.set_viewport_size(viewport)
        page.screenshot(path=f'/tmp/test_{viewport["width"]}.png', full_page=True)

    browser.close()
```

## Common Pitfall

- **Don't** inspect DOM before waiting for `networkidle` on dynamic apps
- **Do** wait for `page.wait_for_load_state('networkidle')` before inspection

## Best Practices

- Use `sync_playwright()` for synchronous scripts
- Always close the browser when done
- Use descriptive selectors: `text=`, `role=`, CSS selectors, or IDs
- Add appropriate waits: `page.wait_for_selector()` or `page.wait_for_timeout()`
