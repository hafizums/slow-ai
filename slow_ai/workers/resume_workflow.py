"""Workflow resume worker entrypoint."""

from slow_ai.engine.executor import run_workflow as execute_workflow


def resume_workflow(workflow_run_name: str) -> None:
    """Resume a persisted workflow run after provider progress."""
    execute_workflow(workflow_run_name)
