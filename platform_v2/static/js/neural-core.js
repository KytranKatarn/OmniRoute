/* ═══════════════════════════════════════════════════════
   NeuralCore — Three.js WebGL Holographic Sphere
   Replaces CSS 3D HoloSphere with GPU-accelerated WebGL.

   Dependencies: Three.js (loaded dynamically from CDN)

   Usage:
     NeuralCore.create(containerEl, {
       nodes: [{ id, label, count, color, station }],
       mood: "focused",
       onNodeClick: function(node) {}
     }).then(function(core) {
       core.setMood("curious");
       core.updateNode(id, { count });
       core.addAgent({ name, station, color });
       core.fireEvent("job:completed", { agent });
       core.destroy();
     });
   ═══════════════════════════════════════════════════════ */

(function() {
"use strict";

/* ── Constants ──────────────────────────────────────── */

var THREE_CDN = "https://cdn.jsdelivr.net/npm/three@0.170.0/build/three.module.min.js";
var EXAMPLES  = "https://cdn.jsdelivr.net/npm/three@0.170.0/examples/jsm";
var CDN_TIMEOUT = 5000;

var MOOD_COLORS = {
  focused:    "#8b5cf6",
  curious:    "#06b6d4",
  happy:      "#22c55e",
  processing: "#f59e0b",
  empathetic: "#ec4899",
  neutral:    "#8b5cf6",
  confident:  "#3b82f6",
  relaxed:    "#22c55e"
};

var STATION_COLORS = {
  COMMAND:        "#8b5cf6",
  ANALYTICS:      "#06b6d4",
  CREATIVE:       "#ec4899",
  ENGINEERING:    "#f59e0b",
  COMMUNICATIONS: "#3b82f6",
  RESEARCH:       "#22c55e",
  SECURITY:       "#ef4444",
  LOGISTICS:      "#f97316",
  DIPLOMATIC:     "#a78bfa",
  OPERATIONS:     "#14b8a6"
};

var PHI_GOLDEN = Math.PI * (1 + Math.sqrt(5));
var TAU = Math.PI * 2;

/* ── Utilities ──────────────────────────────────────── */

function hexToVec3(hex) {
  var r = parseInt(hex.slice(1, 3), 16) / 255;
  var g = parseInt(hex.slice(3, 5), 16) / 255;
  var b = parseInt(hex.slice(5, 7), 16) / 255;
  return { r: r, g: g, b: b };
}

function fibonacciSphere(count, radius) {
  var points = [];
  for (var i = 0; i < count; i++) {
    var y = 1 - (i / (count - 1)) * 2;
    var r = Math.sqrt(1 - y * y);
    var theta = PHI_GOLDEN * i;
    points.push({
      x: Math.cos(theta) * r * radius,
      y: y * radius,
      z: Math.sin(theta) * r * radius
    });
  }
  return points;
}

function isMobile() {
  return window.innerWidth < 768;
}

function prefersReducedMotion() {
  return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function shortNum(n) {
  if (n >= 1000) return (n / 1000).toFixed(1) + "K";
  return String(n);
}

/* ── EventBus ───────────────────────────────────────── */

function EventBus() {
  this._listeners = {};
}

EventBus.prototype.on = function(type, fn) {
  if (!this._listeners[type]) this._listeners[type] = [];
  this._listeners[type].push(fn);
};

EventBus.prototype.off = function(type, fn) {
  if (!this._listeners[type]) return;
  this._listeners[type] = this._listeners[type].filter(function(f) { return f !== fn; });
};

EventBus.prototype.emit = function(type, data) {
  if (!this._listeners[type]) return;
  this._listeners[type].forEach(function(fn) { fn(data); });
};

/* ── CDN Loader ─────────────────────────────────────── */

function loadThreeJS() {
  return new Promise(function(resolve, reject) {
    var timer = setTimeout(function() {
      reject(new Error("Three.js CDN load timed out after " + CDN_TIMEOUT + "ms"));
    }, CDN_TIMEOUT);

    Promise.all([
      import(THREE_CDN),
      import(EXAMPLES + "/postprocessing/EffectComposer.js"),
      import(EXAMPLES + "/postprocessing/RenderPass.js"),
      import(EXAMPLES + "/postprocessing/UnrealBloomPass.js"),
      import(EXAMPLES + "/renderers/CSS2DRenderer.js")
    ]).then(function(modules) {
      clearTimeout(timer);
      resolve({
        THREE:            modules[0],
        EffectComposer:   modules[1].EffectComposer,
        RenderPass:       modules[2].RenderPass,
        UnrealBloomPass:  modules[3].UnrealBloomPass,
        CSS2DRenderer:    modules[4].CSS2DRenderer,
        CSS2DObject:      modules[4].CSS2DObject
      });
    }).catch(function(err) {
      clearTimeout(timer);
      reject(new Error("Failed to load Three.js from CDN: " + err.message));
    });
  });
}

/* ── GLSL Shaders ───────────────────────────────────── */

var SPHERE_VERTEX = [
  "uniform float uTime;",
  "uniform float uNoiseScale;",
  "varying vec3 vNormal;",
  "varying vec3 vViewPosition;",
  "varying float vNoise;",
  "",
  "// 3D hash noise",
  "float hash(vec3 p) {",
  "  p = fract(p * vec3(443.897, 441.423, 437.195));",
  "  p += dot(p, p.yzx + 19.19);",
  "  return fract((p.x + p.y) * p.z);",
  "}",
  "",
  "float noise3d(vec3 p) {",
  "  vec3 i = floor(p);",
  "  vec3 f = fract(p);",
  "  f = f * f * (3.0 - 2.0 * f);",
  "  return mix(",
  "    mix(mix(hash(i), hash(i + vec3(1,0,0)), f.x),",
  "        mix(hash(i + vec3(0,1,0)), hash(i + vec3(1,1,0)), f.x), f.y),",
  "    mix(mix(hash(i + vec3(0,0,1)), hash(i + vec3(1,0,1)), f.x),",
  "        mix(hash(i + vec3(0,1,1)), hash(i + vec3(1,1,1)), f.x), f.y),",
  "    f.z",
  "  );",
  "}",
  "",
  "void main() {",
  "  vNormal = normalize(normalMatrix * normal);",
  "  float n = noise3d(position * uNoiseScale + uTime * 0.15);",
  "  vNoise = n;",
  "  vec3 displaced = position + normal * n * 0.08;",
  "  vec4 mvPos = modelViewMatrix * vec4(displaced, 1.0);",
  "  vViewPosition = -mvPos.xyz;",
  "  gl_Position = projectionMatrix * mvPos;",
  "}"
].join("\n");

var SPHERE_FRAGMENT = [
  "uniform vec3 uColor;",
  "uniform float uOpacity;",
  "uniform float uFresnelPower;",
  "uniform float uTime;",
  "varying vec3 vNormal;",
  "varying vec3 vViewPosition;",
  "varying float vNoise;",
  "",
  "void main() {",
  "  vec3 viewDir = normalize(vViewPosition);",
  "  vec3 normal = normalize(vNormal);",
  "  float fresnel = pow(1.0 - abs(dot(viewDir, normal)), uFresnelPower);",
  "  float pulse = 1.0 + 0.08 * sin(uTime * 1.5);",
  "  float noiseVar = 0.85 + 0.15 * vNoise;",
  "  float alpha = fresnel * uOpacity * pulse * noiseVar;",
  "  gl_FragColor = vec4(uColor * (0.6 + fresnel * 0.4), alpha);",
  "}"
].join("\n");

var PARTICLE_VERTEX = [
  "attribute float aSize;",
  "attribute float aAlpha;",
  "attribute vec3 aColor;",
  "varying float vAlpha;",
  "varying vec3 vColor;",
  "",
  "void main() {",
  "  vAlpha = aAlpha;",
  "  vColor = aColor;",
  "  vec4 mvPos = modelViewMatrix * vec4(position, 1.0);",
  "  gl_PointSize = aSize * (300.0 / -mvPos.z);",
  "  gl_Position = projectionMatrix * mvPos;",
  "}"
].join("\n");

var PARTICLE_FRAGMENT = [
  "varying float vAlpha;",
  "varying vec3 vColor;",
  "",
  "void main() {",
  "  float d = length(gl_PointCoord - vec2(0.5));",
  "  if (d > 0.5) discard;",
  "  float falloff = smoothstep(0.5, 0.1, d);",
  "  gl_FragColor = vec4(vColor, vAlpha * falloff);",
  "}"
].join("\n");

var STREAM_VERTEX = [
  "attribute float aProgress;",
  "varying float vProgress;",
  "varying vec3 vSColor;",
  "",
  "void main() {",
  "  vProgress = aProgress;",
  "  vSColor = vec3(1.0);",
  "  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);",
  "}"
].join("\n");

var STREAM_FRAGMENT = [
  "uniform float uHead;",
  "uniform vec3 uStreamColor;",
  "varying float vProgress;",
  "",
  "void main() {",
  "  float dist = abs(vProgress - uHead);",
  "  float bright = smoothstep(0.15, 0.0, dist);",
  "  float trail = smoothstep(0.4, 0.05, dist) * 0.3;",
  "  float alpha = bright + trail;",
  "  gl_FragColor = vec4(uStreamColor, alpha);",
  "}"
].join("\n");

/* ── NeuralCore Constructor ─────────────────────────── */

function NeuralCore(container, libs, opts) {
  this._container = container;
  this._THREE = libs.THREE;
  this._libs = libs;
  this._opts = opts || {};

  this._clock = new this._THREE.Clock();
  this._scene = null;
  this._camera = null;
  this._renderer = null;
  this._composer = null;
  this._css2dRenderer = null;
  this._rafId = null;
  this._paused = false;
  this._frameCount = 0;

  // Sphere references
  this._sphere = null;
  this._wireframe = null;
  this._innerGlow = null;
  this._sphereMat = null;

  // Rings
  this._rings = [];

  // Nodes
  this._nodes = [];
  this._nodeMap = {};
  this._nodeGroup = new this._THREE.Group();
  this._raycaster = new this._THREE.Raycaster();
  this._mouse = new this._THREE.Vector2();

  // Particles
  this._particles = null;
  this._particleVelocities = [];
  this._particleCount = 0;
  this._dust = null;
  this._dustVelocities = [];

  // Agents
  this._agents = {};
  this._agentGroup = new this._THREE.Group();

  // Streams
  this._streams = [];
  this._streamGroup = new this._THREE.Group();

  // Node bursts
  this._bursts = [];

  // Mood
  this._currentMood = opts.mood || "focused";
  this._moodColor = hexToVec3(MOOD_COLORS[this._currentMood] || MOOD_COLORS.focused);

  // Event handlers (stored for cleanup)
  this._boundResize = null;
  this._boundVisibility = null;
  this._boundClick = null;

  // Init everything
  this._initScene();
  this._initBloom();
  this._initSphere();
  this._initRings();
  this._initNodes();
  this._initParticles();
  this._initCSS2D();
  this._bindEvents();
  this._animate();

  // Hide loading indicator
  var loading = container.querySelector(".nc-loading");
  if (loading) loading.style.display = "none";
}

/* ── Scene Setup ────────────────────────────────────── */

NeuralCore.prototype._initScene = function() {
  var T = this._THREE;
  var w = this._container.clientWidth;
  var h = this._container.clientHeight;

  this._camera = new T.PerspectiveCamera(50, w / h, 0.1, 100);
  this._camera.position.set(0, 0, 10);

  this._scene = new T.Scene();

  this._renderer = new T.WebGLRenderer({
    antialias: true,
    alpha: true,
    powerPreference: "high-performance"
  });
  this._renderer.setSize(w, h);
  this._renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  this._renderer.toneMapping = T.ACESFilmicToneMapping;
  this._renderer.toneMappingExposure = 1.2;
  this._container.appendChild(this._renderer.domElement);

  this._scene.add(new T.AmbientLight(0xffffff, 0.1));

  var self = this;
  this._boundResize = function() {
    var w = self._container.clientWidth;
    var h = self._container.clientHeight;
    self._camera.aspect = w / h;
    self._camera.updateProjectionMatrix();
    self._renderer.setSize(w, h);
    if (self._composer) self._composer.setSize(w, h);
    if (self._css2dRenderer) self._css2dRenderer.setSize(w, h);
  };
  window.addEventListener("resize", this._boundResize);

  this._boundVisibility = function() {
    self._paused = document.hidden;
  };
  document.addEventListener("visibilitychange", this._boundVisibility);
};

/* ── Bloom Post-Processing ──────────────────────────── */

NeuralCore.prototype._initBloom = function() {
  var w = this._container.clientWidth;
  var h = this._container.clientHeight;
  var T = this._THREE;

  var renderPass = new this._libs.RenderPass(this._scene, this._camera);

  var bloomStrength = 1.5;
  if (prefersReducedMotion()) bloomStrength = 0;
  else if (isMobile()) bloomStrength = 0.75;

  var bloomPass = new this._libs.UnrealBloomPass(
    new T.Vector2(w, h),
    bloomStrength,
    0.8,
    0.1
  );

  this._composer = new this._libs.EffectComposer(this._renderer);
  this._composer.addPass(renderPass);
  this._composer.addPass(bloomPass);
};

/* ── Main Sphere ────────────────────────────────────── */

NeuralCore.prototype._initSphere = function() {
  var T = this._THREE;
  var mc = this._moodColor;

  // Main sphere with custom shader
  var sphereGeo = new T.SphereGeometry(3, 64, 64);
  this._sphereMat = new T.ShaderMaterial({
    vertexShader: SPHERE_VERTEX,
    fragmentShader: SPHERE_FRAGMENT,
    uniforms: {
      uTime:         { value: 0 },
      uNoiseScale:   { value: 1.2 },
      uColor:        { value: new T.Vector3(mc.r, mc.g, mc.b) },
      uOpacity:      { value: 0.35 },
      uFresnelPower: { value: 2.5 }
    },
    transparent: true,
    depthWrite: false,
    side: T.FrontSide
  });
  this._sphere = new T.Mesh(sphereGeo, this._sphereMat);
  this._scene.add(this._sphere);

  // Wireframe overlay
  var wireGeo = new T.SphereGeometry(3.02, 32, 32);
  var wireMat = new T.MeshBasicMaterial({
    color: new T.Color(mc.r, mc.g, mc.b),
    wireframe: true,
    transparent: true,
    opacity: 0.06,
    depthWrite: false
  });
  this._wireframe = new T.Mesh(wireGeo, wireMat);
  this._scene.add(this._wireframe);

  // Inner glow (for bloom pickup)
  var glowGeo = new T.SphereGeometry(2.8, 32, 32);
  var glowMat = new T.MeshBasicMaterial({
    color: new T.Color(mc.r, mc.g, mc.b),
    transparent: true,
    opacity: 0.08,
    depthWrite: false
  });
  this._innerGlow = new T.Mesh(glowGeo, glowMat);
  this._scene.add(this._innerGlow);
};

/* ── Orbital Rings ──────────────────────────────────── */

NeuralCore.prototype._initRings = function() {
  var T = this._THREE;
  var mc = this._moodColor;
  var ringDefs = [
    { radius: 3.8, tube: 0.005, tiltX: 0.3,  tiltZ: 0.1,  speed: 0.08, opacity: 0.10 },
    { radius: 4.0, tube: 0.006, tiltX: -0.5, tiltZ: 0.3,  speed: -0.06, opacity: 0.08 },
    { radius: 4.2, tube: 0.007, tiltX: 0.7,  tiltZ: -0.2, speed: 0.10, opacity: 0.12 },
    { radius: 4.4, tube: 0.005, tiltX: -0.2, tiltZ: 0.6,  speed: -0.04, opacity: 0.05 },
    { radius: 4.6, tube: 0.008, tiltX: 0.4,  tiltZ: -0.5, speed: 0.07, opacity: 0.09 }
  ];

  for (var i = 0; i < ringDefs.length; i++) {
    var d = ringDefs[i];
    var geo = new T.TorusGeometry(d.radius, d.tube, 16, 100);
    var mat = new T.MeshBasicMaterial({
      color: new T.Color(mc.r, mc.g, mc.b),
      transparent: true,
      opacity: d.opacity,
      depthWrite: false
    });
    var mesh = new T.Mesh(geo, mat);
    mesh.rotation.x = d.tiltX;
    mesh.rotation.z = d.tiltZ;
    mesh.userData.speed = d.speed;
    this._rings.push(mesh);
    this._scene.add(mesh);
  }
};

/* ── Knowledge Nodes ────────────────────────────────── */

NeuralCore.prototype._initNodes = function() {
  var T = this._THREE;
  var nodes = this._opts.nodes || [];
  var positions = fibonacciSphere(Math.max(nodes.length, 1), 3.5);

  this._scene.add(this._nodeGroup);

  for (var i = 0; i < nodes.length; i++) {
    var n = nodes[i];
    var pos = positions[i];
    var col = new T.Color(n.color || STATION_COLORS.COMMAND);
    var size = 0.15 + Math.min((n.count || 0) / 5000, 0.1);

    var geo = new T.SphereGeometry(size, 16, 16);
    var mat = new T.MeshBasicMaterial({
      color: col,
      transparent: true,
      opacity: 0.85
    });
    var mesh = new T.Mesh(geo, mat);
    mesh.position.set(pos.x, pos.y, pos.z);
    mesh.userData.nodeId = n.id;
    mesh.userData.nodeData = n;
    mesh.userData.baseScale = 1;
    this._nodeGroup.add(mesh);

    // Thread to center
    var centerLine = this._createLine(
      [new T.Vector3(pos.x, pos.y, pos.z), new T.Vector3(0, 0, 0)],
      col, 0.06
    );
    this._nodeGroup.add(centerLine);

    // Thread to next adjacent node
    if (i > 0) {
      var prev = positions[i - 1];
      var adjLine = this._createLine(
        [new T.Vector3(pos.x, pos.y, pos.z), new T.Vector3(prev.x, prev.y, prev.z)],
        col, 0.06
      );
      this._nodeGroup.add(adjLine);
    }

    var entry = { mesh: mesh, data: n, label: null };
    this._nodes.push(entry);
    this._nodeMap[n.id] = entry;
  }
};

NeuralCore.prototype._createLine = function(points, color, opacity) {
  var T = this._THREE;
  var geo = new T.BufferGeometry().setFromPoints(points);
  var mat = new T.LineBasicMaterial({
    color: color,
    transparent: true,
    opacity: opacity,
    depthWrite: false
  });
  return new T.Line(geo, mat);
};

/* ── Inner Particles ────────────────────────────────── */

NeuralCore.prototype._initParticles = function() {
  var T = this._THREE;
  var reduced = prefersReducedMotion();
  var mobile = isMobile();

  // Inner particles
  this._particleCount = reduced ? 0 : (mobile ? 80 : 200);
  if (this._particleCount > 0) {
    var positions = new Float32Array(this._particleCount * 3);
    var sizes = new Float32Array(this._particleCount);
    var alphas = new Float32Array(this._particleCount);
    var colors = new Float32Array(this._particleCount * 3);
    this._particleVelocities = [];
    var mc = this._moodColor;

    for (var i = 0; i < this._particleCount; i++) {
      // Cube root distribution for uniform volume
      var r = Math.cbrt(Math.random()) * 2.8;
      var theta = Math.random() * TAU;
      var phi = Math.acos(2 * Math.random() - 1);
      positions[i * 3]     = r * Math.sin(phi) * Math.cos(theta);
      positions[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
      positions[i * 3 + 2] = r * Math.cos(phi);
      sizes[i] = 1.5 + Math.random() * 2.5;
      alphas[i] = 0.2 + Math.random() * 0.5;
      colors[i * 3]     = mc.r;
      colors[i * 3 + 1] = mc.g;
      colors[i * 3 + 2] = mc.b;
      this._particleVelocities.push({
        x: (Math.random() - 0.5) * 0.002,
        y: (Math.random() - 0.5) * 0.002,
        z: (Math.random() - 0.5) * 0.002
      });
    }

    var geo = new T.BufferGeometry();
    geo.setAttribute("position", new T.BufferAttribute(positions, 3));
    geo.setAttribute("aSize", new T.BufferAttribute(sizes, 1));
    geo.setAttribute("aAlpha", new T.BufferAttribute(alphas, 1));
    geo.setAttribute("aColor", new T.BufferAttribute(colors, 3));

    var mat = new T.ShaderMaterial({
      vertexShader: PARTICLE_VERTEX,
      fragmentShader: PARTICLE_FRAGMENT,
      transparent: true,
      depthWrite: false,
      blending: T.AdditiveBlending
    });

    this._particles = new T.Points(geo, mat);
    this._scene.add(this._particles);
  }

  // Ambient dust outside sphere
  var dustCount = (mobile || reduced) ? 0 : 50;
  if (dustCount > 0) {
    var dPos = new Float32Array(dustCount * 3);
    var dSizes = new Float32Array(dustCount);
    var dAlphas = new Float32Array(dustCount);
    var dColors = new Float32Array(dustCount * 3);
    this._dustVelocities = [];

    for (var j = 0; j < dustCount; j++) {
      var dr = 4.0 + Math.random() * 4.0;
      var dtheta = Math.random() * TAU;
      var dphi = Math.acos(2 * Math.random() - 1);
      dPos[j * 3]     = dr * Math.sin(dphi) * Math.cos(dtheta);
      dPos[j * 3 + 1] = dr * Math.sin(dphi) * Math.sin(dtheta);
      dPos[j * 3 + 2] = dr * Math.cos(dphi);
      dSizes[j] = 0.8 + Math.random() * 1.2;
      dAlphas[j] = 0.08 + Math.random() * 0.15;
      dColors[j * 3]     = 1.0;
      dColors[j * 3 + 1] = 1.0;
      dColors[j * 3 + 2] = 1.0;
      this._dustVelocities.push({
        x: (Math.random() - 0.5) * 0.0005,
        y: 0.001 + Math.random() * 0.001,
        z: (Math.random() - 0.5) * 0.0005
      });
    }

    var dGeo = new T.BufferGeometry();
    dGeo.setAttribute("position", new T.BufferAttribute(dPos, 3));
    dGeo.setAttribute("aSize", new T.BufferAttribute(dSizes, 1));
    dGeo.setAttribute("aAlpha", new T.BufferAttribute(dAlphas, 1));
    dGeo.setAttribute("aColor", new T.BufferAttribute(dColors, 3));

    var dMat = new T.ShaderMaterial({
      vertexShader: PARTICLE_VERTEX,
      fragmentShader: PARTICLE_FRAGMENT,
      transparent: true,
      depthWrite: false,
      blending: T.AdditiveBlending
    });

    this._dust = new T.Points(dGeo, dMat);
    this._scene.add(this._dust);
  }
};

/* ── CSS2D Labels ───────────────────────────────────── */

NeuralCore.prototype._initCSS2D = function() {
  var w = this._container.clientWidth;
  var h = this._container.clientHeight;

  this._css2dRenderer = new this._libs.CSS2DRenderer();
  this._css2dRenderer.setSize(w, h);
  this._css2dRenderer.domElement.style.position = "absolute";
  this._css2dRenderer.domElement.style.top = "0";
  this._css2dRenderer.domElement.style.left = "0";
  this._css2dRenderer.domElement.style.pointerEvents = "none";
  this._container.appendChild(this._css2dRenderer.domElement);

  // Create labels for each node
  for (var i = 0; i < this._nodes.length; i++) {
    var entry = this._nodes[i];
    var div = document.createElement("div");
    div.className = "nc-node-label";
    div.textContent = shortNum(entry.data.count || 0) + " " + (entry.data.label || "");
    div.style.fontSize = "10px";
    div.style.opacity = "0.7";
    div.style.whiteSpace = "nowrap";

    var label = new this._libs.CSS2DObject(div);
    label.position.copy(entry.mesh.position);
    label.position.y += 0.3;
    this._scene.add(label);
    entry.label = label;
    entry.labelDiv = div;
  }
};

/* ── Event Binding ──────────────────────────────────── */

NeuralCore.prototype._bindEvents = function() {
  var self = this;
  var T = this._THREE;

  this._boundClick = function(e) {
    var rect = self._renderer.domElement.getBoundingClientRect();
    self._mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    self._mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;

    self._raycaster.setFromCamera(self._mouse, self._camera);
    var meshes = self._nodes.map(function(n) { return n.mesh; });
    var hits = self._raycaster.intersectObjects(meshes);

    if (hits.length > 0 && self._opts.onNodeClick) {
      var hit = hits[0].object;
      self._opts.onNodeClick(hit.userData.nodeData);
    }
  };

  this._renderer.domElement.addEventListener("click", this._boundClick);
};

/* ── Agent Orbs ─────────────────────────────────────── */

NeuralCore.prototype.addAgent = function(agent) {
  var T = this._THREE;
  var name = agent.name;
  if (this._agents[name]) return;

  var color = new T.Color(agent.color || STATION_COLORS[agent.station] || STATION_COLORS.COMMAND);
  var group = new T.Group();

  // Agent sphere
  var geo = new T.SphereGeometry(0.18, 16, 16);
  var mat = new T.MeshBasicMaterial({
    color: color,
    transparent: true,
    opacity: 0.9
  });
  var mesh = new T.Mesh(geo, mat);
  group.add(mesh);

  // Halo ring
  var haloGeo = new T.TorusGeometry(0.28, 0.01, 8, 32);
  var haloMat = new T.MeshBasicMaterial({
    color: color,
    transparent: true,
    opacity: 0.3
  });
  var halo = new T.Mesh(haloGeo, haloMat);
  halo.rotation.x = Math.PI / 2;
  group.add(halo);

  // CSS2D label with initials
  var initials = name.split(/\s+/).map(function(w) { return w[0]; }).join("").slice(0, 2).toUpperCase();
  var div = document.createElement("div");
  div.className = "nc-agent-label";
  div.textContent = initials;
  div.style.fontSize = "9px";
  div.style.opacity = "0.8";
  var label = new this._libs.CSS2DObject(div);
  label.position.y = 0.35;
  group.add(label);

  // Orbit parameters
  var agentCount = Object.keys(this._agents).length;
  var tiltOffset = agentCount * 0.7;
  group.userData = {
    name: name,
    agent: agent,
    orbitRadius: 4.8,
    orbitSpeed: 0.15 + Math.random() * 0.1,
    orbitTilt: 0.3 + tiltOffset,
    angle: Math.random() * TAU,
    working: false,
    targetNode: null,
    stream: null,
    mesh: mesh,
    halo: halo,
    haloMat: haloMat
  };

  this._scene.add(group);
  this._agents[name] = group;
};

NeuralCore.prototype.removeAgent = function(name) {
  var group = this._agents[name];
  if (!group) return;

  // Dispose stream if active
  if (group.userData.stream) {
    this._removeStream(group.userData.stream);
  }

  this._scene.remove(group);
  group.traverse(function(child) {
    if (child.geometry) child.geometry.dispose();
    if (child.material) child.material.dispose();
  });
  delete this._agents[name];
};

NeuralCore.prototype.setAgentWorking = function(name, working, targetNodeId) {
  var group = this._agents[name];
  if (!group) return;

  var ud = group.userData;
  ud.working = working;

  if (working) {
    ud.mesh.material.opacity = 1.0;
    ud.haloMat.opacity = 0.6;

    // Create stream to target node
    if (targetNodeId && this._nodeMap[targetNodeId]) {
      var nodeEntry = this._nodeMap[targetNodeId];
      ud.targetNode = nodeEntry;
      var stationCode = (ud.agent && ud.agent.station) || "COMMAND";
      var stream = this._addStream(group.position, nodeEntry.mesh.position, stationCode);
      ud.stream = stream;
    }
  } else {
    ud.mesh.material.opacity = 0.9;
    ud.haloMat.opacity = 0.3;
    if (ud.stream) {
      this._removeStream(ud.stream);
      ud.stream = null;
    }
    ud.targetNode = null;
  }
};

/* ── Neural Activity Streams ────────────────────────── */

NeuralCore.prototype._addStream = function(fromPos, toPos, stationCode) {
  var T = this._THREE;
  var color = new T.Color(STATION_COLORS[stationCode] || STATION_COLORS.COMMAND);

  var segCount = 32;
  var positions = new Float32Array(segCount * 3);
  var progress = new Float32Array(segCount);

  for (var i = 0; i < segCount; i++) {
    var t = i / (segCount - 1);
    positions[i * 3]     = fromPos.x + (toPos.x - fromPos.x) * t;
    positions[i * 3 + 1] = fromPos.y + (toPos.y - fromPos.y) * t;
    positions[i * 3 + 2] = fromPos.z + (toPos.z - fromPos.z) * t;
    progress[i] = t;
  }

  var geo = new T.BufferGeometry();
  geo.setAttribute("position", new T.BufferAttribute(positions, 3));
  geo.setAttribute("aProgress", new T.BufferAttribute(progress, 1));

  var mat = new T.ShaderMaterial({
    vertexShader: STREAM_VERTEX,
    fragmentShader: STREAM_FRAGMENT,
    uniforms: {
      uHead:        { value: 0 },
      uStreamColor: { value: new T.Vector3(color.r, color.g, color.b) }
    },
    transparent: true,
    depthWrite: false,
    blending: T.AdditiveBlending
  });

  var line = new T.Line(geo, mat);
  var stream = {
    line: line,
    material: mat,
    life: 1.0,
    fromPos: fromPos.clone ? fromPos.clone() : new T.Vector3(fromPos.x, fromPos.y, fromPos.z),
    toPos: toPos.clone ? toPos.clone() : new T.Vector3(toPos.x, toPos.y, toPos.z)
  };

  this._streamGroup.add(line);
  if (!this._streamGroup.parent) this._scene.add(this._streamGroup);
  this._streams.push(stream);
  return stream;
};

NeuralCore.prototype._removeStream = function(stream) {
  this._streamGroup.remove(stream.line);
  stream.line.geometry.dispose();
  stream.material.dispose();
  var idx = this._streams.indexOf(stream);
  if (idx !== -1) this._streams.splice(idx, 1);
};

/* ── Event Effects ──────────────────────────────────── */

NeuralCore.prototype.fireEvent = function(type, data) {
  data = data || {};

  switch (type) {
    case "job:completed":
      this._pulseFlash("success");
      if (data.agent && this._agents[data.agent]) {
        var ag = this._agents[data.agent];
        ag.userData.mesh.material.opacity = 1.0;
        setTimeout(function() { ag.userData.mesh.material.opacity = 0.9; }, 500);
      }
      break;

    case "job:started":
      if (data.agent) {
        this.setAgentWorking(data.agent, true, data.targetNode);
      }
      break;

    case "job:failed":
      this._pulseFlash("error");
      break;

    case "knowledge:added":
      if (data.nodeId && this._nodeMap[data.nodeId]) {
        var entry = this._nodeMap[data.nodeId];
        this._burstNode(entry);
        this._addStream(entry.mesh.position, new this._THREE.Vector3(0, 0, 0), data.station || "COMMAND");
      }
      break;

    case "agent:dispatched":
      if (data.agent) {
        this.addAgent(data.agent);
      }
      break;
  }

  // Relay to EventBus
  if (window._neuralEvents) {
    window._neuralEvents.emit(type, data);
  }
};

/* ── Mood ───────────────────────────────────────────── */

NeuralCore.prototype.setMood = function(mood) {
  var hex = MOOD_COLORS[mood] || MOOD_COLORS.focused;
  this._currentMood = mood;
  this._moodColor = hexToVec3(hex);
  var mc = this._moodColor;
  var T = this._THREE;

  // Update sphere shader
  if (this._sphereMat) {
    this._sphereMat.uniforms.uColor.value.set(mc.r, mc.g, mc.b);
  }

  // Update wireframe
  if (this._wireframe) {
    this._wireframe.material.color.setRGB(mc.r, mc.g, mc.b);
  }

  // Update inner glow
  if (this._innerGlow) {
    this._innerGlow.material.color.setRGB(mc.r, mc.g, mc.b);
  }

  // Update rings
  for (var i = 0; i < this._rings.length; i++) {
    this._rings[i].material.color.setRGB(mc.r, mc.g, mc.b);
  }
};

/* ── Node Updates ───────────────────────────────────── */

NeuralCore.prototype.updateNode = function(id, data) {
  var entry = this._nodeMap[id];
  if (!entry) return;

  if (data.count !== undefined) {
    entry.data.count = data.count;
    if (entry.labelDiv) {
      entry.labelDiv.textContent = shortNum(data.count) + " " + (entry.data.label || "");
    }
    // Scale based on count
    var s = 1 + Math.min(data.count / 5000, 0.6);
    entry.mesh.scale.setScalar(s);
    entry.mesh.userData.baseScale = s;
  }
};

/* ── Visual Effects ─────────────────────────────────── */

NeuralCore.prototype._pulseFlash = function(type) {
  var cls = "nc-flash-" + type;
  this._container.classList.add(cls);
  var c = this._container;
  setTimeout(function() { c.classList.remove(cls); }, 600);
};

NeuralCore.prototype._burstNode = function(entry) {
  entry.mesh.scale.setScalar((entry.mesh.userData.baseScale || 1) * 1.8);
  this._bursts.push({ entry: entry, time: performance.now() });
};

/* ── Animation Loop ─────────────────────────────────── */

NeuralCore.prototype._animate = function() {
  var self = this;

  function loop() {
    self._rafId = requestAnimationFrame(loop);
    if (self._paused) return;

    var delta = self._clock.getDelta();
    var elapsed = self._clock.getElapsedTime();
    self._frameCount++;

    // Camera slow orbit
    self._camera.position.x = 10 * Math.sin(elapsed * 0.05);
    self._camera.position.z = 10 * Math.cos(elapsed * 0.05);
    self._camera.position.y = 1.5 * Math.sin(elapsed * 0.03);
    self._camera.lookAt(0, 0, 0);

    // Sphere shader time
    if (self._sphereMat) {
      self._sphereMat.uniforms.uTime.value = elapsed;
    }

    // Ring rotation
    for (var ri = 0; ri < self._rings.length; ri++) {
      self._rings[ri].rotation.y += self._rings[ri].userData.speed * delta;
    }

    // Node burst recovery
    var now = performance.now();
    for (var bi = self._bursts.length - 1; bi >= 0; bi--) {
      var b = self._bursts[bi];
      if (now - b.time > 500) {
        var base = b.entry.mesh.userData.baseScale || 1;
        b.entry.mesh.scale.setScalar(base);
        self._bursts.splice(bi, 1);
      }
    }

    // Particle update (Brownian drift + containment)
    if (self._particles && self._particleCount > 0) {
      var pAttr = self._particles.geometry.getAttribute("position");
      for (var pi = 0; pi < self._particleCount; pi++) {
        var vel = self._particleVelocities[pi];
        var px = pAttr.getX(pi) + vel.x;
        var py = pAttr.getY(pi) + vel.y;
        var pz = pAttr.getZ(pi) + vel.z;

        // Sphere containment
        var dist = Math.sqrt(px * px + py * py + pz * pz);
        if (dist > 2.8) {
          var scale = 2.7 / dist;
          px *= scale;
          py *= scale;
          pz *= scale;
          vel.x *= -0.5;
          vel.y *= -0.5;
          vel.z *= -0.5;
        }

        // Brownian perturbation
        vel.x += (Math.random() - 0.5) * 0.0004;
        vel.y += (Math.random() - 0.5) * 0.0004;
        vel.z += (Math.random() - 0.5) * 0.0004;

        pAttr.setXYZ(pi, px, py, pz);
      }
      pAttr.needsUpdate = true;
    }

    // Dust update (slow drift + wrap-around)
    if (self._dust) {
      var dAttr = self._dust.geometry.getAttribute("position");
      var dustLen = self._dustVelocities.length;
      for (var di = 0; di < dustLen; di++) {
        var dv = self._dustVelocities[di];
        var dx = dAttr.getX(di) + dv.x;
        var dy = dAttr.getY(di) + dv.y;
        var dz = dAttr.getZ(di) + dv.z;

        // Wrap around if too far
        var dd = Math.sqrt(dx * dx + dy * dy + dz * dz);
        if (dd > 8.0) {
          var angle = Math.random() * TAU;
          var phi = Math.acos(2 * Math.random() - 1);
          var r = 4.0 + Math.random() * 1.0;
          dx = r * Math.sin(phi) * Math.cos(angle);
          dy = r * Math.sin(phi) * Math.sin(angle);
          dz = r * Math.cos(phi);
        }

        dAttr.setXYZ(di, dx, dy, dz);
      }
      dAttr.needsUpdate = true;
    }

    // Agent orbit update
    var agentNames = Object.keys(self._agents);
    for (var ai = 0; ai < agentNames.length; ai++) {
      var agGroup = self._agents[agentNames[ai]];
      var ud = agGroup.userData;
      ud.angle += ud.orbitSpeed * delta;

      var orbitR = ud.orbitRadius;
      agGroup.position.x = orbitR * Math.cos(ud.angle) * Math.cos(ud.orbitTilt);
      agGroup.position.y = orbitR * Math.sin(ud.orbitTilt) * Math.sin(ud.angle * 0.7);
      agGroup.position.z = orbitR * Math.sin(ud.angle);

      // Pulsing halo when working
      if (ud.working) {
        ud.haloMat.opacity = 0.4 + 0.3 * Math.sin(elapsed * 4);
      }

      // Update stream positions if active
      if (ud.stream && ud.stream.line) {
        var sGeo = ud.stream.line.geometry;
        var sPos = sGeo.getAttribute("position");
        var segCount = sPos.count;
        var from = agGroup.position;
        var to = ud.targetNode ? ud.targetNode.mesh.position : new self._THREE.Vector3(0, 0, 0);
        for (var si = 0; si < segCount; si++) {
          var t = si / (segCount - 1);
          sPos.setXYZ(si,
            from.x + (to.x - from.x) * t,
            from.y + (to.y - from.y) * t,
            from.z + (to.z - from.z) * t
          );
        }
        sPos.needsUpdate = true;
      }
    }

    // Stream update: advance head, decay life, remove dead
    for (var sti = self._streams.length - 1; sti >= 0; sti--) {
      var stream = self._streams[sti];
      var headVal = stream.material.uniforms.uHead.value;
      headVal += delta * 0.8;
      if (headVal > 1.0) headVal -= 1.0;
      stream.material.uniforms.uHead.value = headVal;
      stream.life -= 0.003;

      if (stream.life <= 0) {
        // Check if any agent owns this stream — don't remove those
        var owned = false;
        for (var ak in self._agents) {
          if (self._agents[ak].userData.stream === stream) { owned = true; break; }
        }
        if (!owned) {
          self._removeStream(stream);
        } else {
          stream.life = 1.0; // Reset life for owned streams
        }
      }
    }

    // Render
    if (self._composer) self._composer.render();
    if (self._css2dRenderer) self._css2dRenderer.render(self._scene, self._camera);

    // Adaptive quality: check every 120 frames
    if (self._frameCount % 120 === 0 && delta > 0.025 && self._particleCount > 100) {
      self._particleCount = 100;
    }
  }

  loop();
};

/* ── Destroy ────────────────────────────────────────── */

NeuralCore.prototype.destroy = function() {
  // Cancel animation
  if (this._rafId) {
    cancelAnimationFrame(this._rafId);
    this._rafId = null;
  }

  // Remove event listeners
  if (this._boundResize) window.removeEventListener("resize", this._boundResize);
  if (this._boundVisibility) document.removeEventListener("visibilitychange", this._boundVisibility);
  if (this._boundClick && this._renderer) {
    this._renderer.domElement.removeEventListener("click", this._boundClick);
  }

  // Traverse and dispose all geometries/materials
  if (this._scene) {
    this._scene.traverse(function(obj) {
      if (obj.geometry) obj.geometry.dispose();
      if (obj.material) {
        if (Array.isArray(obj.material)) {
          obj.material.forEach(function(m) { m.dispose(); });
        } else {
          obj.material.dispose();
        }
      }
    });
  }

  // Dispose renderer and composer
  if (this._renderer) {
    this._renderer.dispose();
    if (this._renderer.domElement && this._renderer.domElement.parentNode) {
      this._renderer.domElement.parentNode.removeChild(this._renderer.domElement);
    }
  }

  if (this._composer) {
    this._composer.dispose();
  }

  // Remove CSS2D renderer DOM
  if (this._css2dRenderer && this._css2dRenderer.domElement && this._css2dRenderer.domElement.parentNode) {
    this._css2dRenderer.domElement.parentNode.removeChild(this._css2dRenderer.domElement);
  }

  this._scene = null;
  this._camera = null;
  this._renderer = null;
  this._composer = null;
  this._css2dRenderer = null;
  this._nodes = [];
  this._nodeMap = {};
  this._agents = {};
  this._streams = [];
  this._bursts = [];
};

/* ── Static Factory ─────────────────────────────────── */

NeuralCore.create = function(container, opts) {
  return new Promise(function(resolve, reject) {
    // Check WebGL support
    var canvas = document.createElement("canvas");
    var gl = canvas.getContext("webgl2") || canvas.getContext("webgl");
    if (!gl) {
      reject(new Error("WebGL is not supported in this browser"));
      return;
    }
    canvas = null;

    // Load Three.js from CDN
    loadThreeJS().then(function(libs) {
      try {
        var core = new NeuralCore(container, libs, opts || {});
        resolve(core);
      } catch (err) {
        reject(new Error("NeuralCore initialization failed: " + err.message));
      }
    }).catch(function(err) {
      reject(err);
    });
  });
};

/* ── Global Exposure ────────────────────────────────── */

window.NeuralCore = NeuralCore;
window._neuralEvents = new EventBus();

})();
