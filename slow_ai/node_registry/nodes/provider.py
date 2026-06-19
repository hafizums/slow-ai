"""Generic API-provider nodes."""

from __future__ import annotations

from typing import Any, Mapping

from slow_ai.domain.exceptions import ProviderInvariantError
from slow_ai.domain.ports import PortType
from slow_ai.domain.status import ProviderJobStatus
from slow_ai.infrastructure.provider_jobs import ProviderJobRepository
from slow_ai.infrastructure.provider_outputs import ProviderOutputService, get_workflow_run_project
from slow_ai.node_registry.contracts import ExecutionContext, NodeDefinition, NodeExecutionResult
from slow_ai.node_registry.nodes.base import ConfigSchemaMixin
from slow_ai.providers.contracts import ProviderJobRequest, ProviderSubmission
from slow_ai.providers.registry import ProviderRegistry, create_default_provider_registry


COMMON_CONFIG_FIELDS = frozenset({"provider", "model", "provider_account", "parameters"})


class ProviderNodeBase(ConfigSchemaMixin, NodeDefinition):
    category = "provider"
    version = "1.0.0"
    is_output_node = False
    output_asset_type: str
    output_port: str

    def __init__(
        self,
        *,
        provider_registry: ProviderRegistry | None = None,
        provider_jobs: ProviderJobRepository | None = None,
        provider_outputs: ProviderOutputService | None = None,
    ) -> None:
        self.provider_registry = provider_registry or create_default_provider_registry()
        self.provider_jobs = provider_jobs or ProviderJobRepository()
        self.provider_outputs = provider_outputs or ProviderOutputService()

    def config_schema(self) -> Mapping[str, Any]:
        return {
            "provider": {
                "type": PortType.TEXT.value,
                "value_type": "string",
                "required": True,
                "label": "Provider",
            },
            "model": {
                "type": PortType.TEXT.value,
                "value_type": "string",
                "required": True,
                "label": "Model",
            },
            "provider_account": {
                "type": "AI_PROVIDER_ACCOUNT",
                "value_type": "string",
                "required": False,
                "label": "Provider Account",
            },
            "parameters": {
                "type": PortType.JSON.value,
                "value_type": "object",
                "required": False,
                "label": "Provider Parameters",
            },
        }

    def output_schema(self) -> Mapping[str, Any]:
        return {
            self.output_port: {"type": self.output_port_type().value, "label": self.output_port.title()},
            "result": {"type": PortType.JSON.value, "label": "Provider Result"},
        }

    def output_port_type(self) -> PortType:
        return {
            "IMAGE": PortType.IMAGE_ASSET,
            "VIDEO": PortType.VIDEO_ASSET,
            "AUDIO": PortType.AUDIO_ASSET,
        }[self.output_asset_type]

    def execute(
        self,
        context: ExecutionContext,
        inputs: Mapping[str, Any],
        config: Mapping[str, Any],
    ) -> NodeExecutionResult:
        self.validate_inputs(inputs)
        self.validate_config(config)
        input_data = self.build_input_data(inputs, config)
        provider = str(config["provider"])
        model = str(config["model"])
        idempotency_key = f"{context.node_run_name}:{self.type}"
        project_name = context.project_name or get_workflow_run_project(context.workflow_run_name)
        provider_job_name = self._get_or_create_provider_job(
            ProviderJobRequest(
                provider=provider,
                model=model,
                input_data=input_data,
                node_run_name=context.node_run_name,
                provider_account_name=config.get("provider_account"),
                project_name=project_name,
                idempotency_key=idempotency_key,
            )
        )
        adapter = self.provider_registry.get(provider)
        provider_job = self.provider_jobs.get(provider_job_name)
        if provider_job.status in {
            ProviderJobStatus.SUBMITTED.value,
            ProviderJobStatus.WAITING_PROVIDER.value,
        }:
            result = adapter.poll_job(provider_job_name)
        elif provider_job.status in {ProviderJobStatus.QUEUED.value, ProviderJobStatus.SUBMITTING.value}:
            result = adapter.submit_job(
                ProviderSubmission(
                    provider_job_name=provider_job_name,
                    model=provider_job.model,
                    input_data=input_data,
                )
            )
        else:
            raise ProviderInvariantError(
                f"Provider job is not executable from status {provider_job.status}: {provider_job_name}"
            )

        if result.status != ProviderJobStatus.SUCCEEDED.value:
            return NodeExecutionResult(
                outputs={
                    "result": {
                        "provider_job": provider_job_name,
                        "external_job_id": result.external_job_id,
                        "status": result.status,
                    }
                },
                cost_usd=result.cost_usd,
                provider_job_name=provider_job_name,
                waiting_provider=True,
            )
        if not result.outputs:
            raise ProviderInvariantError(f"Provider job returned no outputs: {provider_job_name}")

        materialized = self.provider_outputs.materialize(
            project_name=project_name,
            workflow_run_name=context.workflow_run_name,
            node_run_name=context.node_run_name,
            provider_job_name=provider_job_name,
            result=result,
            description=f"{self.label} provider cost",
            required_asset_type=self.output_asset_type,
            output_port=self.output_port,
        )
        return NodeExecutionResult(
            outputs=materialized.node_outputs,
            cost_usd=result.cost_usd,
            provider_job_name=provider_job_name,
            asset_names=materialized.asset_names,
        )

    def build_input_data(self, inputs: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
        parameters = config.get("parameters") or {}
        input_data = dict(parameters)
        for key, value in config.items():
            if key in COMMON_CONFIG_FIELDS:
                continue
            input_data[key] = value
        input_data.update(inputs)
        return input_data

    def _get_or_create_provider_job(self, request: ProviderJobRequest) -> str:
        if request.idempotency_key:
            existing = self.provider_jobs.get_by_idempotency_key(request.idempotency_key)
            if existing:
                return existing
        return self.provider_jobs.create_queued_job(request)


class ProviderTextToImageNode(ProviderNodeBase):
    type = "provider_text_to_image"
    label = "Provider Text To Image"
    output_asset_type = "IMAGE"
    output_port = "image"

    def input_schema(self) -> Mapping[str, Any]:
        return {"prompt": {"type": PortType.TEXT.value, "required": True, "label": "Prompt"}}


class ProviderImageToImageNode(ProviderNodeBase):
    type = "provider_image_to_image"
    label = "Provider Image To Image"
    output_asset_type = "IMAGE"
    output_port = "image"

    def input_schema(self) -> Mapping[str, Any]:
        return {
            "prompt": {"type": PortType.TEXT.value, "required": True, "label": "Prompt"},
            "image": {"type": PortType.IMAGE_ASSET.value, "required": True, "label": "Image"},
            "mask": {"type": PortType.MASK_ASSET.value, "required": False, "label": "Mask"},
        }


class ProviderImageToVideoNode(ProviderNodeBase):
    type = "provider_image_to_video"
    label = "Provider Image To Video"
    output_asset_type = "VIDEO"
    output_port = "video"

    def input_schema(self) -> Mapping[str, Any]:
        return {
            "image": {"type": PortType.IMAGE_ASSET.value, "required": True, "label": "Image"},
            "prompt": {"type": PortType.TEXT.value, "required": False, "label": "Prompt"},
        }


class ProviderStartEndToVideoNode(ProviderNodeBase):
    type = "provider_start_end_to_video"
    label = "Provider Start End To Video"
    output_asset_type = "VIDEO"
    output_port = "video"

    def input_schema(self) -> Mapping[str, Any]:
        return {
            "start_image": {
                "type": PortType.IMAGE_ASSET.value,
                "required": True,
                "label": "Start Image",
            },
            "end_image": {
                "type": PortType.IMAGE_ASSET.value,
                "required": True,
                "label": "End Image",
            },
            "prompt": {"type": PortType.TEXT.value, "required": False, "label": "Prompt"},
        }


class ProviderTextToSpeechNode(ProviderNodeBase):
    type = "provider_text_to_speech"
    label = "Provider Text To Speech"
    output_asset_type = "AUDIO"
    output_port = "audio"

    def input_schema(self) -> Mapping[str, Any]:
        return {"text": {"type": PortType.TEXT.value, "required": True, "label": "Text"}}
