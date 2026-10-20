"""Exercise the queued-review browser watcher without a browser or network."""

from pathlib import Path
import subprocess


def test_completion_syncs_before_refresh_and_does_not_duplicate_watcher():
    html = (Path(__file__).resolve().parents[1] / "templates/tools/repair_bay.html").read_text()
    source = html.split("  var _codexWatchers = {};", 1)[1].split("  function queueCodexReview(", 1)[0]
    js = (
        """const assert = require('node:assert/strict');
const timers = [], calls = []; let refreshed = 0, stats = 0;
const API = '/api'; const window = {loadPRReviews: () => refreshed++};
function loadForgeStats() {stats++;}
function setTimeout(fn) {timers.push(fn);}
let statuses = ['running', 'ok'];
async function fetch(url, opts) {
 calls.push([url, opts && opts.method]);
 return {ok: true, json: async () => ({request_id: 'new', status: statuses.shift()})};
}
var _codexWatchers = {};
"""
        + source
        + """
async function flush() {for (let i = 0; i < 10; i++) await Promise.resolve();}
(async () => {
 _prWatchCodexReview(3986, 'new'); _prWatchCodexReview(3986, 'new');
 assert.equal(timers.length, 1);
 timers.shift()(); await flush();
 assert.equal(refreshed, 0); assert.equal(timers.length, 1);
 timers.shift()(); await flush();
 assert.equal(calls[2][1], 'POST');
 assert.ok(calls[2][0].endsWith('/pr-reviews/poll'));
 assert.equal(refreshed, 1); assert.equal(stats, 1);
 assert.equal(timers.length, 0);
 // A different request must not trigger a refresh using the old watcher's identity.
 statuses = ['ok'];
 _prWatchCodexReview(3986, 'old'); timers.shift()(); await flush();
 assert.equal(refreshed, 1);
})().catch(e => {console.error(e); process.exitCode = 1;});
"""
    )
    result = subprocess.run(["node", "-e", js], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
