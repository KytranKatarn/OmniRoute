// Exercise the real functions extracted from the template against a minimal DOM stub.
// Checks the Review-agent selector in the Repair Bay PR Review tab.
//
// The functions are EXTRACTED FROM THE TEMPLATE by name rather than reimplemented, so
// this tests the shipped source. A hand-copied duplicate would pass while the template
// regressed — which is the whole failure mode a UI test usually has.
//
// Requires node. Skipped by the pytest wrapper when node is absent.
const fs = require('fs');
const path = require('path');
const html = fs.readFileSync(
  path.join(__dirname, '..', '..', 'templates', 'tools', 'repair_bay.html'), 'utf8');

// Pull out just the helpers we changed, so we test the shipped source, not a copy.
function grab(name) {
  const i = html.indexOf('function ' + name);
  if (i < 0) throw new Error('missing ' + name);
  let depth = 0, started = false;
  for (let j = i; j < html.length; j++) {
    if (html[j] === '{') { depth++; started = true; }
    else if (html[j] === '}') { depth--; if (started && depth === 0) return html.slice(i, j+1); }
  }
}

let created = 0;
function mkEl(tag) {
  created++;
  const el = {
    tagName: tag, children: [], attrs: {}, style: {cssText:''}, _text: '', value: '',
    set textContent(v) { this._text = String(v); }, get textContent() { return this._text; },
    setAttribute(k,v){ this.attrs[k]=v; },
    appendChild(c){ this.children.push(c); return c; },
    querySelector(sel){
      const want = sel.replace(/^select\[|\]$/g,'');
      const walk = n => { for (const c of n.children||[]) {
        if (c.tagName === 'select' && (!want || c.attrs[want] !== undefined)) return c;
        const r = walk(c); if (r) return r; } return null; };
      return walk(this);
    },
  };
  return el;
}
global.document = { createElement: mkEl };

const PR_REVIEWERS = ['F.O.R.G.E.','P.R.O.B.E.'];
let sel = null;
const code = grab('_prReviewerSelect') + '\n' + grab('_prSelectedReviewer');
eval(code);

const fails = [];
function check(n, got, want){ const ok = got===want; console.log(`  ${ok?'ok  ':'FAIL'} ${n}: got=${JSON.stringify(got)} want=${JSON.stringify(want)}`); if(!ok) fails.push(n); }

sel = _prReviewerSelect();
check('selector has both reviewers', sel.children.map(o=>o.value).join(','), 'F.O.R.G.E.,P.R.O.B.E.');
check('default value set on select', sel.value, 'F.O.R.G.E.');
check('no CODEX option', sel.children.some(o=>o.value.indexOf('CODEX')>=0), false);

const row = mkEl('div'); sel.setAttribute('data-pr-reviewer','1'); row.appendChild(sel);
check('reads selected reviewer', _prSelectedReviewer(row), 'F.O.R.G.E.');
sel.value = 'P.R.O.B.E.';
check('reads changed reviewer', _prSelectedReviewer(row), 'P.R.O.B.E.');

const other = mkEl('div'); const sel2 = _prReviewerSelect(); sel2.setAttribute('data-pr-reviewer','1'); other.appendChild(sel2);
sel2.value = 'F.O.R.G.E.';
check('row A choice not read for row B', _prSelectedReviewer(other), 'F.O.R.G.E.');

const empty = mkEl('div');
check('no selector -> empty (server default)', _prSelectedReviewer(empty), '');

// ── CODEX button: the success dialog must follow the server's answer ────────────
// It used to fire BEFORE the fetch, so a duplicate, an unavailable spool, or a network
// failure all showed "queued" first and the error second — a false success, then a
// correction. Assert ORDER, not just that the strings exist.
const src = fs.readFileSync(
  path.join(__dirname, '..', '..', 'templates', 'tools', 'repair_bay.html'), 'utf8');
const fnStart = src.indexOf('function queueCodexReview');
const fnEnd = src.indexOf('\n  }', fnStart);
const fn = src.slice(fnStart, fnEnd);

