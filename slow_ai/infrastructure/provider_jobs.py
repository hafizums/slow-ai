"""Frappe persistence for AI Provider Job lifecycle."""

from __future__ import annotations

from typing import Any, Mapping

import frappe
from frappe.utils import now_datetime

from slow_ai.domain.exceptions import ProviderInvariantError
from slow_ai.domain.snapshots import canonical_json
from slow_ai.domain.status import PROVIDER_JOB_TERMINAL_STATUSES, ProviderJobStatus
from slow_ai.engine.state_machine import transition_provider_job
from slow_ai.infrastructure.provider_accounts import resolve_provider_account_name
from slow_ai.infrastructure.realtime import publish_provider_job_update
from slow_ai.providers.contracts import NormalizedProviderResult, ProviderJobRequest


class ProviderJobRepository:
    def create_queued_job(self, request: ProviderJobRequest) -> str:
        provider_account_name = self._resolve_provider_account(
            request.provider,
            request.provider_account_name,
            request.project_name,
        )
        model_name = self._resolve_model(request.model)
        provider_job = frappe.get_doc(
            {
                "doctype": "AI Provider Job",
                "node_run": request.node_run_name,
                "provider": request.provider,
                "provider_account": provider_account_name,
                "model": model_name,
                "status": ProviderJobStatus.QUEUED.value,
                "idempotency_key": request.idempotency_key,
                "request_json": canonical_json(request.input_data),
            }
        ).insert(ignore_permissions=True)
        return provider_job.name

    def _resolve_provider_account(
        self,
        provider: str,
        provider_account_name: str | None,
        project_name: str | None,
    ) -> str | None:
        return resolve_provider_account_name(
            provider,
            provider_account_name,
            project_name=project_name,
            error_cls=ProviderInvariantError,
        )

    def _resolve_model(self, model_ref: str) -> str:
        if frappe.db.exists("AI Model", model_ref):
            return model_ref
        for fieldname in ("model_id", "model_slug"):
            matches = frappe.get_all(
                "AI Model",
                filters={fieldname: model_ref},
                fields=["name"],
                order_by="creation asc",
                limit=1,
            )
            if matches:
                return matches[0].name
        return model_ref

    def get(self, provider_job_name: str):
        return frappe.get_doc("AI Provider Job", provider_job_name)

    def get_by_idempotency_key(self, idempotency_key: str) -> str | None:
        return frappe.db.get_value(
            "AI Provider Job",
            {"idempotency_key": idempotency_key},
            "name",
        )

    def mark_submitting(self, provider_job_name: str) -> None:
        doc = self.get(provider_job_name)
        target = transition_provider_job(
            ProviderJobStatus(doc.status),
            ProviderJobStatus.SUBMITTING,
        )
        frappe.db.set_value("AI Provider Job", provider_job_name, "status", target.value)
        publish_provider_job_update(provider_job_name, target.value)

    def apply_result(
        self,
        provider_job_name: str,
        result: NormalizedProviderResult,
        raw_response: Mapping[str, Any],
    ) -> None:
        doc = self.get(provider_job_name)
        target = ProviderJobStatus(result.status)
        values: dict[str, Any] = {
            "response_json": canonical_json(raw_response),
            "cost_usd": result.cost_usd,
        }
        if result.external_job_id:
            values["external_job_id"] = result.external_job_id
        if result.error is not None:
            values["raw_error_json"] = canonical_json(result.error)
        if target in {
            ProviderJobStatus.SUBMITTED,
            ProviderJobStatus.WAITING_PROVIDER,
            ProviderJobStatus.SUCCEEDED,
        } and not doc.submitted_at:
            values["submitted_at"] = now_datetime()
        if target in PROVIDER_JOB_TERMINAL_STATUSES:
            values["completed_at"] = now_datetime()

        current = ProviderJobStatus(doc.status)
        if current != target:
            for next_status in self._transition_path(current, target):
                transition_provider_job(current, next_status)
                current = next_status
            values["status"] = target.value

        frappe.db.set_value("AI Provider Job", provider_job_name, values)
        extra: dict[str, Any] = {}
        if result.external_job_id:
            extra["external_job_id"] = result.external_job_id
        if result.error is not None:
            extra["error"] = result.error
        publish_provider_job_update(provider_job_name, target.value, extra or None)

    def mark_cancelled(self, provider_job_name: str, raw_response: Mapping[str, Any] | None = None) -> None:
        doc = self.get(provider_job_name)
        target = transition_provider_job(ProviderJobStatus(doc.status), ProviderJobStatus.CANCELLED)
        values: dict[str, Any] = {"status": target.value, "completed_at": now_datetime()}
        if raw_response is not None:
            values["response_json"] = canonical_json(raw_response)
        frappe.db.set_value("AI Provider Job", provider_job_name, values)
        publish_provider_job_update(provider_job_name, target.value)

    def _transition_path(
        self,
        current: ProviderJobStatus,
        target: ProviderJobStatus,
    ) -> tuple[ProviderJobStatus, ...]:
        if current == ProviderJobStatus.SUBMITTING and target in {
            ProviderJobStatus.WAITING_PROVIDER,
            ProviderJobStatus.SUCCEEDED,
        }:
            return (ProviderJobStatus.SUBMITTED, target)
        if current == ProviderJobStatus.SUBMITTING and target == ProviderJobStatus.EXPIRED:
            return (
                ProviderJobStatus.SUBMITTED,
                ProviderJobStatus.WAITING_PROVIDER,
                ProviderJobStatus.EXPIRED,
            )
        if current == ProviderJobStatus.SUBMITTED and target == ProviderJobStatus.EXPIRED:
            return (ProviderJobStatus.WAITING_PROVIDER, target)
        return (target,)
