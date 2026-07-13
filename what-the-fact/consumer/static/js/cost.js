/* cost.js — "What Parliament Costs Canadians" renderers.
 *
 * Consumes the live, cached cost API (the single source of truth in
 * ingest.parliament.cost — never recomputed here):
 *   GET /api/cost/summary          -> national "cost of Parliament"
 *   GET /api/cost/mp/<id>          -> one MP, 5-year breakdown
 *   GET /api/cost/senator/<id>     -> one senator, 5-year breakdown
 *
 * These are PUBLIC financial figures. Honesty rails are mandatory:
 *   - every figure is labelled "approximate" (the API `_note`),
 *   - the components are shown (never one opaque number),
 *   - the sources are cited (the API `_source`).
 *
 * Self-contained: no external CDN, no chart library. Bars are plain <div>s
 * sized by numeric percentages. XSS-safe: ALL API-derived text goes through
 * textContent and every node is built with createElement — innerHTML is never
 * set from API data. Style strings are static constants controlled here; only
 * clamped numbers are interpolated into inline sizes.
 */
(function (global) {
  "use strict";

  // --- palette (matches the WTF theme tokens) ---------------------------------
  var C = {
    indemnity: "#0ea5e9", // sky — base salary / sessional indemnity
    topup:     "#f59e0b", // amber — cabinet / role top-up
    office:    "#ef4444", // red (accent) — office expenses
    senator:   "#a855f7", // violet — senators (national split)
    mp:        "#0ea5e9", // sky — MPs (national split)
    track:     "rgba(148,163,184,0.14)",
    muted:     "#6b7280",
    text:      "#e5e7eb",
    subtle:    "#9ca3af"
  };

  function num(v) { var n = Number(v); return isFinite(n) ? n : 0; }

  function fmtCompact(v) {
    var n = num(v), sign = n < 0 ? "-" : "";
    n = Math.abs(n);
    if (n >= 1e9) return sign + "$" + (n / 1e9).toFixed(2) + "B";
    if (n >= 1e6) return sign + "$" + (n / 1e6).toFixed(1) + "M";
    if (n >= 1e3) return sign + "$" + Math.round(n / 1e3) + "k";
    return sign + "$" + Math.round(n);
  }

  function fmtFull(v) {
    var n = Math.round(num(v));
    try { return "$" + n.toLocaleString("en-CA"); }
    catch (e) { return "$" + n; }
  }

  // el("div", {cls, text, css, attrs:{}}) — text via textContent (safe),
  // css is a STATIC constant string, never API data.
  function el(tag, o) {
    o = o || {};
    var e = document.createElement(tag);
    if (o.cls) e.className = o.cls;
    if (o.text != null) e.textContent = String(o.text);
    if (o.css) e.style.cssText = o.css;
    if (o.attrs) { for (var k in o.attrs) if (o.attrs.hasOwnProperty(k)) e.setAttribute(k, o.attrs[k]); }
    return e;
  }

  function clear(node) { while (node && node.firstChild) node.removeChild(node.firstChild); }

  // A vertical stacked-bar chart. cols = [{label, sub, total, segs:[{value,color}]}]
  // Heights are numeric percentages of the largest total — no library, no CDN.
  function stackedChart(cols, opts) {
    opts = opts || {};
    var max = 0, i;
    for (i = 0; i < cols.length; i++) max = Math.max(max, num(cols[i].total));
    if (max <= 0) max = 1;

    var wrap = el("div", { css: "overflow-x:auto;-webkit-overflow-scrolling:touch;" });
    var row = el("div", {
      css: "display:flex;gap:10px;align-items:flex-end;min-width:280px;height:170px;padding-top:8px;"
    });

    cols.forEach(function (col) {
      var colWrap = el("div", { css: "flex:1 1 0;min-width:40px;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;height:100%;" });

      var valLabel = el("div", { text: fmtCompact(col.total), css: "font-size:10px;color:" + C.text + ";margin-bottom:4px;white-space:nowrap;font-weight:600;" });

      // fixed-height track so short bars still align to a common baseline
      var track = el("div", { css: "width:70%;max-width:46px;height:118px;display:flex;flex-direction:column;justify-content:flex-end;background:" + C.track + ";border-radius:3px 3px 0 0;overflow:hidden;" });
      var pctTotal = Math.max(2, Math.round((num(col.total) / max) * 100));
      var stack = el("div", { css: "width:100%;display:flex;flex-direction:column;justify-content:flex-end;" });
      stack.style.height = pctTotal + "%";

      (col.segs || []).forEach(function (seg) {
        var v = num(seg.value);
        if (v <= 0) return;
        var segPct = Math.max(1, Math.round((v / num(col.total || 1)) * 100));
        var s = el("div", { css: "width:100%;background:" + seg.color + ";" });
        s.style.height = segPct + "%";
        s.title = (seg.label ? seg.label + ": " : "") + fmtFull(v);
        stack.appendChild(s);
      });
      track.appendChild(stack);

      var yr = el("div", { text: col.label, css: "font-size:11px;color:" + C.subtle + ";margin-top:6px;letter-spacing:.03em;" });

      colWrap.appendChild(valLabel);
      colWrap.appendChild(track);
      colWrap.appendChild(yr);
      if (col.sub != null) colWrap.appendChild(el("div", { text: col.sub, css: "font-size:9px;color:" + C.muted + ";margin-top:2px;" }));
      row.appendChild(colWrap);
    });

    wrap.appendChild(row);
    return wrap;
  }

  function legend(items) {
    var box = el("div", { css: "display:flex;flex-wrap:wrap;gap:12px;margin-top:12px;" });
    items.forEach(function (it) {
      var pill = el("div", { css: "display:flex;align-items:center;gap:6px;font-size:10px;color:" + C.subtle + ";" });
      var dot = el("span", { css: "width:10px;height:10px;border-radius:2px;flex-shrink:0;background:" + it.color + ";" });
      pill.appendChild(dot);
      pill.appendChild(el("span", { text: it.label }));
      box.appendChild(pill);
    });
    return box;
  }

  // Honesty footer — approximate note + cited sources, both via textContent.
  function honestyBlock(note, source) {
    var box = el("div", { css: "margin-top:16px;padding-top:12px;border-top:1px solid rgba(148,163,184,0.18);" });
    if (note) {
      box.appendChild(el("div", {
        text: "⚠ " + note,
        css: "font-size:11px;color:" + C.subtle + ";line-height:1.7;margin-bottom:8px;"
      }));
    }
    if (source && typeof source === "object") {
      var srcWrap = el("div", { css: "font-size:10px;color:" + C.muted + ";line-height:1.7;" });
      srcWrap.appendChild(el("div", { text: "Sources", css: "text-transform:uppercase;letter-spacing:.08em;color:" + C.subtle + ";margin-bottom:4px;" }));
      var ul = el("ul", { css: "margin:0;padding-left:16px;" });
      var order = ["indemnity", "office_expenses", "senator_expenses"];
      order.forEach(function (key) {
        if (source[key]) ul.appendChild(el("li", { text: source[key], css: "margin-bottom:3px;" }));
      });
      // any extra keys not in the known order
      for (var k in source) {
        if (source.hasOwnProperty(k) && order.indexOf(k) === -1 && source[k]) {
          ul.appendChild(el("li", { text: source[k], css: "margin-bottom:3px;" }));
        }
      }
      srcWrap.appendChild(ul);
      box.appendChild(srcWrap);
    }
    return box;
  }

  function statTile(value, label, color) {
    var t = el("div", { css: "flex:1 1 130px;min-width:130px;background:rgba(148,163,184,0.06);border:1px solid rgba(148,163,184,0.16);border-radius:8px;padding:14px 16px;" });
    t.appendChild(el("div", { text: value, css: "font-size:22px;font-weight:700;color:" + (color || C.text) + ";line-height:1.1;" }));
    t.appendChild(el("div", { text: label, css: "font-size:10px;color:" + C.subtle + ";text-transform:uppercase;letter-spacing:.06em;margin-top:6px;" }));
    return t;
  }

  function errorMsg(target, msg) {
    clear(target);
    target.appendChild(el("div", {
      text: msg,
      css: "font-size:12px;color:" + C.muted + ";padding:16px;text-align:center;"
    }));
  }

  function getJSON(url) {
    return fetch(url, { credentials: "same-origin" }).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    });
  }

  // --- national "Cost of Parliament" -----------------------------------------
  function renderSummary(root) {
    if (!root) return;
    var headline = root.querySelector("[data-cost-headline]");
    var stats = root.querySelector("[data-cost-stats]");
    var chartBox = root.querySelector("[data-cost-chart]");
    var footer = root.querySelector("[data-cost-footer]");
    if (chartBox) errorMsg(chartBox, "Loading figures…");

    getJSON("/api/cost/summary").then(function (data) {
      var years = (data.by_year || []).slice().sort(function (a, b) { return num(a.year) - num(b.year); });
      if (!years.length) {
        if (chartBox) errorMsg(chartBox, "Cost figures are not available yet.");
        return;
      }
      var first = years[0], last = years[years.length - 1];
      var grand = data.grand_total_5yr;
      if (grand == null) { grand = 0; years.forEach(function (y) { grand += num(y.total); }); }

      // headline
      if (headline) {
        clear(headline);
        headline.appendChild(el("div", { text: fmtCompact(grand), css: "font-size:clamp(40px,9vw,72px);font-weight:800;color:" + C.office + ";line-height:1;letter-spacing:-.02em;" }));
        headline.appendChild(el("div", { text: fmtFull(grand) + " · approximate 5-year total (" + first.year + "–" + last.year + ")", css: "font-size:13px;color:" + C.subtle + ";margin-top:10px;" }));
      }

      // stat tiles: latest-year total, trend, per-member avg, member counts
      if (stats) {
        clear(stats);
        var lastTot = num(last.total);
        var firstTot = num(first.total) || 1;
        var trendPct = Math.round(((lastTot - firstTot) / firstTot) * 100);
        var trendStr = (trendPct >= 0 ? "+" : "") + trendPct + "%";
        var mpCount = num(last.mp_count), senCount = num(last.senator_count);
        var avg = last.avg_per_mp != null ? num(last.avg_per_mp) : (mpCount ? (num(last.mp_office_total) + num(last.mp_indemnity_total)) / mpCount : 0);

        stats.appendChild(statTile(fmtCompact(lastTot), last.year + " total cost", C.office));
        stats.appendChild(statTile(trendStr, "change " + first.year + "→" + last.year, trendPct >= 0 ? C.topup : C.indemnity));
        stats.appendChild(statTile(fmtCompact(avg), "avg per MP / year", C.text));
        var countStr = mpCount + (senCount ? " + " + senCount : "");
        stats.appendChild(statTile(countStr, senCount ? "MPs + senators" : "MPs", C.text));
      }

      // chart: one stacked bar per year (trend + MP/senator split in one view)
      if (chartBox) {
        clear(chartBox);
        var cols = years.map(function (y) {
          var mpInd = num(y.mp_indemnity_total), mpOff = num(y.mp_office_total), sen = num(y.senator_total);
          var tot = num(y.total) || (mpInd + mpOff + sen);
          return {
            label: String(y.year),
            total: tot,
            segs: [
              { value: mpInd, color: C.indemnity, label: "MP salary + top-ups" },
              { value: mpOff, color: C.office, label: "MP office expenses" },
              { value: sen, color: C.senator, label: "Senators" }
            ]
          };
        });
        chartBox.appendChild(el("div", { text: "Cost to taxpayers per year", css: "font-size:11px;color:" + C.subtle + ";text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px;" }));
        chartBox.appendChild(stackedChart(cols));
        var hasSen = years.some(function (y) { return num(y.senator_total) > 0; });
        var leg = [
          { color: C.indemnity, label: "MP salary + top-ups" },
          { color: C.office, label: "MP office expenses" }
        ];
        if (hasSen) leg.push({ color: C.senator, label: "Senators" });
        chartBox.appendChild(legend(leg));
      }

      if (footer) { clear(footer); footer.appendChild(honestyBlock(data._note, data._source)); }
    }).catch(function () {
      if (chartBox) errorMsg(chartBox, "Cost figures are temporarily unavailable.");
    });
  }

  // --- per-member panel (MP or senator) --------------------------------------
  // container carries data-kind ("mp"|"senator") and data-id (numeric id).
  function renderMember(container) {
    if (!container) return;
    var kind = container.getAttribute("data-kind") || "mp";
    var id = container.getAttribute("data-id");
    if (!id) { errorMsg(container, "No cost data for this member."); return; }
    errorMsg(container, "Loading cost figures…");

    getJSON("/api/cost/" + kind + "/" + encodeURIComponent(id)).then(function (data) {
      clear(container);
      var years = (data.years || []).slice().sort(function (a, b) { return num(a.year) - num(b.year); });
      if (!years.length) { errorMsg(container, "No cost figures available yet."); return; }

      // headline: 5-year total
      var head = el("div", { css: "display:flex;flex-wrap:wrap;align-items:baseline;gap:12px;margin-bottom:6px;" });
      head.appendChild(el("span", { text: fmtCompact(data.five_year_total), css: "font-size:30px;font-weight:800;color:" + C.office + ";line-height:1;" }));
      head.appendChild(el("span", { text: fmtFull(data.five_year_total) + " · approximate 5-year cost to taxpayers", css: "font-size:11px;color:" + C.subtle + ";" }));
      container.appendChild(head);

      // stacked bars per year
      var cols = years.map(function (y) {
        var ind = num(y.indemnity), top = num(y.top_up), off = num(y.office_total);
        var tot = num(y.total) || (ind + top + off);
        return {
          label: String(y.year),
          total: tot,
          sub: (y.served === false ? "not served" : null),
          segs: [
            { value: ind, color: C.indemnity, label: "Salary / indemnity" },
            { value: top, color: C.topup, label: "Role top-up" },
            { value: off, color: C.office, label: "Office expenses" }
          ]
        };
      });
      container.appendChild(stackedChart(cols));

      var hasTop = years.some(function (y) { return num(y.top_up) > 0; });
      var leg = [
        { color: C.indemnity, label: "Salary / indemnity" }
      ];
      if (hasTop) leg.push({ color: C.topup, label: "Role top-up" });
      leg.push({ color: C.office, label: "Office (travel · hospitality · contracts · staff)" });
      container.appendChild(legend(leg));

      // latest served year component breakdown
      var latest = null;
      for (var i = years.length - 1; i >= 0; i--) { if (years[i].served !== false) { latest = years[i]; break; } }
      if (latest) {
        var o = latest.office || {};
        var tbl = el("div", { css: "margin-top:14px;font-size:11px;color:" + C.subtle + ";" });
        tbl.appendChild(el("div", { text: latest.year + " breakdown", css: "text-transform:uppercase;letter-spacing:.08em;color:" + C.subtle + ";margin-bottom:6px;" }));
        var rows = [
          ["Salary / indemnity", latest.indemnity],
          ["Role top-up", latest.top_up],
          ["Office — travel", o.travel],
          ["Office — hospitality", o.hospitality],
          ["Office — contracts", o.contracts],
          ["Office — staff salaries", o.salaries],
          ["Total", latest.total]
        ];
        rows.forEach(function (r) {
          if (r[1] == null) return;
          if (num(r[1]) === 0 && r[0] !== "Total") return;
          var line = el("div", { css: "display:flex;justify-content:space-between;gap:16px;padding:3px 0;border-bottom:1px solid rgba(148,163,184,0.1);" + (r[0] === "Total" ? "font-weight:700;color:" + C.text + ";border-bottom:none;margin-top:2px;" : "") });
          line.appendChild(el("span", { text: r[0] }));
          line.appendChild(el("span", { text: fmtFull(r[1]) }));
          tbl.appendChild(line);
        });
        container.appendChild(tbl);
      }

      container.appendChild(honestyBlock(data._note, data._source));
    }).catch(function () {
      errorMsg(container, "Cost figures are temporarily unavailable.");
    });
  }

  function auto() {
    var root = document.querySelector("[data-cost-summary]");
    if (root) renderSummary(root);
    var members = document.querySelectorAll("[data-cost-member]");
    for (var i = 0; i < members.length; i++) renderMember(members[i]);
  }

  global.WTFCost = {
    renderSummary: renderSummary,
    renderMember: renderMember,
    fmtCompact: fmtCompact,
    fmtFull: fmtFull,
    auto: auto
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", auto);
  } else {
    auto();
  }
})(window);
