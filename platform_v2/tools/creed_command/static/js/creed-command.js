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
      kpis.appendChild(kpi(d.grants ? String(d.grants.active) : "0", "Grants in pipeline"));
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

  /* ---- Grants pipeline (P2, #3611) ---- */
  var GSTATUS = ["prospect", "drafting", "submitted", "awarded", "declined"];
  var GCOLOR = { prospect: "#94a3b8", drafting: "#22d3ee", submitted: "#f59e0b", awarded: "#22c55e", declined: "#ef4444" };

  function gAmount(a) { return a != null ? "$" + Number(a).toLocaleString() : "—"; }
  function gDate(d) { return d ? String(d).slice(0, 10) : "—"; }

  function renderGrants(list) {
    var box = document.getElementById("cc-grants-table");
    var cnt = document.getElementById("cc-grants-count");
    if (cnt) cnt.textContent = list.length + " in pipeline";
    if (!box) return;
    while (box.firstChild) box.removeChild(box.firstChild);
    if (!list.length) { box.className = "cc-muted"; box.textContent = 'No grants yet — click "Add grant".'; return; }
    box.className = "";
    var table = el("table"); table.className = "cc-table";
    var thead = el("thead"); var htr = el("tr");
    ["Funder / program", "Amount", "Deadline", "Fit", "Status", ""].forEach(function (h) { htr.appendChild(el("th", null, h)); });
    thead.appendChild(htr); table.appendChild(thead);
    var tbody = el("tbody");
    list.forEach(function (g) {
      var tr = el("tr");
      var td0 = el("td");
      var f = el("div", "cc-g-funder", g.funder);
      if (g.url) { var a = el("a", null, " ↗"); a.href = g.url; a.target = "_blank"; a.rel = "noopener"; a.style.color = "#c9a44c"; f.appendChild(a); }
      td0.appendChild(f); td0.appendChild(el("div", "cc-g-prog", g.title));
      tr.appendChild(td0);
      tr.appendChild(el("td", null, gAmount(g.amount_cad)));
      tr.appendChild(el("td", null, gDate(g.deadline)));
      tr.appendChild(el("td", "cc-g-fit", g.fit_score != null ? String(g.fit_score) : "—"));
      var tds = el("td");
      var sel = el("select", "cc-g-status");
      GSTATUS.forEach(function (s) { var o = el("option", null, s); o.value = s; if (s === g.status) o.selected = true; sel.appendChild(o); });
      sel.style.color = GCOLOR[g.status] || "#e2e8f0";
      sel.addEventListener("change", function () { updateGrant(g.id, { status: sel.value }); });
      tds.appendChild(sel); tr.appendChild(tds);
      var tdd = el("td");
      var del = el("button", "cc-g-del", "✕"); del.title = "Delete";
      del.addEventListener("click", function () { if (window.confirm("Delete this grant?")) deleteGrant(g.id); });
      tdd.appendChild(del); tr.appendChild(tdd);
      tbody.appendChild(tr);
    });
    table.appendChild(tbody); box.appendChild(table);
  }

  function loadGrants() {
    fetch("/tools/creed-command/api/grants", { cache: "no-cache" })
      .then(function (r) { return r.json(); })
      .then(function (d) { renderGrants(d.grants || []); })
      .catch(function () { var b = document.getElementById("cc-grants-table"); if (b) { b.className = "cc-muted"; b.textContent = "Could not load grants."; } });
  }

  function updateGrant(id, patch) {
    fetch("/tools/creed-command/api/grants/" + id, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(patch) })
      .then(function () { loadGrants(); }).catch(function () {});
  }

  function deleteGrant(id) {
    fetch("/tools/creed-command/api/grants/" + id, { method: "DELETE" })
      .then(function () { loadGrants(); }).catch(function () {});
  }

  function submitGrant(e) {
    e.preventDefault();
    var msg = document.getElementById("cc-grant-msg"); msg.style.color = "#64748b"; msg.textContent = "";
    function val(id) { var x = document.getElementById(id); return x ? x.value.trim() : ""; }
    var body = {
      title: val("g-title"), funder: val("g-funder"),
      amount_cad: val("g-amount") || null, deadline: val("g-deadline") || null,
      fit_score: val("g-fit") || null, status: document.getElementById("g-status").value,
      url: val("g-url"), notes: val("g-notes"),
    };
    if (!body.title || !body.funder) { msg.style.color = "#fca5a5"; msg.textContent = "Program and funder are required."; return; }
    fetch("/tools/creed-command/api/grants", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        if (res.ok) { var fm = document.getElementById("cc-grant-form"); fm.reset(); fm.style.display = "none"; loadGrants(); }
        else { msg.style.color = "#fca5a5"; msg.textContent = (res.d && res.d.error) || "Could not save."; }
      }).catch(function () { msg.style.color = "#fca5a5"; msg.textContent = "Network error."; });
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
    loadGrants();
    var addBtn = document.getElementById("cc-grant-add-btn");
    var form = document.getElementById("cc-grant-form");
    if (addBtn && form) {
      addBtn.addEventListener("click", function () {
        form.style.display = form.style.display === "none" ? "block" : "none";
      });
    }
    var cancel = document.getElementById("cc-grant-cancel");
    if (cancel && form) cancel.addEventListener("click", function () { form.style.display = "none"; });
    if (form) form.addEventListener("submit", submitGrant);
  });
})();
