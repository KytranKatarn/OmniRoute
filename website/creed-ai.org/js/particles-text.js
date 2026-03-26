/**
 * ParticleText — Canvas particle system that forms "C.R.E.E.D." text
 * Particles spring toward text positions; mouse repulsion on hover.
 */
const ParticleText = (() => {
  let canvas, ctx, particles = [], mouse = { x: -9999, y: -9999 }, animId;

  function sampleTextPixels(text, canvasWidth, canvasHeight) {
    const offscreen = document.createElement('canvas');
    const fontSize = Math.min(canvasWidth / 6, 120);
    offscreen.width = canvasWidth;
    offscreen.height = Math.max(fontSize * 2, 200);
    const octx = offscreen.getContext('2d');
    octx.fillStyle = '#ffffff';
    octx.font = `900 ${fontSize}px Orbitron, monospace`;
    octx.textAlign = 'center';
    octx.textBaseline = 'middle';
    octx.fillText(text, canvasWidth / 2, offscreen.height / 2);
    const imageData = octx.getImageData(0, 0, offscreen.width, offscreen.height);
    const pixels = [];
    const gap = 4;
    for (let y = 0; y < offscreen.height; y += gap) {
      for (let x = 0; x < offscreen.width; x += gap) {
        const idx = (y * offscreen.width + x) * 4;
        if (imageData.data[idx + 3] > 128) {
          // Center vertically on main canvas
          const offsetY = (canvasHeight - offscreen.height) / 2;
          pixels.push({ x, y: y + offsetY });
        }
      }
    }
    return pixels;
  }

  function createParticle(target) {
    const isGold = Math.random() < 0.7;
    return {
      x: Math.random() * canvas.width,
      y: Math.random() * canvas.height,
      vx: 0,
      vy: 0,
      tx: target.x,
      ty: target.y,
      color: isGold ? '#c9a44c' : '#00e5ff',
      size: 1 + Math.random() * 2
    };
  }

  function animate() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    for (const p of particles) {
      // Spring toward target
      const dx = p.tx - p.x;
      const dy = p.ty - p.y;
      p.vx += dx * 0.05;
      p.vy += dy * 0.05;
      p.vx *= 0.85;
      p.vy *= 0.85;

      // Mouse repulsion
      const mdx = p.x - mouse.x;
      const mdy = p.y - mouse.y;
      const dist = Math.sqrt(mdx * mdx + mdy * mdy);
      if (dist < 100 && dist > 0) {
        const force = (100 - dist) / 100;
        p.vx += (mdx / dist) * force * 6;
        p.vy += (mdy / dist) * force * 6;
      }

      p.x += p.vx;
      p.y += p.vy;

      ctx.fillStyle = p.color;
      ctx.fillRect(p.x, p.y, p.size, p.size);
    }
    animId = requestAnimationFrame(animate);
  }

  function buildParticles() {
    if (animId) cancelAnimationFrame(animId);
    particles = [];
    const targets = sampleTextPixels('C.R.E.E.D.', canvas.width, canvas.height);
    for (const t of targets) {
      particles.push(createParticle(t));
    }
    animate();
  }

  function onResize() {
    canvas.width = canvas.offsetWidth;
    canvas.height = canvas.offsetHeight;
    buildParticles();
  }

  function init() {
    // Skip on mobile or reduced motion
    if (window.matchMedia('(max-width: 768px)').matches) return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

    canvas = document.getElementById('particleCanvas');
    if (!canvas) return;
    ctx = canvas.getContext('2d');

    canvas.width = canvas.offsetWidth;
    canvas.height = canvas.offsetHeight;

    canvas.addEventListener('mousemove', (e) => {
      const rect = canvas.getBoundingClientRect();
      mouse.x = e.clientX - rect.left;
      mouse.y = e.clientY - rect.top;
    });
    canvas.addEventListener('mouseleave', () => {
      mouse.x = -9999;
      mouse.y = -9999;
    });

    window.addEventListener('resize', onResize);
    buildParticles();
  }

  return { init };
})();
