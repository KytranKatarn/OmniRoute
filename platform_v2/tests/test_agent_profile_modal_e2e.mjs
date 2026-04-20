import { chromium } from 'playwright';

const BASE = process.env.ARCHIE_BASE || 'http://192.168.1.200:3000';
const ADMIN_USER = process.env.ARCHIE_ADMIN_USER || 'admin';
const ADMIN_PASS = process.env.ARCHIE_ADMIN_PASS || 'Kyt$13ran2025';

async function login(page) {
  await page.goto(BASE + '/login');
  await page.fill('input[name="username"]', ADMIN_USER);
  await page.fill('input[name="password"]', ADMIN_PASS);
  await Promise.all([
    page.waitForURL(/dashboard|tools/),
    page.click('button[type="submit"]'),
  ]);
}

async function openFirstAgent(page) {
  await page.goto(BASE + '/tools/department-hq#roster');
  // Roster cards use inline onclick="openAgentDetail(id)". Wait for them
  // to render then click the first one.
  await page.waitForSelector('[onclick*="openAgentDetail"]', { timeout: 10000 });
  await page.click('[onclick*="openAgentDetail"]');
  await page.waitForSelector('#agentDetailOverlay.active', { timeout: 5000 });
}

async function run() {
  const browser = await chromium.launch();
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  const fail = (m) => { throw new Error('FAIL: ' + m); };

  await login(page);

  // 1) Click a card → modal opens, name + portrait render
  await openFirstAgent(page);
  const nameText = await page.textContent('#agentDetailOverlay .apm-name');
  if (!nameText || !nameText.trim()) fail('name not rendered');

  // ── Snapshot agent state BEFORE mutation so we can restore in `finally` ──
  // Rationale: this test previously left `e2e-<ts>` strings in production
  // bio + system_prompt for whichever agent opened first (typically
  // A.R.C.H.I.E. id=2). Those strings landed in public-roster responses,
  // directors.json, and the website directory page — visibly broken until
  // a human noticed. Snapshot-and-restore prevents that class of bug.
  const agentId = await page.evaluate(() =>
    document.getElementById('agentDetailOverlay').getAttribute('data-agent-id')
  );
  if (!agentId) fail('could not read data-agent-id from overlay');
  const snapshot = await page.evaluate(async (id) => {
    const r = await fetch('/tools/department-hq/api/agent/' + id + '/profile',
      { credentials: 'same-origin' });
    if (!r.ok) throw new Error('snapshot fetch failed: ' + r.status);
    const data = await r.json();
    return { bio: data.agent.bio, system_prompt: data.agent.system_prompt };
  }, agentId);

  let restoreNeeded = false;

  try {
    // 2) EDIT toggle reveals inputs
    await page.click('#agentDetailOverlay [data-action="edit"]');
    await page.waitForSelector(
      '#agentDetailOverlay[data-mode="edit"]',
      { timeout: 3000 }
    );
    if (!(await page.$('textarea[data-edit="bio"]'))) {
      fail('bio textarea missing in edit mode');
    }

    // 3) Change bio, save, verify toast + view-mode persistence
    const stamp = 'e2e-' + Date.now();
    restoreNeeded = true;
    await page.fill('textarea[data-edit="bio"]', stamp);
    await page.click('#agentDetailOverlay [data-action="save"]');
    await page.waitForSelector('.apm-toast.show.ok', { timeout: 5000 });
    await page.waitForSelector(
      '#agentDetailOverlay[data-mode="view"]',
      { timeout: 3000 }
    );
    const bioView = await page.textContent('[data-view="bio"]');
    if (!bioView.includes(stamp)) fail('bio not persisted to view mode');

    // 4) Close + reopen persists
    await page.click('#agentDetailOverlay [data-action="close"]');
    await page.waitForTimeout(300);
    await page.click('[onclick*="openAgentDetail"]');
    await page.waitForSelector('#agentDetailOverlay.active');
    const bio2 = await page.textContent('[data-view="bio"]');
    if (!bio2.includes(stamp)) fail('reopen did not persist');

    // 5) Sensitive-field edit triggers confirm overlay
    await page.click('#agentDetailOverlay [data-action="edit"]');
    await page.fill('[data-edit="system_prompt"]', 'CONFIRM-TEST ' + stamp);
    await page.click('#agentDetailOverlay [data-action="save"]');
    await page.waitForSelector('#apmConfirmOverlay.active', { timeout: 3000 });
    await page.click('#apmConfirmOverlay [data-cx="ok"]');
    await page.waitForSelector('.apm-toast.show.ok', { timeout: 5000 });

    console.log('PASS: all 5 scenarios');
  } finally {
    // Always try to restore — even on partial failure so a broken test
    // run doesn't leave e2e-<ts> in a public-facing field.
    if (restoreNeeded) {
      try {
        const restored = await page.evaluate(async (args) => {
          const r = await fetch('/tools/department-hq/api/agent/' + args.id, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify({
              bio: args.bio ?? '',
              system_prompt: args.system_prompt ?? '',
            }),
          });
          return { ok: r.ok, status: r.status };
        }, { id: agentId, bio: snapshot.bio, system_prompt: snapshot.system_prompt });
        if (restored.ok) {
          console.log('restored bio + system_prompt for agent ' + agentId);
        } else {
          console.error(
            'WARNING: restore PATCH failed for agent ' + agentId +
            ' (HTTP ' + restored.status + '). Check DB manually.'
          );
        }
      } catch (restoreErr) {
        console.error(
          'WARNING: could not restore agent ' + agentId + ':',
          restoreErr.message,
          '— the agent may have e2e-<ts> in bio/system_prompt; restore manually.'
        );
      }
    }
    await browser.close();
  }
}

run().catch((e) => { console.error(e); process.exit(1); });
