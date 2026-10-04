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

console.log('  FAILURES:', fails.length ? fails.join(', ') : 'none');
process.exit(fails.length ? 1 : 0);
