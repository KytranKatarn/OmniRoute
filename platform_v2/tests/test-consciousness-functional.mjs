/**
 * Consciousness Module — Functional + Display Tests
 * Tests tab switching, sub-tabs, API data, modals, cross-module links, i18n
 * Runs at Fold5 closed (374), Fold5 open (717), Desktop (1280)
 *
 * Updated 2026-10-09 for the LCARS redesign (root cause of the old
 * `.cs-header-title` 30s timeout — that selector no longer exists):
 *   - header/tabs are now .lcars-header-title / .lcars-header-tab
 *   - tabs: dashboard, devhq, knowledge, languages, github, tokens, codehealth
 *     (team merged into Starbase Command Crew; insights/integration tabs removed,
 *      their APIs remain live and are still asserted below, and the removal
 *      itself is asserted — see the F21 replacement in Cross-cutting APIs)
 *   - dashboard stats are the Neural Core #nc* elements; knowledge tab owns .cs-stats
 *   - Languages tab is single-page (switchLangSubtab removed)
 *   - agent profile modal (showAgentProfile) removed with the team tab
 */
import { chromium } from 'playwright';

const BASE = process.env.ARCHIE_URL || 'http://192.168.1.200:3000';
const CREDS = { username: 'admin', password: 'Kyt$13ran2025' };
const OUT = '/mnt/archie_brain/screenshots';

let passed = 0, failed = 0;

function test(name, ok) {
  console.log(`${ok ? 'PASS' : 'FAIL'}: ${name}`);
  ok ? passed++ : failed++;
}

async function waitFor(fn, timeout = 10000, interval = 300) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeout) {
    if (await fn()) return true;
    await new Promise((r) => setTimeout(r, interval));
  }
  return false;
}

async function dismissBoot(pg) {
  try {
    const skipBtn = pg.locator('#bootSkipBtn');
    await skipBtn.waitFor({ state: 'visible', timeout: 6000 });
    await skipBtn.click();
    await pg.waitForTimeout(1500);
  } catch (e) {
    await pg.waitForTimeout(6000);
  }
  await pg.evaluate(() => {
    const o = document.getElementById('bootOverlay');
    if (o) o.remove();
  });
  await pg.waitForTimeout(500);
}

async function login(browser, width, height) {
  const ctx = await browser.newContext({
    viewport: { width, height },
    ignoreHTTPSErrors: true,
  });
  const page = await ctx.newPage();
  await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded', timeout: 45000 });
  await page.fill('#username', CREDS.username);
  await page.fill('#password', CREDS.password);
  await page.click('#loginBtn');
  await page.waitForURL(url => !url.pathname.startsWith('/login'), { timeout: 15000 });
  await page.goto(`${BASE}/tools/consciousness`, { waitUntil: 'domcontentloaded', timeout: 45000 });
  await dismissBoot(page);
  await page.waitForTimeout(2500);
  return { ctx, page };
}

async function switchTab(pg, tab) {
  await pg.evaluate((t) => window.switchConsciousnessTab(t), tab);
  await pg.waitForTimeout(1500);
}

