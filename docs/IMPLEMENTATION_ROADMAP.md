# Implementation Roadmap

## Phase 0: Documentation and guardrails

```txt
AGENTS.md
Architecture docs
Codex skills
Default prompts
Definition of Done
Review checklist
```

## Phase 1: Platform kernel

```txt
Folder structure
Core DocTypes
Domain contracts
Node contract
Provider contract
Run state machine
Real integration test skeleton
```

## Phase 2: Workflow JSON and node registry

```txt
Workflow JSON validation
Node registry
Object info API
Initial non-provider nodes
```

## Phase 3: Engine core

```txt
Snapshot creation
Run creation
NodeRun creation
DAG runner
Node runner
Failure handling
Run history
```

## Phase 4: Provider API foundation

```txt
ProviderAdapter
AI Provider Account
AI Model
AI Provider Job
WaveSpeed adapter skeleton
Provider normalization
```

## Phase 5: Real WaveSpeed integration

```txt
Real submit
Real poll
Real asset creation
Real cost ledger if available
Real provider tests
```

## Phase 6: Workers and realtime

```txt
run_workflow
run_node
poll_provider_job
resume_workflow
realtime events
```

## Phase 7: Canvas UI

```txt
Custom Frappe page
React Flow canvas
Node palette from object_info
Config panel
Save workflow
Start run
Run monitor
Asset preview
```

## Phase 8: Tool/App mode

```txt
Tool Output node
Workflow Template
Simple generated form from workflow inputs
Reusable app mode
```
