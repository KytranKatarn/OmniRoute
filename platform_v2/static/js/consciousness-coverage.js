// consciousness-coverage.js (#232)
(function () {
  const LANGS = ["en", "fr", "es", "pt", "de", "zh", "ar", "he"];

  function pct(n, d) { return d === 0 ? 0 : Math.round((n / d) * 100); }

  function band(p) {
    if (p >= 100) return "high";
    if (p >= 80) return "medium";
    return "low";
  }

  function removeAllChildren(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function makeCell(className, text, dataAttrs) {
    const el = document.createElement("div");
    el.className = className;
    el.textContent = text;
    if (dataAttrs) {
      for (const k in dataAttrs) {
        if (Object.prototype.hasOwnProperty.call(dataAttrs, k)) {
          el.setAttribute("data-" + k, String(dataAttrs[k]));
        }
      }
    }
    return el;
  }

  async function load() {
    const grid = document.getElementById("cov-grid");
    const banner = document.getElementById("cov-banner");
    if (!grid) return;
    let data;
    try {
      const r = await fetch("/tools/consciousness/api/translations/coverage-health", { credentials: "include" });
      if (!r.ok) return;
      data = await r.json();
    } catch (e) {
      if (banner) banner.textContent = "Failed to load coverage data";
      return;
    }
    render(grid, banner, data.coverage || [], data.open_gaps || []);
  }

  function render(grid, banner, coverage, gaps) {
    removeAllChildren(grid);

    // Header row: Source column + one per language
    grid.appendChild(makeCell("cov-head cov-source-label", "Source"));
    for (const l of LANGS) grid.appendChild(makeCell("cov-head", l.toUpperCase()));

    // Pivot coverage rows by source
    const bySource = {};
    for (const row of coverage) {
      (bySource[row.source] = bySource[row.source] || {})[row.language] = row;
    }
    for (const src of Object.keys(bySource).sort()) {
      grid.appendChild(makeCell("cov-cell cov-source-label", src));
      for (const l of LANGS) {
        const d = bySource[src][l] || { total: 0, approved: 0 };
        const p = pct(Number(d.approved || 0), Number(d.total || 0));
        const cell = makeCell("cov-cell", p + "%", { band: band(p) });
        cell.title = d.approved + "/" + d.total;
        grid.appendChild(cell);
      }
    }

    if (banner) {
      const gapCount = gaps.reduce(function (s, g) { return s + Number(g.n); }, 0);
      banner.textContent = "Open gaps: " + gapCount;
    }
  }

  async function scanNow(btn) {
    btn.disabled = true;
    btn.textContent = "Scanning...";
    try {
      const r = await fetch("/tools/consciousness/api/translations/full-scan", { method: "POST", credentials: "include" });
      const j = await r.json();
      btn.textContent = j.success ? "Scan started — check back in ~5 min" : "Failed";
    } catch (e) {
      btn.textContent = "Error: " + e.message;
    } finally {
      setTimeout(function () { btn.disabled = false; btn.textContent = "Scan Now"; }, 30000);
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    load();
    const btn = document.getElementById("cov-scan-btn");
    if (btn) btn.addEventListener("click", function () { scanNow(btn); });
  });
})();
