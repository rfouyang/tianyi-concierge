"""Construct the shared capabilities used by the API, UI, and MRT entrypoints."""

from __future__ import annotations

import threading
from dataclasses import dataclass

from loguru import logger

from component.common.body_action import BodyActionClient
from component.common.map_view import MapViewService
from component.common.speech import ANNOUNCEMENTS, SpeechService
from component.map_building import ConciergeMapBuilder
from component.map_localization import ConciergeMapLocalizer
from component.mrt_intervention import MrtInterventionService
from component.navigation import ConciergeNavigator
from component.poi_management import PoiManager
from component.robot_operation import RobotOperationRunner
from component.robot_status import RobotStatusMonitor
from component.task_design import TaskDesigner
from component.task_execution import ConciergeTaskExecutor
from config.settings import AppSettings
from util.slam_helper import SLAM


@dataclass(slots=True)
class ConciergeApplication:
    """One process-wide set of robot capabilities.

    A single BodyActionClient is shared by tours and MRT interventions, so only
    one component can ever command the Tianyi arms at a time.
    """

    settings: AppSettings
    slam: SLAM
    body_actions: BodyActionClient
    map_view: MapViewService
    map_localization: ConciergeMapLocalizer
    map_building: ConciergeMapBuilder
    poi_management: PoiManager
    task_design: TaskDesigner
    task_execution: ConciergeTaskExecutor
    navigation: ConciergeNavigator
    mrt: MrtInterventionService
    operations: RobotOperationRunner
    status: RobotStatusMonitor

    @classmethod
    def build(cls, *, settings: AppSettings | None = None) -> ConciergeApplication:
        resolved = settings or AppSettings.from_env()
        slam = SLAM()
        body_actions = BodyActionClient()
        map_view = MapViewService(slam)
        localizer = ConciergeMapLocalizer(
            slam,
            map_dir=resolved.map_dir,
            registry_path=resolved.map_registry_path,
        )
        speech = SpeechService(cache_dir=resolved.speech_dir)
        task_design = TaskDesigner(
            resolved.task_config_path,
            slam,
            body_actions=body_actions,
            speech=speech,
        )
        executor = ConciergeTaskExecutor(
            task_design,
            slam,
            body_actions=body_actions,
            speech=speech,
        )
        mrt_holder: dict[str, MrtInterventionService] = {}

        def mrt_busy() -> str | None:
            mrt = mrt_holder.get("mrt")
            if mrt is not None and mrt.active_operation_id is not None:
                return "An MRT intervention is running; wait for it or cancel it first"
            return None

        operations = RobotOperationRunner(busy_check=mrt_busy)

        def robot_busy() -> str | None:
            if operations.is_busy() or executor.is_running:
                return "Tianyi is busy with a tour or manual operation"
            return None

        mrt = MrtInterventionService(
            body_actions=body_actions,
            audio_dir=resolved.mrt_audio_dir,
            busy_check=robot_busy,
        )
        mrt_holder["mrt"] = mrt
        executor.localization_guard = localizer.require_localized
        return cls(
            settings=resolved,
            slam=slam,
            body_actions=body_actions,
            map_view=map_view,
            map_localization=localizer,
            map_building=ConciergeMapBuilder(slam, map_dir=resolved.map_dir, localizer=localizer),
            poi_management=PoiManager(slam, localization_guard=localizer.require_localized),
            task_design=task_design,
            task_execution=executor,
            navigation=ConciergeNavigator(executor),
            mrt=mrt,
            operations=operations,
            status=RobotStatusMonitor(
                slam,
                map_view,
                body_actions=body_actions,
                registry=localizer.registry,
                localizer=localizer,
                operations=operations,
            ),
        )

    def start(self) -> None:
        self.status.start()
        threading.Thread(target=self._warm_speech, name="speech-warmup", daemon=True).start()

    def _warm_speech(self) -> None:
        """Best effort: fill the offline speech cache while a network exists."""
        texts = list(ANNOUNCEMENTS)
        try:
            texts += [
                stop["content"] for task in self.task_design.list_tasks() for stop in task["stops"]
            ]
        except Exception as error:
            logger.warning(f"Could not read tasks for speech warm-up: {error}")
        speech = self.task_design.speech
        missing = speech.missing(texts)
        for text in missing:
            try:
                speech.ensure(text)
            except Exception as error:
                logger.warning(f"Speech warm-up stopped; {len(missing)} texts uncached: {error}")
                return
        if missing:
            logger.info(f"Cached {len(missing)} speech clips in data/tts")

    def close(self) -> None:
        self.status.close()
        self.task_execution.stop()
        self.mrt.close()
