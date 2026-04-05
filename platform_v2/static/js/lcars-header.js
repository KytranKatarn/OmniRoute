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

  /* -- Init -- */

  document.addEventListener("DOMContentLoaded", function () {
    _updateStardate();
    setInterval(_updateStardate, 60000);
    if (typeof lucide !== "undefined" && lucide.createIcons) {
      lucide.createIcons();
    }
  });
})();
