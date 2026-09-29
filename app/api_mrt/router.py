"""REST routes for MRT interventions; same contract as the original Flask API."""

from __future__ import annotations

import hmac
import uuid
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.application import ConciergeApplication
from component.mrt_intervention import MRT_ACTIONS

ACTION_ID_BY_NUMBER = {
    str(number): action_id for number, action_id in enumerate(MRT_ACTIONS, start=1)
}


class MrtApiError(Exception):
    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


def mrt_error_response(_: Request, error: MrtApiError) -> JSONResponse:
    return JSONResponse({"status": "failed", "message": str(error)}, status_code=error.status_code)


def get_application(request: Request) -> ConciergeApplication:
    return cast(ConciergeApplication, request.app.state.concierge)


def require_api_key(
    request: Request,
    application: Annotated[ConciergeApplication, Depends(get_application)],
) -> None:
    api_key = application.settings.mrt_api_key
    scheme, _, supplied = request.headers.get("Authorization", "").partition(" ")
    if not api_key or scheme.lower() != "bearer" or not hmac.compare_digest(supplied, api_key):
        raise MrtApiError("Unauthorized", 401)


router = APIRouter(prefix="/api/mrt/v1", dependencies=[Depends(require_api_key)])


def _call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except PermissionError as error:
        raise MrtApiError(str(error), 403) from error
    except KeyError as error:
        raise MrtApiError("MRT intervention was not found", 404) from error
    except ValueError as error:
        raise MrtApiError(str(error), 400) from error
    except RuntimeError as error:
        raise MrtApiError(str(error), 409) from error


@router.get("/health")
def health(application: Annotated[ConciergeApplication, Depends(get_application)]):
    return application.mrt.health()


@router.get("/actions")
def actions(application: Annotated[ConciergeApplication, Depends(get_application)]):
    return {"actions": application.mrt.list_actions()}


@router.get("/interventions")
def start_intervention(
    application: Annotated[ConciergeApplication, Depends(get_application)],
    action: str = "",
    request_id: str | None = None,
):
    action_id = ACTION_ID_BY_NUMBER.get(action)
    if action_id is None:
        raise MrtApiError("action must be 1, 2, 3, or 4", 400)
    operation, created = _call(
        application.mrt.start,
        request_id=request_id or f"api-{uuid.uuid4().hex}",
        action_id=action_id,
        arm_motion_confirmed=True,
    )
    return JSONResponse(operation, status_code=202 if created else 200)


@router.get("/interventions/{operation_id}")
def get_intervention(
    operation_id: str,
    application: Annotated[ConciergeApplication, Depends(get_application)],
):
    return _call(application.mrt.get, operation_id)


@router.post("/interventions/{operation_id}/cancel", status_code=202)
def cancel_intervention(
    operation_id: str,
    application: Annotated[ConciergeApplication, Depends(get_application)],
):
    return JSONResponse(_call(application.mrt.cancel, operation_id), status_code=202)
