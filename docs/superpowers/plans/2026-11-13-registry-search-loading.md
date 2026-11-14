# Registry Search and View Loading Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans; implement inline with test-first checks and one bounded final independent review.

**Goal:** Search property families locally and fetch only the visible registry view while preserving filters and exact version scope.

**Architecture:** Reusable themed native family selector; version-scoped full summary cache shared by directory/editor; filtered summary only when needed; active-gated list/graph readers with cancellation and existing cache isolation.

**Tech Stack:** Existing React 18, Vite, Node tests and development browser harness; no dependencies or backend changes.

**Spec:** docs/superpowers/specs/2026-11-13-registry-search-loading-design.md

## Global Constraints
- Keep all prior uncommitted work in the existing running checkout; no commits, resets, new worktrees or real test writes.
- Keep existing frontend style, semantic theme variables and system color logic.
- Preserve immutable releases, scientific definitions and historical tasks.

## Review Focus
- A selected family outside the candidate search or a different release remains explicit, never silently cleared.
- Hidden view requests and errors must not block the visible view or mutation eligibility.
- Same-filter returns reuse cache; changed pagination, filters or release must not reuse the wrong data.
- Late aborted results must not replace or cache new results; refresh invalidates directory and both view caches.
- Graph record counts cannot depend on the hidden list.

### Task 1: Searchable property family selector
**Files:** create frontend/src/components/registry/RegistryFamilySelect.jsx and frontend/src/lib/registryFamilies.js; modify RegistryWorkspace.jsx, RegistryEditor.jsx, registryWorkbench.css; create frontend/tests/registryFamilies.test.mjs.
**Interfaces:** `filterRegistryFamilies(families, keyword)` returns matching records without mutating input. `RegistryFamilySelect({families,value,onChange,disabled,required,emptyLabel,showCounts})` searches only local candidates and keeps an unmatched selection explicit. Sidebar consumes the version-scoped directory from Task 2.
- [x] Write/run failing local matching and server-rendered selector tests (names, IDs, multiword, large directory, unmatched selection, disabled/required).
- [x] Implement shared selector, sidebar/editor integration and semantic CSS; run focused tests.

### Task 2: Current-view reads and regression verification
**Files:** modify frontend/src/hooks/useRegistryWorkbench.js and RegistryWorkspace.jsx; create frontend/tests/registryLoadingHarness.{html,jsx}; retain existing cache utility unless a regression demonstrates a needed change.
**Interfaces:** Active-gated `useRegistryRead(..., active=true)`; hook exposes `families`, `familyDirectoryError`, `matchedTotal`, existing state/mutations unchanged. Full directory shares exact scope summary cache with `readRegistryEditorCatalog`; filtered summary excludes ordering-only sort.
- [x] Write/run failing real-Hook browser harness for view-only requests, cache reuse, aborts/late responses, hidden errors, scope/filter isolation, refreshing and preserved state.
- [x] Implement active reads, directory sharing, visible loading/error states and summary counts. Preserve matrix offset when selecting the same mode.
- [x] Run browser regression and real App smoke checks; run `npm test`, `npm run build` and `git diff --check`.
- [x] Complete bounded independent review; record evidence and keep both services running. No commit/push.
