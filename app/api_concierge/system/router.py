"""Robot status, the operation feed, and the always-available stop."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api_concierge.dependencies import get_application, robot_errors
from app.application import ConciergeApplication

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/status")
def status(
    application: Annotated[ConciergeApplication, Depends(get_application)],
) -> dict[str, object]:
    """Return the cached robot snapshot and the current operation."""
    return {
        "robot": application.status.snapshot(),
        "operations": application.operations.snapshot(),
    }


@router.get("/operations")
def operations(
    application: Annotated[ConciergeApplication, Depends(get_application)],
) -> dict[str, object]:
    """The running operation and the last 20 finished ones, newest first."""
    return {
        "active": application.operations.snapshot()["active"],
        "history": application.operations.history(),
    }


@router.post("/stop")
def stop_robot(
    application: Annotated[ConciergeApplication, Depends(get_application)],
) -> dict[str, object]:
    """Cancel all motion immediately; this never waits behind other work."""
    with robot_errors("Stop robot"):
        stopped = application.navigation.stop()
    application.status.request_refresh()
    return {
        "stopped": stopped,
        "message": (
            "Stop requested. All robot movement is being cancelled."
            if stopped
            else "No active robot movement was detected."
        ),
    }
