const { chromium } = require('playwright');

(async () => {
  const results = {
    timestamp: new Date().toISOString(),
    module: 'Consciousness',
    url: 'http://192.168.1.200:3000/tools/consciousness',
    login: { status: 'pending' },
    tabs: {},
    consoleErrors: [],
    pageErrors: [],
    summary: { total: 0, passed: 0, failed: 0 }
  };

  const tabDefs = [
    { name: 'dashboard', selector: '[data-tab="dashboard"], [onclick*="dashboard"], a[href*="dashboard"], button:has-text("Dashboard"), .nav-tab:has-text("Dashboard"), .cs-tab:has-text("Dashboard"), [data-section="dashboard"]' },
    { name: 'knowledge', selector: '[data-tab="knowledge"], [onclick*="knowledge"], a[href*="knowledge"], button:has-text("Knowledge"), .nav-tab:has-text("Knowledge"), .cs-tab:has-text("Knowledge"), [data-section="knowledge"]' },
    { name: 'github', selector: '[data-tab="github"], [onclick*="github"], a[href*="github"], button:has-text("GitHub"), .nav-tab:has-text("GitHub"), .cs-tab:has-text("GitHub"), [data-section="github"]' },
    { name: 'languages', selector: '[data-tab="languages"], [onclick*="languages"], a[href*="languages"], button:has-text("Languages"), .nav-tab:has-text("Languages"), .cs-tab:has-text("Languages"), [data-section="languages"]' },
    { name: 'codehealth', selector: '[data-tab="codehealth"], [onclick*="codehealth"], [onclick*="code-health"], [onclick*="codeHealth"], a[href*="codehealth"], button:has-text("Code Health"), .nav-tab:has-text("Code Health"), .cs-tab:has-text("Code Health"), [data-section="codehealth"], [data-tab="code-health"]' }
  ];

  let browser;
  try {
    browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({ viewport: { width: 1920, height: 1080 } });
    const page = await context.newPage();

    // Capture console errors
    page.on('console', msg => {
      if (msg.type() === 'error') {
        results.consoleErrors.push({ text: msg.text(), url: page.url() });
      }
    });
    page.on('pageerror', err => {
      results.pageErrors.push({ message: err.message, url: page.url() });
    });

    // Step 1: Login
    try {
      // No hardcoded credential — supply via env (PROBE_TEST_PASS / ARCHIE_TEST_PASSWORD).
      const TEST_PASS = process.env.PROBE_TEST_PASS || process.env.ARCHIE_TEST_PASSWORD;
      if (!TEST_PASS) {
        throw new Error('Set PROBE_TEST_PASS (or ARCHIE_TEST_PASSWORD) — no test password is hardcoded.');
      }
      await page.goto('http://192.168.1.200:3000/login', { waitUntil: 'networkidle', timeout: 15000 });
      await page.fill('input[name="username"], input[name="email"], #username, #email', 'admin');
      await page.fill('input[name="password"], #password', TEST_PASS);
      await page.click('button[type="submit"], input[type="submit"], .login-btn, #login-btn');
      await page.waitForURL('**/dashboard**', { timeout: 10000 }).catch(() => {});

      // Check if we're logged in (not still on login page)
      const currentUrl = page.url();
      if (currentUrl.includes('/login')) {
        results.login = { status: 'FAIL', error: 'Still on login page after submit', url: currentUrl };
      } else {
        results.login = { status: 'PASS', redirectedTo: currentUrl };
      }
    } catch (e) {
      results.login = { status: 'FAIL', error: e.message };
    }

    // Step 2: Navigate to Consciousness module
    try {
      await page.goto('http://192.168.1.200:3000/tools/consciousness', { waitUntil: 'networkidle', timeout: 15000 });
      await page.waitForTimeout(2000); // Let JS initialize

      // Take initial screenshot
      await page.screenshot({ path: '/mnt/archie_brain/tests/screenshots/consciousness_initial.png', fullPage: false });

      // Debug: find all clickable tab-like elements
      const allTabs = await page.evaluate(() => {
        const candidates = document.querySelectorAll('[data-tab], [onclick], .nav-tab, .cs-tab, .tab-btn, [role="tab"]');
        return Array.from(candidates).map(el => ({
          tag: el.tagName,
          text: el.textContent.trim().substring(0, 50),
          dataTab: el.getAttribute('data-tab'),
          onclick: el.getAttribute('onclick')?.substring(0, 80),
          classes: el.className.substring(0, 80)
        }));
      });
      results.detectedTabs = allTabs;

    } catch (e) {
      results.navigation = { status: 'FAIL', error: e.message };
    }

    // Step 3: Click each tab
    for (const tab of tabDefs) {
      results.summary.total++;
      const tabResult = { status: 'pending', errorsBeforeClick: results.consoleErrors.length };

      try {
        // Try each selector in the comma-separated list
        const selectors = tab.selector.split(', ');
        let clicked = false;

        for (const sel of selectors) {
          try {
            const el = await page.$(sel);
            if (el) {
              await el.click();
              clicked = true;
              tabResult.matchedSelector = sel;
              break;
            }
          } catch (_) { /* try next */ }
        }

        if (!clicked) {
          // Fallback: try text-based click
          try {
            const tabText = tab.name.charAt(0).toUpperCase() + tab.name.slice(1);
            await page.getByText(tabText, { exact: false }).first().click();
            clicked = true;
            tabResult.matchedSelector = `text="${tabText}"`;
          } catch (_) {}
        }

        if (!clicked) {
          tabResult.status = 'FAIL';
          tabResult.error = 'No matching tab element found';
          results.summary.failed++;
        } else {
          await page.waitForTimeout(2000); // Let tab content load

          const screenshotPath = `/mnt/archie_brain/tests/screenshots/consciousness_${tab.name}.png`;
          await page.screenshot({ path: screenshotPath, fullPage: false });
          tabResult.screenshot = screenshotPath;

          // Check for new errors after clicking
          const newErrors = results.consoleErrors.slice(tabResult.errorsBeforeClick);
          tabResult.jsErrors = newErrors;
          tabResult.status = 'PASS';
          results.summary.passed++;
        }
      } catch (e) {
        tabResult.status = 'FAIL';
        tabResult.error = e.message;
        results.summary.failed++;
      }

      results.tabs[tab.name] = tabResult;
    }

  } catch (e) {
    results.fatalError = e.message;
  } finally {
    if (browser) await browser.close();
  }

  // Output results
  console.log(JSON.stringify(results, null, 2));
})();
