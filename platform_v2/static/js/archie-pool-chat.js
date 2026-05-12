/* Archie Pool — L.E.D.G.E.R. chat overlay */
(function () {
  var MAX_RETRIES = 20;
  var retries = 0;
  function init() {
    if (window.archieOverlay) {
      window.archieOverlay.init({
        agentId: 144,
        agentName: "L.E.D.G.E.R.",
        accentColor: "#10b981",
        moduleKey: "archie_pool",
        greeting: "L.E.D.G.E.R. online. Ask me about pool stats, miner performance, or RVN earnings.",
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
