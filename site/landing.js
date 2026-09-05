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
    if (!element || !element.classList) return;
    element.classList.toggle("is-visible", Boolean(isVisible));
  }

  function init(document, window) {
    initNavigation(document, window);
    initHero(document, window);
    initReveal(document, window);
    initCarousel(document, window);
    initLightbox(document, window);
    initBenchmarks(document, window);
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

  /* ═══════════════════════════════════════════════
     滚动动效：优雅升入并持久保留，避免上下翻动忽隐忽现
     ═══════════════════════════════════════════════ */
  function initReveal(document, window) {
    var elements = Array.prototype.slice.call(document.querySelectorAll(".reveal"));
    var reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduceMotion) {
      elements.forEach(function (element) { applyRevealState(element, true); });
      return;
    }

    function checkVisible() {
      var vh = window.innerHeight || 800;
      elements.forEach(function (element) {
        var rect = element.getBoundingClientRect();
        if (rect.top < vh * 0.94 && rect.bottom > 0) {
          applyRevealState(element, true);
        }
      });
    }

    if ("IntersectionObserver" in window) {
      var observer = new window.IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            applyRevealState(entry.target, true);
            observer.unobserve(entry.target);
          }
        });
      }, { threshold: 0.05 });

      elements.forEach(function (element) { observer.observe(element); });
    }

    window.addEventListener("scroll", checkVisible, { passive: true });
    window.addEventListener("resize", checkVisible, { passive: true });
    checkVisible();
    setTimeout(checkVisible, 120);
  }

  /* ═══════════════════════════════════════════════
     横向轮播：与 Astra 胶囊切换组联动
     ═══════════════════════════════════════════════ */
  function initCarousel(document, window) {
    var carousel = document.getElementById("car");
    var dotsBox = document.getElementById("carDots");
    var count = document.getElementById("carCount");
    var status = document.getElementById("carStatus");
    var previous = document.getElementById("carPrev");
    var next = document.getElementById("carNext");
    var phaseTabs = Array.prototype.slice.call(document.querySelectorAll(".tab-pill"));
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

    // 绑定顶部胶囊标签切换组
    phaseTabs.forEach(function (tab) {
      tab.addEventListener("click", function () {
        var targetIndex = parseInt(tab.getAttribute("data-index"), 10);
        if (!isNaN(targetIndex)) goTo(targetIndex);
      });
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
      phaseTabs.forEach(function (tab, tabIndex) {
        var current = tabIndex === activeIndex;
        tab.classList.toggle("active", current);
        tab.setAttribute("aria-selected", current ? "true" : "false");
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

  /* ═══════════════════════════════════════════════
     交互式评测展台：选项卡切换与双向指标卡联动
     ═══════════════════════════════════════════════ */
  function initBenchmarks(document, window) {
    var bstatCards = Array.prototype.slice.call(document.querySelectorAll(".bstat"));
    if (!bstatCards.length) return;

    bstatCards.forEach(function (card) {
      card.addEventListener("mouseenter", function () {
        card.classList.add("is-hovered");
      });
      card.addEventListener("mouseleave", function () {
        card.classList.remove("is-hovered");
      });
    });
  }

  /* ═══════════════════════════════════════════════
     WebGL GPU 点云着色器引擎 (Shader Point Cloud)
     - 60,000+ 粒子 GPU 顶点并行计算
     - 对数螺旋 4 旋臂 + 中心超高密度炽白星核
     - 偏心原点偏移 (Off-Center Pivot Offset)
     - 滚动驱动形态插值 (Logarithmic Spiral -> Cosmic Stream)
     ═══════════════════════════════════════════════ */
  function createShader(gl, type, source) {
    var shader = gl.createShader(type);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      var info = gl.getShaderInfoLog(shader);
      if (typeof console !== "undefined" && console.error) {
        console.error("Shader compile error:", info);
      }
      gl.deleteShader(shader);
      return null;
    }
    return shader;
  }

  function createProgram(gl, vsSource, fsSource) {
    var vs = createShader(gl, gl.VERTEX_SHADER, vsSource);
    var fs = createShader(gl, gl.FRAGMENT_SHADER, fsSource);
    if (!vs || !fs) return null;
    var program = gl.createProgram();
    gl.attachShader(program, vs);
    gl.attachShader(program, fs);
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      var pInfo = gl.getProgramInfoLog(program);
      if (typeof console !== "undefined" && console.error) {
        console.error("Program link error:", pInfo);
      }
      gl.deleteProgram(program);
      return null;
    }
    return program;
  }

  function initWebGLGalaxy(canvas, window) {
    if (!canvas || typeof canvas.getContext !== "function") return null;
    var gl = null;
    try {
      gl = canvas.getContext("webgl", { alpha: false, antialias: false, depth: false }) ||
           canvas.getContext("experimental-webgl", { alpha: false, antialias: false, depth: false });
    } catch (e) {
      return null;
    }
    if (!gl) return null;

    var vsSource = [
      "#ifdef GL_ES",
      "precision mediump float;",
      "#endif",
      "",
      "attribute vec3 aPositionSpiral;",
      "attribute vec3 aPositionStream;",
      "attribute vec3 aColor;",
      "attribute float aSize;",
      "attribute float aPhase;",
      "attribute float aTwinkleSpeed;",
      "",
      "uniform float uTime;",
      "uniform float uMorph;",
      "uniform vec2 uPivotOffset;",
      "uniform vec2 uMouse;",
      "uniform float uDpr;",
      "uniform vec2 uResolution;",
      "",
      "varying vec3 vColor;",
      "varying float vAlpha;",
      "",
      "void main() {",
      "  vColor = aColor;",
      "  float twinkle = 0.80 + sin(uTime * aTwinkleSpeed + aPhase) * 0.20;",
      "  vAlpha = twinkle;",
      "",
      "  // David Greenheck differential rotation",
      "  float distFromCenter = length(aPositionSpiral.xz);",
      "  float rotFactor = 1.0 / (distFromCenter * 2.5 + 0.85);",
      "  float diffAngle = -uTime * 0.048 * rotFactor;",
      "  float cDiff = cos(diffAngle);",
      "  float sDiff = sin(diffAngle);",
      "  vec3 rotatedSpiral = vec3(",
      "    aPositionSpiral.x * cDiff - aPositionSpiral.z * sDiff,",
      "    aPositionSpiral.y,",
      "    aPositionSpiral.x * sDiff + aPositionSpiral.z * cDiff",
      "  );",
      "",
      "  // 自然散落星场：银河平滑散开为全屏深空星海，散开后一以贯之持续作为全局背景",
      "  vec3 pos = mix(rotatedSpiral, aPositionStream, uMorph);",
      "",
      "  // 散开后保持深空缓动自转",
      "  float streamRot = uTime * 0.006 * uMorph;",
      "  float cS = cos(streamRot);",
      "  float sS = sin(streamRot);",
      "  pos.xz = vec2(pos.x * cS - pos.z * sS, pos.x * sS + pos.z * cS);",
      "",
      "  // 3D tilt and mouse parallax",
      "  float angleY = uMouse.x * 0.35 + (1.0 - uMorph) * (uTime * 0.015);",
      "  float angleX = uMouse.y * 0.25 - 0.82;",
      "  float cosY = cos(angleY);",
      "  float sinY = sin(angleY);",
      "  float cosX = cos(angleX);",
      "  float sinX = sin(angleX);",
      "",
      "  float x1 = pos.x * cosY + pos.z * sinY;",
      "  float z1 = -pos.x * sinY + pos.z * cosY;",
      "  float y2 = pos.y * cosX - z1 * sinX;",
      "  float z2 = pos.y * sinX + z1 * cosX;",
      "",
      "  // 视口偏心原点偏移：在相机视角中平移，首屏精准锚定在右下方，绝不随差动自转摆动，绝不重叠左侧文字",
      "  // 当向下滚动时，随粒子散落自然平滑过渡归中",
      "  float pivotFade = 1.0 - smoothstep(0.0, 0.70, uMorph);",
      "  vec3 rotated = vec3(",
      "    x1 + uPivotOffset.x * pivotFade,",
      "    y2 + uPivotOffset.y * pivotFade,",
      "    z2 - 2.15",
      "  );",
      "  float fov = 1.65;",
      "  gl_Position = vec4(rotated.x * fov * (uResolution.y / uResolution.x), rotated.y * fov, rotated.z * 0.5, -rotated.z);",
      "  float distScale = 2.15 / max(0.4, -rotated.z);",
      "  gl_PointSize = clamp(aSize * uDpr * distScale * 1.35, 1.0, 14.0);",
      "}"
    ].join("\n");

    var fsSource = [
      "#ifdef GL_ES",
      "precision mediump float;",
      "#endif",
      "",
      "uniform float uDownstream;",
      "uniform vec2 uResolution;",
      "",
      "varying vec3 vColor;",
      "varying float vAlpha;",
      "",
      "void main() {",
      "  float dist = length(gl_PointCoord - vec2(0.5)) * 2.0;",
      "  if (dist > 1.0) discard;",
      "",
      "  // David Greenheck smooth circular star falloff",
      "  float shape = smoothstep(1.0, 0.0, dist) * smoothstep(1.0, 0.22, dist);",
      "  float core = smoothstep(0.35, 0.0, dist);",
      "  vec3 starColor = mix(vColor, vec3(1.0, 1.0, 1.0), core * 0.75);",
      "",
      "  // Astra downstream soft edge gradient center mask",
      "  float screenX = gl_FragCoord.x / uResolution.x;",
      "  float distFromCenter = abs(screenX - 0.5);",
      "  float railMask = smoothstep(0.18, 0.42, distFromCenter);",
      "  float mask = mix(1.0, railMask, uDownstream);",
      "",
      "  gl_FragColor = vec4(starColor, shape * vAlpha * mask * 0.92);",
      "}"
    ].join("\n");

    var program = createProgram(gl, vsSource, fsSource);
    if (!program) return null;

    var isMobile = (window.innerWidth || 1200) < 768;
    var count = isMobile ? 8500 : 22000;

    var posSpiral = new Float32Array(count * 3);
    var posStream = new Float32Array(count * 3);
    var colors = new Float32Array(count * 3);
    var sizes = new Float32Array(count);
    var phases = new Float32Array(count);
    var twinkleSpeeds = new Float32Array(count);

    function gaussianVal() {
      return (Math.random() + Math.random() + Math.random() - 1.5) / 1.5;
    }

    function mixScalar(a, b, t) {
      return a * (1.0 - t) + b * t;
    }

    var galaxyCount = Math.floor(count * 0.82);

    for (var i = 0; i < count; i++) {
      var sX, sY, sZ;
      var rCol = 1.0, gCol = 1.0, bCol = 1.0;
      var sz = 1.2 + Math.random() * 1.5;

      if (i < galaxyCount) {
        // David Greenheck 2条对称宏伟旋臂 (Grand-Design 2-Arm Logarithmic Spiral)
        var seedNorm = Math.pow(Math.random(), 0.52);
        var maxGalaxyRadius = 0.80;
        var radius = seedNorm * maxGalaxyRadius;

        var isCore = seedNorm < 0.08;
        var isArm = seedNorm >= 0.08 && seedNorm < 0.88;

        if (isCore) {
          var cR = Math.pow(Math.random(), 1.8) * 0.12;
          var cAngle = Math.random() * Math.PI * 2.0;
          sX = Math.cos(cAngle) * cR;
          sZ = Math.sin(cAngle) * cR;
          sY = gaussianVal() * 0.038;
          sz = 2.0 + Math.random() * 2.4;
          rCol = 0.96; gCol = 0.98; bCol = 1.0;
        } else if (isArm) {
          var arm = i % 2; // 严格双旋臂
          var armAngle = arm * Math.PI;
          var spiralAngle = seedNorm * 1.75 * Math.PI * 2.0; // 紧致度 1.75
          var armSpread = gaussianVal() * (0.024 + 0.082 * seedNorm);
          var radialSpread = gaussianVal() * (0.015 + 0.045 * seedNorm);
          var finalR = Math.max(0.018, radius + radialSpread);
          var finalAngle = armAngle + spiralAngle + armSpread / Math.max(0.04, finalR);

          sX = Math.cos(finalAngle) * finalR;
          sZ = Math.sin(finalAngle) * finalR;
          sY = gaussianVal() * (0.018 + 0.032 * (1.0 - seedNorm));
          sz = 1.1 + Math.random() * 1.8;

          // 基于密度的蓝-琥珀渐变色谱 (Greenheck #1885ff -> #ffb28a)
          var radialSparsity = Math.abs(radialSpread) / 0.06;
          var angularSparsity = Math.abs(armSpread) / 0.12;
          var sparsity = Math.min(1.0, (radialSparsity + angularSparsity) * 0.5);
          sparsity = Math.min(1.0, Math.max(0.0, sparsity * 0.72 + seedNorm * 0.35));

          rCol = 0.094 + (1.0 - 0.094) * sparsity;
          gCol = 0.522 + (0.698 - 0.522) * sparsity;
          bCol = 1.0 + (0.541 - 1.0) * sparsity;

          // 核心渐白过渡
          var coreWhiteness = Math.max(0.0, 1.0 - seedNorm * 2.8);
          rCol = mixScalar(rCol, 1.0, coreWhiteness * 0.85);
          gCol = mixScalar(gCol, 1.0, coreWhiteness * 0.85);
          bCol = mixScalar(bCol, 1.0, coreWhiteness * 0.85);
        } else {
          // 旋臂外围稀疏星芒
          var haloAngle = Math.random() * Math.PI * 2.0;
          var haloR = 0.35 + Math.random() * 0.45;
          sX = Math.cos(haloAngle) * haloR + gaussianVal() * 0.08;
          sZ = Math.sin(haloAngle) * haloR + gaussianVal() * 0.08;
          sY = gaussianVal() * 0.07;
          sz = 0.9 + Math.random() * 1.2;
          rCol = 0.65; gCol = 0.82; bCol = 1.0;
        }
      } else {
        // 宇宙深空背景基底星
        sX = (Math.random() - 0.5) * 3.6;
        sY = (Math.random() - 0.5) * 3.4;
        sZ = -1.2 + Math.random() * 2.2;
        sz = 0.8 + Math.random() * 1.3;
        if (Math.random() < 0.65) {
          rCol = 1.0; gCol = 1.0; bCol = 1.0;
        } else if (Math.random() < 0.5) {
          rCol = 1.0; gCol = 0.92; bCol = 0.78;
        } else {
          rCol = 0.75; gCol = 0.90; bCol = 1.0;
        }
      }

      posSpiral[i * 3 + 0] = sX;
      posSpiral[i * 3 + 1] = sY;
      posSpiral[i * 3 + 2] = sZ;

      // 全局深空星海粒子分布：全屏自然散落，滚动时粒子由银河平滑舒展为宇宙深空
      // 正文中央的阅读通道由片元着色器实时线性羽化蒙版 (soft-edge center mask) 保持通透纯黑
      var stX = (Math.random() - 0.5) * 3.8;
      var stY = (Math.random() - 0.5) * 2.8;
      var stZ = -1.1 + Math.random() * 2.2;

      posStream[i * 3 + 0] = stX;
      posStream[i * 3 + 1] = stY;
      posStream[i * 3 + 2] = stZ;

      colors[i * 3 + 0] = rCol;
      colors[i * 3 + 1] = gCol;
      colors[i * 3 + 2] = bCol;

      sizes[i] = sz;
      phases[i] = Math.random() * Math.PI * 2.0;
      twinkleSpeeds[i] = 0.5 + Math.random() * 2.0;
    }

    function bindBuffer(data, usage) {
      var buf = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, buf);
      gl.bufferData(gl.ARRAY_BUFFER, data, usage || gl.STATIC_DRAW);
      return buf;
    }

    var bufSpiral = bindBuffer(posSpiral);
    var bufStream = bindBuffer(posStream);
    var bufColor = bindBuffer(colors);
    var bufSize = bindBuffer(sizes);
    var bufPhase = bindBuffer(phases);
    var bufTwinkle = bindBuffer(twinkleSpeeds);

    var aPositionSpiral = gl.getAttribLocation(program, "aPositionSpiral");
    var aPositionStream = gl.getAttribLocation(program, "aPositionStream");
    var aColor = gl.getAttribLocation(program, "aColor");
    var aSize = gl.getAttribLocation(program, "aSize");
    var aPhase = gl.getAttribLocation(program, "aPhase");
    var aTwinkleSpeed = gl.getAttribLocation(program, "aTwinkleSpeed");

    var uTime = gl.getUniformLocation(program, "uTime");
    var uMorph = gl.getUniformLocation(program, "uMorph");
    var uDownstream = gl.getUniformLocation(program, "uDownstream");
    var uPivotOffset = gl.getUniformLocation(program, "uPivotOffset");
    var uMouse = gl.getUniformLocation(program, "uMouse");
    var uDpr = gl.getUniformLocation(program, "uDpr");
    var uResolution = gl.getUniformLocation(program, "uResolution");

    return {
      resize: function (w, h) {
        gl.viewport(0, 0, w, h);
      },
      render: function (time, morph, downstream, pivotX, pivotY, mouseX, mouseY, width, height, dpr) {
        gl.viewport(0, 0, canvas.width, canvas.height);
        gl.clearColor(0.0, 0.0, 0.0, 1.0);
        gl.clear(gl.COLOR_BUFFER_BIT);

        gl.enable(gl.BLEND);
        gl.blendFunc(gl.SRC_ALPHA, gl.ONE);

        gl.useProgram(program);

        gl.enableVertexAttribArray(aPositionSpiral);
        gl.bindBuffer(gl.ARRAY_BUFFER, bufSpiral);
        gl.vertexAttribPointer(aPositionSpiral, 3, gl.FLOAT, false, 0, 0);

        gl.enableVertexAttribArray(aPositionStream);
        gl.bindBuffer(gl.ARRAY_BUFFER, bufStream);
        gl.vertexAttribPointer(aPositionStream, 3, gl.FLOAT, false, 0, 0);

        gl.enableVertexAttribArray(aColor);
        gl.bindBuffer(gl.ARRAY_BUFFER, bufColor);
        gl.vertexAttribPointer(aColor, 3, gl.FLOAT, false, 0, 0);

        gl.enableVertexAttribArray(aSize);
        gl.bindBuffer(gl.ARRAY_BUFFER, bufSize);
        gl.vertexAttribPointer(aSize, 1, gl.FLOAT, false, 0, 0);

        gl.enableVertexAttribArray(aPhase);
        gl.bindBuffer(gl.ARRAY_BUFFER, bufPhase);
        gl.vertexAttribPointer(aPhase, 1, gl.FLOAT, false, 0, 0);

        gl.enableVertexAttribArray(aTwinkleSpeed);
        gl.bindBuffer(gl.ARRAY_BUFFER, bufTwinkle);
        gl.vertexAttribPointer(aTwinkleSpeed, 1, gl.FLOAT, false, 0, 0);

        gl.uniform1f(uTime, time);
        gl.uniform1f(uMorph, morph);
        gl.uniform1f(uDownstream, downstream);
        gl.uniform2f(uPivotOffset, pivotX, pivotY);
        gl.uniform2f(uMouse, mouseX, mouseY);
        gl.uniform1f(uDpr, dpr);
        gl.uniform2f(uResolution, canvas.width, canvas.height);

        gl.drawArrays(gl.POINTS, 0, count);
      }
    };
  }

  /* ═══════════════════════════════════════════════
     首屏 3D WebGL/Canvas 粒子系统改造
     - “Q 环绕 A” 标志性 3D 点云
     - 鼠标视差旋转与微引力牵引
     - 滚动驱动：流动变形 -> 两侧炸开 -> 侧轨微动
     ═══════════════════════════════════════════════ */
  function initHero(document, window) {
    var motionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    var reduceMotion = motionQuery.matches;
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
    var webglEngine = sideCanvas ? initWebGLGalaxy(sideCanvas, window) : null;
    var sideContext = (!webglEngine && sideCanvas && sideCanvas.getContext) ? sideCanvas.getContext("2d") : null;

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
    var pointerClientX = -9999;
    var pointerClientY = -9999;
    var heroVisible = true;
    var rafId = 0;
    var lastTime = window.performance.now();
    var elapsedTime = 0;
    var formationDuration = 2000;
    // 开屏即呈现成型的 3D 旋转银河（Astra 视觉对标），无需等待或点击
    var formationStartedAt = -formationDuration;
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
        z: options.z || (gaussian() * 0.08),
        size: options.size || randomBetween(0.85, 2.4),
        color: options.color == null ? Math.floor(Math.random() * sprites.length) : options.color,
        alpha: options.alpha || randomBetween(0.45, 0.88),
        twinkleOffset: randomBetween(0, Math.PI * 2),
        twinkleSpeed: randomBetween(0.6, 2.0),
        side: options.side || (Math.random() < 0.5 ? -1 : 1),
        streamX: Math.random(),
        streamY: Math.random(),
        streamSpeed: randomBetween(0.02, 0.08),
        depth: options.depth || randomBetween(0.4, 1.1),
        angle: options.angle || 0,
        radius: options.radius || 0,
        arm: options.arm || 0,
        ring: options.ring || 0,
        drift: randomBetween(0.4, 1.2),
        chaosX: Math.random() - 0.5,
        chaosY: Math.random() - 0.5,
        cosmosX: Math.random() - 0.5,
        cosmosY: Math.random() - 0.5,
        chaosPhase: randomBetween(0, Math.PI * 2),
        chaosSpeed: randomBetween(0.12, 0.38)
      };
    }

    function buildParticles() {
      particles = [];
      var counts = getParticleCounts(width, height, isSmall);
      var index;

      // 1. 全局深空微星背景 (Deep Cosmic Field) - 保持纯黑深邃，不喧宾夺主
      for (index = 0; index < counts.background; index += 1) {
        particles.push(makeParticle("background", {
          x: Math.random() - 0.5,
          y: Math.random() - 0.5
        }, {
          z: randomBetween(-0.5, 0.5),
          size: randomBetween(0.45, 1.05),
          alpha: randomBetween(0.12, 0.42),
          depth: randomBetween(0.2, 0.6),
          color: Math.random() < 0.7 ? 1 : (Math.random() < 0.5 ? 0 : 4)
        }));
      }

      // 2. 真实天体物理螺旋星系模型 (Logarithmic Spiral Arms + Galactic Disk) - 严格对标 OpenAI Astra
      var spiralGroups = [
        { count: counts.nebula, kind: "nebula" },
        { count: counts.orbit, kind: "orbit" },
        { count: counts.glyphA, kind: "glyph-a" },
        { count: counts.glyphQ, kind: "glyph-q" }
      ];

      var numArms = 4; // 2 对称主旋臂 + 2 次级星流
      spiralGroups.forEach(function (group) {
        for (var i = 0; i < group.count; i += 1) {
          var isDiskStar = Math.random() < 0.28; // 28% 为银盘弥散恒星，增加银河整体立体感
          var arm = i % numArms;
          var t = Math.pow(Math.random(), 0.95);
          var r = 0.03 + 0.36 * t;

          var finalAngle, finalR, diskZ;
          if (isDiskStar) {
            finalAngle = Math.random() * Math.PI * 2;
            finalR = 0.02 + 0.35 * Math.pow(Math.random(), 1.35);
            diskZ = gaussian() * (0.018 + 0.035 * (finalR / 0.35));
          } else {
            var winding = 3.8;
            var baseAngle = (arm * Math.PI * 2 / numArms) + Math.pow(t, 0.70) * winding;
            var armWidth = 0.028 + 0.075 * t;
            var armDispersion = gaussian() * armWidth;
            var radialDispersion = gaussian() * (0.012 + 0.032 * t);

            finalR = Math.max(0.02, r + radialDispersion);
            finalAngle = baseAngle + armDispersion / Math.max(0.04, finalR);
            diskZ = gaussian() * (0.015 + 0.04 * t);
          }

          var starColor = 1;
          var colorRand = Math.random();
          if (finalR < 0.09) {
            starColor = colorRand < 0.65 ? 1 : 4; // 耀白与星核金尘
          } else if (finalR < 0.24) {
            starColor = colorRand < 0.5 ? 0 : (colorRand < 0.78 ? 1 : 4); // 天青蓝与纯白
          } else {
            starColor = colorRand < 0.48 ? 0 : (colorRand < 0.74 ? 2 : (colorRand < 0.88 ? 3 : 1)); // 天青、靛紫、极光青绿
          }

          var starSize = randomBetween(0.85, 2.2);
          if (Math.random() < 0.09) starSize *= 1.85;

          particles.push(makeParticle(group.kind, {
            x: Math.cos(finalAngle) * finalR,
            y: Math.sin(finalAngle) * finalR * 0.48
          }, {
            z: diskZ,
            angle: finalAngle,
            radius: finalR,
            arm: arm,
            side: Math.cos(finalAngle) < 0 ? -1 : 1,
            size: starSize,
            color: starColor,
            alpha: randomBetween(0.55, 0.98),
            depth: randomBetween(0.8, 1.3),
            drift: 1.0 / (Math.sqrt(finalR) + 0.22)
          }));
        }
      });

      // 3. 耀白发光银核 (Dense Luminous Core) - Astra 中心璀璨聚光核
      for (index = 0; index < counts.core; index += 1) {
        var coreR = Math.pow(Math.random(), 2.4) * 0.075;
        var coreAngle = Math.random() * Math.PI * 2;
        var coreZ = gaussian() * 0.025;
        particles.push(makeParticle("core", {
          x: Math.cos(coreAngle) * coreR,
          y: Math.sin(coreAngle) * coreR * 0.52
        }, {
          z: coreZ,
          angle: coreAngle,
          radius: coreR,
          side: Math.cos(coreAngle) < 0 ? -1 : 1,
          size: randomBetween(1.5, 3.6) * (Math.random() < 0.35 ? 1.6 : 1),
          color: Math.random() < 0.8 ? 1 : 4,
          alpha: randomBetween(0.92, 1.0),
          depth: randomBetween(0.95, 1.35),
          drift: 2.2
        }));
      }

      buildSideParticles();
    }

    /* ═══════════════════════════════════════════════
       Astra 物理恒星色温系统
       - 18% 冰蓝/深空青 (#A4C8FD, #CBE3FB)
       - 12% 暖金/琥珀色 (#FFE0B2, #FFCC80)
       - 70% 冷白/微灰 (#E8F1FA, #B4C6DA)
       ═══════════════════════════════════════════════ */
    var CELESTIAL_PALETTE = [
      { r: 164, g: 200, b: 253, hex: "#A4C8FD" }, // 0: 冰蓝 (#A4C8FD)
      { r: 203, g: 227, b: 251, hex: "#CBE3FB" }, // 1: 深空青 (#CBE3FB)
      { r: 255, g: 224, b: 178, hex: "#FFE0B2" }, // 2: 暖金 (#FFE0B2)
      { r: 255, g: 204, b: 128, hex: "#FFCC80" }, // 3: 暖琥珀 (#FFCC80)
      { r: 232, g: 241, b: 250, hex: "#E8F1FA" }, // 4: 冷钻白
      { r: 180, g: 198, b: 218, hex: "#B4C6DA" }  // 5: 深空微灰
    ];

    function buildSideParticles() {
      sideParticles = [];
      var totalStars = isSmall ? 140 : 250;

      // 6 颗带十字衍射星芒的物理焦点恒星（Alpha Stars）
      var alphas = [
        { x: 0.50, y: 0.08, color: 1, size: 2.8, spikeLen: 48 }, // 顶部深空青主星
        { x: 0.15, y: 0.28, color: 2, size: 3.0, spikeLen: 48 }, // 左侧暖金焦点星 (#FFE0B2)
        { x: 0.78, y: 0.32, color: 0, size: 2.8, spikeLen: 44 }, // 右侧冰蓝巨星 (#A4C8FD)
        { x: 0.85, y: 0.78, color: 3, size: 2.9, spikeLen: 46 }, // 右下暖琥珀焦点星 (#FFCC80)
        { x: 0.20, y: 0.76, color: 0, size: 2.5, spikeLen: 40 }, // 左下冰蓝亮星
        { x: 0.44, y: 0.90, color: 2, size: 2.6, spikeLen: 42 }  // 底部暖金微星
      ];

      alphas.forEach(function (a, idx) {
        sideParticles.push({
          isAlpha: true,
          tier: 0,
          xSeed: a.x,
          ySeed: a.y,
          size: a.size,
          spikeLen: a.spikeLen,
          color: a.color,
          alpha: 0.96,
          phase: idx * 1.5,
          twinkleSpeed: 0.7,
          speed: 0.008,
          parallax: 0.2
        });
      });

      // 6 个疏散星团聚散中心（Clusters）+ 宇宙空洞（Voids）
      var clusters = [
        { x: 0.20, y: 0.20, sigma: 0.08 },
        { x: 0.80, y: 0.22, sigma: 0.09 },
        { x: 0.35, y: 0.58, sigma: 0.09 },
        { x: 0.82, y: 0.65, sigma: 0.08 },
        { x: 0.16, y: 0.72, sigma: 0.09 },
        { x: 0.54, y: 0.16, sigma: 0.07 }
      ];

      var remaining = totalStars - alphas.length;
      for (var index = 0; index < remaining; index += 1) {
        var isCluster = Math.random() < 0.68;
        var x, y;
        if (isCluster) {
          var c = clusters[Math.floor(Math.random() * clusters.length)];
          x = c.x + gaussian() * c.sigma;
          y = c.y + gaussian() * c.sigma;
        } else {
          x = Math.random();
          y = Math.random();
        }
        x = Math.max(0.01, Math.min(0.99, x));
        y = Math.max(0.01, Math.min(0.99, y));

        // 严格遵循物理恒星色温比例：
        // 12% 暖金/琥珀色，18% 冰蓝/深空青，70% 冷白/微灰
        var rand = Math.random();
        var tier, size, colorIdx, baseAlpha;
        if (rand < 0.12) {
          // 12% 暖金/琥珀色 (#FFE0B2, #FFCC80)
          colorIdx = Math.random() < 0.5 ? 2 : 3;
          size = randomBetween(1.8, 2.5);
          baseAlpha = randomBetween(0.85, 0.98);
          tier = 1;
        } else if (rand < 0.30) {
          // 18% 冰蓝/深空青 (#A4C8FD, #CBE3FB)
          colorIdx = Math.random() < 0.5 ? 0 : 1;
          size = randomBetween(1.4, 2.1);
          baseAlpha = randomBetween(0.70, 0.90);
          tier = 1;
        } else {
          // 70% 冷白/微灰 (远景微弱恒星与星尘，低 opacity 0.3 ~ 0.6)
          colorIdx = Math.random() < 0.6 ? 5 : 4;
          size = randomBetween(0.55, 1.15);
          baseAlpha = randomBetween(0.30, 0.60);
          tier = 2;
        }

        sideParticles.push({
          isAlpha: false,
          tier: tier,
          xSeed: x,
          ySeed: y,
          size: size,
          color: colorIdx,
          alpha: baseAlpha,
          phase: Math.random() * Math.PI * 2,
          twinkleSpeed: randomBetween(0.5, 1.4),
          speed: randomBetween(0.005, 0.02),
          parallax: randomBetween(0.12, 0.45)
        });
      }
    }

    function createSprites(ownerDocument) {
      // 银河核心粒子黑体色板精灵
      var specs = [
        { core: "rgba(255,255,255,1)", mid: "rgba(210,234,255,0.85)", edge: "rgba(180,215,255,0)" }, // 0: 冰蓝
        { core: "rgba(255,255,255,1)", mid: "rgba(252,253,255,0.92)", edge: "rgba(230,240,255,0)" }, // 1: 纯耀白
        { core: "rgba(255,255,255,1)", mid: "rgba(255,247,232,0.88)", edge: "rgba(255,235,200,0)" }, // 2: 暖象牙
        { core: "rgba(255,255,255,1)", mid: "rgba(255,230,198,0.85)", edge: "rgba(255,210,160,0)" }, // 3: 柔暖金
        { core: "rgba(235,240,248,0.9)", mid: "rgba(195,210,225,0.6)", edge: "rgba(170,185,205,0)" }  // 4: 深空淡灰
      ];

      return specs.map(function (spec) {
        var sprite = ownerDocument.createElement("canvas");
        sprite.width = 64;
        sprite.height = 64;
        var sc = sprite.getContext("2d");
        var cx = 32, cy = 32;

        var glow = sc.createRadialGradient(cx, cy, 0, cx, cy, 30);
        glow.addColorStop(0, spec.core);
        glow.addColorStop(0.18, spec.mid);
        glow.addColorStop(0.55, spec.edge);
        glow.addColorStop(1, "rgba(0,0,0,0)");
        sc.fillStyle = glow;
        sc.fillRect(0, 0, 64, 64);
        return sprite;
      });
    }

    function resize() {
      var nextSmall = window.innerWidth < 720;
      isSmall = nextSmall;
      dpr = Math.min(window.devicePixelRatio || 1, 1.5);
      width = Math.max(1, stage.clientWidth);
      height = Math.max(1, stage.clientHeight);
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      canvas.style.width = width + "px";
      canvas.style.height = height + "px";
      if (sideCanvas) {
        sideCanvas.width = Math.round(window.innerWidth * dpr);
        sideCanvas.height = Math.round(window.innerHeight * dpr);
        sideCanvas.style.width = window.innerWidth + "px";
        sideCanvas.style.height = window.innerHeight + "px";
        if (webglEngine) {
          webglEngine.resize(sideCanvas.width, sideCanvas.height);
        }
      }
      buildParticles();
      draw(elapsedTime);
    }

    /* 3D 旋转与透视投影计算 */
    function basePosition(particle, time, scale, centerX, centerY, deform) {
      var x = particle.x;
      var y = particle.y;
      var z = particle.z || 0;

      if (particle.kind === "background") {
        return {
          x: (particle.x + 0.5) * width - pointerX * 32 * particle.depth,
          y: (particle.y + 0.5) * height - pointerY * 24 * particle.depth,
          z: z
        };
      }

      // 螺旋星系差异旋转与形态演进
      var rotSpeed = 0.032 * (particle.drift || 1.0);
      var currentAngle = particle.angle + time * rotSpeed;
      var currentR = particle.radius;

      // 滚动驱动：向外自然扩散融入背景
      var expandR = currentR * (1 + deform * 0.4);
      x = Math.cos(currentAngle) * expandR;
      y = Math.sin(currentAngle) * expandR * (0.46 - deform * 0.06);
      z = (particle.z || 0) + Math.sin(currentAngle * 2) * 0.04;

      // 3D 视角旋转（天然 Galaxy 3D 倾角 ~24度 + 鼠标微视差驱动 Pitch & Yaw）
      var rotY = pointerX * 0.32 + time * 0.007;
      var rotX = -0.38 - pointerY * 0.2;
      var cosY = Math.cos(rotY);
      var sinY = Math.sin(rotY);
      var cosX = Math.cos(rotX);
      var sinX = Math.sin(rotX);

      var x1 = x * cosY + z * sinY;
      var z1 = -x * sinY + z * cosY;
      var y2 = y * cosX - z1 * sinX;
      var z2 = y * sinX + z1 * cosX;

      // 透视投影
      var cameraDist = 2.3;
      var perspective = cameraDist / (cameraDist + z2);

      var stretchX = 1 + deform * 0.6;
      var squashY = 1 - deform * 0.3;

      var projX = centerX + x1 * scale * perspective * stretchX;
      var projY = centerY + y2 * scale * perspective * squashY;

      // 鼠标微引力牵引 (Gravitational Lensing)
      if (pointerClientX > 0 && pointerClientY > 0) {
        var dx = pointerClientX - projX;
        var dy = pointerClientY - projY;
        var dist = Math.sqrt(dx * dx + dy * dy);
        var pullRange = 180;
        if (dist < pullRange && dist > 1) {
          var pullFactor = (1 - dist / pullRange) * 16 * particle.depth;
          projX += (dx / dist) * pullFactor;
          projY += (dy / dist) * pullFactor;
        }
      }

      return {
        x: projX,
        y: projY,
        z: z2
      };
    }

    function chaosPosition(particle, time) {
      var wobble = Math.min(width, height) * (0.015 + 0.02 * particle.depth);
      return {
        x: (particle.chaosX + 0.5) * width
          + Math.sin(time * particle.chaosSpeed + particle.chaosPhase) * wobble
          + pointerX * 16 * particle.depth,
        y: (particle.chaosY + 0.5) * height
          + Math.cos(time * particle.chaosSpeed * 0.82 + particle.chaosPhase) * wobble
          + pointerY * 12 * particle.depth
      };
    }

    function streamPosition(particle, time) {
      var spreadX = ((particle.cosmosX + 0.5 + time * 0.005) % 1.0 + 1.0) % 1.0;
      var spreadY = ((particle.cosmosY + 0.5 + time * 0.003) % 1.0 + 1.0) % 1.0;
      return {
        x: spreadX * width,
        y: spreadY * height
      };
    }

    /* 纯净星空绘制：彻底去除引起画面分层感和锯齿感的 fillRect 横纵扫描杂线 */
    function drawSprite(particle, x, y, size, alpha, burst) {
      context.globalAlpha = Math.max(0, Math.min(1, alpha));
      var diameter = size * (isSmall ? 4.8 : 5.8);
      context.drawImage(sprites[particle.color], x - diameter / 2, y - diameter / 2, diameter, diameter);
    }

    /* 贯通全站的深空星海：Astra 物理质感、十字衍射星芒与黑体辐射色温 */
    function drawSideField(time, opacity, rawProgress, runwayProgress) {
      if (!sideCanvas) return;
      if (webglEngine) {
        var isDesktop = window.innerWidth >= 960;
        var isWide = window.innerWidth >= 1400;
        var pivotX = isDesktop ? (isWide ? 0.76 : 0.66) : 0.0;
        var pivotY = isDesktop ? (isWide ? -0.18 : -0.14) : -0.06;
        var morph = smoothstep(0.06, 0.80, (rawProgress || 0) * 0.55 + (runwayProgress || 0) * 0.65);

        var scrollY = window.scrollY || 0;
        var heroH = hero ? hero.offsetHeight : (window.innerHeight || 800);
        var downstream = clamp01((scrollY - heroH * 0.20) / (heroH * 0.60));

        webglEngine.render(time, morph, downstream, pivotX, pivotY, pointerX, pointerY, window.innerWidth, window.innerHeight, dpr);
        return;
      }
      if (!sideContext) return;
      sideCanvas.style.opacity = "1";
      sideContext.setTransform(dpr, 0, 0, dpr, 0, 0);
      var w = window.innerWidth;
      var h = window.innerHeight;
      sideContext.clearRect(0, 0, w, h);

      sideContext.globalCompositeOperation = "lighter";
      var scrollOffset = window.scrollY || 0;

      sideParticles.forEach(function (star) {
        var pal = CELESTIAL_PALETTE[star.color] || CELESTIAL_PALETTE[1];
        var twinkle = reduceMotion ? 1 : 0.82 + Math.sin(time * (star.twinkleSpeed || 0.8) + star.phase) * 0.18;
        var a = star.alpha * twinkle;

        // 视差滚动与有机空间位置
        var x = star.xSeed * w;
        var y = ((star.ySeed * h - scrollOffset * star.parallax * 0.22) % h + h) % h;

        if (star.isAlpha) {
          // 1. 望远镜经典 4 翼十字衍射星芒 (Cross Diffraction Spikes)
          var spikeLen = star.spikeLen * (isSmall ? 0.75 : 1.0);

          // 水平衍射十字芒
          var hGrad = sideContext.createLinearGradient(x - spikeLen, y, x + spikeLen, y);
          hGrad.addColorStop(0, "rgba(" + pal.r + "," + pal.g + "," + pal.b + ",0)");
          hGrad.addColorStop(0.42, "rgba(255,255,255," + (0.28 * a) + ")");
          hGrad.addColorStop(0.5, "rgba(255,255,255," + (0.95 * a) + ")");
          hGrad.addColorStop(0.58, "rgba(255,255,255," + (0.28 * a) + ")");
          hGrad.addColorStop(1, "rgba(" + pal.r + "," + pal.g + "," + pal.b + ",0)");
          sideContext.fillStyle = hGrad;
          sideContext.fillRect(x - spikeLen, y - 0.75, spikeLen * 2, 1.5);

          // 垂直衍射十字芒
          var vGrad = sideContext.createLinearGradient(x, y - spikeLen, x, y + spikeLen);
          vGrad.addColorStop(0, "rgba(" + pal.r + "," + pal.g + "," + pal.b + ",0)");
          vGrad.addColorStop(0.42, "rgba(255,255,255," + (0.28 * a) + ")");
          vGrad.addColorStop(0.5, "rgba(255,255,255," + (0.95 * a) + ")");
          vGrad.addColorStop(0.58, "rgba(255,255,255," + (0.28 * a) + ")");
          vGrad.addColorStop(1, "rgba(" + pal.r + "," + pal.g + "," + pal.b + ",0)");
          sideContext.fillStyle = vGrad;
          sideContext.fillRect(x - 0.75, y - spikeLen, 1.5, spikeLen * 2);

          // 2. 柔和高斯光晕 (Radial Bloom Halo)
          var haloR = star.size * 16;
          var haloGrad = sideContext.createRadialGradient(x, y, 0, x, y, haloR);
          haloGrad.addColorStop(0, "rgba(255,255,255," + (0.9 * a) + ")");
          haloGrad.addColorStop(0.12, "rgba(" + pal.r + "," + pal.g + "," + pal.b + "," + (0.45 * a) + ")");
          haloGrad.addColorStop(0.48, "rgba(" + pal.r + "," + pal.g + "," + pal.b + "," + (0.12 * a) + ")");
          haloGrad.addColorStop(1, "rgba(" + pal.r + "," + pal.g + "," + pal.b + ",0)");
          sideContext.fillStyle = haloGrad;
          sideContext.beginPath();
          sideContext.arc(x, y, haloR, 0, Math.PI * 2);
          sideContext.fill();

          // 3. 钻石亮核
          sideContext.fillStyle = "rgba(255,255,255," + a + ")";
          sideContext.beginPath();
          sideContext.arc(x, y, star.size, 0, Math.PI * 2);
          sideContext.fill();

        } else if (star.tier === 1) {
          // 主要恒星：柔和羽化光晕 + 亮核
          var rBloom = star.size * 7;
          var g = sideContext.createRadialGradient(x, y, 0, x, y, rBloom);
          g.addColorStop(0, "rgba(255,255,255," + (0.95 * a) + ")");
          g.addColorStop(0.2, "rgba(" + pal.r + "," + pal.g + "," + pal.b + "," + (0.4 * a) + ")");
          g.addColorStop(0.55, "rgba(" + pal.r + "," + pal.g + "," + pal.b + "," + (0.08 * a) + ")");
          g.addColorStop(1, "rgba(" + pal.r + "," + pal.g + "," + pal.b + ",0)");
          sideContext.fillStyle = g;
          sideContext.beginPath();
          sideContext.arc(x, y, rBloom, 0, Math.PI * 2);
          sideContext.fill();

          sideContext.fillStyle = "rgba(255,255,255," + a + ")";
          sideContext.beginPath();
          sideContext.arc(x, y, star.size * 0.9, 0, Math.PI * 2);
          sideContext.fill();

        } else {
          // 中等与深空微星：羽化软碟，绝无生硬实心圆点
          var rSoft = star.size * 2.4;
          var g2 = sideContext.createRadialGradient(x, y, 0, x, y, rSoft);
          g2.addColorStop(0, "rgba(" + pal.r + "," + pal.g + "," + pal.b + "," + a + ")");
          g2.addColorStop(0.4, "rgba(" + pal.r + "," + pal.g + "," + pal.b + "," + (0.4 * a) + ")");
          g2.addColorStop(1, "rgba(" + pal.r + "," + pal.g + "," + pal.b + ",0)");
          sideContext.fillStyle = g2;
          sideContext.beginPath();
          sideContext.arc(x, y, rSoft, 0, Math.PI * 2);
          sideContext.fill();
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
      if (reduceMotion || stage.classList.contains("is-formed")) return;
      formationStartedAt = elapsedTime * 1000 - formationDuration;
      if (gate) {
        gate.classList.add("is-dismissed");
        gate.setAttribute("aria-hidden", "true");
        gate.disabled = true;
      }
      stage.classList.add("is-formed");
      scheduleFrame();
    }

    function handleMotionPreferenceChange(event) {
      reduceMotion = event.matches;
      lastTime = window.performance.now();
      if (reduceMotion) {
        if (rafId) window.cancelAnimationFrame(rafId);
        rafId = 0;
        formationStartedAt = 0;
      } else {
        scheduleFrame();
      }
      if (gate) {
        gate.classList.add("is-dismissed");
        gate.setAttribute("aria-hidden", "true");
        gate.disabled = true;
      }
      stage.classList.add("is-formed");
      draw(elapsedTime);
    }

    function draw(animationTime) {
      var heroRect = hero.getBoundingClientRect();
      var rawProgress = getHeroProgress(heroRect.top, heroRect.height, window.innerHeight);
      var activatedProgress = getActivatedHeroProgress(
        rawProgress,
        formationStartedAt,
        animationTime * 1000,
        formationDuration,
        reduceMotion
      );
      var progress = activatedProgress;
      var stages = getMotionStages(progress);
      var formation = getFormationProgress(formationStartedAt, animationTime * 1000, formationDuration, reduceMotion);

      pointerX += (pointerTargetX - pointerX) * 0.055;
      pointerY += (pointerTargetY - pointerY) * 0.055;

      var runway = document.getElementById("narrativeRunway");
      var banner = document.getElementById("narrativeBanner");
      var runwayProgress = 0;
      if (runway) {
        var rRect = runway.getBoundingClientRect();
        runwayProgress = clamp01(-rRect.top / Math.max(1, rRect.height - window.innerHeight));
        var quoteOpacity = 0;
        var quoteScale = 0.95;
        var quoteY = 24;
        if (runwayProgress >= 0.15 && runwayProgress <= 0.85) {
          if (runwayProgress < 0.45) {
            var t = (runwayProgress - 0.15) / 0.30;
            quoteOpacity = smoothstep(0, 1, t);
            quoteScale = 0.95 + 0.05 * t;
            quoteY = 24 * (1 - t);
          } else if (runwayProgress < 0.65) {
            quoteOpacity = 1;
            quoteScale = 1.0;
            quoteY = 0;
          } else {
            var t = (runwayProgress - 0.65) / 0.20;
            quoteOpacity = 1 - smoothstep(0, 1, t);
            quoteScale = 1.0 + 0.04 * t;
            quoteY = -24 * t;
          }
        }
        if (banner) {
          banner.style.setProperty("--narrative-opacity", quoteOpacity.toFixed(3));
          banner.style.setProperty("--narrative-scale", quoteScale.toFixed(3));
          banner.style.setProperty("--narrative-y", quoteY.toFixed(1) + "px");
        }
      }

      sideOpacity = measureSideOpacity(animationTime * 1000);
      drawSideField(animationTime, sideOpacity, rawProgress, runwayProgress);

      stage.style.setProperty("--hero-progress", progress.toFixed(4));
      var copyAlpha = stages.copyOpacity * (0.18 + formation * 0.82);
      stage.style.setProperty("--hero-copy-opacity", copyAlpha.toFixed(4));
      stage.style.setProperty("--hero-copy-scale", (1 - stages.deform * 0.06).toFixed(4));
      stage.style.setProperty("--hero-copy-y", (-stages.deform * 36).toFixed(1) + "px");
      stage.style.setProperty("--hero-copy-pointer", copyAlpha < 0.12 ? "none" : "auto");

      if (formation >= 0.999 && !stage.classList.contains("is-formed")) {
        stage.classList.add("is-formed");
      }

      if (!shouldRenderHero(heroVisible, heroRect.top, heroRect.bottom, window.innerHeight)) return;

      context.setTransform(dpr, 0, 0, dpr, 0, 0);
      context.clearRect(0, 0, width, height);
      context.globalCompositeOperation = "lighter";

      // 银河定位：位于首屏居中视觉焦点，宏大壮丽，与两侧文字保留宽裕呼吸空间
      var scale = Math.min(width, height) * (isSmall ? 0.76 : 0.70);
      var centerX = width * 0.5;
      var centerY = height * (isSmall ? 0.48 : 0.50);

      particles.forEach(function (particle) {
        var base = basePosition(particle, animationTime, scale, centerX, centerY, stages.deform);
        var chaos = chaosPosition(particle, animationTime);
        var gather = particle.kind === "background" ? 1 : formation;
        var formedX = chaos.x + (base.x - chaos.x) * gather;
        var formedY = chaos.y + (base.y - chaos.y) * gather;

        // 下滚时星系自然微扩并渐隐融入全局 Astra 星空，绝无爆散杂乱噪点
        var burstAngle = Math.atan2(formedY - centerY, formedX - centerX);
        var burstDist = Math.sqrt((formedX - centerX) * (formedX - centerX) + (formedY - centerY) * (formedY - centerY));
        var x = formedX + Math.cos(burstAngle) * burstDist * stages.burst * 0.45;
        var y = formedY + Math.sin(burstAngle) * burstDist * stages.burst * 0.45;

        var twinkle = reduceMotion ? 1 : 0.78 + Math.sin(animationTime * particle.twinkleSpeed + particle.twinkleOffset) * 0.22;
        var glyphBoost = particle.kind.indexOf("glyph") === 0
          ? 1.2
          : (particle.kind === "core" ? 1.5 : (particle.kind === "orbit" ? 1.15 : 1));
        var fadeOut = Math.max(0, 1 - stages.burst * 1.35);
        var alpha = particle.alpha * twinkle * glyphBoost * fadeOut;
        drawSprite(particle, x, y, particle.size * particle.depth, alpha, stages.burst);
      });

      // 旋臂内侧明亮穿梭恒星
      if (stages.burst < 0.93 && formation > 0.02) {
        var orbitAngle = (animationTime * 0.14) % (Math.PI * 2);
        var orbitR = 0.2;
        var leadParticle = { color: 1, size: 4.2, side: 1 };
        var leadBase = basePosition({
          kind: "nebula", x: Math.cos(orbitAngle) * orbitR, y: Math.sin(orbitAngle) * orbitR,
          depth: 1.1, angle: orbitAngle, radius: orbitR, z: 0.05, drift: 1.6
        }, animationTime, scale, centerX, centerY, stages.deform);
        var headFade = 1 - stages.burst;
        drawSprite(leadParticle, leadBase.x, leadBase.y, 4.2, 0.98 * headFade * formation, 0);
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
      pointerClientX = event.clientX;
      pointerClientY = event.clientY;
      scheduleFrame();
    }, { passive: true });

    stage.addEventListener("pointerleave", function () {
      pointerTargetX = 0;
      pointerTargetY = 0;
      pointerClientX = -9999;
      pointerClientY = -9999;
    });

    window.addEventListener("blur", function () {
      pointerTargetX = 0;
      pointerTargetY = 0;
      pointerClientX = -9999;
      pointerClientY = -9999;
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
    if (!reduceMotion) {
      activateFormation();
      scheduleFrame();
    }
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
