import { chromium } from 'playwright';
import path from 'path';

const SCREENSHOT_DIR = '/mnt/archie_brain/screenshots';
const BASE_URL = 'http://192.168.1.200:3000';

const accounts = [
  { username: 'Terry', password: 'TestFree456!', tier: 'free' },
  { username: 'test_pro', password: 'TestPro123!', tier: 'pro' },
  { username: 'test_business', password: 'TestBiz123!', tier: 'business' },
  { username: 'test_enterprise', password: 'TestEnt123!', tier: 'enterprise' },
  { username: 'test_vip', password: 'TestVIP123!', tier: 'vip' },
  { username: 'admin', password: 'Kyt$13ran2025', tier: 'kytran-admin' },
];

(async () => {
  const browser = await chromium.launch({ headless: true });

  for (const account of accounts) {
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const page = await context.newPage();

    console.log('');
    console.log('=== ' + account.username + ' (' + account.tier + ') ===');

    try {
      await page.goto(BASE_URL + '/login', { waitUntil: 'networkidle', timeout: 15000 });
      await page.waitForTimeout(2000);

      await page.locator('#username').fill(account.username);
      await page.locator('#password').fill(account.password);
      await page.locator('#loginBtn').click();

      try {
        await page.waitForURL('**/dashboard**', { timeout: 10000 });
        console.log('Logged in successfully → ' + page.url());

        // Wait for dashboard to fully load
        await page.waitForTimeout(3000);

        // Try to dismiss any loading overlay
        await page.evaluate(() => {
          const overlay = document.querySelector('.loading-overlay, .dashboard-loading, #loadingOverlay');
          if (overlay) overlay.style.display = 'none';
        });
        await page.waitForTimeout(500);

        // Get module cards visible
        const moduleCards = await page.locator('.module-card, .tool-card, [class*="card"]').count();
        console.log('Module cards visible: ' + moduleCards);

        // Get tier display
        const tierText = await page.locator('[class*="tier"], [class*="subscription"]').first().textContent().catch(() => 'not found');
        console.log('Tier display: ' + tierText);

        // Check for Account Center link (admin-only)
        const acLink = await page.locator('a[href*="account"], a:has-text("Account Center")').count();
        console.log('Account Center link visible: ' + (acLink > 0 ? 'YES' : 'NO'));

        // Full page screenshot
        await page.screenshot({
          path: path.join(SCREENSHOT_DIR, 'dashboard-' + account.tier + '.png'),
          fullPage: true
        });
        console.log('Screenshot saved.');

        // Also try to access Account Center directly
        await page.goto(BASE_URL + '/tools/account-center/', { waitUntil: 'networkidle', timeout: 10000 });
        await page.waitForTimeout(1000);
        const acUrl = page.url();
        console.log('Account Center access: ' + (acUrl.includes('account-center') ? 'ALLOWED (' + acUrl + ')' : 'DENIED (redirected to ' + acUrl + ')'));

        if (acUrl.includes('account-center')) {
          await page.screenshot({
            path: path.join(SCREENSHOT_DIR, 'account-center-' + account.tier + '.png'),
            fullPage: true
          });
        }

      } catch (e) {
        console.log('Login FAILED: ' + page.url());
        await page.screenshot({ path: path.join(SCREENSHOT_DIR, 'login-fail-' + account.tier + '.png'), fullPage: true });
      }

    } catch (err) {
      console.log('EXCEPTION: ' + err.message);
    }

    await context.close();
  }

  await browser.close();
  console.log('');
  console.log('=== All tier tests complete ===');
})();
