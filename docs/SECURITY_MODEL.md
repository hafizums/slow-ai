# Security Model

## Secrets

Provider API keys must be stored in `AI Provider Account` using secure secret/password field patterns.

Do not expose API keys to client JavaScript.

Do not log API keys.

## API security

Every whitelisted method must enforce permissions.

Do not rely only on client-side filtering.

## Asset security

Asset access must check ownership/project permission.

## Error security

Do not expose:

```txt
Provider headers
API keys
Stack traces
Internal paths
Raw sensitive provider responses
```
