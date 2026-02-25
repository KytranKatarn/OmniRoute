import { chromium } from 'playwright';
import path from 'path';

const SCREENSHOT_DIR = '/mnt/archie_brain/screenshots';
const BASE_URL = 'http://192.168.1.200:3000';

(async () => {
  const browser = await chromium.launch({ headless: true });

  // Test 1: Google OAuth button from login page
  console.log('=== Test 1: Google OAuth from Login Page ===');
  {
    const context = await browser.newContext({ viewport: { width: 1280, height: 720 } });
    const page = await context.newPage();

    await page.goto(BASE_URL + '/login', { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(2000);

    // Find and click Google button
    const googleBtn = page.locator('a[href*="google"], button:has-text("Google"), .google-btn, [class*="google"]').first();
    const googleHref = await googleBtn.getAttribute('href').catch(() => null);
    console.log('Google button href: ' + googleHref);

    // Click it and track where it redirects
    const [response] = await Promise.all([
      page.waitForEvent('response', { predicate: r => r.url().includes('google') || r.url().includes('/auth/google'), timeout: 10000 }).catch(() => null),
      googleBtn.click()
    ]);

    await page.waitForTimeout(3000);
    const finalUrl = page.url();
    console.log('After click URL: ' + finalUrl);

    if (finalUrl.includes('accounts.google.com')) {
      console.log('SUCCESS: Redirected to Google OAuth consent page');
    } else if (finalUrl.includes('/auth/google')) {
      console.log('SUCCESS: Hit our OAuth route (may redirect to Google)');
    } else {
      console.log('NOTE: URL is ' + finalUrl);
    }

    await page.screenshot({ path: path.join(SCREENSHOT_DIR, 'google-oauth-redirect.png'), fullPage: true });
    await context.close();
  }

  // Test 2: Google OAuth from signup page
  console.log('');
  console.log('=== Test 2: Google OAuth from Signup Page ===');
  {
    const context = await browser.newContext({ viewport: { width: 1280, height: 720 } });
    const page = await context.newPage();

    await page.goto(BASE_URL + '/signup', { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(2000);

    const googleBtn = page.locator('a[href*="google"], button:has-text("Google"), .google-btn, [class*="google"]').first();
    const googleHref = await googleBtn.getAttribute('href').catch(() => null);
    console.log('Google button href: ' + googleHref);

    await googleBtn.click();
    await page.waitForTimeout(3000);
    const finalUrl = page.url();
    console.log('After click URL: ' + finalUrl);

    if (finalUrl.includes('accounts.google.com')) {
      console.log('SUCCESS: Redirected to Google OAuth consent page');
    } else {
      console.log('NOTE: URL is ' + finalUrl);
    }

    await page.screenshot({ path: path.join(SCREENSHOT_DIR, 'google-oauth-signup-redirect.png'), fullPage: true });
    await context.close();
  }

  // Test 3: Direct access to /auth/google/login endpoint
  console.log('');
  console.log('=== Test 3: Direct /auth/google/login ===');
  {
    const context = await browser.newContext({ viewport: { width: 1280, height: 720 } });
    const page = await context.newPage();

    await page.goto(BASE_URL + '/auth/google/login', { waitUntil: 'networkidle', timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(3000);
    const finalUrl = page.url();
    console.log('Redirected to: ' + finalUrl);

    if (finalUrl.includes('accounts.google.com')) {
      console.log('SUCCESS: OAuth flow initiated correctly');
      // Check for correct client_id in URL
      if (finalUrl.includes('706224502104')) {
        console.log('SUCCESS: Correct Google Client ID in redirect');
      }
      // Check for callback URL
      if (finalUrl.includes('redirect_uri')) {
        const params = new URL(finalUrl).searchParams;
        console.log('Redirect URI: ' + params.get('redirect_uri'));
        console.log('Scope: ' + params.get('scope'));
      }
    }

    await page.screenshot({ path: path.join(SCREENSHOT_DIR, 'google-oauth-direct.png'), fullPage: true });
    await context.close();
  }

  await browser.close();
  console.log('');
  console.log('=== Google OAuth tests complete ===');
})();
