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
      // A PARTIAL year (e.g. the current year to date) sits in the same row as the full years but is
      // dimmed + dashed so nobody reads it as a complete year.
      if (col.partial) {
        stack.style.opacity = "0.55";
        track.style.outline = "1px dashed " + C.muted;
        track.style.outlineOffset = "-1px";
      }

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
        var winLabel = (data.window && data.window.label) ? data.window.label : ("5-year total, " + first.year + "–" + last.year);
        headline.appendChild(el("div", { text: fmtFull(grand) + " · approximate — " + winLabel, css: "font-size:13px;color:" + C.subtle + ";margin-top:10px;" }));
        var minG = num(data.ministerial_grand_5yr);
        if (minG > 0) {
          headline.appendChild(el("div", {
            text: "＋ " + fmtFull(minG) + " ministerial travel & hospitality (borne centrally — not in the total above) · combined ≈ " + fmtFull(num(data.combined_grand_5yr) || (grand + minG)),
            css: "font-size:12px;color:" + C.topup + ";margin-top:8px;font-weight:600;"
          }));
        }
      }

      // addenda — disclosed partial years (e.g. the current year to date), shown for
      // completeness + split by chamber + projected, NEVER folded into the headline total.
      var addBox = root.querySelector("[data-cost-addenda]");
      if (addBox) {
        clear(addBox);
        (data.addenda || []).forEach(function (a) {
          var qs = (a.quarters || []).join(", ");
          var kind = a.kind === "latest_ytd" ? "year-to-date" : "partial year";
          var wrap = el("div", { css: "margin-top:8px;padding-top:8px;border-top:1px solid rgba(148,163,184,0.1);" });
          var head = el("div", { css: "font-size:12px;line-height:1.6;" });
          head.appendChild(el("span", { text: "＋ " + a.year + " " + kind + (qs ? " (" + qs + ")" : "") + ": ", css: "color:" + C.text + ";font-weight:600;" }));
          head.appendChild(el("span", { text: fmtFull(a.combined) + " disclosed so far — shown for completeness, not in the total above.", css: "color:" + C.subtle + ";" }));
          wrap.appendChild(head);
          // chamber split — MP vs Senate vs ministerial
          var split = el("div", { css: "font-size:11px;color:" + C.subtle + ";margin-top:3px;padding-left:14px;" });
          var splitTxt = "House of Commons " + fmtFull(a.mp) + (a.mp_count ? " (" + a.mp_count + " MPs)" : "")
            + "  ·  Senate " + fmtFull(a.senator) + (a.senator_count ? " (" + a.senator_count + " senators)" : "");
          if (num(a.ministerial) > 0) splitTxt += "  ·  ministerial " + fmtFull(a.ministerial);
          split.appendChild(el("span", { text: splitTxt }));
          wrap.appendChild(split);
          // projected full year — only for the current year; annualized once >=2 quarters land
          if (a.projected && a.projected.combined) {
            var fq = a.projected.from_quarters;
            wrap.appendChild(el("div", {
              text: "↗ projected full year ≈ " + fmtFull(a.projected.combined) + " (House " + fmtFull(a.projected.parliamentary) + " + ministerial " + fmtFull(a.projected.ministerial) + ") — annualized from " + fq + " quarter" + (fq === 1 ? "" : "s") + "; estimate, actuals will differ",
              css: "font-size:11px;color:" + C.topup + ";margin-top:3px;padding-left:14px;line-height:1.5;"
            }));
          } else if (a.kind === "latest_ytd") {
            wrap.appendChild(el("div", {
              text: "↗ a full-year projection appears here once ≥2 quarters are disclosed",
              css: "font-size:11px;color:" + C.muted + ";margin-top:3px;padding-left:14px;"
            }));
          }
          addBox.appendChild(wrap);
        });
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
      // The current partial year (year to date) goes IN THE ROW next to the full years — marked partial,
      // and still NEVER part of the 5-year total above (the dashed box below carries the projection).
      var curYtd = data.current, partialCol = null;
      if (curYtd && num(curYtd.total) > 0) {
        var q = num(curYtd.quarters);
        partialCol = {
          label: String(curYtd.year) + "*",
          total: num(curYtd.total),
          partial: true,
          sub: q + " quarter" + (q === 1 ? "" : "s") + " so far",
          segs: [
            { value: num(curYtd.indemnity), color: C.indemnity, label: "Salary / indemnity" },
            { value: num(curYtd.top_up), color: C.topup, label: "Role top-up" },
            { value: num(curYtd.office_total), color: C.office, label: "Office expenses" }
          ]
        };
        cols.push(partialCol);
      }
      container.appendChild(stackedChart(cols));

      var hasTop = years.some(function (y) { return num(y.top_up) > 0; });
      var leg = [
        { color: C.indemnity, label: "Salary / indemnity" }
      ];
      if (hasTop) leg.push({ color: C.topup, label: "Role top-up" });
      leg.push({ color: C.office, label: "Office (travel · hospitality · contracts · staff)" });
      if (partialCol) leg.push({ color: C.muted, label: "* year to date — partial, not in the 5-year total" });
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

      // Ministerial (departmental) travel & hospitality — borne CENTRALLY, a line ON TOP of the
      // MP office budget above (why a PM/minister's MP-budget travel can read ~$0).
      var mn = data.ministerial;
      if (mn && num(mn.five_year_total) > 0) {
        var mbox = el("div", { css: "margin-top:16px;padding:12px 14px;border:1px solid " + C.topup + "55;border-radius:8px;background:" + C.topup + "14;" });
        mbox.appendChild(el("span", { text: "＋ Ministerial travel & hospitality", css: "font-weight:800;color:" + C.text + ";font-size:13px;" }));
        mbox.appendChild(el("div", { text: "Cost of their cabinet role, borne centrally — government travel + official hospitality. NOT charged to the MP office budget above.", css: "font-size:11px;color:" + C.subtle + ";margin:3px 0 9px;" }));
        var mhead = el("div", { css: "display:flex;flex-wrap:wrap;align-items:baseline;gap:10px;" });
        mhead.appendChild(el("span", { text: fmtCompact(mn.five_year_total), css: "font-size:24px;font-weight:800;color:" + C.topup + ";line-height:1;" }));
        mhead.appendChild(el("span", { text: fmtFull(mn.five_year_total) + " · 5-year ministerial travel & hospitality", css: "font-size:11px;color:" + C.subtle + ";" }));
        mbox.appendChild(mhead);
        var combined = num(data.five_year_total) + num(mn.five_year_total);
        mbox.appendChild(el("div", { text: "Combined 5-year cost to taxpayers ≈ " + fmtFull(combined), css: "font-size:12px;font-weight:700;color:" + C.text + ";margin-top:9px;" }));
        mbox.appendChild(el("div", { text: "MP office budget " + fmtFull(data.five_year_total) + " + ministerial " + fmtFull(mn.five_year_total), css: "font-size:10px;color:" + C.subtle + ";margin-top:1px;" }));
        container.appendChild(mbox);
      }

      // Federal contracts the minister's PORTFOLIO oversees (#373 Contract chain link) — NOT the
      // minister's personal cost; the department they lead awarded these. Portfolio-level, approximate.
      var ct = mn && mn.contracts;
      if (ct && num(ct.total) > 0) {
        var fys = ct.by_fy ? Object.keys(ct.by_fy).sort() : [];
        var winTxt = fys.length ? fys[0] + " – " + fys[fys.length - 1] : "";
        var ctbox = el("div", { css: "margin-top:16px;padding:12px 14px;border:1px dashed rgba(148,163,184,0.32);border-radius:8px;" });
        ctbox.appendChild(el("span", { text: "Federal contracts their portfolio oversees", css: "font-weight:800;color:" + C.text + ";font-size:13px;" }));
        ctbox.appendChild(el("div", { text: "Awarded by " + ct.department + " — the department this minister leads. NOT their personal cost, and not personally directed; shown to trace where public money flows.", css: "font-size:11px;color:" + C.subtle + ";margin:3px 0 9px;" }));
        var cthead = el("div", { css: "display:flex;flex-wrap:wrap;align-items:baseline;gap:10px;" });
        cthead.appendChild(el("span", { text: fmtCompact(ct.total), css: "font-size:24px;font-weight:800;color:" + C.text + ";line-height:1;" }));
        cthead.appendChild(el("span", { text: fmtFull(ct.total) + " · " + ct.n + " contract award" + (ct.n === 1 ? "" : "s") + (winTxt ? " (" + winTxt + ")" : ""), css: "font-size:11px;color:" + C.subtle + ";" }));
        ctbox.appendChild(cthead);
        if (ct.central_purchaser) {
          ctbox.appendChild(el("div", { text: "This department is the government's central purchasing agent — much of this is procured on behalf of other departments.", css: "font-size:10px;color:" + C.muted + ";margin-top:7px;" }));
        }
        ctbox.appendChild(el("div", { text: "Approximate & partial — CanadaBuys open procurement data, via Gov Watch.", css: "font-size:10px;color:" + C.muted + ";margin-top:7px;" }));
        container.appendChild(ctbox);
      }

      // Current partial year (year-to-date) + projected full year — NEVER in the 5-year total.
      var cur = data.current;
      if (cur && num(cur.total) > 0) {
        var cbox = el("div", { css: "margin-top:16px;padding:12px 14px;border:1px dashed rgba(148,163,184,0.32);border-radius:8px;" });
        cbox.appendChild(el("span", { text: cur.year + " so far", css: "font-weight:800;color:" + C.text + ";font-size:13px;" }));
        cbox.appendChild(el("span", { text: " · " + cur.quarters + " quarter" + (cur.quarters === 1 ? "" : "s") + " disclosed — shown for completeness, not in the total above", css: "font-size:11px;color:" + C.subtle + ";" }));
        var chead = el("div", { css: "display:flex;flex-wrap:wrap;align-items:baseline;gap:10px;margin-top:6px;" });
        chead.appendChild(el("span", { text: fmtCompact(cur.total), css: "font-size:24px;font-weight:800;color:" + C.office + ";line-height:1;" }));
        chead.appendChild(el("span", { text: fmtFull(cur.total) + " year-to-date", css: "font-size:11px;color:" + C.subtle + ";" }));
        cbox.appendChild(chead);
        if (cur.projected_full_year) {
          cbox.appendChild(el("div", { text: "↗ projected full year ≈ " + fmtFull(cur.projected_full_year) + " (annualized from " + cur.quarters + " quarter" + (cur.quarters === 1 ? "" : "s") + " — estimate, actuals will differ)", css: "font-size:11px;color:" + C.topup + ";margin-top:6px;" }));
        } else {
          cbox.appendChild(el("div", { text: "↗ a full-year projection appears once ≥2 quarters are disclosed", css: "font-size:11px;color:" + C.muted + ";margin-top:6px;" }));
        }
        container.appendChild(cbox);
      }

      container.appendChild(honestyBlock(data._note, data._source));
    }).catch(function () {
      errorMsg(container, "Cost figures are temporarily unavailable.");
    });
  }

  // --- "How we calculated this" — member-by-member reconciliation + provenance ---
  function renderMethodology() {
    var box = document.querySelector("[data-cost-methodology-body]");
    if (!box) return;
    errorMsg(box, "Loading the reconciliation…");
    getJSON("/api/cost/reconciliation").then(function (d) {
      clear(box);
      var h = d.headline || {}, ms = d.member_sum || {}, ct = d.counts || {};

      // 1) the reconciliation statement
      var recon = el("div", { css: "background:rgba(34,197,94,0.06);border:1px solid rgba(34,197,94,0.25);border-radius:8px;padding:14px 16px;margin-bottom:16px;" });
      recon.appendChild(el("div", {
        text: (d.reconciles ? "✓ " : "⚠ ") + "The headline reconciles member-by-member",
        css: "font-size:13px;font-weight:700;color:" + (d.reconciles ? "#22c55e" : C.topup) + ";margin-bottom:6px;"
      }));
      recon.appendChild(el("div", {
        text: "The " + (d.window ? d.window.label : "5-year") + " headline of " + fmtFull(h.parliamentary) +
              " is the independent sum of every member: " + ct.mps + " MPs + " + ct.senators + " senators = " + fmtFull(ms.parliamentary) + ".",
        css: "font-size:12px;color:" + C.text + ";line-height:1.7;"
      }));
      recon.appendChild(el("div", {
        text: "Ministerial travel & hospitality (borne centrally, reported separately): " + fmtFull(h.ministerial) +
              " across " + ct.ministers + " ministers. Combined ≈ " + fmtFull(h.combined) + ".",
        css: "font-size:12px;color:" + C.subtle + ";line-height:1.7;margin-top:4px;"
      }));
      var diff = num(d.discrepancy);
      recon.appendChild(el("div", {
        text: "Independent cross-check difference: " + (diff === 0 ? "$0 — exact."
              : fmtFull(Math.abs(diff)) + " out of " + fmtFull(h.parliamentary) + " — presentational rounding (each member page rounds its own annual figures)."),
        css: "font-size:11px;color:" + C.muted + ";margin-top:6px;"
      }));
      box.appendChild(recon);

      // 2) what's in / out / window / matching
      function dl(term, desc) {
        var w = el("div", { css: "margin-top:12px;" });
        w.appendChild(el("div", { text: term, css: "font-size:12px;font-weight:600;color:" + C.text + ";" }));
        w.appendChild(el("div", { text: desc, css: "font-size:12px;color:" + C.subtle + ";line-height:1.7;margin-top:2px;" }));
        return w;
      }
      box.appendChild(dl("What's counted",
        "Each member's base salary / sessional indemnity, any cabinet or role top-up, and office expenses (travel, hospitality, contracts and staff salaries). Cabinet ministers additionally carry their departmental travel & hospitality, borne centrally, shown as a separate line."));
      box.appendChild(dl("What's excluded",
        "Pensions, severance, and central costs (departmental program spending, security details, buildings). These are the cost of members and their offices — not the whole cost of government."));
      box.appendChild(dl("The window (tracked automatically)",
        "The headline covers the " + (d.window ? d.window.label : "5 complete fiscal years") + " — every year with all four quarters on file. This window is computed from the data and advances on its own: a year rolls into the headline the moment its fourth quarter is disclosed, and an incomplete year can never inflate it. Partial years (shown above the chart) are disclosed for completeness but never summed into the headline."));
      box.appendChild(dl("Current year & projections",
        "The current year to date is shown separately — split by chamber (House of Commons vs Senate) plus ministerial — as quarters are published. A projected full year is annualized once at least two quarters are on file (a single quarter is too noisy to project honestly); it is always labelled an estimate and refines as more data lands. Projections are never part of the official total."));
      box.appendChild(dl("How members are matched",
        "Every disclosed record is name-matched to the Library of Parliament roster. A public figure is never guessed — an official we cannot confidently match is simply not counted, so the total is a floor, not an over-count."));

      // 3) data coverage
      var covWrap = el("div", { css: "margin-top:16px;" });
      covWrap.appendChild(el("div", { text: "Data coverage", css: "font-size:12px;font-weight:600;color:" + C.text + ";margin-bottom:6px;" }));
      (d.coverage || []).forEach(function (c) {
        var r = el("div", { css: "display:flex;justify-content:space-between;gap:12px;font-size:11px;padding:4px 0;border-bottom:1px solid rgba(148,163,184,0.08);" });
        r.appendChild(el("span", { text: c.source, css: "color:" + C.subtle + ";" }));
        var count = Number(c.rows); count = isFinite(count) ? count.toLocaleString("en-CA") : c.rows;
        r.appendChild(el("span", { text: c.first + " → " + c.last + " · " + count + " records", css: "color:" + C.text + ";white-space:nowrap;" }));
        covWrap.appendChild(r);
      });
      box.appendChild(covWrap);

      // 4) sources
      if (d._source) {
        var sWrap = el("div", { css: "margin-top:14px;" });
        sWrap.appendChild(el("div", { text: "Sources", css: "font-size:12px;font-weight:600;color:" + C.text + ";margin-bottom:4px;" }));
        Object.keys(d._source).forEach(function (k) {
          sWrap.appendChild(el("div", { text: "• " + d._source[k], css: "font-size:11px;color:" + C.subtle + ";line-height:1.6;margin-top:2px;" }));
        });
        box.appendChild(sWrap);
      }

      // 5) costliest members + full-data download
      if (d.members && d.members.length) {
        var mWrap = el("div", { css: "margin-top:16px;" });
        mWrap.appendChild(el("div", { text: "Costliest members over the window — top " + d.members.length, css: "font-size:12px;font-weight:600;color:" + C.text + ";margin-bottom:6px;" }));
        d.members.forEach(function (m, i) {
          var r = el("div", { css: "display:flex;justify-content:space-between;gap:12px;font-size:11px;padding:3px 0;" });
          r.appendChild(el("span", { text: (i + 1) + ". " + m.name + " (" + m.type + ")", css: "color:" + C.subtle + ";" }));
          r.appendChild(el("span", { text: fmtFull(m.five_year_total), css: "color:" + C.text + ";white-space:nowrap;" }));
          mWrap.appendChild(r);
        });
        mWrap.appendChild(el("a", {
          text: "Download the full member-by-member breakdown (JSON) →",
          css: "display:inline-block;margin-top:8px;font-size:11px;color:#0af;text-decoration:none;",
          attrs: { href: "/api/cost/reconciliation?members=all" }
        }));
        box.appendChild(mWrap);
      }
    }).catch(function () {
      errorMsg(box, "The reconciliation is temporarily unavailable.");
    });
  }

  function auto() {
    var root = document.querySelector("[data-cost-summary]");
    if (root) renderSummary(root);
    if (document.querySelector("[data-cost-methodology-body]")) renderMethodology();
    var members = document.querySelectorAll("[data-cost-member]");
    for (var i = 0; i < members.length; i++) renderMember(members[i]);
  }

  global.WTFCost = {
    renderSummary: renderSummary,
    renderMember: renderMember,
    renderMethodology: renderMethodology,
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
