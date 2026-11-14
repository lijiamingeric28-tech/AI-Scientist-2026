# 天体类型与性质规范工作台 Implementation Plan

> Execute the user-approved Chinese plan from this chat. Use executing-plans with independently owned domain tasks and final code review. Current checkout/branch is deliberately retained; do not commit or discard prior knowledge-workbench changes.

**Goal:** A theme-aware Settings registry workbench with graph/matrix/detail, type/property/binding drafts, validation, immutable publication/rollback, manual user subtypes and truthful runtime/insight compatibility.

**Architecture:** Existing RegistryService scientific sources stay immutable. A SQLite-backed RegistryWorkbenchService projects exact source views, stores a sparse local draft, validates it and publishes a local extension plus knowledge compatibility manifest. New queries pin one active version bundle. Existing task science/qualification guards remain authoritative.

**Stack:** Existing Python/FastAPI/SQLite/Pydantic/Astropy; React/Vite/CSS semantic theme variables, Canvas and Web Worker. No new database, algorithms, AI document authoring or external paid verification calls.

## Global constraints

- Settings -> 服务与知识 -> 天体与性质规范, hash #settings=registry. Types, not individual objects.
- Save draft -> validate/impact -> publish for new tasks only. Published/historical versions readonly. Atomic activation and rollback, expected revisions/idempotency.
- Full type/property/binding CRUD/disable, dependencies visible, no cascade of published records. Custom types have one parent chain ending in an official type; query explicitly selects compatible subtype, original SIMBAD facts preserved.
- Editable definitions/aliases/subject/units/representation/conditions/source rationale; no arbitrary scientific scripts or new algorithms. Scientific identity changes require a new property.
- Shared definition edit vs current-type binding/profile edit are distinct operations. Full exact references, not property ID alone, determine identity (source contains 1437 definition records for1434 IDs and1443 output records for1433 IDs).
- No forged scientific reviews or model/software qualification receipts. New/changed properties without exact permission retain source data and advertise unavailable automatic execution/conversion; existing exact unchanged scopes can reuse audited provenance only.
- Insight compatibility retains exact unchanged mappings, suspends changed mappings with reasons, permits missing coverage, preserves original333-card author content and labels.
- UI and Canvas use system palette/semantic tokens, no component color literals/independent palette. Light/dark/custom/contrast/font changes redraw without camera reset. Category user color is configuration data.
- Desktop1440/1280/1024. Graph80/120/200 total nodes; all records accessible via server paging/search. Worker stable layout, no continuous idle redraw. Cards24, table50 with25/50/100. Search250ms cancel/stale guards.
- Only isolated QA stores may receive synthetic mutation/publication/activation. Preserve real runtime user overlay and default installed pair. No commits/pushes.

## Locked domain/API contract

Prefix /api/registry-workbench. Reads accept workspace_id(optional), release_id(optional), keyword,type_id,family_id,origin,status,sort,offset,limit; summary/list/graph use the same effective projection and scoped facets.

Summary: {revision,view:'published'|'draft',workspace:null|{id,revision,status,base_bundle},active_bundle:{id,revision,registry_ref,knowledge_ref,capability_ref?},counts:{types,properties,bindings,disabled,changed},types:[type summaries],families:[{id,label,count}],knowledge_coverage:{available,missing},capabilities:{subjects:[{id,label}],scales:[{id,label}],conversion_policies:[...]},workspace_available:bool}. counts are real effective views, never stale file comments. Lists {items,total,offset,limit,revision}; detail full canonical object. Mutations {success:true,workspace:{id,revision,status},item?,impact?}; UI never treats false/missing ACK as success.

Type summary/full: {id,kind:'type',code,label,description,aliases,parent_id,standard_otype,origin:'builtin'|'user'|'override',status:'active'|'disabled',revision,property_count,conditions:[],color?:user data,source_refs:[],...}. Existing standard id/code immutable. Child id user_type_UUID; standard_otype points to one actual anchor.

Property summary/full: {id:<opaque stable record key>,kind:'property',property_id,label,description,family_id,origin,status,revision,definition_ref,definition:<canonical PropertyDefinition>,output_profiles:[<canonical OutputProfile>],unit_label,representation_label,subject_label,type_count,automatic_conversion_ready,knowledge_coverage,...}. id distinguishes exact source definition views; property_id displayed separately. Editing retains record key and increments exact semantic refs; display-only metadata does not alter scientific refs.

Binding: {id,type_id,property_key,definition_ref,profile_ref,conditions:[],excluded_conditions:[],display_order,status,conditional,origin,revision,rule_refs:[]}. Details include bindings, dependents, knowledge links with entry_id/title/compatibility/reason, source/version and impact.

POST /workspaces {base_bundle_id?}; GET /workspaces lists current drafts; GET /workspaces/{id}.
POST /workspaces/{id}/types|properties|bindings creates with expected_revision. PUT /workspaces/{id}/{kind}/{item_id} updates with expected_revision. DELETE ... with expected_revision performs removal of unreferenced new draft item or disable/detach; GET .../impact returns dependents.
POST /workspaces/{id}/validate {expected_revision} -> {success,validation:{id,workspace_revision,state:'passed'|'failed',errors:[],warnings:[],impact,knowledge_coverage,capabilities}}. Successful draft writes invalidate old validation. POST /publish {expected_revision,validation_id,expected_active_bundle_id,idempotency_key} -> {success,release,bundle,workspace}; GET /releases; POST /releases/{id}/activate {expected_active_bundle_id,idempotency_key}. Errors409 concurrent/stale,422 invalid,503 persistence/build errors. No partial activation or fake success.

