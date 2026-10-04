#!/usr/bin/env node
/*
 * Repair Bay — PR Review pane end-to-end click check.
 *
 * WHY THIS EXISTS, and why it is not part of the unit suite:
 * every bug in this area during the CODEX review work (2026-10-04) was invisible to
 * string-assertion tests and obvious the moment a browser clicked the thing:
 *
 *   - the CODEX pane read /issues/N/comments while CODEX posts to /pulls/N/reviews
 *   - the "==== CODEX REVIEW ====" marker is never posted, so matching it found nothing
 *   - tag-stripping silently mangled code spans in findings
 *   - a 502 rendered as "(No CodeRabbit review)" instead of an error
 *   - showPRDetail() threw on `codexBtn.style` and blanked the entire report pane
 *
 * The JS spec tests grep the template for strings. A file can contain every string you
 * grepped for and still throw on line 4222 at runtime. Only execution catches that.
 *
 * WHAT IT DOES: logs in as the agent account, opens Repair Bay -> PR Review, and for
 * each filter clicks the first row and asserts the right-hand detail pane actually
 * rendered content and logged no page errors.
 *
 * REQUIREMENTS: a running platform, and `playwright` in the repo's node_modules.
 * It is an OPERATOR check, not CI — it needs credentials and a live platform.
 *
 * CREDENTIALS: read from the agent credentials file, or ARCHIE_CLAUDE_PASSWORD from the
 * environment. Never printed, never logged, never passed on a command line.
 *
 * USAGE:
 *   node scripts/test_repair_bay_pr_pane.cjs
 *   ARCHIE_BASE_URL=http://127.0.0.1:3000 node scripts/test_repair_bay_pr_pane.cjs
 *
 * EXIT: 0 = every checked pane rendered. 1 = a check failed. 2 = could not run
 * (no playwright / no credentials) — deliberately NOT a pass, so a skipped check can
 * never be mistaken for a green one.
 */

'use strict';

const fs = require('fs');
const path = require('path');

const BASE = (process.env.ARCHIE_BASE_URL || 'http://127.0.0.1:3000').replace(/\/$/, '');
const CREDS = process.env.ARCHIE_CRED_FILE || '/mnt/archie_brain/credentials/agent_passwords.env';
const USER = 'claude';
const FILTERS = ['open', 'merged'];
// The pane must render SOMETHING substantive. 500 bytes is well below a real report and
// well above the ~70-byte "Select a PR to view the review" placeholder.
const MIN_PANE_BYTES = 500;

function bail(msg, code) {
  console.error('  SKIPPED: ' + msg);
  process.exit(code === undefined ? 2 : code);
}

