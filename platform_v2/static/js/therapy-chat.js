/* Therapy — V.I.T.A.L. chat overlay */
(function () {
  var MAX_RETRIES = 20;
  var retries = 0;
  function init() {
    if (window.archieOverlay) {
      window.archieOverlay.init({
        agentId: 148,
        agentName: "V.I.T.A.L.",
        accentColor: "#60a5fa",
        moduleKey: "therapy",
        greeting: "V.I.T.A.L. here. I'm with you. Share what's on your mind or ask about your wellness journey.",
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
