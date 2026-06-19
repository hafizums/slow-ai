# Review Checklist

## Block if any are true

```txt
ComfyUI source code copied
Local model runtime introduced
Provider call in frontend
Provider call in DocType controller
Workflow executes draft directly
External call without AI Provider Job
Generated file without AI Asset
Cost movement without AI Credit Ledger
Mock-based acceptance proof
Engine hardcodes provider or node type
Boundary gate removed or bypassed
```

## Architecture review

```txt
Correct layer used?
DocTypes persistence only?
Application service used?
Engine remains node/provider agnostic?
Provider isolated?
Workers used for long work?
Boundary gate updated when contracts change?
```

## Test review

```txt
Real DocTypes used?
Persisted state asserted?
API tested where needed?
Worker path tested where needed?
Provider test gated by env vars?
Architecture boundary gate run?
```

## Automated boundary gate

```txt
slow_ai/tests/integration/test_architecture_boundaries.py
```

This test is part of the normal `bench --site saas run-tests --app slow_ai`
suite. It blocks accidental provider calls in API/client/DocType layers, local
model runtime terms in production code, ComfyUI references in production code,
direct SQL, and API methods that stop delegating to application services.
