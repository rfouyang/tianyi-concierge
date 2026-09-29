"""REST routes for the map catalog, map loading, and localization."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api_concierge.dependencies import get_application, require_confirmation, robot_errors
from app.api_concierge.maps.schemas import (
    BindDockCommand,
    LoadMapCommand,
    LocalizeAtPoseCommand,
    SnapshotCommand,
    SyncMapCommand,
)
from app.api_concierge.operations import run_operation
from app.application import ConciergeApplication

router = APIRouter(tags=["maps"])


@router.get("/maps")
def list_maps(
    application: Annotated[ConciergeApplication, Depends(get_application)],
) -> dict[str, object]:
    """Every STCM file in data/maps."""
    return {"maps": application.map_localization.list_maps()}


@router.get("/maps/current")
def current_map(
    application: Annotated[ConciergeApplication, Depends(get_application)],
) -> dict[str, object]:
    """Identify the robot's loaded map against data/maps (read-only)."""
    with robot_errors("Identify the current map"):
        return application.map_localization.get_current_map_identity()


@router.post("/maps/load", status_code=status.HTTP_202_ACCEPTED)
def load_map(
    command: LoadMapCommand,
    application: Annotated[ConciergeApplication, Depends(get_application)],
) -> dict[str, object]:
    require_confirmation(
        command.confirmed,
        "Confirm that this map should replace the stored robot map and reload at the dock",
    )
    with robot_errors("Load map"):
        application.map_localization.resolve_map(command.name)
        return run_operation(
            application,
            "map_load",
            f"Load {command.name}",
            application.map_localization.load_map,
            command.name,
            refresh_map=True,
            details={"name": command.name},
        )


@router.post("/maps/sync", status_code=status.HTTP_202_ACCEPTED)
def sync_map(
    command: SyncMapCommand,
    application: Annotated[ConciergeApplication, Depends(get_application)],
) -> dict[str, object]:
    require_confirmation(
        command.confirmed,
        "Confirm that Sync saves and reloads the robot's in-memory map",
    )
    with robot_errors("Sync map"):
        return run_operation(
            application,
            "map_sync",
            "Sync the robot map",
            application.map_localization.sync_current_map,
            refresh_map=True,
        )


@router.post("/maps/snapshot", status_code=status.HTTP_202_ACCEPTED)
def save_snapshot(
    command: SnapshotCommand,
    application: Annotated[ConciergeApplication, Depends(get_application)],
) -> dict[str, object]:
    with robot_errors("Save map snapshot"):
        return run_operation(
            application,
            "map_snapshot",
            f"Save snapshot {command.filename}",
            application.map_localization.save_snapshot,
            command.filename,
            overwrite=command.overwrite,
        )


@router.get("/maps/view")
def map_view(
    application: Annotated[ConciergeApplication, Depends(get_application)],
) -> dict[str, object]:
    """Grid metadata for the cached explore map (origin, resolution, size)."""
    view = application.map_view.view()
    if view is None:
        with robot_errors("Read the explore map"):
            view = application.map_view.refresh()
    return view


@router.get("/maps/view.png")
def map_view_png(
    application: Annotated[ConciergeApplication, Depends(get_application)],
) -> Response:
    image = application.map_view.png()
    if image is None:
        with robot_errors("Read the explore map"):
            application.map_view.refresh()
        image = application.map_view.png()
    if image is None:
        raise HTTPException(status_code=503, detail="The explore map is not available yet")
    revision, png = image
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "no-cache", "ETag": revision, "X-Map-Revision": revision},
    )


@router.get("/localization")
def localization_status(
    application: Annotated[ConciergeApplication, Depends(get_application)],
) -> dict[str, object]:
    with robot_errors("Read localization"):
        return application.map_localization.get_localization_status()


@router.post("/localization/stop", status_code=status.HTTP_202_ACCEPTED)
def stop_localization(
    application: Annotated[ConciergeApplication, Depends(get_application)],
) -> dict[str, object]:
    with robot_errors("Stop localization"):
        return run_operation(
            application,
            "localization_stop",
            "Stop localization",
            application.map_localization.stop_localization,
        )


@router.post("/localization/bind-dock", status_code=status.HTTP_202_ACCEPTED)
def bind_home_dock(
    command: BindDockCommand,
    application: Annotated[ConciergeApplication, Depends(get_application)],
) -> dict[str, object]:
    """Bind the map's charging dock so tours can return home (Tianyi on the dock)."""
    require_confirmation(command.confirmed, "Confirm that Tianyi is on the charging dock")
    with robot_errors("Bind charging dock"):
        return run_operation(
            application,
            "dock_bind",
            "Bind the charging dock",
            application.map_localization.bind_home_dock,
        )


@router.post("/localization/dock", status_code=status.HTTP_202_ACCEPTED)
def localize_at_dock(
    application: Annotated[ConciergeApplication, Depends(get_application)],
) -> dict[str, object]:
    with robot_errors("Localize at dock"):
        return run_operation(
            application,
            "localization_dock",
            "Localize at the charging dock",
            application.map_localization.localize_at_dock,
        )


@router.post("/localization/pose", status_code=status.HTTP_202_ACCEPTED)
def localize_at_pose(
    command: LocalizeAtPoseCommand,
    application: Annotated[ConciergeApplication, Depends(get_application)],
) -> dict[str, object]:
    if command.allow_rotation:
        require_confirmation(
            command.rotation_confirmed,
            "Confirm the area around Tianyi is clear before allowing it to rotate",
        )
    with robot_errors("Localize at pose"):
        return run_operation(
            application,
            "localization_pose",
            "Localize at the placed arrow",
            application.map_localization.localize_at_pose,
            command.x,
            command.y,
            command.yaw,
            search_half_size=command.search_half_size,
            allow_rotation=command.allow_rotation,
            details=command.model_dump(),
        )
