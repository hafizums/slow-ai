# AGENTS.md

## Project

This repository contains `slow_ai`, a Frappe-native AI workflow platform.

The platform is inspired by ComfyUI-style node workflow concepts and Weave-like creative workflow UX, but it must not copy ComfyUI source code, UI assets, branding, or proprietary implementations from any product.

## Core product direction

```txt
Frappe-native workflow engine
+ custom canvas UI
+ API-provider-only execution
+ WaveSpeed as first provider
+ no local model execution
+ no local GPU dependency
```

## Required layers

```txt
api/
application/
domain/
engine/
node_registry/
providers/
infrastructure/
workers/
doctype/
tests/
```

## Layer responsibilities

```txt
api/              Whitelisted Frappe methods only
application/      Use-case orchestration and transaction boundary
domain/           Pure business rules, contracts, validation, policies
engine/           DAG execution, dependency resolution, run state machine
node_registry/    Node definitions, schemas, node execution contracts
providers/        External API provider adapters and normalization
infrastructure/   Repositories, file storage, queue, realtime helpers
workers/          Background execution, polling, recovery jobs
doctype/          Persistence only
tests/            Real integration, API, worker, provider, UI tests
```

## Documentation Location

The canonical Slow AI architecture docs and contracts are tracked in this repository under:

```txt
docs/
```

When working from the Frappe bench root, the compatibility path is:

```txt
apps/slow_ai/docs/
```

## Required reading before coding

```txt
docs/ARCHITECTURE.md
docs/CODING_RULES.md
docs/API_PROVIDER_ONLY_POLICY.md
docs/NO_LOCAL_MODEL_POLICY.md
docs/COMFYUI_REFERENCE_MAPPING.md
docs/DOMAIN_MODEL.md
docs/DOCTYPE_DESIGN.md
docs/WORKFLOW_JSON_SPEC.md
docs/NODE_CONTRACT.md
docs/PROVIDER_CONTRACT.md
docs/RUN_STATE_MACHINE.md
docs/WORKER_DESIGN.md
docs/TESTING_POLICY.md
docs/INTEGRATION_TEST_MATRIX.md
docs/DEFINITION_OF_DONE.md
```

For feature-specific work, also read and update the relevant contract/design docs in `docs/`, such as API methods, canvas UI, public tool pages, run sharing, run output gallery, template versioning, provider design, billing, and run preflight contracts.

## Non-negotiable priorities

1. Enterprise Architecture
2. Clean Code
3. SOLID principles
4. Easy maintainability
5. Easy extension
6. Real integration tests
7. No mock-based acceptance tests
8. API-provider-only execution
9. No local model runtime
10. No ComfyUI source code copying

## Hard rules

1. Do not copy ComfyUI source code.
2. Do not copy ComfyUI UI code.
3. Do not implement checkpoint loading.
4. Do not implement CLIP loader.
5. Do not implement VAE loader.
6. Do not implement KSampler.
7. Do not implement CUDA/GPU memory management.
8. Do not scan local model folders.
9. Do not place provider calls in client JavaScript.
10. Do not place provider calls in DocType controllers.
11. Do not execute workflows inside normal HTTP requests.
12. Do not execute editable workflow drafts directly.
13. Always create immutable `AI Workflow Version` before running.
14. Always create or update `AI Node Run` for every node execution.
15. Always create `AI Provider Job` before every external provider call.
16. Always create `AI Asset` for every generated or uploaded output used by a workflow.
17. Always create `AI Credit Ledger` for every credit or cost movement.
18. Node logic must live only in `node_registry/`.
19. Provider logic must live only in `providers/`.
20. Workflow execution must live only in `engine/` and `workers/`.
21. API methods must call application services only.
22. DocType controllers must not contain provider or workflow execution logic.
23. No duplicated model pricing logic.
24. No direct SQL unless documented and justified.
25. No business logic in React canvas components.
26. No hidden background behavior without run logs.
27. Any new DocType must be added to the Slow AI workspace.
28. Add a workspace chart for a new DocType when a chart is applicable.

## Permanent DocTypes

```txt
AI Project
AI Project Member
AI Workflow
AI Workflow Version
AI Workflow Run
AI Node Run
AI Asset
AI Provider Job
AI Model
AI Provider Account
AI Credit Ledger
AI Workflow Template
AI Workflow Template Version
AI Tool Run Share
```

## Core execution flow

```txt
AI Workflow draft
→ graph validation
→ AI Workflow Version immutable snapshot
→ AI Workflow Run
→ AI Node Run records
→ Frappe background worker
→ NodeDefinition execution
→ ProviderAdapter call when needed
→ AI Provider Job
→ AI Asset
→ AI Credit Ledger
→ realtime event
→ run history
```

## Verification commands

```bash
bench --site saas run-tests --app slow_ai
```

Real provider tests:

```bash
SLOW_AI_REAL_PROVIDER_TESTS=1 WAVESPEED_API_KEY=xxx bench --site saas run-tests --app slow_ai
```
