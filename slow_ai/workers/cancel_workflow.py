"""Workflow cancellation worker entrypoint."""


def cancel_workflow(workflow_run_name: str) -> None:
    raise NotImplementedError(f"Workflow cancellation worker is not implemented yet: {workflow_run_name}")
