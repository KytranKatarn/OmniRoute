#!/usr/bin/env node
/**
 * A.R.C.H.I.E. Repair Bay merge-affordance behaviour audit
 *
 * The Python tests in test_forge_close_pr.py pin the AFFORDANCE LOGIC by reading the
 * source as text. That catches "someone deleted the branch", but it is blind to a
 * behavioural regression inside the branch — an early return, a swapped comparison, an
 * inverted flag — because the strings are all still present. That is exactly how a
 * merge button can go back to green-and-enabled while every source pin stays green.
 *
 * So this loads the REAL helpers out of the shipped JS and EXECUTES them. Nothing here
 * reimplements the rule under test: `src` is sliced from the file on disk, so a change
 * to the helper is a change to what runs below.
 *
 * Usage:
 *   node platform_v2/tests/repair_bay_merge_affordance.mjs
 *   node platform_v2/tests/repair_bay_merge_affordance.mjs --verbose
 *
 * Exit code 0 = every behaviour held. 1 = at least one behaviour regressed.
 */

import { readFileSync } from 'fs';
import { join } from 'path';

const VERBOSE = process.argv.includes('--verbose');

const SCRIPT_DIR = new URL('.', import.meta.url).pathname;
const PLATFORM_DIR = join(SCRIPT_DIR, '..');
const JS_PATH = join(PLATFORM_DIR, 'static', 'js', 'repair-bay-main.js');

// ---------------------------------------------------------------------------
// 1. Lift the real helpers out of the shipped file
// ---------------------------------------------------------------------------

const src = readFileSync(JS_PATH, 'utf8');

function lift(name) {
    const start = src.indexOf(`function ${name}(`);
    if (start < 0) throw new Error(`${name} is missing from ${JS_PATH}`);
    // Walk braces from the body to find the true end — a comment or a brace inside a
    // string literal must not decide where the function stops.
    let i = src.indexOf('{', start);
    let depth = 0;
    for (let j = i; j < src.length; j++) {
        if (src[j] === '{') depth++;
        else if (src[j] === '}') {
            depth--;
            if (depth === 0) return src.slice(start, j + 1);
        }
    }
    throw new Error(`could not find the end of ${name} — unbalanced braces`);
}

// A button stand-in: _prStyleMergeBtn only ever touches these four properties.
function fakeBtn() {
    return { style: { cssText: '' }, textContent: '', title: '', disabled: false, onclick: null };
}

const sandbox = { document: { createElement: fakeBtn } };
const factory = new Function(
    'document',
    `${lift('_prMergeAffordance')}\n${lift('_prStyleMergeBtn')}\nreturn { _prMergeAffordance, _prStyleMergeBtn };`
);
const { _prMergeAffordance, _prStyleMergeBtn } = factory(sandbox.document);

// ---------------------------------------------------------------------------
// 2. Cases
// ---------------------------------------------------------------------------

// Fixtures mirror what pr_review_service.merge_state() ACTUALLY emits. That function
// sets `mergeable` explicitly per state, and the pairing is load-bearing:
//
//   approved          -> mergeable=True
//   coverage_only     -> mergeable=True   (route still demands an ack)
//   changes_requested -> mergeable=False
//   reviewing         -> mergeable=False
//   awaiting_review   -> mergeable=False
//   closed / merged   -> mergeable=False
//
// `mergeable` means "the gate would not refuse outright" — the merge handler is still
// the gate. So the client contract is `can === !!ms.mergeable`, with `state` driving
// only the label and colour. Do NOT hand these fixtures an impossible pairing such as
// {state:'changes_requested', mergeable:true}: the server cannot produce it, and an
// assertion built on it will "prove" a bug that does not exist.
const MS = {
    approved:   { state: 'approved',          mergeable: true,  hint: 'F.O.R.G.E. approved' },
    coverage:   { state: 'coverage_only',     mergeable: true,  hint: '2 files not read',
                  dropped_files: ['a.js', 'b.js'] },
    changes:    { state: 'changes_requested', mergeable: false, hint: 'Needs changes' },
    reviewing:  { state: 'reviewing',         mergeable: false, hint: 'A review is running.' },
    awaiting:   { state: 'awaiting_review',   mergeable: false, hint: 'No stored verdict yet.' },
    closed:     { state: 'closed',            mergeable: false, hint: 'This PR is already merged.' },
};