async function run() {
  const browser = await chromium.launch({ headless: true });

  // =============================================
  // SECTION 1: Functional Tests (1280px)
  // =============================================
  console.log('=== FUNCTIONAL TESTS (1280px) ===\n');
  const { ctx, page } = await login(browser, 1280, 900);

  // --- Dashboard Tab ---
  console.log('--- Dashboard Tab ---');

  // F1: Header renders with title (LCARS header)
  const headerTitle = await page.locator('.lcars-header-title').textContent();
  test('Header title present', headerTitle && headerTitle.length > 0);

  // F2: All 7 tabs exist
  const tabCount = await page.locator('.lcars-header-tab').count();
  test('7 tab buttons exist', tabCount === 7);

  // F3: Dashboard is active by default
  const activePanel = await page.locator('.cs-panel.active').getAttribute('id');
  test('Dashboard panel active by default', activePanel === 'panel-dashboard');

  // F4: Dashboard summary API returns valid data
  const summaryData = await page.evaluate(async () => {
    const r = await fetch('/tools/consciousness/api/dashboard/summary');
    return r.json();
  });
  test('Dashboard API returns success', summaryData.success === true);
  test('Dashboard has knowledge count > 0', (summaryData.knowledge?.total || 0) > 0);
  test('Dashboard has agents count > 0', (summaryData.agents?.total || 0) > 0);
  test('Dashboard has activity items', Array.isArray(summaryData.activity));

  // F5: Neural Core stats populated (not showing --)
  const ncOk = await waitFor(async () => {
    const v = await page.evaluate(() => ({
      knowledge: document.querySelector('#ncTotalKnowledge')?.textContent?.trim() || '',
      agents: document.querySelector('#ncActiveAgents')?.textContent?.trim() || '',
    }));
    return v.knowledge !== '--' && parseInt(v.knowledge.replace(/[^0-9]/g, '')) > 0 &&
           v.agents !== '--' && v.agents.length > 0;
  }, 12000);
  test('Neural Core knowledge stat populated', ncOk);
  const ncAgents = await page.locator('#ncActiveAgents').textContent();
  test('Neural Core agents stat populated', ncAgents && ncAgents !== '--');

  // F6: Activity feed has items
  const activityItems = await page.locator('#dashboardActivity .cs-activity-item').count();
  test('Activity feed has items', activityItems > 0);

  // F7: Mood indicator populated (dashboard side widget)
  const moodValue = await page.locator('#moodValue').textContent();
  test('Mood indicator populated', moodValue && moodValue.length > 0);

  // --- Tab Switching ---
  console.log('\n--- Tab Switching ---');

  const tabs = ['devhq', 'knowledge', 'languages', 'github', 'tokens', 'codehealth'];
  for (const tab of tabs) {
    await switchTab(page, tab);
    const panelVisible = await page.locator(`#panel-${tab}`).isVisible();
    test(`Switch to ${tab} tab — panel visible`, panelVisible);

    // Verify URL hash updated
    const hash = await page.evaluate(() => window.location.hash);
    test(`${tab} tab — URL hash updated`, hash === `#${tab}`);
  }

  // --- Knowledge Tab ---
  console.log('\n--- Knowledge Tab ---');
  await switchTab(page, 'knowledge');

  // F8: Knowledge browser sub-tab active by default
  const kbBrowserVisible = await page.locator('#kb-browser').isVisible();
  test('Knowledge Browser sub-tab visible by default', kbBrowserVisible);

  // F9: Knowledge table has rows (loads async)
  const kbRowsOk = await waitFor(async () => {
    const n = await page.locator('#kbBrowserTable table tbody tr').count();
    return n > 0;
  }, 12000);
  test('Knowledge table has rows', kbRowsOk);

  // F10: Knowledge search input exists
  const searchInput = await page.locator('#kbSearch').isVisible();
  test('Knowledge search input visible', searchInput);

  // F11: Knowledge type filter exists
  const typeFilter = await page.locator('#kbFilterType').isVisible();
  test('Knowledge type filter visible', typeFilter);

  // F12: Switch sub-tabs (processing tab removed — browser/categories/embeddings/graph)
  const kbSubtabs = ['categories', 'embeddings', 'graph'];
  for (const sub of kbSubtabs) {
    await page.evaluate((s) => window.switchKnowledgeSubtab(s), sub);
    await page.waitForTimeout(1000);
    const subVisible = await page.locator(`#kb-${sub}`).isVisible();
    test(`Knowledge sub-tab "${sub}" switches`, subVisible);
  }
  await page.evaluate(() => window.switchKnowledgeSubtab('browser'));
  await page.waitForTimeout(500);

  // --- Dev HQ Tab (team tab merged into Starbase Command Crew) ---
  console.log('\n--- Dev HQ Tab ---');
  await switchTab(page, 'devhq');
  // Integrations live on the System sub-tab (loadIntegrations only runs there)
  await page.evaluate(() => window.switchDevHQTab('system'));
  await page.waitForTimeout(1500);
  const devhqLoaded = await waitFor(async () => {
    const n = await page.locator('#integrationsGrid').evaluate((el) => (el?.textContent || '').trim().length);
    return n > 30;
  }, 15000);
  test('Dev HQ integrations grid populated (System sub-tab)', devhqLoaded);

  // F: Dev HQ summary API
  const devhqSummary = await page.evaluate(async () => {
    const r = await fetch('/tools/consciousness/api/integration/devhq-summary');
    return r.json();
  });
  test('Dev HQ summary API success', devhqSummary.success === true);
  test('Dev HQ summary has decisions', Array.isArray(devhqSummary.decisions));

  // --- Languages Tab ---
  console.log('\n--- Languages Tab ---');
  await switchTab(page, 'languages');

  // F: Languages stats API (tab is single-page now — no sub-tabs)
  const langStats = await page.evaluate(async () => {
    const r = await fetch('/tools/consciousness/api/translations/stats');
    return r.json();
  });
  test('Translation stats API returns data', !!langStats.stats);
  test('Translation stats has 7+ languages', Object.keys(langStats.stats || {}).length >= 7);

  const langPanelText = await page.locator('#panel-languages').textContent();
  test('Languages panel renders content', langPanelText && langPanelText.length > 500);

  // --- GitHub Tab ---
  console.log('\n--- GitHub Tab ---');
  await switchTab(page, 'github');

  // F: GitHub repos API
  const ghRepos = await page.evaluate(async () => {
    const r = await fetch('/tools/consciousness/api/github/repos');
    return r.json();
  });
  test('GitHub repos API success', ghRepos.success === true);

  // F: GitHub repo grid + review filter bar render
  const ghGridOk = await waitFor(async () => {
    const n = await page.locator('#ghRepoGrid > *').count();
    return n > 0;
  }, 12000);
  test('GitHub repo grid rendered', ghGridOk);
  const ghFilterBar = await page.locator('#ghFilterBar').count();
  test('GitHub review filter bar present', ghFilterBar > 0);

  // --- Integration + Insights: removed tabs (old F21) + APIs still live ---
  console.log('\n--- Cross-cutting APIs ---');

  // F21 (was: sub-tab switching for sessions/improvements) — the insights and
  // integration tabs and their sub-tabs were deleted in the LCARS redesign and
  // window.switchInsightsSubtab was removed from consciousness.js. Cover the
  // removal explicitly (negative assertions), then the still-live APIs below.
  const removedUi = await page.evaluate(() => ({
    insightsTab: !!document.querySelector('.lcars-header-tab[data-tab="insights"]'),
    integrationTab: !!document.querySelector('.lcars-header-tab[data-tab="integration"]'),
    insightsPanel: !!document.getElementById('panel-insights'),
    insightsSubtabs: !!document.getElementById('insights-sessions') ||
                     !!document.getElementById('insights-improvements'),
    switchFn: typeof window.switchInsightsSubtab,
  }));
  test('Insights tab button absent from LCARS header', removedUi.insightsTab === false);
  test('Integration tab button absent from LCARS header', removedUi.integrationTab === false);
  test('Insights panel absent', removedUi.insightsPanel === false);
  test('Insights sub-tabs absent (sessions/improvements)', removedUi.insightsSubtabs === false);
  test('switchInsightsSubtab removed from window', removedUi.switchFn === 'undefined');

  const intHealth = await page.evaluate(async () => {
    const r = await fetch('/tools/consciousness/api/integration/health');
    return r.json();
  });
  test('Integration health API success', intHealth.success === true);
  test('Integration health has systems', !!intHealth.systems);

  const insightsData = await page.evaluate(async () => {
    const r = await fetch('/tools/consciousness/api/insights/summary');
    return r.json();
  });
  test('Insights summary API success', insightsData.success === true);
  test('Insights has bridge stats', !!insightsData.bridge_stats);

  // F: Pipeline toggle button (dashboard pipeline — replaces old Test Pipeline button)
  await switchTab(page, 'dashboard');
  const pipelineBtn = await page.locator('#pipelineToggleBtn').count();
  test('Pipeline toggle button exists', pipelineBtn > 0);

  // --- Cross-Module Links ---
  console.log('\n--- Cross-Module Links ---');

  // F: Old /tools/starbase URLs keep working (redirect compat route)
  const sb = await page.evaluate(async () => {
    const r = await fetch('/tools/starbase', { redirect: 'follow' });
    return { status: r.status, url: r.url };
  });
  test('Starbase compat redirect lands on a live page', sb.status === 200);
  await page.screenshot({ path: `${OUT}/consciousness-bridge-crosslink.png`, fullPage: false });

  // F: Hash navigation works
  await page.goto(`${BASE}/tools/consciousness#github`, { waitUntil: 'domcontentloaded', timeout: 45000 });
  await dismissBoot(page);
  await page.waitForTimeout(3000);
  const ghActive = await page.locator('#panel-github').isVisible();
  test('Hash navigation #github opens github tab', ghActive);

  await ctx.close();

  // =============================================
  // SECTION 2: Display Tests (all 3 viewports)
  // =============================================
  const VIEWPORTS = [
    { name: 'fold5-closed-374', width: 374, height: 812 },
    { name: 'fold5-open-717', width: 717, height: 812 },
    { name: 'desktop-1280', width: 1280, height: 900 },
  ];

  for (const vp of VIEWPORTS) {
    console.log(`\n=== DISPLAY TESTS (${vp.name}) ===`);
    const { ctx: c, page: pg } = await login(browser, vp.width, vp.height);

    // D1: Header doesn't overflow
    const headerBox = await pg.locator('.lcars-header').boundingBox();
    test(`[${vp.name}] Header fits within viewport`, headerBox && headerBox.width <= vp.width + 2);

    // D2: Tab nav doesn't overflow vertically (should scroll, not wrap excessively)
    const tabsBox = await pg.locator('.lcars-header-tabs').boundingBox();
    // LCARS header tabs wrap to 2 rows on fold widths; 1 row on desktop
    const maxTabHeight = vp.width <= 480 ? 200 : vp.width <= 800 ? 140 : 80;
    test(`[${vp.name}] Tab nav height reasonable (${tabsBox?.height?.toFixed(0)}px)`, tabsBox && tabsBox.height < maxTabHeight);

    // D3: No horizontal page overflow
    const pageWidth = await pg.evaluate(() => document.documentElement.scrollWidth);
    test(`[${vp.name}] No horizontal overflow (${pageWidth}px)`, pageWidth <= vp.width + 5);

    // D4: Dashboard content not empty
    const dashContent = await pg.locator('#panel-dashboard').textContent();
    test(`[${vp.name}] Dashboard has content`, dashContent && dashContent.length > 50);

    // D5: Dashboard stat-card grid renders (Neural Core row)
    const statsBox = await pg.locator('#panel-dashboard .cs-dashboard-grid-3').first().boundingBox();
    test(`[${vp.name}] Stats grid visible`, statsBox && statsBox.height > 0);

    // D6: Dashboard stat cards render
    const statCards = await pg.locator('#panel-dashboard .cs-dashboard-grid-3 > *').count();
    test(`[${vp.name}] Dashboard stat cards render (${statCards})`, statCards >= 2);

    // D7: Stat card grid adapts to viewport
    if (statCards >= 2) {
      const card1 = await pg.locator('#panel-dashboard .cs-dashboard-grid-3 > *').nth(0).boundingBox();
      const card2 = await pg.locator('#panel-dashboard .cs-dashboard-grid-3 > *').nth(1).boundingBox();
      if (vp.width >= 1280) {
        // Desktop: cards side by side
        test(`[${vp.name}] Stat cards in multi-column layout`, card1 && card2 && card2.x > card1.x);
      } else {
        // Mobile/tablet: cards fit viewport
        test(`[${vp.name}] Stat cards fit viewport`, card1 && card1.width <= vp.width);
      }
    }

    // D8: Knowledge table scrollable
    await switchTab(pg, 'knowledge');
    const tableWrapOk = await waitFor(async () => {
      const rows = await pg.locator('#kbBrowserTable table tbody tr').count();
      return rows > 0;
    }, 12000);
    const tableWrap = tableWrapOk && await pg.locator('.cs-table-wrap').first().isVisible();
    test(`[${vp.name}] Knowledge table has scroll wrapper`, tableWrap);

    // D9: No content clipped (check body scroll height vs viewport)
    const scrollH = await pg.evaluate(() => document.body.scrollHeight);
    test(`[${vp.name}] Page scrollable (${scrollH}px)`, scrollH > 0);

    // Screenshot for visual reference
    await pg.screenshot({ path: `${OUT}/consciousness-display-${vp.name}.png`, fullPage: true });
    console.log(`  Screenshot: consciousness-display-${vp.name}.png`);

    await c.close();
  }

  // =============================================
  // RESULTS
  // =============================================
  console.log(`\n${'='.repeat(50)}`);
  console.log(`RESULTS: ${passed} passed, ${failed} failed`);
  console.log(`${'='.repeat(50)}`);

  await browser.close();
  process.exit(failed > 0 ? 1 : 0);
}

run().catch(e => { console.error('FATAL:', e.message); process.exit(1); });
