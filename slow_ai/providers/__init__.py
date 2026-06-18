"""External API provider adapter contracts and registries."""

from slow_ai.providers.contracts import (
    NormalizedProviderResult,
    ProviderAdapter,
    ProviderJobRequest,
    ProviderSubmission,
)
from slow_ai.providers.registry import ProviderRegistry, create_default_provider_registry

__all__ = [
    "NormalizedProviderResult",
    "ProviderAdapter",
    "ProviderJobRequest",
    "ProviderRegistry",
    "ProviderSubmission",
    "create_default_provider_registry",
]
