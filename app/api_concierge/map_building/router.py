"""REST routes for building a new map from the charging dock."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api_concierge.dependencies import get_application, require_confirmation, robot_errors
from app.api_concierge.map_building.schemas import FinishMapBuildCommand, StartMapBuildCommand
from app.api_concierge.operations import run_operation
from app.application import ConciergeApplication

router = APIRouter(prefix="/map-building", tags=["map-building"])


@router.get("")
def map_building_status(
    application: Annotated[ConciergeApplication, Depends(get_application)],
) -> dict[str, object]:
    with robot_errors("Read map-building status"):
        return application.map_building.get_status()


@router.post("/start", status_code=status.HTTP_202_ACCEPTED)
def start_build(
    command: StartMapBuildCommand,
    application: Annotated[ConciergeApplication, Depends(get_application)],
) -> dict[str, object]:
    require_confirmation(command.confirmed, "Confirm that Start clears the robot's in-memory map")
    with robot_errors("Start map building"):
        application.map_building.get_map_path(command.filename)
        return run_operation(
            application,
            "map_build_start",
            "Start map building",
            application.map_building.start,
            command.filename,
            dock_name=command.dock_name,
            overwrite=command.overwrite,
            refresh_map=True,
        )


@router.post("/finish", status_code=status.HTTP_202_ACCEPTED)
def finish_build(
    command: FinishMapBuildCommand,
    application: Annotated[ConciergeApplication, Depends(get_application)],
) -> dict[str, object]:
    options = {} if command.overwrite is None else {"overwrite": command.overwrite}
    with robot_errors("Finish map building"):
        return run_operation(
            application,
            "map_build_finish",
            "Finish and save the map",
            application.map_building.finish,
            refresh_map=True,
            **options,
        )


@router.post("/stop-existing", status_code=status.HTTP_202_ACCEPTED)
def stop_existing_mapping(
    application: Annotated[ConciergeApplication, Depends(get_application)],
) -> dict[str, object]:
    with robot_errors("Stop existing mapping"):
        return run_operation(
            application,
            "map_build_stop_existing",
            "Stop existing mapping",
            application.map_building.stop_active_mapping,
            refresh_map=True,
        )
