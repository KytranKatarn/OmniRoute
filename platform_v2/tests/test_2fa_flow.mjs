import { chromium } from 'playwright';
import path from 'path';
import { execFileSync } from 'child_process';

const SCREENSHOT_DIR = '/mnt/archie_brain/screenshots';
const BASE_URL = 'http://192.168.1.200:3000';

// Test user for 2FA
const TEST_USER = { username: 'Terry', password: 'TestFree456!' };

function generateTotpCode(secret) {
  // Use execFileSync to safely call docker exec with pyotp
  const result = execFileSync('docker', [
    'exec', 'archie_platform', 'python3', '-c',
    'import pyotp; print(pyotp.TOTP("' + secret + '").now())'
  ], { encoding: 'utf-8' });
  return result.trim();
}

(async () => {
  const browser = await chromium.launch({ headless: true });

  // Step 1: Enable 2FA for Terry via Account Center API (logged in as admin)
  console.log('=== Step 1: Enable 2FA via Account Center ===');
  {
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const page = await context.newPage();

    // Login as admin
    await page.goto(BASE_URL + '/login', { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(2000);
    await page.locator('#username').fill('admin');
    await page.locator('#password').fill('Kyt$13ran2025');
    await page.locator('#loginBtn').click();
    await page.waitForURL('**/dashboard**', { timeout: 10000 });
    console.log('Admin logged in.');

    // Get Terry's user ID
    const usersRes = await page.evaluate(async () => {
      const res = await fetch('/tools/account-center/api/users');
      return res.json();
    });

    const terry = usersRes.users.find(u => u.username === 'Terry');
    if (!terry) {
      console.log('ERROR: Terry not found in users list');
      await context.close();
      await browser.close();
      return;
    }
    console.log('Terry user ID: ' + terry.id);

    // Enable 2FA for Terry
    const enable2faRes = await page.evaluate(async (userId) => {
      const res = await fetch('/tools/account-center/api/security/2fa/' + userId, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: true })
      });
      return res.json();
    }, terry.id);

    if (enable2faRes.success) {
      console.log('2FA enabled for Terry.');
      console.log('TOTP Secret: ' + enable2faRes.totp_secret);
      console.log('QR Code present: ' + (enable2faRes.qr_code ? 'YES' : 'NO'));

      const totpSecret = enable2faRes.totp_secret;

      // Screenshot Account Center Security tab
      await page.goto(BASE_URL + '/tools/account-center/', { waitUntil: 'networkidle', timeout: 15000 });
      await page.waitForTimeout(2000);
      const secTab = page.locator('[data-tab="security"], .tab-btn:has-text("Security")');
      if (await secTab.count() > 0) {
        await secTab.first().click();
        await page.waitForTimeout(2000);
        await page.screenshot({ path: path.join(SCREENSHOT_DIR, '2fa-account-center-security.png'), fullPage: true });
        console.log('Security tab screenshot saved.');
      }

      await context.close();

      // Step 2: Login as Terry - should redirect to 2FA page
      console.log('');
      console.log('=== Step 2: Login as Terry (expect 2FA redirect) ===');
      {
        const ctx2 = await browser.newContext({ viewport: { width: 1280, height: 720 } });
        const pg2 = await ctx2.newPage();

        await pg2.goto(BASE_URL + '/login', { waitUntil: 'networkidle', timeout: 15000 });
        await pg2.waitForTimeout(2000);
        await pg2.locator('#username').fill(TEST_USER.username);
        await pg2.locator('#password').fill(TEST_USER.password);
        await pg2.locator('#loginBtn').click();

        await pg2.waitForTimeout(3000);
        const afterLoginUrl = pg2.url();
        console.log('After login URL: ' + afterLoginUrl);

        if (afterLoginUrl.includes('verify-2fa') || afterLoginUrl.includes('2fa')) {
          console.log('SUCCESS: Redirected to 2FA verification page!');
          await pg2.screenshot({ path: path.join(SCREENSHOT_DIR, '2fa-verify-page.png'), fullPage: true });

          // Step 3: Generate TOTP code and submit
          console.log('');
          console.log('=== Step 3: Submit valid TOTP code ===');

          const totpCode = generateTotpCode(totpSecret);
          console.log('Generated TOTP code: ' + totpCode);

          // Find and fill the code input
          const codeInput = pg2.locator('input[name="code"], input[name="totp_code"], input[type="text"], input[inputmode="numeric"]').first();
          await codeInput.fill(totpCode);
          console.log('TOTP code entered.');

          // Submit
          const verifyBtn = pg2.locator('button[type="submit"], button:has-text("Verify"), input[type="submit"]').first();
          await verifyBtn.click();
          console.log('Verify button clicked.');

          await pg2.waitForTimeout(3000);
          const afterVerifyUrl = pg2.url();
          console.log('After verify URL: ' + afterVerifyUrl);

          if (afterVerifyUrl.includes('dashboard')) {
            console.log('SUCCESS: 2FA verification complete - reached dashboard!');
          } else if (afterVerifyUrl.includes('verify-2fa') || afterVerifyUrl.includes('2fa')) {
            console.log('NOTE: Still on 2FA page (code may have expired).');
          } else {
            console.log('UNKNOWN: URL is ' + afterVerifyUrl);
          }

          await pg2.screenshot({ path: path.join(SCREENSHOT_DIR, '2fa-after-verify.png'), fullPage: true });
        } else if (afterLoginUrl.includes('dashboard')) {
          console.log('NOTE: Went straight to dashboard (2FA may not be active).');
        } else {
          console.log('UNEXPECTED URL: ' + afterLoginUrl);
        }

        await ctx2.close();
      }

      // Step 4: Disable 2FA for Terry (cleanup)
      console.log('');
      console.log('=== Step 4: Cleanup - Disable 2FA ===');
      {
        const ctx3 = await browser.newContext({ viewport: { width: 1280, height: 720 } });
        const pg3 = await ctx3.newPage();

        await pg3.goto(BASE_URL + '/login', { waitUntil: 'networkidle', timeout: 15000 });
        await pg3.waitForTimeout(2000);
        await pg3.locator('#username').fill('admin');
        await pg3.locator('#password').fill('Kyt$13ran2025');
        await pg3.locator('#loginBtn').click();
        await pg3.waitForURL('**/dashboard**', { timeout: 10000 });

        const disableRes = await pg3.evaluate(async (userId) => {
          const res = await fetch('/tools/account-center/api/security/2fa/' + userId, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled: false })
          });
          return res.json();
        }, terry.id);

        console.log('2FA disabled: ' + (disableRes.success ? 'YES' : 'NO'));
        await ctx3.close();
      }

      // Step 5: Verify Terry can login without 2FA
      console.log('');
      console.log('=== Step 5: Verify normal login (no 2FA) ===');
      {
        const ctx4 = await browser.newContext({ viewport: { width: 1280, height: 720 } });
        const pg4 = await ctx4.newPage();

        await pg4.goto(BASE_URL + '/login', { waitUntil: 'networkidle', timeout: 15000 });
        await pg4.waitForTimeout(2000);
        await pg4.locator('#username').fill(TEST_USER.username);
        await pg4.locator('#password').fill(TEST_USER.password);
        await pg4.locator('#loginBtn').click();

        try {
          await pg4.waitForURL('**/dashboard**', { timeout: 10000 });
          console.log('SUCCESS: Terry logged in directly (no 2FA prompt).');
        } catch (e) {
          console.log('ISSUE: URL is ' + pg4.url());
        }

        await ctx4.close();
      }

    } else {
      console.log('ERROR enabling 2FA: ' + JSON.stringify(enable2faRes));
      await context.close();
    }
  }

  await browser.close();
  console.log('');
  console.log('=== 2FA test flow complete ===');
})();
