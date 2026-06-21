"""Persisted project/user/provider run quota policy."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

import frappe
from frappe.utils import nowdate

from slow_ai.domain.exceptions import RunPreflightError
from slow_ai.domain.status import ProviderJobStatus, WorkflowRunStatus


ACTIVE_WORKFLOW_RUN_STATUSES = (
    WorkflowRunStatus.QUEUED.value,
    WorkflowRunStatus.RUNNING.value,
    WorkflowRunStatus.WAITING_PROVIDER.value,
)
ACTIVE_PROVIDER_JOB_STATUSES = (
    ProviderJobStatus.QUEUED.value,
    ProviderJobStatus.SUBMITTING.value,
    ProviderJobStatus.SUBMITTED.value,
    ProviderJobStatus.WAITING_PROVIDER.value,
)
DAILY_SPEND_LEDGER_TYPES = ("DEBIT", "RESERVE", "RELEASE")


@dataclass(frozen=True)
class ProjectRunQuota:
    max_active_runs: int | None
    max_active_runs_per_user: int | None
    daily_project_spend_cap_usd: Decimal | None
    daily_user_spend_cap_usd: Decimal | None


def assert_run_quota_allows_start(
    *,
    project: str,
    provider_runs: Iterable[Any],
    estimated_cost_usd: Decimal,
    user: str | None = None,
) -> None:
    project_name = _require_project(project)
    current_user = user or frappe.session.user
    quota = _project_quota(project_name)
    provider_runs_tuple = tuple(provider_runs)

    _assert_project_active_runs(project_name, quota.max_active_runs)
    _assert_user_active_runs(project_name, current_user, quota.max_active_runs_per_user)
    _assert_provider_account_capacity(provider_runs_tuple)
    _assert_daily_spend_caps(project_name, current_user, estimated_cost_usd, quota)


def _assert_project_active_runs(project: str, limit: int | None) -> None:
    if limit is None:
        return
    active_count = frappe.db.count(
        "AI Workflow Run",
        {
            "project": project,
            "status": ["in", ACTIVE_WORKFLOW_RUN_STATUSES],
        },
    )
    if active_count >= limit:
        raise RunPreflightError(
            f"Project active run limit reached ({active_count}/{limit}). "
            "Wait for an active run to finish before starting another run."
        )


def _assert_user_active_runs(project: str, user: str, limit: int | None) -> None:
    if limit is None:
        return
    active_count = frappe.db.count(
        "AI Workflow Run",
        {
            "project": project,
            "owner": user,
            "status": ["in", ACTIVE_WORKFLOW_RUN_STATUSES],
        },
    )
    if active_count >= limit:
        raise RunPreflightError(
            f"User active run limit reached ({active_count}/{limit}). "
            "Wait for one of your active runs to finish before starting another run."
        )


def _assert_provider_account_capacity(provider_runs: tuple[Any, ...]) -> None:
    requested_by_account = Counter(run.provider_account for run in provider_runs if run.provider_account)
    for provider_account, requested_count in requested_by_account.items():
        limit = _provider_account_active_job_limit(provider_account)
        if limit is None:
            continue
        active_count = frappe.db.count(
            "AI Provider Job",
            {
                "provider_account": provider_account,
                "status": ["in", ACTIVE_PROVIDER_JOB_STATUSES],
            },
        )
        if active_count + requested_count > limit:
            raise RunPreflightError(
                f"Provider account active job limit reached ({active_count}/{limit}). "
                "Wait for provider jobs on this account to finish before starting another run."
            )


def _assert_daily_spend_caps(
    project: str,
    user: str,
    estimated_cost_usd: Decimal,
    quota: ProjectRunQuota,
) -> None:
    if estimated_cost_usd <= 0:
        return
    if quota.daily_project_spend_cap_usd is not None:
        project_exposure = _daily_spend_exposure(project=project)
        projected = project_exposure + estimated_cost_usd
        if projected > quota.daily_project_spend_cap_usd:
            raise RunPreflightError(
                "Daily project spend cap reached. "
                f"Projected spend {projected} USD exceeds cap {quota.daily_project_spend_cap_usd} USD."
            )

    if quota.daily_user_spend_cap_usd is not None:
        user_exposure = _daily_spend_exposure(project=project, user=user)
        projected = user_exposure + estimated_cost_usd
        if projected > quota.daily_user_spend_cap_usd:
            raise RunPreflightError(
                "Daily user spend cap reached. "
                f"Projected spend {projected} USD exceeds cap {quota.daily_user_spend_cap_usd} USD."
            )


def _daily_spend_exposure(*, project: str, user: str | None = None) -> Decimal:
    filters: dict[str, Any] = {
        "project": project,
        "ledger_type": ["in", DAILY_SPEND_LEDGER_TYPES],
        "creation": [">=", f"{nowdate()} 00:00:00"],
    }
    if user:
        filters["owner"] = user
    rows = frappe.get_all("AI Credit Ledger", filters=filters, fields=["ledger_type", "amount_usd"])
    exposure = Decimal("0")
    for row in rows:
        amount = _as_decimal(row.amount_usd)
        if row.ledger_type == "RELEASE":
            exposure -= amount
        else:
            exposure += amount
    return max(exposure, Decimal("0"))


def _project_quota(project: str) -> ProjectRunQuota:
    doc = frappe.get_doc("AI Project", project)
    return ProjectRunQuota(
        max_active_runs=_as_positive_int_or_none(getattr(doc, "max_active_runs", None)),
        max_active_runs_per_user=_as_positive_int_or_none(getattr(doc, "max_active_runs_per_user", None)),
        daily_project_spend_cap_usd=_as_positive_decimal_or_none(
            getattr(doc, "daily_project_spend_cap_usd", None)
        ),
        daily_user_spend_cap_usd=_as_positive_decimal_or_none(getattr(doc, "daily_user_spend_cap_usd", None)),
    )


def _provider_account_active_job_limit(provider_account: str) -> int | None:
    value = frappe.db.get_value("AI Provider Account", provider_account, "rate_limit_json")
    if not value:
        return None
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except json.JSONDecodeError as exc:
        raise RunPreflightError("Provider account rate limit configuration is invalid.") from exc
    if not isinstance(parsed, dict):
        return None
    return _as_positive_int_or_none(
        parsed.get("max_active_provider_jobs")
        or parsed.get("max_active_jobs")
        or parsed.get("concurrency")
    )


def _require_project(project: str) -> str:
    project_name = str(project or "").strip()
    if not project_name:
        raise RunPreflightError("Project is required for run quota checks.")
    if not frappe.db.exists("AI Project", project_name):
        raise RunPreflightError(f"AI Project does not exist: {project_name}.")
    return project_name


def _as_positive_int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _as_positive_decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed > 0 else None


def _as_decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, ValueError):
        return Decimal("0")
