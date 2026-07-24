# KSO Power UI — ready-to-apply patch (#5140, follow-up to PR #2443)

The **collector is live** (PR #2443 merged + deployed): `host_monitor.py` now writes a `power`
block to `host_monitor_data.json` every cycle (verified: total ~204 W, 34% of 600 W, real
GPU+CPU measured, RAM/disk estimated). This patch is the **UI slice** — it could not be applied
from the isolated platform session because KSO (`/mnt/archie_brain/kytran-server-manager/`) is a
separate, git-less product outside the platform worktree. Apply these 3 edits directly in the KSO
source, then `cd /mnt/archie_brain/kytran-server-manager && docker compose up -d --build`.

Data shape available (confirmed live) from `host_monitor_data.json["power"]`:
```json
{"components":[{"name","watts","max_watts","class":"measured|estimated|unavailable","detail"}],
 "total_watts","total_class","psu_watts":600,"headroom_watts","load_pct","redline_pct":80}
```

---

## Edit 1 — backend: expose `power` on /api/hardware
File: `kytran_system_operations/routes/core_routes.py`, in `api_hardware()`'s `result` dict
(after `"upgrade_summary": upgrade_summary,`):
```python
            "upgrade_summary": upgrade_summary,
            "power": host_data.get("power", {}),   # #5140
        }
```
(`host_data` is already in scope from `load_host_monitor_data()`.)

## Edit 2 — template: a Server-Power panel
File: `kytran_system_operations/templates/dashboard.html` — insert right after the Hardware
Summary Cards `</div>` (the `stats-grid`), before `<!-- Two column layout for CPU and Memory sections -->`:
```html
        <!-- Server Power (#5140) -->
        <div class="panel" style="margin-bottom: 1.5rem;">
            <div class="panel-header">
                <div class="panel-title">
                    <i data-lucide="zap" class="sysops-icon-16"></i>
                    Server Power
                </div>
            </div>
            <div id="hw-power-content">
                <div class="sysops-text-muted">Loading power…</div>
            </div>
        </div>
```

## Edit 3 — JS: render the power card
File: `kytran_system_operations/static/js/system-operations.js`.
(a) In `renderHardwareTab(data)`, add after `renderHardwareSummary(data);`:
```javascript
    renderPowerSection(data.power || {});
```
(b) Add this function (XSS-safe — all text via textContent):
```javascript
function renderPowerSection(power) {
    var el = document.getElementById('hw-power-content');
    if (!el) return;
    el.textContent = '';
    if (!power || power.error || power.total_watts == null) {
        var m = document.createElement('div');
        m.className = 'sysops-text-muted';
        m.textContent = (power && power.error)
            ? ('Power data unavailable: ' + power.error)
            : 'Power data not available yet (host_monitor collecting…).';
        el.appendChild(m);
        return;
    }
    var psu = power.psu_watts || 600;
    var total = power.total_watts || 0;
    var pct = (power.load_pct != null) ? power.load_pct : Math.round(total / psu * 100);
    var redline = power.redline_pct || 80;

    var head = document.createElement('div');
    head.style.cssText = 'display:flex; align-items:baseline; gap:12px; flex-wrap:wrap; margin-bottom:10px;';
    var big = document.createElement('div');
    big.style.cssText = 'font-size:2rem; font-weight:700; color:#00ccff;';
    big.textContent = total + ' W';
    var sub = document.createElement('div');
    sub.className = 'sysops-text-muted';
    var headroom = (power.headroom_watts != null) ? power.headroom_watts : (psu - total);
    sub.textContent = pct + '% of ' + psu + ' W PSU  ·  ' + headroom + ' W headroom  ·  ' + (power.total_class || '');
    head.appendChild(big); head.appendChild(sub);
    el.appendChild(head);

    // PSU headroom bar with an 80% redline marker
    var barWrap = document.createElement('div');
    barWrap.style.cssText = 'position:relative; height:14px; background:rgba(255,255,255,0.08); border-radius:7px; overflow:hidden; margin-bottom:4px;';
    var over = pct >= redline;
    var fill = document.createElement('div');
    fill.style.cssText = 'height:100%; width:' + Math.min(pct, 100) + '%; background:' + (over ? '#ef4444' : (pct >= 60 ? '#f59e0b' : '#22c55e')) + '; border-radius:7px;';
    barWrap.appendChild(fill);
    var mark = document.createElement('div');
    mark.title = redline + '% redline';
    mark.style.cssText = 'position:absolute; top:0; bottom:0; left:' + redline + '%; width:2px; background:#ef4444;';
    barWrap.appendChild(mark);
    el.appendChild(barWrap);
    var rl = document.createElement('div');
    rl.className = 'sysops-text-muted';
    rl.style.cssText = 'font-size:11px; margin-bottom:12px;';
    rl.textContent = 'PSU 0–' + psu + ' W · red line = ' + redline + '% safe max';
    el.appendChild(rl);

    (power.components || []).forEach(function(c) {
        var row = document.createElement('div');
        row.style.cssText = 'display:flex; align-items:center; gap:10px; padding:4px 0; border-top:1px solid rgba(255,255,255,0.05);';
        var name = document.createElement('span');
        name.style.cssText = 'min-width:90px; font-weight:600;';
        name.textContent = c.name;
        var w = document.createElement('span');
        w.style.cssText = 'min-width:70px; color:#00ccff; font-family:monospace;';
        w.textContent = (c.watts != null ? c.watts : '—') + ' W';
        var meas = (c.class === 'measured');
        var tag = document.createElement('span');
        tag.style.cssText = 'font-size:10px; padding:1px 6px; border-radius:3px; ' +
            (meas ? 'background:rgba(34,197,94,0.2); color:#4ade80;' : 'background:rgba(148,163,184,0.15); color:#94a3b8;');
        tag.textContent = c.class;
        var det = document.createElement('span');
        det.className = 'sysops-text-muted';
        det.style.cssText = 'font-size:12px;';
        det.textContent = c.detail || '';
        row.appendChild(name); row.appendChild(w); row.appendChild(tag); row.appendChild(det);
        el.appendChild(row);
    });
}
```

## Deploy + verify
```bash
cd /mnt/archie_brain/kytran-server-manager && docker compose up -d --build
# then open server.kytranempowerment.com → Hardware tab → Server Power panel
```

---

# PART B — Watts HISTORY chart on the dashboard (mirrors the CPU chart)

KSO already has the whole history pipeline: `metrics_collector.py` samples → `record_metric(name, value)`
→ `system_metrics_history` table → `/api/history?type=<name>&hours=N` (core_routes.py:594) → Chart.js
on the dashboard (`cpuChart`/`memChart`/`gpuChart`). **The `/api/history` endpoint is generic, so
`type=power_total` needs NO backend change.** Four edits make a watts chart identical to CPU:

## Edit 4 — record watts to history
File: `kytran_system_operations/services/metrics_collector.py`, in `_collect_once()` right after the
`record_metric("cpu", cpu_pct)` block:
```python
            # Server power (#5140) — record total watts like cpu/memory/gpu
            pw = data.get("power", {})
            if isinstance(pw, dict) and pw.get("total_watts") is not None:
                record_metric("power_total", pw["total_watts"])
```

## Edit 5 — dashboard.html: a power chart-card
Add a 4th `chart-card` next to the cpu/mem/gpu canvases (near line 259–269), matching their markup
(copy the CPU card's title element for style consistency):
```html
            <div class="chart-card">
                <div class="chart-title">Server Power (W)</div>
                <canvas id="powerChart"></canvas>
            </div>
```

## Edit 6 — system-operations.js: init powerChart
(a) Declare the global next to `cpuChart` (wherever `var cpuChart, memChart, gpuChart;` is): add `powerChart`.
(b) After the `gpuChart = new Chart(...)` init (near line 772), add — note the y-axis is **watts vs the
600 W PSU ceiling**, not a 0–100% scale, so clone the config and override `y.max`:
```javascript
    // Server power chart (#5140) — y-axis is watts against the 600W PSU ceiling
    var powerChartConfig = JSON.parse(JSON.stringify(chartConfig));  // chartConfig has no functions → safe clone
    powerChartConfig.options.scales.y.max = 600;   // PSU capacity; add a redline annotation later if wanted
    powerChart = new Chart(document.getElementById('powerChart'), {
        ...powerChartConfig,
        data: {
            labels: ['Loading...'],
            datasets: [{ data: [null], borderColor: '#00ccff', backgroundColor: 'rgba(0,204,255,0.1)', fill: true, borderWidth: 2 }]
        }
    });
```

## Edit 7 — system-operations.js: load power history
In `loadHistoricalData()`, right after the CPU `try{…}` block (near line 945), add the same pattern:
```javascript
    // Load Server Power history (#5140) — identical shape to CPU
    try {
        const pRes = await fetch('/dashboard/api/history?type=power_total&hours=' + hours);
        if (pRes.ok) {
            const pJson = await pRes.json();
            if (pJson.success && pJson.data && pJson.data.values && pJson.data.values.length > 0 && powerChart) {
                const pLabels = pJson.data.labels;
                powerChart.data.labels = pLabels.map(l => formatHistoryTime(l, hours));
                powerChart.data.datasets[0].data = pJson.data.values;
                powerChart.update('none');
            }
        }
    } catch (e) { console.error('loadHistoricalData: power error:', e); }
```

## Result after Parts A+B
- **Hardware tab:** live "Server Power" panel — total watts + PSU-headroom gauge + per-component
  measured/estimated breakdown (Part A).
- **Dashboard:** a "Server Power (W)" line chart over 1h/24h/7d **exactly like the CPU history chart**
  (Part B) — the metrics collector records `power_total` every cycle; the existing history range
  controls (`historyHours`) drive it for free.
Optional v1.2: record `power_gpu`/`power_cpu` too for a stacked per-component history.
