#!/usr/bin/env node
/**
 * Bridge Command Module — Screenshot Capture
 *
 * Takes screenshots of the Bridge Command module at 3 breakpoints:
 *   - 374px  (Galaxy Z Fold5 front screen)
 *   - 717px  (Galaxy Z Fold5 unfolded / tablet)
 *   - 1280px (Desktop)
 *
 * Usage:
 *   node platform_v2/tests/bridge-screenshots.mjs
 */

import { chromium } from 'playwright';
import { mkdirSync } from 'fs';
import { join } from 'path';

const BASE_URL = 'http://192.168.1.200:3000';
const USERNAME = 'admin';
const PASSWORD = 'Kyt$13ran2025';
const OUTPUT_DIR = '/mnt/archie_brain/screenshots';

const VIEWPORTS = [
  { width: 374, height: 812,  label: '374' },
  { width: 717, height: 1024, label: '717' },
  { width: 1280, height: 900, label: '1280' },
];

mkdirSync(OUTPUT_DIR, { recursive: true });

async function main() {
  console.log('[bridge-screenshots] Launching Chromium...');
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: VIEWPORTS[2],
    ignoreHTTPSErrors: true,
  });
  const page = await context.newPage();

  // ---- Login ----
  console.log('[bridge-screenshots] Logging in...');
  await page.goto(`${BASE_URL}/login`, { waitUntil: 'networkidle', timeout: 15000 });
  await page.fill('input[name="username"]', USERNAME);
  await page.fill('input[name="password"]', PASSWORD);
  await page.click('button[type="submit"]');
  await page.waitForURL('**/dashboard**', { timeout: 15000 });
  console.log('[bridge-screenshots] Login successful, on dashboard.');

  // ---- Navigate to Bridge ----
  console.log('[bridge-screenshots] Navigating to /tools/bridge...');
  await page.goto(`${BASE_URL}/tools/bridge`, { waitUntil: 'networkidle', timeout: 20000 });

  // Extra wait for async content to settle (charts, stats, etc.)
  await page.waitForTimeout(3000);
  console.log('[bridge-screenshots] Page loaded.');

  // ---- Capture at each viewport ----
  for (const vp of VIEWPORTS) {
    console.log(`[bridge-screenshots] Setting viewport to ${vp.width}x${vp.height}...`);
    await page.setViewportSize({ width: vp.width, height: vp.height });
    // Allow layout to reflow
    await page.waitForTimeout(1000);

    const filename = `bridge-${vp.label}.png`;
    const filepath = join(OUTPUT_DIR, filename);
    await page.screenshot({ path: filepath, fullPage: true });
    console.log(`[bridge-screenshots] Saved: ${filepath}`);
  }

  await browser.close();
  console.log('[bridge-screenshots] Done. All 3 screenshots captured.');
}

main().catch((err) => {
  console.error('[bridge-screenshots] FAILED:', err.message);
  process.exit(1);
});
