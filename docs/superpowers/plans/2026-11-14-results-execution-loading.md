# Results and execution loading implementation plan

**Goal:** Speed up all three quality tabs (completion, processing, coverage), material browsing and execution details; make the material-page back-to-top button movable while preserving scientific results, historical scope and themes.

**Architecture:** Reuse exact-publication UI projections for audit reports, rather than decoding the large delivery per endpoint. Share bounded execution reconstructions at an authoritative source/cursor/dependency identity. Frontend readers load only visible dependencies and reuse bounded exact-scope results. Back-to-top gains an opt-in draggable fixed overlay.

**Constraints:** Existing worktree and theme variables; no scientific reruns, model calls, export changes or authoritative-data migrations. Cache misses, corruption and disk failures retain the correct read path. Reads validate task, replay horizon and delivery revision before using cached data.

- [x] Add regression tests for audit reads surviving restart without whole-delivery decode; exact old revisions, mutable review dependencies, concurrent misses and cache failure.
- [x] Add a separate rebuildable audit projection in the existing UI cache, preserving current response contracts and saved report contents.
- [x] Test and implement bounded execution reconstruction reuse, concurrent request merging, mutation isolation and exact cursor/dependency invalidation.
- [x] Remove unnecessary quality-tab dependencies; debounce execution search and cache visited execution sections with cancellation and bounded memory.
- [x] Implement opt-in draggable floating back-to-top for material browsing; verify click, drag suppression, viewport bounds, resize, keyboard activation and theme reuse.
- [x] Run relevant backend regressions, frontend tests and production build; compare real-sample endpoint responses and timings with baseline; check actual UI and unchanged task/export/demo data.

Baseline: current large sample quality ~3.34 s; activity ~3.18–4.86 s; coverage ~3.36–3.40 s; execution sections ~0.46–0.87 s each. Details are in `AstroQuery/scratch/results-loading-2026-11-14/baseline.json`.
