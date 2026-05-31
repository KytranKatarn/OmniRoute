/* C.R.E.E.D. Command Center — tab switching (P0 scaffold). */
(function () {
  document.addEventListener("DOMContentLoaded", function () {
    var tabs = document.querySelectorAll(".cc-tab");
    var panes = document.querySelectorAll(".cc-pane");
    tabs.forEach(function (tab) {
      tab.addEventListener("click", function () {
        var name = tab.getAttribute("data-tab");
        tabs.forEach(function (t) { t.classList.toggle("active", t === tab); });
        panes.forEach(function (p) {
          p.classList.toggle("active", p.id === "pane-" + name);
        });
        if (history.replaceState) history.replaceState(null, "", "#" + name);
      });
    });
    // Deep-link: open the tab named in the URL hash.
    var hash = (location.hash || "").replace("#", "");
    if (hash) {
      var target = document.querySelector('.cc-tab[data-tab="' + hash + '"]');
      if (target) target.click();
    }
  });
})();