Graph query view=overview|type|property,focus_id,limit80/120/200 -> {nodes,edges,categories,meta:{total_types,total_properties,matched_entries,shown_entries,node_count,truncated,view,revision,represented_entries}}. Node IDs namespaced; nodes use kind type/property/aggregate plus source_kind; exact bindings edge relation_type applicable|conditional, user/source hierarchy explicit only; no inferred hierarchy. Frontend adapter may map to reusable graph kinds, preserving source_kind.

## Tasks and ownership

### Task1 domain service / immutable releases (backend agent)
- Create registry/workbench*.py and registry/workspace_release.py, api/routes/registry_workbench.py; own RegistryService support/load extension, Application composition, API registration and SQLite migration. Tests new registry workbench files.
- Project source exact context definition/profile variants via existing candidate helpers, not lossy ID dicts or invented rules. Draft sparse ops, dependency/identity/unit/representation validation, source-type hierarchy only when explicit, honest user metadata, atomic build/activation/rollback and insight compatibility.
- Published local release schema registry-workspace/1 loads as common registry view with workspace metadata. RegistryService.support(release,otypes,subject_class_id,*,user_type_ref=None) applies local exact changes while preserving source AST gates/exclusions. Public runtime helper contracts locked via message to root before integration.
- Active bundle acquired with a single repository read, retaining legacy active_registry/active_knowledge mirrored atomically. Bundle must keep base registry/knowledge refs and capability compatibility proof; no blind receipt copying. Preserve original source records. New insight wrapper schema insight-knowledge-workspace/1 contains base knowledge ref and compatible binding IDs/gaps, not rewritten author prose.
- RED/GREEN persistence/concurrency/deletion/release failure/idempotency/rollback/exact variant coverage +5000 synthetic paging. Focused tests first. Report source freeze before root full suite.

### Task2 frontend workbench (frontend agent)
- Own new frontend registry components/hooks/services/styles/tests, SettingsDialog + new settings launch panel/studio, App hash wiring. No Python or existing shared graph/theme changes. Query confirmation user subtype panel remains root-owned.
- Implement graph/matrix cards/table/shared selection, tree/facets, overlay blurred details, five grouped type/property/binding forms, current-type vs global edit, impact/dependency dialogs, conflict drafts, draft/release selector, validation/coverage/publish/rollback UI and link to existing knowledge studio.
- Use locked API above; default published readonly, first write creates draft; real ACK required. Persist/recover drafts through server. Read failures expose cached readonly state, never substitute fabricated data.
- Reuse KnowledgeGraphView through a namespaced adapter and its existing props; root provides semantic palette helper and renderer support for conditional edges/custom source_kind. No hardcoded visual color.
- Tests API/payload/state/controls before code. Build/test only frontend; do not write real user data. Report focused evidence and source freeze.

### Task3 runtime + shared theme integration (root)
- Shared Canvas theme resolver; existing knowledge graph and registry graph consume resolved semantic tokens; palette-derived category coloring and status/conditional line semantics, stable camera/idle behavior.
- Pin active registry/knowledge/capability bundle at new draft creation and confirmation; old drafts/tasks use pinned version, explicit reload/reconfirm upgrades. Manual compatible subtype selection UI/action uses user_type_ref, never changes external target assertions.
- Read local registry/insight wrapper through exact base refs; unchanged definition/profile/rule deps preserve eligibility only after dependency-equivalence checks, changed/new definitions remain honest unqualified where necessary. Preserve raw facts, forbid unlicensed arithmetic, expose coverage/capability gaps. No M11 failure merely because claims unavailable.
- Fixed-input integration tests for unmodified scopes, user types, new/disabled props, source retention, no automatic normalization without permission, knowledge gaps, old-task pins and rollback.

### Task4 integrate / review / verify
- Full frontend test/build + full offline pytest (all Configuration.EDITABLE env values forced empty, not unset), Ruff, diff check. Independent scoped backend/frontend reviews then final whole-change review, fix material findings.
- Isolated UI1440/1280/1024/light/dark/custom/contrast, real current corpus, draft CRUD/reload/publish/restart/rollback, conflict and disk/outage errors, correct source props/types, explicit graph coverage and new-query pins.5000 synthetic paging;200-node actual CanvasP95<=33ms and idle0. Keep main5173/HMR+8781 latest, no synthetic writes to main.

## Preflight and defaults

Existing user-approved working-branch preference persists; current codex/knowledge-workbench includes prior uncommitted changes. Keep this checkout so running HMR and local resources remain aligned. No clean/revert/commit. Native PowerShell equivalent used for plan workspace when WSL bash is unavailable.
User plan is the authoritative spec; this file locks implementation interfaces. One domain owner and one frontend owner can work independently under exact contracts; root integrates runtime/shared renderer. Exact runtime qualification cannot be invented by technical validation: expose gaps and retain native facts rather than silently bypass existing guards.
