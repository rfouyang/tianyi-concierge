"""Assemble domain routers for the concierge console API."""

from __future__ import annotations

from fastapi import APIRouter

from app.api_concierge.execution.router import router as execution_router
from app.api_concierge.map_building.router import router as map_building_router
from app.api_concierge.maps.router import router as maps_router
from app.api_concierge.navigation.router import router as navigation_router
from app.api_concierge.pois.router import router as pois_router
from app.api_concierge.system.router import router as system_router
from app.api_concierge.tasks.router import router as tasks_router
from app.api_concierge.websocket import concierge_websocket

router = APIRouter(prefix="/api/concierge")
router.include_router(system_router)
router.include_router(map_building_router)
router.include_router(maps_router)
router.include_router(pois_router)
router.include_router(navigation_router)
router.include_router(tasks_router)
router.include_router(execution_router)
router.add_api_websocket_route("/ws", concierge_websocket)
