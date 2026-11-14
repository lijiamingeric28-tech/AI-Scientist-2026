# User Property Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Make published user-defined properties executable by the ordinary retrieval, extraction and normalization workflow, retaining source data when conversion is unavailable.

**Architecture:** Compile a distinct immutable user-declared execution contract and validation receipt per exact definition/output/applicability. Existing source evidence gates and arithmetic are reused; user publication is never represented as built-in scientific review. New query bundles freeze execution references and legacy releases retain old behavior.

**Tech Stack:** Existing Python/FastAPI/SQLite, React/Vite and existing normalization engine; no new services or libraries.

**Spec:** docs/superpowers/specs/2026-11-13-user-property-execution-design.md

## Global Constraints
- Keep original scientific packages and author knowledge read-only; no invented scientific/model approval records.
- Preserve all existing uncommitted work on codex/knowledge-workbench; no commits, pushes, resets or checkout changes.
- Do not test-publish or create tasks in the real runtime-data store. All mutation/science checks use temporary synthetic stores and offline providers.
- No arbitrary algorithms/scripts; reuse existing same-quantity conversion and evidence validation.
- Keep existing frontend style and system colors; no new literal color palette.
- Existing frozen tasks and historical releases keep exact prior version behavior.

## Review Focus
- Mixed built-in/user selections must preserve built-in qualification checks while allowing the explicit local contract only for its exact definition/output/binding.
- Missing source units/reference parameters or unsupported conversion retains admitted native data with concrete reasons.
- Client-supplied ready flags, samples, changed refs or stale validation cannot authorize execution.
- Legacy published wrappers are not silently recompiled under the new policy.
- Source identity/quantity/ownership and uncertainty/limit checks remain active for user definitions.

### Task 1: Compile and consume user execution contracts
**Owner:** backend implementer. Own backend source/tests only; root will edit frontend.
**Files:** create focused registry/user_execution.py and runtime/science helper modules as necessary; modify registry workbench/projection/validation/publication/workspace_release, query context/drafts, runtime profiles, science reader profiles, ordinary normalization/admission integration. New tests/rebuild/test_user_property_execution.py and focused integration tests.
**Interfaces:** Properties accept `execution_examples: []`; each numeric example has `label`, `source_value` (decimal string), `source_unit` (string), `source_representation` (Representation JSON), `expected_value` (decimal string), optional exact `profile_ref` (otherwise first output profile). Do not introduce general expressions. Public property `execution_capabilities` contains `schema_version: user-property-capabilities/1`, `origin: user_defined|user_modified|builtin`, `retrieval/extraction/native/normalization: {ready: bool, reasons: [human-readable string]}`, `validation: {state: pending|passed|failed, checks: [], examples: []}`, and optional `execution_ref` canonical Ref. Existing automatic_conversion_ready is retained as a compatibility presentation value, not the authority. Workspace validation report may add `execution` aggregate report. Publish persists hash-bound execution_manifest. Communicate any essential additive interface before implementation.
- [x] Write RED tests for new property in support/ordinary M01 selection, expected-output numeric example validation, tampering/stale validation, unsupported conversion/native preservation and legacy behavior.
- [x] Compile validated user definitions separately from strict reviewed models. Exact dictionary refs and source/approval provenance remain accurate. Load user definitions/profiles into effective projections without fabricated review refs. Build ordinary support bindings with exact dependency refs.
- [x] Runtime checks use the frozen published execution contract. Existing configured model operation/format/bounds and source evidence gates remain active. Built-in portion of mixed selections retains existing strict scientific checks. Native-only is an accepted execution mode.
- [x] Reuse existing arithmetic and uncertainty handling; conversion failures become explicit not-run representations with admitted raw records retained. Test an actual source unit change and no-conversion delivery path, not just direct support dictionaries.
- [x] Test query creation/freeze, release publication, rollback and application reopening with old/new task versions. Run scoped backend tests and Ruff; report exact commands/results and material limitations. No commits.

### Task 2: Processing/verification editor and reading UI
**Owner:** root. Own frontend files only during Task 1.
**Files:** frontend/src/components/registry/RegistryEditor.jsx, RegistryWorkspace.jsx, registryWorkbench.css, frontend/src/lib/registryWorkbench.js, frontend/src/components/chat/RegistryQueryScope.jsx, focused frontend tests.
**Interfaces:** Consume Task 1's execution_capabilities and execution_examples without inventing readiness locally. Preserve absent capability fields on legacy entries.
- [x] Add RED tests for example round trips, capability summaries and raw-only query explanations.
- [x] Extend existing property editor with optional repeatable numeric examples (input value/unit/representation and expected output), meaningful removal and validation display; preserve dirty/conflict behavior.
- [x] Show separate capabilities and concrete reasons in details/cards/query scope; preserve legacy display fallback and all system color/font settings. Missing conversion does not imply property unavailable for extraction.
- [x] Run focused tests, full frontend tests and production build.

### Task 3: End-to-end review and delivery
**Owner:** root with independent reviewer.
- [x] Review Task 1 and Task 2 against spec and diff snapshots; fix important findings with regression tests.
- [x] Run final source backend offline full regression once source is stable; verify frontend full tests/build.
- [x] Snapshot main active defaults, user overlay and historical object hashes; restart final backend, preserve frontend HMR, verify HTTP routes and unchanged main data.
- [x] Report supported executable paths, native preservation, exact validation results and limitations. No commit/push.
