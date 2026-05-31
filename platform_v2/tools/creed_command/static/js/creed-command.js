/* C.R.E.E.D. Command Center — tabs + live dashboard (P5, #3615). */
(function () {
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text; // textContent — XSS-safe
    return e;
  }

  function kpi(value, label, extraClass) {
    var k = el("div", "cc-kpi" + (extraClass ? " " + extraClass : ""));
    k.appendChild(el("div", "cc-kpi-n", value));
    k.appendChild(el("div", "cc-kpi-l", label));
    return k;
  }

  function fmtAt(iso) {
    if (!iso) return "";
    try { return new Date(iso).toLocaleString(); } catch (e) { return iso; }
  }

  function renderDashboard(d) {
    var g = d.governance || {};

    var kpis = document.getElementById("cc-kpis");
    if (kpis) {
      while (kpis.firstChild) kpis.removeChild(kpis.firstChild);
      kpis.appendChild(kpi(g.grade || "—", "Governance grade", "grade"));
      kpis.appendChild(kpi(g.score != null ? g.score + "%" : "—", "Compliance score"));
      kpis.appendChild(kpi(g.incidents_disclosed != null ? String(g.incidents_disclosed) : "—", "Incidents disclosed"));
      kpis.appendChild(kpi(d.redress ? String(d.redress.pending) : "0", "Open redress"));
      kpis.appendChild(kpi(d.ethos_activity_7d != null ? String(d.ethos_activity_7d) : "0", "E.T.H.O.S. tasks (7d)"));
    }

    var brief = document.getElementById("cc-brief");
    if (brief) {
      while (brief.firstChild) brief.removeChild(brief.firstChild);
      if (d.latest_brief && d.latest_brief.title) {
        brief.className = "";
        var t = el("div"); t.style.cssText = "color:#cbd5e1;font-size:0.9rem;";
        t.textContent = d.latest_brief.title;
        var s = el("div", "cc-muted", fmtAt(d.latest_brief.at));
        s.style.marginTop = "0.3rem";
        brief.appendChild(t); brief.appendChild(s);
      } else {
        brief.className = "cc-muted";
        brief.textContent = "No ethics brief yet — E.T.H.O.S. runs the weekly brief Sundays at 05:30 ET (reviewing K.I.N.'s welfare digest + the week's governance log).";
      }
    }

    var act = document.getElementById("cc-activity");
    if (act) {
      while (act.firstChild) act.removeChild(act.firstChild);
      var rows = d.recent_activity || [];
      if (!rows.length) {
        act.className = "cc-muted";
        act.textContent = "No recent activity.";
      } else {
        act.className = "";
        rows.forEach(function (r) {
          var row = el("div", "cc-act");
          var dot = el("span", "cc-dot");
          dot.style.background = r.success ? "#22c55e" : "#ef4444";
          var cap = el("span", "cc-act-cap", r.capability || "—");
          var at = el("span", "cc-act-at", fmtAt(r.at));
          row.appendChild(dot); row.appendChild(cap); row.appendChild(at);
          act.appendChild(row);
        });
      }
    }
  }

  function loadDashboard() {
    fetch("/tools/creed-command/api/dashboard", { cache: "no-cache" })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(renderDashboard)
      .catch(function (e) {
        var kpis = document.getElementById("cc-kpis");
        if (kpis) { kpis.textContent = ""; kpis.appendChild(kpi("—", "Dashboard unavailable")); }
        console.warn("[CREED Command] dashboard load failed:", e);
      });
  }

  document.addEventListener("DOMContentLoaded", function () {
    var tabs = document.querySelectorAll(".cc-tab");
    var panes = document.querySelectorAll(".cc-pane");
    tabs.forEach(function (tab) {
      tab.addEventListener("click", function () {
        var name = tab.getAttribute("data-tab");
        tabs.forEach(function (t) { t.classList.toggle("active", t === tab); });
        panes.forEach(function (p) { p.classList.toggle("active", p.id === "pane-" + name); });
        if (history.replaceState) history.replaceState(null, "", "#" + name);
      });
    });
    var hash = (location.hash || "").replace("#", "");
    if (hash) {
      var target = document.querySelector('.cc-tab[data-tab="' + hash + '"]');
      if (target) target.click();
    }
    loadDashboard();
  });
})();
