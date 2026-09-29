"""Realtime robot status and operation progress for browsers."""

from __future__ import annotations

import asyncio

from fastapi import WebSocket, WebSocketDisconnect

from app.api_concierge.dependencies import get_websocket_application

POLL_SECONDS = 0.25


async def concierge_websocket(websocket: WebSocket) -> None:
    """Push status and operation snapshots whenever their revision changes."""
    await websocket.accept()
    application = get_websocket_application(websocket)
    sent_status = -1
    sent_operations = -1
    sent_mrt = None
    try:
        while True:
            status = application.status.snapshot()
            if status["revision"] != sent_status:
                await websocket.send_json({"type": "status", **status})
                sent_status = status["revision"]

            operations = application.operations.snapshot()
            if operations["revision"] != sent_operations:
                await websocket.send_json({"type": "operations", **operations})
                sent_operations = operations["revision"]

            mrt_active = application.mrt.active_operation_id
            if mrt_active != sent_mrt:
                await websocket.send_json({"type": "mrt", "active_operation_id": mrt_active})
                sent_mrt = mrt_active

            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=POLL_SECONDS)
            except asyncio.TimeoutError:
                continue
    except WebSocketDisconnect:
        return