const CASES = [
    // --- dependency order outranks everything, INCLUDING a missing merge_state ---
    ['unstamped row is still blocked by a declared dependency',
     () => _prMergeAffordance(null, true, 0, 'Blocked — after #12'),
     a => a.can === false && a.text.includes('#12')],

    ['unstamped row with no dependency stays legacy-enabled',
     () => _prMergeAffordance(null, false, 0),
     a => a.can === true && a.text === 'Merge'],

    ['a blocked row is disabled even when the verdict says mergeable',
     () => _prMergeAffordance(MS.approved, true, 0, 'Blocked — after #12'),
     a => a.can === false && a.text.includes('#12') && a.col === '#f97316'],

    ['a blocked row stays blocked when the verdict says NOT mergeable',
     () => _prMergeAffordance(MS.changes, true, 0, 'Blocked'),
     a => a.can === false],

    // --- verdict states: `can` follows mergeable, always ---
    ['an approved row offers an enabled Merge',
     () => _prMergeAffordance(MS.approved, false, 0),
     a => a.can === true && a.text === 'Merge'],

    ['changes requested is disabled',
     () => _prMergeAffordance(MS.changes, false, 0),
     a => a.can === false && /re-review/i.test(a.text)],

    ['reviewing is disabled',
     () => _prMergeAffordance(MS.reviewing, false, 0),
     a => a.can === false],

    ['awaiting review is disabled',
     () => _prMergeAffordance(MS.awaiting, false, 0),
     a => a.can === false && /waiting/i.test(a.text)],

    ['a closed PR is disabled',
     () => _prMergeAffordance(MS.closed, false, 0),
     a => a.can === false],

    ['a coverage demotion warns with the unread count',
     () => _prMergeAffordance(MS.coverage, false, 2),
     a => a.can === true && a.text === 'Merge (2 unread)'],

    // --- the hint must reach the button ---
    ['a disabled row carries the verdict hint as its title',
     () => { const b = _prStyleMergeBtn(fakeBtn(), _prMergeAffordance(MS.changes, false, 0));
             return { can: true, text: b.title }; },
     a => a.text === 'Needs changes'],

    // --- a disabled button must not be clickable ---
    ['a disabled button sets disabled and never wires onclick',
     () => { const b = _prStyleMergeBtn(fakeBtn(), _prMergeAffordance(MS.changes, false, 0));
             return { can: b.onclick === null, text: b.disabled === true }; },
     a => a.can && a.text],

    ['an enabled button is clickable',
     () => { const b = _prStyleMergeBtn(fakeBtn(), _prMergeAffordance(MS.approved, false, 0));
             return { can: b.disabled !== true, text: /pointer/.test(b.style.cssText) }; },
     a => a.can && a.text],

    ['the blocked style uses not-allowed',
     () => _prStyleMergeBtn(fakeBtn(), _prMergeAffordance(null, true, 0, 'Blocked')),
     b => /not-allowed/.test(b.style.cssText)],
];

// ---------------------------------------------------------------------------
// 3. Report
// ---------------------------------------------------------------------------

let failed = 0;
for (const [name, act, check] of CASES) {
    let ok = false;
    let detail = '';
    try {
        const result = act();
        ok = !!check(result);
        if (!ok) detail = ` → got ${JSON.stringify(result)}`;
    } catch (err) {
        detail = ` → threw ${err.message}`;
    }
    if (!ok) failed++;
    if (VERBOSE || !ok) console.log(`${ok ? '  ok  ' : 'FAIL  '}${name}${detail}`);
}

console.log(`\nrepair-bay merge affordance: ${CASES.length - failed}/${CASES.length} behaviours held`);
process.exit(failed === 0 ? 0 : 1);
