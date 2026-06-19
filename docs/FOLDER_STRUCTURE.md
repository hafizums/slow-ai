# Folder Structure

Target structure:

```txt
slow_ai/
├── slow_ai/
│   ├── api/
│   ├── application/
│   ├── domain/
│   ├── engine/
│   ├── node_registry/
│   ├── providers/
│   ├── infrastructure/
│   ├── workers/
│   ├── doctype/
│   └── tests/
│       ├── integration/
│       ├── api/
│       ├── worker/
│       ├── provider/
│       ├── ui/
│       └── fixtures/
```

Task 01 platform kernel files:

```txt
slow_ai/domain/
├── exceptions.py
├── graph_validator.py
├── ports.py
├── status.py
└── workflow_graph.py

slow_ai/engine/
├── dag.py
├── executor.py
├── node_runner.py
└── state_machine.py

slow_ai/node_registry/
├── contracts.py
├── registry.py
├── schema.py
└── nodes/
    └── provider.py

slow_ai/domain/workflow_json.py
slow_ai/api/
├── assets.py
├── nodes.py
├── queue.py
├── runs.py
└── workflows.py

slow_ai/application/run_service.py
slow_ai/application/node_catalog.py
slow_ai/application/workflow_validation.py
slow_ai/application/assets.py
slow_ai/application/queue.py
slow_ai/application/runs.py
slow_ai/application/templates.py
slow_ai/application/workflows.py

slow_ai/providers/
├── contracts.py
├── registry.py
└── wavespeed/
    ├── adapter.py
    ├── auth.py
    ├── client.py
    ├── errors.py
    ├── models.py
    └── normalizer.py

slow_ai/infrastructure/provider_jobs.py
slow_ai/infrastructure/provider_outputs.py
slow_ai/infrastructure/queue.py
slow_ai/infrastructure/realtime.py

slow_ai/application/contracts.py
slow_ai/doctype/contracts.py
slow_ai/slow_ai/doctype/
slow_ai/infrastructure/repositories.py
slow_ai/workers/*.py
slow_ai/slow_ai/page/slow_ai_canvas/
slow_ai/tests/integration/test_platform_kernel.py
slow_ai/tests/integration/test_api_methods.py
slow_ai/tests/integration/test_provider_nodes.py
slow_ai/tests/integration/test_provider_wavespeed.py
slow_ai/tests/integration/test_workers_realtime.py
slow_ai/tests/integration/test_asset_ledger_pipeline.py
slow_ai/tests/integration/test_canvas_placeholder.py
slow_ai/tests/integration/test_tool_mode_design.py
```

The platform kernel is intentionally UI-free and provider-runtime-free. Concrete
DocType JSON, repository adapters, API methods, worker execution logic, and the
initial API-only canvas placeholder are added by later tasks.
