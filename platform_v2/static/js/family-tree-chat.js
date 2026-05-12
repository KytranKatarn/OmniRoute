/* Family Tree — H.E.R.I.T.A.G.E. chat overlay */
(function () {
  var MAX_RETRIES = 20;
  var retries = 0;
  function init() {
    if (window.archieOverlay) {
      window.archieOverlay.init({
        agentId: 331,
        agentName: "H.E.R.I.T.A.G.E.",
        accentColor: "#f59e0b",
        moduleKey: "family_tree",
        greeting: "H.E.R.I.T.A.G.E. online. I can help trace lineage, analyze relationships, or research your family history.",
      });
    } else if (retries++ < MAX_RETRIES) {
      setTimeout(init, 300);
    }
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
