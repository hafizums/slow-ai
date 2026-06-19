# Tool Mode Design

## Goal

Turn a workflow into a simplified reusable app.

## Concept

Workflow author builds:

```txt
Product Image
Prompt
Provider Image Generation
Provider Video Generation
Export Output
```

Tool mode exposes only selected inputs:

```txt
Upload product image
Enter product name
Choose style
Generate
```

## Rule

Tool mode must call the same run engine.

Do not create a separate execution path for tools.
