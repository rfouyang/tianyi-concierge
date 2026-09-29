from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, wait
from pathlib import Path

from loguru import logger

from util.slam_helper import SLAM

from ..common.body_action import BodyActionClient
from ..common.docking import DockingService
from ..common.errors import ConciergeTaskCancelled
from ..common.execution_checkpoint import ConciergeExecutionCheckpoint
from ..common.execution_options import ConciergeExecutionOptions
from ..common.navigation import NavigationService
from ..common.speech import SpeechService
from ..task_design.service import TaskDesigner
from .preflight import ConciergeExecutionPreflight

BASE_DIR = Path(__file__).resolve().parents[2]
SPEECH_DIR = BASE_DIR / "data" / "tts"


class ConciergeTaskExecutor:
    """Execute one saved concierge task with cancellation and recovery."""

    def __init__(
        self,
        task_designer: TaskDesigner,
        slam: SLAM | None = None,
        options: ConciergeExecutionOptions | None = None,
        audio_dir: Path = SPEECH_DIR,
        body_actions: BodyActionClient | None = None,
        speech: SpeechService | None = None,
    ) -> None:
        self.task_designer = task_designer
        self.slam = slam or SLAM()
        self.audio_dir = Path(audio_dir)
        self.options = options or ConciergeExecutionOptions()
        self.body_actions = body_actions or BodyActionClient()
        self.preflight_service = ConciergeExecutionPreflight(
            self.task_designer,
            self.slam,
            self.body_actions,
        )
        self.navigation = NavigationService(self.slam)
        self.speech = speech or SpeechService(cache_dir=self.audio_dir)
        self.docking = DockingService(self.slam)
        self._run_lock = threading.Lock()
        self._cancel_event = threading.Event()
        self._stop_requested = threading.Event()
        self._running_event = threading.Event()
        self._active_mode = None
        self._checkpoint = None
        # Set by the application: raises unless Tianyi is localized on the loaded map.
        self.localization_guard = None

    def preflight(self, task, **kwargs):
        return self.preflight_service.check(task, **kwargs)

    def _check_cancelled(self):
        if self._cancel_event.is_set():
            raise ConciergeTaskCancelled("Task was cancelled by the user")

    def _cancel_active_action(self):
        try:
            action = self.slam.motion.get_current_action()
            if action is not None and action.get("state", {}).get("status") != 4:
                self.slam.motion.cancel_current_action()
                return True
        except Exception as exc:
            logger.warning(f"Could not cancel the active robot action: {exc}")
        return False

    def _cancel_active_body_action(self):
        try:
            return self.body_actions.cancel_current()
        except Exception as exc:
            logger.warning(f"Could not cancel the active Tianyi body action: {exc}")
            return False

    def _perform_action_and_speech(
        self,
        body_actions,
        body_arm_token,
        audio_path,
    ):
        """Run one POI's arm action and prepared speech concurrently."""
        start_event = threading.Event()

        def execute_action():
            start_event.wait()
            results = []
            for body_action in body_actions:
                self._check_cancelled()
                results.append(
                    self.body_actions.execute(
                        body_action["action_id"],
                        body_arm_token,
                        self._cancel_event,
                    )
                )
            return results

        def play_speech():
            start_event.wait()
            return self.speech.play(audio_path)

        with ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="concierge-poi",
        ) as executor:
            action_future = executor.submit(execute_action)
            speech_future = executor.submit(play_speech)
            start_event.set()
            wait((action_future, speech_future))

        action_error = action_future.exception()
        speech_error = speech_future.exception()
        if action_error is not None:
            # The arms may not have returned to concierge_init. Keep the base
            # stationary until an operator verifies the body state.
            self._stop_requested.set()
            if speech_error is not None:
                logger.error(f"POI speech also failed: {speech_error}")
            raise action_error
        if speech_error is not None:
            raise speech_error

    @staticmethod
    def _event(status, message, task, **kwargs):
        return {
            "status": status,
            "message": message,
            "task_id": task["id"],
            "task_name": task["name"],
            "stop_index": kwargs.get("stop_index"),
            "stop_count": len(task["stops"]),
            "poi_name": kwargs.get("poi_name"),
            "action_id": kwargs.get("action_id"),
            "action_ids": kwargs.get("action_ids"),
            "error": kwargs.get("error"),
        }

    def _return_home(self, **kwargs):
        return self._perform_return_home(**kwargs)

    def _announce(self, text, label):
        """Play a prepared announcement; tours never synthesize speech."""
        try:
            self.speech.play_cached(text)
        except Exception as exc:
            logger.warning(f"Announcement skipped ({label}): {exc}")

    def _perform_undock(self, **kwargs):
        options = self.options.with_overrides(**kwargs)
        self._announce(
            "I am leaving the charging dock.",
            "guide_undock_start",
        )
        result = self.docking.undock(
            distance=options.undock_distance,
            max_distance=options.max_undock_distance,
            max_pulses=options.max_undock_pulses,
            pulse_ms=options.undock_pulse_ms,
        )
        self._announce(
            "I have left the charging dock.",
            "guide_undock_complete",
        )
        return result

    def _perform_return_home(self, **kwargs):
        options = self.options.with_overrides(**kwargs)
        self._announce(
            "I am returning to the charging dock.",
            "guide_return_home_start",
        )
        result = self.docking.return_home(
            home_timeout=options.home_timeout,
            poll_interval=options.poll_interval,
            charging_retry_count=options.charging_retry_count,
            charging_timeout=options.charging_timeout,
        )
        self._announce(
            "I have returned to the charging dock and am charging.",
            "guide_return_home_complete",
        )
        return result

    def _run_manual_action(self, action, **kwargs):
        mode = kwargs.pop("_mode", "manual")
        if not self._run_lock.acquire(blocking=False):
            raise RuntimeError("Another robot action is already running")
        try:
            self._cancel_event.clear()
            self._stop_requested.clear()
            self._active_mode = mode
            self._running_event.set()
            return action(**kwargs)
        finally:
            self._active_mode = None
            self._running_event.clear()
            self._run_lock.release()

    def undock(self, **kwargs):
        """Undock the robot and announce the operation aloud."""
        return self._run_manual_action(self._perform_undock, **kwargs)

    def _require_localized(self):
        if self.localization_guard is not None:
            self.localization_guard()

    def return_home(self, **kwargs):
        """Return the robot to its charging dock and announce the operation."""
        self._require_localized()
        return self._run_manual_action(self._perform_return_home, **kwargs)

    def _perform_rehearsal(self, actions, audio_path=None):
        action_ids = [action["action_id"] for action in actions]
        token = self.body_actions.arm(sorted(set(action_ids)), confirmed=True)
        self.body_actions.prepare(token)
        self._check_cancelled()
        if audio_path is not None:
            self._perform_action_and_speech(actions, token, audio_path)
        else:
            for action in actions:
                self._check_cancelled()
                self.body_actions.execute(action["action_id"], token, self._cancel_event)
        return {
            "status": "completed",
            "action_ids": action_ids,
            "speech": str(audio_path) if audio_path else None,
        }

    def _perform_speech_rehearsal(self, audio_path):
        self.speech.play(audio_path)
        return {"status": "completed", "action_ids": [], "speech": str(audio_path)}

    def rehearse(self, actions, content=None, *, audio=None, arms_confirmed=False):
        """Perform a stop's arm actions (and speech) in place; the base never moves.

        Used while designing a task. Speech must already be prepared; the caller
        prepares it first because design is the stage where synthesis happens.
        """
        actions = [
            {"action_id": str(action["action_id"]).strip()}
            for action in actions or []
            if str(action.get("action_id") or "").strip()
        ]
        if actions and arms_confirmed is not True:
            raise PermissionError(
                "Confirm Tianyi arm motion: both arm areas are clear and the "
                "emergency stop is ready"
            )
        if audio:
            audio_path = self.speech.stop_audio({"audio": audio, "content": content or ""})
        else:
            audio_path = self.speech.require(content) if content else None
        if not actions and audio_path is None:
            raise ValueError("Add at least one action or some speech to rehearse")
        if not actions:
            return self._run_manual_action(
                self._perform_speech_rehearsal, _mode="rehearsal", audio_path=audio_path
            )
        return self._run_manual_action(
            self._perform_rehearsal,
            _mode="rehearsal",
            actions=actions,
            audio_path=audio_path,
        )

    def _set_checkpoint(self, task, next_stop_index):
        self._checkpoint = ConciergeExecutionCheckpoint(
            task_id=task["id"],
            task_name=task["name"],
            next_stop_index=next_stop_index,
            stop_count=len(task["stops"]),
        )

    def get_resume_checkpoint(self, task_id=None):
        if self._checkpoint is None:
            return None
        if self._checkpoint.next_stop_index >= self._checkpoint.stop_count:
            return None
        if task_id is not None and self._checkpoint.task_id != str(task_id):
            return None
        return self._checkpoint.to_dict()

    def _prepare_resume_position(self, preflight, **kwargs):
        quality = preflight["localization_quality"]
        min_quality = kwargs.get("min_quality", self.options.min_quality)
        if quality < min_quality:
            message = (
                "Localization quality is too low. Please manually return me "
                "to the charging dock, then press Resume."
            )
            self._announce(message, "guide_resume_localization_low")
            raise RuntimeError(f"{message} Quality: {quality} < {min_quality}.")

        power = self.slam.power.get_status()
        return power.get("dockingStatus") != "on_dock"

    def _is_off_dock(self, *, default):
        """Read departure state after a motion attempt.

        If the power endpoint is unavailable after navigation has started, use
        the caller's conservative default so recovery can still run.
        """
        try:
            power = self.slam.power.get_status()
        except Exception as exc:
            logger.warning(f"Could not verify departure state: {exc}")
            return default
        return power.get("dockingStatus") != "on_dock"

    def _find_poi(self, poi_id):
        expected_id = str(poi_id or "").strip()
        if not expected_id:
            raise ValueError("POI ID is required")
        for poi in self.slam.poi.get_all():
            if str(poi.get("id") or "").strip() == expected_id:
                return poi
        raise LookupError(f"POI is not present in the current map: {expected_id}")

    def _perform_debug_poi(self, poi, content, **kwargs):
        poi_name = str(poi.get("metadata", {}).get("display_name") or "POI")
        self.navigation.navigate(
            {"poi": poi, "poi_name": poi_name},
            move_timeout=kwargs.get("move_timeout", self.options.move_timeout),
            poll_interval=kwargs.get("poll_interval", self.options.poll_interval),
            acceptable_precision=kwargs.get(
                "acceptable_precision", self.options.acceptable_precision
            ),
            fail_retry_count=kwargs.get("fail_retry_count", self.options.fail_retry_count),
            speed_ratio=kwargs.get("speed_ratio", self.options.speed_ratio),
        )
        self._check_cancelled()
        audio_path = self.speech.speak(
            content,
            f"guide_debug_{poi.get('id', poi_name)}",
        )
        return {
            "status": "completed",
            "poi_id": poi.get("id"),
            "poi_name": poi_name,
            "speech": content,
            "audio": str(audio_path),
        }

    def debug_poi(self, poi_id, **kwargs):
        """Navigate to one POI, speak its debug content, and stay there."""
        self._require_localized()
        poi = self._find_poi(poi_id)
        poi_name = str(poi.get("metadata", {}).get("display_name") or "POI")
        options = dict(kwargs)
        content = str(options.pop("content", None) or f"You have arrived at {poi_name}.").strip()
        if not content:
            content = f"You have arrived at {poi_name}."

        try:
            return self._run_manual_action(
                self._perform_debug_poi,
                _mode="debug",
                poi=poi,
                content=content,
                **options,
            )
        except Exception:
            if self._stop_requested.is_set():
                return {
                    "status": "stopped",
                    "poi_id": poi_id,
                    "poi_name": poi_name,
                    "message": "Debug navigation stopped; robot remains here.",
                }
            raise

    def stop(self):
        """Stop active robot movement without starting return-home recovery."""
        was_running = self.is_running
        self._stop_requested.set()
        self._cancel_event.set()
        action_stopped = self._cancel_active_action()
        body_action_stopped = self._cancel_active_body_action()
        if was_running or action_stopped or body_action_stopped:
            logger.warning("Robot stop requested")
            return True
        self._stop_requested.clear()
        self._cancel_event.clear()
        return False

    @property
    def is_running(self):
        return self._running_event.is_set()

    def cancel(self):
        if not self.is_running or self._active_mode != "task":
            return False
        self._cancel_event.set()
        self._cancel_active_action()
        self._cancel_active_body_action()
        logger.warning("Task cancellation requested")
        return True

    def run_events(self, task_id, **kwargs):
        yield from self._run_events(task_id, resume=False, **kwargs)

    def resume_events(self, task_id, **kwargs):
        yield from self._run_events(task_id, resume=True, **kwargs)

    def _run_events(self, task_id, resume, **kwargs):
        if not self._run_lock.acquire(blocking=False):
            raise RuntimeError("Another task is already running")

        self._running_event.set()
        self._cancel_event.clear()
        self._stop_requested.clear()
        self._active_mode = "task"
        options = self.options.with_overrides(**kwargs)
        departed = False
        body_arm_token = None
        task = None
        start_stop_index = 0
        try:
            task = self.task_designer.get_task(task_id)
            checkpoint = self.get_resume_checkpoint(task_id) if resume else None
            if resume and checkpoint is None:
                raise RuntimeError("No resumable execution exists for the selected task")
            start_stop_index = checkpoint["next_stop_index"] if checkpoint else 0
            yield self._event(
                "starting",
                (
                    f"Checking resume state for task '{task['name']}'"
                    if resume
                    else f"Checking task '{task['name']}' and robot state"
                ),
                task,
            )
            self._check_cancelled()
            preflight = (
                self.preflight_service.check_resume(task, **kwargs)
                if resume
                else self.preflight(task, **kwargs)
            )
            task = preflight["task"]
            self._require_localized()
            missing_speech = [
                stop["poi_name"]
                for stop in task["stops"][start_stop_index:]
                if not self.speech.stop_ready(stop)
            ]
            if missing_speech:
                raise RuntimeError(
                    "Speech is not prepared for: "
                    + ", ".join(missing_speech)
                    + ". Save the task in Task design to prepare it"
                )
            action_ids = sorted(
                {
                    action["action_id"]
                    for stop in task["stops"]
                    for action in stop.get("actions", [])
                }
            )
            if kwargs.get("body_actions_confirmed") is not True:
                raise PermissionError(
                    "Confirm physical Tianyi arm actions before running this task"
                )
            body_arm_token = self.body_actions.arm(
                action_ids,
                confirmed=True,
            )
            if start_stop_index >= len(task["stops"]):
                raise RuntimeError("The selected task has no remaining POIs")
            if not resume:
                self._set_checkpoint(task, 0)
            self._check_cancelled()

            if resume:
                next_stop = task["stops"][start_stop_index]
                yield self._event(
                    "resuming",
                    f"Resuming with {next_stop['poi_name']}",
                    task,
                    stop_index=start_stop_index + 1,
                    poi_name=next_stop["poi_name"],
                )

            yield self._event(
                "body_preparing",
                "Moving the Tianyi arms to concierge_init before navigation",
                task,
            )
            self.body_actions.prepare(body_arm_token)
            self._check_cancelled()

            if resume:
                yield self._event(
                    "localization_check",
                    "Checking localization before resuming",
                    task,
                )
                departed = self._prepare_resume_position(preflight, **kwargs)
            self._check_cancelled()

            prepared_audio = []
            for stop_index, stop in enumerate(
                task["stops"][start_stop_index:],
                start=start_stop_index + 1,
            ):
                yield self._event(
                    "preparing",
                    f"Preparing speech for {stop['poi_name']}",
                    task,
                    stop_index=stop_index,
                    poi_name=stop["poi_name"],
                )
                self._check_cancelled()
                prepared_audio.append(self.speech.prepare(task, stop, stop_index))
                self._check_cancelled()

            if not resume:
                first_stop = task["stops"][start_stop_index]
                yield self._event(
                    "departing",
                    (
                        "Starting planned navigation from the current position "
                        f"to {first_stop['poi_name']}"
                    ),
                    task,
                )
                self._check_cancelled()
            self._check_cancelled()

            for stop_index, (stop, audio_path) in enumerate(
                zip(task["stops"][start_stop_index:], prepared_audio, strict=False),
                start=start_stop_index + 1,
            ):
                yield self._event(
                    "navigating",
                    f"Navigating to {stop['poi_name']}",
                    task,
                    stop_index=stop_index,
                    poi_name=stop["poi_name"],
                )
                self._check_cancelled()
                try:
                    self.navigation.navigate(
                        stop,
                        move_timeout=options.move_timeout,
                        poll_interval=options.poll_interval,
                        acceptable_precision=options.acceptable_precision,
                        fail_retry_count=options.fail_retry_count,
                        speed_ratio=options.speed_ratio,
                    )
                except Exception:
                    if not departed:
                        departed = self._is_off_dock(default=True)
                    raise

                if not departed:
                    departed = self._is_off_dock(default=True)
                    if not departed:
                        raise RuntimeError(
                            "Navigation completed but the robot did not leave the charging dock"
                        )
                self._check_cancelled()

                body_actions = stop["actions"]
                if body_arm_token is None:
                    raise RuntimeError("Tianyi body-action authorization is missing")
                stop_action_ids = [action["action_id"] for action in body_actions]
                action_message = (
                    f"Performing {' -> '.join(stop_action_ids)} and speaking"
                    if stop_action_ids
                    else "Keeping arms at concierge_init and speaking"
                )
                yield self._event(
                    "performing_stop",
                    (f"{action_message} at {stop['poi_name']}"),
                    task,
                    stop_index=stop_index,
                    poi_name=stop["poi_name"],
                    action_id=stop_action_ids[0] if stop_action_ids else None,
                    action_ids=stop_action_ids,
                )
                self._check_cancelled()
                self._perform_action_and_speech(
                    body_actions,
                    body_arm_token,
                    audio_path,
                )
                self._check_cancelled()
                self._checkpoint.next_stop_index = stop_index
                yield self._event(
                    "stop_completed",
                    f"Completed {stop['poi_name']}",
                    task,
                    stop_index=stop_index,
                    poi_name=stop["poi_name"],
                )

            yield self._event("returning", "Returning to the charging dock", task)
            self._return_home(**kwargs)
            departed = False
            self._check_cancelled()
            self._checkpoint = None
            yield self._event("completed", f"Task '{task['name']}' completed", task)
        except Exception as exc:
            if self._cancel_event.is_set() and not isinstance(exc, ConciergeTaskCancelled):
                exc = ConciergeTaskCancelled("Task was cancelled by the user")
            stopped = self._stop_requested.is_set()
            self._cancel_active_action()
            self._cancel_active_body_action()
            recovery_error = None
            if departed and task is not None and not stopped:
                yield self._event(
                    "recovering",
                    "Returning to the charging dock after interruption",
                    task,
                    error=str(exc),
                )
                try:
                    self._return_home(**kwargs)
                except Exception as error:
                    recovery_error = error
            if task is None:
                raise

            if isinstance(exc, ConciergeTaskCancelled):
                message = "Task stopped" if stopped else "Task cancelled"
                if recovery_error:
                    message += f"; return-to-dock failed: {recovery_error}"
                elif departed and not stopped:
                    message += "; robot returned to the dock"
                elif stopped:
                    message += "; robot remains at its current location"
                yield self._event("cancelled", message, task, error=str(recovery_error or exc))
            else:
                message = f"Task failed: {exc}"
                if recovery_error:
                    message += f"; return-to-dock also failed: {recovery_error}"
                elif departed and not stopped:
                    message += "; robot returned to the dock"
                elif stopped:
                    message += "; robot remains at its current location"
                yield self._event("failed", message, task, error=str(recovery_error or exc))
        finally:
            self._active_mode = None
            self._cancel_event.clear()
            self._stop_requested.clear()
            self._running_event.clear()
            self._run_lock.release()


def demo_task_status():
    return TaskDesigner().list_tasks()


def main():
    print(demo_task_status())


if __name__ == "__main__":
    main()