function agentPassword() {
  if (process.env.ARCHIE_CLAUDE_PASSWORD) return process.env.ARCHIE_CLAUDE_PASSWORD;
  let raw;
  try {
    raw = fs.readFileSync(CREDS, 'utf8');
  } catch (e) {
    bail('no agent credentials at ' + CREDS + ' (set ARCHIE_CLAUDE_PASSWORD)');
  }
  const m = raw.match(/^ARCHIE_CLAUDE_PASSWORD=(.*)$/m);
  if (!m) bail('ARCHIE_CLAUDE_PASSWORD not present in ' + CREDS);
  return m[1].trim().replace(/^["']|["']$/g, '');
}

function loadPlaywright() {
  const candidates = [
    'playwright',
    path.join(__dirname, '..', 'node_modules', 'playwright'),
    '/mnt/archie_brain/node_modules/playwright',
  ];
  for (const c of candidates) {
    try { return require(c); } catch (e) { /* try next */ }
  }
  bail('playwright not found (looked in node_modules and ' + CREDS.replace(/credentials.*/, 'node_modules') + ')');
}

async function login(page, password) {
  await page.goto(BASE + '/login', { waitUntil: 'domcontentloaded' });
  await page.fill("input[name='username'], #username", USER);
  await page.fill("input[type='password'], #password", password);
  await page.click("button[type='submit'], button:has-text('ACCESS SYSTEM')");
  await page.waitForLoadState('networkidle');
  if (/\/login/.test(page.url())) throw new Error('login did not leave /login (agent account rejected?)');
}

(async () => {
  const { chromium } = loadPlaywright();
  const password = agentPassword();
  const browser = await chromium.launch();
  const ctx = await browser.newContext({
    // The running app must be asked for the CURRENT template, not a cached page. This
    // bit us: a stale cached page made a good fix look broken and a real break look fixed.
    extraHTTPHeaders: { 'Cache-Control': 'no-cache' },
  });
  const page = await ctx.newPage();
  const pageErrors = [];
  page.on('pageerror', (e) => pageErrors.push(e.message));
  page.on('console', (m) => { if (m.type() === 'error') pageErrors.push('console: ' + m.text()); });

  let failures = 0;
  try {
    await login(page, password);
    await page.goto(BASE + '/tools/repair-bay/?smoke=' + Date.now(), { waitUntil: 'networkidle' });

    const hasTab = await page.evaluate(() => !!document.getElementById('tab-pr-review'));
    if (!hasTab) throw new Error('PR Review tab markup not found — the pane was renamed or removed');
    await page.evaluate(() => window.switchTab && window.switchTab('pr-review'));
    await page.waitForTimeout(1200);

    for (const filter of FILTERS) {
      pageErrors.length = 0;
      const rows = await page.evaluate(async (f) => {
        document.getElementById('prFilter-' + f).click();
        await new Promise((r) => setTimeout(r, 2500));
        // [data-pr-row] only. Walking children by position once selected the
        // truncation NOTE instead of a PR, because the note is the first child.
        return document.querySelectorAll('#prReviewList > div[data-pr-row]').length;
      }, filter);

      if (!rows) {
        console.log('  SKIP  ' + filter + ': no tracked PRs in this filter (nothing to click)');
        continue;
      }

      const clicked = await page.evaluate(() => {
        const r = document.querySelector('#prReviewList > div[data-pr-row]');
        if (!r) return false;
        r.click();
        return true;
      });
      if (!clicked) { console.log('  FAIL  ' + filter + ': row present but not clickable'); failures++; continue; }
      await page.waitForTimeout(2500);

      const pane = await page.evaluate(() => {
        const el = document.getElementById('prReviewDetail');
        if (!el) return { missing: true };
        return {
          bytes: el.innerHTML.length,
          stillEmpty: el.className.includes('--empty'),
          text: (el.innerText || '').replace(/\s+/g, ' ').slice(0, 70),
        };
      });

      const errs = pageErrors.slice();
      if (pane.missing) {
        console.log('  FAIL  ' + filter + ': #prReviewDetail is missing from the DOM');
        failures++;
      } else if (pane.stillEmpty) {
        // This is the exact fingerprint of the showPRDetail crash: the handler clears
        // --empty, then throws, so the pane is blank rather than showing its placeholder.
        console.log('  FAIL  ' + filter + ': pane still flagged empty after clicking a row');
        failures++;
      } else if (pane.bytes < MIN_PANE_BYTES) {
        console.log('  FAIL  ' + filter + ': pane rendered only ' + pane.bytes + ' bytes (below ' + MIN_PANE_BYTES + ') — likely truncated');
        failures++;
      } else if (errs.length) {
        console.log('  FAIL  ' + filter + ': pane rendered but JS threw: ' + errs[0].slice(0, 80));
        failures++;
      } else {
        console.log('  ok    ' + filter + ': pane rendered ' + pane.bytes + ' bytes — "' + pane.text + '"');
      }
    }
  } catch (e) {
    console.log('  FAIL  harness error: ' + e.message);
    failures++;
  } finally {
    await browser.close();
  }

  if (failures) {
    console.error('  ' + failures + ' check(s) FAILED');
    process.exit(1);
  }
  console.log('  all checks passed');
  process.exit(0);
})();
