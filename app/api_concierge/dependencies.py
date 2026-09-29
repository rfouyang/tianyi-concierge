"""FastAPI dependency providers and error translation for the concierge API."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import cast

from fastapi import HTTPException, Request, WebSocket
from loguru import logger

from app.application import ConciergeApplication
from component.robot_operation import RobotOperationBusy


def get_application(request: Request) -> ConciergeApplication:
    """Return the process-wide application assembled by the host."""
    return cast(ConciergeApplication, request.app.state.concierge)


def get_websocket_application(websocket: WebSocket) -> ConciergeApplication:
    return cast(ConciergeApplication, websocket.app.state.concierge)


@contextmanager
def robot_errors(action: str) -> Iterator[None]:
    """Translate component exceptions into HTTP responses with a clear message."""
    try:
        yield
    except HTTPException:
        raise
    except RobotOperationBusy as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except FileExistsError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (FileNotFoundError, LookupError) as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except (RuntimeError, TimeoutError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except Exception as error:
        logger.exception(f"{action} failed")
        raise HTTPException(status_code=502, detail=f"{action} failed: {error}") from error


def require_confirmation(confirmed: bool, message: str) -> None:
    if confirmed is not True:
        raise HTTPException(status_code=403, detail=message)
