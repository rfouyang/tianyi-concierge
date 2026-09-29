from __future__ import annotations

from pathlib import Path

from util.slam_helper import SLAM

from ..common.concierge_task import ConciergeTask
from .repository import ConciergeTaskRepository

BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = BASE_DIR / "config" / "task.json"


class TaskDesigner:
    """Task CRUD and resolution against the currently loaded POIs."""

    def __init__(
        self,
        path: Path = DEFAULT_CONFIG_PATH,
        slam: SLAM | None = None,
        body_actions=None,
        speech=None,
    ) -> None:
        self.repository = ConciergeTaskRepository(path)
        self.slam = slam or SLAM()
        self.body_actions = body_actions
        self.speech = speech

    def list_tasks(self):
        return [task.to_dict() for task in self.repository.list()]

    def get_task(self, task_id):
        return self.repository.get(task_id).to_dict()

    def save_task(self, name, stops, task_id=None):
        """Save a task and prepare every stop's speech now, while designing."""
        self._validate_stop_actions(stops)
        task = self.repository.save(name, stops, task_id).to_dict()
        return {**task, "speech": self.prepare_speech(task)}

    def prepare_speech(self, task):
        """Synthesize missing stop speech into data/tts; tours only play it back."""
        if self.speech is None:
            return self.speech_status(task)
        failures = []
        for index, stop in enumerate(task["stops"], start=1):
            if stop.get("audio"):
                continue
            try:
                self.speech.ensure(stop["content"])
            except Exception as error:
                failures.append(
                    {"stop_index": index, "poi_name": stop["poi_name"], "error": str(error)}
                )
        status = self.speech_status(task)
        status["errors"] = failures
        return status

    def speech_status(self, task):
        """Readiness and the length in seconds of every stop's prepared speech."""
        stops = task["stops"]
        durations = [
            None if self.speech is None else self.speech.stop_duration(stop) for stop in stops
        ]
        missing = [
            {"stop_index": index, "poi_name": stop["poi_name"]}
            for index, (stop, duration) in enumerate(zip(stops, durations, strict=True), start=1)
            if duration is None
        ]
        return {
            "ready": not missing,
            "cached": len(stops) - len(missing),
            "missing": missing,
            "durations": durations,
            "total_duration": round(sum(d for d in durations if d), 1),
        }

    def _validate_stop_actions(self, stops) -> None:
        if not isinstance(stops, list):
            return

        def actions_for(stop):
            if not isinstance(stop, dict):
                return []
            actions = stop.get("actions")
            if actions is None:
                legacy_action = stop.get("action")
                return [] if legacy_action is None else [legacy_action]
            return actions if isinstance(actions, list) else []

        action_ids = {
            str(action.get("action_id") or "").strip()
            for stop in stops
            for action in actions_for(stop)
            if isinstance(action, dict)
        }
        if "" in action_ids:
            raise ValueError("Tianyi arm action IDs cannot be empty")
        if self.body_actions is None:
            return
        available = {
            str(action["action_id"])
            for action in self.body_actions.list_actions()
            if action.get("ready", True) is True
        }
        unavailable = sorted(action_ids - available)
        if unavailable:
            raise ValueError("Unavailable Tianyi arm actions: " + ", ".join(unavailable))

    def delete_task(self, task_id):
        self.repository.delete(task_id)

    def available_pois(self):
        pois = []
        for poi in self.slam.poi.get_all():
            poi_id = str(poi.get("id") or "").strip()
            name = str(poi.get("metadata", {}).get("display_name") or "").strip()
            if poi_id and name:
                pois.append(
                    {
                        "id": poi_id,
                        "name": name,
                        "type": poi.get("metadata", {}).get("type", ""),
                    }
                )
        return sorted(pois, key=lambda item: item["name"].casefold())

    def available_actions(self):
        if self.body_actions is None:
            return []
        return sorted(
            self.body_actions.list_actions(),
            key=lambda item: str(item.get("label") or item.get("action_id")).casefold(),
        )

    def resolve_task(self, task):
        task = ConciergeTask.from_dict(task, require_stops=True).to_dict()
        current_pois = {str(poi.get("id")): poi for poi in self.slam.poi.get_all()}
        resolved_stops = []
        for stop in task["stops"]:
            poi = current_pois.get(stop["poi_id"])
            if poi is None:
                raise LookupError(f"POI '{stop['poi_name']}' is not present in the current map")
            current_name = str(poi.get("metadata", {}).get("display_name") or "").strip()
            if not current_name:
                raise ValueError(f"POI has no display name: {stop['poi_id']}")
            resolved_stops.append({**stop, "poi_name": current_name, "poi": poi})
        return {**task, "stops": resolved_stops}
