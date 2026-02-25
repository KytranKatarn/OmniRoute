import { chromium } from 'playwright';

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
const page = await ctx.newPage();
await page.goto('http://192.168.1.200:3000/login');
await page.waitForTimeout(1500);
await page.fill('input[name="username"]', 'admin');
await page.fill('input[name="password"]', 'Kyt$13ran2025');
await page.click('button[type="submit"]');
await page.waitForTimeout(2000);
try { await page.click('text=PASSER', { timeout: 3000 }); } catch(e) {}
await page.waitForTimeout(3000);

// Remove boot overlay via DOM manipulation
await page.locator('[id*="boot"]').evaluateAll(els => els.forEach(el => el.remove()));
await page.waitForTimeout(500);

// Screenshot just the priority stations element
const el = page.locator('#featured-modules');
const count = await el.count();
if (count > 0) {
    await el.screenshot({ path: '/tmp/priority-stations-focused.png' });
    console.log('Captured featured-modules');
} else {
    console.log('featured-modules not found, doing full page');
    await page.screenshot({ path: '/tmp/priority-stations-focused.png', fullPage: true });
}

// Dump the actual text content of the featured cards
const cards = await page.locator('.featured-card').evaluateAll(cards => cards.map(c => ({
    name: c.querySelector('.featured-card-name')?.textContent?.trim(),
    desc: c.querySelector('.featured-card-desc')?.textContent?.trim(),
    nameI18n: c.querySelector('.featured-card-name')?.getAttribute('data-i18n'),
    descI18n: c.querySelector('.featured-card-desc')?.getAttribute('data-i18n')
})));
console.log(JSON.stringify(cards, null, 2));

await browser.close();
