/* AaaS public commissioning wizard (#2474).
   Multi-step form → POST /api/aaas/orders (public, same-origin, CSRF-exempt).
   No untrusted innerHTML — all dynamic text via textContent. */
(function () {
  "use strict";

  var form = document.getElementById("aaasForm");
  if (!form) return;

  var TOTAL = 5;
  var current = 1;

  var steps = Array.prototype.slice.call(form.querySelectorAll(".aaas-step"));
  var pSteps = Array.prototype.slice.call(document.querySelectorAll(".aaas-progress-step"));
  var backBtn = document.getElementById("aaasBack");
  var nextBtn = document.getElementById("aaasNext");
  var submitBtn = document.getElementById("aaasSubmit");
  var formError = document.getElementById("aaasFormError");
  var confirmEl = document.getElementById("aaasConfirm");
  var reviewEl = document.getElementById("aaasReview");

  function q(name) { return form.querySelector('[name="' + name + '"]'); }
  function val(name) { var el = q(name); return el ? el.value.trim() : ""; }
  function checkedVals(name) {
    return Array.prototype.slice
      .call(form.querySelectorAll('[name="' + name + '"]:checked'))
      .map(function (el) { return el.value; });
  }

  function showStep(n) {
    current = Math.max(1, Math.min(TOTAL, n));
    steps.forEach(function (s) { s.classList.toggle("is-active", Number(s.dataset.step) === current); });
    pSteps.forEach(function (p) {
      var idx = Number(p.dataset.pstep);
      p.classList.toggle("is-active", idx === current);
      p.classList.toggle("is-done", idx < current);
    });
    backBtn.hidden = current === 1;
    nextBtn.hidden = current === TOTAL;
    submitBtn.hidden = current !== TOTAL;
    if (current === TOTAL) buildReview();
    if (window.lucide) window.lucide.createIcons();
    document.getElementById("aaas-form").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function setErr(name, msg) {
    var el = form.querySelector('[data-err="' + name + '"]');
    if (el) el.textContent = msg || "";
  }

  function validEmail(v) { return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v); }

  function validateStep(n) {
    setErr("contact_email", "");
    setErr("mission", "");
    if (n === 1) {
      var email = val("contact_email");
      if (!email || !validEmail(email)) { setErr("contact_email", "Please enter a valid email."); return false; }
    }
    if (n === 3) {
      if (!val("mission")) { setErr("mission", "A one-line mission is required."); return false; }
    }
    return true;
  }

  // --- toggles ---------------------------------------------------------------
  var autoName = q("auto_name");
  var nameInput = document.querySelector(".aaas-name-input");
  function syncName() { if (nameInput) nameInput.hidden = autoName.checked; }
  if (autoName) { autoName.addEventListener("change", syncName); syncName(); }

  var knowType = q("knowledge_type");
  var knowRef = document.querySelector(".aaas-knowledge-ref");
  function syncKnow() { if (knowRef) knowRef.hidden = (knowType.value === "none"); }
  if (knowType) { knowType.addEventListener("change", syncKnow); syncKnow(); }

  // --- tier card picker ------------------------------------------------------
  Array.prototype.slice.call(document.querySelectorAll(".aaas-tier-pick")).forEach(function (btn) {
    btn.addEventListener("click", function () {
      var tier = btn.dataset.tier;
      var sel = q("tier");
      if (sel) sel.value = tier;
      document.querySelectorAll(".aaas-tier-card").forEach(function (c) { c.classList.remove("is-picked"); });
      var card = btn.closest(".aaas-tier-card");
      if (card) card.classList.add("is-picked");
      document.getElementById("aaas-form").scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });

  // --- review (textContent only) --------------------------------------------
  function addRow(dt, dd) {
    var d1 = document.createElement("dt"); d1.textContent = dt;
    var d2 = document.createElement("dd"); d2.textContent = dd || "—";
    reviewEl.appendChild(d1); reviewEl.appendChild(d2);
  }
  function buildReview() {
    reviewEl.textContent = "";
    addRow("Company", val("company_name"));
    addRow("Contact", (val("contact_name") + " · " + val("contact_email")).replace(/^ · | · $/g, ""));
    addRow("Industry", val("industry"));
    addRow("Agent name", autoName && autoName.checked ? "A.R.C.H.I.E. will name it" : (val("agent_name") || "—"));
    addRow("Tone", val("persona_tone"));
    addRow("Mission", val("mission"));
    var caps = checkedVals("cap"); addRow("Capabilities", caps.length ? caps.join(", ") : "—");
    var del = checkedVals("delivery"); if (del.indexOf("api") === -1) del.unshift("api");
    addRow("Delivery", del.join(", "));
    addRow("Languages", checkedVals("lang").join(", "));
    addRow("Plan", val("tier"));
  }

  // --- payload ---------------------------------------------------------------
  function buildPayload() {
    var caps = checkedVals("cap");
    var del = checkedVals("delivery");
    var name = (autoName && autoName.checked) ? null : (val("agent_name") || null);
    var knowType2 = val("knowledge_type");
    var knowRef2 = val("knowledge_ref");
    var brief = {
      agent_name: name,
      display_name: name,
      accent_color: val("accent_color") || "#3b82f6",
      system_prompt: val("mission"),
      mission: val("mission"),
      capabilities: caps,
      use_cases: val("use_cases"),
      persona_tone: val("persona_tone"),
      industry: val("industry"),
      knowledge_sources: (knowType2 && knowType2 !== "none") ? [{ type: knowType2, ref: knowRef2 }] : [],
      delivery: {
        api: true,
        kbs_embed: del.indexOf("kbs_embed") !== -1,
        mailbox: del.indexOf("mailbox") !== -1,
        channels: []
      },
      i18n_languages: checkedVals("lang")
    };
    return {
      contact_email: val("contact_email"),
      contact_name: val("contact_name") || null,
      company_name: val("company_name") || null,
      tier: val("tier") || "starter",
      company_website: val("company_website"), // honeypot — empty for humans
      brief: brief
    };
  }

  // --- nav handlers ----------------------------------------------------------
  nextBtn.addEventListener("click", function () { if (validateStep(current)) showStep(current + 1); });
  backBtn.addEventListener("click", function () { showStep(current - 1); });

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    formError.hidden = true;
    if (!validateStep(1)) { showStep(1); return; }
    if (!validateStep(3)) { showStep(3); return; }
    submitBtn.disabled = true;
    submitBtn.textContent = "Submitting…";

    fetch("/api/aaas/orders", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(buildPayload())
    })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, status: r.status, body: j }; }); })
      .then(function (res) {
        if (res.ok && res.body && res.body.success) {
          form.hidden = true;
          document.querySelector(".aaas-progress").style.display = "none";
          confirmEl.hidden = false;
          var ref = document.getElementById("aaasOrderRef");
          ref.textContent = res.body.order_id ? ("AAAS-" + res.body.order_id) : "received";
          if (window.lucide) window.lucide.createIcons();
          confirmEl.scrollIntoView({ behavior: "smooth", block: "center" });
        } else {
          var msg = (res.body && res.body.error) || "Something went wrong. Please try again.";
          if (res.status === 429) msg = "Too many requests — please wait a moment and try again.";
          formError.textContent = msg;
          formError.hidden = false;
          submitBtn.disabled = false;
          submitBtn.textContent = "Submit request";
        }
      })
      .catch(function () {
        formError.textContent = "Network error — please try again.";
        formError.hidden = false;
        submitBtn.disabled = false;
        submitBtn.textContent = "Submit request";
      });
  });

  showStep(1);
})();
