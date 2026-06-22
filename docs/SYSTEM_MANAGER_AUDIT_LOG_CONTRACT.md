# System Manager Audit Log Contract

Slow AI uses Frappe-native audit surfaces for System Manager and project
governance actions. The current design does not add a custom audit DocType.

Audit evidence may come from:

- Frappe `Version` rows for tracked DocTypes when `doc.save` changes fields
- `owner`, `creation`, `modified`, and `modified_by` fields on persisted records
- append-only business records such as `AI Credit Ledger`, `AI Workflow Template Version`, and `AI Tool Run Share`

Governance actions covered by this contract include:

- `AI Project Member` add, role update, and disable
- `AI Provider Account` create, set default, and disable
- `AI Model` status, pricing, and metadata updates
- `AI Workflow Template` submit, approve, reject, archive, and rollback
- `AI Credit Ledger` credit top-up
- System Manager run recovery inspect, resume, and expire
- `AI Tool Run Share` create and disable

Rejected governance actions must fail before creating misleading audit or
business records. They must not create workflow versions, workflow runs, node
runs, provider jobs, assets, ledger rows, share rows, enqueue workers, or call
providers unless the action itself explicitly permits that side effect.

Audit/read payloads must remain safe. They must not expose provider secrets,
provider account names, raw provider request/response/error JSON, raw provider
URLs, API keys, Authorization headers, stack traces, or workflow draft internals
outside explicitly safe authenticated workflow APIs.

Coverage lives in:

```txt
slow_ai/tests/integration/test_system_manager_audit_log_matrix.py
```
