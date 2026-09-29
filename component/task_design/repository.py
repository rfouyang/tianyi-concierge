from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from ..common.concierge_task import ConciergeTask, _uuid


class ConciergeTaskRepository:
    """Atomic JSON persistence for saved tasks."""

    SCHEMA_VERSION = 1

    def __init__(self, path) -> None:
        self.path = Path(path)
        self.file_lock = threading.RLock()

    def _empty_document(self) -> dict:
        return {"version": self.SCHEMA_VERSION, "tasks": []}

    def _validate_document(self, document: dict) -> list[ConciergeTask]:
        if not isinstance(document, dict):
            raise ValueError("Task configuration must be a JSON object")
        if document.get("version") != self.SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported task configuration version: {document.get('version')}"
            )
        if not isinstance(document.get("tasks"), list):
            raise ValueError("Task configuration 'tasks' must be a list")

        tasks = [ConciergeTask.from_dict(task) for task in document["tasks"]]
        ids = [task.id for task in tasks]
        names = [task.name.casefold() for task in tasks]
        if len(ids) != len(set(ids)):
            raise ValueError("Task configuration contains duplicate task IDs")
        if len(names) != len(set(names)):
            raise ValueError("Task configuration contains duplicate task names")
        return tasks

    def _read(self) -> list[ConciergeTask]:
        with self.file_lock:
            if not self.path.exists() or self.path.stat().st_size == 0:
                return []
            try:
                document = json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid task configuration JSON: {self.path}") from exc
            return self._validate_document(document)

    def _write(self, tasks: list[ConciergeTask]) -> None:
        document = {
            "version": self.SCHEMA_VERSION,
            "tasks": [task.to_dict() for task in tasks],
        }
        self._validate_document(document)
        content = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
        with self.file_lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = self.path.with_suffix(self.path.suffix + ".tmp")
            temporary_path.write_text(content, encoding="utf-8")
            os.replace(temporary_path, self.path)

    def list(self) -> list[ConciergeTask]:
        return self._read()

    def get(self, task_id: str) -> ConciergeTask:
        expected_id = _uuid(task_id, "Task ID")
        task = next((task for task in self._read() if task.id == expected_id), None)
        if task is None:
            raise LookupError(f"Task not found: {expected_id}")
        return task

    def save(self, name, stops, task_id=None) -> ConciergeTask:
        name = str(name or "").strip()
        if not name:
            raise ValueError("Task name cannot be empty")
        if not isinstance(stops, list) or not stops:
            raise ValueError("Add at least one POI to the task")

        with self.file_lock:
            tasks = self._read()
            expected_id = _uuid(task_id, "Task ID") if task_id else str(uuid4())
            existing = next((task for task in tasks if task.id == expected_id), None)
            if task_id and existing is None:
                raise LookupError(f"Task not found: {expected_id}")
            if any(
                task.id != expected_id and task.name.casefold() == name.casefold()
                for task in tasks
            ):
                raise ValueError(f"A task named '{name}' already exists")

            now = datetime.now(timezone.utc).isoformat()
            task = ConciergeTask.from_dict(
                {
                    "id": expected_id,
                    "name": name,
                    "stops": stops,
                    "created_at": existing.created_at if existing else now,
                    "updated_at": now,
                },
                require_stops=True,
            )
            self._write([current for current in tasks if current.id != expected_id] + [task])
            return task

    def delete(self, task_id: str) -> None:
        with self.file_lock:
            tasks = self._read()
            remaining = [task for task in tasks if task.id != str(task_id)]
            if len(remaining) == len(tasks):
                raise LookupError(f"Task not found: {task_id}")
            self._write(remaining)
