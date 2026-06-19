"""Server-side workflow run preflight policy."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import frappe

from slow_ai.application.billing import assert_project_has_balance
from slow_ai.application.contracts import WorkflowDraft
from slow_ai.application.models import pricing_summary_from_json
from slow_ai.domain.exceptions import RunPreflightError
from slow_ai.domain.workflow_graph import WorkflowGraph, WorkflowNode
from slow_ai.infrastructure.provider_accounts import resolve_provider_account_name


@dataclass(frozen=True)
class RunPreflightPolicy:
    require_known_pricing: bool = True
    max_estimated_cost_usd: Decimal | None = None

    @classmethod
    def from_frappe_conf(cls) -> "RunPreflightPolicy":
        return cls(
            require_known_pricing=_as_bool(
                frappe.conf.get("slow_ai_run_preflight_require_known_pricing", True)
            ),
            max_estimated_cost_usd=_as_decimal_or_none(
                frappe.conf.get("slow_ai_run_preflight_max_cost_usd")
            ),
        )


@dataclass(frozen=True)
class ProviderRunPreflight:
    node_id: str
    node_type: str
    provider: str
    model: str
    model_name: str
    provider_account: str
    estimated_cost_usd: Decimal


@dataclass(frozen=True)
class RunPreflightResult:
    provider_runs: tuple[ProviderRunPreflight, ...]
    estimated_cost_usd: Decimal


class RunPreflightService:
    def __init__(self, policy: RunPreflightPolicy | None = None) -> None:
        self.policy = policy or RunPreflightPolicy.from_frappe_conf()

    def assert_can_start(self, draft: WorkflowDraft, graph: WorkflowGraph) -> RunPreflightResult:
        provider_runs: list[ProviderRunPreflight] = []
        total_estimated_cost = Decimal("0")

        for node in graph.nodes:
            if not is_provider_node(node):
                continue
            provider_run = self._inspect_provider_node(node, draft.project)
            provider_runs.append(provider_run)
            total_estimated_cost += provider_run.estimated_cost_usd

        if self.policy.max_estimated_cost_usd is not None:
            if total_estimated_cost > self.policy.max_estimated_cost_usd:
                raise RunPreflightError(
                    "Workflow estimated provider cost "
                    f"{total_estimated_cost} USD exceeds configured budget "
                    f"{self.policy.max_estimated_cost_usd} USD."
                )

        if total_estimated_cost > Decimal("0"):
            assert_project_has_balance(draft.project, total_estimated_cost)

        return RunPreflightResult(
            provider_runs=tuple(provider_runs),
            estimated_cost_usd=total_estimated_cost,
        )

    def _inspect_provider_node(self, node: WorkflowNode, project_name: str) -> ProviderRunPreflight:
        provider = str(node.config.get("provider") or "").strip()
        model_ref = str(node.config.get("model") or "").strip()
        if not provider:
            raise RunPreflightError(f"Provider node {node.id} is missing provider.")
        if not model_ref:
            raise RunPreflightError(f"Provider node {node.id} is missing model.")

        model = self._resolve_model(model_ref)
        if model.provider != provider:
            raise RunPreflightError(
                f"Provider node {node.id} model {model_ref} belongs to provider "
                f"{model.provider}, not {provider}."
            )
        if model.status != "ENABLED":
            raise RunPreflightError(f"Provider node {node.id} uses disabled model {model_ref}.")
        if getattr(model, "category", None) and model.category != "provider":
            raise RunPreflightError(
                f"Provider node {node.id} uses model {model_ref} with non-provider category {model.category}."
            )
        if getattr(model, "node_type", None) and model.node_type != node.type:
            raise RunPreflightError(
                f"Provider node {node.id} uses model {model_ref} for node type "
                f"{model.node_type}, not {node.type}."
            )

        pricing = pricing_summary_from_json(model.pricing_json)
        if not pricing["pricing_known"] and self.policy.require_known_pricing:
            raise RunPreflightError(
                f"Provider node {node.id} uses model {model_ref} without known pricing."
            )

        provider_account = self._resolve_provider_account(
            provider,
            node.config.get("provider_account"),
            project_name,
        )
        return ProviderRunPreflight(
            node_id=node.id,
            node_type=node.type,
            provider=provider,
            model=model_ref,
            model_name=model.name,
            provider_account=provider_account,
            estimated_cost_usd=_as_decimal_or_zero(pricing["estimated_cost_usd"]),
        )

    def _resolve_model(self, model_ref: str):
        if frappe.db.exists("AI Model", model_ref):
            return frappe.get_doc("AI Model", model_ref)
        matches = frappe.get_all(
            "AI Model",
            filters={"model_id": model_ref},
            fields=["name"],
            order_by="creation asc",
            limit=1,
        )
        if not matches:
            matches = frappe.get_all(
                "AI Model",
                filters={"model_slug": model_ref},
                fields=["name"],
                order_by="creation asc",
                limit=1,
            )
        if not matches:
            raise RunPreflightError(f"Provider model is not configured: {model_ref}.")
        return frappe.get_doc("AI Model", matches[0].name)

    def _resolve_provider_account(
        self,
        provider: str,
        provider_account_name: Any | None,
        project_name: str,
    ) -> str:
        account_name = resolve_provider_account_name(
            provider,
            provider_account_name,
            project_name=project_name,
            require_default=True,
            error_cls=RunPreflightError,
        )
        if not account_name:
            raise RunPreflightError(f"No active default provider account is configured for {provider}.")
        return account_name


def is_provider_node(node: WorkflowNode) -> bool:
    return node.type.startswith("provider_")


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(value)


def _as_decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise RunPreflightError("slow_ai_run_preflight_max_cost_usd must be a decimal value.") from exc
    if amount < 0:
        raise RunPreflightError("slow_ai_run_preflight_max_cost_usd cannot be negative.")
    return amount


def _as_decimal_or_zero(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")
