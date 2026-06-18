"""Workflow run worker entrypoint."""

from slow_ai.engine.executor import run_workflow as execute_workflow


def run_workflow(workflow_run_name: str) -> None:
    """Execute a persisted workflow run from a background worker."""
    execute_workflow(workflow_run_name)
