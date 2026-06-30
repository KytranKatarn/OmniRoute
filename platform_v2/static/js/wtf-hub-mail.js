/* WTF Hub — newsroom Inbox (what-the-fact.com mailboxes).
   Drives the per-box News-agent triage/draft/send over /tools/wtf-hub/api/mail/*.
   Read-only IMAP; send-as gated on an explicit click. All email content is
   rendered via textContent (XSS-safe). Mirrors the C.R.E.E.D. Command inbox. */
(function () {
  "use strict";
  var API = "/tools/wtf-hub/api/mail";
  var state = { box: null, uid: null, boxes: [] };

  function el(tag, cls, txt) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (txt != null) e.textContent = txt;
    return e;
  }
  function getJSON(url) {
    return fetch(url, { cache: "no-cache", headers: { Accept: "application/json" } }).then(function (r) {
      return r.json();
    });
  }
  function postJSON(url, body) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    }).then(function (r) {
      return r.json().then(function (d) { return { ok: r.ok, status: r.status, d: d }; });
    });
  }
  function fmtDate(iso) {
    if (!iso) return "";
    try {
      return window.ArchieTime && ArchieTime.format ? ArchieTime.format(iso, "datetime") : new Date(iso).toLocaleString();
    } catch (e) { return iso; }
  }
  function emailOf(s) { if (!s) return ""; var m = s.match(/<([^>]+)>/); return m ? m[1] : s.trim(); }
  function reSubject(s) { s = s || ""; return /^re:/i.test(s) ? s : "Re: " + s; }

  /* ---- mailbox chips ---- */
  function renderBoxes() {
    var wrap = document.getElementById("wtf-mail-boxes");
    if (!wrap) return;
    wrap.textContent = "";
    state.boxes.forEach(function (b) {
      var chip = el("button", "wtf-mail-chip" + (state.box === b.key ? " active" : ""));
      chip.appendChild(el("span", "wtf-mail-chip-addr", b.address));
      if (b.error) {
        chip.appendChild(el("span", "wtf-mail-chip-err", "⚠ " + b.error));
        chip.disabled = true;
      } else {
        chip.appendChild(el("span", "wtf-mail-chip-badge", (b.unseen || 0) + " new · " + (b.total || 0) + " total"));
      }
      if (!chip.disabled) chip.addEventListener("click", function () { selectBox(b.key); });
      wrap.appendChild(chip);
    });
  }
  function loadStatus() {
    var wrap = document.getElementById("wtf-mail-boxes");
    if (wrap) { wrap.textContent = ""; wrap.appendChild(el("span", "wtf-muted", "Loading mailboxes…")); }
    return getJSON(API + "/status").then(function (d) {
      state.boxes = (d && d.mailboxes) || [];
      renderBoxes();
      if (!state.box) {
        var first = state.boxes.filter(function (b) { return !b.error; })[0];
        if (first) selectBox(first.key);
      }
    }).catch(function () {
      if (wrap) { wrap.textContent = ""; wrap.appendChild(el("span", "wtf-mail-chip-err", "Could not load mailboxes.")); }
    });
  }
  function selectBox(key) {
    state.box = key; state.uid = null;
    renderBoxes();
    var read = document.getElementById("wtf-mail-read"); if (read) read.textContent = "";
    loadInbox(key);
  }

  /* ---- message list ---- */
  function loadInbox(box) {
    var list = document.getElementById("wtf-mail-list");
    list.textContent = ""; list.appendChild(el("div", "wtf-muted", "Loading…"));
    getJSON(API + "/inbox?box=" + encodeURIComponent(box) + "&limit=25").then(function (d) {
      renderList(box, (d && d.messages) || []);
    }).catch(function () {
      list.textContent = ""; list.appendChild(el("div", "wtf-mail-chip-err", "Could not load inbox."));
    });
  }
  function renderList(box, msgs) {
    var list = document.getElementById("wtf-mail-list");
    list.textContent = "";
    if (!msgs.length) { list.appendChild(el("div", "wtf-muted", "No messages.")); return; }
    msgs.forEach(function (m) {
      var item = el("div", "wtf-mail-item" + (m.seen ? "" : " unseen"));
      item.appendChild(el("div", "wtf-mail-item-subj", m.subject || "(no subject)"));
      var meta = el("div", "wtf-mail-item-meta");
      meta.appendChild(el("span", "wtf-mail-item-from", m.from || ""));
      meta.appendChild(el("span", null, fmtDate(m.date)));
      item.appendChild(meta);
      item.addEventListener("click", function () { loadMessage(box, m.uid); });
      list.appendChild(item);
    });
  }

  /* ---- read pane + News-agent AI ---- */
  function loadMessage(box, uid) {
    state.uid = uid;
    var read = document.getElementById("wtf-mail-read");
    read.textContent = ""; read.appendChild(el("div", "wtf-muted", "Loading…"));
    getJSON(API + "/message?box=" + encodeURIComponent(box) + "&uid=" + encodeURIComponent(uid)).then(function (d) {
      if (d.error) { read.textContent = ""; read.appendChild(el("div", "wtf-mail-chip-err", d.error)); return; }
      renderRead(box, uid, d);
    }).catch(function () { read.textContent = ""; read.appendChild(el("div", "wtf-mail-chip-err", "Could not load message.")); });
  }
  function renderRead(box, uid, d) {
    var read = document.getElementById("wtf-mail-read");
    read.textContent = "";
    read.appendChild(el("h2", "wtf-mail-read-subj", d.subject || "(no subject)"));
    var meta = el("div", "wtf-mail-read-meta");
    meta.appendChild(el("div", null, "From: " + (d.from || "")));
    meta.appendChild(el("div", null, "To: " + (d.to || "")));
    meta.appendChild(el("div", null, fmtDate(d.date)));
    read.appendChild(meta);
    read.appendChild(el("div", "wtf-mail-read-body", d.body || ""));
    read.appendChild(aiSection(box, uid, d));
    loadAi(box, uid);
  }
  function aiSection(box, uid, d) {
    var wrap = el("div", "wtf-mail-ai");
    var bar = el("div", "wtf-mail-ai-bar");
    bar.appendChild(el("span", "wtf-mail-ai-label", "News-desk AI"));
    var tBtn = el("button", "wtf-btn-sm", "⚖ Triage");
    var dBtn = el("button", "wtf-btn-sm", "✎ Draft reply");
    tBtn.addEventListener("click", function () { runAi("triage", box, uid, tBtn, d); });
    dBtn.addEventListener("click", function () { runAi("draft", box, uid, dBtn, d); });
    bar.appendChild(tBtn); bar.appendChild(dBtn);
    wrap.appendChild(bar);
    var t = el("div"); t.id = "wtf-ai-triage"; wrap.appendChild(t);
    var dd = el("div"); dd.id = "wtf-ai-draft"; wrap.appendChild(dd);
    return wrap;
  }
  function runAi(kind, box, uid, btn, d) {
    btn.disabled = true;
    var target = document.getElementById(kind === "triage" ? "wtf-ai-triage" : "wtf-ai-draft");
    target.textContent = "";
    target.appendChild(el("div", "wtf-muted", (kind === "triage" ? "Triaging" : "Drafting") + "… News agent working (GPU cluster)."));
    postJSON(API + "/" + kind, { box: box, uid: uid }).then(function (res) {
      if (res.ok && res.d && res.d.status === "pending") { pollAi(box, uid, kind, btn, d); }
      else {
        btn.disabled = false; target.textContent = "";
        target.appendChild(el("div", "wtf-mail-chip-err", (res.d && res.d.error) || "Could not start."));
      }
    }).catch(function () { btn.disabled = false; });
  }
  function pollAi(box, uid, kind, btn, d) {
    var tries = 0;
    var iv = setInterval(function () {
      tries++;
      getJSON(API + "/ai?box=" + encodeURIComponent(box) + "&uid=" + encodeURIComponent(uid)).then(function (a) {
        var st = a && a[kind];
        if (st && st.status === "done") { clearInterval(iv); btn.disabled = false; renderAi(kind, st.result, d, box, uid); }
        else if (st && st.status === "error") {
          clearInterval(iv); btn.disabled = false;
          var tgt = document.getElementById(kind === "triage" ? "wtf-ai-triage" : "wtf-ai-draft");
          tgt.textContent = ""; tgt.appendChild(el("div", "wtf-mail-chip-err", "AI error — try again."));
        } else if (tries > 50) { clearInterval(iv); btn.disabled = false; }
      });
    }, 3000);
  }
  function loadAi(box, uid) {
    getJSON(API + "/ai?box=" + encodeURIComponent(box) + "&uid=" + encodeURIComponent(uid)).then(function (a) {
      if (a && a.triage && a.triage.status === "done") renderAi("triage", a.triage.result, null, box, uid);
      if (a && a.draft && a.draft.status === "done") renderAi("draft", a.draft.result, null, box, uid);
    }).catch(function () {});
  }
  function renderAi(kind, result, d, box, uid) {
    var target = document.getElementById(kind === "triage" ? "wtf-ai-triage" : "wtf-ai-draft");
    if (!target) return;
    target.textContent = "";
    var block = el("div", "wtf-mail-ai-block");
    block.appendChild(el("div", "wtf-mail-ai-title", kind === "triage" ? "Triage" : "Draft reply"));
    if (kind === "triage") {
      block.appendChild(el("div", "wtf-mail-ai-text", result || ""));
    } else {
      block.appendChild(el("label", "wtf-mail-flabel", "To"));
      var to = el("input", "wtf-mail-input"); to.id = "wtf-reply-to"; if (d) to.value = emailOf(d.from);
      block.appendChild(to);
      block.appendChild(el("label", "wtf-mail-flabel", "Subject"));
      var subj = el("input", "wtf-mail-input"); subj.id = "wtf-reply-subj"; if (d) subj.value = reSubject(d.subject);
      block.appendChild(subj);
      block.appendChild(el("label", "wtf-mail-flabel", "Reply (review before sending)"));
      var ta = el("textarea", "wtf-mail-textarea"); ta.id = "wtf-reply-body"; ta.value = result || "";
      block.appendChild(ta);
      var row = el("div", "wtf-mail-send-row");
      var send = el("button", "wtf-btn-sm wtf-btn-send", "▶ Send reply");
      var status = el("span", "wtf-mail-send-status"); status.id = "wtf-reply-status";
      send.addEventListener("click", function () { sendReply(box || state.box, uid || state.uid, send, status); });
      row.appendChild(send); row.appendChild(status);
      block.appendChild(row);
    }
    target.appendChild(block);
  }
  function sendReply(box, uid, btn, status) {
    var to = (document.getElementById("wtf-reply-to") || {}).value || "";
    var subj = (document.getElementById("wtf-reply-subj") || {}).value || "";
    var body = (document.getElementById("wtf-reply-body") || {}).value || "";
    if (!to || !body) { status.className = "wtf-mail-send-status err"; status.textContent = "To + reply body required."; return; }
    btn.disabled = true; status.className = "wtf-mail-send-status"; status.textContent = "Sending…";
    postJSON(API + "/send", { box: box, uid: uid, to: to, subject: subj, body: body }).then(function (res) {
      if (res.ok && res.d && !res.d.error) { status.className = "wtf-mail-send-status ok"; status.textContent = "Sent ✓"; }
      else { btn.disabled = false; status.className = "wtf-mail-send-status err"; status.textContent = (res.d && res.d.error) || "Send failed."; }
    }).catch(function () { btn.disabled = false; status.className = "wtf-mail-send-status err"; status.textContent = "Network error."; });
  }

  /* ---- activate when the Inbox tab is first shown ---- */
  var loaded = false;
  window.wtfInboxActivate = function () {
    var rb = document.getElementById("wtf-mail-refresh");
    if (rb && !rb._wired) { rb._wired = true; rb.addEventListener("click", function () { loadStatus(); if (state.box) loadInbox(state.box); }); }
    if (loaded) return;
    loaded = true;
    loadStatus();
  };
})();
