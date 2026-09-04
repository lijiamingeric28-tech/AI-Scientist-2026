(function (root, factory) {
  "use strict";

  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else {
    root.AstroQueryLanding = api;
    if (root.document) {
      root.__AQ_LANDING_V2__ = true;
      api.init(root.document, root);
    }
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function clamp01(value) {
    return Math.max(0, Math.min(1, value));
  }

  function smoothstep(from, to, value) {
    var t = clamp01((value - from) / (to - from));
    return t * t * (3 - 2 * t);
  }

  function segmentPoint(ax, ay, bx, by, progress) {
    var t = clamp01(progress);
    return { x: ax + (bx - ax) * t, y: ay + (by - ay) * t };
  }

  function getHeroProgress(rectTop, rectHeight, viewportHeight) {
    return clamp01(-rectTop / Math.max(1, rectHeight - viewportHeight));
  }

  function sampleAPoint(progress) {
    var t = clamp01(progress);
    if (t < 0.4) return segmentPoint(-0.26, 0.32, 0, -0.34, t / 0.4);
    if (t < 0.8) return segmentPoint(0, -0.34, 0.27, 0.32, (t - 0.4) / 0.4);
    return segmentPoint(-0.14, 0.08, 0.15, 0.08, (t - 0.8) / 0.2);
  }

  function sampleQPoint(progress) {
    var t = clamp01(progress);
    if (t < 0.88) {
      var angle = (t / 0.88) * Math.PI * 2;
      return { x: Math.cos(angle) * 0.48, y: Math.sin(angle) * 0.17 };
    }
    return segmentPoint(0.25, 0.11, 0.5, 0.32, (t - 0.88) / 0.12);
  }

  function getMotionStages(progress) {
    var p = clamp01(progress);
    return {
      deform: smoothstep(0.3, 0.68, p),
      burst: smoothstep(0.68, 1, p),
      copyOpacity: 1 - smoothstep(0.24, 0.66, p)
    };
  }

  function shouldAnimate(heroVisible, documentHidden, reduceMotion) {
    return Boolean(heroVisible && !documentHidden && !reduceMotion);
  }

  function getFormationProgress(startedAt, now, duration, reduceMotion) {
    if (reduceMotion) return 1;
    if (startedAt == null) return 0;
    return smoothstep(startedAt, startedAt + Math.max(1, duration), now);
  }

  function getActivatedHeroProgress(scrollProgress, startedAt, now, formationDuration, reduceMotion) {
    if (reduceMotion || startedAt == null) return 0;
    var duration = Math.max(1, formationDuration);
    var unlock = smoothstep(startedAt + duration + 300, startedAt + duration + 750, now);
    return clamp01(scrollProgress) * unlock;
  }

  function sampleOrbitPoint(progress, ringIndex) {
    var radiiX = [0.31, 0.4, 0.5, 0.61];
    var radiiY = [0.105, 0.145, 0.19, 0.235];
    var ring = Math.max(0, Math.min(radiiX.length - 1, ringIndex | 0));
    var angle = clamp01(progress) * Math.PI * 2;
    return {
      x: Math.cos(angle) * radiiX[ring],
      y: Math.sin(angle) * radiiY[ring]
    };
  }

  function getSideRailOpacity(heroProgress) {
    return smoothstep(0.58, 0.88, heroProgress);
  }

  function getSideRailPosition(side, xSeed, ySeed, time, width, height) {
    var edge = 0.035 + clamp01(xSeed) * 0.14;
    var normalizedY = ((clamp01(ySeed) + time * 0.05) % 1 + 1) % 1;
    return {
      x: Math.round((side < 0 ? edge : 1 - edge) * width * 1000) / 1000,
      y: Math.round(normalizedY * height * 1000) / 1000
    };
  }

  function shouldAnimateScene(heroVisible, sideOpacity, documentHidden, reduceMotion) {
    return Boolean(!documentHidden && !reduceMotion && (heroVisible || sideOpacity > 0));
  }

  function shouldRenderHero(heroVisible, rectTop, rectBottom, viewportHeight) {
    var intersectsViewport = rectBottom > 0 && rectTop < Math.max(1, viewportHeight);
    return Boolean(heroVisible || intersectsViewport);
  }

  function getParticleCounts(width, height, isSmall) {
    var base = isSmall
      ? { background: 160, nebula: 390, orbit: 300, glyphA: 240, glyphQ: 270, core: 120 }
      : { background: 430, nebula: 1200, orbit: 900, glyphA: 620, glyphQ: 710, core: 220 };
    var referenceArea = isSmall ? 390 * 844 : 1440 * 900;
    var areaScale = Math.max(0.64, Math.min(1.15, Math.max(1, width * height) / referenceArea));
    var counts = {
      background: Math.round(base.background * areaScale),
      nebula: Math.round(base.nebula * areaScale),
      orbit: Math.round(base.orbit * areaScale),
      glyphA: Math.round(base.glyphA * areaScale),
      glyphQ: Math.round(base.glyphQ * areaScale),
      core: Math.round(base.core * areaScale)
    };
    var maximum = Math.round((base.background + base.nebula + base.orbit + base.glyphA + base.glyphQ + base.core) * 1.15);
    var total = counts.background + counts.nebula + counts.orbit + counts.glyphA + counts.glyphQ + counts.core;
    if (total > maximum) counts.nebula -= total - maximum;
    return counts;
  }

  function advanceAnimationClock(elapsed, previousTimestamp, nextTimestamp, maxDeltaSeconds) {
    var delta = Math.max(0, (nextTimestamp - previousTimestamp) / 1000);
    return {
      elapsed: elapsed + Math.min(delta, maxDeltaSeconds),
      timestamp: nextTimestamp
    };
  }

  function nearestSlideIndex(containerCenter, slideCenters) {
    if (!slideCenters || !slideCenters.length) return 0;
    var nearest = 0;
    var nearestDistance = Infinity;
    slideCenters.forEach(function (center, index) {
      var distance = Math.abs(center - containerCenter);
      if (distance < nearestDistance) {
        nearest = index;
        nearestDistance = distance;
      }
    });
    return nearest;
  }

  function carouselKeyTarget(key, currentIndex, slideCount) {
    if (slideCount < 1) return null;
    if (key === "ArrowRight") return Math.min(slideCount - 1, currentIndex + 1);
    if (key === "ArrowLeft") return Math.max(0, currentIndex - 1);
    if (key === "Home") return 0;
    if (key === "End") return slideCount - 1;
    return null;
  }

  function applyRevealState(element, isVisible) {
    element.classList.toggle("is-visible", Boolean(isVisible));
  }

  function init(document, window) {
    initNavigation(document, window);
    initHero(document, window);
    initReveal(document, window);
    initCarousel(document, window);
    initLightbox(document, window);
  }

  function initNavigation(document, window) {
    var nav = document.getElementById("nav");
    if (!nav) return;
    function updateNavigation() {
      nav.classList.toggle("scrolled", window.scrollY > 24);
    }
    window.addEventListener("scroll", updateNavigation, { passive: true });
    updateNavigation();
  }

  function initReveal(document, window) {
    var elements = Array.prototype.slice.call(document.querySelectorAll(".reveal"));
    var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduceMotion || !("IntersectionObserver" in window)) {
      elements.forEach(function (element) { applyRevealState(element, true); });
      return;
    }

    var observer = new window.IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        applyRevealState(entry.target, entry.isIntersecting);
      });
    }, { threshold: 0.14, rootMargin: "0px 0px -8% 0px" });

    elements.forEach(function (element) { observer.observe(element); });
  }

  function initCarousel(document, window) {
    var carousel = document.getElementById("car");
    var dotsBox = document.getElementById("carDots");
    var count = document.getElementById("carCount");
    var status = document.getElementById("carStatus");
    var previous = document.getElementById("carPrev");
    var next = document.getElementById("carNext");
    if (!carousel || !dotsBox || !count || !status || !previous || !next) return;

    var slides = Array.prototype.slice.call(carousel.querySelectorAll(".slide"));
    var activeIndex = 0;
    var scrollFrame = 0;
    var announceTimer = 0;
    var pointerDown = false;
    var pointerId = null;
    var pointerStartX = 0;
    var pointerStartScroll = 0;
    var pointerMoved = false;
    var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    dotsBox.textContent = "";
    var dots = slides.map(function (_, index) {
      var dot = document.createElement("button");
      dot.type = "button";
      dot.className = "car-dot";
      dot.setAttribute("aria-label", "查看第 " + (index + 1) + " 张卡片");
      dot.addEventListener("click", function () { goTo(index); });
      dotsBox.appendChild(dot);
      return dot;
    });

    function currentIndexFromGeometry() {
      var carouselRect = carousel.getBoundingClientRect();
      var containerCenter = carouselRect.left + carouselRect.width / 2;
      var centers = slides.map(function (slide) {
        var rect = slide.getBoundingClientRect();
        return rect.left + rect.width / 2;
      });
      return nearestSlideIndex(containerCenter, centers);
    }

    function renderState(index, announce) {
      activeIndex = Math.max(0, Math.min(slides.length - 1, index));
      dots.forEach(function (dot, dotIndex) {
        var current = dotIndex === activeIndex;
        dot.classList.toggle("on", current);
        if (current) dot.setAttribute("aria-current", "true");
        else dot.removeAttribute("aria-current");
      });
      count.textContent = String(activeIndex + 1).padStart(2, "0") + " / " + String(slides.length).padStart(2, "0");
      if (announce !== false) status.textContent = "第 " + (activeIndex + 1) + " 张，共 " + slides.length + " 张";
      previous.disabled = activeIndex === 0;
      next.disabled = activeIndex === slides.length - 1;
    }

    function goTo(index) {
      var target = Math.max(0, Math.min(slides.length - 1, index));
      var slide = slides[target];
      var left = slide.offsetLeft - (carousel.clientWidth - slide.clientWidth) / 2;
      carousel.scrollTo({ left: left, behavior: reduceMotion ? "auto" : "smooth" });
      renderState(target, true);
    }

    previous.addEventListener("click", function () { goTo(activeIndex - 1); });
    next.addEventListener("click", function () { goTo(activeIndex + 1); });

    carousel.addEventListener("keydown", function (event) {
      var target = carouselKeyTarget(event.key, activeIndex, slides.length);
      if (target == null) return;
      event.preventDefault();
      goTo(target);
    });

    carousel.addEventListener("scroll", function () {
      if (announceTimer) window.clearTimeout(announceTimer);
      announceTimer = window.setTimeout(function () {
        announceTimer = 0;
        renderState(currentIndexFromGeometry(), true);
      }, 160);
      if (scrollFrame) return;
      scrollFrame = window.requestAnimationFrame(function () {
        scrollFrame = 0;
        renderState(currentIndexFromGeometry(), false);
      });
    }, { passive: true });

    carousel.addEventListener("pointerdown", function (event) {
      if (event.pointerType !== "mouse") return;
      pointerDown = true;
      pointerId = event.pointerId;
      pointerMoved = false;
      pointerStartX = event.clientX;
      pointerStartScroll = carousel.scrollLeft;
      carousel.setPointerCapture(pointerId);
      carousel.classList.add("dragging");
    });

    carousel.addEventListener("pointermove", function (event) {
      if (!pointerDown || event.pointerId !== pointerId) return;
      var distance = event.clientX - pointerStartX;
      if (Math.abs(distance) > 5) pointerMoved = true;
      carousel.scrollLeft = pointerStartScroll - distance;
    });

    function finishDrag(event) {
      if (!pointerDown || event.pointerId !== pointerId) return;
      pointerDown = false;
      if (carousel.hasPointerCapture(pointerId)) carousel.releasePointerCapture(pointerId);
      pointerId = null;
      carousel.classList.remove("dragging");
      goTo(currentIndexFromGeometry());
    }

    carousel.addEventListener("pointerup", finishDrag);
    carousel.addEventListener("pointercancel", finishDrag);
    carousel.addEventListener("dragstart", function (event) { event.preventDefault(); });
    carousel.addEventListener("click", function (event) {
      if (!pointerMoved) return;
      event.preventDefault();
      event.stopPropagation();
      pointerMoved = false;
    }, true);
    window.addEventListener("resize", function () { renderState(currentIndexFromGeometry(), true); }, { passive: true });

    renderState(0, true);
  }

  function initLightbox(document) {
    var items = Array.prototype.slice.call(document.querySelectorAll("[data-cap]"));
    var lightbox = document.getElementById("lightbox");
    var lightboxImage = document.getElementById("lbImg");
    var caption = document.getElementById("lbCap");
    var closeButton = document.getElementById("lbClose");
    var previousButton = document.getElementById("lbPrev");
    var nextButton = document.getElementById("lbNext");
    if (!items.length || !lightbox || !lightboxImage || !caption || !closeButton || !previousButton || !nextButton) return;

    var current = 0;
    var previousFocus = null;

    function show(index) {
      current = (index + items.length) % items.length;
      var item = items[current];
      var sourceImage = item.querySelector("img");
      lightbox.classList.remove("has-image-error");
      lightboxImage.src = sourceImage.src;
      lightboxImage.alt = sourceImage.alt;
      caption.textContent = item.getAttribute("data-cap") || sourceImage.alt;
    }

    function open(index) {
      previousFocus = document.activeElement;
      show(index);
      lightbox.setAttribute("aria-hidden", "false");
      lightbox.classList.add("open");
      document.body.classList.add("modal-open");
      closeButton.focus();
    }

    function close() {
      lightbox.classList.remove("open");
      lightbox.setAttribute("aria-hidden", "true");
      document.body.classList.remove("modal-open");
      if (previousFocus && previousFocus.focus) previousFocus.focus();
    }

    items.forEach(function (item, index) {
      item.tabIndex = 0;
      item.setAttribute("role", "button");
      item.setAttribute("aria-label", "查看大图：" + (item.getAttribute("data-cap") || "架构图"));
      item.addEventListener("click", function () { open(index); });
      item.addEventListener("keydown", function (event) {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        open(index);
      });
    });

    lightboxImage.addEventListener("error", function () {
      lightbox.classList.add("has-image-error");
      caption.textContent = "图片暂时无法加载，请查看卡片中的文字说明。";
    });
    closeButton.addEventListener("click", close);
    previousButton.addEventListener("click", function (event) { event.stopPropagation(); show(current - 1); });
    nextButton.addEventListener("click", function (event) { event.stopPropagation(); show(current + 1); });
    lightbox.addEventListener("click", function (event) { if (event.target === lightbox) close(); });
    document.addEventListener("keydown", function (event) {
      if (!lightbox.classList.contains("open")) return;
      if (event.key === "Escape") close();
      if (event.key === "ArrowLeft") show(current - 1);
      if (event.key === "ArrowRight") show(current + 1);
      if (event.key === "Tab") {
        var controls = [closeButton, previousButton, nextButton];
        var focusIndex = controls.indexOf(document.activeElement);
        if (event.shiftKey && focusIndex <= 0) {
          event.preventDefault();
          nextButton.focus();
        } else if (!event.shiftKey && (focusIndex < 0 || focusIndex === controls.length - 1)) {
          event.preventDefault();
          closeButton.focus();
        }
      }
    });
  }

  function initHero(document, window) {
    var canvas = document.getElementById("starfield");
    var sideCanvas = document.getElementById("sidefield");
    var hero = document.getElementById("top");
    var stage = document.getElementById("heroStage");
    var gate = document.getElementById("starGate");
    if (!canvas || !hero || !stage || !canvas.getContext) {
      if (stage) stage.classList.add("no-canvas");
      return;
    }

    var context = canvas.getContext("2d");
    if (!context) {
      stage.classList.add("no-canvas");
      return;
    }
    var sideContext = sideCanvas && sideCanvas.getContext ? sideCanvas.getContext("2d") : null;

    var motionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    var reduceMotion = motionQuery.matches;
    var width = 0;
    var height = 0;
    var dpr = 1;
    var isSmall = false;
    var particles = [];
    var sideParticles = [];
    var sprites = createSprites(document);
    var pointerTargetX = 0;
    var pointerTargetY = 0;
    var pointerX = 0;
    var pointerY = 0;
    var heroVisible = true;
    var rafId = 0;
    var lastTime = window.performance.now();
    var elapsedTime = 0;
    var formationStartedAt = reduceMotion ? 0 : null;
    var formationDuration = 2200;
    var sideOpacity = 0;

    function randomBetween(min, max) {
      return min + Math.random() * (max - min);
    }

    function gaussian() {
      return (Math.random() + Math.random() + Math.random() - 1.5) / 1.5;
    }

    function makeParticle(kind, point, options) {
      options = options || {};
      return {
        kind: kind,
        x: point.x,
        y: point.y,
        size: options.size || randomBetween(0.65, 2.15),
        color: options.color == null ? Math.floor(Math.random() * sprites.length) : options.color,
        alpha: options.alpha || randomBetween(0.35, 0.78),
        twinkleOffset: randomBetween(0, Math.PI * 2),
        twinkleSpeed: randomBetween(0.55, 1.8),
        side: options.side || (Math.random() < 0.5 ? -1 : 1),
        streamX: Math.random(),
        streamY: Math.random(),
        streamSpeed: randomBetween(0.018, 0.07),
        depth: options.depth || randomBetween(0.35, 1),
        angle: options.angle || 0,
        radius: options.radius || 0,
        arm: options.arm || 0,
        ring: options.ring || 0,
        drift: randomBetween(0.35, 1.15),
        chaosX: Math.random() - 0.5,
        chaosY: Math.random() - 0.5,
        chaosPhase: randomBetween(0, Math.PI * 2),
        chaosSpeed: randomBetween(0.1, 0.36)
      };
    }

    function buildParticles() {
      particles = [];
      var counts = getParticleCounts(width, height, isSmall);
      var index;

      for (index = 0; index < counts.background; index += 1) {
        particles.push(makeParticle("background", {
          x: Math.random() - 0.5,
          y: Math.random() - 0.5
        }, {
          size: randomBetween(0.45, 1.35),
          alpha: randomBetween(0.2, 0.55),
          depth: randomBetween(0.2, 0.8)
        }));
      }

      for (index = 0; index < counts.nebula; index += 1) {
        var arm = index % 3;
        var radial = Math.pow(Math.random(), 0.66);
        var angle = arm * Math.PI * 2 / 3 + radial * 6.1 + gaussian() * (0.14 + radial * 0.19);
        particles.push(makeParticle("nebula", { x: 0, y: 0 }, {
          angle: angle,
          radius: 0.055 + radial * 0.61,
          arm: arm,
          side: Math.cos(angle) < 0 ? -1 : 1,
          size: randomBetween(0.7, 2.55) * (Math.random() < 0.07 ? 1.9 : 1),
          color: Math.random() < 0.4 ? 2 : (Math.random() < 0.52 ? 1 : 0),
          alpha: randomBetween(0.4, 0.86)
        }));
      }

      for (index = 0; index < counts.orbit; index += 1) {
        var ring = index % 4;
        var orbitPoint = sampleOrbitPoint((index + Math.random() * 0.7) / counts.orbit * 4 % 1, ring);
        particles.push(makeParticle("orbit", {
          x: orbitPoint.x + gaussian() * 0.0055,
          y: orbitPoint.y + gaussian() * 0.0045
        }, {
          ring: ring,
          side: orbitPoint.x < 0 ? -1 : 1,
          size: randomBetween(0.72, 2.45) * (Math.random() < 0.12 ? 1.85 : 1),
          color: Math.random() < 0.48 ? 0 : (Math.random() < 0.48 ? 4 : 1),
          alpha: randomBetween(0.52, 0.96),
          depth: randomBetween(0.72, 1.12)
        }));
      }

      for (index = 0; index < counts.glyphA; index += 1) {
        var aPoint = sampleAPoint(index / Math.max(1, counts.glyphA - 1));
        particles.push(makeParticle("glyph-a", {
          x: aPoint.x + gaussian() * 0.0075,
          y: aPoint.y + gaussian() * 0.0075
        }, {
          side: aPoint.x < 0 ? -1 : 1,
          size: randomBetween(1.05, 2.9) * (Math.random() < 0.13 ? 1.65 : 1),
          color: Math.random() < 0.6 ? 4 : (Math.random() < 0.66 ? 0 : 1),
          alpha: randomBetween(0.7, 1),
          depth: randomBetween(0.76, 1.12)
        }));
      }

      for (index = 0; index < counts.glyphQ; index += 1) {
        var qPoint = sampleQPoint(index / Math.max(1, counts.glyphQ - 1));
        particles.push(makeParticle("glyph-q", {
          x: qPoint.x + gaussian() * 0.0065,
          y: qPoint.y + gaussian() * 0.0055
        }, {
          side: qPoint.x < 0 ? -1 : 1,
          size: randomBetween(0.95, 2.7) * (Math.random() < 0.11 ? 1.7 : 1),
          color: Math.random() < 0.54 ? 2 : (Math.random() < 0.66 ? 0 : 4),
          alpha: randomBetween(0.64, 0.98),
          depth: randomBetween(0.68, 1.08)
        }));
      }

      for (index = 0; index < counts.core; index += 1) {
        var coreRadius = Math.pow(Math.random(), 2.4) * 0.12;
        var coreAngle = Math.random() * Math.PI * 2;
        particles.push(makeParticle("core", {
          x: Math.cos(coreAngle) * coreRadius,
          y: Math.sin(coreAngle) * coreRadius * 0.68
        }, {
          side: Math.cos(coreAngle) < 0 ? -1 : 1,
          size: randomBetween(1.25, 3.4) * (Math.random() < 0.18 ? 1.75 : 1),
          color: Math.random() < 0.72 ? 4 : (Math.random() < 0.5 ? 0 : 1),
          alpha: randomBetween(0.72, 1),
          depth: randomBetween(0.88, 1.18)
        }));
      }

      buildSideParticles();
    }

    function buildSideParticles() {
      sideParticles = [];
      var count = isSmall ? 190 : 480;
      for (var index = 0; index < count; index += 1) {
        sideParticles.push({
          side: index % 2 === 0 ? -1 : 1,
          xSeed: Math.pow(Math.random(), 1.45),
          ySeed: Math.random(),
          speed: randomBetween(0.025, 0.085),
          scrollInfluence: randomBetween(0.035, 0.11),
          phase: randomBetween(0, Math.PI * 2),
          size: randomBetween(0.65, 2.25) * (Math.random() < 0.1 ? 1.9 : 1),
          alpha: randomBetween(0.28, 0.78),
          color: Math.random() < 0.48 ? 0 : (Math.random() < 0.58 ? 2 : 1)
        });
      }
    }

    function createSprites(ownerDocument) {
      var colors = [
        "rgba(193,226,255,.94)",
        "rgba(255,174,121,.9)",
        "rgba(173,126,255,.94)",
        "rgba(116,240,218,.78)",
        "rgba(245,250,255,.98)"
      ];
      return colors.map(function (middle) {
        var sprite = ownerDocument.createElement("canvas");
        sprite.width = 84;
        sprite.height = 84;
        var spriteContext = sprite.getContext("2d");
        var glow = spriteContext.createRadialGradient(42, 42, 0, 42, 42, 42);
        glow.addColorStop(0, "rgba(255,255,255,1)");
        glow.addColorStop(0.09, "rgba(255,255,255,1)");
        glow.addColorStop(0.28, middle);
        glow.addColorStop(1, "rgba(0,0,0,0)");
        spriteContext.fillStyle = glow;
        spriteContext.fillRect(0, 0, 84, 84);
        return sprite;
      });
    }

    function resize() {
      var nextSmall = window.innerWidth < 720;
      isSmall = nextSmall;
      dpr = Math.min(window.devicePixelRatio || 1, isSmall ? 1.25 : 1.6);
      width = Math.max(1, stage.clientWidth);
      height = Math.max(1, stage.clientHeight);
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      canvas.style.width = width + "px";
      canvas.style.height = height + "px";
      if (sideCanvas && sideContext) {
        sideCanvas.width = Math.round(window.innerWidth * dpr);
        sideCanvas.height = Math.round(window.innerHeight * dpr);
        sideCanvas.style.width = window.innerWidth + "px";
        sideCanvas.style.height = window.innerHeight + "px";
      }
      buildParticles();
      draw(elapsedTime);
    }

    function basePosition(particle, time, scale, centerX, centerY, deform) {
      var x = particle.x;
      var y = particle.y;

      if (particle.kind === "background") {
        return {
          x: (particle.x + 0.5) * width - pointerX * 32 * particle.depth,
          y: (particle.y + 0.5) * height - pointerY * 22 * particle.depth
        };
      }

      if (particle.kind === "nebula") {
        var nebulaAngle = particle.angle + time * 0.026 * particle.drift + deform * 0.72;
        x = Math.cos(nebulaAngle) * particle.radius;
        y = Math.sin(nebulaAngle) * particle.radius * (0.42 - deform * 0.14);
      }

      if (particle.kind === "orbit") {
        var ringTilts = [-0.38, -0.17, 0.12, 0.34];
        var ringDirections = [1, -1, 1, -1];
        var ringRotation = ringTilts[particle.ring] + time * 0.012 * ringDirections[particle.ring];
        var ringCosine = Math.cos(ringRotation);
        var ringSine = Math.sin(ringRotation);
        var ringX = x * ringCosine - y * ringSine;
        var ringY = x * ringSine + y * ringCosine;
        x = ringX;
        y = ringY;
      }

      var pointerRotation = pointerX * 0.1 + pointerY * 0.035;
      var motionRotation = particle.kind.indexOf("glyph") === 0
        ? pointerRotation * 0.45 + time * 0.004
        : pointerRotation + time * 0.012;
      var cosine = Math.cos(motionRotation);
      var sine = Math.sin(motionRotation);
      var rotatedX = x * cosine - y * sine;
      var rotatedY = x * sine + y * cosine;
      var stretchX = 1 + deform * (particle.kind.indexOf("glyph") === 0 ? 0.48 : 0.7);
      var squashY = 1 - deform * 0.5;

      return {
        x: centerX + rotatedX * scale * stretchX + pointerX * 42 * particle.depth,
        y: centerY + rotatedY * scale * squashY + pointerY * 28 * particle.depth
      };
    }

    function chaosPosition(particle, time) {
      var wobble = Math.min(width, height) * (0.014 + 0.018 * particle.depth);
      return {
        x: (particle.chaosX + 0.5) * width
          + Math.sin(time * particle.chaosSpeed + particle.chaosPhase) * wobble
          + pointerX * 16 * particle.depth,
        y: (particle.chaosY + 0.5) * height
          + Math.cos(time * particle.chaosSpeed * 0.83 + particle.chaosPhase) * wobble
          + pointerY * 12 * particle.depth
      };
    }

    function streamPosition(particle, time) {
      var edgeStart = particle.side < 0 ? 0.025 : 0.79;
      return {
        x: (edgeStart + particle.streamX * 0.18) * width,
        y: (((particle.streamY + time * particle.streamSpeed) % 1.12) - 0.06) * height
      };
    }

    function drawSprite(particle, x, y, size, alpha, burst) {
      context.globalAlpha = Math.max(0, Math.min(1, alpha));
      var diameter = size * (isSmall ? 5 : 6.2);
      context.drawImage(sprites[particle.color], x - diameter / 2, y - diameter / 2, diameter, diameter);

      if (burst > 0.12 && particle.size > 1.8) {
        context.fillStyle = particle.color === 1 ? "rgba(255,198,151,.32)" : "rgba(184,158,255,.3)";
        context.fillRect(x - particle.side * diameter * 2.2, y - 0.45, particle.side * diameter * 2.2, 0.9);
      }
    }

    function drawSideField(time, opacity) {
      if (!sideCanvas || !sideContext) return;
      sideCanvas.style.opacity = opacity.toFixed(3);
      sideContext.setTransform(dpr, 0, 0, dpr, 0, 0);
      sideContext.clearRect(0, 0, window.innerWidth, window.innerHeight);
      if (opacity <= 0.002) return;

      sideContext.globalCompositeOperation = "lighter";
      var scrollUnits = window.scrollY / Math.max(1, window.innerHeight);
      sideParticles.forEach(function (particle) {
        var movingSeed = ((particle.ySeed + time * particle.speed
          + scrollUnits * particle.scrollInfluence) % 1 + 1) % 1;
        var position = getSideRailPosition(
          particle.side,
          particle.xSeed,
          movingSeed,
          0,
          window.innerWidth,
          window.innerHeight
        );
        var wave = Math.sin(time * (0.36 + particle.speed * 2.5) + particle.phase) * (8 + particle.xSeed * 24);
        var x = position.x + wave * particle.side;
        var diameter = particle.size * (isSmall ? 4.2 : 5.4);
        var twinkle = reduceMotion ? 1 : 0.74 + Math.sin(time * 1.2 + particle.phase) * 0.26;
        sideContext.globalAlpha = Math.min(1, particle.alpha * twinkle * opacity);
        sideContext.drawImage(sprites[particle.color], x - diameter / 2, position.y - diameter / 2, diameter, diameter);

        if (particle.size > 2.25) {
          sideContext.fillStyle = particle.color === 1
            ? "rgba(255,184,132,.28)"
            : "rgba(194,220,255,.27)";
          sideContext.fillRect(x - 0.45, position.y - diameter * 2.2, 0.9, diameter * 4.4);
        }
      });
      sideContext.globalAlpha = 1;
      sideContext.globalCompositeOperation = "source-over";
    }

    function measureSideOpacity(animationTimeMs) {
      var rect = hero.getBoundingClientRect();
      if (reduceMotion) return rect.bottom < window.innerHeight * 0.62 ? 1 : 0;
      var rawProgress = getHeroProgress(rect.top, rect.height, window.innerHeight);
      var activatedProgress = getActivatedHeroProgress(
        rawProgress,
        formationStartedAt,
        animationTimeMs,
        formationDuration,
        false
      );
      return getSideRailOpacity(activatedProgress);
    }

    function activateFormation() {
      if (reduceMotion || formationStartedAt != null) return;
      formationStartedAt = elapsedTime * 1000;
      if (gate) {
        gate.classList.add("is-dismissed");
        gate.setAttribute("aria-hidden", "true");
        gate.disabled = true;
      }
      stage.classList.add("is-forming");
      scheduleFrame();
    }

    function handleMotionPreferenceChange(event) {
      reduceMotion = event.matches;
      lastTime = window.performance.now();
      if (reduceMotion) {
        if (rafId) window.cancelAnimationFrame(rafId);
        rafId = 0;
        formationStartedAt = 0;
        if (gate) {
          gate.classList.add("is-dismissed");
          gate.setAttribute("aria-hidden", "true");
          gate.disabled = true;
        }
        stage.classList.add("is-formed");
        draw(elapsedTime);
        return;
      }

      formationStartedAt = elapsedTime * 1000 - formationDuration;
      scheduleFrame();
    }

    function draw(animationTime) {
      var time = reduceMotion ? 0 : animationTime;
      var heroRect = hero.getBoundingClientRect();
      var rawProgress = reduceMotion ? 0 : getHeroProgress(heroRect.top, heroRect.height, window.innerHeight);
      var progress = getActivatedHeroProgress(
        rawProgress,
        formationStartedAt,
        animationTime * 1000,
        formationDuration,
        reduceMotion
      );
      var stages = getMotionStages(progress);
      var formation = getFormationProgress(formationStartedAt, animationTime * 1000, formationDuration, reduceMotion);
      pointerX += (pointerTargetX - pointerX) * 0.055;
      pointerY += (pointerTargetY - pointerY) * 0.055;

      sideOpacity = measureSideOpacity(animationTime * 1000);
      drawSideField(time, sideOpacity);

      stage.style.setProperty("--hero-progress", progress.toFixed(4));
      stage.style.setProperty("--hero-copy-opacity", (stages.copyOpacity * (0.18 + formation * 0.82)).toFixed(4));
      stage.style.setProperty("--hero-copy-scale", (1 - stages.deform * 0.075).toFixed(4));

      if (formation >= 0.999 && !stage.classList.contains("is-formed")) {
        stage.classList.add("is-formed");
      }

      if (!shouldRenderHero(heroVisible, heroRect.top, heroRect.bottom, window.innerHeight)) return;

      context.setTransform(dpr, 0, 0, dpr, 0, 0);
      context.clearRect(0, 0, width, height);
      context.globalCompositeOperation = "lighter";

      var scale = Math.min(width, height) * (isSmall ? 0.88 : 0.82);
      var centerX = width * 0.5;
      var centerY = height * (isSmall ? 0.45 : 0.48);

      particles.forEach(function (particle) {
        var base = basePosition(particle, time, scale, centerX, centerY, stages.deform);
        var chaos = chaosPosition(particle, time);
        var gather = particle.kind === "background" ? 1 : formation;
        var formedX = chaos.x + (base.x - chaos.x) * gather;
        var formedY = chaos.y + (base.y - chaos.y) * gather;
        var stream = streamPosition(particle, time);
        var x = formedX + (stream.x - formedX) * stages.burst;
        var y = formedY + (stream.y - formedY) * stages.burst;
        var twinkle = reduceMotion ? 1 : 0.78 + Math.sin(time * particle.twinkleSpeed + particle.twinkleOffset) * 0.22;
        var glyphBoost = particle.kind.indexOf("glyph") === 0
          ? 1.36
          : (particle.kind === "core" ? 1.48 : (particle.kind === "orbit" ? 1.16 : 1));
        var alpha = particle.alpha * twinkle * glyphBoost * (1 - stages.burst * 0.14);
        drawSprite(particle, x, y, particle.size * particle.depth, alpha, stages.burst);
      });

      if (stages.burst < 0.93 && formation > 0.02) {
        var qHead = sampleQPoint((time * 0.05) % 0.88);
        var qParticle = { color: 4, size: 4.6, side: 1 };
        var qBase = basePosition({
          kind: "glyph-q", x: qHead.x, y: qHead.y, depth: 1,
          angle: 0, radius: 0
        }, time, scale, centerX, centerY, stages.deform);
        var headFade = 1 - stages.burst;
        drawSprite(qParticle, qBase.x, qBase.y, 4.6, 0.98 * headFade * formation, 0);
      }

      context.globalAlpha = 1;
      context.globalCompositeOperation = "source-over";
    }

    function scheduleFrame() {
      sideOpacity = measureSideOpacity(elapsedTime * 1000);
      if (!rafId && shouldAnimateScene(heroVisible, sideOpacity, document.hidden, reduceMotion)) {
        rafId = window.requestAnimationFrame(frame);
      }
    }

    function frame(now) {
      rafId = 0;
      sideOpacity = measureSideOpacity(elapsedTime * 1000);
      if (!shouldAnimateScene(heroVisible, sideOpacity, document.hidden, reduceMotion)) return;
      var clock = advanceAnimationClock(elapsedTime, lastTime, now, 0.05);
      elapsedTime = clock.elapsed;
      lastTime = clock.timestamp;
      draw(elapsedTime);
      scheduleFrame();
    }

    stage.addEventListener("pointermove", function (event) {
      pointerTargetX = (event.clientX / Math.max(1, window.innerWidth) - 0.5) * 2;
      pointerTargetY = (event.clientY / Math.max(1, window.innerHeight) - 0.5) * 2;
      scheduleFrame();
    }, { passive: true });

    stage.addEventListener("pointerleave", function () {
      pointerTargetX = 0;
      pointerTargetY = 0;
    });

    window.addEventListener("blur", function () {
      pointerTargetX = 0;
      pointerTargetY = 0;
    });

    window.addEventListener("resize", resize, { passive: true });
    window.addEventListener("scroll", function () {
      if (reduceMotion) draw(elapsedTime);
      else scheduleFrame();
    }, { passive: true });
    document.addEventListener("visibilitychange", function () {
      lastTime = window.performance.now();
      scheduleFrame();
    });

    if ("IntersectionObserver" in window) {
      var visibilityObserver = new window.IntersectionObserver(function (entries) {
        heroVisible = Boolean(entries[0] && entries[0].isIntersecting);
        lastTime = window.performance.now();
        scheduleFrame();
      }, { threshold: 0 });
      visibilityObserver.observe(stage);
    }

    if (gate) {
      if (reduceMotion) {
        gate.classList.add("is-dismissed");
        gate.setAttribute("aria-hidden", "true");
        gate.disabled = true;
      } else {
        gate.addEventListener("click", activateFormation);
      }
    }

    if (motionQuery.addEventListener) motionQuery.addEventListener("change", handleMotionPreferenceChange);
    else if (motionQuery.addListener) motionQuery.addListener(handleMotionPreferenceChange);

    resize();
    if (!reduceMotion) scheduleFrame();
  }

  return {
    clamp01: clamp01,
    smoothstep: smoothstep,
    getHeroProgress: getHeroProgress,
    sampleAPoint: sampleAPoint,
    sampleQPoint: sampleQPoint,
    getMotionStages: getMotionStages,
    shouldAnimate: shouldAnimate,
    getFormationProgress: getFormationProgress,
    getActivatedHeroProgress: getActivatedHeroProgress,
    sampleOrbitPoint: sampleOrbitPoint,
    getSideRailOpacity: getSideRailOpacity,
    getSideRailPosition: getSideRailPosition,
    shouldAnimateScene: shouldAnimateScene,
    shouldRenderHero: shouldRenderHero,
    getParticleCounts: getParticleCounts,
    advanceAnimationClock: advanceAnimationClock,
    nearestSlideIndex: nearestSlideIndex,
    carouselKeyTarget: carouselKeyTarget,
    applyRevealState: applyRevealState,
    init: init
  };
});
