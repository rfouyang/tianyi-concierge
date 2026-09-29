"""REST routes for designing guide tasks (no robot motion)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from app.api_concierge.dependencies import get_application, require_confirmation, robot_errors
from app.api_concierge.operations import run_operation
from app.api_concierge.tasks.schemas import RehearseCommand, SaveTaskCommand, SpeechPreviewCommand
from app.application import ConciergeApplication

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("")
def list_tasks(
    application: Annotated[ConciergeApplication, Depends(get_application)],
) -> dict[str, object]:
    with robot_errors("Read tasks"):
        return {"tasks": application.task_design.list_tasks()}


@router.get("/catalog")
def task_catalog(
    application: Annotated[ConciergeApplication, Depends(get_application)],
) -> dict[str, object]:
    """POIs on the current map and validated Tianyi arm actions for the editor."""
    catalog: dict[str, object] = {"pois": [], "actions": [], "errors": []}
    errors: list[str] = []
    try:
        catalog["pois"] = application.task_design.available_pois()
    except Exception as error:
        errors.append(f"POIs are unavailable: {error}")
    try:
        catalog["actions"] = application.task_design.available_actions()
    except Exception as error:
        errors.append(f"Tianyi actions are unavailable: {error}")
    catalog["errors"] = errors
    return catalog


@router.post("/speech/preview")
def preview_speech(
    command: SpeechPreviewCommand,
    application: Annotated[ConciergeApplication, Depends(get_application)],
) -> dict[str, object]:
    """Prepare generated speech in data/tts (design stage) and report its length."""
    with robot_errors("Prepare speech preview"):
        path = application.task_design.speech.ensure(command.text)
    return {"file": path.name, "duration": application.task_design.speech.duration(path)}


@router.post("/speech/upload")
async def upload_speech(
    request: Request,
    application: Annotated[ConciergeApplication, Depends(get_application)],
) -> dict[str, object]:
    """Store an operator-made WAV (16 kHz, mono, 16-bit PCM) as a stop's speech.

    The request body is the raw WAV file; no multipart parsing is needed.
    """
    data = await request.body()
    with robot_errors("Upload speech"):
        stored = application.task_design.speech.store_upload(data)
    return stored


@router.post("/rehearse", status_code=status.HTTP_202_ACCEPTED)
def rehearse(
    command: RehearseCommand,
    application: Annotated[ConciergeApplication, Depends(get_application)],
) -> dict[str, object]:
    """Let Tianyi perform a stop's actions and speech in place (no base motion)."""
    content = (command.content or "").strip() or None
    audio = (command.audio or "").strip() or None
    if command.actions:
        require_confirmation(
            command.arms_confirmed,
            "Confirm Tianyi arm motion: both arm areas are clear and the emergency stop is ready",
        )
    with robot_errors("Rehearse on Tianyi"):
        if audio:
            application.task_design.speech.stop_audio({"audio": audio, "content": content or ""})
        elif content:
            application.task_design.speech.ensure(content)
        return run_operation(
            application,
            "rehearsal",
            "Rehearse on Tianyi",
            application.task_execution.rehearse,
            [action.model_dump() for action in command.actions],
            content,
            audio=audio,
            arms_confirmed=command.arms_confirmed,
            details={"action_ids": [action.action_id for action in command.actions]},
        )


@router.get("/{task_id}")
def get_task(
    task_id: str,
    application: Annotated[ConciergeApplication, Depends(get_application)],
) -> dict[str, object]:
    with robot_errors("Read task"):
        task = application.task_design.get_task(task_id)
    return {**task, "speech": application.task_design.speech_status(task)}


@router.post("/{task_id}/speech")
def prepare_task_speech(
    task_id: str,
    application: Annotated[ConciergeApplication, Depends(get_application)],
) -> dict[str, object]:
    """Retry speech synthesis for a saved task (needs a network connection)."""
    with robot_errors("Prepare speech"):
        task = application.task_design.get_task(task_id)
    return application.task_design.prepare_speech(task)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_task(
    command: SaveTaskCommand,
    application: Annotated[ConciergeApplication, Depends(get_application)],
) -> dict[str, object]:
    with robot_errors("Save task"):
        task = application.task_design.save_task(
            command.name, [stop.model_dump() for stop in command.stops]
        )
    return task


@router.put("/{task_id}")
def update_task(
    task_id: str,
    command: SaveTaskCommand,
    application: Annotated[ConciergeApplication, Depends(get_application)],
) -> dict[str, object]:
    with robot_errors("Save task"):
        task = application.task_design.save_task(
            command.name,
            [stop.model_dump() for stop in command.stops],
            task_id=task_id,
        )
    return task


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(
    task_id: str,
    application: Annotated[ConciergeApplication, Depends(get_application)],
) -> Response:
    with robot_errors("Delete task"):
        application.task_design.delete_task(task_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
