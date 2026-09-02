/* Group headers open their menu on click instead of navigating away, so a
   tap on "News" reveals Latest / Blindspot / Divergence rather than jumping
   straight to a landing page. Hover still works; keyboard still works. */
(function () {
  function closeAll(except) {
    document.querySelectorAll('.navgrp.open').forEach(g => { if (g !== except) g.classList.remove('open'); });
  }
  document.addEventListener('click', e => {
    const grp = e.target.closest('.navgrp > .grp, .navgrp > span');
    if (grp) {
      const box = grp.parentElement;
      if (box.querySelector('.navgrp-menu')) {
        e.preventDefault();
        const wasOpen = box.classList.contains('open');
        closeAll(box);
        box.classList.toggle('open', !wasOpen);
        return;
      }
    }
    if (!e.target.closest('.navgrp-menu')) closeAll(null);
  });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeAll(null); });
  // Leaving the group with the pointer also dismisses it.
  document.querySelectorAll('.navgrp').forEach(g =>
    g.addEventListener('mouseleave', () => g.classList.remove('open')));
})();
