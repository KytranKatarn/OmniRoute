import { chromium } from 'playwright';

const b = await chromium.launch({ headless: true });
const c = await b.newContext({ viewport: { width: 1280, height: 900 } });
const p = await c.newPage();

await p.goto('http://192.168.1.200:3000/login', { waitUntil: 'networkidle', timeout: 15000 });
await p.fill('#username', 'admin');
await p.fill('#password', 'Kyt$13ran2025');
await p.click('#loginBtn');
await p.waitForURL(u => u.pathname !== '/login', { timeout: 10000 });

const results = [];
function test(name, pass, detail) {
  results.push({ name, pass, detail: detail || '' });
}

// 1. Test async embedding — should return immediately with job_id
const start = Date.now();
const embedResp = await p.evaluate(async () => {
  const r = await fetch('/tools/consciousness/api/processing/generate-embeddings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ batch_size: 10 })
  });
  return { status: r.status, data: await r.json() };
});
const elapsed = Date.now() - start;
test('Embedding returns immediately (< 3s)', elapsed < 3000, `${elapsed}ms`);
test('Embedding returns job_id', !!embedResp.data.job_id || embedResp.data.message?.includes('already embedded'),
  embedResp.data.job_id ? `job #${embedResp.data.job_id}` : embedResp.data.message);

// 2. Test duplicate prevention — second call should get 409
if (embedResp.data.job_id) {
  const dup = await p.evaluate(async () => {
    const r = await fetch('/tools/consciousness/api/processing/generate-embeddings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ batch_size: 10 })
    });
    return { status: r.status, data: await r.json() };
  });
  test('Duplicate blocked with 409', dup.status === 409,
    `status=${dup.status}, duplicate=${dup.data.duplicate}`);
} else {
  test('Duplicate blocked with 409', true, 'Skipped (no items to embed)');
}

// 3. Test async analysis — should return immediately
const analysisResp = await p.evaluate(async () => {
  const r = await fetch('/tools/consciousness/api/processing/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ category: 'conversations', batch_size: 5 })
  });
  return { status: r.status, data: await r.json() };
});
test('Analysis returns immediately', analysisResp.data.success === true || analysisResp.data.message?.includes('No items'),
  analysisResp.data.message || `job #${analysisResp.data.job_id}`);

// 4. Navigate to consciousness and verify station status renders
await p.goto('http://192.168.1.200:3000/tools/consciousness', { waitUntil: 'networkidle', timeout: 15000 });
await p.waitForTimeout(9000);
await p.evaluate(() => { const o = document.getElementById('bootOverlay'); if (o) o.remove(); });
await p.waitForTimeout(1000);

// Switch to GitHub tab (triggers checkActiveJobs)
await p.click('[data-tab="github"]');
await p.waitForTimeout(3000);

// Check station status element exists and has content
const stationStatus = await p.evaluate(() => {
  const el = document.getElementById('stationStatus');
  return el ? el.innerHTML : null;
});
test('Station status element rendered', stationStatus !== null && stationStatus.length > 0,
  stationStatus ? `${stationStatus.length} chars` : 'empty or missing');

// Check "Bridge Station" text is in the station status
test('Station status shows Bridge Station label',
  stationStatus && stationStatus.indexOf('Bridge Station') > -1,
  stationStatus ? stationStatus.substring(0, 100) : 'empty');

// Buttons should be enabled (no running jobs or job is our test one)
const reindexEnabled = await p.locator('#btnReindexAll').isEnabled();
const embedEnabled = await p.locator('#btnEmbedGH').isEnabled();
test('Buttons accessible', reindexEnabled || embedEnabled, `reindex=${reindexEnabled}, embed=${embedEnabled}`);

// 5. Check Bridge jobs endpoint shows job tracked
if (embedResp.data.job_id) {
  const jobDetail = await p.evaluate(async (jid) => {
    const r = await fetch('/tools/starbase/api/bridge/jobs/' + jid);
    return await r.json();
  }, embedResp.data.job_id);
  test('Bridge tracks embedding job', jobDetail.success === true,
    `status=${jobDetail.job?.status}, agent=${jobDetail.job?.agent_name}`);
}

await p.screenshot({ path: '/mnt/archie_brain/screenshots/async-jobs-test.png', fullPage: true });

let passed = 0, failed = 0;
for (const r of results) {
  const icon = r.pass ? '✓' : '✗';
  console.log(`${icon} ${r.name}${r.detail ? ' — ' + r.detail : ''}`);
  if (r.pass) passed++; else failed++;
}
console.log(`\n${passed}/${results.length} passed, ${failed} failed`);

await b.close();