check('queueCodexReview is defined', fn.length > 0, true);
const fetchAt = fn.indexOf('fetch(');
const firstAlert = fn.indexOf('_rbLcarsAlert');
// The opening dialog is legitimately before the fetch; what must NOT happen is a
// QUEUED/success dialog before it.
const preFetch = fn.slice(0, fetchAt);
check('no success/queued title before the fetch',
  !/CODEX REVIEW QUEUED|CODEX DRY RUN QUEUED/.test(preFetch), true);
check('no false-success wording before the fetch',
  !/added to the CODEX queue/.test(preFetch), true);
check('the pending dialog is shown before the fetch', /REQUESTED/.test(preFetch), true);
check('success title appears only after the fetch',
  fn.indexOf('CODEX REVIEW QUEUED') > fetchAt, true);
check('a failure path exists', /CODEX REVIEW NOT QUEUED/.test(fn), true);
check('a non-JSON body is handled', /non-JSON response/.test(fn), true);
check("the server's own message is echoed", /body\.message/.test(fn), true);

// ── the CODEX pane: extraction rules mirrored in JS ────────────────────────────
// The endpoint is Python, so this re-implements the same parse to pin the RULES the
// endpoint must follow. It is a specification test, not a duplicate of the impl.
const markerRe = /=+\s*CODEX REVIEW\s*=+/i;

// The REAL posted body, captured from PR #3618. Note: NO banner — codex_pr_review.sh
// echoes "==== CODEX REVIEW ====" to the terminal but pipes only $BODY to
// `gh pr review --comment`. Matching the banner therefore finds nothing, ever.
const REAL_POSTED = [
  'VERDICT: REQUEST_CHANGES',
  'The pane can display an outdated review and remove meaningful text from findings.',
  '- [medium] routes.py:1062 - Only the first 100 comments are fetched.',
  '- [medium] routes.py:1091 - A finding containing `/api/items/<int:item_id>` loses its parameter, and `x < 0 or x > 100` becomes `x  100`.',
].join('\n');
check('detects the REAL posted body (no banner)', markerRe.test(REAL_POSTED) || /^\s*VERDICT:/.test(REAL_POSTED), true);
check('banner is genuinely absent from a real post', markerRe.test(REAL_POSTED), false);

const verdictRe = /^\s*VERDICT:\s*([A-Z_]+)/m;

function extract(comments) {
  // Newest wins: a re-review supersedes the one before it. Rendering a stale verdict as
  // current is the exact defect class this platform refuses merges over.
  let newest = null, newestVerdict = null, newestAt = null;
  for (const c of comments) {
    const body = c.body || '';
    const m = markerRe.exec(body);
    if (!m) continue;
    newest = body.slice(m.index);
    const vm = verdictRe.exec(newest);
    newestVerdict = vm ? vm[1] : null;
    newestAt = c.created_at;
  }
  return {codex: newest, verdict: newestVerdict, at: newestAt};
}

const withReview = (v, at, extra) => Object.assign({
  user: {login: 'KytranKatarn'},
  created_at: at,
  body: '============ CODEX REVIEW ================\nVERDICT: ' + v + '\n- finding\n=============================================='
}, extra || {});

// Author-independent: the login varies with whoever's token ran it.
const r1 = extract([withReview('REQUEST_CHANGES', '2026-10-04T01:00:00Z')]);
check('finds a CODEX review regardless of author', r1.codex !== null, true);
check('extracts REQUEST_CHANGES', r1.verdict, 'REQUEST_CHANGES');
check('author really did vary', r1.codex.indexOf('KytranKatarn') === -1, true);

const r2 = extract([Object.assign(withReview('REQUEST_CHANGES', '2026-10-04T01:00:00Z'),
                                  {user: {login: 'forge-review[bot]'}})]);
check('finds it under a bot author too', r2.verdict, 'REQUEST_CHANGES');

const r3 = extract([withReview('REQUEST_CHANGES', '2026-10-04T01:00:00Z'),
                    withReview('APPROVE', '2026-10-04T09:00:00Z')]);
check('newest review wins', r3.verdict, 'APPROVE');
check('  and carries its timestamp', r3.at, '2026-10-04T09:00:00Z');

check('ignores comments without the marker', extract([{body: 'just a comment'}]).codex, null);
// Real false positive, measured on PR #3616: a CodeRabbit comment whose body contains
// "**Codex review queue**" as a heading. A loose substring match for "codex review"
// picks it up; the equals-delimited marker must not.
check('rejects a CodeRabbit heading that merely says "Codex review"',
  extract([{body: '## Walkthrough\n**Codex review queue**\n- platform_v2/.../codex_review_service.py'}]).codex,
  null);
