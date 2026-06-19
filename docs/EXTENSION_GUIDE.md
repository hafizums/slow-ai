# Extension Guide

## Add a new node

1. Create `node_registry/nodes/<node_name>.py`.
2. Implement `NodeDefinition`.
3. Add input/config/output schemas.
4. Register it in `NODE_REGISTRY`.
5. Add object_info metadata.
6. Add real integration test.
7. Update docs if contract changes.

Do not edit engine core.

## Add a new provider

1. Create `providers/<provider>/`.
2. Implement `ProviderAdapter`.
3. Add provider auth handling.
4. Add normalizer.
5. Register provider.
6. Add AI Provider Account support.
7. Add AI Model records.
8. Add real provider test gated by env vars.

Do not edit engine core.
