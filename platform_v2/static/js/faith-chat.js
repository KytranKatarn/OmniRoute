/* Faith — F.A.I.T.H. chat overlay */
(function () {
  var MAX_RETRIES = 20;
  var retries = 0;
  function init() {
    if (window.archieOverlay) {
      window.archieOverlay.init({
        agentId: 352,
        agentName: "F.A.I.T.H.",
        accentColor: "#a78bfa",
        moduleKey: "faith",
        greeting: "F.A.I.T.H. present. Ask me about devotionals, reflections, or spiritual guidance.",
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
