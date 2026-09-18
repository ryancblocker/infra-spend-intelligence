// PACT motion system: GSAP entrance choreography + Lenis (the site's one
// smooth-scroll engine) + a word-by-word heading reveal, shared by every
// page. Page-specific work (the welcome hero's Three.js scene) lives in its
// own file and calls back into the helpers exported here.
//
// Everything in this file is additive on top of already-visible, already-
// readable markup - every element GSAP animates is styled and positioned
// correctly by plain CSS with no JS at all; GSAP's .from() only animates
// FROM a temporary starting state TO the element's natural rendered state,
// so a visitor with JavaScript disabled, or a slow/failed script load,
// simply sees the finished page with no animation, never a hidden one.

(function () {
  "use strict";

  var reduceMotion = !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  var hasGsap = !!window.gsap;

  // Switches off theme.css's plain CSS page-fade-in fallback the instant
  // GSAP is confirmed present - before this script touches a single
  // element - so the CSS and JS entrance animations can never both play on
  // the same load. If gsap.min.js failed to fetch, this class is never
  // added and that CSS fallback is exactly what keeps the page from
  // looking broken instead of just unanimated.
  if (hasGsap) document.documentElement.classList.add("pact-motion-ready");

  if (hasGsap && window.ScrollTrigger) {
    gsap.registerPlugin(ScrollTrigger);
  }

  // --- Lenis: the site's one smooth-scroll engine -----------------------
  // Tuned light on purpose - a short duration and a gentle cubic-out curve
  // read as a slight inertia refinement, not the heavy cinematic drag a
  // marketing site can afford. PACT is read in dense tables for long
  // stretches, so anything heavier would fight fast, precise scanning.
  // Fully skipped under reduced motion, which leaves the browser's native
  // scroll in place - not a "lighter" Lenis, no Lenis at all.
  var lenis = null;
  if (!reduceMotion && window.Lenis && hasGsap) {
    lenis = new Lenis({
      duration: 0.7,
      easing: function (t) { return 1 - Math.pow(1 - t, 3); },
      smoothWheel: true,
      wheelMultiplier: 1,
      touchMultiplier: 1.2,
    });
    lenis.on("scroll", ScrollTrigger.update);
    gsap.ticker.add(function (time) { lenis.raf(time * 1000); });
    gsap.ticker.lagSmoothing(0);
  }
  window.pactLenis = lenis;

  // --- Word-by-word heading reveal ---------------------------------------
  // Splits an element's own text into word-spans purely at runtime (the
  // server-rendered HTML is always the plain, complete heading) and gives
  // the element an aria-label of that original text so assistive tech
  // announces one clean phrase instead of 20 individually-hidden spans -
  // the spans themselves carry aria-hidden="true" for exactly that reason.
  function splitWords(el) {
    var text = el.textContent;
    el.setAttribute("aria-label", text);
    var tokens = text.split(/(\s+)/);
    el.textContent = "";
    var spans = [];
    tokens.forEach(function (chunk) {
      if (chunk === "" ) return;
      if (/^\s+$/.test(chunk)) {
        el.appendChild(document.createTextNode(chunk));
        return;
      }
      var span = document.createElement("span");
      span.className = "word-split";
      span.setAttribute("aria-hidden", "true");
      span.textContent = chunk;
      el.appendChild(span);
      spans.push(span);
    });
    return spans;
  }

  function revealHeading(el, opts) {
    opts = opts || {};
    if (!el || reduceMotion || !hasGsap) return;
    var spans = splitWords(el);
    if (!spans.length) return;
    gsap.from(spans, {
      opacity: 0,
      yPercent: 60,
      duration: 0.7,
      ease: "power3.out",
      stagger: 0.04,
      delay: opts.delay || 0,
    });
  }
  window.pactRevealHeading = revealHeading;

  // --- Generic load-time entrance ----------------------------------------
  // Every page shares the same shell (.page-header > .page-title +
  // .page-subtitle, then a run of top-level blocks inside <main>), so one
  // generic timeline can choreograph any page without page-specific code:
  // the title reveals word by word, the subtitle and the first handful of
  // sections settle in with a short top-to-bottom stagger. This replaces
  // the old CSS-only page-fade-in - GSAP owns page-load motion now, CSS
  // keeps the plain fallback for when GSAP hasn't run (see the file banner).
  function pageEntrance() {
    var main = document.querySelector(".main");
    if (!main) return;

    var title = main.querySelector(".page-title, .welcome-title");
    if (title) revealHeading(title);

    if (reduceMotion || !hasGsap) return;

    // The welcome page nests everything inside one .welcome wrapper instead
    // of a run of top-level <main> children, and has its own dedicated
    // hero.js choreography (Three.js hero, scroll-triggered section
    // reveals) - let that own the rest of this page instead of the generic
    // stagger below double-animating the same elements.
    if (main.querySelector(".welcome")) return;

    var subtitle = main.querySelector(".page-subtitle, .welcome-lede");
    var sections = Array.prototype.slice.call(main.children).filter(function (child) {
      return child !== main.querySelector(".page-header") && !child.classList.contains("page-header");
    });
    // Cap the stagger to the first handful of sections - a long page (a
    // 48-row contracts table, a long findings list) would otherwise force
    // the reader to wait through a multi-second cascade before the content
    // below the fold is even in its resting state.
    var staggered = sections.slice(0, 6);
    var rest = sections.slice(6);

    var tl = gsap.timeline({ delay: title ? 0.25 : 0 });
    if (subtitle) tl.from(subtitle, { opacity: 0, y: 10, duration: 0.5, ease: "power2.out" }, 0.1);
    if (staggered.length) {
      tl.from(staggered, {
        opacity: 0, y: 16, duration: 0.5, ease: "power2.out", stagger: 0.08,
      }, subtitle ? 0.2 : 0);
    }
    // Anything past the cap just appears at rest, undelayed - correct and
    // instant beats correct-but-late on a page someone opens dozens of
    // times a day.
    rest.forEach(function (el) { gsap.set(el, { clearProps: "all" }); });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", pageEntrance);
  } else {
    pageEntrance();
  }

  window.pactMotion = { reduceMotion: reduceMotion, hasGsap: hasGsap };
})();
