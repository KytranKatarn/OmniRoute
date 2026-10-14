/* Progressive enhancement: all records and map links work without JavaScript. */
(() => {
  "use strict";
  const data = document.getElementById("atlas-map-data");
  if (!data) return;
  const maps = JSON.parse(data.textContent);
  const frame = document.getElementById("atlas-frame");
  const compare = document.getElementById("atlas-compare");
  const play = document.getElementById("atlas-play");
  const status = document.getElementById("atlas-status");
  let timer = null;
  let failed = false;
  const stop = () => {
    if (timer !== null) window.clearInterval(timer);
    timer = null;
    play.textContent = "Play snapshots";
    play.setAttribute("aria-pressed", "false");
  };
  const draw = () => {
    const index = Math.max(0, Math.min(maps.length - 1, Number(frame.value)));
    const item = maps[index];
    if (!/^nrcan-\d{4}\.svg$/.test(item.file)) return;
    const image = document.getElementById("atlas-current");
    image.src = "/static/history/" + item.file;
    image.alt = "Generalized political map snapshot for " + item.year;
    document.getElementById("atlas-year").value = item.year;
    frame.setAttribute("aria-valuetext", String(item.year));
    document.getElementById("atlas-current-label").textContent = item.year + " · source-derived political reference";
    const showing = compare.checked && index > 0;
    document.getElementById("atlas-previous-panel").hidden = !showing;
    document.getElementById("atlas-map-grid").classList.toggle("wtf-ha-comparing", showing);
    if (showing) {
      const previous = maps[index - 1];
      const previousImage = document.getElementById("atlas-previous");
      previousImage.src = "/static/history/" + previous.file;
      previousImage.alt = "Preceding political snapshot for " + previous.year;
      document.getElementById("atlas-previous-label").textContent = previous.year + " · preceding available snapshot";
    }
    status.textContent = item.year + " snapshot. Within-year legal commencement dates are unresolved.";
    if (compare.checked && index === 0) status.textContent += " No earlier snapshot is available.";
  };
  frame.addEventListener("input", () => { stop(); draw(); });
  compare.addEventListener("change", draw);
  play.addEventListener("click", () => {
    if (timer !== null) { stop(); return; }
    if (failed) return;
    if (Number(frame.value) === maps.length - 1) frame.value = "0";
    draw();
    play.textContent = "Pause snapshots";
    play.setAttribute("aria-pressed", "true");
    timer = window.setInterval(() => {
      if (Number(frame.value) >= maps.length - 1) { stop(); return; }
      frame.value = String(Number(frame.value) + 1);
      draw();
    }, 2000);
  });
  document.querySelectorAll(".wtf-ha-map-grid img").forEach(image => image.addEventListener("error", () => {
    failed = true;
    stop();
    play.disabled = true;
    status.textContent = "Map image unavailable. Event evidence remains readable; no missing geometry is inferred.";
  }));
  document.addEventListener("visibilitychange", () => { if (document.hidden) stop(); });
  document.getElementById("atlas-controls").hidden = false;
  draw();
})();
