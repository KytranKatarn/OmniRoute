/* ═══════════════════════════════════════════════════════
   GlassNav — Frosted Glass Navigation Bar
   Shared component. No dependencies.

   Usage:
     var nav = new GlassNav(navEl, {
       onSwitch: function(tabName) {}
     });
     nav.setActive("dashboard");
   ═══════════════════════════════════════════════════════ */

(function() {
"use strict";

function GlassNav(el, opts) {
  if (!el) throw new Error("GlassNav: element required");
  opts = opts || {};

  this.el = el;
  this.onSwitch = opts.onSwitch || null;
  this._indicator = el.querySelector(".glass-nav-indicator");
  this._items = Array.prototype.slice.call(el.querySelectorAll(".glass-nav-item"));

  this._bindEvents();
  // Position indicator on the initially active item
  var active = el.querySelector(".glass-nav-item.active");
  if (active && this._indicator) {
    this._moveIndicator(active, false);
  }
}

GlassNav.prototype._bindEvents = function() {
  var self = this;
  this._items.forEach(function(item) {
    item.addEventListener("click", function() {
      var tab = item.dataset.tab;
      if (!tab) return;
      self.setActive(tab);
      if (self.onSwitch) self.onSwitch(tab);
    });
  });

  // Reposition indicator on resize
  this._resizeHandler = function() {
    var active = self.el.querySelector(".glass-nav-item.active");
    if (active) self._moveIndicator(active, false);
  };
  window.addEventListener("resize", this._resizeHandler);
};

GlassNav.prototype.setActive = function(tab) {
  var target = null;
  this._items.forEach(function(item) {
    if (item.dataset.tab === tab) {
      item.classList.add("active");
      target = item;
    } else {
      item.classList.remove("active");
    }
  });
  if (target && this._indicator) {
    this._moveIndicator(target, true);
  }
};

GlassNav.prototype._moveIndicator = function(item, animate) {
  var indicator = this._indicator;
  if (!indicator || !item) return;

  var trackRect = this.el.querySelector(".glass-nav-track").getBoundingClientRect();
  var itemRect = item.getBoundingClientRect();

  var left = itemRect.left - trackRect.left;
  var width = itemRect.width;

  if (!animate) {
    indicator.style.transition = "none";
  }
  indicator.style.left = left + "px";
  indicator.style.width = width + "px";

  if (!animate) {
    // Force reflow then restore transition
    indicator.offsetHeight;
    indicator.style.transition = "";
  }
};

GlassNav.prototype.destroy = function() {
  if (this._resizeHandler) {
    window.removeEventListener("resize", this._resizeHandler);
  }
};

window.GlassNav = GlassNav;

})();
