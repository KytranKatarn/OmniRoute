/* lcars-header.js -- LCARS Header Component Behavior
   Handles: tab switching, alert state management, toast notifications, stardate.
   Works with lcars-header.html + lcars-header.css.
*/

(function () {
  "use strict";

  /* -- Tab Switching -- */

  window.lcarsHeaderSwitchTab = function (tabId) {
    var tabs = document.querySelectorAll(".lcars-header-tab");
    tabs.forEach(function (t) {
      t.classList.toggle("active", t.dataset.tab === tabId);
    });
    if (typeof window.onLcarsTabSwitch === "function") {
      window.onLcarsTabSwitch(tabId);
    }
  };

  /* -- Alert State Management -- */

  window.lcarsSetAlertState = function (state) {
    var header = document.getElementById("lcarsHeader");
    if (header) {
      header.dataset.alertState = state;
    }
  };

  /* -- Toast Notifications -- */

  var _toastId = 0;

  /**
   * lcarsToast(title, message, severity, options)
   * options: { durationMs, href, actionLabel }
   * - href: clicking toast navigates here
   * - actionLabel: text shown at bottom (e.g. "VIEW APPROVALS")
   */
  window.lcarsToast = function (title, message, severity, options) {
    severity = severity || "info";
    if (typeof options === "number") {
      options = { durationMs: options }; // backwards compat
    }
    options = options || {};
    var durationMs = typeof options.durationMs !== "undefined" ? options.durationMs
      : severity === "error" ? 0 : severity === "warning" ? 10000 : 5000;

    var container = document.getElementById("lcarsToastContainer");
    if (!container) return;

    var toast = document.createElement("div");
    toast.className = "lcars-toast";
    toast.dataset.severity = severity;
    toast.id = "lcarsToast" + (++_toastId);

    // Store dismiss callback on the element
    if (options.onDismiss) {
      toast._onDismiss = options.onDismiss;
    }

    // Click to navigate (also dismisses)
    if (options.href) {
      toast.addEventListener("click", function (e) {
        if (e.target.closest(".lcars-toast-close")) return;
        if (toast._onDismiss) toast._onDismiss();
        window.location.href = options.href;
      });
    }

    // LCARS elbow accent
    var accent = document.createElement("div");
    accent.className = "lcars-toast-accent";
    toast.appendChild(accent);

    // Content area
    var content = document.createElement("div");
    content.className = "lcars-toast-content";

    // Header row (title + close)
    var header = document.createElement("div");
    header.className = "lcars-toast-header";

    var titleEl = document.createElement("span");
    titleEl.className = "lcars-toast-title";
    titleEl.textContent = title;
    header.appendChild(titleEl);

    var closeBtn = document.createElement("button");
    closeBtn.className = "lcars-toast-close";
    closeBtn.textContent = "\u00d7";
    closeBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      _removeToast(toast);
    });
    header.appendChild(closeBtn);
    content.appendChild(header);

    // Message
    if (message) {
      var msgEl = document.createElement("span");
      msgEl.className = "lcars-toast-message";
      msgEl.textContent = message;
      content.appendChild(msgEl);
    }

    // Action hint
    if (options.actionLabel || options.href) {
      var actionEl = document.createElement("span");
      actionEl.className = "lcars-toast-action";
      actionEl.textContent = options.actionLabel || "TAP TO VIEW \u25B8";
      content.appendChild(actionEl);
    }

    toast.appendChild(content);
    container.appendChild(toast);

    if (durationMs > 0) {
      setTimeout(function () { _removeToast(toast); }, durationMs);
    }
  };

  function _removeToast(toast) {
    if (!toast || !toast.parentNode) return;
    if (toast._onDismiss) toast._onDismiss();
    toast.classList.add("removing");
    setTimeout(function () {
      if (toast.parentNode) toast.parentNode.removeChild(toast);
    }, 300);
  }

  /* -- Notification Polling -- */

  var _notifPollInterval = null;

  function _pollNotifications() {
    fetch("/api/notifications/count")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data.success) return;
        var critical = data.critical || 0;
        var errors = data.errors || 0;
        var unread = data.unread || 0;

        // Update elbow alert state
        if (critical > 0) {
          lcarsSetAlertState("critical");
        } else if (errors > 0) {
          lcarsSetAlertState("warning");
        } else {
          lcarsSetAlertState("normal");
        }

        // Update badge counts (strip + elbow)
        var badges = ["lcarsStripBadge", "lcarsNotifBadge"];
        badges.forEach(function (id) {
          var badge = document.getElementById(id);
          if (badge) {
            if (unread > 0) {
              badge.textContent = unread > 99 ? "99+" : String(unread);
              badge.style.display = "inline-flex";
            } else {
              badge.style.display = "none";
            }
          }
        });
      })
      .catch(function () {}); // Silent fail — polling recovers next tick
  }

  // Expose for Mark All Read button
  window._pollNotifications = _pollNotifications;

  function _startNotifPolling() {
    _pollNotifications(); // Immediate first check
    _notifPollInterval = setInterval(_pollNotifications, 30000); // Every 30s
  }

  function _stopNotifPolling() {
    if (_notifPollInterval) {
      clearInterval(_notifPollInterval);
      _notifPollInterval = null;
    }
  }

  /* -- Notification Modal -- */

  window.lcarsOpenNotifications = function () {
    var overlay = document.getElementById("lcarsNotifModal");
    if (!overlay) return;

    overlay.classList.add("active");
    _loadNotificationList();
  };

  window.lcarsCloseNotifications = function () {
    var overlay = document.getElementById("lcarsNotifModal");
    if (overlay) overlay.classList.remove("active");
  };

  function _loadNotificationList() {
    var body = document.getElementById("lcarsNotifBody");
    if (!body) return;

    body.textContent = "";
    var loading = document.createElement("p");
    loading.style.color = "#94a3b8";
    loading.textContent = "Loading notifications...";
    body.appendChild(loading);

    fetch("/api/notifications")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        body.textContent = "";

        if (!data.success || !data.notifications || data.notifications.length === 0) {
          var empty = document.createElement("p");
          empty.style.color = "#64748b";
          empty.textContent = "No notifications";
          body.appendChild(empty);
          return;
        }

        data.notifications.forEach(function (n) {
          var wrapper = document.createElement("div");
          wrapper.style.cssText = "border-bottom:1px solid rgba(var(--cat-accent-rgb,0,255,255),0.08);transition:opacity 0.3s ease,transform 0.3s ease,max-height 0.5s ease;overflow:hidden;";

          // Summary row (clickable)
          var item = document.createElement("div");
          item.style.cssText = "display:flex;align-items:flex-start;gap:10px;padding:10px 12px;cursor:pointer;transition:background 0.15s ease;";
          item.addEventListener("mouseenter", function () { item.style.background = "rgba(var(--cat-accent-rgb,0,255,255),0.04)"; });
          item.addEventListener("mouseleave", function () { item.style.background = "none"; });

          // Severity dot
          var dot = document.createElement("span");
          var dotColor = n.type === "error" ? "#ef4444" : n.type === "warning" ? "#ff9f43" : "var(--cat-accent, #00ffff)";
          dot.style.cssText = "width:8px;height:8px;border-radius:50%;flex-shrink:0;margin-top:6px;background:" + dotColor + ";box-shadow:0 0 6px " + dotColor + ";";
          item.appendChild(dot);

          // Summary content
          var content = document.createElement("div");
          content.style.cssText = "flex:1;min-width:0;";

          var title = document.createElement("div");
          title.style.cssText = "font-size:0.8rem;color:#e2e8f0;font-family:'Antonio',sans-serif;text-transform:uppercase;letter-spacing:0.3px;";
          title.textContent = n.title || "Notification";
          content.appendChild(title);

          // Short preview
          var preview = document.createElement("div");
          preview.style.cssText = "font-size:0.65rem;color:#64748b;margin-top:2px;";
          var previewParts = [];
          if (n.source) previewParts.push(n.source);
          if (n.created_at) {
            var d = new Date(n.created_at);
            if (!isNaN(d)) previewParts.push(d.toLocaleString());
          }
          preview.textContent = previewParts.join(" \u2022 ");
          content.appendChild(preview);

          item.appendChild(content);

          // Arrow indicator
          var arrow = document.createElement("span");
          arrow.style.cssText = "flex-shrink:0;color:rgba(var(--cat-accent-rgb,0,255,255),0.3);font-size:0.7rem;margin-top:4px;transition:transform 0.2s ease;";
          arrow.textContent = "\u25B8";
          item.appendChild(arrow);

          wrapper.appendChild(item);

          // Detail panel (hidden by default)
          var detail = document.createElement("div");
          detail.style.cssText = "max-height:0;overflow:hidden;transition:max-height 0.3s ease,padding 0.3s ease;padding:0 12px 0 30px;background:rgba(var(--cat-accent-rgb,0,255,255),0.03);";

          // Parse message
          var fullMsg = n.message || "No details available.";
          try {
            var parsed = JSON.parse(n.message);
            if (typeof parsed === "object") {
              fullMsg = Object.keys(parsed).map(function (k) { return k + ": " + parsed[k]; }).join("\n");
            }
          } catch (e) { /* not JSON */ }

          // Detail fields
          var fields = [
            { label: "TYPE", value: (n.type || "info").toUpperCase() },
            { label: "PRIORITY", value: (n.priority || "normal").toUpperCase() },
            { label: "SOURCE", value: n.source || "—" },
            { label: "MESSAGE", value: fullMsg },
            { label: "CREATED", value: n.created_at ? new Date(n.created_at).toLocaleString() : "—" },
            { label: "ID", value: n.id ? "#" + n.id : "—" }
          ];

          fields.forEach(function (f) {
            var row = document.createElement("div");
            row.style.cssText = "display:flex;gap:8px;padding:3px 0;";

            var lbl = document.createElement("span");
            lbl.style.cssText = "font-size:0.55rem;color:rgba(var(--cat-accent-rgb,0,255,255),0.5);font-family:'Antonio',sans-serif;letter-spacing:0.5px;width:60px;flex-shrink:0;text-transform:uppercase;";
            lbl.textContent = f.label;
            row.appendChild(lbl);

            var val = document.createElement("span");
            val.style.cssText = "font-size:0.65rem;color:#cbd5e1;font-family:'IBM Plex Mono',monospace;white-space:pre-wrap;word-break:break-word;";
            val.textContent = f.value;
            row.appendChild(val);

            detail.appendChild(row);
          });

          // Action buttons in detail
          var actions = document.createElement("div");
          actions.style.cssText = "display:flex;gap:8px;padding:8px 0;margin-top:4px;border-top:1px solid rgba(var(--cat-accent-rgb,0,255,255),0.08);";

          if (n.id) {
            var clearBtn = document.createElement("button");
            clearBtn.style.cssText = "background:none;border:1px solid rgba(var(--cat-accent-rgb,0,255,255),0.25);color:var(--cat-accent,#00ffff);font-size:0.55rem;font-family:'Antonio',sans-serif;letter-spacing:0.8px;padding:4px 12px;border-radius:3px;cursor:pointer;text-transform:uppercase;transition:background 0.15s;";
            clearBtn.textContent = "CLEAR";
            clearBtn.addEventListener("click", function (e) {
              e.stopPropagation();
              fetch("/api/notifications/mark-read/" + n.id, { method: "POST" })
                .then(function () {
                  wrapper.style.opacity = "0";
                  wrapper.style.transform = "translateX(30px)";
                  wrapper.style.maxHeight = "0";
                  setTimeout(function () {
                    if (wrapper.parentNode) wrapper.parentNode.removeChild(wrapper);
                    _pollNotifications();
                    if (body.querySelectorAll("div").length === 0) {
                      var empty = document.createElement("p");
                      empty.style.color = "#64748b";
                      empty.textContent = "All clear — no notifications";
                      body.appendChild(empty);
                    }
                  }, 300);
                });
            });
            clearBtn.addEventListener("mouseenter", function () { clearBtn.style.background = "rgba(var(--cat-accent-rgb,0,255,255),0.1)"; });
            clearBtn.addEventListener("mouseleave", function () { clearBtn.style.background = "none"; });
            actions.appendChild(clearBtn);
          }

          detail.appendChild(actions);
          wrapper.appendChild(detail);

          // Toggle detail on click
          var expanded = false;
          item.addEventListener("click", function () {
            expanded = !expanded;
            if (expanded) {
              detail.style.maxHeight = "300px";
              detail.style.padding = "8px 12px 8px 30px";
              arrow.style.transform = "rotate(90deg)";
              arrow.style.color = "var(--cat-accent, #00ffff)";
            } else {
              detail.style.maxHeight = "0";
              detail.style.padding = "0 12px 0 30px";
              arrow.style.transform = "rotate(0deg)";
              arrow.style.color = "rgba(var(--cat-accent-rgb,0,255,255),0.3)";
            }
          });

          body.appendChild(wrapper);
        });
      })
      .catch(function () {
        body.textContent = "";
        var err = document.createElement("p");
        err.style.color = "#ef4444";
        err.textContent = "Failed to load notifications";
        body.appendChild(err);
      });
  }

  /* -- Stardate -- */

  function _updateStardate() {
    var el = document.getElementById("lcarsStardate");
    if (!el) return;
    var now = new Date();
    var year = now.getFullYear();
    var start = new Date(year, 0, 1);
    var diff = now - start;
    var oneDay = 86400000;
    var day = Math.floor(diff / oneDay);
    var fraction = Math.floor((diff % oneDay) / oneDay * 10);
    el.textContent = "SD " + year + day + "." + fraction;
  }

  /* -- Ops Summary Integration (replaces ops-alert-bar when LCARS header present) -- */

  var _opsLastSig = sessionStorage.getItem("lcars_ops_sig") || "";
  var _opsFirstPoll = true;
  var _opsPollInterval = null;
  var _SS_SIG = "lcars_ops_sig";
  var _SS_DISMISSED = "lcars_ops_dismissed";

  function _isOpsDismissed(key) {
    try {
      var d = JSON.parse(sessionStorage.getItem(_SS_DISMISSED) || "{}");
      return !!d[key];
    } catch (e) { return false; }
  }

  function _dismissOps(key) {
    try {
      var d = JSON.parse(sessionStorage.getItem(_SS_DISMISSED) || "{}");
      d[key] = Date.now();
      sessionStorage.setItem(_SS_DISMISSED, JSON.stringify(d));
    } catch (e) {}
  }

  function _pollOpsSummary() {
    fetch("/tools/autonomy/api/ops-summary")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data) return;

        var approvals = (data.approvals && data.approvals.pending) || 0;
        var aj = data.active_jobs || {};
        var jobs = (aj.bridge_running || 0) + (aj.bridge_pending || 0);
        var e1h = data.errors_1h || {};
        var errors = (e1h.bridge_failed || 0) + (e1h.loop_errors || 0);

        // Build signature for change detection
        var sig = "a:" + approvals + "|e:" + errors + "|j:" + jobs;
        var changed = sig !== _opsLastSig;
        _opsLastSig = sig;
        sessionStorage.setItem(_SS_SIG, sig);

        // Update elbow alert state based on ops severity (always update, no toasts needed)
        if (errors > 0) {
          lcarsSetAlertState("critical");
        } else if (approvals > 0) {
          lcarsSetAlertState("warning");
        } else {
          lcarsSetAlertState("normal");
        }

        // On first poll (page load), just record state — don't toast
        if (_opsFirstPoll) {
          _opsFirstPoll = false;
          // Clear dismissed if state changed (new issue)
          if (changed) {
            sessionStorage.removeItem(_SS_DISMISSED);
          }
          return;
        }

        // Toast only when state CHANGES and not dismissed this session
        if (changed && approvals > 0 && !_isOpsDismissed("approvals")) {
          lcarsToast(
            "Approvals Pending",
            approvals + " approval" + (approvals > 1 ? "s" : "") + " require your review",
            "warning",
            {
              href: "/tools/autonomy#approvals",
              actionLabel: "OPEN APPROVALS \u25B8",
              onDismiss: function () { _dismissOps("approvals"); }
            }
          );
        }
        if (changed && errors > 0 && !_isOpsDismissed("errors")) {
          lcarsToast(
            "System Errors",
            errors + " error" + (errors > 1 ? "s" : "") + " detected in the last hour",
            "error",
            {
              href: "/tools/autonomy#active",
              actionLabel: "VIEW ERROR LOG \u25B8",
              onDismiss: function () { _dismissOps("errors"); }
            }
          );
        }
      })
      .catch(function () {}); // Silent fail — recovers next tick
  }

  /* -- Admin Notification Channel Integration -- */

  function _initAdminNotifChannel() {
    if (typeof BroadcastChannel === "undefined") return;
    try {
      var channel = new BroadcastChannel("archie_admin_notifications");
      channel.addEventListener("message", function (ev) {
        var d = ev.data;
        if (d && d.type === "show" && d.notification) {
          var n = d.notification;
          var severity = n.type === "error" ? "error" : n.type === "warning" ? "warning" : "info";
          lcarsToast(n.title || "System Alert", n.text || "", severity, {
            href: n.href || null,
            actionLabel: n.actionLabel || null
          });
        }
      });
    } catch (e) {}
  }

  /* -- Init -- */

  document.addEventListener("DOMContentLoaded", function () {
    _updateStardate();
    setInterval(_updateStardate, 60000);
    _startNotifPolling();

    // Ops summary polling (replaces ops-alert-bar)
    _pollOpsSummary();
    _opsPollInterval = setInterval(_pollOpsSummary, 30000);

    // Listen for admin notification broadcasts
    _initAdminNotifChannel();

    if (typeof lucide !== "undefined" && lucide.createIcons) {
      lucide.createIcons();
    }

    // Wire elbow click to open notifications
    var elbow = document.getElementById("lcarsHeaderElbow");
    if (elbow) {
      elbow.style.cursor = "pointer";
      elbow.addEventListener("click", function (e) {
        if (e.target.closest(".lcars-header-back") || e.target.closest(".lcars-header-util")) return;
        lcarsOpenNotifications();
      });
    }
  });
})();
