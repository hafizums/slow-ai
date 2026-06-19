# Definition of Done

A task is complete only when:

```txt
1. It follows AGENTS.md.
2. It follows docs/ARCHITECTURE.md.
3. It follows docs/CODING_RULES.md.
4. It follows docs/API_PROVIDER_ONLY_POLICY.md.
5. It does not introduce local model runtime.
6. It does not copy ComfyUI source code.
7. It preserves layer boundaries.
8. It uses immutable AI Workflow Version for runs.
9. It creates/updates AI Node Run for node execution.
10. It creates AI Provider Job before external calls.
11. It creates AI Asset for outputs.
12. It creates AI Credit Ledger for cost movement.
13. It adds/updates real integration tests.
14. Relevant tests pass.
15. Docs are updated if contracts changed.
16. The final response includes files changed, tests run, and known risks.
17. The architecture boundary gate passes for changes touching API, DocType,
    client, provider, worker, engine, or node-registry contracts.
```
