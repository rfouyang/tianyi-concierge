"""REST routes for running, resuming, and cancelling a guide task."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api_concierge.dependencies import get_application, require_confirmation, robot_errors
from app.api_concierge.execution.schemas import RunTaskCommand
from app.application import ConciergeApplication
from component.task_execution.progress import (
    apply_progress_event,
    initial_stop_states,
    progress_rows,
)

router = APIRouter(prefix="/execution", tags=["execution"])


@router.get("")
def execution_state(
    application: Annotated[ConciergeApplication, Depends(get_application)],
) -> dict[str, object]:
    """The running task (if any) and the in-memory resume checkpoint."""
    operations = application.operations.snapshot()
    active = operations["active"]
    latest = operations["latest"]
    return {
        "running": active if active and active["kind"] == "task" else None,
        "latest": latest if latest and latest["kind"] == "task" else None,
        "checkpoint": application.task_execution.get_resume_checkpoint(),
    }


@router.post("/run", status_code=status.HTTP_202_ACCEPTED)
def run_task(
    command: RunTaskCommand,
    application: Annotated[ConciergeApplication, Depends(get_application)],
) -> dict[str, object]:
    return _start(application, command, resume=False)


@router.post("/resume", status_code=status.HTTP_202_ACCEPTED)
def resume_task(
    command: RunTaskCommand,
    application: Annotated[ConciergeApplication, Depends(get_application)],
) -> dict[str, object]:
    return _start(application, command, resume=True)


@router.post("/cancel")
def cancel_task(
    application: Annotated[ConciergeApplication, Depends(get_application)],
) -> dict[str, object]:
    """Cancel the running task; Tianyi returns to the dock if it had left."""
    cancelled = application.task_execution.cancel()
    return {
        "cancelled": cancelled,
        "message": (
            "Cancellation requested. Waiting for the robot to stop and return safely."
            if cancelled
            else "No task is currently running."
        ),
    }


def _start(
    application: ConciergeApplication,
    command: RunTaskCommand,
    *,
    resume: bool,
) -> dict[str, object]:
    require_confirmation(
        command.arms_confirmed,
        "Confirm Tianyi arm motion: both arm areas are clear and the emergency stop is ready",
    )
    executor = application.task_execution
    with robot_errors("Start task"):
        task = application.task_design.get_task(command.task_id)
        checkpoint = executor.get_resume_checkpoint(command.task_id)
        if resume and checkpoint is None:
            raise HTTPException(
                status_code=409, detail="No resumable execution exists for the selected task"
            )
        start_index = checkpoint["next_stop_index"] if resume else 0
        stop_states = initial_stop_states(len(task["stops"]), start_index)

        def on_event(operation: dict, event: dict) -> None:
            apply_progress_event(stop_states, event)
            operation["progress"] = {
                "task_id": task["id"],
                "task_name": task["name"],
                "rows": progress_rows(task, stop_states),
                "stop_index": event.get("stop_index"),
                "stop_count": len(task["stops"]),
                "last_event": event,
            }

        def events():
            generator = (
                executor.resume_events(command.task_id, body_actions_confirmed=True)
                if resume
                else executor.run_events(command.task_id, body_actions_confirmed=True)
            )
            try:
                yield from generator
            finally:
                application.status.request_refresh()

        return application.operations.start_events(
            "task",
            f"{'Resume' if resume else 'Run'} {task['name']}",
            events,
            details={"task_id": task["id"], "task_name": task["name"], "resume": resume},
            on_event=on_event,
        )
