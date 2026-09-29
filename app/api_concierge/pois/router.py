"""REST routes for recording and deleting POIs on the loaded map."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api_concierge.dependencies import get_application, robot_errors
from app.api_concierge.operations import run_operation
from app.api_concierge.pois.schemas import RecordPoiCommand
from app.application import ConciergeApplication

router = APIRouter(prefix="/pois", tags=["pois"])


@router.get("")
def list_pois(
    application: Annotated[ConciergeApplication, Depends(get_application)],
) -> dict[str, object]:
    with robot_errors("Read POIs"):
        return application.poi_management.get_catalog()


@router.post("", status_code=status.HTTP_202_ACCEPTED)
def record_poi(
    command: RecordPoiCommand,
    application: Annotated[ConciergeApplication, Depends(get_application)],
) -> dict[str, object]:
    """Record Tianyi's current localized pose; the map is persisted afterwards."""
    with robot_errors("Record POI"):
        return run_operation(
            application,
            "poi_record",
            f"Record POI {command.name.strip()}",
            application.poi_management.create,
            command.name,
        )


@router.delete("/{poi_id}", status_code=status.HTTP_202_ACCEPTED)
def delete_poi(
    poi_id: str,
    application: Annotated[ConciergeApplication, Depends(get_application)],
) -> dict[str, object]:
    with robot_errors("Delete POI"):
        return run_operation(
            application,
            "poi_delete",
            "Delete POI",
            application.poi_management.delete,
            poi_id,
            details={"poi_id": poi_id},
        )
