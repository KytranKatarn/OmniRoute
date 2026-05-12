/* DOC — V.I.T.A.L. chat overlay */
(function () {
  var MAX_RETRIES = 20;
  var retries = 0;
  function init() {
    if (window.archieOverlay) {
      window.archieOverlay.init({
        agentId: 148,
        agentName: "V.I.T.A.L.",
        accentColor: "#3b82f6",
        moduleKey: "doc",
        greeting: "V.I.T.A.L. here. I can help review symptoms, track medications, or prepare for appointments.",
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
