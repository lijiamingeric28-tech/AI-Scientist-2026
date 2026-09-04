import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const testDir = dirname(fileURLToPath(import.meta.url));
const siteDir = join(testDir, "..");
const workspaceDir = join(siteDir, "..");

function readPage() {
  return readFileSync(join(siteDir, "index.html"), "utf8");
}

function readClientScript() {
  return readFileSync(join(siteDir, "landing.js"), "utf8");
}

test("bundles the real AstroQuery icon inside the static site", () => {
  assert.equal(existsSync(join(siteDir, "assets", "icon.png")), true);
  assert.match(readPage(), /src="assets\/icon\.png"/);
});

test("does not add dynamic data loading to the landing page", () => {
  const source = `${readPage()}\n${readClientScript()}`;
  assert.doesNotMatch(source, /fetch\s*\(/);
  assert.doesNotMatch(source, /XMLHttpRequest|EventSource|WebSocket/);
  assert.doesNotMatch(source, /\.csv(?:["'?]|\b)/i);
});

test("uses only deployable relative media paths", () => {
  const html = readPage();
  assert.doesNotMatch(html, /(?:src|href)="[A-Za-z]:[\\/]/);
  assert.doesNotMatch(html, /(?:src|href)="file:\/\//);
});

test("keeps the page readable when JavaScript is unavailable", () => {
  const html = readPage();
  assert.match(html, /<noscript>[\s\S]*\.reveal\s*\{[^}]*opacity:\s*1\s*!important[^}]*transform:\s*none\s*!important/);
  assert.match(html, /<noscript>[\s\S]*\.hero-fallback-mark\s*\{[^}]*opacity:\s*\.7\s*!important/);
});

async function loadLandingModel() {
  const module = await import("../landing.js");
  return module.default;
}

function closeTo(actual, expected, epsilon = 1e-9) {
  assert.ok(Math.abs(actual - expected) <= epsilon, `${actual} is not close to ${expected}`);
}

test("maps sticky Hero travel to a reversible zero-to-one progress", async () => {
  const landing = await loadLandingModel();
  assert.equal(landing.getHeroProgress(100, 1800, 900), 0);
  assert.equal(landing.getHeroProgress(0, 1800, 900), 0);
  assert.equal(landing.getHeroProgress(-450, 1800, 900), 0.5);
  assert.equal(landing.getHeroProgress(-900, 1800, 900), 1);
  assert.equal(landing.getHeroProgress(-1400, 1800, 900), 1);
});

test("samples the A glyph from two legs and one crossbar", async () => {
  const landing = await loadLandingModel();
  for (const [t, expectedX, expectedY] of [
    [0, -0.26, 0.32],
    [0.4, 0, -0.34],
    [0.8, -0.14, 0.08],
    [1, 0.15, 0.08]
  ]) {
    const point = landing.sampleAPoint(t);
    closeTo(point.x, expectedX);
    closeTo(point.y, expectedY);
  }
});

test("samples the Q as an ellipse followed by a lower-right tail", async () => {
  const landing = await loadLandingModel();
  const right = landing.sampleQPoint(0);
  closeTo(right.x, 0.48);
  closeTo(right.y, 0);

  const bottom = landing.sampleQPoint(0.22);
  closeTo(bottom.x, 0);
  closeTo(bottom.y, 0.17);

  const tailStart = landing.sampleQPoint(0.88);
  closeTo(tailStart.x, 0.25);
  closeTo(tailStart.y, 0.11);
  const tailEnd = landing.sampleQPoint(1);
  closeTo(tailEnd.x, 0.5);
  closeTo(tailEnd.y, 0.32);
});

test("separates deformation from the final two-sided burst", async () => {
  const landing = await loadLandingModel();
  assert.deepEqual(landing.getMotionStages(0), { deform: 0, burst: 0, copyOpacity: 1 });
  const early = landing.getMotionStages(0.3);
  assert.equal(early.deform, 0);
  assert.equal(early.burst, 0);
  closeTo(early.copyOpacity, 0.9446064139941691);
  assert.deepEqual(landing.getMotionStages(0.68), { deform: 1, burst: 0, copyOpacity: 0 });
  assert.deepEqual(landing.getMotionStages(1), { deform: 1, burst: 1, copyOpacity: 0 });
});

test("animates only while the Hero is visible and motion is allowed", async () => {
  const landing = await loadLandingModel();
  assert.equal(landing.shouldAnimate(true, false, false), true);
  assert.equal(landing.shouldAnimate(false, false, false), false);
  assert.equal(landing.shouldAnimate(true, true, false), false);
  assert.equal(landing.shouldAnimate(true, false, true), false);
});

test("scales particle budgets by viewport area within safe bounds", async () => {
  const landing = await loadLandingModel();
  const desktop = landing.getParticleCounts(1440, 900, false);
  assert.ok(desktop.orbit >= 800, "desktop scene needs several dense orbit layers");
  assert.ok(desktop.core >= 180, "desktop scene needs a luminous core");
  assert.ok(Object.values(desktop).reduce((sum, value) => sum + value, 0) >= 4000);

  const mobile = landing.getParticleCounts(390, 844, true);
  assert.ok(mobile.orbit >= 240);
  assert.ok(mobile.core >= 80);
  assert.ok(Object.values(mobile).reduce((sum, value) => sum + value, 0) >= 1400);

  const compactDesktop = landing.getParticleCounts(720, 700, false);
  assert.ok(Object.values(compactDesktop).reduce((sum, value) => sum + value, 0) < 4000);
  const largeDesktop = landing.getParticleCounts(3840, 2160, false);
  assert.ok(Object.values(largeDesktop).reduce((sum, value) => sum + value, 0) <= 4700);
});

test("keeps particles chaotic until activation and then eases them into formation", async () => {
  const landing = await loadLandingModel();
  assert.equal(landing.getFormationProgress(null, 1500, 2200, false), 0);
  assert.equal(landing.getFormationProgress(1000, 1000, 2200, false), 0);
  assert.equal(landing.getFormationProgress(1000, 2100, 2200, false), 0.5);
  assert.equal(landing.getFormationProgress(1000, 4000, 2200, false), 1);
  assert.equal(landing.getFormationProgress(null, 1500, 2200, true), 1);
});

test("holds scroll deformation until the AQ opening has formed", async () => {
  const landing = await loadLandingModel();
  assert.equal(landing.getActivatedHeroProgress(0.9, null, 9000, 2200, false), 0);
  assert.equal(landing.getActivatedHeroProgress(0.9, 1000, 3200, 2200, false), 0);
  closeTo(landing.getActivatedHeroProgress(0.9, 1000, 3725, 2200, false), 0.45);
  assert.equal(landing.getActivatedHeroProgress(0.9, 1000, 4000, 2200, false), 0.9);
  assert.equal(landing.getActivatedHeroProgress(0.9, 1000, 4000, 2200, true), 0);
});

test("samples four visibly distinct orbital rings around the AQ glyph", async () => {
  const landing = await loadLandingModel();
  const rightEdges = [0, 1, 2, 3].map((ring) => landing.sampleOrbitPoint(0, ring));
  assert.deepEqual(rightEdges.map((point) => Number(point.x.toFixed(2))), [0.31, 0.4, 0.5, 0.61]);
  assert.ok(rightEdges.every((point) => Math.abs(point.y) < 1e-9));
});

test("keeps side rails visible after the Hero burst has completed", async () => {
  const landing = await loadLandingModel();
  assert.equal(landing.getSideRailOpacity(0.5), 0);
  assert.ok(landing.getSideRailOpacity(0.75) > 0);
  assert.equal(landing.getSideRailOpacity(1), 1);
  assert.deepEqual(landing.getSideRailPosition(-1, 0.25, 0.5, 0, 1000, 800), { x: 70, y: 400 });
  assert.deepEqual(landing.getSideRailPosition(1, 0.25, 0.5, 0, 1000, 800), { x: 930, y: 400 });
  assert.equal(landing.shouldAnimateScene(false, 1, false, false), true);
  assert.equal(landing.shouldAnimateScene(false, 0, false, false), false);
  assert.equal(landing.shouldAnimateScene(true, 0, true, false), false);
  assert.equal(landing.shouldAnimateScene(true, 0, false, true), false);
});

test("includes an accessible activation layer and persistent side-star canvas", () => {
  const html = readPage();
  assert.match(html, /<canvas id="sidefield"[^>]*aria-hidden="true"/);
  assert.match(html, /<button[^>]*id="starGate"[^>]*aria-label="聚合 AQ 星图"/);
});

test("skips the dense Hero render after it leaves the viewport", async () => {
  const landing = await loadLandingModel();
  assert.equal(landing.shouldRenderHero(true, -900, 0, 900), true);
  assert.equal(landing.shouldRenderHero(false, -480, 420, 900), true);
  assert.equal(landing.shouldRenderHero(false, -900, 0, 900), false);
  assert.match(readClientScript(), /if \(!shouldRenderHero\(heroVisible,\s*heroRect\.top,\s*heroRect\.bottom,\s*window\.innerHeight\)\) return;/);
});

test("fits the opening content inside short landscape viewports", () => {
  const html = readPage();
  assert.match(html, /@media\s*\(max-height:\s*620px\)/);
  assert.match(html, /@media\s*\(max-height:\s*620px\)[\s\S]*?\.hero-stage\s*\{[^}]*min-height:\s*100svh/);
});

test("declares the live motion preference inside Hero initialization", () => {
  const script = readClientScript();
  assert.match(
    script,
    /function initHero\(document, window\)[\s\S]*?var motionQuery\s*=\s*window\.matchMedia\("\(prefers-reduced-motion: reduce\)"\);\s*var reduceMotion\s*=\s*motionQuery\.matches;/
  );
});

test("advances animation time with a bounded delta after resume", async () => {
  const landing = await loadLandingModel();
  assert.deepEqual(landing.advanceAnimationClock(2, 1000, 1016, 0.05), {
    elapsed: 2.016,
    timestamp: 1016
  });
  assert.deepEqual(landing.advanceAnimationClock(2, 1000, 6000, 0.05), {
    elapsed: 2.05,
    timestamp: 6000
  });
  assert.deepEqual(landing.advanceAnimationClock(2, 1000, 900, 0.05), {
    elapsed: 2,
    timestamp: 900
  });
});

test("chooses the card whose visual center is nearest the carousel center", async () => {
  const landing = await loadLandingModel();
  assert.equal(landing.nearestSlideIndex(500, [80, 478, 920]), 1);
  assert.equal(landing.nearestSlideIndex(500, [40, 280, 560, 940]), 2);
  assert.equal(landing.nearestSlideIndex(500, []), 0);
});

test("maps carousel keys to bounded slide targets", async () => {
  const landing = await loadLandingModel();
  assert.equal(landing.carouselKeyTarget("ArrowRight", 2, 5), 3);
  assert.equal(landing.carouselKeyTarget("ArrowRight", 4, 5), 4);
  assert.equal(landing.carouselKeyTarget("ArrowLeft", 0, 5), 0);
  assert.equal(landing.carouselKeyTarget("Home", 3, 5), 0);
  assert.equal(landing.carouselKeyTarget("End", 1, 5), 4);
  assert.equal(landing.carouselKeyTarget("Enter", 2, 5), null);
});

test("reveal visibility can be removed and applied again", async () => {
  const landing = await loadLandingModel();
  const values = new Set();
  const element = {
    classList: {
      toggle(name, enabled) {
        if (enabled) values.add(name);
        else values.delete(name);
      }
    }
  };

  landing.applyRevealState(element, true);
  assert.equal(values.has("is-visible"), true);
  landing.applyRevealState(element, false);
  assert.equal(values.has("is-visible"), false);
  landing.applyRevealState(element, true);
  assert.equal(values.has("is-visible"), true);
});

test("keeps the closed lightbox out of keyboard and accessibility navigation", () => {
  const html = readPage();
  const script = readClientScript();
  assert.match(html, /\.lb\s*\{[^}]*visibility:\s*hidden/);
  assert.match(html, /id="lightbox"[^>]*aria-hidden="true"/);
  assert.match(script, /setAttribute\("aria-hidden",\s*"false"\)/);
  assert.match(script, /setAttribute\("aria-hidden",\s*"true"\)/);
  assert.match(script, /event\.key\s*===\s*"Tab"/);
});

test("allows carousel controls to wrap safely on narrow screens", () => {
  const html = readPage();
  assert.match(html, /@media\s*\(max-width:\s*560px\)\s*\{\s*\.car-bar\s*\{[^}]*flex-wrap:\s*wrap/);
});

test("prevents native image dragging from stealing the carousel gesture", () => {
  assert.match(readClientScript(), /carousel\.addEventListener\("dragstart"/);
});

test("debounces live carousel announcements and exposes dark-theme focus rings", () => {
  const html = readPage();
  const script = readClientScript();
  assert.match(html, /id="carStatus"[^>]*role="status"[^>]*aria-live="polite"/);
  assert.match(script, /announceTimer\s*=\s*window\.setTimeout/);
  assert.match(script, /renderState\(currentIndexFromGeometry\(\),\s*false\)/);
  assert.match(html, /\.car:focus-visible,\s*\.slide \.img:focus-visible/);
  assert.doesNotMatch(html, /@media\s*\(max-width:\s*640px\)[^{]*\{[^}]*\.lb-prev[^}]*display:\s*none/);
});

test("keeps ids unique and all deployment-owned runtime assets present", () => {
  const html = readPage();
  const ids = [...html.matchAll(/\sid="([^"]+)"/g)].map((match) => match[1]);
  assert.equal(new Set(ids).size, ids.length);

  const sourcePaths = [
    ...html.matchAll(/\ssrc="([^"]+)"/g),
    ...html.matchAll(/url\("([^"]+)"\)/g)
  ].map((match) => match[1]).filter(Boolean);

  for (const relativePath of ["landing.js", ...sourcePaths]) {
    if (/^(?:https?:|data:|\/\/)/.test(relativePath)) continue;
    const parts = relativePath.split(/[?#]/)[0].split("/");
    const existsInSite = existsSync(join(siteDir, ...parts));
    const existsInAssembledAssets = existsSync(join(workspaceDir, ...parts));
    assert.equal(existsInSite || existsInAssembledAssets, true, relativePath);
  }
});
