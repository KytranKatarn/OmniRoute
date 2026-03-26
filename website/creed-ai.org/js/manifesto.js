/**
 * Manifesto — Scroll-pinned word-by-word text reveal using GSAP ScrollTrigger + Splitting.js
 */
const Manifesto = (() => {
  function init() {
    if (typeof Splitting === 'undefined' || typeof gsap === 'undefined') return;
    if (typeof ScrollTrigger === 'undefined') return;

    gsap.registerPlugin(ScrollTrigger);

    const sections = document.querySelectorAll('.manifesto-section');
    if (!sections.length) return;

    sections.forEach((section) => {
      // Split into word spans
      Splitting({ target: section.querySelectorAll('p, li'), by: 'words' });

      const words = section.querySelectorAll('.word');
      if (!words.length) return;

      gsap.fromTo(
        words,
        { opacity: 0.1 },
        {
          opacity: 1,
          stagger: 0.03,
          ease: 'none',
          scrollTrigger: {
            trigger: section,
            start: 'top 70%',
            end: 'bottom 30%',
            scrub: 1,
          },
        }
      );
    });
  }

  return { init };
})();

// Auto-init on DOMContentLoaded if on manifesto page
document.addEventListener('DOMContentLoaded', () => {
  if (document.querySelector('.manifesto-section')) {
    Manifesto.init();
  }
});
