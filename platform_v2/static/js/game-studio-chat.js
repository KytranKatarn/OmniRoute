/* Game Studio — M.U.S.E. chat overlay */
(function () {
  var MAX_RETRIES = 20;
  var retries = 0;
  function init() {
    if (window.archieOverlay) {
      window.archieOverlay.init({
        agentId: 138,
        agentName: "M.U.S.E.",
        accentColor: "#f472b6",
        moduleKey: "game_studio",
        greeting: "M.U.S.E. here. I can help with game design, scene creation, asset management, or world-building.",
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
