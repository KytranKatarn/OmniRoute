/* department-ops.js — Shared LCARS Department Operations Terminal Component
 *
 * Extracted from Consciousness module into reusable component.
 * Usage:
 *   var ops = new DepartmentOps({
 *     stationCode: "ENGINEERING",
 *     moduleSource: "repair_bay",
 *     agentsElId: "engOpsAgents",
 *     jobsElId: "engOpsJobs",
 *     commandsElId: "engOpsCommands",
 *     statusElId: "engOpsOnline",
 *     commands: [{label:"SCAN", cls:"purple", fn:"startScan()", id:"btnScan"}],
 *     onJobComplete: function(job) { ... },
 *     onCapacityChange: function(atCapacity) { ... }
 *   });
 *   ops.render(jobData);       // full render cycle
 *   ops.checkJobs();           // poll Bridge for running jobs
 *   ops.pollJob(jobId, elId, onComplete);  // poll single job
 *
 * Note: innerHTML usage is safe here — all user-supplied strings are escaped
 * via escHtml() before insertion. This matches the existing Consciousness
 * module pattern (consciousness.js setHtml/escHtml).
 */
(function() {
  "use strict";

  /* ── Helpers ──────────────────────────────────── */

  function escHtml(str) {
    if (str == null) return "";
    var div = document.createElement("div");
    div.textContent = String(str);
    return div.innerHTML;
  }

  function setHtml(el, html) {
    if (typeof el === "string") el = document.getElementById(el);
    if (el) el.innerHTML = html;  // nosemgrep: innerHTML with pre-escaped content
  }

  /* ── Constructor ──────────────────────────────── */

  function DepartmentOps(config) {
    this.stationCode = config.stationCode;         // "ENGINEERING", "ANALYTICS", etc.
    this.moduleSource = config.moduleSource;         // "repair_bay", "consciousness"
    this.agentsElId = config.agentsElId;             // element id for crew list
    this.jobsElId = config.jobsElId;                 // element id for job progress
    this.commandsElId = config.commandsElId;         // element id for command buttons
    this.statusElId = config.statusElId;             // element id for ONLINE/AT CAPACITY
    this.commands = config.commands || [];            // [{label, cls, fn, id, title}]
    this.onJobComplete = config.onJobComplete;       // callback(job)
    this.onCapacityChange = config.onCapacityChange; // callback(atCapacity)
    this.dataUrl = config.dataUrl || null;           // custom data URL (overrides Bridge API)
    this.maxPrimaryOverride = config.maxPrimary || null; // override max primary slots (e.g. 1 for starship command)
    this.maxAuxOverride = config.maxAux;                 // override max auxiliary slots (0 to disable)
    this._activePolls = {};
    this._atCapacity = false;
    this._commandsInjected = false;
  }

  /* ── Render station crew + cross-station assists + contractors ── */

  DepartmentOps.prototype.renderAgents = function(jobData) {
    var self = this;
    var agentsEl = document.getElementById(this.agentsElId);
    if (!agentsEl) return;

    var stationsUrl = this.dataUrl || "/tools/starbase/api/stations";
    fetch(stationsUrl).then(function(resp) {
      var ct = resp.headers.get("content-type") || "";
      if (ct.indexOf("application/json") === -1) return Promise.reject("not json");
      return resp.json();
    }).then(function(data) {
      if (!data.success) return;
      var crew = [];
      var maxPrimary = 2;
      var maxAux = 1;
      var stations = data.stations || [];
      stations.forEach(function(s) {
        if (s.code !== self.stationCode) return;
        maxPrimary = self.maxPrimaryOverride || s.max_primary || 2;
        maxAux = (self.maxAuxOverride !== undefined && self.maxAuxOverride !== null) ? self.maxAuxOverride : (s.max_auxiliary || 1);
        (s.assigned_agents || []).forEach(function(a) {
          /* Skip barracked agents — they are not available for dispatch */
          if (a.shift_state === 'barracked') return;
          crew.push({
            name: (a.first_name && a.last_name) ? a.first_name + " " + a.last_name : (a.name || "Agent"),
            title: a.title || a.assignment_type || "agent",
            agentName: a.name || "",
            status: a.status || "active",
            shiftState: a.shift_state || "active"
          });
        });
      });

      /* Filter jobs to this station (primary + cross-station TO here + contractors here)
       * Cross-station jobs: station_code = agent's home, but module_station or
       * dispatch_station = the requesting station. Match on either. */
      var stationJobs = [];
      var assists = [];
      var contractors = [];
      if (jobData && jobData.length) {
        jobData.forEach(function(j) {
          var meta = j.metadata || {};
          var jobForStation = j.station_code === self.stationCode;
          var moduleForStation = meta.module_station === self.stationCode || meta.dispatch_station === self.stationCode;
          if (meta.is_cloud && (jobForStation || moduleForStation)) {
            var cname = j.agent_name || "Cloud";
            var already = contractors.some(function(c) { return c.name === cname; });
            if (!already) {
              contractors.push({ name: cname, cap: meta.capability || j.job_type || "task" });
            }
            stationJobs.push(j);
          } else if (meta.is_cross_station && (jobForStation || moduleForStation)) {
            /* Cross-station agent helping THIS station */
            var aname = j.agent_name || "Cross-station agent";
            var already2 = assists.some(function(a) { return a.name === aname; });
            if (!already2) {
              assists.push({ name: aname, station: meta.agent_station || j.station_code, cap: meta.capability || "assist" });
            }
            stationJobs.push(j);
          } else if (jobForStation) {
            stationJobs.push(j);
          }
        });
      }

      /* Build lookup of busy agents from THIS station's jobs only */
      var busyMap = {};
      stationJobs.forEach(function(j) {
        if (j.agent_name && j.status === "running") {
          busyMap[j.agent_name] = j.description || j.job_type || "task";
        }
      });

      /* Count how many crew members are busy */
      var busyCrew = 0;
      crew.forEach(function(a) {
        if (busyMap[a.agentName] || busyMap[a.name]) busyCrew++;
      });

      /* Station is at capacity when all crew busy AND auxiliary is full */
      var wasAtCapacity = self._atCapacity;
      var wasFirstRender = !self._hasRendered;
      self._hasRendered = true;
      self._atCapacity = (busyCrew >= crew.length && crew.length > 0) && (assists.length >= maxAux);
      if (self._atCapacity !== wasAtCapacity || wasFirstRender) {
        self._applyCapacity(self._atCapacity);
        if (self.onCapacityChange) self.onCapacityChange(self._atCapacity);
      }

      var parts = [];

      /* STATION CREW — always show all 3 slots (Primary, Secondary, Auxiliary) */
      parts.push('<div class="stn-ops-section-label cs-ops-section-label">STATION CREW (' + crew.length + '/' + maxPrimary + ')</div>');

      /* Render Primary + Secondary slots (always show both, even if empty) */
      var slotLabels = ['PRIMARY', 'SECONDARY'];
      var slotColors = ['#10b981', '#3b82f6'];
      var slotRgba = ['16,185,129', '59,130,246'];
      for (var si = 0; si < maxPrimary; si++) {
        var a = crew[si];
        var roleLabel = slotLabels[si] || ('CREW ' + (si + 1));
        var roleColor = slotColors[si] || '#94a3b8';
        var rgba = slotRgba[si] || '148,163,184';
        if (a) {
          var busy = busyMap[a.agentName] || busyMap[a.name];
          var isPaused = a.status === 'paused';
          var rowStyle = isPaused ? ' style="opacity:0.4;filter:grayscale(0.7);"' : '';
          parts.push('<div class="stn-ops-agent-row cs-ops-agent-row"' + rowStyle + '>');
          parts.push('<span class="stn-ops-agent-name cs-ops-agent-name">' + escHtml(a.name) + '</span>');
          if (isPaused) {
            parts.push('<span class="stn-ops-agent-badge cs-ops-agent-badge" style="background:rgba(255,165,0,0.15);color:#FFA500;">PAUSED</span>');
          } else if (busy) {
            parts.push('<span class="stn-ops-agent-badge cs-ops-agent-badge working">WORKING</span>');
          }
          parts.push('<span class="stn-ops-agent-role cs-ops-agent-role" style="color:' + roleColor + '; background:rgba(' + rgba + ',0.15);">' + roleLabel + '</span>');
          parts.push('</div>');
        } else {
          /* Empty slot */
          parts.push('<div class="stn-ops-agent-row cs-ops-agent-row" style="opacity:0.3;border-left-color:#555;">');
          parts.push('<span class="stn-ops-agent-name cs-ops-agent-name" style="font-style:italic;">— vacant —</span>');
          parts.push('<span class="stn-ops-agent-role cs-ops-agent-role" style="color:' + roleColor + '; background:rgba(' + rgba + ',0.1);">' + roleLabel + '</span>');
          parts.push('</div>');
        }
      }

      /* AUXILIARY slot — always show (1 slot), filled by cross-station helpers */
      parts.push('<div class="stn-ops-section-label cs-ops-section-label" style="margin-top:8px;">AUXILIARY (' + assists.length + '/' + maxAux + ')</div>');
      if (assists.length) {
        assists.forEach(function(a) {
          parts.push('<div class="stn-ops-agent-row cs-ops-agent-row" style="border-left-color:#facc15;">');
          parts.push('<span class="stn-ops-agent-name cs-ops-agent-name">' + escHtml(a.name) + '</span>');
          parts.push('<span class="stn-ops-agent-badge cs-ops-agent-badge working">HELPING</span>');
          parts.push('<span class="stn-ops-agent-role cs-ops-agent-role" style="color:#facc15; background:rgba(250,204,21,0.15);">');
          parts.push(escHtml(a.station) + ' \u2022 ' + escHtml(a.cap) + '</span>');
          parts.push('</div>');
        });
      } else {
        /* Empty auxiliary slot */
        parts.push('<div class="stn-ops-agent-row cs-ops-agent-row" style="opacity:0.3;border-left-color:#555;">');
        parts.push('<span class="stn-ops-agent-name cs-ops-agent-name" style="font-style:italic;">— vacant —</span>');
        parts.push('<span class="stn-ops-agent-role cs-ops-agent-role" style="color:#facc15; background:rgba(250,204,21,0.1);">AUX</span>');
        parts.push('</div>');
      }

      /* CONTRACTOR section (only if active) */
      if (contractors.length) {
        parts.push('<div class="stn-ops-section-label cs-ops-section-label" style="margin-top:8px; color:#a78bfa;">CONTRACTOR (' + contractors.length + ')</div>');
        contractors.forEach(function(c) {
          parts.push('<div class="stn-ops-agent-row cs-ops-agent-row" style="border-left-color:#a78bfa;">');
          parts.push('<span class="stn-ops-agent-name cs-ops-agent-name" style="color:#a78bfa;">' + escHtml(c.name) + '</span>');
          parts.push('<span class="stn-ops-agent-badge cs-ops-agent-badge working" style="background:rgba(167,139,250,0.15); color:#a78bfa;">HIRED</span>');
          parts.push('<span class="stn-ops-agent-role cs-ops-agent-role" style="color:#a78bfa; background:rgba(167,139,250,0.15);">');
          parts.push(escHtml(c.cap) + '</span>');
          parts.push('</div>');
        });
      }

      /* Station capacity banner */
      if (self._atCapacity) {
        parts.push('<div class="stn-ops-capacity-banner cs-ops-capacity-banner">STATION AT CAPACITY \u2014 awaiting free slot</div>');
      }

      var html = parts.join("");

      /* Only update DOM if content actually changed */
      if (agentsEl.innerHTML !== html) {
        setHtml(agentsEl, html);
      }
    }).catch(function() {
      if (agentsEl.innerHTML !== "") setHtml(agentsEl, "");
    });
  };

  /* ── Render job progress rows in ops terminal ── */

  DepartmentOps.prototype.renderJobs = function(jobs) {
    var self = this;
    var jobsEl = document.getElementById(this.jobsElId);
    if (!jobsEl) return;
    if (jobs && jobs.length) {
      var seen = {};
      var unique = jobs.filter(function(j) {
        if (seen[j.id]) return false;
        var meta = j.metadata || {};
        var forStation = j.station_code === self.stationCode ||
          meta.module_station === self.stationCode ||
          meta.dispatch_station === self.stationCode;
        if (j.station_code && !forStation) return false;
        seen[j.id] = true;
        return true;
      });
      if (!unique.length) { setHtml(jobsEl, ""); return; }
      var parts = ['<div class="stn-ops-section-label cs-ops-section-label">ACTIVE JOBS</div>'];
      unique.forEach(function(j) {
        var pct = j.progress_pct || 0;
        var desc = j.description || j.job_type || "Processing";
        var agentLabel = j.agent_name || "Queued";
        var stationLabel = j.station_code || "";
        if (stationLabel) agentLabel += " \u2022 " + stationLabel;
        var completed = j.completed_steps || 0;
        var total = j.total_steps || 0;
        var countLabel = total > 0 ? ('<span class="stn-ops-job-count cs-ops-job-count">' + completed + ' / ' + total + '</span>') : '';
        parts.push('<div class="stn-ops-job-row cs-ops-job-row">');
        parts.push('<div class="stn-ops-job-info cs-ops-job-info">');
        parts.push('<div class="stn-ops-job-desc cs-ops-job-desc">' + escHtml(desc) + '</div>');
        parts.push('<div class="stn-ops-job-agent cs-ops-job-agent">' + escHtml(agentLabel) + '</div>');
        parts.push('</div>');
        parts.push('<div class="stn-ops-job-bar cs-ops-job-bar"><div class="stn-ops-job-fill cs-ops-job-fill" style="width:' + pct + '%"></div></div>');
        parts.push(countLabel);
        parts.push('<div class="stn-ops-job-pct cs-ops-job-pct">' + pct + '%</div>');
        parts.push('</div>');
      });
      setHtml(jobsEl, parts.join(""));
    } else {
      setHtml(jobsEl, "");
    }
  };

  /* ── Render command buttons (once) ── */

  DepartmentOps.prototype.renderCommands = function() {
    var cmdsEl = document.getElementById(this.commandsElId);
    if (!cmdsEl || cmdsEl.hasChildNodes()) return;
    this.commands.forEach(function(c) {
      var btn = document.createElement("button");
      btn.className = "stn-ops-cmd cs-ops-cmd " + c.cls;
      btn.textContent = c.label;
      btn.setAttribute("onclick", c.fn);
      if (c.id) btn.id = c.id;
      if (c.title) btn.title = c.title;
      cmdsEl.appendChild(btn);
    });
    this._commandsInjected = true;
  };

  /* ── Full render cycle ── */

  DepartmentOps.prototype.render = function(jobData) {
    this.renderAgents(jobData);
    this.renderJobs(jobData);
    this.renderCommands();
  };

  /* ── Poll Bridge for running jobs (filtered by moduleSource) ── */

  DepartmentOps.prototype.checkJobs = function() {
    var self = this;
    return fetch("/tools/starbase/api/bridge/jobs?status=running").then(function(resp) {
      var ct = resp.headers.get("content-type") || "";
      if (ct.indexOf("application/json") === -1) return Promise.reject("not json");
      return resp.json();
    }).then(function(data) {
      if (!data.success) return { myJobs: [], allJobs: [] };
      var myJobs = (data.jobs || []).filter(function(j) {
        return j.module_source === self.moduleSource ||
          (j.module_source && j.module_source.indexOf(self.moduleSource) === 0);
      });
      return { myJobs: myJobs, allJobs: data.jobs || [] };
    }).catch(function() {
      return { myJobs: [], allJobs: [] };
    });
  };

  /* ── Poll individual job progress ── */

  DepartmentOps.prototype.pollJob = function(jobId, elId, onComplete) {
    var self = this;
    var retries = 0;
    var maxRetries = 3;
    var poll = setInterval(function() {
      fetch("/tools/starbase/api/bridge/jobs/" + jobId).then(function(resp) {
        var ct = resp.headers.get("content-type") || "";
        if (ct.indexOf("application/json") === -1) return Promise.reject("not json");
        return resp.json();
      }).then(function(data) {
        retries = 0;
        if (!data.success) { clearInterval(poll); return; }
        var j = data.job;
        var pct = j.total_steps > 0 ? Math.round(((j.completed_steps || 0) / j.total_steps) * 100) : 0;
        self.renderJob({
          description: j.description,
          agent_name: j.agent_display_name || j.agent_name || "Agent",
          station_code: j.station_code || "",
          completed_steps: j.completed_steps || 0,
          total_steps: j.total_steps || 0,
          failed_steps: j.failed_steps || 0,
          progress_pct: pct,
          status: j.status
        }, elId);
        if (j.status === "completed" || j.status === "failed" || j.status === "cancelled") {
          clearInterval(poll);
          if (onComplete) onComplete(j);
        }
      }).catch(function() {
        retries++;
        if (retries >= maxRetries) {
          clearInterval(poll);
          var fallbackEl = (typeof elId === "string") ? document.getElementById(elId) : elId;
          if (fallbackEl) {
            fallbackEl.textContent = "";
            var msg = document.createElement("div");
            msg.className = "cs-pipeline-step";
            msg.style.color = "rgba(255,255,255,0.5)";
            var icon = document.createElement("span");
            icon.className = "cs-pipeline-icon";
            icon.style.color = "var(--stn-accent,#8b5cf6)";
            icon.textContent = "\u25B6";
            msg.appendChild(icon);
            msg.appendChild(document.createTextNode(" Job #" + jobId + " running \u2014 check "));
            var link = document.createElement("a");
            link.href = "/tools/starbase";
            link.style.color = "var(--stn-accent,#8b5cf6)";
            link.textContent = "Starbase Command";
            msg.appendChild(link);
            msg.appendChild(document.createTextNode(" for live progress"));
            fallbackEl.appendChild(msg);
          }
          if (onComplete) onComplete(null);
        }
      });
    }, 3000);
    return poll;
  };

  /* ── Build job progress HTML (LCARS notification bar) ── */
  /* Note: all dynamic strings are escaped via escHtml() before insertion */

  DepartmentOps.prototype.buildJobHtml = function(job) {
    var pct = job.progress_pct || 0;
    var agent = job.agent_name || "Queued";
    if (job.station_code) agent += " \u2022 " + job.station_code;
    var eta = "";
    if (job.eta_seconds && job.eta_seconds > 0) {
      var m = Math.floor(job.eta_seconds / 60);
      var s = job.eta_seconds % 60;
      eta = m > 0 ? " \u2022 ~" + m + "m " + s + "s remaining" : " \u2022 ~" + s + "s remaining";
    }
    var type = job.status === "failed" ? "err" : job.status === "completed" ? "ok" : "info";
    var icon = job.status === "failed" ? "\u2717" : job.status === "completed" ? "\u2713" : "\u25B6";
    var capColor = job.status === "failed" ? "#ef4444" : job.status === "completed" ? "#10b981" : "var(--stn-accent,#8b5cf6)";
    var barColor = job.status === "failed" ? "#ef4444" : job.status === "completed" ? "#10b981" : "var(--stn-accent,#8b5cf6)";

    var countStr = (job.completed_steps || 0) + ' / ' + (job.total_steps || 0);
    if (job.failed_steps > 0) countStr += ' (' + job.failed_steps + ' failed)';

    var parts = [];
    parts.push('<div class="cs-job-msg ' + type + '" style="flex-direction:column;align-items:stretch;">');
    parts.push('<div style="display:flex;align-items:stretch;">');
    parts.push('<span class="cs-job-msg-cap" style="background:' + capColor + ';">' + icon + '</span>');
    parts.push('<span class="cs-job-msg-text" style="display:flex;justify-content:space-between;align-items:center;">');
    parts.push('<span>' + escHtml(job.description) + '</span>');
    parts.push('<span style="font-size:0.7rem;opacity:0.7;white-space:nowrap;margin-left:8px;">' + escHtml(agent) + '</span>');
    parts.push('</span></div>');
    parts.push('<div style="padding:0 12px 8px 12px;">');
    parts.push('<div style="background:rgba(255,255,255,0.06);border-radius:4px;height:6px;overflow:hidden;margin-bottom:4px;">');
    parts.push('<div style="width:' + pct + '%;height:100%;background:' + barColor + ';transition:width 0.5s ease;border-radius:4px;"></div>');
    parts.push('</div>');
    parts.push('<div style="display:flex;justify-content:space-between;font-size:0.7rem;opacity:0.6;">');
    parts.push('<span>' + countStr + eta + '</span>');
    parts.push('<span>' + pct + '%</span>');
    parts.push('</div></div></div>');
    return parts.join("");
  };

  /* ── Render a single Bridge job into an element ── */

  DepartmentOps.prototype.renderJob = function(job, el) {
    setHtml(el, this.buildJobHtml(job));
  };

  /* ── Render multiple Bridge jobs stacked ── */

  DepartmentOps.prototype.renderBridgeJobs = function(jobs, el, prefix) {
    var self = this;
    var pfx = prefix || el;
    var parts = [];
    jobs.forEach(function(j) {
      parts.push('<div id="bjob-' + pfx + '-' + j.id + '">' + self.buildJobHtml(j) + '</div>');
    });
    setHtml(el, parts.join(""));
  };

  /* ── Apply capacity status to status indicator ── */

  DepartmentOps.prototype._applyCapacity = function(atCapacity) {
    var el = document.getElementById(this.statusElId);
    if (!el) return;
    var dot = el.querySelector(".stn-ops-dot, .cs-ops-dot");
    var textNode = el.childNodes[el.childNodes.length - 1];
    if (atCapacity) {
      if (dot) { dot.style.background = "#f59e0b"; dot.style.boxShadow = "0 0 4px #f59e0b"; }
      if (textNode && textNode.nodeType === 3) textNode.textContent = " AT CAPACITY";
      el.style.color = "#f59e0b";
    } else {
      if (dot) { dot.style.background = ""; dot.style.boxShadow = ""; }
      if (textNode && textNode.nodeType === 3) textNode.textContent = " ONLINE";
      el.style.color = "";
    }
  };

  /* ── Check if station is at capacity ── */

  DepartmentOps.prototype.isAtCapacity = function() {
    return this._atCapacity;
  };

  /* ── Auto-render DB-driven action buttons (bidirectional sync) ── */

  /**
   * Fetch registered actions for this module and render them as buttons
   * in the commandsElId container. Actions trigger via Bridge API and
   * poll for job progress — keeping both module page and Bridge ACTN
   * tab in sync (bidirectional: both see the same running jobs).
   *
   * Usage:
   *   ops.renderActionPanel();  // auto-fetches + renders + wires exec
   */
  DepartmentOps.prototype.renderActionPanel = function() {
    var self = this;
    var cmdsEl = document.getElementById(this.commandsElId);
    if (!cmdsEl) return Promise.resolve();

    return DepartmentOps.fetchActions(this.moduleSource).then(function(actions) {
      if (!actions.length) {
        cmdsEl.innerHTML = '<span class="stn-ops-no-actions" style="color:var(--archie-text-muted);font-size:11px;">No actions registered</span>';
        return;
      }

      cmdsEl.innerHTML = "";
      actions.forEach(function(act) {
        var btn = document.createElement("button");
        btn.className = "stn-ops-cmd cs-ops-cmd " + (act.color_class || "purple");
        btn.innerHTML = (act.icon ? '<span style="margin-right:4px;">' + act.icon + '</span>' : "") + escHtml(act.label);
        if (act.description) btn.title = act.description;
        btn.dataset.actionKey = act.action_key;

        btn.addEventListener("click", function() {
          btn.disabled = true;
          btn.dataset.origText = btn.textContent;
          btn.textContent = "Running...";

          DepartmentOps._execAction(
            self,
            act.action_key,
            act.endpoint_path,
            act.http_method || "POST",
            act.creates_job,
            {},
            self.jobsElId,
            function(result, err) {
              btn.disabled = false;
              btn.textContent = btn.dataset.origText;
              if (err) {
                console.warn("[DepartmentOps] Action failed:", act.action_key, err);
              }
              // Refresh jobs display after action completes
              self.checkJobs().then(function(r) { self.render(r.myJobs); });
            }
          );
        });

        cmdsEl.appendChild(btn);
      });
      self._commandsInjected = true;
    });
  };

  /**
   * Start polling loop — checks Bridge for running jobs every `intervalMs`
   * and re-renders crew + jobs. Call once after initial render.
   *
   * Usage:
   *   ops.startPolling(3000);  // poll every 3 seconds
   */
  DepartmentOps.prototype.startPolling = function(intervalMs) {
    var self = this;
    var ms = intervalMs || 3000;

    function tick() {
      self.checkJobs().then(function(r) {
        self.renderAgents(r.myJobs);
        self.renderJobs(r.myJobs);
      });
    }
    tick();  // initial fetch
    this._pollTimer = setInterval(tick, ms);
  };

  DepartmentOps.prototype.stopPolling = function() {
    if (this._pollTimer) {
      clearInterval(this._pollTimer);
      this._pollTimer = null;
    }
  };

  /* ── Fetch DB-driven actions for a module ── */

  /**
   * Fetch registered actions for a module from the station_actions table.
   * Returns a promise resolving to an array of action objects.
   *
   * Usage:
   *   DepartmentOps.fetchActions("repair_bay").then(function(actions) { ... });
   */
  DepartmentOps.fetchActions = function(moduleSource) {
    return fetch("/tools/starbase/api/station-actions?module_source=" + encodeURIComponent(moduleSource))
      .then(function(r) { return r.json(); })
      .then(function(data) {
        return (data.success && data.actions) ? data.actions : [];
      })
      .catch(function() { return []; });
  };

  /**
   * Execute a station action by POSTing to its endpoint.
   * If createsJob is true, starts polling via the instance's pollJob method.
   *
   * @param {DepartmentOps} ops   - DepartmentOps instance (for pollJob)
   * @param {string} actionKey - e.g. "repair_bay.scan.batch"
   * @param {string} endpointPath - e.g. "/tools/repair-bay/api/scan/batch"
   * @param {string} httpMethod - "POST" or "GET"
   * @param {boolean} createsJob - whether to poll for job progress
   * @param {object} params - optional body params
   * @param {string|HTMLElement} jobElId - element to render job progress into
   * @param {Function} onComplete - callback(job) when done
   */
  DepartmentOps._execAction = function(ops, actionKey, endpointPath, httpMethod, createsJob, params, jobElId, onComplete) {
    var fetchOpts = {
      method: httpMethod || "POST",
      headers: { "Content-Type": "application/json" }
    };
    if (params && Object.keys(params).length > 0) {
      fetchOpts.body = JSON.stringify(params);
    }

    return fetch(endpointPath, fetchOpts)
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.success === false) {
          if (onComplete) onComplete(null, data.error || "Action failed");
          return;
        }
        var jobId = data.job_id || data.jobId || data.id;
        if (createsJob && jobId && ops) {
          ops.pollJob(jobId, jobElId, onComplete);
        } else {
          if (onComplete) onComplete(data);
        }
      })
      .catch(function(err) {
        if (onComplete) onComplete(null, "Network error");
      });
  };

  /* ── Expose helpers for module-specific code ── */
  DepartmentOps.escHtml = escHtml;
  DepartmentOps.setHtml = setHtml;

  window.DepartmentOps = DepartmentOps;
})();
