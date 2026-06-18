"""Domain exceptions for slow_ai."""


class SlowAIError(Exception):
    """Base exception for expected slow_ai failures."""


class GraphValidationError(SlowAIError):
    """Raised when a workflow graph violates the execution contract."""


class StateTransitionError(SlowAIError):
    """Raised when a run state transition is not allowed."""


class RegistryError(SlowAIError):
    """Raised when a registry lookup or registration fails."""


class ProviderInvariantError(SlowAIError):
    """Raised when provider execution invariants are violated."""
