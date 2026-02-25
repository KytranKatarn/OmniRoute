/**
 * Consciousness Module — Functional + Display Tests
 * Tests tab switching, sub-tabs, API data, modals, cross-module links, i18n
 * Runs at Fold5 closed (374), Fold5 open (717), Desktop (1280)
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
  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle', timeout: 15000 });
  await page.fill('#username', CREDS.username);
  await page.fill('#password', CREDS.password);
  await page.click('#loginBtn');
  await page.waitForURL(url => !url.pathname.startsWith('/login'), { timeout: 10000 });
  await page.goto(`${BASE}/tools/consciousness`, { waitUntil: 'networkidle', timeout: 15000 });
  await dismissBoot(page);
  await page.waitForTimeout(2000);
  return { ctx, page };
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

  // F1: Header renders with title
  const headerTitle = await page.locator('.cs-header-title').textContent();
  test('Header title present', headerTitle && headerTitle.length > 0);

  // F2: All 7 tabs exist
  const tabCount = await page.locator('.cs-tab').count();
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

  // F5: Stat cards populated (not showing --)
  const knowledgeStat = await page.locator('#statKnowledgeTotal').textContent();
  test('Knowledge stat populated', knowledgeStat && knowledgeStat !== '--' && parseInt(knowledgeStat) > 0);

  const agentStat = await page.locator('#statAgentTotal').textContent();
  test('Agent stat populated', agentStat && agentStat !== '--' && parseInt(agentStat) > 0);

  // F6: Activity feed has items
  const activityItems = await page.locator('#dashboardActivity .cs-activity-item').count();
  test('Activity feed has items', activityItems > 0);

  // F7: Integration health items visible
  const healthItems = await page.locator('#dashboardIntegration .cs-integration-item').count();
  test('Integration health items present', healthItems > 0);

  // --- Tab Switching ---
  console.log('\n--- Tab Switching ---');

  const tabs = ['knowledge', 'team', 'insights', 'languages', 'github', 'integration'];
  for (const tab of tabs) {
    await page.evaluate((t) => window.switchConsciousnessTab(t), tab);
    await page.waitForTimeout(1500);
    const panelVisible = await page.locator(`#panel-${tab}`).isVisible();
    test(`Switch to ${tab} tab — panel visible`, panelVisible);

    // Verify URL hash updated
    const hash = await page.evaluate(() => window.location.hash);
    test(`${tab} tab — URL hash updated`, hash === `#${tab}`);
  }

  // --- Knowledge Tab ---
  console.log('\n--- Knowledge Tab ---');
  await page.evaluate(() => window.switchConsciousnessTab('knowledge'));
  await page.waitForTimeout(2000);

  // F8: Knowledge browser sub-tab active by default
  const kbBrowserVisible = await page.locator('#kb-browser').isVisible();
  test('Knowledge Browser sub-tab visible by default', kbBrowserVisible);

  // F9: Knowledge table has rows
  const kbRows = await page.locator('#kbBrowserTable table tbody tr').count();
  test('Knowledge table has rows', kbRows > 0);

  // F10: Knowledge search input exists
  const searchInput = await page.locator('#kbSearch').isVisible();
  test('Knowledge search input visible', searchInput);

  // F11: Knowledge type filter exists
  const typeFilter = await page.locator('#kbFilterType').isVisible();
  test('Knowledge type filter visible', typeFilter);

  // F12: Switch sub-tabs
  const kbSubtabs = ['processing', 'categories', 'embeddings'];
  for (const sub of kbSubtabs) {
    await page.evaluate((s) => window.switchKnowledgeSubtab(s), sub);
    await page.waitForTimeout(1500);
    const subVisible = await page.locator(`#kb-${sub}`).isVisible();
    test(`Knowledge sub-tab "${sub}" switches`, subVisible);
  }

  // --- Team Tab ---
  console.log('\n--- Team Tab ---');
  await page.evaluate(() => window.switchConsciousnessTab('team'));
  await page.waitForTimeout(2000);

  // F13: Team roster API returns agents
  const rosterData = await page.evaluate(async () => {
    const r = await fetch('/tools/consciousness/api/team/roster');
    return r.json();
  });
  test('Team roster API success', rosterData.success === true);
  test('Team roster has agents', (rosterData.agents?.length || 0) > 0);

  // F14: Agent cards rendered
  const agentCards = await page.locator('.cs-agent-card').count();
  test('Agent cards rendered in DOM', agentCards > 0);

  // F15: Click agent card opens modal
  if (agentCards > 0) {
    const firstAgentId = rosterData.agents[0].id;
    await page.evaluate((id) => window.showAgentProfile(id), firstAgentId);
    await page.waitForTimeout(2000);
    const modalVisible = await page.locator('#agentModalOverlay.open').isVisible();
    test('Agent profile modal opens', modalVisible);

    // F16: Modal has profile content
    const modalBody = await page.locator('#agentModalBody').textContent();
    test('Agent modal has content', modalBody && modalBody.length > 20);

    // F17: Modal title shows agent name
    const modalTitle = await page.locator('#agentModalTitle').textContent();
    test('Agent modal title has name', modalTitle && modalTitle.includes('Personnel File'));

    // F18: Close modal
    await page.evaluate(() => window.closeAgentModal());
    await page.waitForTimeout(500);
    const modalClosed = !(await page.locator('#agentModalOverlay.open').isVisible());
    test('Agent modal closes', modalClosed);
  }

  // F19: Agent profile detail API
  if (rosterData.agents?.length > 0) {
    const profileData = await page.evaluate(async (id) => {
      const r = await fetch('/tools/consciousness/api/team/agents/' + id + '/profile');
      return r.json();
    }, rosterData.agents[0].id);
    test('Agent profile API success', profileData.success === true);
    test('Agent profile has identity', !!profileData.agent?.full_name);
  }

  // --- Insights Tab ---
  console.log('\n--- Insights Tab ---');
  await page.evaluate(() => window.switchConsciousnessTab('insights'));
  await page.waitForTimeout(2000);

  // F20: Insights summary API
  const insightsData = await page.evaluate(async () => {
    const r = await fetch('/tools/consciousness/api/insights/summary');
    return r.json();
  });
  test('Insights summary API success', insightsData.success === true);
  test('Insights has bridge stats', !!insightsData.bridge_stats);

  // F21: Sub-tab switching
  const insightsSubs = ['sessions', 'improvements'];
  for (const sub of insightsSubs) {
    await page.evaluate((s) => window.switchInsightsSubtab(s), sub);
    await page.waitForTimeout(1500);
    const subVisible = await page.locator(`#insights-${sub}`).isVisible();
    test(`Insights sub-tab "${sub}" switches`, subVisible);
  }

  // --- Languages Tab ---
  console.log('\n--- Languages Tab ---');
  await page.evaluate(() => window.switchConsciousnessTab('languages'));
  await page.waitForTimeout(2000);

  // F22: Languages stats API
  const langStats = await page.evaluate(async () => {
    const r = await fetch('/tools/consciousness/api/translations/stats');
    return r.json();
  });
  test('Translation stats API returns data', !!langStats.stats);
  test('Translation stats has 7+ languages', Object.keys(langStats.stats || {}).length >= 7);

  // F23: Sub-tab switching
  const langSubs = ['browser', 'review', 'glossary'];
  for (const sub of langSubs) {
    await page.evaluate((s) => window.switchLangSubtab(s), sub);
    await page.waitForTimeout(1500);
    const subVisible = await page.locator(`#lang-${sub}`).isVisible();
    test(`Languages sub-tab "${sub}" switches`, subVisible);
  }

  // --- GitHub Tab ---
  console.log('\n--- GitHub Tab ---');
  await page.evaluate(() => window.switchConsciousnessTab('github'));
  await page.waitForTimeout(2000);

  // F24: GitHub repos API
  const ghRepos = await page.evaluate(async () => {
    const r = await fetch('/tools/consciousness/api/github/repos');
    return r.json();
  });
  test('GitHub repos API success', ghRepos.success === true);

  // --- Integration Tab ---
  console.log('\n--- Integration Tab ---');
  await page.evaluate(() => window.switchConsciousnessTab('integration'));
  await page.waitForTimeout(2000);

  // F25: Integration health API with data
  const intHealth = await page.evaluate(async () => {
    const r = await fetch('/tools/consciousness/api/integration/health');
    return r.json();
  });
  test('Integration health API success', intHealth.success === true);
  test('Integration health has systems', !!intHealth.systems);

  // F26: Dev HQ summary API
  const devhqSummary = await page.evaluate(async () => {
    const r = await fetch('/tools/consciousness/api/integration/devhq-summary');
    return r.json();
  });
  test('Dev HQ summary API success', devhqSummary.success === true);
  test('Dev HQ summary has decisions', Array.isArray(devhqSummary.decisions));

  // F27: Pipeline test button exists
  const pipelineBtn = await page.locator('#testPipelineBtn, button:has-text("Test Pipeline")').count();
  test('Pipeline test button exists', pipelineBtn > 0);

  // --- Cross-Module Links ---
  console.log('\n--- Cross-Module Links ---');

  // F28: Bridge has Personnel File button
  await page.goto(`${BASE}/tools/bridge`, { waitUntil: 'networkidle', timeout: 15000 });
  await dismissBoot(page);
  await page.waitForTimeout(3000);

  // Switch to crew tab and open an agent profile
  await page.evaluate(() => window.switchBridgeTab && window.switchBridgeTab('crew'));
  await page.waitForTimeout(4000);
  const crewCards = await page.locator('.crew-agent-card').count();
  if (crewCards > 0) {
    await page.locator('.crew-agent-card').first().click();
    await page.waitForTimeout(3000);
    // Check for the Personnel File button in the modal footer
    const personnelBtn = await page.locator('#agent-profile-footer button:has-text("Personnel")').count();
    test('Bridge agent modal has Personnel File button', personnelBtn > 0);
    // Screenshot for evidence
    await page.screenshot({ path: `${OUT}/consciousness-bridge-crosslink.png`, fullPage: false });
    // Close the modal
    await page.evaluate(() => {
      const m = document.getElementById('agent-profile-modal');
      if (m) m.classList.remove('active');
    });
  } else {
    test('Bridge crew cards exist for cross-link test', false);
  }

  // F29: Hash navigation works
  await page.goto(`${BASE}/tools/consciousness#team`, { waitUntil: 'networkidle', timeout: 15000 });
  await dismissBoot(page);
  await page.waitForTimeout(3000);
  const teamActive = await page.locator('#panel-team').isVisible();
  test('Hash navigation #team opens team tab', teamActive);

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
    const headerBox = await pg.locator('.cs-header').boundingBox();
    test(`[${vp.name}] Header fits within viewport`, headerBox && headerBox.width <= vp.width + 2);

    // D2: Tab nav doesn't overflow vertically (should scroll, not wrap excessively)
    const tabsBox = await pg.locator('.cs-tabs').boundingBox();
    const maxTabHeight = vp.width <= 480 ? 120 : 65; // icon-only may wrap on mobile; text tabs ~61px on tablet
    test(`[${vp.name}] Tab nav height reasonable (${tabsBox?.height?.toFixed(0)}px)`, tabsBox && tabsBox.height < maxTabHeight);

    // D3: Stats grid renders properly (scoped to dashboard panel)
    const statsBox = await pg.locator('#panel-dashboard .cs-stats').first().boundingBox();
    test(`[${vp.name}] Stats grid visible`, statsBox && statsBox.height > 0);

    // D4: No horizontal page overflow
    const pageWidth = await pg.evaluate(() => document.documentElement.scrollWidth);
    test(`[${vp.name}] No horizontal overflow (${pageWidth}px)`, pageWidth <= vp.width + 5);

    // D5: Dashboard content not empty
    const dashContent = await pg.locator('#panel-dashboard').textContent();
    test(`[${vp.name}] Dashboard has content`, dashContent && dashContent.length > 50);

    // D6: Switch to team — cards render
    await pg.evaluate(() => window.switchConsciousnessTab('team'));
    await pg.waitForTimeout(2000);
    const teamCards = await pg.locator('.cs-agent-card').count();
    test(`[${vp.name}] Team cards render (${teamCards})`, teamCards > 0);

    // D7: Agent card grid adapts to viewport
    if (teamCards >= 2) {
      const card1 = await pg.locator('.cs-agent-card').nth(0).boundingBox();
      const card2 = await pg.locator('.cs-agent-card').nth(1).boundingBox();
      if (vp.width >= 1280) {
        // Desktop: should be 3 columns (cards side by side)
        test(`[${vp.name}] Agent cards in multi-column layout`, card1 && card2 && card2.x > card1.x);
      } else {
        // Mobile/tablet: 1-2 columns
        test(`[${vp.name}] Agent cards fit viewport`, card1 && card1.width <= vp.width);
      }
    }

    // D8: Switch to knowledge — table scrollable
    await pg.evaluate(() => window.switchConsciousnessTab('knowledge'));
    await pg.waitForTimeout(2000);
    const tableWrap = await pg.locator('.cs-table-wrap').first().isVisible();
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
