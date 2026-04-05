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

  window.lcarsToast = function (title, message, severity, durationMs) {
    severity = severity || "info";
    if (typeof durationMs === "undefined") {
      durationMs = severity === "error" ? 0 : severity === "warning" ? 10000 : 5000;
    }

    var container = document.getElementById("lcarsToastContainer");
    if (!container) return;

    var toast = document.createElement("div");
    toast.className = "lcars-toast";
    toast.dataset.severity = severity;
    toast.id = "lcarsToast" + (++_toastId);

    var accent = document.createElement("div");
    accent.className = "lcars-toast-accent";
    toast.appendChild(accent);

    var content = document.createElement("div");
    content.className = "lcars-toast-content";

    var titleEl = document.createElement("span");
    titleEl.className = "lcars-toast-title";
    titleEl.textContent = title;
    content.appendChild(titleEl);

    if (message) {
      var msgEl = document.createElement("span");
      msgEl.className = "lcars-toast-message";
      msgEl.textContent = message;
      content.appendChild(msgEl);
    }
    toast.appendChild(content);

    var closeBtn = document.createElement("button");
    closeBtn.className = "lcars-toast-close";
    closeBtn.textContent = "\u00d7";
    closeBtn.addEventListener("click", function () { _removeToast(toast); });
    toast.appendChild(closeBtn);

    container.appendChild(toast);

    if (durationMs > 0) {
      setTimeout(function () { _removeToast(toast); }, durationMs);
    }
  };

  function _removeToast(toast) {
    if (!toast || !toast.parentNode) return;
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

        // Update badge count on elbow
        var badge = document.getElementById("lcarsNotifBadge");
        if (badge) {
          if (unread > 0) {
            badge.textContent = unread > 99 ? "99+" : String(unread);
            badge.style.display = "flex";
          } else {
            badge.style.display = "none";
          }
        }
      })
      .catch(function () {}); // Silent fail — polling recovers next tick
  }

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
          var item = document.createElement("div");
          item.style.cssText = "display:flex;align-items:flex-start;gap:10px;padding:10px 0;border-bottom:1px solid rgba(var(--cat-accent-rgb,0,255,255),0.1);cursor:pointer;";

          // Severity dot
          var dot = document.createElement("span");
          var dotColor = n.type === "error" ? "#ef4444" : n.type === "warning" ? "#ff9f43" : "var(--cat-accent, #00ffff)";
          dot.style.cssText = "width:8px;height:8px;border-radius:50%;flex-shrink:0;margin-top:4px;background:" + dotColor + ";box-shadow:0 0 6px " + dotColor + ";";
          item.appendChild(dot);

          // Content
          var content = document.createElement("div");
          content.style.cssText = "flex:1;min-width:0;";

          var title = document.createElement("div");
          title.style.cssText = "font-size:0.8rem;color:#e2e8f0;font-family:'Antonio',sans-serif;text-transform:uppercase;letter-spacing:0.3px;";
          title.textContent = n.title || "Notification";
          content.appendChild(title);

          if (n.message) {
            var msg = document.createElement("div");
            msg.style.cssText = "font-size:0.7rem;color:#94a3b8;margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;";
            msg.textContent = n.message;
            content.appendChild(msg);
          }

          var meta = document.createElement("div");
          meta.style.cssText = "font-size:0.6rem;color:#475569;margin-top:3px;";
          meta.textContent = (n.source || "") + (n.time_ago ? " \u2022 " + n.time_ago : "");
          content.appendChild(meta);

          item.appendChild(content);

          // Click to mark read
          if (n.id) {
            item.addEventListener("click", function () {
              fetch("/api/notifications/mark-read/" + n.id, { method: "POST" })
                .then(function () {
                  item.style.opacity = "0.4";
                  _pollNotifications();
                });
            });
          }

          body.appendChild(item);
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

  var _opsLastSig = "";
  var _opsPollInterval = null;

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

        // Update elbow alert state based on ops severity
        if (errors > 0) {
          lcarsSetAlertState("critical");
        } else if (approvals > 0) {
          lcarsSetAlertState("warning");
        } else {
          lcarsSetAlertState("normal");
        }

        // Toast on new issues only (not every poll)
        if (changed && approvals > 0) {
          lcarsToast("Approvals Pending", approvals + " approval" + (approvals > 1 ? "s" : "") + " waiting", "warning");
        }
        if (changed && errors > 0) {
          lcarsToast("Errors Detected", errors + " error" + (errors > 1 ? "s" : "") + " in last hour", "error");
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
          lcarsToast(n.title || "System Alert", n.text || "", severity);
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
