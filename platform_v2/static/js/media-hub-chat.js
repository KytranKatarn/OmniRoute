/* Media Hub — M.A.V.E.N. chat overlay */
(function () {
  var MAX_RETRIES = 20;
  var retries = 0;
  function init() {
    if (window.archieOverlay) {
      window.archieOverlay.init({
        agentId: 27,
        agentName: "M.A.V.E.N.",
        accentColor: "#8b5cf6",
        moduleKey: "media_hub",
        greeting: "M.A.V.E.N. here. Ask me about your media library, downloads, or request new content.",
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
