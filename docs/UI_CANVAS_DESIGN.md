# UI Canvas Design

## Core rule

The canvas is an editor and monitor.

It is not the execution engine.

## UI can

```txt
Render nodes
Render edges
Edit config
Save workflow
Start run
Show run status
Preview assets
```

## UI must not

```txt
Call WaveSpeed directly
Poll provider directly
Execute graph
Calculate final billing
Read provider secrets
```

## Recommended UI stack

```txt
Custom Frappe page
React
React Flow
Frappe API calls
Frappe realtime
```
