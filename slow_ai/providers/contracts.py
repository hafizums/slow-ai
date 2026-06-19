"""Provider adapter contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Mapping

from slow_ai.domain.exceptions import ProviderInvariantError


@dataclass(frozen=True)
class ProviderJobRequest:
    provider: str
    model: str
    input_data: Mapping[str, Any]
    node_run_name: str | None = None
    provider_account_name: str | None = None
    project_name: str | None = None
    idempotency_key: str | None = None
    estimated_cost_usd: Decimal | float | str | None = None

    def __post_init__(self) -> None:
        if not self.provider:
            raise ProviderInvariantError("Provider is required before creating AI Provider Job.")
        if not self.model:
            raise ProviderInvariantError("Provider model is required before creating AI Provider Job.")


@dataclass(frozen=True)
class ProviderSubmission:
    provider_job_name: str
    model: str
    input_data: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not self.provider_job_name:
            raise ProviderInvariantError("AI Provider Job must exist before provider submission.")
        if not self.model:
            raise ProviderInvariantError("Provider model is required for provider submission.")


@dataclass(frozen=True)
class NormalizedProviderOutput:
    asset_type: str
    url: str
    mime_type: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NormalizedProviderResult:
    status: str
    external_job_id: str | None = None
    outputs: tuple[NormalizedProviderOutput, ...] = ()
    cost_usd: float = 0.0
    error: Mapping[str, Any] | None = None


class ProviderAdapter(ABC):
    provider_name: str

    @abstractmethod
    def submit_job(self, submission: ProviderSubmission) -> NormalizedProviderResult:
        """Submit an already-persisted provider job to an external API."""

    @abstractmethod
    def poll_job(self, provider_job_name: str) -> NormalizedProviderResult:
        """Poll an existing AI Provider Job."""

    @abstractmethod
    def cancel_job(self, provider_job_name: str) -> None:
        """Cancel an existing provider job."""

    @abstractmethod
    def normalize_result(self, raw_response: Mapping[str, Any]) -> NormalizedProviderResult:
        """Normalize provider-specific responses before they leave providers/."""

    @abstractmethod
    def estimate_cost(self, model: str, input_data: Mapping[str, Any]) -> Mapping[str, Any]:
        """Estimate cost through provider-specific pricing rules."""
