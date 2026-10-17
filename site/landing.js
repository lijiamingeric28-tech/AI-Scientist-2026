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
    var bstatCards = Array.prototype.slice.call(document.querySelectorAll(".bstat, .rigor-card"));
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

  /* ═══════════════════════════════════════════════
     四元数与 3D 矩阵数学工具集 (Virtual Arcball / Trackball Math)
     ═══════════════════════════════════════════════ */
  function quatIdentity() {
    return [1, 0, 0, 0];
  }

  function quatNormalize(q) {
    var len = Math.sqrt(q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3]);
    if (len > 0.000001) {
      var inv = 1 / len;
      q[0] *= inv; q[1] *= inv; q[2] *= inv; q[3] *= inv;
    } else {
      q[0] = 1; q[1] = 0; q[2] = 0; q[3] = 0;
    }
    return q;
  }

  function quatMultiply(out, a, b) {
    var aw = a[0], ax = a[1], ay = a[2], az = a[3];
    var bw = b[0], bx = b[1], by = b[2], bz = b[3];
    out[0] = aw * bw - ax * bx - ay * by - az * bz;
    out[1] = aw * bx + ax * bw + ay * bz - az * by;
    out[2] = aw * by - ax * bz + ay * bw + az * bx;
    out[3] = aw * bz + ax * by - ay * bx + az * bw;
    return quatNormalize(out);
  }

  function quatFromAxisAngle(out, axisX, axisY, axisZ, angleRad) {
    var half = angleRad * 0.5;
    var s = Math.sin(half);
    var len = Math.sqrt(axisX * axisX + axisY * axisY + axisZ * axisZ);
    if (len > 0.00001) {
      axisX /= len; axisY /= len; axisZ /= len;
    }
    out[0] = Math.cos(half);
    out[1] = axisX * s;
    out[2] = axisY * s;
    out[3] = axisZ * s;
    return out;
  }

  function quatSlerp(out, a, b, t) {
    var aw = a[0], ax = a[1], ay = a[2], az = a[3];
    var bw = b[0], bx = b[1], by = b[2], bz = b[3];
    var cosHalfTheta = aw * bw + ax * bx + ay * by + az * bz;
    if (cosHalfTheta < 0) {
      bw = -bw; bx = -bx; by = -by; bz = -bz;
      cosHalfTheta = -cosHalfTheta;
    }
    if (cosHalfTheta >= 0.9995) {
      out[0] = aw + t * (bw - aw);
      out[1] = ax + t * (bx - ax);
      out[2] = ay + t * (by - ay);
      out[3] = az + t * (bz - az);
      return quatNormalize(out);
    }
    var halfTheta = Math.acos(cosHalfTheta);
    var sinHalfTheta = Math.sqrt(1.0 - cosHalfTheta * cosHalfTheta);
    var ratioA = Math.sin((1 - t) * halfTheta) / sinHalfTheta;
    var ratioB = Math.sin(t * halfTheta) / sinHalfTheta;
    out[0] = aw * ratioA + bw * ratioB;
    out[1] = ax * ratioA + bx * ratioB;
    out[2] = ay * ratioA + by * ratioB;
    out[3] = az * ratioA + bz * ratioB;
    return quatNormalize(out);
  }

  function quatToMat3(out, q) {
    var w = q[0], x = q[1], y = q[2], z = q[3];
    var x2 = x + x, y2 = y + y, z2 = z + z;
    var xx = x * x2, xy = x * y2, xz = x * z2;
    var yy = y * y2, yz = y * z2, zz = z * z2;
    var wx = w * x2, wy = w * y2, wz = w * z2;

    out[0] = 1 - (yy + zz);
    out[1] = xy + wz;
    out[2] = xz - wy;

    out[3] = xy - wz;
    out[4] = 1 - (xx + zz);
    out[5] = yz + wx;

    out[6] = xz + wy;
    out[7] = yz - wx;
    out[8] = 1 - (xx + yy);
    return out;
  }

  function mat3Multiply(out, a, b) {
    var a00 = a[0], a01 = a[1], a02 = a[2];
    var a10 = a[3], a11 = a[4], a12 = a[5];
    var a20 = a[6], a21 = a[7], a22 = a[8];

    var b00 = b[0], b01 = b[1], b02 = b[2];
    var b10 = b[3], b11 = b[4], b12 = b[5];
    var b20 = b[6], b21 = b[7], b22 = b[8];

    out[0] = a00 * b00 + a10 * b01 + a20 * b02;
    out[1] = a01 * b00 + a11 * b01 + a21 * b02;
    out[2] = a02 * b00 + a12 * b01 + a22 * b02;

    out[3] = a00 * b10 + a10 * b11 + a20 * b12;
    out[4] = a01 * b10 + a11 * b11 + a21 * b12;
    out[5] = a02 * b10 + a12 * b11 + a22 * b12;

    out[6] = a00 * b20 + a10 * b21 + a20 * b22;
    out[7] = a01 * b20 + a11 * b21 + a21 * b22;
    out[8] = a02 * b20 + a12 * b21 + a22 * b22;
    return out;
  }

  function makeBaseRotMat(out, angleX, angleY) {
    var cX = Math.cos(angleX), sX = Math.sin(angleX);
    var cY = Math.cos(angleY), sY = Math.sin(angleY);

    out[0] = cY;
    out[1] = sY * sX;
    out[2] = -sY * cX;

    out[3] = 0;
    out[4] = cX;
    out[5] = sX;

    out[6] = sY;
    out[7] = -cY * sX;
    out[8] = cY * cX;
    return out;
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
      "attribute vec3 aRandomness;",
      "attribute vec3 aColor;",
      "attribute vec3 aColorOuter;",
      "attribute vec2 aStarProps; // x = size (0.35 ~ 50.0), y = starType (0, 1, 2, 3)",
      "attribute vec2 aTwinkle;   // x = phase, y = speed",
      "",
      "uniform float uTime;",
      "uniform float uMorph;",
      "uniform vec2 uPivotOffset;",
      "uniform vec2 uMouse;",
      "uniform float uDpr;",
      "uniform vec2 uResolution;",
      "uniform vec2 uMouseCoord;",
      "uniform vec2 uMouseVel;",
      "uniform float uMouseActive;",
      "uniform mat3 uRotMat;",
      "",
      "varying vec3 vColor;",
      "varying vec3 vColorOuter;",
      "varying float vAlpha;",
      "varying float vStarType;",
      "",
      "void main() {",
      "  vColor = aColor;",
      "  vColorOuter = aColorOuter;",
      "  vStarType = aStarProps.y;",
      "",
      "  float twinkle = 0.84 + sin(uTime * aTwinkle.y + aTwinkle.x) * 0.16;",
      "  vAlpha = twinkle;",
      "",
      "  // 严格复刻 threejs-galaxy-generator 差动自转绕卷公式",
      "  // aPositionSpiral 初始位于 3 条辐射直线上 (0, 120, 240 度)",
      "  float angle = atan(aPositionSpiral.z, aPositionSpiral.x);",
      "  float distFromCenter = length(aPositionSpiral.xz);",
      "",
      "  // 中心自转速度显著快于外圈：(1.0 / dist) * uTime * 0.18",
      "  float simonDist = max(0.14, distFromCenter * 2.8);",
      "  float angleOffset = (1.0 / simonDist) * (uTime * 0.18);",
      "  angle += angleOffset;",
      "",
      "  // 下滚初期的蓄能加速自转与星核引力汇聚 (Warp Spin Tension & Focal Attraction)",
      "  float warpSpin = smoothstep(0.02, 0.38, uMorph) * (1.0 - smoothstep(0.38, 0.85, uMorph)) * 0.55;",
      "  angle += angleOffset * warpSpin;",
      "",
      "  // 动态旋转后结合 3D 空间立体坐标与幂律扩散",
      "  vec3 dynamicSpiral = vec3(",
      "    distFromCenter * cos(angle) + aRandomness.x,",
      "    aPositionSpiral.y + aRandomness.y,",
      "    distFromCenter * sin(angle) + aRandomness.z",
      "  );",
      "",
      "  // 电影级两翼星轨分流 (Bilateral Cosmic Rail Streaming):",
      "  // 摒弃生硬插值，粒子沿双曲抛物线流线优雅向视口左、右两翼流淌展开",
      "  float morphCurve = smoothstep(0.08, 0.88, uMorph);",
      "  vec3 curvedFlight = vec3(",
      "    dynamicSpiral.x * (1.0 + morphCurve * 0.85) + sign(dynamicSpiral.x) * (morphCurve * 0.42),",
      "    dynamicSpiral.y + morphCurve * 0.16 * sign(dynamicSpiral.y),",
      "    dynamicSpiral.z - morphCurve * 0.65",
      "  );",
      "  vec3 pos = mix(dynamicSpiral, mix(curvedFlight, aPositionStream, morphCurve), morphCurve);",
      "",
      "  // 散开后保持深空缓动自转",
      "  float streamRot = uTime * 0.006 * uMorph;",
      "  float cS = cos(streamRot);",
      "  float sS = sin(streamRot);",
      "  pos.xz = vec2(pos.x * cS - pos.z * sS, pos.x * sS + pos.z * cS);",
      "",
      "  // 3D 万向球自由姿态与宏大立体矩阵变换 (3D Arcball & Volumetric Orientation)",
      "  vec3 rotatedSpiral = uRotMat * pos;",
      "",
      "  // 视口偏心原点偏移：首屏锚定在右侧，下滚时平滑居中聚焦 (Centering Focus)",
      "  float pivotFade = 1.0 - smoothstep(0.0, 0.55, uMorph);",
      "  // 电影级推进推镜 (Camera Dolly-In): 产生向星核纵深穿梭的宏大景深速度感",
      "  float dollyIn = smoothstep(0.04, 0.42, uMorph) * 0.65 - smoothstep(0.42, 0.95, uMorph) * 0.25;",
      "  vec3 rotated = vec3(",
      "    rotatedSpiral.x + uPivotOffset.x * pivotFade,",
      "    rotatedSpiral.y + uPivotOffset.y * pivotFade,",
      "    rotatedSpiral.z - (2.15 - dollyIn)",
      "  );",
      "  float fov = 1.65;",
      "  float aspect = uResolution.y / uResolution.x;",
      "",
      "  // 穿梭时掠过镜头的近身消隐，防止过大星体爆屏穿模",
      "  float nearFade = smoothstep(-0.35, -0.75, rotated.z);",
      "  vAlpha = twinkle * nearFade;",
      "",
      "  // 交互流体弹性引力场：无突变硬截断，顺向速度拖拽与阻尼弹簧丝滑复位",
      "  float interactiveInfluence = 0.0;",
      "  if (uMouseActive > 0.001) {",
      "    vec2 starScreenPos = vec2(rotated.x * fov * aspect, rotated.y * fov) / (-rotated.z);",
      "    vec2 dMouse = starScreenPos - uMouseCoord;",
      "    vec2 dAspect = vec2(dMouse.x / aspect, dMouse.y);",
      "    float distToMouse = length(dAspect);",
      "",
      "    // 连续高斯弹性势井（适度展宽平滑作用半径，无生硬硬截断）",
      "    float pullInfluence = exp(-distToMouse * distToMouse * 11.0) * uMouseActive;",
      "",
      "    if (pullInfluence > 0.001) {",
      "      vec2 pullDir = normalize(dMouse);",
      "",
      "      // 1. 弹性橡皮筋拉扯力 (显著增强拉扯振幅，形成饱满弹性伸缩感)",
      "      float springPull = distToMouse * pullInfluence * 0.17;",
      "      vec2 elasticDisplace = -pullDir * springPull;",
      "",
      "      // 2. 随鼠标滑动的流体速度拖拽 (强化顺向跟随尾流)",
      "      vec2 dragDisplace = uMouseVel * (pullInfluence * 0.14);",
      "",
      "      // 3. 阻尼波动涟漪与复位弹性振荡 (强化柔和水波回弹复位)",
      "      float velMag = length(uMouseVel);",
      "      float wavePhase = distToMouse * 20.0 - uTime * 4.5;",
      "      float reboundWave = sin(wavePhase) * exp(-distToMouse * 6.0) * velMag * 0.050;",
      "      vec2 waveDisplace = pullDir * reboundWave;",
      "",
      "      // 4. 三维立体位移：屏幕 2D 平移 + 深度 Z 轴引力透镜凹陷 (3D Funnel Well)",
      "      vec2 totalScreenDisplace = (elasticDisplace + dragDisplace + waveDisplace) * (1.0 - uMorph * 0.7);",
      "      rotated.x += totalScreenDisplace.x * (-rotated.z / (fov * aspect));",
      "      rotated.y += totalScreenDisplace.y * (-rotated.z / fov);",
      "      rotated.z -= pullInfluence * 0.16; // 3D 引力井下沉凸显",
      "",
      "      interactiveInfluence = pullInfluence;",
      "      vAlpha = twinkle * (1.0 + pullInfluence * 0.55);",
      "    }",
      "  }",
      "",
      "  gl_Position = vec4(rotated.x * fov * aspect, rotated.y * fov, rotated.z * 0.5, -rotated.z);",
      "  float distScale = pow(2.15 / max(0.4, -rotated.z), 1.35);",
      "  float starSize = aStarProps.x;",
      "  // 主力星群（1.6px ~ 2.4px），高光焦点大星（7.5px ~ 36.0px）",
      "  float downstreamScale = mix(1.0, clamp(2.8 / max(2.8, starSize), 0.16, 1.0), uMorph);",
      "  gl_PointSize = clamp(starSize * downstreamScale * uDpr * distScale * 1.30 * (1.0 + interactiveInfluence * 0.35), 0.5, 54.0);",
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
      "varying vec3 vColorOuter;",
      "varying float vAlpha;",
      "varying float vStarType;",
      "",
      "void main() {",
      "  vec2 coord = gl_PointCoord;",
      "  float dist = length(coord - vec2(0.5)) * 2.0;",
      "  if (dist > 1.0) discard;",
      "",
      "  // 严格采用 threejs-galaxy-generator 经典 5 次幂高光平滑衰减，剔除生硬星环",
      "  float strength = pow(max(0.0, 1.0 - dist), 5.0);",
      "  // 核心超高温白炽钻石纯白聚光核",
      "  float hotCore = pow(max(0.0, 1.0 - dist), 14.0);",
      "",
      "  // 单颗恒星自内向外径向渐变：钻石白炽核 (#FFFFFF) -> 主光谱色 (vColor) -> 柔和星云外晕 (vColorOuter)",
      "  vec3 coreWhite = vec3(1.0, 1.0, 1.0);",
      "  vec3 starColor = mix(vColor, coreWhite, hotCore * 0.92);",
      "  float rimFactor = smoothstep(0.25, 0.95, dist);",
      "  starColor = mix(starColor, vColorOuter, rimFactor * 0.45);",
      "",
      "  // 多元光芒散射样式 (vStarType): 0=纯净高光圆点, 1=多层柔光渐变日冕圆斑, 2=经典4翼衍射光芒, 3=华丽8翼超新星晶芒, 4=双层宽频弥散光晕",
      "  float extraGlow = 0.0;",
      "  float spikeFade = mix(1.0, 0.0, uDownstream);",
      "  if (vStarType > 0.5 && vStarType < 1.5) {",
      "    // Type 1: 多层柔光渐变日冕圆斑 (Soft Radial Multi-Layer Corona)",
      "    float softCorona = exp(-dist * dist * 3.6) * 0.75;",
      "    float outerGlow = smoothstep(0.9, 0.15, dist) * 0.35;",
      "    extraGlow = (softCorona + outerGlow) * spikeFade;",
      "    starColor = mix(starColor, coreWhite, softCorona * 0.45);",
      "  } else if (vStarType >= 1.5 && vStarType < 2.5) {",
      "    // Type 2: 经典 4 翼细致衍射星芒 (4-Point Slender Diffraction Spike)",
      "    vec2 sCoord = abs(coord - vec2(0.5));",
      "    float spikeX = exp(-sCoord.y * 45.0) * smoothstep(0.5, 0.0, sCoord.x);",
      "    float spikeY = exp(-sCoord.x * 45.0) * smoothstep(0.5, 0.0, sCoord.y);",
      "    extraGlow = max(spikeX, spikeY) * 0.85 * spikeFade;",
      "    starColor = mix(starColor, coreWhite, extraGlow * 0.65);",
      "  } else if (vStarType >= 2.5 && vStarType < 3.5) {",
      "    // Type 3: 华丽 8 翼超新星晶体星芒 (8-Point Diamond Starburst)",
      "    vec2 p0 = abs(coord - vec2(0.5));",
      "    vec2 d = coord - vec2(0.5);",
      "    vec2 pRot = abs(vec2(d.x * 0.7071 - d.y * 0.7071, d.x * 0.7071 + d.y * 0.7071));",
      "    float crossMain = max(exp(-p0.y * 42.0) * smoothstep(0.5, 0.0, p0.x), exp(-p0.x * 42.0) * smoothstep(0.5, 0.0, p0.y));",
      "    float crossDiag = max(exp(-pRot.y * 48.0) * smoothstep(0.42, 0.0, pRot.x), exp(-pRot.x * 48.0) * smoothstep(0.42, 0.0, pRot.y)) * 0.65;",
      "    extraGlow = max(crossMain, crossDiag) * 0.90 * spikeFade;",
      "    starColor = mix(starColor, coreWhite, extraGlow * 0.75);",
      "  } else if (vStarType >= 3.5) {",
      "    // Type 4: 双层宽频弥散光晕圆盘 (Broad Chromatic Halo Disc)",
      "    float broadDisk = smoothstep(0.85, 0.05, dist) * 0.60;",
      "    float centerBleed = exp(-dist * 4.0) * 0.50;",
      "    extraGlow = (broadDisk + centerBleed) * spikeFade;",
      "  }",
      "",
      "  float intensity = strength + hotCore * 0.50 + extraGlow;",
      "",
      "  // 电影级自适应中央阅读廊道 (渐进式呼吸拉开，而非生硬打孔)",
      "  float screenX = gl_FragCoord.x / uResolution.x;",
      "  float distFromCenter = abs(screenX - 0.5);",
      "  float corridorOpen = smoothstep(0.18, 0.85, uDownstream);",
      "  float railMask = smoothstep(0.16, 0.44, distFromCenter);",
      "  float mask = mix(1.0, railMask, corridorOpen);",
      "",
      "  gl_FragColor = vec4(starColor, clamp(intensity, 0.0, 1.0) * vAlpha * mask * 0.95);",
      "}"
    ].join("\n");

    var program = createProgram(gl, vsSource, fsSource);
    if (!program) return null;

    var isMobile = (window.innerWidth || 1200) < 768;
    var count = isMobile ? 12000 : 28000;

    var posSpiral = new Float32Array(count * 3);
    var posStream = new Float32Array(count * 3);
    var randomness = new Float32Array(count * 3);
    var colors = new Float32Array(count * 3);
    var colorsOuter = new Float32Array(count * 3);
    var starProps = new Float32Array(count * 2);
    var twinkles = new Float32Array(count * 2);

    var galaxyCount = Math.floor(count * 0.88);

    for (var i = 0; i < count; i++) {
      var sX, sY, sZ;
      var rndX = 0, rndY = 0, rndZ = 0;
      var rCol = 1.0, gCol = 1.0, bCol = 1.0;
      var roCol = 0.5, goCol = 0.5, boCol = 1.0;
      var sz = 0.5;
      var sType = 0.0;

      if (i < galaxyCount) {
        // 严格复刻 threejs-galaxy-generator: 初始几何为 3 条辐射直线辐条 (0, 120, 240 度)
        var branches = 3;
        var arm = i % branches;
        var branchAngle = arm * (Math.PI * 2.0 / branches);
        // 旋臂大幅延长舒展长尾
        var normR = Math.pow(Math.random(), 1.08); // 0 ~ 1
        var radius = normR * 1.65;

        // 1. 双层盘面体系：65% 薄盘核心亮星 + 35% 厚盘蓬松弥散星晕 (Thin Disk vs Thick Disk)
        var isThickDisk = Math.random() < 0.35;

        // 2. 柱状管体横截面高斯体积分布 (Volumetric Cylindrical Arm Tubes)
        // 随半径扩散的旋臂空间管状截面半径：厚度扩充 3~4 倍
        var tubeRadius = (0.045 + 0.19 * Math.pow(normR, 1.2)) * (isThickDisk ? 1.55 : 0.85);
        var tubePhi = Math.random() * Math.PI * 2.0;
        var tubeDist = tubeRadius * Math.pow(Math.random(), isThickDisk ? 0.75 : 1.35);
        var tubeRadialOffset = Math.cos(tubePhi) * tubeDist;
        var tubeY = Math.sin(tubePhi) * tubeDist;

        // 3. 增强型天体物理 3D S-Warp 空间立体波浪折叠 (波幅由 0.16 提升至 0.36)
        // 各旋臂进入空间波浪相位各异，一条大幅高扬、一条大幅俯冲穿插
        var warpAmp = 0.36 * Math.pow(normR, 1.35);
        var warpY = Math.sin(branchAngle * 1.0 + radius * 2.0 + 0.4) * warpAmp;

        // 4. 银心核球高斯 3D 球体发光体 (Dense Bulge Volume)
        var bulgeFactor = Math.exp(-radius * 7.0);
        var bulgeY = bulgeFactor * (Math.random() - 0.5 + Math.random() - 0.5) * 0.18;
        var bulgeR = bulgeFactor * (Math.random() - 0.5) * 0.06;

        // 5. 组合空间位置
        var effectiveR = Math.max(0.015, radius + tubeRadialOffset + bulgeR);
        sX = Math.cos(branchAngle) * effectiveR;
        sZ = Math.sin(branchAngle) * effectiveR;
        sY = warpY + bulgeY + tubeY;

        // 6. 旋臂内部微扰：高阶幂律聚集保持旋臂主干凝聚璀璨，同时外层形成立体羽化
        var randPower = isThickDisk ? 4.5 : 7.8;
        var rSpread = (0.02 + 0.14 * normR) * (isThickDisk ? 1.4 : 0.85);
        rndX = Math.pow(Math.random(), randPower) * (Math.random() < 0.5 ? -1 : 1) * rSpread;
        rndY = (Math.random() - 0.5) * (0.025 + 0.08 * normR) * (isThickDisk ? 1.5 : 0.75);
        rndZ = Math.pow(Math.random(), randPower) * (Math.random() < 0.5 ? -1 : 1) * rSpread;

        // Astra 色谱：冰蓝、浅蓝、暖橙、杏色与银白；只调整颜色，保留全部几何抽样。
        if (radius < 0.12) {
          // 银心保留银白亮核，穿插少量暖杏色恒星。
          if (Math.random() < 0.70) {
            rCol = 245 / 255; gCol = 246 / 255; bCol = 251 / 255;
            roCol = rCol * 0.72; goCol = gCol * 0.72; boCol = bCol * 0.72;
          } else {
            rCol = 250 / 255; gCol = 153 / 255; bCol = 76 / 255;
            roCol = rCol * 0.60; goCol = gCol * 0.60; boCol = bCol * 0.60;
          }
        } else {
          // 为原有 8% 白星抽样预留权重，五色总比例为 36/16/12/10/26。
          // 沿用原有两次颜色随机调用，后续位置、尺寸与闪烁的随机序列不变。
          var pick = Math.random() * 0.92;

          if (pick < 0.36) {
            // 冰蓝 #6DCBF4，同色相柔和外晕。
            rCol = 109 / 255; gCol = 203 / 255; bCol = 244 / 255;
            roCol = rCol * 0.60; goCol = gCol * 0.60; boCol = bCol * 0.60;
          } else if (pick < 0.52) {
            // 浅蓝 #7AB1FE。
            rCol = 122 / 255; gCol = 177 / 255; bCol = 254 / 255;
            roCol = rCol * 0.60; goCol = gCol * 0.60; boCol = bCol * 0.60;
          } else if (pick < 0.64) {
            // 暖橙 #F87915。
            rCol = 248 / 255; gCol = 121 / 255; bCol = 21 / 255;
            roCol = rCol * 0.60; goCol = gCol * 0.60; boCol = bCol * 0.60;
          } else if (pick < 0.74) {
            // 杏色 #FA994C。
            rCol = 250 / 255; gCol = 153 / 255; bCol = 76 / 255;
            roCol = rCol * 0.60; goCol = gCol * 0.60; boCol = bCol * 0.60;
          } else {
            // 银白 #F5F6FB。
            rCol = 245 / 255; gCol = 246 / 255; bCol = 251 / 255;
            roCol = rCol * 0.72; goCol = gCol * 0.72; boCol = bCol * 0.72;
          }

          if (Math.random() < 0.08) {
            // 银白亮星；保留原有抽样，不影响后续几何与星芒分配。
            rCol = 245 / 255; gCol = 246 / 255; bCol = 251 / 255;
            roCol = rCol * 0.72; goCol = gCol * 0.72; boCol = bCol * 0.72;
          }
        }

        // 尺寸分配：主力星群换大至 1.6px ~ 2.4px，高光大星范围扩大至 7.5px ~ 36.0px（大小随机性更强）
        var sizeRoll = Math.random();
        if (sizeRoll < 0.925) {
          // 92.5% 主力星群：1.6px ~ 2.4px（充盈饱满，星体数量感倍增）
          sz = 1.60 + Math.random() * 0.80;
          sType = 0.0; // Type 0: 钻石纯净高光圆点
        } else if (sizeRoll < 0.985) {
          // 6.0% 过渡中等亮星：2.6px ~ 6.0px（增强星系景深纵深）
          sz = 2.60 + Math.random() * 3.40;
          sType = Math.random() < 0.5 ? 0.0 : 1.0; // 50% 纯圆，50% 柔光日冕
        } else {
          // 1.5% 高光焦点大星：7.5px ~ 36.0px（大小随机性更强，非线性幂律阶梯）
          var powerRoll = Math.pow(Math.random(), 1.55);
          sz = 7.5 + powerRoll * 28.5; // 7.5px ~ 36.0px

          // 多元光芒散射样式随机分配
          var typePick = Math.random();
          if (typePick < 0.30) {
            sType = 1.0; // Type 1: 多层柔光渐变日冕圆斑
          } else if (typePick < 0.60) {
            sType = 2.0; // Type 2: 经典 4 翼细致衍射星芒
          } else if (typePick < 0.85) {
            sType = 3.0; // Type 3: 华丽 8 翼超新星晶体星芒
          } else {
            sType = 4.0; // Type 4: 双层宽频弥散光晕圆盘
          }
        }
      } else {
        // 宇宙深空背景基底星 (全屏星海分布)
        sX = (Math.random() - 0.5) * 3.8;
        sY = (Math.random() - 0.5) * 3.4;
        sZ = -1.2 + Math.random() * 2.2;
        rndX = 0; rndY = 0; rndZ = 0;

        var bgRand = Math.random();
        if (bgRand < 0.94) {
          sz = 1.40 + Math.random() * 0.80; // 背景微星同步微调，提升全屏星海丰满度
          sType = 0.0;
        } else {
          sz = 2.40 + Math.random() * 1.80;
          sType = Math.random() < 0.4 ? 1.0 : 0.0;
        }

        var tempRand = Math.random();
        // 独立背景星沿用同一组 Astra 五色，散开后不会切回旧色谱。
        if (tempRand < 0.36) {
          rCol = 109 / 255; gCol = 203 / 255; bCol = 244 / 255;
          roCol = rCol * 0.60; goCol = gCol * 0.60; boCol = bCol * 0.60;
        } else if (tempRand < 0.52) {
          rCol = 122 / 255; gCol = 177 / 255; bCol = 254 / 255;
          roCol = rCol * 0.60; goCol = gCol * 0.60; boCol = bCol * 0.60;
        } else if (tempRand < 0.64) {
          rCol = 248 / 255; gCol = 121 / 255; bCol = 21 / 255;
          roCol = rCol * 0.60; goCol = gCol * 0.60; boCol = bCol * 0.60;
        } else if (tempRand < 0.74) {
          rCol = 250 / 255; gCol = 153 / 255; bCol = 76 / 255;
          roCol = rCol * 0.60; goCol = gCol * 0.60; boCol = bCol * 0.60;
        } else {
          rCol = 245 / 255; gCol = 246 / 255; bCol = 251 / 255;
          roCol = rCol * 0.72; goCol = gCol * 0.72; boCol = bCol * 0.72;
        }
      }

      posSpiral[i * 3 + 0] = sX;
      posSpiral[i * 3 + 1] = sY;
      posSpiral[i * 3 + 2] = sZ;

      randomness[i * 3 + 0] = rndX;
      randomness[i * 3 + 1] = rndY;
      randomness[i * 3 + 2] = rndZ;

      // 全局深空星海粒子分布：分流至左右两翼流光星轨（Bilateral Cosmic Rails）
      var railSide = (i % 2 === 0 ? 1 : -1);
      var stX, stY, stZ;
      if (Math.random() < 0.82) {
        // 82% 粒子流向视口两侧流光星轨（0.60 ~ 2.05 区域）
        var edgeDist = 0.60 + Math.pow(Math.random(), 1.35) * 1.45;
        stX = railSide * edgeDist;
        stY = (Math.random() - 0.5) * 3.4;
        stZ = -1.6 + Math.random() * 2.5;
      } else {
        // 18% 纵深远景微弱深空尘星，位于极远背景，不干扰中央阅读走廊
        stX = (Math.random() - 0.5) * 3.6;
        stY = (Math.random() - 0.5) * 3.0;
        stZ = -2.4 + Math.random() * 1.0;
      }

      posStream[i * 3 + 0] = stX;
      posStream[i * 3 + 1] = stY;
      posStream[i * 3 + 2] = stZ;

      colors[i * 3 + 0] = rCol;
      colors[i * 3 + 1] = gCol;
      colors[i * 3 + 2] = bCol;

      colorsOuter[i * 3 + 0] = roCol;
      colorsOuter[i * 3 + 1] = goCol;
      colorsOuter[i * 3 + 2] = boCol;

      starProps[i * 2 + 0] = sz;
      starProps[i * 2 + 1] = sType;

      twinkles[i * 2 + 0] = Math.random() * Math.PI * 2.0;
      twinkles[i * 2 + 1] = 0.5 + Math.random() * 2.0;
    }

    function bindBuffer(data, usage) {
      var buf = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, buf);
      gl.bufferData(gl.ARRAY_BUFFER, data, usage || gl.STATIC_DRAW);
      return buf;
    }

    var bufSpiral = bindBuffer(posSpiral);
    var bufStream = bindBuffer(posStream);
    var bufRandomness = bindBuffer(randomness);
    var bufColor = bindBuffer(colors);
    var bufColorOuter = bindBuffer(colorsOuter);
    var bufStarProps = bindBuffer(starProps);
    var bufTwinkle = bindBuffer(twinkles);

    var aPositionSpiral = gl.getAttribLocation(program, "aPositionSpiral");
    var aPositionStream = gl.getAttribLocation(program, "aPositionStream");
    var aRandomness = gl.getAttribLocation(program, "aRandomness");
    var aColor = gl.getAttribLocation(program, "aColor");
    var aColorOuter = gl.getAttribLocation(program, "aColorOuter");
    var aStarProps = gl.getAttribLocation(program, "aStarProps");
    var aTwinkle = gl.getAttribLocation(program, "aTwinkle");

    var uTime = gl.getUniformLocation(program, "uTime");
    var uMorph = gl.getUniformLocation(program, "uMorph");
    var uDownstream = gl.getUniformLocation(program, "uDownstream");
    var uPivotOffset = gl.getUniformLocation(program, "uPivotOffset");
    var uMouse = gl.getUniformLocation(program, "uMouse");
    var uDpr = gl.getUniformLocation(program, "uDpr");
    var uResolution = gl.getUniformLocation(program, "uResolution");
    var uMouseCoord = gl.getUniformLocation(program, "uMouseCoord");
    var uMouseVel = gl.getUniformLocation(program, "uMouseVel");
    var uMouseActive = gl.getUniformLocation(program, "uMouseActive");
    var uRotMat = gl.getUniformLocation(program, "uRotMat");

    return {
      resize: function (w, h) {
        gl.viewport(0, 0, w, h);
      },
      render: function (time, morph, downstream, pivotX, pivotY, mouseX, mouseY, width, height, dpr, mouseCoordX, mouseCoordY, mouseActive, mouseVelX, mouseVelY, rotMat) {
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

        gl.enableVertexAttribArray(aRandomness);
        gl.bindBuffer(gl.ARRAY_BUFFER, bufRandomness);
        gl.vertexAttribPointer(aRandomness, 3, gl.FLOAT, false, 0, 0);

        gl.enableVertexAttribArray(aColor);
        gl.bindBuffer(gl.ARRAY_BUFFER, bufColor);
        gl.vertexAttribPointer(aColor, 3, gl.FLOAT, false, 0, 0);

        gl.enableVertexAttribArray(aColorOuter);
        gl.bindBuffer(gl.ARRAY_BUFFER, bufColorOuter);
        gl.vertexAttribPointer(aColorOuter, 3, gl.FLOAT, false, 0, 0);

        gl.enableVertexAttribArray(aStarProps);
        gl.bindBuffer(gl.ARRAY_BUFFER, bufStarProps);
        gl.vertexAttribPointer(aStarProps, 2, gl.FLOAT, false, 0, 0);

        gl.enableVertexAttribArray(aTwinkle);
        gl.bindBuffer(gl.ARRAY_BUFFER, bufTwinkle);
        gl.vertexAttribPointer(aTwinkle, 2, gl.FLOAT, false, 0, 0);

        gl.uniform1f(uTime, time);
        gl.uniform1f(uMorph, morph);
        gl.uniform1f(uDownstream, downstream);
        gl.uniform2f(uPivotOffset, pivotX, pivotY);
        gl.uniform2f(uMouse, mouseX, mouseY);
        gl.uniform1f(uDpr, dpr);
        gl.uniform2f(uResolution, canvas.width, canvas.height);

        var mcX = mouseCoordX != null ? mouseCoordX : mouseX;
        var mcY = mouseCoordY != null ? mouseCoordY : -mouseY;
        var mActive = mouseActive != null ? mouseActive : 0.0;
        var mvX = mouseVelX != null ? mouseVelX : 0.0;
        var mvY = mouseVelY != null ? mouseVelY : 0.0;
        gl.uniform2f(uMouseCoord, mcX, mcY);
        gl.uniform2f(uMouseVel, mvX, mvY);
        gl.uniform1f(uMouseActive, mActive);

        if (rotMat) {
          gl.uniformMatrix3fv(uRotMat, false, rotMat);
        } else {
          var defaultMat = new Float32Array(9);
          var angleY = mouseX * 0.36 + (1.0 - morph) * (time * 0.012);
          var angleX = mouseY * 0.24 - 0.78;
          makeBaseRotMat(defaultMat, angleX, angleY);
          gl.uniformMatrix3fv(uRotMat, false, defaultMat);
        }

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
    var springPointerX = 0;
    var springPointerY = 0;
    var mouseVelX = 0;
    var mouseVelY = 0;
    var pointerClientX = -9999;
    var pointerClientY = -9999;
    var mouseActive = 0;
    var mouseActiveTarget = 0;
    var isDragging = false;
    var dragPointerId = null;
    var dragLastX = 0;
    var dragLastY = 0;
    var dragLastTime = 0;
    var trackballVelX = 0;
    var trackballVelY = 0;
    var trackballQuat = quatIdentity();
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
       Astra 五色色板的 Canvas 兼容映射
       保留原有索引和抽样分支，避免影响星点大小、密度及视差。
       第 5 项为银白的低亮度版本。
       ═══════════════════════════════════════════════ */
    var CELESTIAL_PALETTE = [
      { r: 109, g: 203, b: 244, hex: "#6DCBF4" }, // 0: 冰蓝
      { r: 122, g: 177, b: 254, hex: "#7AB1FE" }, // 1: 浅蓝
      { r: 250, g: 153, b: 76, hex: "#FA994C" },  // 2: 杏色
      { r: 248, g: 121, b: 21, hex: "#F87915" },  // 3: 暖橙
      { r: 245, g: 246, b: 251, hex: "#F5F6FB" }, // 4: 银白
      { r: 181, g: 182, b: 186, hex: "#B5B6BA" }  // 5: 低亮银白
    ];

    function buildSideParticles() {
      sideParticles = [];
      var totalStars = isSmall ? 140 : 250;

      // 6 颗带十字衍射星芒的物理焦点恒星（Alpha Stars）
      var alphas = [
        { x: 0.50, y: 0.08, color: 1, size: 2.8, spikeLen: 48 }, // 顶部深空青主星
        { x: 0.15, y: 0.28, color: 2, size: 3.0, spikeLen: 48 }, // 左侧杏色焦点星
        { x: 0.78, y: 0.32, color: 0, size: 2.8, spikeLen: 44 }, // 右侧冰蓝巨星
        { x: 0.85, y: 0.78, color: 3, size: 2.9, spikeLen: 46 }, // 右下暖橙焦点星
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
          // 保留原有暖色星的尺寸与亮度分支。
          colorIdx = Math.random() < 0.5 ? 2 : 3;
          size = randomBetween(1.8, 2.5);
          baseAlpha = randomBetween(0.85, 0.98);
          tier = 1;
        } else if (rand < 0.30) {
          // 保留原有冷色星的尺寸与亮度分支。
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
        { core: "rgba(255,255,255,1)", mid: "rgba(109,203,244,0.85)", edge: "rgba(109,203,244,0)" }, // 0: 冰蓝
        { core: "rgba(255,255,255,1)", mid: "rgba(245,246,251,0.92)", edge: "rgba(245,246,251,0)" }, // 1: 银白
        { core: "rgba(255,255,255,1)", mid: "rgba(122,177,254,0.88)", edge: "rgba(122,177,254,0)" }, // 2: 浅蓝
        { core: "rgba(255,255,255,1)", mid: "rgba(248,121,21,0.85)", edge: "rgba(248,121,21,0)" },  // 3: 暖橙
        { core: "rgba(245,246,251,0.9)", mid: "rgba(250,153,76,0.6)", edge: "rgba(250,153,76,0)" }   // 4: 杏色
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
    function basePosition(particle, time, scale, centerX, centerY, deform, rotMatrix) {
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

      // 3D 视角旋转（由万向球复合矩阵驱动，若无则采用基础倾角）
      var x1, y2, z2;
      if (rotMatrix) {
        x1 = rotMatrix[0] * x + rotMatrix[3] * y + rotMatrix[6] * z;
        y2 = rotMatrix[1] * x + rotMatrix[4] * y + rotMatrix[7] * z;
        z2 = rotMatrix[2] * x + rotMatrix[5] * y + rotMatrix[8] * z;
      } else {
        var rotY = pointerX * 0.32 + time * 0.007;
        var rotX = -0.38 - pointerY * 0.2;
        var cosY = Math.cos(rotY);
        var sinY = Math.sin(rotY);
        var cosX = Math.cos(rotX);
        var sinX = Math.sin(rotX);

        x1 = x * cosY + z * sinY;
        var z1 = -x * sinY + z * cosY;
        y2 = y * cosX - z1 * sinX;
        z2 = y * sinX + z1 * cosX;
      }

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
    function drawSideField(time, opacity, rawProgress, runwayProgress, totalRotMat) {
      if (!sideCanvas) return;
      if (webglEngine) {
        var isDesktop = window.innerWidth >= 960;
        var isWide = window.innerWidth >= 1400;
        var pivotX = isDesktop ? (isWide ? 0.58 : 0.50) : 0.0;
        var pivotY = isDesktop ? (isWide ? -0.10 : -0.06) : -0.04;
        // 展宽人眼感知窗口：平滑渐进，提供充足的下滚仪式感与聚焦时间
        var morph = smoothstep(0.04, 0.90, (rawProgress || 0) * 0.58 + (runwayProgress || 0) * 0.52);

        var scrollY = window.scrollY || 0;
        var heroH = hero ? hero.offsetHeight : (window.innerHeight || 800);
        var downstream = clamp01((scrollY - heroH * 0.15) / (heroH * 0.92));

        webglEngine.render(time, morph, downstream, pivotX, pivotY, pointerX, pointerY, window.innerWidth, window.innerHeight, dpr, springPointerX, -springPointerY, mouseActive, mouseVelX, -mouseVelY, totalRotMat);
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

      if (mouseActiveTarget > 0.5) {
        mouseActive += (1.0 - mouseActive) * 0.12;
      } else {
        mouseActive *= 0.93; // 离开时光标引力丝滑阻尼衰减回弹
      }
      pointerX += (pointerTargetX - pointerX) * 0.055;
      pointerY += (pointerTargetY - pointerY) * 0.055;

      // 二级流体弹簧物理追踪器：计算平滑跟随位置与瞬时移动速度向量
      var targetVelX = (pointerTargetX - springPointerX) * 3.0;
      var targetVelY = (pointerTargetY - springPointerY) * 3.0;
      mouseVelX += (targetVelX - mouseVelX) * 0.20;
      mouseVelY += (targetVelY - mouseVelY) * 0.20;

      springPointerX += (pointerTargetX - springPointerX) * 0.085;
      springPointerY += (pointerTargetY - springPointerY) * 0.085;

      var runway = document.getElementById("narrativeRunway");
      var banner = document.getElementById("narrativeBanner");
      var runwayProgress = 0;
      if (runway) {
        var rRect = runway.getBoundingClientRect();
        runwayProgress = clamp01(-rRect.top / Math.max(1, rRect.height - window.innerHeight));
        var quoteOpacity = 0;
        var quoteScale = 0.95;
        var quoteY = 24;
        if (runwayProgress <= 0.98) {
          if (runwayProgress < 0.10) {
            var t = runwayProgress / 0.10;
            quoteOpacity = smoothstep(0, 1, t);
            quoteScale = 0.95 + 0.05 * t;
            quoteY = 24 * (1 - t);
          } else if (runwayProgress < 0.78) {
            quoteOpacity = 1;
            quoteScale = 1.0;
            quoteY = 0;
          } else {
            var t = (runwayProgress - 0.78) / 0.20;
            quoteOpacity = 1 - smoothstep(0, 1, t);
            quoteScale = 1.0 + 0.04 * t;
            quoteY = -24 * t;
          }
        } else {
          quoteOpacity = 0;
          quoteScale = 1.04;
          quoteY = -24;
        }
        if (banner) {
          banner.style.setProperty("--narrative-opacity", quoteOpacity.toFixed(3));
          banner.style.setProperty("--narrative-scale", quoteScale.toFixed(3));
          banner.style.setProperty("--narrative-y", quoteY.toFixed(1) + "px");
        }
      }

      if (!isDragging && !reduceMotion) {
        // 惯性滑行 (Inertia Glide)
        if (Math.abs(trackballVelX) > 0.0001 || Math.abs(trackballVelY) > 0.0001) {
          var qP = [0, 0, 0, 0];
          var qY = [0, 0, 0, 0];
          var qI = [0, 0, 0, 0];
          quatFromAxisAngle(qP, 1, 0, 0, trackballVelY);
          quatFromAxisAngle(qY, 0, 1, 0, trackballVelX);
          quatMultiply(qI, qP, qY);
          quatMultiply(trackballQuat, qI, trackballQuat);
          trackballVelX *= 0.93;
          trackballVelY *= 0.93;
        }

        // 缓慢优雅弹性归位 (Damped Spherical Relaxation: ~3.5 秒平滑回归)
        var returnRate = 0.018 + progress * 0.06;
        var distToIdentity = Math.abs(1.0 - Math.abs(trackballQuat[0]));
        if (distToIdentity > 0.00005) {
          quatSlerp(trackballQuat, trackballQuat, [1, 0, 0, 0], returnRate);
        } else {
          trackballQuat[0] = 1; trackballQuat[1] = 0; trackballQuat[2] = 0; trackballQuat[3] = 0;
        }
      }

      var baseRotMat = new Float32Array(9);
      var trackMat = new Float32Array(9);
      var totalRotMat = new Float32Array(9);

      var angleY = pointerX * 0.36 + (1.0 - progress) * (animationTime * 0.012);
      var angleX = pointerY * 0.24 - 0.78;
      makeBaseRotMat(baseRotMat, angleX, angleY);
      quatToMat3(trackMat, trackballQuat);
      mat3Multiply(totalRotMat, trackMat, baseRotMat);

      sideOpacity = measureSideOpacity(animationTime * 1000);
      drawSideField(animationTime, sideOpacity, rawProgress, runwayProgress, totalRotMat);

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
        var base = basePosition(particle, animationTime, scale, centerX, centerY, stages.deform, totalRotMat);
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
        }, animationTime, scale, centerX, centerY, stages.deform, totalRotMat);
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

    function updatePointerCoordinates(clientX, clientY) {
      pointerTargetX = (clientX / Math.max(1, window.innerWidth) - 0.5) * 2;
      pointerTargetY = (clientY / Math.max(1, window.innerHeight) - 0.5) * 2;
      pointerClientX = clientX;
      pointerClientY = clientY;
      mouseActiveTarget = 1;
      scheduleFrame();
    }

    function handlePointerDown(event) {
      if (reduceMotion) return;
      var target = event.target;
      var interactive = target && target.closest && target.closest("a, button, input, textarea, select, [role='button'], .btn");
      if (interactive) return;

      isDragging = true;
      dragPointerId = event.pointerId;
      dragLastX = event.clientX;
      dragLastY = event.clientY;
      dragLastTime = window.performance.now();
      trackballVelX = 0;
      trackballVelY = 0;

      stage.classList.add("is-grabbing");
      if (stage.setPointerCapture && event.pointerId != null) {
        try { stage.setPointerCapture(event.pointerId); } catch (e) {}
      }
      document.body.style.userSelect = "none";
      updatePointerCoordinates(event.clientX, event.clientY);
    }

    function handlePointerMove(event) {
      if (isDragging && event.pointerId === dragPointerId) {
        var now = window.performance.now();
        var dt = Math.max(1, now - dragLastTime);
        var dx = event.clientX - dragLastX;
        var dy = event.clientY - dragLastY;
        dragLastX = event.clientX;
        dragLastY = event.clientY;
        dragLastTime = now;

        var rotSens = 0.0045;
        var deltaPitch = dy * rotSens;
        var deltaYaw = dx * rotSens;

        var qPitch = [0, 0, 0, 0];
        var qYaw = [0, 0, 0, 0];
        var qInc = [0, 0, 0, 0];
        quatFromAxisAngle(qPitch, 1, 0, 0, deltaPitch);
        quatFromAxisAngle(qYaw, 0, 1, 0, deltaYaw);
        quatMultiply(qInc, qPitch, qYaw);
        quatMultiply(trackballQuat, qInc, trackballQuat);

        var instVelX = deltaYaw * (16.67 / dt);
        var instVelY = deltaPitch * (16.67 / dt);
        trackballVelX = trackballVelX * 0.35 + instVelX * 0.65;
        trackballVelY = trackballVelY * 0.35 + instVelY * 0.65;

        updatePointerCoordinates(event.clientX, event.clientY);
        scheduleFrame();
        return;
      }

      if (!heroVisible) {
        mouseActiveTarget = 0;
        return;
      }
      var scrollY = window.scrollY || 0;
      var heroH = hero ? hero.offsetHeight : (window.innerHeight || 800);
      if (scrollY < heroH * 0.90 && event.clientY <= window.innerHeight) {
        updatePointerCoordinates(event.clientX, event.clientY);
      } else {
        mouseActiveTarget = 0;
      }
    }

    function handlePointerUp(event) {
      if (!isDragging) return;
      if (event.pointerId != null && dragPointerId != null && event.pointerId !== dragPointerId) return;
      isDragging = false;
      dragPointerId = null;
      stage.classList.remove("is-grabbing");
      document.body.style.userSelect = "";

      var maxVel = 0.032;
      trackballVelX = Math.max(-maxVel, Math.min(maxVel, trackballVelX));
      trackballVelY = Math.max(-maxVel, Math.min(maxVel, trackballVelY));
      scheduleFrame();
    }

    stage.addEventListener("pointerdown", handlePointerDown);
    stage.addEventListener("pointermove", handlePointerMove, { passive: true });
    window.addEventListener("pointermove", handlePointerMove, { passive: true });
    window.addEventListener("pointerup", handlePointerUp);
    window.addEventListener("pointercancel", handlePointerUp);

    stage.addEventListener("pointerleave", function () {
      if (isDragging) return;
      pointerTargetX = 0;
      pointerTargetY = 0;
      pointerClientX = -9999;
      pointerClientY = -9999;
      mouseActiveTarget = 0;
    });

    window.addEventListener("pointerleave", function () {
      if (isDragging) return;
      pointerTargetX = 0;
      pointerTargetY = 0;
      pointerClientX = -9999;
      pointerClientY = -9999;
      mouseActiveTarget = 0;
    });

    window.addEventListener("blur", function () {
      if (isDragging) {
        isDragging = false;
        stage.classList.remove("is-grabbing");
        document.body.style.userSelect = "";
      }
      pointerTargetX = 0;
      pointerTargetY = 0;
      pointerClientX = -9999;
      pointerClientY = -9999;
      mouseActiveTarget = 0;
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
    quatIdentity: quatIdentity,
    quatNormalize: quatNormalize,
    quatMultiply: quatMultiply,
    quatFromAxisAngle: quatFromAxisAngle,
    quatSlerp: quatSlerp,
    quatToMat3: quatToMat3,
    mat3Multiply: mat3Multiply,
    makeBaseRotMat: makeBaseRotMat,
    init: init
  };
});
