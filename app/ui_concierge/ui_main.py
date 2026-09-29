"""HTML routes for the concierge console and the standalone MRT page."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import cast

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict

from app.application import ConciergeApplication
from component.mrt_intervention import MRT_ACTIONS

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent / "static"
templates = Jinja2Templates(directory=TEMPLATE_DIR)


def static_asset(path: str) -> str:
    """Static URL with a version so browsers reload JS/CSS after every change."""
    file = STATIC_DIR / path.lstrip("/")
    version = file.stat().st_mtime_ns if file.is_file() else 0
    return f"/static/concierge/{path.lstrip('/')}?v={version}"


templates.env.globals["asset"] = static_asset
router = APIRouter(include_in_schema=False)

ICONS = {
    "build": '<path d="M4 20V8l8-5 8 5v12"/><path d="M9 20v-6h6v6"/><path d="M2 20h20"/>',
    "locate": (
        '<circle cx="12" cy="12" r="7"/>'
        '<path d="M12 2v4M12 18v4M2 12h4M18 12h4"/>'
        '<circle cx="12" cy="12" r="2"/>'
    ),
    "pin": (
        '<path d="M12 21s-7-6.2-7-11a7 7 0 0 1 14 0c0 4.8-7 11-7 11z"/>'
        '<circle cx="12" cy="10" r="2.5"/>'
    ),
    "nav": '<path d="M12 2 19 21l-7-4-7 4z"/>',
    "edit": '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13 7l4 4"/>',
    "play": '<path d="M7 4v16l13-8z"/>',
    "wifi": (
        '<path d="M2 9a15 15 0 0 1 20 0M5 12.5a10 10 0 0 1 14 0M8.5 16a5 5 0 0 1 7 0"/>'
        '<circle cx="12" cy="19.5" r="0.8"/>'
    ),
    "battery": (
        '<rect x="2" y="7" width="17" height="10" rx="2"/>'
        '<path d="M22 11v2"/>'
        '<path d="M5 10h9v4H5z"/>'
    ),
    "plug": '<path d="M9 2v6M15 2v6M6 8h12v4a6 6 0 0 1-12 0z"/><path d="M12 18v4"/>',
    "target": '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/>',
    "layers": '<path d="M12 3 2 8l10 5 10-5z"/><path d="M2 13l10 5 10-5"/>',
    "arm": '<path d="M4 20l5-5 3 1 5-6"/><circle cx="17" cy="6" r="2"/><path d="M3 21h6"/>',
}


@dataclass(frozen=True, slots=True)
class Page:
    key: str
    path: str
    title: str
    short: str
    icon: str
    template: str


PAGES = (
    Page(
        "map-building", "/map-building", "Map building", "Build", "build", "pages/map_building.html"
    ),
    Page(
        "localization",
        "/localization",
        "Map & localization",
        "Localize",
        "locate",
        "pages/localization.html",
    ),
    Page("pois", "/pois", "POI management", "POIs", "pin", "pages/pois.html"),
    Page("navigation", "/navigation", "Navigation", "Navigate", "nav", "pages/navigation.html"),
    Page("task-design", "/task-design", "Task design", "Design", "edit", "pages/task_design.html"),
    Page(
        "task-execution",
        "/task-execution",
        "Task execution",
        "Execute",
        "play",
        "pages/task_execution.html",
    ),
)


def _application(request: Request) -> ConciergeApplication:
    return cast(ConciergeApplication, request.app.state.concierge)


def _render(request: Request, page: Page) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name=page.template,
        context={
            "page": page,
            "pages": [{**asdict(item), "icon": ICONS[item.icon]} for item in PAGES],
            "icons": ICONS,
        },
    )


@router.get("/")
def home() -> RedirectResponse:
    return RedirectResponse(url=PAGES[0].path)


def _page_route(page: Page):
    def route(request: Request) -> HTMLResponse:
        return _render(request, page)

    route.__name__ = f"page_{page.key.replace('-', '_')}"
    return route


for _page in PAGES:
    router.add_api_route(
        _page.path, _page_route(_page), methods=["GET"], response_class=HTMLResponse
    )


# ----------------------------------------------------------------- MRT page
@router.get("/mrt", response_class=HTMLResponse)
def mrt_page(request: Request) -> HTMLResponse:
    """Standalone MRT operator page, served on the LAN console only."""
    application = _application(request)
    return templates.TemplateResponse(
        request=request,
        name="pages/mrt.html",
        context={
            "mrt_actions": [
                {"action_id": action_id, "label": action.label, "message": action.message}
                for action_id, action in MRT_ACTIONS.items()
            ],
            "mrt_port": application.settings.mrt_port,
        },
    )


class StartMrtCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: str
    arm_motion_confirmed: bool = False


def _mrt_call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except KeyError as error:
        raise HTTPException(status_code=404, detail="MRT intervention was not found") from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/ui/mrt/health")
def mrt_health(request: Request) -> dict[str, object]:
    application = _application(request)
    health = _mrt_call(application.mrt.health)
    recent = application.mrt.recent(limit=1)
    return {**health, "latest_operation": recent[0] if recent else None}


@router.post("/ui/mrt/interventions", status_code=202)
def mrt_start(request: Request, command: StartMrtCommand) -> dict[str, object]:
    if command.arm_motion_confirmed is not True:
        raise HTTPException(status_code=403, detail="Confirm that both arm areas are clear")
    operation, _ = _mrt_call(
        _application(request).mrt.start,
        request_id=f"ui-{uuid.uuid4().hex}",
        action_id=command.action_id,
        arm_motion_confirmed=True,
    )
    return operation


@router.get("/ui/mrt/interventions/{operation_id}")
def mrt_get(request: Request, operation_id: str) -> dict[str, object]:
    return _mrt_call(_application(request).mrt.get, operation_id)


@router.post("/ui/mrt/interventions/{operation_id}/cancel", status_code=202)
def mrt_cancel(request: Request, operation_id: str) -> dict[str, object]:
    return _mrt_call(_application(request).mrt.cancel, operation_id)
