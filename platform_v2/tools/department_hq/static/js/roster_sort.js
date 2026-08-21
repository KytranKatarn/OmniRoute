/* Roster sorting + grouping. Pure functions, no DOM — unit-tested in
   tests/test_roster_sort.mjs. Loaded as a plain script (globals). */

// DECIMAL columns (performance_score, success_rate) come back from the API
// as JSON strings, not numbers (psycopg2 Decimal -> JSON string). Without
// this, "100.00" < "99.98" < "5.50" lexicographically, so ascending sort
// never surfaces the true worst performer. See roster_routes.py — the
// server also converts these to real numbers; this is defense in depth for
// any future numeric column that arrives as a string.
function looksNumeric(v) {
    if (typeof v === 'number') return !Number.isNaN(v);
    if (typeof v !== 'string') return false;
    var s = v.trim();
    if (s === '') return false;
    // Whole-string numeric literal ONLY (optional sign, digits, at most one
    // decimal point). Deliberately strict: a version string like "1.2.3" or
    // an alphanumeric id like "AG-042" must FAIL this test and fall through
    // to the text comparator below — otherwise genuine text columns
    // (name/department/title) could get silently coerced into numeric
    // ordering.
    return /^-?\d+(\.\d+)?$/.test(s);
}

function compareAgents(a, b, key, dir) {
    var av = a[key], bv = b[key];
    var aNull = (av === null || av === undefined || av === '');
    var bNull = (bv === null || bv === undefined || bv === '');
    // NULLs always last, in BOTH directions. Never coerce to 0: an unscored
    // agent would render as the worst performer in the fleet.
    if (aNull && bNull) return 0;
    if (aNull) return 1;
    if (bNull) return -1;
    var cmp;
    if (looksNumeric(av) && looksNumeric(bv)) cmp = parseFloat(av) - parseFloat(bv);
    else cmp = String(av).localeCompare(String(bv));
    return dir === 'desc' ? -cmp : cmp;
}

function sortAgents(list, key, dir) {
    return list.slice().sort(function (a, b) { return compareAgents(a, b, key, dir); });
}

function groupAgents(list, groupKey) {
    var groups = {};
    list.forEach(function (a) {
        var k = a[groupKey] || '—';
        (groups[k] = groups[k] || []).push(a);
    });
    return groups;
}
