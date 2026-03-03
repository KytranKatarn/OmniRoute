/* archie-time.js — Global Timezone-Aware Timestamp Formatter
 *
 * Converts UTC timestamps to the user's local timezone automatically.
 *
 * Usage (HTML — auto-converted on page load):
 *   <span data-utc="2026-01-15T15:45:30Z" data-fmt="datetime">Jan 15, 2026</span>
 *
 * Usage (JS — for dynamically built content):
 *   ArchieTime.format("2026-01-15T15:45:30Z", "datetime")  → "Jan 15, 2026, 3:45 PM"
 *   ArchieTime.age("2026-01-15T15:45:30Z")                 → "3d ago"
 *   ArchieTime.refresh()                                     → re-scan DOM for new [data-utc] elements
 *
 * Formats:
 *   "age"      → "just now", "5m ago", "2h ago", "3d ago", then falls back to date
 *   "date"     → "Jan 15, 2026"
 *   "datetime" → "Jan 15, 2026, 3:45 PM"
 *   "time"     → "3:45 PM"
 *   "short"    → "Jan 15, 3:45 PM" (no year)
 *   "iso"      → "2026-01-15"
 */
(function() {
  "use strict";

  var PROCESSED_ATTR = "data-utc-done";

  /* ── Core formatters ──────────────────────────── */

  function parseDate(str) {
    if (!str) return null;
    var d = new Date(str);
    if (isNaN(d.getTime())) return null;
    return d;
  }

  function formatAge(dateStr) {
    var d = parseDate(dateStr);
    if (!d) return "\u2014";
    var diff = (Date.now() - d.getTime()) / 1000;
    if (diff < 0) return "just now";
    if (diff < 60) return "just now";
    if (diff < 3600) return Math.floor(diff / 60) + "m ago";
    if (diff < 86400) return Math.floor(diff / 3600) + "h ago";
    if (diff < 604800) return Math.floor(diff / 86400) + "d ago";
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  }

  function formatDate(dateStr) {
    var d = parseDate(dateStr);
    if (!d) return "\u2014";
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  }

  function formatDateTime(dateStr) {
    var d = parseDate(dateStr);
    if (!d) return "\u2014";
    return d.toLocaleDateString("en-US", {
      month: "short", day: "numeric", year: "numeric",
      hour: "numeric", minute: "2-digit", hour12: true
    });
  }

  function formatTime(dateStr) {
    var d = parseDate(dateStr);
    if (!d) return "\u2014";
    return d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", hour12: true });
  }

  function formatShort(dateStr) {
    var d = parseDate(dateStr);
    if (!d) return "\u2014";
    return d.toLocaleDateString("en-US", {
      month: "short", day: "numeric",
      hour: "numeric", minute: "2-digit", hour12: true
    });
  }

  function formatIso(dateStr) {
    var d = parseDate(dateStr);
    if (!d) return "\u2014";
    var y = d.getFullYear();
    var m = String(d.getMonth() + 1).padStart(2, "0");
    var day = String(d.getDate()).padStart(2, "0");
    return y + "-" + m + "-" + day;
  }

  /* ── Format dispatcher ────────────────────────── */

  function format(dateStr, fmt) {
    fmt = fmt || "datetime";
    switch (fmt) {
      case "age":      return formatAge(dateStr);
      case "date":     return formatDate(dateStr);
      case "datetime": return formatDateTime(dateStr);
      case "time":     return formatTime(dateStr);
      case "short":    return formatShort(dateStr);
      case "iso":      return formatIso(dateStr);
      default:         return formatDateTime(dateStr);
    }
  }

  /* ── DOM scanner ──────────────────────────────── */

  function processElement(el) {
    if (el.hasAttribute(PROCESSED_ATTR)) return;
    var utc = el.getAttribute("data-utc");
    var fmt = el.getAttribute("data-fmt") || "datetime";
    if (!utc) return;
    var result = format(utc, fmt);
    el.textContent = result;
    /* Add tooltip with full local datetime for short formats */
    if (fmt === "age" || fmt === "date" || fmt === "time" || fmt === "short") {
      el.title = formatDateTime(utc);
    }
    el.setAttribute(PROCESSED_ATTR, "1");
  }

  function refresh(root) {
    var container = root || document;
    var els = container.querySelectorAll("[data-utc]:not([" + PROCESSED_ATTR + "])");
    for (var i = 0; i < els.length; i++) {
      processElement(els[i]);
    }
  }

  /* ── Auto-init on page load ───────────────────── */

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function() { refresh(); });
  } else {
    refresh();
  }

  /* ── MutationObserver for dynamic content ─────── */
  if (typeof MutationObserver !== "undefined") {
    var observer = new MutationObserver(function(mutations) {
      var needsScan = false;
      for (var i = 0; i < mutations.length; i++) {
        var added = mutations[i].addedNodes;
        for (var j = 0; j < added.length; j++) {
          if (added[j].nodeType === 1) {
            if (added[j].hasAttribute && added[j].hasAttribute("data-utc")) {
              processElement(added[j]);
            }
            if (added[j].querySelectorAll) {
              var inner = added[j].querySelectorAll("[data-utc]:not([" + PROCESSED_ATTR + "])");
              for (var k = 0; k < inner.length; k++) {
                processElement(inner[k]);
              }
            }
          }
        }
      }
    });
    observer.observe(document.documentElement, { childList: true, subtree: true });
  }

  /* ── Public API ───────────────────────────────── */

  window.ArchieTime = {
    format: format,
    age: formatAge,
    date: formatDate,
    datetime: formatDateTime,
    time: formatTime,
    short: formatShort,
    iso: formatIso,
    refresh: refresh
  };

})();
