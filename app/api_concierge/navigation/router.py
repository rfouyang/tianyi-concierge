"""REST routes for manual navigation: visit a POI, dock, and undock."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api_concierge.dependencies import get_application, robot_errors
from app.api_concierge.navigation.schemas import GoToPoiCommand
from app.api_concierge.operations import run_operation
from app.application import ConciergeApplication

router = APIRouter(prefix="/navigation", tags=["navigation"])


@router.post("/go", status_code=status.HTTP_202_ACCEPTED)
def go_to_poi(
    command: GoToPoiCommand,
    application: Annotated[ConciergeApplication, Depends(get_application)],
) -> dict[str, object]:
    """Navigate to a POI, speak, and stay there until moved or stopped."""
    with robot_errors("Go to POI"):
        return run_operation(
            application,
            "navigation_go",
            "Go to POI",
            application.navigation.go_to_poi,
            command.poi_id,
            command.content,
            details=command.model_dump(),
        )


@router.post("/home", status_code=status.HTTP_202_ACCEPTED)
def go_home(
    application: Annotated[ConciergeApplication, Depends(get_application)],
) -> dict[str, object]:
    with robot_errors("Go home"):
        return run_operation(
            application, "navigation_home", "Go home", application.navigation.go_home
        )


@router.post("/undock", status_code=status.HTTP_202_ACCEPTED)
def undock(
    application: Annotated[ConciergeApplication, Depends(get_application)],
) -> dict[str, object]:
    with robot_errors("Undock"):
        return run_operation(
            application, "navigation_undock", "Undock", application.navigation.undock
        )
