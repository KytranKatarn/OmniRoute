/* Media Studio — M.U.S.E. chat overlay */
(function () {
  var MAX_RETRIES = 20;
  var retries = 0;
  function init() {
    if (window.archieOverlay) {
      window.archieOverlay.init({
        agentId: 138,
        agentName: "M.U.S.E.",
        accentColor: "#f472b6",
        moduleKey: "media_studio",
        greeting: "M.U.S.E. here. Ask me about image generation, portraits, gallery management, or creative workflows.",
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
