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

  /* ---- AI-workforce welfare (#379 Phase 5) ---- */
  function renderWelfare(w) {
    var grade = document.getElementById("cc-welfare-grade");
    var body = document.getElementById("cc-welfare-body");
    if (!body) return;
    if (grade) {
      grade.textContent = (w.score != null ? w.score : "—") + " · " + (w.grade || "—");
      var c = w.score >= 90 ? "#22c55e" : w.score >= 80 ? "#22d3ee" : w.score >= 70 ? "#f59e0b" : "#ef4444";
      grade.style.background = c + "22"; grade.style.color = c; grade.style.borderColor = c + "55";
    }
    while (body.firstChild) body.removeChild(body.firstChild);
    body.className = "";
    var sum = el("div", "cc-wf-sum");
    sum.textContent = (w.active_agents || 0) + " active agents · "
      + (w.healthy_pct != null ? w.healthy_pct : "—") + "% within bounds · "
      + (w.break_honored_pct != null ? w.break_honored_pct : "—") + "% breaks honored"
      + (w.needed_break ? " · " + w.needed_break + " over a limit" : "");
    body.appendChild(sum);
    var recs = w.recommendations || [];
    var h = el("div", "cc-wf-h", recs.length ? "Recommendations to improve" : "No issues — workforce within healthy bounds.");
    body.appendChild(h);
    recs.forEach(function (r) {
      var row = el("div", "cc-wf-rec");
      var sev = el("span", "cc-wf-sev " + (r.severity === "critical" ? "crit" : "warn"), r.severity || "info");
      var txt = el("span", "cc-wf-txt", r.detail || r.kind || "");
      row.appendChild(sev); row.appendChild(txt); body.appendChild(row);
    });
    if (w.last_run_at) {
      var f = el("div", "cc-muted", "Last governance run: " + fmtAt(w.last_run_at));
      f.style.marginTop = "0.5rem"; body.appendChild(f);
    }
  }

  function loadWelfare() {
    fetch("/tools/creed-command/api/welfare", { cache: "no-cache" })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(renderWelfare)
      .catch(function (e) {
        var body = document.getElementById("cc-welfare-body");
        if (body) { body.className = "cc-muted"; body.textContent = "Welfare data unavailable."; }
        console.warn("[CREED Command] welfare load failed:", e);
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
      var tdd = el("td"); tdd.style.whiteSpace = "nowrap";
      var draftBtn = el("button", "cc-btn-sm", g.draft ? "✎ Draft*" : "✎ Draft");
      draftBtn.style.cssText = "padding:0.25rem 0.55rem;font-size:0.66rem;margin-right:0.4rem;";
      draftBtn.title = g.draft ? "Regenerate E.T.H.O.S. draft" : "Draft with E.T.H.O.S.";
      draftBtn.addEventListener("click", function () { draftGrant(g, draftBtn); });
      var del = el("button", "cc-g-del", "✕"); del.title = "Delete";
      del.addEventListener("click", function () { if (window.confirm("Delete this grant?")) deleteGrant(g.id); });
      tdd.appendChild(draftBtn); tdd.appendChild(del); tr.appendChild(tdd);
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

  function renderDraft(g, draft, at) {
    var panel = document.getElementById("cc-draft-panel");
    if (!panel) return;
    panel.className = "";
    while (panel.firstChild) panel.removeChild(panel.firstChild);
    var card = el("div", "cc-card");
    card.appendChild(el("h2", null, "E.T.H.O.S. draft — " + g.funder + " / " + g.title));
    var meta = el("div", "cc-muted", at ? "Generated " + new Date(at).toLocaleString() + " · review + edit before submitting" : "Review + edit before submitting");
    meta.style.cssText = "font-size:0.74rem;margin-bottom:0.6rem;";
    card.appendChild(meta);
    var body = el("div", null, draft); // textContent — XSS-safe
    body.style.cssText = "white-space:pre-wrap;font-size:0.88rem;line-height:1.6;color:#cbd5e1;";
    card.appendChild(body);
    panel.appendChild(card);
    if (panel.scrollIntoView) panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function pollDraft(g, since, tries, btn, orig) {
    var panel = document.getElementById("cc-draft-panel");
    if (tries <= 0) {
      btn.disabled = false; btn.textContent = orig;
      if (panel) { panel.className = "cc-muted"; panel.textContent = "Still drafting — check back shortly (E.T.H.O.S. may be busy)."; }
      return;
    }
    fetch("/tools/creed-command/api/grants/" + g.id, { cache: "no-cache" })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.draft && d.draft_generated_at && d.draft_generated_at !== since) {
          btn.disabled = false; btn.textContent = orig;
          renderDraft(g, d.draft, d.draft_generated_at); loadGrants();
        } else {
          setTimeout(function () { pollDraft(g, since, tries - 1, btn, orig); }, 5000);
        }
      })
      .catch(function () { setTimeout(function () { pollDraft(g, since, tries - 1, btn, orig); }, 5000); });
  }

  function draftGrant(g, btn) {
    var orig = btn.textContent;
    btn.disabled = true; btn.textContent = "Drafting…";
    var panel = document.getElementById("cc-draft-panel");
    if (panel) { panel.className = "cc-muted"; panel.textContent = "E.T.H.O.S. is drafting — this can take a minute or two…"; }
    fetch("/tools/creed-command/api/grants/" + g.id + "/draft", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        if (res.ok && res.d.status === "drafting") {
          pollDraft(g, res.d.since || null, 40, btn, orig); // ~40 × 5s ≈ 3.3 min
        } else {
          btn.disabled = false; btn.textContent = orig;
          if (panel) { panel.className = "cc-muted"; panel.textContent = (res.d && res.d.error) || "Could not start drafting."; }
        }
      })
      .catch(function () {
        btn.disabled = false; btn.textContent = orig;
        if (panel) { panel.className = "cc-muted"; panel.textContent = "Network error while drafting."; }
      });
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

  /* ---- Inbox (Hostinger creed-ai.org IMAP, read-only) — #3608/#3609/#3610 ---- */
  var mailState = { box: null, loadedStatus: false, list: [] };

  function renderMailBoxes() {
    var wrap = document.getElementById("cc-mail-boxes");
    if (!wrap) return;
    while (wrap.firstChild) wrap.removeChild(wrap.firstChild);
    mailState.list.forEach(function (b) {
      var chip = el("button", "cc-mail-chip" + (b.key === mailState.box ? " active" : ""));
      chip.appendChild(el("span", "cc-mail-chip-addr", b.address));
      if (b.error) {
        chip.appendChild(el("span", "cc-mail-chip-err", b.error === "no password" ? "not set" : b.error));
        if (b.error === "no password") chip.disabled = true;
      } else {
        chip.appendChild(el("span", "cc-mail-chip-badge", String(b.unseen != null ? b.unseen : 0)));
      }
      if (!chip.disabled) chip.addEventListener("click", function () { selectMailBox(b.key); });
      wrap.appendChild(chip);
    });
  }

  function loadMailStatus() {
    mailState.loadedStatus = true;
    var wrap = document.getElementById("cc-mail-boxes");
    if (wrap && !wrap.firstChild) { wrap.appendChild(el("span", "cc-muted", "Checking mailboxes…")); }
    fetch("/tools/creed-command/api/mail/status", { cache: "no-cache" })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        mailState.list = d.mailboxes || [];
        if (!mailState.box) {
          var first = mailState.list.filter(function (b) { return b.configured && !b.error; })[0];
          if (first) mailState.box = first.key;
        }
        renderMailBoxes();
        if (mailState.box) loadInbox(mailState.box);
      })
      .catch(function () {
        if (wrap) { wrap.textContent = ""; wrap.appendChild(el("span", "cc-muted", "Could not reach mail server.")); }
      });
  }

  function selectMailBox(key) { mailState.box = key; renderMailBoxes(); loadInbox(key); }

  function renderMailList(box, msgs) {
    var list = document.getElementById("cc-mail-list");
    if (!list) return;
    while (list.firstChild) list.removeChild(list.firstChild);
    if (!msgs.length) { list.className = "cc-card cc-muted"; list.textContent = "No messages."; return; }
    list.className = "cc-card";
    msgs.forEach(function (msg) {
      var item = el("div", "cc-mail-item" + (msg.seen ? "" : " unseen"));
      item.appendChild(el("div", "cc-mail-item-subj", msg.subject));
      var meta = el("div", "cc-mail-item-meta");
      meta.appendChild(el("span", "cc-mail-item-from", msg.from || "(unknown)"));
      meta.appendChild(el("span", "cc-mail-item-date", msg.date ? fmtAt(msg.date) : ""));
      item.appendChild(meta);
      item.addEventListener("click", function () { openMessage(box, msg.uid); });
      list.appendChild(item);
    });
  }

  function loadInbox(box) {
    var list = document.getElementById("cc-mail-list");
    if (list) { list.className = "cc-card cc-muted"; list.textContent = "Loading…"; }
    fetch("/tools/creed-command/api/mail/inbox?box=" + encodeURIComponent(box) + "&limit=25", { cache: "no-cache" })
      .then(function (r) { return r.json(); })
      .then(function (d) { renderMailList(box, d.messages || []); })
      .catch(function () { if (list) { list.className = "cc-card cc-muted"; list.textContent = "Could not load inbox."; } });
  }

  function openMessage(box, uid) {
    var read = document.getElementById("cc-mail-read");
    if (read) { read.className = "cc-card cc-muted"; read.textContent = "Loading message…"; }
    fetch("/tools/creed-command/api/mail/message?box=" + encodeURIComponent(box) + "&uid=" + encodeURIComponent(uid), { cache: "no-cache" })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!read) return;
        if (d.error) { read.className = "cc-card cc-muted"; read.textContent = "Could not load message."; return; }
        read.className = "cc-card";
        while (read.firstChild) read.removeChild(read.firstChild);
        read.appendChild(el("h2", "cc-mail-read-subj", d.subject || "(no subject)"));
        var meta = el("div", "cc-mail-read-meta");
        meta.appendChild(el("div", null, "From: " + (d.from || "")));
        if (d.to) meta.appendChild(el("div", null, "To: " + d.to));
        meta.appendChild(el("div", null, d.date ? fmtAt(d.date) : ""));
        read.appendChild(meta);
        read.appendChild(el("div", "cc-mail-read-body", d.body || "(empty message)")); // textContent — XSS-safe
        mailState.currentMsg = { box: box, uid: uid, from: d.from || "", subject: d.subject || "" };
        read.appendChild(mailAiSection(box, uid));
        loadMailAi(box, uid);
      })
      .catch(function () { if (read) { read.className = "cc-card cc-muted"; read.textContent = "Could not load message."; } });
  }

  /* ---- E.T.H.O.S. triage + draft-reply (#3620) ---- */
  function mailAiSection(box, uid) {
    var wrap = el("div", "cc-mail-ai");
    var bar = el("div", "cc-mail-ai-bar");
    bar.appendChild(el("span", "cc-mail-ai-label", "E.T.H.O.S.:"));
    var tBtn = el("button", "cc-btn-sm", "⚖ Triage");
    var dBtn = el("button", "cc-btn-sm", "✍ Draft reply");
    tBtn.addEventListener("click", function () { runMailAi("triage", box, uid, tBtn); });
    dBtn.addEventListener("click", function () { runMailAi("draft", box, uid, dBtn); });
    bar.appendChild(tBtn);
    bar.appendChild(dBtn);
    wrap.appendChild(bar);
    var t = el("div"); t.id = "cc-ai-triage"; wrap.appendChild(t);
    var d = el("div"); d.id = "cc-ai-draft"; wrap.appendChild(d);
    return wrap;
  }

  function renderAiBlock(kind, data) {
    var box = document.getElementById("cc-ai-" + kind);
    if (!box) return;
    while (box.firstChild) box.removeChild(box.firstChild);
    if (!data) return;
    if (data.status === "pending") {
      box.className = "cc-mail-ai-block cc-muted";
      box.textContent = (kind === "triage" ? "Triaging" : "Drafting") + "… E.T.H.O.S. is working (GPU cluster).";
      return;
    }
    if (data.status === "error" || !data.result) {
      box.className = "cc-mail-ai-block cc-muted";
      box.textContent = "E.T.H.O.S. could not complete this — try again.";
      return;
    }
    box.className = "cc-mail-ai-block";
    if (kind === "triage") {
      box.appendChild(el("div", "cc-mail-ai-title", "Triage"));
      box.appendChild(el("div", "cc-mail-ai-text", data.result)); // textContent — XSS-safe
      return;
    }
    // draft → editable composer + send (human approves the final body before it goes out)
    box.appendChild(el("div", "cc-mail-ai-title", "Draft reply — review, edit, send"));
    var cm = mailState.currentMsg || {};
    var fromAddr = addrForKey(cm.box);
    var toIn = el("input", "cc-mail-input"); toIn.type = "text"; toIn.value = emailOf(cm.from || ""); toIn.placeholder = "recipient@example.com";
    var subIn = el("input", "cc-mail-input"); subIn.type = "text"; subIn.value = reSubject(cm.subject || "");
    var ta = el("textarea", "cc-mail-textarea"); ta.value = data.result;
    var sendBtn = el("button", "cc-btn-sm cc-btn-send", "Send from " + (fromAddr || "mailbox"));
    var statusEl = el("span", "cc-mail-send-status", "");
    sendBtn.addEventListener("click", function () {
      sendReply(cm.box, cm.uid, toIn.value.trim(), subIn.value.trim(), ta.value, sendBtn, statusEl);
    });
    box.appendChild(el("label", "cc-mail-flabel", "To"));
    box.appendChild(toIn);
    box.appendChild(el("label", "cc-mail-flabel", "Subject"));
    box.appendChild(subIn);
    box.appendChild(el("label", "cc-mail-flabel", "Message"));
    box.appendChild(ta);
    var row = el("div", "cc-mail-send-row");
    row.appendChild(sendBtn);
    row.appendChild(statusEl);
    box.appendChild(row);
  }

  function emailOf(s) {
    var m = /<([^>]+@[^>]+)>/.exec(s || "");
    if (m) return m[1].trim();
    m = /([^\s<]+@[^\s>]+)/.exec(s || "");
    return m ? m[1].trim() : "";
  }

  function reSubject(s) {
    s = (s || "").trim();
    return /^re:/i.test(s) ? s : "Re: " + s;
  }

  function addrForKey(key) {
    var b = (mailState.list || []).filter(function (x) { return x.key === key; })[0];
    return b ? b.address : "";
  }

  function sendReply(box, uid, to, subject, body, btn, statusEl) {
    function fail(t) { if (statusEl) { statusEl.className = "cc-mail-send-status err"; statusEl.textContent = t; } }
    if (!to || to.indexOf("@") < 0) return fail("Enter a valid recipient.");
    if (!body.trim()) return fail("Message is empty.");
    if (!window.confirm("Send this reply from " + addrForKey(box) + " to " + to + "?")) return;
    if (btn) btn.disabled = true;
    if (statusEl) { statusEl.className = "cc-mail-send-status"; statusEl.textContent = "Sending…"; }
    fetch("/tools/creed-command/api/mail/send", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ box: box, uid: uid, to: to, subject: subject, body: body }),
    })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        if (btn) btn.disabled = false;
        if (res.ok && res.d.sent) {
          if (statusEl) { statusEl.className = "cc-mail-send-status ok"; statusEl.textContent = "✓ Sent to " + res.d.to; }
        } else {
          fail((res.d && res.d.error) || "Send failed.");
        }
      })
      .catch(function () { if (btn) btn.disabled = false; fail("Network error."); });
  }

  /* ---- Marketing → Inbox compose (#3946) ---- */
  var MKT_FROM_BOX = { press: "press", newsletter: "contact", linkedin: "contact", x: "contact", blog: "contact" };

  function renderCompose(asset) {
    var read = document.getElementById("cc-mail-read");
    if (!read) return;
    read.className = "cc-card";
    while (read.firstChild) read.removeChild(read.firstChild);
    read.appendChild(el("h2", "cc-mail-read-subj", "Compose — outreach from marketing asset"));
    read.appendChild(el("div", "cc-mail-read-meta",
      mktLabel(asset.channel) + " · " + (asset.topic || "") + " · nothing sends without your explicit click"));
    var boxes = (mailState.list || []).filter(function (b) { return b.configured && !b.error; });
    var fromSel = el("select", "cc-mail-input");
    boxes.forEach(function (b) { var o = el("option", null, b.address); o.value = b.key; fromSel.appendChild(o); });
    var want = MKT_FROM_BOX[asset.channel] || "contact";
    if (boxes.some(function (b) { return b.key === want; })) fromSel.value = want;
    var toIn = el("input", "cc-mail-input"); toIn.type = "text"; toIn.placeholder = "recipient@example.com";
    var subIn = el("input", "cc-mail-input"); subIn.type = "text"; subIn.value = asset.topic || "";
    var ta = el("textarea", "cc-mail-textarea"); ta.value = asset.content || "";
    var sendBtn = el("button", "cc-btn-sm cc-btn-send", "Send");
    var statusEl = el("span", "cc-mail-send-status", "");
    sendBtn.addEventListener("click", function () {
      sendReply(fromSel.value, null, toIn.value.trim(), subIn.value.trim(), ta.value, sendBtn, statusEl);
    });
    read.appendChild(el("label", "cc-mail-flabel", "From"));
    read.appendChild(fromSel);
    read.appendChild(el("label", "cc-mail-flabel", "To"));
    read.appendChild(toIn);
    read.appendChild(el("label", "cc-mail-flabel", "Subject"));
    read.appendChild(subIn);
    read.appendChild(el("label", "cc-mail-flabel", "Message"));
    read.appendChild(ta);
    var row = el("div", "cc-mail-send-row");
    row.appendChild(sendBtn);
    row.appendChild(statusEl);
    read.appendChild(row);
    toIn.focus();
  }

  function openComposeFromAsset(asset) {
    var inboxTab = document.querySelector('.cc-tab[data-tab="inbox"]');
    if (inboxTab) inboxTab.click(); // switches pane + lazy-loads mailbox status
    if ((mailState.list || []).some(function (b) { return b.configured && !b.error; })) {
      renderCompose(asset);
      return;
    }
    var read = document.getElementById("cc-mail-read");
    if (read) { read.className = "cc-card cc-muted"; read.textContent = "Loading mailboxes…"; }
    var tries = 20;
    (function wait() {
      if ((mailState.list || []).some(function (b) { return b.configured && !b.error; })) return renderCompose(asset);
      if (--tries <= 0) { if (read) read.textContent = "Mailboxes unavailable — check the Inbox tab."; return; }
      setTimeout(wait, 500);
    })();
  }

  function pollMailAi(box, uid, tries) {
    if (tries <= 0) return;
    fetch("/tools/creed-command/api/mail/ai?box=" + encodeURIComponent(box) + "&uid=" + encodeURIComponent(uid), { cache: "no-cache" })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (mailState.box !== box) return; // user switched boxes
        renderAiBlock("triage", d.triage);
        renderAiBlock("draft", d.draft);
        var pend = (d.triage && d.triage.status === "pending") || (d.draft && d.draft.status === "pending");
        if (pend) setTimeout(function () { pollMailAi(box, uid, tries - 1); }, 4000);
      })
      .catch(function () { setTimeout(function () { pollMailAi(box, uid, tries - 1); }, 4000); });
  }

  function loadMailAi(box, uid) {
    fetch("/tools/creed-command/api/mail/ai?box=" + encodeURIComponent(box) + "&uid=" + encodeURIComponent(uid), { cache: "no-cache" })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        renderAiBlock("triage", d.triage);
        renderAiBlock("draft", d.draft);
        if ((d.triage && d.triage.status === "pending") || (d.draft && d.draft.status === "pending")) {
          pollMailAi(box, uid, 60);
        }
      })
      .catch(function () {});
  }

  function runMailAi(kind, box, uid, btn) {
    if (btn) btn.disabled = true;
    renderAiBlock(kind, { status: "pending" });
    fetch("/tools/creed-command/api/mail/" + kind, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ box: box, uid: uid }),
    })
      .then(function (r) { return r.json(); })
      .then(function () {
        if (btn) btn.disabled = false;
        setTimeout(function () { pollMailAi(box, uid, 60); }, 3000);
      })
      .catch(function () { if (btn) btn.disabled = false; renderAiBlock(kind, { status: "error" }); });
  }

  /* ---- Marketing studio (#3613) ---- */
  var mktState = { loaded: false };
  function mktLabel(c) {
    return { linkedin: "LinkedIn", x: "X / Twitter", newsletter: "Newsletter", press: "Press pitch", blog: "Blog teaser" }[c] || c;
  }

  function renderMktAssets(list) {
    var box = document.getElementById("cc-mkt-list");
    if (!box) return;
    while (box.firstChild) box.removeChild(box.firstChild);
    if (!list.length) { box.className = "cc-muted"; box.textContent = "No assets yet — pick a channel + topic and click Generate."; return; }
    box.className = "";
    list.forEach(function (a) {
      var card = el("div", "cc-mkt-asset");
      var head = el("div", "cc-mkt-head");
      head.appendChild(el("span", "cc-mkt-badge", mktLabel(a.channel)));
      head.appendChild(el("span", "cc-mkt-topic", a.topic));
      if (a.approved) head.appendChild(el("span", "cc-mkt-approved", "✓ approved"));
      card.appendChild(head);
      if (a.gen_status === "pending") {
        card.appendChild(el("div", "cc-muted", "E.T.H.O.S. is writing… (GPU cluster)"));
        pollMkt(a.id, 40);
      } else if (a.gen_status === "error" || !a.content) {
        card.appendChild(el("div", "cc-muted", "E.T.H.O.S. could not generate this — delete and retry."));
      } else {
        var ta = el("textarea", "cc-mail-textarea"); ta.value = a.content; ta.style.minHeight = "110px";
        card.appendChild(ta);
        var actions = el("div", "cc-mkt-actions");
        var saveBtn = el("button", "cc-btn-sm", "Save edits");
        saveBtn.addEventListener("click", function () { patchMkt(a.id, { content: ta.value }); });
        var copyBtn = el("button", "cc-btn-sm", "Copy");
        copyBtn.addEventListener("click", function () {
          if (navigator.clipboard) navigator.clipboard.writeText(ta.value);
          copyBtn.textContent = "Copied ✓"; setTimeout(function () { copyBtn.textContent = "Copy"; }, 1500);
        });
        var apprBtn = el("button", "cc-btn-sm", a.approved ? "Unapprove" : "Approve");
        apprBtn.addEventListener("click", function () { patchMkt(a.id, { approved: !a.approved }); });
        var delBtn = el("button", "cc-btn-sm", "Delete");
        delBtn.addEventListener("click", function () { if (window.confirm("Delete this asset?")) deleteMkt(a.id); });
        actions.appendChild(saveBtn); actions.appendChild(copyBtn); actions.appendChild(apprBtn); actions.appendChild(delBtn);
        // #3946 — open this asset as a prefilled Inbox compose (send stays human-gated)
        var inboxBtn = el("button", "cc-btn-sm", "✉ Open in Inbox");
        inboxBtn.title = "Prefill an Inbox compose with this asset — review, pick recipient, send-as";
        inboxBtn.addEventListener("click", function () {
          openComposeFromAsset({ id: a.id, channel: a.channel, topic: a.topic, content: ta.value });
        });
        actions.appendChild(inboxBtn);
        if (a.channel === "linkedin") {
          // #3944 — publishing is owned by S.I.G.N.A.L.: this queues the post
          // for human approval (DHQ Social tab / Telegram), Creed-AI account.
          var sigBtn = el("button", "cc-btn-sm",
            a.gen_status === "sent_to_signal" ? "✓ Queued — re-send to S.I.G.N.A.L." : "Send to S.I.G.N.A.L. →");
          sigBtn.addEventListener("click", function () {
            sigBtn.disabled = true;
            fetch("/tools/creed-command/api/marketing/" + a.id + "/send-to-signal", { method: "POST" })
              .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
              .then(function (res) {
                sigBtn.disabled = false;
                if (res.ok) { loadMarketing(); }
                else {
                  sigBtn.textContent = (res.d && res.d.error) || "Failed";
                  setTimeout(function () { sigBtn.textContent = "Send to S.I.G.N.A.L. →"; }, 3000);
                }
              })
              .catch(function () { sigBtn.disabled = false; });
          });
          actions.appendChild(sigBtn);
        }
        actions.appendChild(el("span", "right", a.updated_at ? fmtAt(a.updated_at) : ""));
        card.appendChild(actions);
      }
      box.appendChild(card);
    });
  }

  function loadMarketing() {
    mktState.loaded = true;
    fetch("/tools/creed-command/api/marketing", { cache: "no-cache" })
      .then(function (r) { return r.json(); })
      .then(function (d) { renderMktAssets(d.assets || []); })
      .catch(function () { var b = document.getElementById("cc-mkt-list"); if (b) { b.className = "cc-muted"; b.textContent = "Could not load assets."; } });
  }

  function pollMkt(id, tries) {
    if (tries <= 0) return;
    setTimeout(function () {
      fetch("/tools/creed-command/api/marketing/" + id, { cache: "no-cache" })
        .then(function (r) { return r.json(); })
        .then(function (a) { if (a.gen_status && a.gen_status !== "pending") loadMarketing(); else pollMkt(id, tries - 1); })
        .catch(function () { pollMkt(id, tries - 1); });
    }, 4000);
  }

  function genMkt() {
    var chEl = document.getElementById("cc-mkt-channel");
    var topicEl = document.getElementById("cc-mkt-topic");
    var topic = (topicEl.value || "").trim();
    if (!topic) { topicEl.focus(); return; }
    var btn = document.getElementById("cc-mkt-gen");
    if (btn) btn.disabled = true;
    fetch("/tools/creed-command/api/marketing", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ channel: chEl.value, topic: topic }),
    })
      .then(function (r) { return r.json(); })
      .then(function () { if (btn) btn.disabled = false; topicEl.value = ""; loadMarketing(); })
      .catch(function () { if (btn) btn.disabled = false; });
  }

  function patchMkt(id, patch) {
    fetch("/tools/creed-command/api/marketing/" + id, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(patch) })
      .then(function () { loadMarketing(); }).catch(function () {});
  }
  function deleteMkt(id) {
    fetch("/tools/creed-command/api/marketing/" + id, { method: "DELETE" }).then(function () { loadMarketing(); }).catch(function () {});
  }

  /* ---- Document library (#3614) ---- */
  var fileState = { loaded: false };
  function fmtSize(n) {
    if (n == null) return "";
    if (n < 1024) return n + " B";
    if (n < 1048576) return (n / 1024).toFixed(1) + " KB";
    return (n / 1048576).toFixed(1) + " MB";
  }

  function renderFiles(list) {
    var box = document.getElementById("cc-file-list");
    if (!box) return;
    while (box.firstChild) box.removeChild(box.firstChild);
    if (!list.length) { box.className = "cc-muted"; box.textContent = "No files yet — upload one above."; return; }
    box.className = "";
    list.forEach(function (f) {
      var row = el("div", "cc-file-row");
      var left = el("div");
      left.appendChild(el("div", "cc-file-name", f.filename));
      left.appendChild(el("div", "cc-file-meta", fmtSize(f.size_bytes) + (f.uploaded_at ? " · " + fmtAt(f.uploaded_at) : "")));
      row.appendChild(left);
      if (f.tag) row.appendChild(el("span", "cc-file-tag", f.tag));
      if (f.grant_title) row.appendChild(el("span", "cc-file-link", "↳ " + f.grant_title));
      var actions = el("div", "cc-file-actions");
      var dl = el("a", "cc-btn-sm", "Download");
      dl.href = "/tools/creed-command/api/files/" + f.id + "/download";
      dl.setAttribute("download", "");
      actions.appendChild(dl);
      var del = el("button", "cc-btn-sm", "Delete");
      del.addEventListener("click", function () { if (window.confirm("Delete " + f.filename + "?")) deleteFile(f.id); });
      actions.appendChild(del);
      row.appendChild(actions);
      box.appendChild(row);
    });
  }

  function loadFiles() {
    fileState.loaded = true;
    fetch("/tools/creed-command/api/grants", { cache: "no-cache" })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var sel = document.getElementById("cc-file-grant");
        if (!sel) return;
        var cur = sel.value;
        while (sel.options.length > 1) sel.remove(1);
        (d.grants || []).forEach(function (g) { var o = el("option", null, g.funder + " / " + g.title); o.value = g.id; sel.appendChild(o); });
        sel.value = cur;
      }).catch(function () {});
    fetch("/tools/creed-command/api/files", { cache: "no-cache" })
      .then(function (r) { return r.json(); })
      .then(function (d) { renderFiles(d.files || []); })
      .catch(function () { var b = document.getElementById("cc-file-list"); if (b) { b.className = "cc-muted"; b.textContent = "Could not load files."; } });
  }

  function uploadFile() {
    var input = document.getElementById("cc-file-input");
    var status = document.getElementById("cc-file-status");
    function fail(t) { if (status) { status.className = "cc-mail-send-status err"; status.textContent = t; } }
    if (!input || !input.files || !input.files[0]) return fail("Choose a file first.");
    var fd = new FormData();
    fd.append("file", input.files[0]);
    fd.append("tag", (document.getElementById("cc-file-tag").value || "").trim());
    fd.append("grant_id", document.getElementById("cc-file-grant").value || "");
    var btn = document.getElementById("cc-file-upload");
    if (btn) btn.disabled = true;
    if (status) { status.className = "cc-mail-send-status"; status.textContent = "Uploading…"; }
    fetch("/tools/creed-command/api/files", { method: "POST", body: fd })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        if (btn) btn.disabled = false;
        if (res.ok) {
          if (status) { status.className = "cc-mail-send-status ok"; status.textContent = "✓ Uploaded"; }
          input.value = ""; document.getElementById("cc-file-tag").value = ""; loadFiles();
        } else { fail((res.d && res.d.error) || "Upload failed."); }
      })
      .catch(function () { if (btn) btn.disabled = false; fail("Upload failed."); });
  }

  function deleteFile(id) {
    fetch("/tools/creed-command/api/files/" + id, { method: "DELETE" }).then(function () { loadFiles(); }).catch(function () {});
  }

  /* ---- Tenants ops (#3945) ---- */
  var tenantState = { loaded: false };

  function tenantGradeColor(g) {
    if (!g || g === "PROVISIONAL") return "#6b7280";
    if (g.indexOf("A") === 0) return "#10b981";
    if (g.indexOf("B") === 0) return "#3b82f6";
    if (g.indexOf("C") === 0) return "#f59e0b";
    return "#ef4444";
  }

  function renderTenantCounts(c) {
    var box = document.getElementById("cc-tenant-counts");
    if (!box) return;
    box.className = "";
    box.textContent = (c.total || 0) + " tenant(s) · " + (c.active || 0) + " active · " +
      (c.pending || 0) + " pending · " + (c.suspended || 0) + " suspended";
  }

  function renderApplications(list) {
    var box = document.getElementById("cc-tenant-apps");
    if (!box) return;
    while (box.firstChild) box.removeChild(box.firstChild);
    if (!list.length) { box.className = "cc-muted"; box.textContent = "No pending applications."; return; }
    box.className = "";
    list.forEach(function (a) {
      var row = el("div", "cc-card");
      row.appendChild(el("div", "cc-mkt-topic", a.name + " (" + a.slug + ")"));
      var meta = el("div", "cc-muted");
      meta.textContent = (a.website || "—") + " · " + (a.country || "—") + " · " + (a.contact_email || "—") +
        " · email " + (a.email_verified ? "verified ✓" : "unverified") + (a.applied_at ? " · " + fmtAt(a.applied_at) : "");
      row.appendChild(meta);
      if (a.ai_description) { var d = el("p"); d.textContent = a.ai_description; row.appendChild(d); }
      var actions = el("div", "cc-mkt-actions");
      var ap = el("button", "cc-btn-sm", "Approve + mint key");
      ap.addEventListener("click", function () { approveTenant(a.slug, ap); });
      var rj = el("button", "cc-btn-sm", "Reject");
      rj.addEventListener("click", function () { if (window.confirm("Reject " + a.name + "?")) rejectTenant(a.slug); });
      actions.appendChild(ap); actions.appendChild(rj);
      row.appendChild(actions);
      box.appendChild(row);
    });
  }

  function renderTenantList(list) {
    var box = document.getElementById("cc-tenant-list");
    if (!box) return;
    while (box.firstChild) box.removeChild(box.firstChild);
    var shown = list.filter(function (t) { return t.status !== "pending"; });
    if (!shown.length) { box.className = "cc-muted"; box.textContent = "No active tenants yet."; return; }
    box.className = "";
    shown.forEach(function (t) {
      var row = el("div", "cc-card");
      var head = el("div", "cc-mkt-head");
      head.appendChild(el("span", "cc-mkt-topic", t.name + " (" + t.slug + ")"));
      var badge = el("span", "cc-mkt-badge", (t.grade || t.status));
      badge.style.background = tenantGradeColor(t.grade);
      head.appendChild(badge);
      row.appendChild(head);
      var meta = el("div", "cc-muted");
      meta.textContent = t.status + (t.verification_tier ? " · " + t.verification_tier : "") +
        (t.overall != null ? " · score " + t.overall : "") +
        (t.events_30d != null ? " · " + t.events_30d + " events/30d" : "") +
        (t.last_event_at ? " · last " + fmtAt(t.last_event_at) : "") + (t.website ? " · " + t.website : "");
      row.appendChild(meta);
      var actions = el("div", "cc-mkt-actions");
      var profile = el("a", "cc-btn-sm", "Public profile ↗");
      profile.href = "https://creed.kytranempowerment.com/org/" + t.slug; profile.target = "_blank"; profile.rel = "noopener";
      var keysBtn = el("button", "cc-btn-sm", "Keys");
      keysBtn.addEventListener("click", function () { showKeys(t.slug); });
      actions.appendChild(profile); actions.appendChild(keysBtn);
      row.appendChild(actions);
      box.appendChild(row);
    });
  }

  function loadTenants() {
    tenantState.loaded = true;
    fetch("/tools/creed-command/api/tenants", { cache: "no-cache" })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.success) { var b = document.getElementById("cc-tenant-counts"); if (b) b.textContent = d.error || "Unavailable"; return; }
        renderTenantCounts(d.counts || {});
        renderTenantList(d.tenants || []);
      })
      .catch(function () { var b = document.getElementById("cc-tenant-counts"); if (b) b.textContent = "Could not load tenants."; });
    fetch("/tools/creed-command/api/tenants/applications", { cache: "no-cache" })
      .then(function (r) { return r.json(); })
      .then(function (d) { renderApplications((d && d.applications) || []); })
      .catch(function () {});
  }

  function approveTenant(slug, btn) {
    if (btn) btn.disabled = true;
    fetch("/tools/creed-command/api/tenants/" + slug + "/approve", { method: "POST" })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var key = d.api_key || d.key;
        if (d.success && key) { window.alert("Approved " + slug + ".\n\nIngest key (shown ONCE — copy now):\n\n" + key); }
        else if (!d.success) { window.alert("Approve failed: " + (d.error || "unknown")); }
        tenantState.loaded = false; loadTenants();
      })
      .catch(function () { if (btn) btn.disabled = false; });
  }

  function rejectTenant(slug) {
    fetch("/tools/creed-command/api/tenants/" + slug + "/reject", { method: "POST" })
      .then(function () { tenantState.loaded = false; loadTenants(); }).catch(function () {});
  }

  function showKeys(slug) {
    fetch("/tools/creed-command/api/tenants/" + slug + "/keys", { cache: "no-cache" })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var keys = (d && d.keys) || [];
        var lines = keys.length ? keys.map(function (k) {
          return "• " + (k.label || "key#" + k.id) + " · " + (k.scopes || "ingest") + " · " + (k.is_active ? "active" : "revoked") +
            (k.last_used_at ? " · last used " + fmtAt(k.last_used_at) : " · never used");
        }).join("\n") : "(no keys yet)";
        if (window.confirm(slug + " keys:\n\n" + lines + "\n\nMint a NEW ingest key?")) {
          fetch("/tools/creed-command/api/tenants/" + slug + "/keys", {
            method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ label: "issued from CREED Command" }),
          })
            .then(function (r) { return r.json(); })
            .then(function (m) { var nk = m.api_key || m.key; if (nk) window.alert("New key (copy ONCE):\n\n" + nk); });
        }
      }).catch(function () {});
  }

  /* ---- Redress queue (Governance tab) ---- */
  var redressState = { loaded: false };
  var REDRESS_STATUSES = ["pending", "under_review", "resolved", "denied"];

  function redressStatusColor(s) {
    if (s === "pending") return "#f59e0b";
    if (s === "under_review") return "#3b82f6";
    if (s === "resolved") return "#10b981";
    return "#6b7280"; /* denied */
  }

  function renderRedressCounts(byStatus, total) {
    var box = document.getElementById("cc-redress-counts");
    if (!box) return;
    box.className = "";
    box.textContent = total + " total · " + byStatus.pending + " pending · " +
      byStatus.under_review + " under review · " + byStatus.resolved + " resolved · " +
      byStatus.denied + " denied";
  }

  function renderRedressList(items) {
    var box = document.getElementById("cc-redress-list");
    if (!box) return;
    while (box.firstChild) box.removeChild(box.firstChild);
    var open = items.filter(function (r) { return r.status === "pending" || r.status === "under_review"; });
    if (!open.length) { box.className = "cc-muted"; box.textContent = "No open redress requests."; return; }
    box.className = "";
    open.forEach(function (r) {
      var row = el("div", "cc-card");
      var head = el("div", "cc-mkt-head");
      head.appendChild(el("span", "cc-mkt-topic", r.request_ref));
      var badge = el("span", "cc-mkt-badge", r.status);
      badge.style.background = redressStatusColor(r.status);
      head.appendChild(badge);
      row.appendChild(head);
      var meta = el("div", "cc-muted");
      meta.textContent = (r.email || "no email given") +
        (r.ai_decision_ref ? " · re: " + r.ai_decision_ref : "") +
        " · filed " + fmtAt(r.created_at) + " · SLA due " + fmtAt(r.sla_due_at);
      row.appendChild(meta);
      var reason = el("p", null, r.reason);
      row.appendChild(reason);
      if (r.desired_outcome) {
        var outcome = el("p", "cc-muted", "Desired outcome: " + r.desired_outcome);
        row.appendChild(outcome);
      }
      var notes = el("textarea");
      notes.className = "cc-mail-input";
      notes.placeholder = "Resolution notes (shown to no one automatically — internal record)";
      notes.rows = 2;
      row.appendChild(notes);
      var actions = el("div", "cc-mkt-actions");
      REDRESS_STATUSES.filter(function (s) { return s !== r.status; }).forEach(function (s) {
        var btn = el("button", "cc-btn-sm", s.replace("_", " "));
        btn.addEventListener("click", function () { resolveRedress(r.request_ref, s, notes.value, btn); });
        actions.appendChild(btn);
      });
      row.appendChild(actions);
      box.appendChild(row);
    });
  }

  function loadRedressQueue() {
    redressState.loaded = true;
    fetch("/tools/creed-command/api/redress-requests", { cache: "no-cache" })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.success) { var b = document.getElementById("cc-redress-counts"); if (b) b.textContent = d.error || "Unavailable"; return; }
        var items = d.requests || [];
        var counts = { pending: 0, under_review: 0, resolved: 0, denied: 0 };
        items.forEach(function (r) { if (counts[r.status] != null) counts[r.status] += 1; });
        renderRedressCounts(counts, items.length);
        renderRedressList(items);
      })
      .catch(function () { var b = document.getElementById("cc-redress-counts"); if (b) b.textContent = "Could not load redress queue."; });
  }

  function resolveRedress(ref, status, notes, btn) {
    if (btn) btn.disabled = true;
    fetch("/tools/creed-command/api/redress-requests/" + ref + "/resolve", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: status, resolution_notes: notes }),
    })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.success) window.alert("Update failed: " + (d.error || "unknown"));
        redressState.loaded = false; loadRedressQueue();
      })
      .catch(function () { if (btn) btn.disabled = false; });
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
        if (name === "inbox" && !mailState.loadedStatus) loadMailStatus();
        if (name === "marketing" && !mktState.loaded) loadMarketing();
        if (name === "files" && !fileState.loaded) loadFiles();
        if (name === "tenants" && !tenantState.loaded) loadTenants();
        if (name === "governance" && !redressState.loaded) loadRedressQueue();
      });
    });
    var hash = (location.hash || "").replace("#", "");
    if (hash) {
      var target = document.querySelector('.cc-tab[data-tab="' + hash + '"]');
      if (target) target.click();
    }
    loadDashboard();
    loadWelfare();
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
    var mailRefresh = document.getElementById("cc-mail-refresh");
    if (mailRefresh) mailRefresh.addEventListener("click", loadMailStatus);
    if ((location.hash || "").replace("#", "") === "inbox") loadMailStatus();
    var mktGen = document.getElementById("cc-mkt-gen");
    if (mktGen) mktGen.addEventListener("click", genMkt);
    if ((location.hash || "").replace("#", "") === "marketing") loadMarketing();
    var fileUp = document.getElementById("cc-file-upload");
    if (fileUp) fileUp.addEventListener("click", uploadFile);
    if ((location.hash || "").replace("#", "") === "files") loadFiles();
  });
})();
