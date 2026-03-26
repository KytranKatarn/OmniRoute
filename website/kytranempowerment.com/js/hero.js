/* ==========================================================================
   Kytran Empowerment — Hero Three.js Particle Scene
   ========================================================================== */

const Hero = {
    scene: null,
    camera: null,
    renderer: null,
    particles: null,
    mouse: { x: 0, y: 0 },
    target: { x: 0, y: 0 },
    animFrameId: null,

    init() {
        // Skip on mobile or reduced-motion
        if (window.matchMedia('(max-width: 768px)').matches) return;
        if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
        if (typeof THREE === 'undefined') return;

        const canvas = document.getElementById('heroCanvas');
        if (!canvas) return;

        // Scene
        this.scene = new THREE.Scene();

        // Camera
        this.camera = new THREE.PerspectiveCamera(
            75,
            window.innerWidth / window.innerHeight,
            0.1,
            100
        );
        this.camera.position.z = 5;

        // Renderer
        this.renderer = new THREE.WebGLRenderer({
            canvas,
            alpha: true,
            antialias: true,
        });
        this.renderer.setSize(window.innerWidth, window.innerHeight);
        this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

        // Particles
        const count = 800;
        const positions = new Float32Array(count * 3);
        const colors = new Float32Array(count * 3);

        const teal   = new THREE.Color('#00e5ff');
        const purple = new THREE.Color('#8b5cf6');

        for (let i = 0; i < count; i++) {
            const i3 = i * 3;
            // Random positions in a 20x20x20 cube
            positions[i3]     = (Math.random() - 0.5) * 20;
            positions[i3 + 1] = (Math.random() - 0.5) * 20;
            positions[i3 + 2] = (Math.random() - 0.5) * 20;

            // Random color: teal or purple
            const color = Math.random() > 0.5 ? teal : purple;
            colors[i3]     = color.r;
            colors[i3 + 1] = color.g;
            colors[i3 + 2] = color.b;
        }

        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
        geometry.setAttribute('color',    new THREE.BufferAttribute(colors, 3));

        const material = new THREE.PointsMaterial({
            size: 0.05,
            vertexColors: true,
            transparent: true,
            opacity: 0.8,
            sizeAttenuation: true,
        });

        this.particles = new THREE.Points(geometry, material);
        this.scene.add(this.particles);

        // Mouse tracking
        window.addEventListener('mousemove', (e) => {
            this.mouse.x = (e.clientX / window.innerWidth  - 0.5) * 2;
            this.mouse.y = (e.clientY / window.innerHeight - 0.5) * 2;
        });

        // Resize handler
        window.addEventListener('resize', () => this._onResize());

        // Start loop
        this._animate();
    },

    _animate() {
        this.animFrameId = requestAnimationFrame(() => this._animate());

        // Slow rotation
        if (this.particles) {
            this.particles.rotation.y += 0.001;
            this.particles.rotation.x += 0.0005;
        }

        // Lerp camera toward mouse
        this.target.x += (this.mouse.x * 0.3 - this.target.x) * 0.05;
        this.target.y += (-this.mouse.y * 0.3 - this.target.y) * 0.05;
        this.camera.position.x = this.target.x;
        this.camera.position.y = this.target.y;
        this.camera.lookAt(this.scene.position);

        this.renderer.render(this.scene, this.camera);
    },

    _onResize() {
        this.camera.aspect = window.innerWidth / window.innerHeight;
        this.camera.updateProjectionMatrix();
        this.renderer.setSize(window.innerWidth, window.innerHeight);
        this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    },
};

document.addEventListener('DOMContentLoaded', () => Hero.init());
