/* Fitness — V.I.T.A.L. chat overlay */
(function () {
  var MAX_RETRIES = 20;
  var retries = 0;
  function init() {
    if (window.archieOverlay) {
      window.archieOverlay.init({
        agentId: 148,
        agentName: "V.I.T.A.L.",
        accentColor: "#22d3ee",
        moduleKey: "fitness",
        greeting: "V.I.T.A.L. here. Ask me about your fitness goals, workout plans, or progress tracking.",
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