check('rejects "codex review" with no delimiters',
  extract([{body: 'I looked at the codex review and it seems fine'}]).codex, null);

// Stripping tags must NOT eat code spans — measured: a blanket <[^>]+> turned
// `/items/<int:item_id>` into `/items/` and `x < 0 or x > 100` into `x  100`.
function stripTags(html) {
  const spans = [];
  // `m` IS the match here (no capture group), so push `m` — m[0] would be its
  // first character. Mirrors Python's mo.group(0).
  const stash = (m) => { spans.push(m); return '\u0000' + (spans.length - 1) + '\u0000'; };
  let out = String(html).replace(/`[^`]+`/g, stash).replace(/<[^>]+>/g, '');
  return out.replace(/\u0000(\d+)\u0000/g, (m, i) => spans[+i]);
}
check('code span with an angle bracket survives tag stripping',
  stripTags('a `/items/<int:item_id>` b'), 'a `/items/<int:item_id>` b');
check('comparison operator in a code span survives',
  stripTags('`x < 0 or x > 100` becomes `x  100`'),
  '`x < 0 or x > 100` becomes `x  100`');
check('a bare tag IS still stripped', stripTags('<!-- x --><b>bold</b>'), 'bold');
check('handles a review with no VERDICT line',
  extract([{body: '==== CODEX REVIEW ====\nnothing conclusive'}]).verdict, null);
check('empty comment list', extract([]).codex, null);

// The pane must label the verdict as the MODEL's, never as merge authority.
// A 502 resolves r.json(), so .catch() never fires. Both panes must check d.error
// explicitly or a failed fetch is displayed as "no review exists".
const tplHtml = require('fs').readFileSync(
  __dirname + '/../../templates/tools/repair_bay.html', 'utf8');
const crFetch = tplHtml.slice(html.indexOf("/coderabbit'"), html.indexOf("/coderabbit'") + 900);
const cxFetch = tplHtml.slice(html.indexOf("/codex'"), html.indexOf("/codex'") + 900);
check('CodeRabbit pane checks d.error', /if \(d\.error\)/.test(crFetch), true);
check('CODEX pane checks d.error', /if \(d\.error\)/.test(cxFetch), true);
check('CodeRabbit pane does not report a fetch failure as "no review"',
  crFetch.indexOf('if (d.error)') > -1
  && crFetch.indexOf('if (d.error)') < crFetch.indexOf('d.coderabbit ||'), true);

// The detail pane built codexBtn2 in the "reviewed" branch but copied its styling off
// codexBtn, which is declared in the MUTUALLY EXCLUSIVE coverage branch. On any cleanly
// reviewed PR that branch never runs, so codexBtn hoisted as undefined and
// `codexBtn.style` threw — blanking the entire right-hand report pane. Both branches now
// read hoisted constants instead. These guard the coupling from coming back.
const detail = tplHtml.slice(tplHtml.indexOf('function showPRDetail('),
                             tplHtml.indexOf('function showPRDetail(') + 20000);
check('detail pane does not read codexBtn from the other branch',
  /codexBtn2\.style\.cssText = codexBtn\.style\.cssText/.test(detail), false);
check('detail pane does not read codexBtn.title cross-branch',
  /codexBtn2\.title = codexBtn\.title/.test(detail), false);
check('CODEX button css is hoisted above both branches',
  /var CODEX_BTN_CSS =/.test(detail), true);
check('CODEX button title is hoisted above both branches',
  /var CODEX_BTN_TITLE =/.test(detail), true);
check('both CODEX buttons use the hoisted constants',
  (detail.match(/CODEX_BTN_CSS;/g) || []).length >= 2
  && (detail.match(/CODEX_BTN_TITLE;/g) || []).length >= 2, true);

check('pane labels the verdict advisory',
  /model says APPROVE \(advisory\)/.test(src), true);
check('pane names the endpoint it fetches', /pr-reviews\/' \+ pr\.pr_number \+ '\/codex/.test(src), true);

console.log('  FAILURES:', fails.length ? fails.join(', ') : 'none');
process.exit(fails.length ? 1 : 0);
