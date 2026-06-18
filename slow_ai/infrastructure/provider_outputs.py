"""Asset and credit ledger pipeline for provider outputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import frappe

from slow_ai.domain.snapshots import canonical_json
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
        existing = self.get_provider_assets(provider_job_name)
        if existing:
            return existing

        asset_names: list[str] = []
        for index, output in enumerate(outputs, start=1):
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
    ) -> str | None:
        if amount_usd == 0:
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
            return existing

        ledger = frappe.get_doc(
            {
                "doctype": "AI Credit Ledger",
                "project": project_name,
                "workflow_run": workflow_run_name,
                "node_run": node_run_name,
                "provider_job": provider_job_name,
                "ledger_type": "DEBIT",
                "amount_usd": amount_usd,
                "currency": "USD",
                "description": description,
                "reference_doctype": "AI Provider Job",
                "reference_name": provider_job_name,
            }
        ).insert(ignore_permissions=True)
        return ledger.name


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
            amount_usd=result.cost_usd,
            description=description,
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
                },
            },
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
