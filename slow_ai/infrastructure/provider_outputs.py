"""Asset and credit ledger pipeline for provider outputs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

import frappe

from slow_ai.application.models import pricing_summary_from_json
from slow_ai.domain.exceptions import ProviderInvariantError
from slow_ai.domain.snapshots import canonical_json
from slow_ai.domain.status import ProviderJobStatus
from slow_ai.providers.contracts import NormalizedProviderOutput, NormalizedProviderResult


ASSET_TYPE_TO_OUTPUT_PORT = {
    "IMAGE": "image",
    "VIDEO": "video",
    "AUDIO": "audio",
    "MASK": "mask",
    "JSON": "json",
    "TEXT": "text",
}


@dataclass(frozen=True)
class ProviderOutputMaterialization:
    asset_names: tuple[str, ...]
    ledger_name: str | None
    node_outputs: Mapping[str, Any]
    debit_amount_usd: float
    debit_cost_source: str


@dataclass(frozen=True)
class ProviderDebitDecision:
    amount_usd: Decimal
    cost_source: str


class AssetWriter:
    def create_uploaded_asset(
        self,
        *,
        project_name: str,
        asset_type: str,
        url: str | None = None,
        file: str | None = None,
        mime_type: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> str:
        asset = frappe.get_doc(
            {
                "doctype": "AI Asset",
                "project": project_name,
                "asset_type": asset_type,
                "url": url,
                "file": file,
                "mime_type": mime_type,
                "metadata_json": canonical_json(metadata or {}),
            }
        ).insert(ignore_permissions=True)
        return asset.name

    def create_provider_assets(
        self,
        *,
        project_name: str,
        workflow_run_name: str,
        node_run_name: str,
        provider_job_name: str,
        outputs: tuple[NormalizedProviderOutput, ...],
    ) -> tuple[str, ...]:
        existing_by_index = self.get_provider_assets_by_output_index(provider_job_name)
        if existing_by_index is None:
            return self.get_provider_assets(provider_job_name)

        asset_names: list[str] = []
        for index, output in enumerate(outputs, start=1):
            existing_asset = existing_by_index.get(index)
            if existing_asset:
                asset_names.append(existing_asset)
                continue
            metadata: dict[str, Any] = dict(output.metadata)
            metadata["provider_output_index"] = index
            asset_names.append(
                self.create_uploaded_asset(
                    project_name=project_name,
                    asset_type=output.asset_type,
                    url=output.url,
                    mime_type=output.mime_type,
                    metadata=metadata
                    | {
                        "source_workflow_run": workflow_run_name,
                        "source_node_run": node_run_name,
                        "source_provider_job": provider_job_name,
                    },
                )
            )
            frappe.db.set_value(
                "AI Asset",
                asset_names[-1],
                {
                    "source_workflow_run": workflow_run_name,
                    "source_node_run": node_run_name,
                    "source_provider_job": provider_job_name,
                    "metadata_json": canonical_json(metadata),
                },
            )
        return tuple(asset_names)

    def get_provider_assets(self, provider_job_name: str) -> tuple[str, ...]:
        rows = frappe.get_all(
            "AI Asset",
            filters={"source_provider_job": provider_job_name},
            fields=["name"],
            order_by="creation asc",
        )
        return tuple(row.name for row in rows)

    def get_provider_assets_by_output_index(self, provider_job_name: str) -> dict[int, str] | None:
        rows = frappe.get_all(
            "AI Asset",
            filters={"source_provider_job": provider_job_name},
            fields=["name", "metadata_json"],
            order_by="creation asc",
        )
        assets_by_index: dict[int, str] = {}
        for row in rows:
            metadata = _loads_json(row.metadata_json, {})
            output_index = metadata.get("provider_output_index")
            if output_index in (None, ""):
                return None
            try:
                index = int(output_index)
            except (TypeError, ValueError):
                return None
            assets_by_index.setdefault(index, row.name)
        return assets_by_index


class CreditLedgerService:
    def create_provider_debit(
        self,
        *,
        project_name: str,
        workflow_run_name: str,
        node_run_name: str,
        provider_job_name: str,
        amount_usd: float,
        description: str,
        cost_source: str = "ACTUAL",
    ) -> str | None:
        amount = _as_decimal_or_zero(amount_usd)
        if amount == 0:
            self._record_provider_debit_metadata(provider_job_name, amount, cost_source)
            return None
        existing = frappe.db.get_value(
            "AI Credit Ledger",
            {
                "provider_job": provider_job_name,
                "ledger_type": "DEBIT",
            },
            "name",
        )
        if existing:
            self._record_existing_provider_debit_metadata(provider_job_name, existing, cost_source)
            return existing

        ledger = frappe.get_doc(
            {
                "doctype": "AI Credit Ledger",
                "project": project_name,
                "workflow_run": workflow_run_name,
                "node_run": node_run_name,
                "provider_job": provider_job_name,
                "ledger_type": "DEBIT",
                "amount_usd": amount,
                "currency": "USD",
                "description": f"{description} ({cost_source.lower()} cost)",
                "reference_doctype": "AI Provider Job",
                "reference_name": provider_job_name,
            }
        ).insert(ignore_permissions=True)
        self._record_provider_debit_metadata(provider_job_name, amount, cost_source)
        return ledger.name

    def _record_existing_provider_debit_metadata(
        self,
        provider_job_name: str,
        ledger_name: str,
        cost_source: str,
    ) -> None:
        provider_job = frappe.get_doc("AI Provider Job", provider_job_name)
        if provider_job.debit_cost_source:
            return
        amount_usd = frappe.db.get_value("AI Credit Ledger", ledger_name, "amount_usd")
        self._record_provider_debit_metadata(provider_job_name, _as_decimal_or_zero(amount_usd), cost_source)

    def _record_provider_debit_metadata(
        self,
        provider_job_name: str,
        amount_usd: Decimal,
        cost_source: str,
    ) -> None:
        frappe.db.set_value(
            "AI Provider Job",
            provider_job_name,
            {
                "debit_cost_usd": amount_usd,
                "debit_cost_source": cost_source,
            },
        )


class ProviderOutputService:
    def __init__(
        self,
        *,
        asset_writer: AssetWriter | None = None,
        credit_ledger: CreditLedgerService | None = None,
    ) -> None:
        self.asset_writer = asset_writer or AssetWriter()
        self.credit_ledger = credit_ledger or CreditLedgerService()

    def materialize(
        self,
        *,
        project_name: str,
        workflow_run_name: str,
        node_run_name: str,
        provider_job_name: str,
        result: NormalizedProviderResult,
        description: str,
        required_asset_type: str | None = None,
        output_port: str | None = None,
    ) -> ProviderOutputMaterialization:
        if result.status != ProviderJobStatus.SUCCEEDED.value:
            raise ProviderInvariantError(
                f"Provider output materialization requires SUCCEEDED result: {provider_job_name}"
            )
        debit = resolve_provider_debit(provider_job_name, result)
        asset_names = self.asset_writer.create_provider_assets(
            project_name=project_name,
            workflow_run_name=workflow_run_name,
            node_run_name=node_run_name,
            provider_job_name=provider_job_name,
            outputs=result.outputs,
        )
        ledger_name = self.credit_ledger.create_provider_debit(
            project_name=project_name,
            workflow_run_name=workflow_run_name,
            node_run_name=node_run_name,
            provider_job_name=provider_job_name,
            amount_usd=float(debit.amount_usd),
            description=description,
            cost_source=debit.cost_source,
        )
        primary_asset = _primary_asset_name(
            result.outputs,
            asset_names,
            required_asset_type=required_asset_type,
        )
        primary_output_port = output_port or _output_port_for(result.outputs, primary_asset, asset_names)
        return ProviderOutputMaterialization(
            asset_names=asset_names,
            ledger_name=ledger_name,
            node_outputs={
                primary_output_port: primary_asset,
                "result": {
                    "provider_job": provider_job_name,
                    "external_job_id": result.external_job_id,
                    "assets": list(asset_names),
                    "status": result.status,
                    "ledger": ledger_name,
                    "debit_cost_usd": str(debit.amount_usd),
                    "debit_cost_source": debit.cost_source,
                },
            },
            debit_amount_usd=float(debit.amount_usd),
            debit_cost_source=debit.cost_source,
        )


class ProviderOutputRepository(ProviderOutputService):
    """Backward-compatible facade used by provider nodes."""

    def create_assets(
        self,
        *,
        project_name: str,
        workflow_run_name: str,
        node_run_name: str,
        provider_job_name: str,
        outputs: tuple[NormalizedProviderOutput, ...],
    ) -> tuple[str, ...]:
        return self.asset_writer.create_provider_assets(
            project_name=project_name,
            workflow_run_name=workflow_run_name,
            node_run_name=node_run_name,
            provider_job_name=provider_job_name,
            outputs=outputs,
        )

    def create_cost_ledger(
        self,
        *,
        project_name: str,
        workflow_run_name: str,
        node_run_name: str,
        provider_job_name: str,
        amount_usd: float,
        description: str,
    ) -> str | None:
        return self.credit_ledger.create_provider_debit(
            project_name=project_name,
            workflow_run_name=workflow_run_name,
            node_run_name=node_run_name,
            provider_job_name=provider_job_name,
            amount_usd=amount_usd,
            description=description,
        )


def get_workflow_run_project(workflow_run_name: str) -> str:
    return frappe.get_doc("AI Workflow Run", workflow_run_name).project


def resolve_provider_debit(
    provider_job_name: str,
    result: NormalizedProviderResult,
) -> ProviderDebitDecision:
    actual_cost = _as_decimal_or_zero(result.cost_usd)
    if actual_cost > 0:
        return ProviderDebitDecision(amount_usd=actual_cost, cost_source="ACTUAL")

    provider_job = frappe.get_doc("AI Provider Job", provider_job_name)
    estimated_cost = _as_decimal_or_zero(getattr(provider_job, "estimated_cost_usd", None))
    if estimated_cost > 0:
        return ProviderDebitDecision(amount_usd=estimated_cost, cost_source="ESTIMATED")

    model_pricing = _model_pricing_summary(getattr(provider_job, "model", None))
    model_estimate = _as_decimal_or_zero(model_pricing.get("estimated_cost_usd"))
    if model_estimate > 0:
        return ProviderDebitDecision(amount_usd=model_estimate, cost_source="ESTIMATED")
    if model_pricing.get("pricing_known") and model_estimate == 0:
        return ProviderDebitDecision(amount_usd=Decimal("0"), cost_source="ZERO_COST")

    raise ProviderInvariantError(
        f"Provider job has no actual or estimated cost; refusing to materialize output: {provider_job_name}"
    )


def _model_pricing_summary(model_name: str | None) -> dict[str, Any]:
    if not model_name or not frappe.db.exists("AI Model", model_name):
        return {"pricing_known": False, "estimated_cost_usd": None}
    pricing_json = frappe.db.get_value("AI Model", model_name, "pricing_json")
    return pricing_summary_from_json(pricing_json)


def _as_decimal_or_zero(value: Any | None) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")
    return amount if amount > 0 else Decimal("0")


def _loads_json(value: str | None, default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)


def _primary_asset_name(
    outputs: tuple[NormalizedProviderOutput, ...],
    asset_names: tuple[str, ...],
    *,
    required_asset_type: str | None,
) -> str:
    if not outputs:
        raise ValueError("Provider result has no outputs to materialize.")
    if required_asset_type is None:
        return asset_names[0]
    for index, output in enumerate(outputs):
        if output.asset_type == required_asset_type:
            return asset_names[index]
    raise ValueError(f"Provider result does not contain required asset type: {required_asset_type}")


def _output_port_for(
    outputs: tuple[NormalizedProviderOutput, ...],
    primary_asset: str,
    asset_names: tuple[str, ...],
) -> str:
    index = asset_names.index(primary_asset)
    return ASSET_TYPE_TO_OUTPUT_PORT.get(outputs[index].asset_type, "asset")
