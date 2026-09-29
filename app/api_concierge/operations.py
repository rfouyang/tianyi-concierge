"""Start robot work through the shared single-operation runner."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.application import ConciergeApplication


def run_operation(
    application: ConciergeApplication,
    kind: str,
    label: str,
    function: Callable[..., Any],
    *args: Any,
    refresh_map: bool = False,
    details: dict | None = None,
    **kwargs: Any,
) -> dict:
    """Run robot work in the background and refresh status when it ends."""

    def wrapped() -> Any:
        try:
            return function(*args, **kwargs)
        finally:
            application.status.request_refresh(include_map=refresh_map)

    return application.operations.start(kind, label, wrapped, details=details)
