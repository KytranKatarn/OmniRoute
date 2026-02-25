import { chromium } from 'playwright';

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage();
await page.setViewportSize({ width: 1280, height: 900 });

// Login
await page.goto('http://192.168.1.200:3000/login');
await page.fill('input[name="username"]', 'admin');
await page.fill('input[name="password"]', 'Kyt$13ran2025');
await page.click('button[type="submit"]');
await page.waitForLoadState('networkidle');

// Navigate to Consciousness module
await page.goto('http://192.168.1.200:3000/tools/consciousness/');
await page.waitForLoadState('networkidle');
await page.waitForTimeout(2000);

// Click Languages tab
const langTab = page.locator('button.tab-btn[data-tab="languages"]');
await langTab.click();
await page.waitForTimeout(2000);

// Debug: check what's visible
const dropdown = page.locator('#ls-target-lang');
const isVisible = await dropdown.isVisible();
console.log('Dropdown visible:', isVisible);

if (!isVisible) {
    // Take debug screenshot
    await page.screenshot({ path: '/mnt/archie_brain/languages-tab-debug.png', fullPage: false });
    console.log('Debug screenshot saved');
} else {
    // Select Hebrew
    await dropdown.selectOption('he');
    await page.waitForTimeout(2000);
    await page.screenshot({ path: '/mnt/archie_brain/languages-tab-hebrew.png', fullPage: false });
    console.log('Hebrew screenshot saved');
}

await browser.close();
