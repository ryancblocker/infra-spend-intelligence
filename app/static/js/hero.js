// Welcome-page hero: a Three.js graph of PACT's actual 8-agent pipeline
// (Discovery -> four parallel workers -> Optimization -> Critic ->
// Narrator), with pulses traveling the edges and a light pointer-driven
// parallax. This is the one Three.js canvas in the whole app - it exists
// because the pipeline topology IS the product, not as decoration, and it
// is the entire justification for pulling in Three.js at all (see
// build-awwwards-quality-sites's "Three.js only with purpose").
//
// Static markup in welcome.html already renders an SVG of this exact same
// graph (same node positions, same edges) as the poster - this script's
// only job on a reduced-motion visitor, a WebGL failure, or before init is
// to leave that SVG alone. Nothing here is required for the hero to be
// complete; it is a pure enhancement layered on top of it.

(function () {
  "use strict";

  var container = document.getElementById("hero-scene");
  if (!container) return; // not the welcome page

  var reduceMotion = !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  var poster = document.getElementById("hero-poster");

  function useStaticPoster() {
    container.hidden = true;
    if (poster) poster.hidden = false;
  }

  if (reduceMotion || !window.THREE) {
    useStaticPoster();
  } else {
    initScene();
  }

  // --- GSAP hero intro + welcome-page-specific choreography --------------
  // Runs regardless of whether the Three.js scene initialized - the copy
  // and CTA must read as finished the same way with or without WebGL.
  if (window.gsap) {
    var titleEl = document.querySelector(".welcome-title");
    if (titleEl && window.pactRevealHeading) window.pactRevealHeading(titleEl, { delay: 0.15 });

    if (!reduceMotion) {
      var tl = gsap.timeline({ delay: 0.1 });
      tl.from(".welcome-eyebrow", { opacity: 0, y: 8, duration: 0.4, ease: "power2.out" }, 0)
        .from(".welcome-lede", { opacity: 0, y: 12, duration: 0.5, ease: "power2.out" }, 0.5)
        .from(".welcome-actions > *", { opacity: 0, y: 10, duration: 0.4, ease: "power2.out", stagger: 0.08 }, 0.65)
        .from("#hero-scene, #hero-poster", { opacity: 0, scale: 0.96, duration: 0.9, ease: "power2.out" }, 0.1);

      // Scroll-choreographed reveals: the one place in the app a scroll
      // trigger is earned - this page is read top to bottom once, not
      // scanned for a specific row the way a data table is.
      if (window.ScrollTrigger) {
        gsap.utils.toArray(".welcome-section").forEach(function (section) {
          gsap.from(section, {
            opacity: 0,
            y: 24,
            duration: 0.6,
            ease: "power2.out",
            scrollTrigger: { trigger: section, start: "top 85%" },
          });
        });
        gsap.from(".welcome-agent", {
          opacity: 0,
          x: -12,
          duration: 0.4,
          ease: "power2.out",
          stagger: 0.06,
          scrollTrigger: { trigger: ".welcome-agents", start: "top 80%" },
        });
      }
    }
  }

  function initScene() {
    var W, H;
    var scene, camera, renderer, group;
    var pulses = [];
    var rafId = null;
    var running = false;
    var pointer = { x: 0, y: 0 };
    var pointerTarget = { x: 0, y: 0 };

    // Node layout: mirrors the real pipeline diagram's left-to-right flow,
    // with the four parallel agents fanned out vertically in the middle.
    // z varies slightly per node purely for visual depth under the camera
    // parallax - it carries no other meaning.
    var NODES = [
      { name: "Discovery",   x: -7.5, y: 0,    z: 0.4 },
      { name: "Extraction",  x: -2.5, y: 3.2,  z: -0.6 },
      { name: "Waste",       x: -2.5, y: 1.05, z: 0.5 },
      { name: "Benchmark",   x: -2.5, y: -1.05, z: -0.3 },
      { name: "Renewal",     x: -2.5, y: -3.2, z: 0.7 },
      { name: "Optimization", x: 3,   y: 0,    z: -0.5 },
      { name: "Critic",      x: 6.2,  y: 0,    z: 0.3 },
      { name: "Narrator",    x: 9.2,  y: 0,    z: -0.4 },
    ];
    var EDGES = [
      [0, 1], [0, 2], [0, 3], [0, 4],
      [1, 5], [2, 5], [3, 5], [4, 5],
      [5, 6], [6, 7],
    ];

    function themeColor(varName, fallback) {
      var v = getComputedStyle(document.documentElement).getPropertyValue(varName).trim();
      return v || fallback;
    }

    function setup() {
      var rect = container.getBoundingClientRect();
      W = rect.width || container.clientWidth || 600;
      H = rect.height || container.clientHeight || 420;

      scene = new THREE.Scene();
      camera = new THREE.PerspectiveCamera(38, W / H, 0.1, 100);
      camera.position.set(0, 0, 18);

      try {
        renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
      } catch (e) {
        useStaticPoster();
        return false;
      }
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
      renderer.setSize(W, H);
      renderer.domElement.setAttribute("aria-hidden", "true");
      container.appendChild(renderer.domElement);

      // Only swap the visible layer over to the canvas once it has a real
      // WebGL context and a frame ready to render - the SVG poster stays
      // the thing on screen for every millisecond before this succeeds.
      container.hidden = false;
      if (poster) poster.hidden = true;

      renderer.domElement.addEventListener("webglcontextlost", function (e) {
        e.preventDefault();
        stop();
        useStaticPoster();
      });

      group = new THREE.Group();
      scene.add(group);

      var brand = new THREE.Color(themeColor("--brand", "#ff8a1e"));
      var accent = new THREE.Color(themeColor("--accent-2", "#8b7bf0"));

      // Edges: one static LineSegments draw call for all ten edges.
      var linePositions = new Float32Array(EDGES.length * 2 * 3);
      EDGES.forEach(function (edge, i) {
        var a = NODES[edge[0]], b = NODES[edge[1]];
        linePositions.set([a.x, a.y, a.z, b.x, b.y, b.z], i * 6);
      });
      var lineGeo = new THREE.BufferGeometry();
      lineGeo.setAttribute("position", new THREE.BufferAttribute(linePositions, 3));
      var lineMat = new THREE.LineBasicMaterial({ color: accent, transparent: true, opacity: 0.28 });
      group.add(new THREE.LineSegments(lineGeo, lineMat));

      // Nodes: small glowing spheres, brand-colored, Discovery/Narrator
      // (the pipeline's start and end) slightly larger to anchor the eye.
      var nodeGeo = new THREE.SphereGeometry(0.22, 16, 16);
      var nodeMat = new THREE.MeshBasicMaterial({ color: brand });
      NODES.forEach(function (n, i) {
        var mesh = new THREE.Mesh(nodeGeo, nodeMat);
        mesh.position.set(n.x, n.y, n.z);
        var scale = (i === 0 || i === NODES.length - 1) ? 1.35 : 1;
        mesh.scale.setScalar(scale);
        group.add(mesh);
      });

      // Pulses: a fixed pool of small points, one per edge, each looping
      // along its own edge on a staggered offset - reused every frame,
      // nothing allocated after setup.
      var pulseGeo = new THREE.SphereGeometry(0.09, 8, 8);
      var pulseMat = new THREE.MeshBasicMaterial({ color: brand, transparent: true, opacity: 0.9 });
      EDGES.forEach(function (edge, i) {
        var mesh = new THREE.Mesh(pulseGeo, pulseMat);
        group.add(mesh);
        pulses.push({
          mesh: mesh,
          from: NODES[edge[0]],
          to: NODES[edge[1]],
          t: (i / EDGES.length),
          speed: 0.12 + (i % 3) * 0.015,
        });
      });

      window.addEventListener("resize", onResize);
      container.addEventListener("mousemove", onPointerMove);
      container.addEventListener("mouseleave", onPointerLeave);

      return true;
    }

    function onResize() {
      var rect = container.getBoundingClientRect();
      W = rect.width || W;
      H = rect.height || H;
      if (!renderer || !camera) return;
      camera.aspect = W / H;
      camera.updateProjectionMatrix();
      renderer.setSize(W, H);
    }

    function onPointerMove(e) {
      var rect = container.getBoundingClientRect();
      pointerTarget.x = ((e.clientX - rect.left) / rect.width - 0.5) * 2;
      pointerTarget.y = ((e.clientY - rect.top) / rect.height - 0.5) * 2;
    }
    function onPointerLeave() {
      pointerTarget.x = 0;
      pointerTarget.y = 0;
    }

    var clock = new THREE.Clock();
    function tick() {
      if (!running) return;
      var dt = Math.min(clock.getDelta(), 0.05);

      pointer.x += (pointerTarget.x - pointer.x) * 0.04;
      pointer.y += (pointerTarget.y - pointer.y) * 0.04;
      group.rotation.y = pointer.x * 0.18;
      group.rotation.x = -pointer.y * 0.1;

      pulses.forEach(function (p) {
        p.t += dt * p.speed;
        if (p.t > 1) p.t -= 1;
        p.mesh.position.set(
          p.from.x + (p.to.x - p.from.x) * p.t,
          p.from.y + (p.to.y - p.from.y) * p.t,
          p.from.z + (p.to.z - p.from.z) * p.t
        );
      });

      renderer.render(scene, camera);
      rafId = requestAnimationFrame(tick);
    }

    function start() {
      if (running) return;
      running = true;
      clock.start();
      rafId = requestAnimationFrame(tick);
    }
    function stop() {
      running = false;
      if (rafId) cancelAnimationFrame(rafId);
      rafId = null;
    }

    // Pause entirely off-screen or when the tab isn't visible - this is a
    // hero decoration, not something worth spending a frame budget on
    // while it can't be seen.
    var io = null;
    // The loop only ever runs while BOTH conditions hold: the canvas is
    // actually on screen (IntersectionObserver) and the tab itself is the
    // visible one (visibilitychange). Each listener only knows its own
    // half of that, so both re-evaluate the combined state independently
    // on every change instead of assuming the other one will re-trigger -
    // an IntersectionObserver only fires on intersection changes, never on
    // a visibility change alone, so a version that left resuming-from-
    // hidden to "the intersection observer will handle it" would leave the
    // scene frozen forever the first time a visitor switched tabs and back.
    var isIntersecting = true;
    function syncRunning() {
      var shouldRun = isIntersecting && document.visibilityState === "visible";
      if (shouldRun) start(); else stop();
    }
    function watchVisibility() {
      if ("IntersectionObserver" in window) {
        isIntersecting = false;
        io = new IntersectionObserver(function (entries) {
          isIntersecting = entries[0].isIntersecting;
          syncRunning();
        }, { threshold: 0.05 });
        io.observe(container);
      } else {
        syncRunning();
      }
      document.addEventListener("visibilitychange", syncRunning);
    }

    function dispose() {
      stop();
      if (io) io.disconnect();
      window.removeEventListener("resize", onResize);
      container.removeEventListener("mousemove", onPointerMove);
      container.removeEventListener("mouseleave", onPointerLeave);
      if (!scene) return;
      scene.traverse(function (obj) {
        if (obj.geometry) obj.geometry.dispose();
        if (obj.material) obj.material.dispose();
      });
      if (renderer) {
        renderer.dispose();
        if (renderer.domElement && renderer.domElement.parentNode) {
          renderer.domElement.parentNode.removeChild(renderer.domElement);
        }
      }
    }
    window.addEventListener("pagehide", dispose);

    if (setup()) watchVisibility();
  }
})();
