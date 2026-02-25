import { chromium } from 'playwright';
import path from 'path';

const SCREENSHOT_DIR = '/mnt/archie_brain/screenshots';
const BASE_URL = 'http://192.168.1.200:3000';

const accounts = [
  { username: 'kytranempowerment', password: 'TestFree123!' },
  { username: 'Terry', password: 'TestFree456!' },
];

(async () => {
  const browser = await chromium.launch({ headless: true });

  for (const account of accounts) {
    const context = await browser.newContext({ viewport: { width: 1280, height: 720 } });
    const page = await context.newPage();
    const label = account.username.toLowerCase();

    console.log('');
    console.log('=== Testing account: ' + account.username + ' ===');

    try {
      await page.goto(BASE_URL + '/login', { waitUntil: 'networkidle', timeout: 15000 });
      await page.waitForTimeout(2000);

      const usernameField = page.locator('#username');
      const passwordField = page.locator('#password');

      await usernameField.fill(account.username);
      await passwordField.fill(account.password);
      console.log('Credentials filled.');

      const loginBtn = page.locator('#loginBtn');
      await loginBtn.click();
      console.log('Login button clicked.');

      try {
        await page.waitForURL('**/dashboard**', { timeout: 10000 });
        console.log('SUCCESS: Redirected to ' + page.url());
        await page.waitForTimeout(2000);
        await page.screenshot({ path: path.join(SCREENSHOT_DIR, 'login-' + label + '-dashboard.png'), fullPage: true });
      } catch (e) {
        console.log('Current URL: ' + page.url());

        // Check for flash messages or error indicators
        const flashMsgs = await page.locator('.flash-message, .alert, [class*="error"], [class*="flash"]').allTextContents();
        if (flashMsgs.length > 0) {
          console.log('Flash messages: ' + flashMsgs.join(' | '));
        }

        if (page.url().includes('login')) {
          console.log('FAILURE: Still on login page.');
        } else if (page.url().includes('dashboard')) {
          console.log('SUCCESS: On dashboard.');
        } else if (page.url().includes('pending') || page.url().includes('inactive')) {
          console.log('ACCOUNT ISSUE: Redirected to ' + page.url());
        } else {
          console.log('UNKNOWN: URL is ' + page.url());
        }
        await page.screenshot({ path: path.join(SCREENSHOT_DIR, 'login-' + label + '-result.png'), fullPage: true });
      }

    } catch (err) {
      console.log('EXCEPTION: ' + err.message);
    }

    await context.close();
  }

  await browser.close();
  console.log('');
  console.log('=== All tests complete ===');
})();
