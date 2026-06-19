# Coding Rules

## Architecture rules

```txt
api/ calls application/
application/ coordinates use cases
domain/ contains rules
engine/ executes graphs
node_registry/ defines nodes
providers/ calls external APIs
infrastructure/ wraps Frappe services
workers/ runs long jobs
doctype/ persists data
```

## Provider rules

```txt
Provider code only in providers/
External call must create AI Provider Job
Provider response must be normalized
No API key in frontend
No provider call in DocType controller
```

## Engine rules

```txt
No hardcoded node types
No hardcoded provider names
No editable draft execution
No local model runtime
No if/else chain for node execution
```

## Testing rules

```txt
No mock-based acceptance tests
Real integration tests for real behavior
Real provider tests gated by env vars
Tests assert persisted state
```
