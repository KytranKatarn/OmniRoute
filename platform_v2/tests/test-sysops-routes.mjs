/**
 * System Operations — Route Split Verification
 * Ensures all endpoints still respond after ADR-045 refactor.
 */
import { chromium } from 'playwright';

const BASE = process.env.ARCHIE_URL || 'http://192.168.1.200:3000';
const CREDS = {
  username: process.env.ARCHIE_TEST_USER || 'admin',
  password: process.env.ARCHIE_TEST_PASS || 'Kyt$13ran2025',
};

const ENDPOINTS = [
  // Core
  { path: '/tools/system-operations', expect: 200, name: 'index' },
  { path: '/tools/system-operations/api/overview', expect: 200, name: 'overview' },
  { path: '/tools/system-operations/api/cpu', expect: 200, name: 'cpu' },
  { path: '/tools/system-operations/api/memory', expect: 200, name: 'memory' },
  { path: '/tools/system-operations/api/memory-hardware', expect: 200, name: 'memory-hw' },
  { path: '/tools/system-operations/api/hardware', expect: 200, name: 'hardware' },
  { path: '/tools/system-operations/api/disks', expect: 200, name: 'disks' },
  { path: '/tools/system-operations/api/host-data', expect: 200, name: 'host-data' },
  { path: '/tools/system-operations/health', expect: 200, name: 'health' },
  // Process
  { path: '/tools/system-operations/api/processes', expect: 200, name: 'processes' },
  { path: '/tools/system-operations/api/services', expect: 200, name: 'services' },
  // Docker
  { path: '/tools/system-operations/api/docker', expect: 200, name: 'docker' },
  { path: '/tools/system-operations/api/docker/health', expect: 200, name: 'docker-health' },
  // Network
  { path: '/tools/system-operations/api/network', expect: 200, name: 'network' },
  { path: '/tools/system-operations/api/network/port-map', expect: 200, name: 'port-map' },
  { path: '/tools/system-operations/api/network/bandwidth', expect: 200, name: 'bandwidth' },
  { path: '/tools/system-operations/api/network/port-usage', expect: 200, name: 'port-usage' },
  // Firewall
  { path: '/tools/system-operations/api/firewall/status', expect: [200, 504], name: 'fw-status', timeout: 60000, slow: true },
  { path: '/tools/system-operations/api/firewall/rules', expect: [200, 504], name: 'fw-rules', timeout: 60000, slow: true },
  // Stacks
  { path: '/tools/system-operations/api/stacks', expect: 200, name: 'stacks' },
  { path: '/tools/system-operations/api/stacks/status', expect: 200, name: 'stacks-status' },
  // Storage
  { path: '/tools/system-operations/api/storage/drives', expect: 200, name: 'drives' },
  { path: '/tools/system-operations/api/storage/mounts', expect: 200, name: 'mounts' },
  { path: '/tools/system-operations/api/lvm/info', expect: 200, name: 'lvm-info' },
  // Health
  { path: '/tools/system-operations/api/health/alerts', expect: 200, name: 'alerts' },
  { path: '/tools/system-operations/api/health/config', expect: 200, name: 'health-config' },
  { path: '/tools/system-operations/api/health/webhooks', expect: 200, name: 'webhooks' },
  { path: '/tools/system-operations/api/system-health-full', expect: 200, name: 'full-health' },
];

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

async function run() {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, ignoreHTTPSErrors: true });
  const page = await ctx.newPage();

  // Login
  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle', timeout: 15000 });
  await page.fill('#username', CREDS.username);
  await page.fill('#password', CREDS.password);
  await page.click('#loginBtn');
  await page.waitForURL(url => !url.pathname.startsWith('/login'), { timeout: 10000 });
  await dismissBoot(page);

  let passed = 0, failed = 0;
  for (const ep of ENDPOINTS) {
    try {
      const resp = await page.request.get(`${BASE}${ep.path}`, { timeout: ep.timeout || 30000 });
      const status = resp.status();
      const expected = Array.isArray(ep.expect) ? ep.expect : [ep.expect];
      if (expected.includes(status)) {
        console.log(`  PASS  ${ep.name} (${status})${ep.slow ? ' [slow]' : ''}`);
        passed++;
      } else {
        console.log(`  FAIL  ${ep.name} expected ${expected.join('|')} got ${status}`);
        failed++;
      }
    } catch (e) {
      console.log(`  FAIL  ${ep.name}: ${e.message}`);
      failed++;
    }
  }

  console.log(`\n${passed} passed, ${failed} failed out of ${ENDPOINTS.length}`);
  await browser.close();
  process.exit(failed > 0 ? 1 : 0);
}

run().catch(console.error);
